"""Write run outputs, scenario comparisons and summary tables."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import rasterize

from .config import Config
from .grid import Grid


def run_dir(cfg: Config, run_id: str):
    return cfg.outputs_dir / run_id


def default_baseline_id(cfg: Config) -> str:
    return cfg.scenarios[0]["id"]


def result_scale(cfg: Config, run, res, grid: Grid) -> dict:
    """Reference values for the 0 to 100 scale, taken from the baseline run.

    The baseline run sets them (the chosen percentile of its non-zero impact); every other
    run reuses them so all runs share one scale. If the baseline has not been run yet, the
    run's own values are used and a warning is recorded.
    """
    f = cfg.outputs_dir / "result_scale.json"
    pct = cfg.project["model"].get("result_normalization_percentile", 95)

    def ref(a):
        v = a[grid.mask & (a > 0)] if a is not None else np.array([])
        return float(np.percentile(v, pct)) if v.size else 0.0

    if run.run_id == default_baseline_id(cfg):
        scale = {"percentile": pct, "impact": ref(res.total), "rarity_adjusted": ref(res.rarity_adjusted),
                 "from_run": run.run_id}
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(scale, indent=2))
        return scale
    if f.exists():
        return json.loads(f.read_text())
    import logging
    logging.getLogger("rscia").warning("Baseline not run yet: 0 to 100 scale taken from %s itself", run.run_id)
    return {"percentile": pct, "impact": ref(res.total), "rarity_adjusted": ref(res.rarity_adjusted),
            "from_run": run.run_id}


def write_run_outputs(cfg: Config, grid: Grid, run, res, missing: list[str]) -> None:
    from .model import scale_0_100

    d = run_dir(cfg, run.run_id)
    d.mkdir(parents=True, exist_ok=True)

    scale = result_scale(cfg, run, res, grid)
    grid.write(d / "impact_index.tif", scale_0_100(res.total, scale["impact"]))
    if res.rarity_adjusted is not None:
        grid.write(d / "impact_rarity_adjusted.tif", res.rarity_adjusted)
        grid.write(d / "impact_rarity_adjusted_index.tif", scale_0_100(res.rarity_adjusted, scale["rarity_adjusted"]))

    grid.write(d / "impact_total.tif", res.total)
    grid.write(d / "impact_by_pressure.tif", res.by_pressure, res.pressure_ids)
    grid.write(d / "impact_by_component.tif", res.by_component, res.component_ids)
    grid.write(d / "confidence.tif", res.confidence)
    grid.write(d / "component_count.tif", res.component_count)

    pct = cfg.project["model"].get("hotspot_percentile", 90)
    vals = res.total[grid.mask & (res.total > 0)]
    thr = float(np.percentile(vals, pct)) if vals.size else np.inf
    hot = np.where(res.total >= thr, 1.0, 0.0).astype("float32")
    grid.write(d / "hotspots.tif", hot)

    # summary tables
    total = float(np.nansum(res.total))
    pt = res.pressure_totals()
    kind = {p["id"]: p.get("kind", "local") for p in cfg.pressures}
    names = {p["id"]: p["name"] for p in cfg.pressures}
    sp = pd.DataFrame({"pressure": pt.index, "name": [names[i] for i in pt.index],
                       "kind": [kind[i] for i in pt.index], "impact": pt.values})
    sp["share_pct"] = 100 * sp["impact"] / total if total else 0.0
    sp.sort_values("impact", ascending=False).to_csv(d / "summary_by_pressure.csv", index=False)

    ct = res.component_totals()
    group = {c["id"]: c["group"] for c in cfg.components}
    cn = {c["id"]: c["name"] for c in cfg.components}
    sc = pd.DataFrame({"component": ct.index, "name": [cn[i] for i in ct.index],
                       "group": [group[i] for i in ct.index], "impact": ct.values})
    sc["share_pct"] = 100 * sc["impact"] / total if total else 0.0
    sc.sort_values("impact", ascending=False).to_csv(d / "summary_by_component.csv", index=False)
    sc.groupby("group")[["impact", "share_pct"]].sum().sort_values("impact", ascending=False).to_csv(d / "summary_by_group.csv")

    _planning_unit_summary(cfg, grid, res, d)
    _region_summary(cfg, grid, res, d, scale)

    info = {
        "run_id": run.run_id, "scenario": run.scenario_id, "description": run.description,
        "ssp": run.ssp, "horizon": run.horizon,
        "development_changes": len(run.development),
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cells": int(grid.mask.sum()), "total_impact": total,
        "mean_impact": float(np.nanmean(res.total)) if grid.mask.any() else 0.0,
        "hotspot_threshold": thr if np.isfinite(thr) else None,
        "local_share_pct": float(sp.loc[sp.kind == "local", "share_pct"].sum()),
        "climate_share_pct": float(sp.loc[sp.kind == "climate", "share_pct"].sum()),
        "scale_0_100": scale,
        "mean_impact_index": float(np.nanmean(100 * res.total / scale["impact"])) if scale["impact"] else None,
        "missing_inputs": missing,
    }
    (d / "run_info.json").write_text(json.dumps(info, indent=2))


def _region_summary(cfg: Config, grid: Grid, res, d, scale) -> None:
    """Impact totals, means and top pressures per assessment region."""
    from .pipeline import load_regions

    if not cfg.regions:
        return
    reg = load_regions(cfg, grid)
    names = {p["id"]: p["name"] for p in cfg.pressures}
    rows = []
    for r in [{"id": 0, "name": "Outside regions"}] + cfg.regions:
        m = (reg == r["id"]) & grid.mask
        if not m.any():
            continue
        tot = float(np.nansum(res.total[m]))
        byp = {p: float(np.nansum(res.by_pressure[i][m])) for i, p in enumerate(res.pressure_ids)}
        top = sorted(byp, key=byp.get, reverse=True)[:3]
        rows.append({"region": r["name"], "cells": int(m.sum()), "impact_total": tot,
                     "share_of_eez_pct": 100 * tot / float(np.nansum(res.total)) if np.nansum(res.total) else 0,
                     "mean_impact_index": float(np.nanmean(100 * res.total[m] / scale["impact"])) if scale["impact"] else None,
                     "mean_rarity_adjusted": float(np.nanmean(res.rarity_adjusted[m])) if res.rarity_adjusted is not None else None,
                     "top_pressures": "; ".join(f"{names[t]} ({100 * byp[t] / tot:.0f}%)" for t in top if tot)})
    pd.DataFrame(rows).to_csv(d / "summary_by_region.csv", index=False)


def _planning_unit_summary(cfg: Config, grid: Grid, res, d) -> None:
    f = cfg.project["paths"].get("planning_units_file")
    if not f or not cfg.path(f).exists():
        return
    field = cfg.project["paths"].get("planning_units_field", "name")
    pu = gpd.read_file(cfg.path(f)).to_crs(grid.crs).reset_index(drop=True)
    ids = rasterize([(g, i + 1) for i, g in enumerate(pu.geometry)], out_shape=grid.shape,
                    transform=grid.transform, fill=0, dtype="int32")
    rows = []
    for i, r in pu.iterrows():
        m = (ids == i + 1) & grid.mask
        if not m.any():
            continue
        row = {"unit": r[field], "cells": int(m.sum()), "impact_total": float(np.nansum(res.total[m])),
               "impact_mean": float(np.nanmean(res.total[m]))}
        for j, p in enumerate(res.pressure_ids):
            row[f"p_{p}"] = float(np.nansum(res.by_pressure[j][m]))
        rows.append(row)
    pd.DataFrame(rows).to_csv(d / "summary_by_planning_unit.csv", index=False)


def _rarity_change(grid: Grid, a_dir, b_dir) -> dict:
    fa, fb = a_dir / "impact_rarity_adjusted.tif", b_dir / "impact_rarity_adjusted.tif"
    if not (fa.exists() and fb.exists()):
        return {}
    ra, rb = np.nansum(grid.read(fa, "nearest")), np.nansum(grid.read(fb, "nearest"))
    return {"rarity_adjusted_change_pct": float(100 * (ra - rb) / rb) if rb else np.nan}


def compare(cfg: Config, grid: Grid, run_id: str, baseline_id: str | None = None) -> pd.DataFrame:
    """Difference between a run and the baseline: map and change tables."""
    import rasterio

    baseline_id = baseline_id or default_baseline_id(cfg)

    a_dir, b_dir = run_dir(cfg, run_id), run_dir(cfg, baseline_id)
    for x in (a_dir, b_dir):
        if not (x / "impact_total.tif").exists():
            raise FileNotFoundError(f"Run outputs not found: {x}")
    a = grid.read(a_dir / "impact_total.tif", "nearest")
    b = grid.read(b_dir / "impact_total.tif", "nearest")
    diff = a - b
    out = cfg.outputs_dir / "comparisons" / f"{run_id}_vs_{baseline_id}"
    out.mkdir(parents=True, exist_ok=True)
    grid.write(out / "impact_difference.tif", diff)
    with np.errstate(invalid="ignore", divide="ignore"):
        rel = np.where(b > 0, 100 * diff / b, np.nan)
    grid.write(out / "impact_change_pct.tif", rel)

    def band_totals(path):
        with rasterio.open(path) as src:
            names = list(src.descriptions)
            arr = src.read(masked=True)
        return pd.Series([float(arr[i].sum()) for i in range(arr.shape[0])], index=names)

    tables = {}
    for kind in ("pressure", "component"):
        ta = band_totals(a_dir / f"impact_by_{kind}.tif")
        tb = band_totals(b_dir / f"impact_by_{kind}.tif")
        t = pd.DataFrame({"baseline": tb, "scenario": ta})
        t["change"] = t.scenario - t.baseline
        t["change_pct"] = np.where(t.baseline > 0, 100 * t.change / t.baseline.replace(0, np.nan), np.nan)
        t.index.name = kind
        t.sort_values("change", ascending=False).to_csv(out / f"change_by_{kind}.csv")
        tables[kind] = t

    summary = pd.DataFrame([{
        "run": run_id, "baseline": baseline_id,
        "total_baseline": float(np.nansum(b)), "total_scenario": float(np.nansum(a)),
        "change_pct": float(100 * (np.nansum(a) - np.nansum(b)) / np.nansum(b)) if np.nansum(b) else np.nan,
        "cells_increased": int(np.nansum(diff > 1e-6)), "cells_decreased": int(np.nansum(diff < -1e-6)),
        "max_cell_increase": float(np.nanmax(diff)) if np.isfinite(diff).any() else 0.0,
        **_rarity_change(grid, a_dir, b_dir),
    }])
    summary.to_csv(out / "summary.csv", index=False)
    return summary

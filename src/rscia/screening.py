"""Screen a single development application against the cumulative baseline.

A project file (YAML) lists the pressures the project adds, in the same form as the
development changes in config/scenarios.yaml:

    id: APP-2026-014
    name: Example desalination plant
    applicant: Example Water Company
    changes:
      - {pressure: desal_brine, mode: add_sources, file: data/applications/APP-2026-014/plant.gpkg}
      - {pressure: chemical_discharge, mode: add_sources, file: data/applications/APP-2026-014/plant.gpkg}

The project is run on top of the baseline (S0). The report states what the project adds,
where, to which ecosystem components, and how loaded that area already is.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import yaml

from .config import Config
from .grid import Grid
from .pipeline import RunSpec, load_components, run_scenario
from .reporting import run_dir

DEFAULT_FOCAL = ["coral_shallow", "coral_mesophotic", "seagrass", "mangrove", "turtle_nesting",
                 "green_turtle", "hawksbill_turtle", "dugong"]


def load_project(path: Path) -> dict:
    p = yaml.safe_load(Path(path).read_text())
    for k in ("id", "changes"):
        if k not in p:
            raise ValueError(f"Project file needs '{k}'")
    return p


def _bands(path):
    with rasterio.open(path) as src:
        return list(src.descriptions), src.read(masked=True).filled(np.nan)


def screen(cfg: Config, grid: Grid, project_file: Path, baseline_id: str = "S0_baseline") -> Path:
    proj = load_project(project_file)
    base_dir = run_dir(cfg, baseline_id)
    if not (base_dir / "impact_total.tif").exists():
        raise FileNotFoundError("Run the baseline first: rscia run --scenario S0_baseline")
    for ch in proj["changes"]:
        if ch["pressure"] not in cfg.pressure_ids:
            raise ValueError(f"Unknown pressure '{ch['pressure']}' in project file")

    run_id = f"screening/{proj['id']}"
    run = RunSpec(run_id, "screening", proj.get("name", proj["id"]), proj["changes"])
    res = run_scenario(cfg, run, grid)
    out = run_dir(cfg, run_id)

    base = grid.read(base_dir / "impact_total.tif", "nearest")
    added = res.total - base
    grid.write(out / "added_impact.tif", added)
    zone = grid.mask & (added > 1e-6)
    n_zone = int(zone.sum())
    km2 = (grid.resolution / 1000) ** 2

    # context: how loaded the zone already is
    base_vals = base[grid.mask]
    zone_base_mean = float(np.nanmean(base[zone])) if n_zone else np.nan
    pct_rank = float((base_vals < zone_base_mean).mean() * 100) if n_zone else np.nan
    hot_thr = np.nanpercentile(base_vals[base_vals > 0], cfg.project["model"].get("hotspot_percentile", 90))
    hot_cells = int((zone & (base >= hot_thr)).sum())

    # pressures and components
    pn, pb = _bands(base_dir / "impact_by_pressure.tif")
    cn, cb = _bands(base_dir / "impact_by_component.tif")
    by_p = pd.DataFrame({"pressure": res.pressure_ids,
                         "added_impact": [float(np.nansum(res.by_pressure[i][zone] - pb[pn.index(p)][zone])) for i, p in enumerate(res.pressure_ids)]})
    by_p = by_p[by_p.added_impact.abs() > 1e-6].sort_values("added_impact", ascending=False)
    names = {c["id"]: c["name"] for c in cfg.components}
    missing: list = []
    E = load_components(cfg, grid, missing)
    focal = cfg.project["model"].get("focal_components", DEFAULT_FOCAL)
    rows = []
    for j, c in enumerate(res.component_ids):
        add = float(np.nansum(res.by_component[j][zone] - cb[cn.index(c)][zone]))
        area = float(np.nansum(E[c][zone]) * km2)
        if area <= 0 and add <= 0:
            continue
        rows.append({"component": c, "name": names[c], "focal": c in focal,
                     "area_in_zone_km2": round(area, 2),
                     "baseline_impact_in_zone": float(np.nansum(cb[cn.index(c)][zone])),
                     "added_impact": add})
    by_c = pd.DataFrame(rows).sort_values(["focal", "added_impact"], ascending=[False, False]) if rows else pd.DataFrame()

    # survey sites in the zone
    sites_txt = "No coral survey file loaded."
    sf = cfg.path(cfg.project["paths"]["surveys_file"])
    if sf.exists():
        from .validation import load_surveys
        s = load_surveys(cfg, grid)
        s = s[s.in_grid]
        inz = s[zone[s.row, s.col]]
        if len(inz):
            cc = inz.get("live_coral_cover_pct")
            ids = list(inz.site_id.astype(str))
            shown = ", ".join(ids[:10]) + (f" and {len(ids) - 10} more (see added_by_site.csv)" if len(ids) > 10 else "")
            inz.drop(columns=["row", "col", "in_grid"]).to_csv(out / "added_by_site.csv", index=False)
            sites_txt = f"{len(inz)} survey site(s) in the zone of influence: {shown}."
            if cc is not None and cc.notna().any():
                sites_txt += f" Mean live coral cover {cc.mean():.1f}% (all sites: {s.live_coral_cover_pct.mean():.1f}%)."
        else:
            sites_txt = "No coral survey sites in the zone of influence."

    by_p.to_csv(out / "added_by_pressure.csv", index=False)
    if not by_c.empty:
        by_c.to_csv(out / "added_by_component.csv", index=False)

    total_base = float(np.nansum(base))
    total_add = float(np.nansum(added[zone]))
    L = [f"# Screening report: {proj.get('name', proj['id'])}", "",
         f"Application: {proj['id']}" + (f" | Applicant: {proj['applicant']}" if proj.get("applicant") else ""),
         f"Date: {date.today().isoformat()} | Baseline: {baseline_id} | Model version: RS-CIA",
         "", "## Summary", "",
         f"- Zone of influence: {n_zone} cells ({n_zone * km2:,.0f} km2) where the project raises impact.",
         f"- Added impact: {total_add:,.2f}, equal to {100 * total_add / total_base:.3f}% of the EEZ baseline total"
         + (f" and {100 * total_add / np.nansum(base[zone]):.1f}% of the baseline within the zone." if n_zone and np.nansum(base[zone]) > 0 else "."),
         f"- Existing load: mean baseline impact in the zone is higher than in {pct_rank:.0f}% of EEZ cells; "
         f"{hot_cells} zone cells are already baseline hotspots (top 10%).",
         f"- {sites_txt}", "", "## Added impact by pressure", "", "| Pressure | Added impact |", "|---|---|"]
    for _, r in by_p.iterrows():
        L.append(f"| {cfg.pressure(r.pressure)['name']} | {r.added_impact:,.2f} |")
    L += ["", "## Ecosystem components in the zone", "",
          "Focal components (coral, seagrass, mangrove, turtles, dugong) are listed first.", "",
          "| Component | Focal | Area in zone (km2) | Baseline impact | Added impact |", "|---|---|---|---|---|"]
    for _, r in by_c.iterrows():
        L.append(f"| {r['name']} | {'yes' if r.focal else ''} | {r.area_in_zone_km2:,.1f} | {r.baseline_impact_in_zone:,.2f} | {r.added_impact:,.2f} |")
    if missing:
        L += ["", "## Missing inputs", "", "These layers were missing and set to zero, so the report may understate impact:", ""]
        L += [f"- {m}" for m in sorted(set(missing))]
    L += ["", "## Files", "",
          "- added_impact.tif: map of the impact the project adds",
          "- impact_total.tif: cumulative impact with the project",
          "- added_by_pressure.csv, added_by_component.csv", "",
          "This screening uses the RS-CIA cumulative impact model. It supports, and does not replace,",
          "the review of the project's EIA."]
    (out / "screening_report.md").write_text("\n".join(L) + "\n")
    return out / "screening_report.md"

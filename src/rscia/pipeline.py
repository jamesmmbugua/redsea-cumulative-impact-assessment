"""Prepare layers and run scenarios."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from . import layers
from .config import Config
from .grid import Grid, build_grid, save_template
from .model import ImpactResult, commonness, cumulative_impact

log = logging.getLogger("rscia")


# ---------------------------------------------------------------- grid

def make_grid(cfg: Config) -> Grid:
    g = cfg.project["grid"]
    eez = gpd.read_file(cfg.path(g["eez_file"]))
    flt = g.get("eez_filter")
    if flt:
        eez = eez[eez[flt["field"]].isin(flt["values"])]
        if eez.empty:
            raise ValueError(f"EEZ filter matched nothing: {flt}")
    land = gpd.read_file(cfg.path(g["coastline_file"])) if g.get("coastline_file") and cfg.path(g["coastline_file"]).exists() else None
    clip = gpd.read_file(cfg.path(g["clip_file"])) if g.get("clip_file") else None
    grid = build_grid(eez, g["crs"], g["resolution_m"], land, g.get("coastal_buffer_m", 0), clip)
    save_template(grid, cfg.path(g["template_raster"]))
    log.info("Grid %d x %d, %d cells in study area", grid.width, grid.height, int(grid.mask.sum()))
    make_regions(cfg, grid)
    return grid


def make_regions(cfg: Config, grid: Grid) -> np.ndarray:
    """Rasterize the assessment regions (Northern, Central, Southern) to the grid.

    Each cell gets the id of the region covering its centre; 0 where no region applies.
    """
    from rasterio.features import rasterize

    rcfg = cfg.project.get("regions") or {}
    out = np.zeros(grid.shape, dtype="float32")
    f = cfg.path(rcfg.get("file"))
    if f is None or not f.exists():
        log.warning("No regions file (%s); the default sensitivity matrix is used everywhere", f)
    else:
        gdf = gpd.read_file(f).to_crs(grid.crs)
        code_to_id = {r["code"]: int(r["id"]) for r in cfg.regions}
        field = rcfg.get("field", "region")
        shapes = []
        for geom, code in zip(gdf.geometry, gdf[field]):
            if code not in code_to_id:
                raise ValueError(f"Region '{code}' in {f} is not listed in project.yaml regions")
            shapes.append((geom, code_to_id[code]))
        out = rasterize(shapes, out_shape=grid.shape, transform=grid.transform, fill=0,
                        dtype="int16").astype("float32")
        # Study cells not covered (e.g. the landward coastal strip, since MEOW stops at the
        # coast) take the region of the nearest covered cell.
        gaps = grid.mask & (out == 0)
        if gaps.any() and (out > 0).any():
            from scipy import ndimage
            _, (ri, ci) = ndimage.distance_transform_edt(out == 0, return_indices=True)
            out[gaps] = out[ri[gaps], ci[gaps]]
        for r in cfg.regions:
            log.info("Region %s: %d cells", r["name"], int(((out == r["id"]) & grid.mask).sum()))
        if ((out == 0) & grid.mask).any():
            log.warning("%d study cells fall outside all regions and use the default matrix",
                        int(((out == 0) & grid.mask).sum()))
    out[~grid.mask] = np.nan
    if rcfg.get("raster"):
        grid.write(cfg.path(rcfg["raster"]), out)
    return out


def load_regions(cfg: Config, grid: Grid) -> np.ndarray:
    rcfg = cfg.project.get("regions") or {}
    f = cfg.path(rcfg.get("raster"))
    if f is not None and f.exists():
        r = grid.read(f, resampling="nearest", fill=0)
        return np.nan_to_num(r).astype("int16")
    return np.nan_to_num(make_regions(cfg, grid)).astype("int16")


def load_grid(cfg: Config) -> Grid:
    p = cfg.path(cfg.project["grid"]["template_raster"])
    if not p.exists():
        raise FileNotFoundError(f"Grid template not found: {p}. Run `rscia build-grid` first.")
    return Grid.from_template(p)


# ---------------------------------------------------------------- run specs

@dataclass
class RunSpec:
    run_id: str
    scenario_id: str
    description: str
    development: list = field(default_factory=list)
    ssp: str | None = None
    horizon: str | None = None


def expand_runs(cfg: Config) -> list[RunSpec]:
    runs = []
    for sc in cfg.scenarios:
        dev = sc.get("development") or []
        clim = sc.get("climate") or [None]
        for c in clim:
            if c is None:
                runs.append(RunSpec(sc["id"], sc["id"], sc.get("description", ""), dev))
            else:
                rid = f"{sc['id']}_{c['ssp']}_{c['horizon']}"
                runs.append(RunSpec(rid, sc["id"], sc.get("description", ""), dev, c["ssp"], str(c["horizon"])))
    return runs


def climate_futures(cfg: Config) -> list[tuple[str, str]]:
    seen = []
    for r in expand_runs(cfg):
        if r.ssp and (r.ssp, r.horizon) not in seen:
            seen.append((r.ssp, r.horizon))
    ref = cfg.bio_oracle.get("reference")
    if ref and (ref["ssp"], str(ref["horizon"])) not in seen:
        seen.append((ref["ssp"], str(ref["horizon"])))
    return seen


# ---------------------------------------------------------------- pressures

def _read_vector(path: Path) -> gpd.GeoDataFrame | None:
    return gpd.read_file(path) if path is not None and path.exists() else None


def raw_pressure(cfg: Config, grid: Grid, p: dict, extra: list[Path] | None = None,
                 missing: list | None = None) -> np.ndarray:
    """Raw (un-normalized) intensity for a local or direct pressure."""
    m = p["method"]
    src = cfg.path(p.get("sources"))
    if m in ("decay", "footprint"):
        frames = []
        base = _read_vector(src)
        if base is None:
            if missing is not None:
                missing.append(str(src))
        else:
            frames.append(base)
        for e in extra or []:
            g = _read_vector(e)
            if g is None:
                if missing is not None:
                    missing.append(str(e))
                continue
            if frames:
                g = g.to_crs(frames[0].crs)
            frames.append(g)
        gdf = pd.concat(frames, ignore_index=True) if frames else None
        if gdf is not None:
            gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=frames[0].crs)
        if m == "decay":
            return layers.decay_from_points(gdf, grid, p.get("decay_km", 1), p.get("weight_field"))
        return layers.footprint(gdf, grid, p.get("decay_km", 0))
    if m in ("density", "direct"):
        if src is None or not src.exists():
            if missing is not None:
                missing.append(str(src))
            return grid.empty()
        return grid.read(src, resampling="bilinear")
    raise ValueError(f"raw_pressure does not handle method {m}")


def _bio_oracle_path(cfg: Config, variable: str, ssp: str | None = None, horizon: str | None = None) -> Path:
    bo = cfg.bio_oracle
    d = cfg.path(bo["raw_dir"])
    if ssp is None:
        return d / bo["present_pattern"].format(variable=variable)
    return d / bo["future_pattern"].format(variable=variable, ssp=ssp, horizon=horizon)


def processed_dir(cfg: Config) -> Path:
    return cfg.path(cfg.project["paths"]["pressures_dir"])


def prepare_pressures(cfg: Config, grid: Grid | None = None) -> dict:
    """Build baseline pressure layers and normalization references."""
    grid = grid or load_grid(cfg)
    norm = cfg.project["normalization"]
    out = processed_dir(cfg)
    refs, missing = {}, []

    for p in cfg.pressures:
        if p["method"] == "climate_delta":
            continue
        raw = raw_pressure(cfg, grid, p, missing=missing)
        tdir = cfg.pressure_dir(p["id"])
        grid.write(tdir / "intensity" / f"{p['id']}.tif", raw)
        n, ref = layers.normalize(raw, None, norm["reference_percentile"], p.get("log_transform", False), norm.get("clip_max", 1.0))
        grid.write(tdir / f"{p['id']}.tif", n)
        refs[p["id"]] = ref

    # climate deltas for every future used by a scenario
    clim = [p for p in cfg.pressures if p["method"] == "climate_delta"]
    futures = climate_futures(cfg)
    ref_f = cfg.bio_oracle.get("reference")
    for p in clim:
        v = p["variable"]
        present_path = _bio_oracle_path(cfg, v)
        if not present_path.exists():
            missing.append(str(present_path))
            continue
        present = grid.read(present_path, resampling="bilinear", fill=None)
        deltas = {}
        for ssp, hz in futures:
            fp = _bio_oracle_path(cfg, v, ssp, hz)
            if not fp.exists():
                missing.append(str(fp))
                continue
            d = layers.climate_delta(present, grid.read(fp, resampling="bilinear", fill=None), p["direction"])
            d[np.isnan(d) & grid.mask] = 0
            deltas[(ssp, hz)] = d
            grid.write(cfg.pressure_dir(p["id"]) / "intensity" / f"{p['id']}_{ssp}_{hz}.tif", d)
        if not deltas:
            continue
        key = (ref_f["ssp"], str(ref_f["horizon"])) if ref_f else None
        ref_arr = deltas.get(key) if key else None
        if ref_arr is None:  # fall back to the largest change available
            ref_arr = max(deltas.values(), key=lambda a: np.nanmax(a))
        _, ref = layers.normalize(ref_arr, None, norm["reference_percentile"], p.get("log_transform", False))
        refs[p["id"]] = ref
        for (ssp, hz), d in deltas.items():
            n, _ = layers.normalize(d, ref, log_transform=p.get("log_transform", False), clip_max=norm.get("clip_max", 1.0))
            grid.write(cfg.pressure_dir(p["id"]) / f"{p['id']}_{ssp}_{hz}.tif", n)

    (out / "references.json").write_text(json.dumps({"references": refs, "missing_inputs": sorted(set(missing))}, indent=2))
    for m in sorted(set(missing)):
        log.warning("Missing input (layer set to zero): %s", m)
    return refs


# ---------------------------------------------------------------- run

def load_components(cfg: Config, grid: Grid, missing: list) -> dict[str, np.ndarray]:
    out = {}
    for c in cfg.components:
        f = cfg.component_file(c["id"])
        if f.exists():
            a = grid.read(f, resampling="bilinear")
            out[c["id"]] = np.clip(a, 0, 1)
        else:
            missing.append(str(f))
            out[c["id"]] = grid.empty()
    return out


def scenario_pressures(cfg: Config, grid: Grid, run: RunSpec, missing: list) -> dict[str, np.ndarray]:
    out_dir = processed_dir(cfg)
    ref_file = out_dir / "references.json"
    if not ref_file.exists():
        raise FileNotFoundError("Pressure layers not prepared. Run `rscia prepare` first.")
    refs = json.loads(ref_file.read_text())["references"]
    norm = cfg.project["normalization"]
    scen_clip = norm.get("scenario_clip_max", norm.get("clip_max", 1.0))

    changes: dict[str, list] = {}
    for ch in run.development:
        changes.setdefault(ch["pressure"], []).append(ch)

    P = {}
    for p in cfg.pressures:
        pid = p["id"]
        if p["method"] == "climate_delta":
            if run.ssp is None:
                P[pid] = grid.empty()  # present climate: no change
            else:
                f = cfg.pressure_dir(pid) / f"{pid}_{run.ssp}_{run.horizon}.tif"
                if f.exists():
                    P[pid] = grid.read(f, resampling="nearest")
                else:
                    missing.append(str(f))
                    P[pid] = grid.empty()
            continue

        base_norm = cfg.pressure_dir(pid) / f"{pid}.tif"
        if pid not in changes:
            P[pid] = grid.read(base_norm, resampling="nearest") if base_norm.exists() else grid.empty()
            continue

        # apply development changes on raw intensity, then normalize with baseline reference
        raw_f = cfg.pressure_dir(pid) / "intensity" / f"{pid}.tif"
        raw = grid.read(raw_f, resampling="nearest") if raw_f.exists() else grid.empty()
        raw_base = raw.copy()
        add_sources = [cfg.path(c["file"]) for c in changes[pid] if c["mode"] == "add_sources"]
        if add_sources:
            raw = raw_pressure(cfg, grid, p, extra=add_sources, missing=missing)
        for c in changes[pid]:
            f = cfg.path(c["file"])
            if c["mode"] in ("replace_raster", "add_raster"):
                if not f.exists():
                    missing.append(str(f))
                    continue
                r = grid.read(f, resampling="bilinear")
                raw = r if c["mode"] == "replace_raster" else np.nan_to_num(raw) + r
                raw[~grid.mask] = np.nan
        log_t = p.get("log_transform", False)
        if norm.get("scenario_uses_baseline_reference", True) and pid in refs:
            # Baseline layer plus the change, both on the baseline scale. Unchanged cells stay
            # identical to the baseline; increases above today's maximum are not capped
            # unless scenario_clip_max is set.
            ref = refs[pid]
            base_clipped = grid.read(base_norm, resampling="nearest") if base_norm.exists() else grid.empty()
            scen_u, _ = layers.normalize(raw, ref, log_transform=log_t, clip_max=None)
            base_u, _ = layers.normalize(raw_base, ref, log_transform=log_t, clip_max=None)
            val = np.nan_to_num(base_clipped) + (np.nan_to_num(scen_u) - np.nan_to_num(base_u))
            val = np.maximum(val, 0)
            if scen_clip is not None:
                val = np.minimum(val, scen_clip)
            val[~grid.mask] = np.nan
            P[pid] = val.astype("float32")
        else:
            P[pid], _ = layers.normalize(raw, None, norm["reference_percentile"], log_t, scen_clip)
    return P


def run_scenario(cfg: Config, run: RunSpec, grid: Grid | None = None) -> ImpactResult:
    from .reporting import write_run_outputs

    grid = grid or load_grid(cfg)
    missing: list = []
    E = load_components(cfg, grid, missing)
    P = scenario_pressures(cfg, grid, run, missing)
    res = cumulative_impact(
        P, E, cfg.regional, grid.mask,
        pressure_confidence={p["id"]: p.get("data_confidence", 2) for p in cfg.pressures},
        component_confidence={c["id"]: c.get("data_confidence", 2) for c in cfg.components},
        regions=load_regions(cfg, grid),
        rarity=commonness(E, grid.mask),
        rarity_min_share=cfg.project["model"].get("rarity_min_share", 0.0),
    )
    write_run_outputs(cfg, grid, run, res, sorted(set(missing)))
    for m in sorted(set(missing)):
        log.warning("[%s] missing input (set to zero): %s", run.run_id, m)
    log.info("[%s] total impact %.1f", run.run_id, float(np.nansum(res.total)))
    return res

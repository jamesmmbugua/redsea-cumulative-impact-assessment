"""Build a small synthetic study area and run the whole pipeline on it.

The demo checks that the engine works end to end. Every number it produces is synthetic.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import yaml
from pyproj import Transformer
from rasterio.transform import from_origin
from scipy import ndimage
from shapely.geometry import Point, Polygon, box

log = logging.getLogger("rscia")

LON0, LON1, LAT0, LAT1 = 38.55, 39.35, 21.0, 22.0   # area near Jeddah
COAST_LON = 39.15


def _coast_lon(lat):
    return COAST_LON + 0.03 * np.sin((lat - LAT0) * 9)


def _write_4326(path: Path, fn, res=0.05):
    lons = np.arange(LON0 - 0.1, LON1 + 0.1, res) + res / 2
    lats = np.arange(LAT1 + 0.1, LAT0 - 0.1, -res) - res / 2
    LON, LAT = np.meshgrid(lons, lats)
    arr = fn(LON, LAT).astype("float32")
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1,
                       dtype="float32", crs="EPSG:4326",
                       transform=from_origin(LON0 - 0.1, LAT1 + 0.1, res, res), nodata=-9999) as dst:
        dst.write(arr, 1)


def _points(rng, n, lon_range, lat_range, **fields):
    lons = rng.uniform(*lon_range, n)
    lats = rng.uniform(*lat_range, n)
    df = {"geometry": [Point(x, y) for x, y in zip(lons, lats)]}
    for k, (lo, hi) in fields.items():
        df[k] = rng.uniform(lo, hi, n)
    return gpd.GeoDataFrame(df, crs="EPSG:4326")


def _coastal_points(rng, n, **fields):
    lats = rng.uniform(LAT0 + 0.05, LAT1 - 0.05, n)
    lons = _coast_lon(lats) - rng.uniform(0.0, 0.02, n)
    df = {"geometry": [Point(x, y) for x, y in zip(lons, lats)]}
    for k, (lo, hi) in fields.items():
        df[k] = rng.uniform(lo, hi, n)
    return gpd.GeoDataFrame(df, crs="EPSG:4326")


def _coastal_polys(rng, n, size=0.02):
    lats = rng.uniform(LAT0 + 0.05, LAT1 - 0.05, n)
    geoms = []
    for la in lats:
        lo = _coast_lon(la)
        geoms.append(box(lo - size * rng.uniform(0.5, 1.5), la - size / 2, lo + 0.005, la + size / 2))
    return gpd.GeoDataFrame({"geometry": geoms}, crs="EPSG:4326")


def build_demo(root: Path, repo_root: Path, seed: int = 42) -> None:
    rng = np.random.default_rng(seed)
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(repo_root / "config", root / "config")

    # project config for the demo area
    pfile = root / "config" / "project.yaml"
    proj = yaml.safe_load(pfile.read_text())
    bnd_rel = "data/interim/reference/boundaries"
    proj["grid"].update(eez_file=f"{bnd_rel}/eez_demo.gpkg", eez_filter=None,
                        clip_file=None, coastline_file=f"{bnd_rel}/land_demo.gpkg")
    proj["paths"]["surveys_file"] = "data/interim/reference/surveys/coral_surveys.csv"
    proj["paths"]["planning_units_file"] = f"{bnd_rel}/planning_units_demo.gpkg"
    pfile.write_text(yaml.safe_dump(proj, sort_keys=False))

    # synthetic inputs go where the configuration expects the cleaned (interim) files
    bnd = root / bnd_rel
    bnd.mkdir(parents=True, exist_ok=True)
    pdoc = yaml.safe_load((root / "config" / "pressures.yaml").read_text())
    src = {p["id"]: root / p["sources"] for p in pdoc["pressures"] if p.get("sources")}
    for f in src.values():
        f.parent.mkdir(parents=True, exist_ok=True)
    scen = yaml.safe_load((root / "config" / "scenarios.yaml").read_text())
    dev = {c["pressure"]: root / c["file"] for c in scen["planned_development"]}
    for f in dev.values():
        f.parent.mkdir(parents=True, exist_ok=True)
    lats = np.linspace(LAT0, LAT1, 60)
    coast = list(zip(_coast_lon(lats), lats))
    sea = Polygon([(LON0, LAT0)] + coast + [(LON0, LAT1)])
    land = Polygon(coast + [(LON1 + 0.2, LAT1), (LON1 + 0.2, LAT0)])
    gpd.GeoDataFrame({"name": ["Demo EEZ"]}, geometry=[sea], crs="EPSG:4326").to_file(bnd / "eez_demo.gpkg")
    gpd.GeoDataFrame(geometry=[land], crs="EPSG:4326").to_file(bnd / "land_demo.gpkg")
    # three synthetic assessment regions (in the real data these come from MEOW)
    regions = gpd.GeoDataFrame(
        {"region": ["northern", "central", "southern"], "name": ["Northern Red Sea", "Central Red Sea", "Southern Red Sea"]},
        geometry=[box(LON0, 21.65, COAST_LON + 0.1, LAT1), box(LON0, 21.3, COAST_LON + 0.1, 21.65),
                  box(LON0, LAT0, COAST_LON + 0.1, 21.3)], crs="EPSG:4326")
    regions["geometry"] = regions.geometry.intersection(sea)   # stop at the coast, like MEOW
    regions.to_file(root / proj["regions"]["file"])
    # southern matrix differs slightly to exercise the regional matrices
    sm = pd.read_csv(root / "config" / "sensitivity_matrix.csv", index_col=0)
    sm.loc["marine_heatwaves", "coral_shallow"] = 0.8
    sm.to_csv(root / "config" / "sensitivity_matrix_southern.csv")
    proj["model"]["regional_matrices"]["southern"]["matrix"] = "config/sensitivity_matrix_southern.csv"
    pfile.write_text(yaml.safe_dump(proj, sort_keys=False))
    bands = [box(LON0, LAT0 + i * 0.25, LON1, LAT0 + (i + 1) * 0.25) for i in range(4)]
    gpd.GeoDataFrame({"name": ["South", "South-central", "North-central", "North"]}, geometry=bands,
                     crs="EPSG:4326").to_file(bnd / "planning_units_demo.gpkg")

    # pressures (cleaned model inputs)
    _coastal_points(rng, 4, capacity_m3_day=(50_000, 600_000)).to_file(src["desal_brine"])
    _coastal_points(rng, 3, capacity_mw=(200, 1500)).to_file(src["thermal_discharge"])
    _coastal_polys(rng, 6).to_file(src["reclamation"])
    _coastal_points(rng, 5).to_file(src["dredging_sediment"])
    _coastal_points(rng, 6, population_served=(20_000, 900_000)).to_file(src["wastewater_nutrients"])
    _points(rng, 3, (38.9, 39.1), (21.3, 21.6)).to_file(src["oil_spill_risk"])
    _coastal_points(rng, 12, boats=(5, 120)).to_file(src["fishing_artisanal"])
    _coastal_points(rng, 3, production_t_year=(500, 8000)).to_file(src["aquaculture"])
    _coastal_points(rng, 15, visitors_year=(1_000, 80_000)).to_file(src["tourism_diving"])
    lane = lambda lon, lat: 1000 * np.exp(-((lon - 38.75) / 0.06) ** 2) + rng.gamma(1, 5, lon.shape)
    _write_4326(src["shipping_noise"], lane, 0.01)
    _write_4326(src["ship_strike"], lambda lo, la: 15 * lane(lo, la), 0.01)
    _write_4326(src["fishing_commercial"],
                lambda lo, la: ndimage.gaussian_filter(rng.gamma(0.5, 10, lo.shape), 2), 0.01)
    _write_4326(src["light_pollution"],
                lambda lo, la: 60 * np.exp(-np.abs(lo - _coast_lon(la)) / 0.03) * (1 + (np.abs(la - 21.5) < 0.15) * 3), 0.005)

    # climate
    _write_4326(src["marine_heatwaves"], lambda lo, la: 0.2 + 0.4 * (LAT1 - la) + 0.05 * rng.random(lo.shape))
    bo = root / pdoc["bio_oracle"]["raw_dir"]
    base = {
        "thetao_max": lambda lo, la: 31.0 + 0.8 * (LAT1 - la) - 0.3 * (COAST_LON - lo),
        "ph_mean": lambda lo, la: 8.10 - 0.01 * (LAT1 - la),
        "o2_mean": lambda lo, la: 0.20 - 0.01 * (LAT1 - la),
        "so_mean": lambda lo, la: 39.5 + 0.3 * (la - LAT0),
    }
    change = {  # per SSP at 2100; 2050 is about half
        "ssp126": dict(thetao_max=0.8, ph_mean=-0.07, o2_mean=-0.004, so_mean=0.05),
        "ssp245": dict(thetao_max=1.6, ph_mean=-0.15, o2_mean=-0.008, so_mean=0.10),
        "ssp585": dict(thetao_max=3.2, ph_mean=-0.32, o2_mean=-0.015, so_mean=0.20),
    }
    def shifted(f, c):
        return lambda lo, la: f(lo, la) + c * (1 + 0.2 * (LAT1 - la))

    for v, f in base.items():
        _write_4326(bo / f"{v}_baseline.tif", f)
        for ssp, ch in change.items():
            for hz, k in (("2050", 0.45), ("2100", 1.0)):
                _write_4326(bo / f"{v}_{ssp}_{hz}.tif", shifted(f, ch[v] * k))

    # planned developments
    _coastal_points(rng, 2, capacity_m3_day=(300_000, 1_000_000)).to_file(dev["desal_brine"])
    _coastal_points(rng, 1, capacity_mw=(800, 2000)).to_file(dev["thermal_discharge"])
    _coastal_polys(rng, 3, size=0.04).to_file(dev["reclamation"])
    _coastal_points(rng, 3).to_file(dev["dredging_sediment"])
    _coastal_points(rng, 2, population_served=(100_000, 400_000)).to_file(dev["wastewater_nutrients"])
    _coastal_points(rng, 6, visitors_year=(20_000, 150_000)).to_file(dev["tourism_diving"])
    _coastal_points(rng, 1, production_t_year=(2000, 6000)).to_file(dev["aquaculture"])
    # light_planned.tif deliberately left out to show how missing inputs are reported


def build_demo_components(cfg, grid, seed: int = 7) -> None:
    """Synthetic ecosystem component rasters on the demo grid."""
    rng = np.random.default_rng(seed)
    rows, cols, x, y = grid.cell_centres(only_mask=False)
    tr = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    lon, lat = tr.transform(x, y)
    lon, lat = lon.reshape(grid.shape), lat.reshape(grid.shape)
    dist_km = (_coast_lon(lat) - lon) * 104  # rough km offshore (negative on land)

    def patches(scale, thr):
        f = ndimage.gaussian_filter(rng.random(grid.shape), scale)
        f = (f - f.min()) / (f.max() - f.min())
        return np.clip((f - thr) / (1 - thr), 0, 1)

    band = lambda a, b: ((dist_km >= a) & (dist_km < b)).astype(float)
    near = lambda s: np.exp(-np.clip(dist_km, 0, None) / s)
    layers = {
        "coral_shallow": band(0.5, 15) * patches(2, 0.45),
        "coral_mesophotic": band(5, 25) * patches(3, 0.6),
        "seagrass": band(0, 6) * patches(2, 0.5),
        "mangrove": band(-1.5, 1) * patches(1.5, 0.6),
        "intertidal_flats": band(-2, 0.5) * patches(2, 0.4),
        "soft_sediment": band(0, 30) * patches(4, 0.3),
        "hard_substrate": band(0, 30) * patches(3, 0.7),
        "deep_sea": (dist_km > 25).astype(float),
        "dugong": band(0, 8) * patches(4, 0.4),
        "green_turtle": band(0, 10) * patches(4, 0.3),
        "hawksbill_turtle": band(0.5, 15) * patches(4, 0.3),
        "turtle_nesting": band(-1, 0.3) * patches(2, 0.75),
        "whale_shark": band(5, 40) * patches(6, 0.55),
        "manta_mobula": band(2, 30) * patches(5, 0.5),
        "dolphins": (dist_km > 0) * patches(6, 0.2),
        "other_cetaceans": (dist_km > 20) * patches(6, 0.3),
        "seabird_breeding": band(1, 20) * patches(1, 0.85),
        "seabird_foraging": near(15) * (dist_km > 0),
        "reef_fish": band(0.5, 15) * patches(2, 0.45) * 0.9,
        "spawning_aggregations": band(1, 15) * patches(1, 0.88),
        "pelagic_productive": (dist_km > 0) * (0.3 + 0.7 * patches(8, 0.0)),
    }
    for k, v in layers.items():
        grid.write(cfg.component_file(k), np.clip(v, 0, 1).astype("float32"))


def build_demo_surveys(cfg, grid, seed: int = 3) -> None:
    """100 synthetic survey sites; coral condition loosely tied to baseline impact plus noise."""
    rng = np.random.default_rng(seed)
    coral = grid.read(cfg.component_file("coral_shallow"), "nearest")
    impact = grid.read(cfg.outputs_dir / "S0_baseline" / "impact_total.tif", "nearest")
    r, c = np.nonzero(coral > 0.2)
    pick = rng.choice(len(r), size=min(100, len(r)), replace=False)
    r, c = r[pick], c[pick]
    x = grid.transform.c + (c + 0.5) * grid.transform.a
    y = grid.transform.f + (r + 0.5) * grid.transform.e
    lon, lat = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True).transform(x, y)
    imp = impact[r, c]
    z = (imp - np.nanmean(imp)) / (np.nanstd(imp) or 1)
    n = len(r)
    df = pd.DataFrame({
        "site_id": [f"DEMO{i+1:03d}" for i in range(n)],
        "latitude": np.round(lat, 5), "longitude": np.round(lon, 5),
        "survey_date": "2025-05-01", "depth_m": rng.integers(3, 15, n),
        "live_coral_cover_pct": np.clip(35 - 9 * z + rng.normal(0, 8, n), 1, 90).round(1),
        "recent_mortality_pct": np.clip(6 + 3 * z + rng.normal(0, 3, n), 0, 60).round(1),
        "bleaching_pct": np.clip(10 + 4 * z + rng.normal(0, 6, n), 0, 100).round(1),
        "macroalgae_cover_pct": np.clip(8 + 3 * z + rng.normal(0, 4, n), 0, 80).round(1),
        "coral_genera_richness": np.clip(30 - 4 * z + rng.normal(0, 5, n), 3, 60).round(),
        "fish_biomass_kg_ha": np.clip(900 - 200 * z + rng.normal(0, 250, n), 50, 4000).round(),
        "notes": "synthetic demo data",
    })
    f = cfg.path(cfg.project["paths"]["surveys_file"])
    f.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(f, index=False)


def build_demo_application(cfg) -> Path:
    """A synthetic permit application: one desalination plant plus a small resort."""
    rng = np.random.default_rng(11)
    d = cfg.root / "data" / "interim" / "scenarios" / "applications" / "DEMO-APP-001"
    d.mkdir(parents=True, exist_ok=True)
    _coastal_points(rng, 1, capacity_m3_day=(400_000, 400_001)).to_file(d / "desal_plant.gpkg")
    _coastal_points(rng, 1, visitors_year=(60_000, 60_001)).to_file(d / "resort.gpkg")
    proj = {
        "id": "DEMO-APP-001", "name": "Synthetic desalination plant and resort", "applicant": "Demo applicant",
        "changes": [
            {"pressure": "desal_brine", "mode": "add_sources", "file": "data/interim/scenarios/applications/DEMO-APP-001/desal_plant.gpkg"},
            {"pressure": "chemical_discharge", "mode": "add_sources", "file": "data/interim/scenarios/applications/DEMO-APP-001/desal_plant.gpkg"},
            {"pressure": "tourism_diving", "mode": "add_sources", "file": "data/interim/scenarios/applications/DEMO-APP-001/resort.gpkg"},
        ],
    }
    f = d / "project.yaml"
    f.write_text(yaml.safe_dump(proj, sort_keys=False))
    return f

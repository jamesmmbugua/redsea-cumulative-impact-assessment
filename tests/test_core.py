import numpy as np
import pandas as pd
import geopandas as gpd
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import Point, box

from rscia import layers
from rscia.config import load_config
from rscia.grid import Grid
from rscia.model import cumulative_impact
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRS_AEA = "+proj=aea +lat_0=22 +lon_0=39 +lat_1=18.5 +lat_2=27.5 +datum=WGS84 +units=m +no_defs"


def small_grid(n=20, res=1000.0):
    return Grid(from_origin(0, n * res, res, res), n, n, CRS.from_user_input(CRS_AEA),
                np.ones((n, n), dtype=bool))


def test_config_loads_and_matrix_complete():
    cfg = load_config(ROOT)
    assert len(cfg.component_ids) == 21
    assert len(cfg.pressure_ids) == 19
    assert set(cfg.sensitivity.index) == set(cfg.pressure_ids)
    assert set(cfg.sensitivity.columns) == set(cfg.component_ids)


def test_impact_formula_matches_hand_calculation():
    mask = np.ones((2, 2), bool)
    P = {"a": np.array([[1, 0.5], [0, 0]], float), "b": np.array([[0, 1], [1, 0]], float)}
    E = {"x": np.array([[1, 1], [1, 0]], float), "y": np.array([[0.5, 0], [1, 1]], float)}
    S = pd.DataFrame({"x": [0.8, 0.2], "y": [0.0, 1.0]}, index=["a", "b"])
    r = cumulative_impact(P, E, S, mask)
    expected = np.zeros((2, 2))
    for p in P:
        for c in E:
            expected += P[p] * E[c] * S.at[p, c]
    np.testing.assert_allclose(r.total, expected, rtol=1e-6)
    np.testing.assert_allclose(r.by_pressure.sum(0), r.total, rtol=1e-6)
    np.testing.assert_allclose(r.by_component.sum(0), r.total, rtol=1e-6)


def test_outside_mask_is_nan():
    mask = np.array([[True, False]])
    r = cumulative_impact({"a": np.ones((1, 2))}, {"x": np.ones((1, 2))},
                          pd.DataFrame({"x": [1.0]}, index=["a"]), mask)
    assert r.total[0, 0] == pytest.approx(1.0) and np.isnan(r.total[0, 1])


def test_normalize_reference_and_log():
    a = np.arange(101, dtype=float)
    n, ref = layers.normalize(a, percentile=99)
    assert ref == pytest.approx(np.percentile(a[1:], 99))
    assert n.max() == pytest.approx(1.0)
    n2, _ = layers.normalize(a * 2, reference=ref, clip_max=None)
    assert n2.max() > 1.0  # scenario layers can exceed the baseline scale
    nl, refl = layers.normalize(a, log_transform=True)
    assert refl == pytest.approx(np.percentile(np.log1p(a[1:]), 99))


def test_decay_from_points():
    g = small_grid()
    pts = gpd.GeoDataFrame({"w": [10.0]}, geometry=[Point(10_500, 10_500)], crs=g.crs)
    a = layers.decay_from_points(pts, g, decay_km=2, weight_field="w")
    r, c = np.unravel_index(np.nanargmax(a), a.shape)
    assert (r, c) == (9, 10)
    assert a[9, 10] == pytest.approx(10.0)
    assert a[9, 12] == pytest.approx(10 * np.exp(-1), rel=1e-6)  # 2 km away
    assert a[0, 0] == 0  # beyond the 3 x decay cutoff


def test_fractional_cover():
    g = small_grid()
    poly = gpd.GeoDataFrame(geometry=[box(0, 19_000, 1_500, 20_000)], crs=g.crs)
    a = layers.fractional_cover(poly, g, supersample=10)
    assert a[0, 0] == pytest.approx(1.0)
    assert a[0, 1] == pytest.approx(0.5)
    assert a[1, 0] == 0


def test_climate_delta_directions():
    p, f = np.array([1.0, 2.0]), np.array([2.0, 1.0])
    np.testing.assert_allclose(layers.climate_delta(p, f, "increase"), [1, 0])
    np.testing.assert_allclose(layers.climate_delta(p, f, "decrease"), [0, 1])
    np.testing.assert_allclose(layers.climate_delta(p, f, "absolute"), [1, 1])


def test_scenario_expansion_gives_14_runs():
    from rscia.pipeline import expand_runs
    runs = expand_runs(load_config(ROOT))
    assert len(runs) == 14
    assert runs[0].run_id == "S0_baseline"
    assert "S3_combined_ssp585_2100" in {r.run_id for r in runs}


def test_demo_pipeline(tmp_path):
    from rscia.cli import main
    out = tmp_path / "demo"
    main(["--root", str(ROOT), "demo", "--out", str(out)])
    res = out / "outputs"
    assert (res / "S0_baseline" / "impact_total.tif").exists()
    s = pd.read_csv(res / "comparisons" / "all_runs_summary.csv")
    assert len(s) == 13
    # development adds pressure, so total impact cannot fall
    assert (s.loc[s.run == "S1_development", "change_pct"] > 0).all()
    v = pd.read_csv(res / "S0_baseline" / "validation" / "validation_summary.csv")
    assert v.direction_as_expected.all()

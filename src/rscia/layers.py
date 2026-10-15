"""Turn raw inputs into grid layers: distance decay, footprints, normalization, climate deltas."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize
from scipy import ndimage
from scipy.spatial import cKDTree

from .grid import Grid


def decay_from_points(gdf: gpd.GeoDataFrame, grid: Grid, decay_km: float,
                      weight_field: str | None = None, cutoff_factor: float = 3.0) -> np.ndarray:
    """Sum of weight x exp(-distance / decay) from each source, within cutoff.

    Lines and polygons are represented by their representative point. Distances are
    straight-line (not around land).
    """
    out = grid.empty()
    if gdf is None or len(gdf) == 0:
        return out
    gdf = gdf.to_crs(grid.crs)
    pts = gdf.geometry.representative_point()
    sx, sy = pts.x.to_numpy(), pts.y.to_numpy()
    if weight_field:
        if weight_field not in gdf.columns:
            raise KeyError(f"Weight field '{weight_field}' not found in sources")
        w = gdf[weight_field].fillna(0).to_numpy(dtype=float)
    else:
        w = np.ones(len(gdf))

    rows, cols, cx, cy = grid.cell_centres()
    tree = cKDTree(np.column_stack([cx, cy]))
    d = decay_km * 1000.0
    radius = max(cutoff_factor * d, grid.resolution)
    vals = np.zeros(len(cx))
    for x, y, wi in zip(sx, sy, w):
        idx = tree.query_ball_point([x, y], r=radius)
        if not idx:
            continue
        idx = np.asarray(idx)
        dist = np.hypot(cx[idx] - x, cy[idx] - y)
        vals[idx] += wi * (np.exp(-dist / d) if d > 0 else (dist <= grid.resolution / 2))
    out[rows, cols] = vals
    return out


def fractional_cover(gdf: gpd.GeoDataFrame, grid: Grid, supersample: int = 5) -> np.ndarray:
    """Fraction of each cell covered by polygons (0 to 1)."""
    out = grid.empty()
    if gdf is None or len(gdf) == 0:
        return out
    gdf = gdf.to_crs(grid.crs)
    f = supersample
    t = grid.transform @ grid.transform.scale(1 / f, 1 / f)
    fine = rasterize([(g, 1) for g in gdf.geometry if g is not None and not g.is_empty],
                     out_shape=(grid.height * f, grid.width * f), transform=t,
                     fill=0, dtype="uint8")
    cover = fine.reshape(grid.height, f, grid.width, f).mean(axis=(1, 3)).astype("float32")
    out[grid.mask] = cover[grid.mask]
    return out


def footprint(gdf: gpd.GeoDataFrame, grid: Grid, decay_km: float = 0.0,
              supersample: int = 5) -> np.ndarray:
    """Polygon footprint, optionally spread outward with an exponential kernel."""
    cover = fractional_cover(gdf, grid, supersample)
    if decay_km and decay_km > 0:
        d_cells = decay_km * 1000.0 / grid.resolution
        r = int(np.ceil(3 * d_cells))
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        k = np.exp(-np.hypot(xx, yy) / d_cells)
        spread = ndimage.convolve(np.nan_to_num(cover), k, mode="constant")
        cover = np.maximum(cover, np.minimum(spread, 1.0))
        cover[~grid.mask] = np.nan
    return cover


def kernel_density(gdf: gpd.GeoDataFrame, grid: Grid, bandwidth_km: float,
                   weight_field: str | None = None) -> np.ndarray:
    """Gaussian kernel density of point records (for species sightings)."""
    out = grid.empty()
    if gdf is None or len(gdf) == 0:
        return out
    gdf = gdf.to_crs(grid.crs)
    counts = np.zeros(grid.shape, dtype="float64")
    r, c = grid.rowcol(gdf.geometry.x, gdf.geometry.y)
    w = gdf[weight_field].to_numpy(float) if weight_field else np.ones(len(gdf))
    ok = (r >= 0) & (r < grid.height) & (c >= 0) & (c < grid.width)
    np.add.at(counts, (r[ok], c[ok]), w[ok])
    sm = ndimage.gaussian_filter(counts, sigma=bandwidth_km * 1000.0 / grid.resolution)
    out[grid.mask] = sm[grid.mask]
    return out


def normalize(arr: np.ndarray, reference: float | None = None, percentile: float = 99,
              log_transform: bool = False, clip_max: float | None = 1.0):
    """Scale a layer to 0 to 1.

    Returns (normalized array, reference value). Pass the baseline reference when
    normalizing scenario layers so they share the baseline scale.
    """
    a = np.asarray(arr, dtype="float64").copy()
    a[a < 0] = 0
    if log_transform:
        a = np.log1p(a)
    if reference is None:
        vals = a[np.isfinite(a) & (a > 0)]
        reference = float(np.percentile(vals, percentile)) if vals.size else 0.0
    if reference > 0:
        a = a / reference
    else:
        a = np.where(np.isfinite(a), 0.0, np.nan)
    if clip_max is not None:
        a = np.minimum(a, clip_max)
    return a.astype("float32"), reference


def climate_delta(present: np.ndarray, future: np.ndarray, direction: str) -> np.ndarray:
    """Climate pressure as change from present. Only harmful change counts."""
    diff = future - present
    if direction == "increase":
        out = np.maximum(diff, 0)
    elif direction == "decrease":
        out = np.maximum(-diff, 0)
    elif direction == "absolute":
        out = np.abs(diff)
    else:
        raise ValueError(direction)
    return out.astype("float32")

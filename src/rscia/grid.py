"""The 1 km analysis grid and raster input/output on it."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import reproject

NODATA = -9999.0


@dataclass
class Grid:
    transform: rasterio.Affine
    width: int
    height: int
    crs: CRS
    mask: np.ndarray  # True inside the study area

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height, self.width)

    @property
    def resolution(self) -> float:
        return self.transform.a

    def empty(self) -> np.ndarray:
        a = np.zeros(self.shape, dtype="float32")
        a[~self.mask] = np.nan
        return a

    def cell_centres(self, only_mask: bool = True):
        """Return (rows, cols, x, y) of cell centres."""
        rows, cols = np.nonzero(self.mask) if only_mask else np.indices(self.shape).reshape(2, -1)
        xs = self.transform.c + (cols + 0.5) * self.transform.a
        ys = self.transform.f + (rows + 0.5) * self.transform.e
        return rows, cols, xs, ys

    def rowcol(self, x, y):
        cols = np.floor((np.asarray(x) - self.transform.c) / self.transform.a).astype(int)
        rows = np.floor((np.asarray(y) - self.transform.f) / self.transform.e).astype(int)
        return rows, cols

    # ---- io -------------------------------------------------------------
    def write(self, path: Path, data: np.ndarray, band_names: list[str] | None = None) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        arr = np.asarray(data, dtype="float32")
        if arr.ndim == 2:
            arr = arr[None]
        out = np.where(np.isnan(arr), NODATA, arr)
        out[:, ~self.mask] = NODATA
        profile = dict(
            driver="GTiff", width=self.width, height=self.height, count=arr.shape[0],
            dtype="float32", crs=self.crs, transform=self.transform, nodata=NODATA,
            compress="deflate", tiled=True, blockxsize=256, blockysize=256,
        )
        if self.width < 256 or self.height < 256:
            profile.update(tiled=False)
            profile.pop("blockxsize"); profile.pop("blockysize")
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(out)
            if band_names:
                for i, n in enumerate(band_names, start=1):
                    dst.set_band_description(i, n)

    def read(self, path: Path, resampling: str = "bilinear", fill: float | None = 0.0) -> np.ndarray:
        """Read a single-band raster onto this grid, reprojecting if needed.

        Cells inside the study area with no data become `fill` (0 by default);
        cells outside are NaN.
        """
        with rasterio.open(path) as src:
            same = (
                src.crs == self.crs and src.transform == self.transform
                and src.width == self.width and src.height == self.height
            )
            if same:
                arr = src.read(1).astype("float32")
                if src.nodata is not None:
                    arr[arr == src.nodata] = np.nan
            else:
                arr = np.full(self.shape, np.nan, dtype="float32")
                src_arr = src.read(1).astype("float32")
                if src.nodata is not None:
                    src_arr[src_arr == src.nodata] = np.nan
                reproject(
                    source=src_arr, destination=arr,
                    src_transform=src.transform, src_crs=src.crs,
                    dst_transform=self.transform, dst_crs=self.crs,
                    src_nodata=np.nan, dst_nodata=np.nan,
                    resampling=getattr(Resampling, resampling),
                )
        if fill is not None:
            arr[np.isnan(arr) & self.mask] = fill
        arr[~self.mask] = np.nan
        return arr

    @classmethod
    def from_template(cls, path: Path) -> "Grid":
        with rasterio.open(path) as src:
            m = src.read(1)
            mask = m != src.nodata if src.nodata is not None else m > 0
            return cls(src.transform, src.width, src.height, src.crs, mask & (m > 0))


def build_grid(eez: gpd.GeoDataFrame, crs: str, resolution: float,
               land: gpd.GeoDataFrame | None = None, coastal_buffer: float = 0.0,
               clip: gpd.GeoDataFrame | None = None) -> Grid:
    """Build the analysis grid: EEZ (optionally clipped) plus a landward coastal strip."""
    crs = CRS.from_user_input(crs)
    area = eez.to_crs(crs).union_all()
    if clip is not None:
        area = area.intersection(clip.to_crs(crs).union_all())
    if land is not None and coastal_buffer > 0:
        land_u = land.to_crs(crs).clip(area.buffer(coastal_buffer)).union_all()
        strip = area.buffer(coastal_buffer).intersection(land_u)
        area = area.union(strip)

    minx, miny, maxx, maxy = area.bounds
    minx = np.floor(minx / resolution) * resolution
    maxy = np.ceil(maxy / resolution) * resolution
    width = int(np.ceil((maxx - minx) / resolution))
    height = int(np.ceil((maxy - miny) / resolution))
    transform = from_origin(minx, maxy, resolution, resolution)
    mask = rasterize([(area, 1)], out_shape=(height, width), transform=transform,
                     fill=0, all_touched=True, dtype="uint8").astype(bool)
    return Grid(transform, width, height, crs, mask)


def save_template(grid: Grid, path: Path) -> None:
    grid.write(path, np.where(grid.mask, 1.0, np.nan))

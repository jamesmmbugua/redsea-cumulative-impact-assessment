"""Import Bio-ORACLE v3 layers into the names the model expects.

Bio-ORACLE v3 files (from the ERDDAP server or the R/Python packages) are NetCDF files
named like:

    thetao_baseline_2000_2019_depthsurf.nc
    thetao_ssp245_2020_2100_depthsurf.nc     (decadal time steps 2020 to 2090)

This script reads every such file in an input folder, clips it to the Red Sea, picks the
right time step, and writes GeoTIFFs to data/raw/climate/bio_oracle/ named

    {variable}_baseline.tif
    {variable}_{ssp}_{horizon}.tif         horizon 2050 = decade 2040s, 2100 = decade 2090s

where {variable} is the statistic inside the file, for example thetao_max, ph_mean,
o2_mean, so_mean (as listed in config/pressures.yaml). GeoTIFFs already exported from
Bio-ORACLE can be used too: just name them by the same rule.

Usage:
    python scripts/import_bio_oracle.py path/to/bio_oracle_folder [--depth depthsurf]
"""
import argparse
import re
from pathlib import Path

import numpy as np
import rasterio
import xarray as xr
from rasterio.transform import from_bounds

BBOX = dict(lon=(32.0, 44.5), lat=(12.0, 30.5))
HORIZON_YEAR = {"2050": 2040, "2100": 2090}
OUT = Path("data/raw/climate/bio_oracle")
NAME = re.compile(r"^(?P<var>[a-z0-9]+)_(?P<scen>baseline|ssp\d{3})_(?P<y0>\d{4})_(?P<y1>\d{4})_(?P<depth>depth\w+)")


def write_tif(da, path):
    lon = da["longitude"].values if "longitude" in da.coords else da["lon"].values
    lat = da["latitude"].values if "latitude" in da.coords else da["lat"].values
    arr = da.values.astype("float32")
    if lat[0] < lat[-1]:  # north up
        arr, lat = arr[::-1], lat[::-1]
    rx, ry = abs(lon[1] - lon[0]), abs(lat[1] - lat[0])
    t = from_bounds(lon.min() - rx / 2, lat.min() - ry / 2, lon.max() + rx / 2, lat.max() + ry / 2, len(lon), len(lat))
    arr = np.where(np.isfinite(arr), arr, -9999)
    with rasterio.open(path, "w", driver="GTiff", width=len(lon), height=len(lat), count=1, dtype="float32",
                       crs="EPSG:4326", transform=t, nodata=-9999, compress="deflate") as dst:
        dst.write(arr, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--depth", default="depthsurf", help="depthsurf, depthmean, depthmin or depthmax")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(Path(a.folder).glob("*.nc")):
        m = NAME.match(f.stem)
        if not m or m["depth"] != a.depth:
            continue
        ds = xr.open_dataset(f)
        lonn = "longitude" if "longitude" in ds.coords else "lon"
        latn = "latitude" if "latitude" in ds.coords else "lat"
        lat_slice = slice(*BBOX["lat"]) if ds[latn][0] < ds[latn][-1] else slice(*BBOX["lat"][::-1])
        ds = ds.sel({lonn: slice(*BBOX["lon"]), latn: lat_slice})
        for var in ds.data_vars:
            if not var.startswith(m["var"] + "_"):
                continue
            da = ds[var]
            if m["scen"] == "baseline":
                if "time" in da.dims:
                    da = da.mean("time")
                write_tif(da, OUT / f"{var}_baseline.tif"); n += 1
            else:
                years = da["time"].dt.year.values
                for hz, yr in HORIZON_YEAR.items():
                    if yr not in years:
                        print(f"  {f.name}: no {yr} step, skipped {hz}")
                        continue
                    write_tif(da.sel(time=da["time"].dt.year == yr).squeeze("time"), OUT / f"{var}_{m['scen']}_{hz}.tif"); n += 1
        print(f"read {f.name}")
    print(f"Wrote {n} GeoTIFFs to {OUT}")


if __name__ == "__main__":
    main()

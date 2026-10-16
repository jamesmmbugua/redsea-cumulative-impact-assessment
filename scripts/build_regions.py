"""Build the three assessment regions (Northern, Central, Southern Red Sea) from MEOW.

Marine Ecoregions of the World (Spalding et al. 2007) has two Red Sea ecoregions on the
Saudi side: "Northern and Central Red Sea" and "Southern Red Sea". RS-CIA splits the first
at a chosen latitude:

    Northern Red Sea = Northern and Central Red Sea, north of the split latitude
    Central Red Sea  = Northern and Central Red Sea, south of the split latitude
    Southern Red Sea = Southern Red Sea

The regions are clipped to the study area (EEZ plus the coastal strip) and written to
data/interim/reference/boundaries/regions.gpkg with a `region` field (northern, central, southern).

Usage (from the repository root):
    python scripts/build_regions.py [--meow path/to/meow_ecos.shp] [--split-lat 23.5]

The split latitude defaults to regions.north_central_split_latitude in config/project.yaml.
MEOW can be downloaded from https://www.marineregions.org (MEOW, WWF/TNC 2007).
"""
import argparse
from pathlib import Path

import geopandas as gpd
import yaml
from shapely.geometry import box

NC = "Northern and Central Red Sea"
S = "Southern Red Sea"


def main():
    cfg = yaml.safe_load(Path("config/project.yaml").read_text())
    rc = cfg["regions"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--meow", default=rc.get("meow_file"))
    ap.add_argument("--split-lat", type=float, default=rc.get("north_central_split_latitude"))
    a = ap.parse_args()
    if a.split_lat is None:
        raise SystemExit("Set regions.north_central_split_latitude in config/project.yaml or pass --split-lat")

    meow = gpd.read_file(a.meow).to_crs(4326)
    name_col = next(c for c in meow.columns if c.upper() == "ECOREGION")
    found = set(meow[name_col])
    for n in (NC, S):
        if n not in found:
            raise SystemExit(f"Ecoregion '{n}' not in {a.meow}. Red Sea names found: "
                             f"{sorted(x for x in found if 'Red Sea' in str(x))}")

    nc = meow.loc[meow[name_col] == NC].union_all()
    south = meow.loc[meow[name_col] == S].union_all()
    north = nc.intersection(box(30, a.split_lat, 45, 32))
    central = nc.intersection(box(30, 10, 45, a.split_lat))

    # Clip to the EEZ. MEOW stops at the coast, so cells in the landward coastal strip are
    # given the region of the nearest marine cell when `rscia build-grid` rasterizes them.
    eez = gpd.read_file(cfg["grid"]["eez_file"]).to_crs(4326).union_all()
    regions = gpd.GeoDataFrame(
        {"region": ["northern", "central", "southern"],
         "name": ["Northern Red Sea", "Central Red Sea", "Southern Red Sea"]},
        geometry=[north.intersection(eez), central.intersection(eez), south.intersection(eez)], crs=4326)

    out = Path(rc["file"])
    out.parent.mkdir(parents=True, exist_ok=True)
    regions.to_file(out)
    areas = regions.to_crs(cfg["grid"]["crs"]).area / 1e6
    for (_, r), km2 in zip(regions.iterrows(), areas):
        print(f"{r['name']}: {km2:,.0f} km2")
    print(f"Wrote {out}. Run `rscia build-grid` to rasterize the regions.")


if __name__ == "__main__":
    main()

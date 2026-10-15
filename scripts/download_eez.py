"""Download the Saudi Arabian EEZ from Marine Regions and keep the Red Sea part.

Run from the repository root (needs internet access):

    python scripts/download_eez.py

Writes data/raw/boundaries/eez_v12.gpkg with one polygon: the Saudi EEZ west of 44.5 E
(Red Sea and Gulf of Aqaba). The Arabian Gulf part lies east of 48 E and is dropped.
Cite: Flanders Marine Institute (2023), Maritime Boundaries Geodatabase v12.
"""
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

WFS = (
    "https://geo.vliz.be/geoserver/MarineRegions/wfs?service=WFS&version=1.0.0"
    "&request=GetFeature&typeName=MarineRegions:eez&outputFormat=application/json"
    "&CQL_FILTER=sovereign1='Saudi Arabia'"
)
RED_SEA_BOX = box(32.0, 12.0, 44.5, 30.5)
OUT = Path("data/raw/boundaries/eez_v12.gpkg")


def main():
    eez = gpd.read_file(WFS.replace(" ", "%20").replace("'", "%27"))
    if eez.empty:
        raise SystemExit("No EEZ features returned; check the Marine Regions WFS.")
    eez = eez.to_crs(4326)
    print("Features returned:", list(eez.get("geoname", eez.index)))
    red = eez.clip(RED_SEA_BOX)
    red = red[~red.geometry.is_empty]
    red = gpd.GeoDataFrame({"name": ["Saudi Red Sea EEZ"]}, geometry=[red.union_all()], crs=4326)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    red.to_file(OUT)
    area = red.to_crs("+proj=aea +lat_0=22 +lon_0=39 +lat_1=18.5 +lat_2=27.5 +datum=WGS84").area.iloc[0] / 1e6
    print(f"Wrote {OUT} ({area:,.0f} km2)")


if __name__ == "__main__":
    main()

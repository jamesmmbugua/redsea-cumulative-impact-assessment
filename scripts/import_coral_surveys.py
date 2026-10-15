"""Bring a coral survey spreadsheet into the standard format used by the model.

Usage:
    python scripts/import_coral_surveys.py surveys.xlsx --map site=Site lat=Lat lon=Long \
        coral=HardCoral_pct
Standard columns (see data/surveys/coral_surveys_template.csv):
    site_id, latitude, longitude, survey_date, depth_m, live_coral_cover_pct,
    recent_mortality_pct, bleaching_pct, macroalgae_cover_pct, coral_genera_richness,
    fish_biomass_kg_ha, notes
Short keys for --map: site, lat, lon, date, depth, coral, mortality, bleaching, algae,
richness, fish. Columns already named in the standard way need no mapping.
Coordinates in degrees-minutes-seconds text (22°19'12"N) are converted to decimal degrees.
"""
import argparse
import re
from pathlib import Path

import pandas as pd

STD = ["site_id", "latitude", "longitude", "survey_date", "depth_m", "live_coral_cover_pct",
       "recent_mortality_pct", "bleaching_pct", "macroalgae_cover_pct", "coral_genera_richness",
       "fish_biomass_kg_ha", "notes"]
SHORT = dict(site="site_id", lat="latitude", lon="longitude", date="survey_date", depth="depth_m",
             coral="live_coral_cover_pct", mortality="recent_mortality_pct", bleaching="bleaching_pct",
             algae="macroalgae_cover_pct", richness="coral_genera_richness", fish="fish_biomass_kg_ha")
OUT = Path("data/surveys/coral_surveys.csv")


def to_decimal(v):
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    nums = [float(x) for x in re.findall(r"[\d.]+", s)]
    if not nums:
        return float("nan")
    d = nums[0] + (nums[1] / 60 if len(nums) > 1 else 0) + (nums[2] / 3600 if len(nums) > 2 else 0)
    return -d if re.search(r"[SWsw]", s) or s.startswith("-") else d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--sheet", default=0)
    ap.add_argument("--map", nargs="*", default=[], help="key=SourceColumn pairs")
    a = ap.parse_args()
    f = Path(a.file)
    df = pd.read_excel(f, sheet_name=a.sheet) if f.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(f)
    rename = {}
    for pair in a.map:
        k, v = pair.split("=", 1)
        rename[v] = SHORT.get(k, k)
    df = df.rename(columns=rename)
    missing = [c for c in ("site_id", "latitude", "longitude") if c not in df.columns]
    if missing:
        raise SystemExit(f"Missing required columns {missing}. Columns found: {list(df.columns)}")
    df["latitude"] = df["latitude"].map(to_decimal)
    df["longitude"] = df["longitude"].map(to_decimal)
    bad = df[~df.latitude.between(12, 30.5) | ~df.longitude.between(32, 44.5)]
    if len(bad):
        print(f"Warning: {len(bad)} sites fall outside the Red Sea box:\n{bad[['site_id', 'latitude', 'longitude']]}")
    for c in STD:
        if c not in df.columns:
            df[c] = pd.NA
    extra = [c for c in df.columns if c not in STD]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df[STD + extra].to_csv(OUT, index=False)
    filled = {c: int(df[c].notna().sum()) for c in STD[4:11]}
    print(f"Wrote {len(df)} sites to {OUT}. Values per metric: {filled}")


if __name__ == "__main__":
    main()

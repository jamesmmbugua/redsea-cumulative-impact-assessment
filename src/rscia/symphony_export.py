"""Export a run's inputs as a baseline for the Symphony / WIO Symphony platform.

Format, from the Symphony data import guide (database/DataImportREADME.md in MSP-Symphony):
- ecosystem.tif and pressure.tif: multiband GeoTIFFs, one band per component, values 0 to 100,
  8-bit (Byte), tiled.
- sensitivity_<region>.csv: N pressures x M components, first field "SENSITIVITY", component
  titles in the first row, pressure titles in the first column, values 0 to 1, semicolon
  separated, period as decimal separator.
- ecosystem_metadata.csv and pressure_metadata.csv: one row per band, the 43 Symphony
  metadata fields, semicolon separated. "Title" must match the matrix row/column names exactly.

Symphony uses one projection per installation; the export keeps the RS-CIA grid (Albers
Equal Area), which is set when the Symphony instance is configured.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import numpy as np
import rasterio

from .config import Config
from .grid import Grid
from .pipeline import RunSpec, expand_runs, load_components, scenario_pressures

METADATA_FIELDS = [
    "Bandnumber", "Multiband .tif name", "Metadata filename", "Name", "Symphony Category",
    "Symphony Theme", "Symphony Theme (localized)", "Symphony Data Type", "Marine Plan Area",
    "Title", "Title (localized)", "Date Created", "Date  Published", "Resource Type", "Format",
    "Summary", "Swedish Summary", "Limitations for Symphony", "Recommendations", "Lineage",
    "Status", "Author Organisation", "Author Email", "Data Owner", "Data Owner (Swedish)",
    "Owner Email", "Topic Category", "Descriptive Keywords", "Theme", "Temporal Period",
    "Use Limitations", "Access / Use Restrictions", "OtherRestrictions", "Map Acknowledgement",
    "Security Classification", "Maintenance Information", "Spatial Representation",
    "Spatial Reference System", "Metadata date", "Metadata Organisation",
    "Metadata Organisation (Swedish)", "Metadata Email", "Metadata Language",
]
assert len(METADATA_FIELDS) == 43

ORG = "General Authority for Conservation of Corals and Sea Turtles in the Red Sea"
def _to_byte(a: np.ndarray, mask: np.ndarray) -> np.ndarray:
    v = np.clip(np.nan_to_num(a) * 100.0, 0, 100).round().astype("uint8")
    v[~mask] = 255  # nodata
    return v


def _write_multiband(path: Path, grid: Grid, layers: list[np.ndarray], names: list[str]) -> None:
    profile = dict(driver="GTiff", width=grid.width, height=grid.height, count=len(layers),
                   dtype="uint8", crs=grid.crs, transform=grid.transform, nodata=255,
                   compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    if grid.width < 256 or grid.height < 256:
        for k in ("tiled", "blockxsize", "blockysize"):
            profile.pop(k)
    with rasterio.open(path, "w", **profile) as dst:
        for i, (a, n) in enumerate(zip(layers, names), start=1):
            dst.write(_to_byte(a, grid.mask), i)
            dst.set_band_description(i, n)


def _metadata_rows(items: list[dict], category: str, tif: str, theme_of, data_conf) -> list[dict]:
    today = date.today().isoformat()
    rows = []
    for i, it in enumerate(items):
        conf = data_conf(it)
        rows.append({f: "" for f in METADATA_FIELDS} | {
            "Bandnumber": i, "Multiband .tif name": tif, "Metadata filename": f"{it['id']}.csv",
            "Name": it["id"], "Symphony Category": category, "Symphony Theme": theme_of(it),
            "Symphony Data Type": "Normalised", "Marine Plan Area": "Saudi Red Sea EEZ",
            "Title": it["name"], "Date Created": today, "Resource Type": "dataset",
            "Format": "8-bit GeoTIFF, values 0 to 100",
            "Summary": it.get("source", "") or it.get("method", ""),
            "Limitations for Symphony": f"RS-CIA data confidence {conf} of 3" if conf else "",
            "Lineage": f"Prepared with the RS-CIA tool (method: {it.get('method', '')})",
            "Status": "Draft", "Author Organisation": ORG, "Data Owner": ORG,
            "Topic Category": "oceans, environment", "Map Acknowledgement": ORG,
            "Spatial Representation": "grid", "Spatial Reference System": "Albers Equal Area (RS-CIA grid)",
            "Metadata date": today, "Metadata Organisation": ORG, "Metadata Language": "eng",
        })
    return rows


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader()
        w.writerows(rows)


def export_symphony(cfg: Config, grid: Grid, run_id: str | None = None, out_dir: Path | None = None) -> Path:
    runs = {r.run_id: r for r in expand_runs(cfg)}
    run = runs[run_id] if run_id else next(iter(runs.values()))
    out = Path(out_dir) if out_dir else cfg.outputs_dir / "symphony_export" / run.run_id
    out.mkdir(parents=True, exist_ok=True)
    missing: list = []

    E = load_components(cfg, grid, missing)
    P = scenario_pressures(cfg, grid, run, missing)
    comps, press = cfg.components, cfg.pressures
    _write_multiband(out / "ecosystem.tif", grid, [E[c["id"]] for c in comps], [c["name"] for c in comps])
    _write_multiband(out / "pressure.tif", grid, [P[p["id"]] for p in press], [p["name"] for p in press])

    _write_csv(out / "ecosystem_metadata.csv",
               _metadata_rows(comps, "Ecosystem", "ecosystem.tif", lambda c: cfg.theme_labels("components").get(c["group"], c["group"]),
                              lambda c: c.get("data_confidence")),
               METADATA_FIELDS)
    _write_csv(out / "pressure_metadata.csv",
               _metadata_rows(press, "Pressure", "pressure.tif",
                              lambda p: cfg.theme_labels("pressures").get(p["theme"], p["theme"]),
                              lambda p: p.get("data_confidence")),
               METADATA_FIELDS)

    # one sensitivity matrix per region (plus the default)
    ctitle = [c["name"] for c in comps]
    names = {0: "default"} | {int(r["id"]): r["code"] for r in cfg.regions}
    for rid, (smat, _) in cfg.regional.items():
        with open(out / f"sensitivity_{names[rid]}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["SENSITIVITY"] + ctitle)
            for p in press:
                w.writerow([p["name"]] + [f"{float(smat.at[p['id'], c['id']]):.2f}" for c in comps])

    note = [f"Symphony baseline export of RS-CIA run {run.run_id}, {date.today().isoformat()}.", "",
            "Files:", "- ecosystem.tif, pressure.tif: 8-bit multiband GeoTIFFs, 0 to 100, nodata 255",
            "- ecosystem_metadata.csv, pressure_metadata.csv: Symphony metadata (43 fields, ';')",
            "- sensitivity_<region>.csv: one matrix per region (';'). Symphony applies regional",
            "  matrices through its calculation areas: import one matrix per area.", ""]
    if missing:
        note += ["Missing inputs (exported as zero):"] + [f"- {m}" for m in sorted(set(missing))]
    (out / "README.txt").write_text("\n".join(note) + "\n")
    return out

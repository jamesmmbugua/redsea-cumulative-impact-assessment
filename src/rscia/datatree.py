"""Create the thematic data folder tree and keep it in line with the configuration.

The same thematic folders are used at every data stage:

    data/raw/        original files exactly as received, one folder per source (never edited)
    data/interim/    cleaned model inputs: clipped, reprojected, standard attribute names
    data/processed/  model-ready 1 km rasters written by rscia

Themes come from `themes` in config/project.yaml; source folders come from the
`raw_folder` column of config/data_catalogue.csv.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .config import Config

SOURCE_TEMPLATE = """# Source: {folder}

Layer(s): {layers}

| Item | Value |
|---|---|
| Provider | |
| Dataset name and version | |
| Download URL or contact | |
| Date obtained | |
| Licence and use conditions | |
| Original projection | |
| Files received | |

Notes: keep the files in this folder exactly as received. Cleaning and reprojection happen in
code that writes to data/interim/. Record the same details in config/data_catalogue.csv.
"""


def catalogue(cfg: Config) -> list[dict]:
    f = cfg.root / "config" / "data_catalogue.csv"
    if not f.exists():
        return []
    with open(f, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def theme_folders(cfg: Config) -> list[Path]:
    """Every thematic folder at every stage, relative to the repository root."""
    paths = cfg.project["paths"]
    raw = Path(paths.get("raw_dir", "data/raw"))
    interim = Path(paths.get("interim_dir", "data/interim"))
    processed = Path(paths.get("processed_dir", "data/processed"))
    ref, comp, pres = (list(cfg.theme_labels(k)) for k in ("reference", "components", "pressures"))
    out: list[Path] = []
    for stage in (raw, interim):
        out += [stage / "reference" / t for t in ref]
        out += [stage / "components" / t for t in comp]
        out += [stage / "pressures" / t for t in pres]
        out += [stage / "scenarios" / "development" / t for t in pres if t != "climate"]
        out.append(stage / "scenarios" / "applications")
    out.append(Path(cfg.project["grid"]["template_raster"]).parent)
    out += [Path(paths["components_dir"]) / t for t in comp]
    out += [Path(paths["pressures_dir"]) / t for t in pres]
    return out


def init_data(cfg: Config, root: Path | None = None) -> dict:
    """Create the folder tree under `root` (default: the repository) without touching files.

    Returns counts of folders and SOURCE.md notes created.
    """
    base = Path(root) if root else cfg.root
    made_dirs = made_notes = 0
    for rel in theme_folders(cfg):
        d = base / rel
        if not d.exists():
            d.mkdir(parents=True)
            made_dirs += 1
    layers_by_folder: dict[str, list[str]] = {}
    for row in catalogue(cfg):
        if row.get("raw_folder"):
            layers_by_folder.setdefault(row["raw_folder"], []).append(row["layer_id"])
    for folder, layer_ids in layers_by_folder.items():
        d = base / folder
        if not d.exists():
            d.mkdir(parents=True)
            made_dirs += 1
        note = d / "SOURCE.md"
        if not note.exists():
            note.write_text(SOURCE_TEMPLATE.format(folder=folder, layers=", ".join(layer_ids)), encoding="utf-8")
            made_notes += 1
    return {"folders_created": made_dirs, "source_notes_created": made_notes, "root": str(base)}


def catalogue_problems(cfg: Config) -> list[str]:
    """Differences between the catalogue and the configuration (themes, processed paths)."""
    rows = {r["layer_id"]: r for r in catalogue(cfg)}
    problems = []
    for c in cfg.components:
        r = rows.get(c["id"])
        want = str(cfg.component_file(c["id"]).relative_to(cfg.root))
        if r is None:
            problems.append(f"component {c['id']} has no catalogue row")
        elif r["theme"] != c["group"] or r["processed_file"] != want:
            problems.append(f"component {c['id']}: catalogue theme/processed_file should be {c['group']} / {want}")
    for p in cfg.pressures:
        r = rows.get(p["id"])
        if r is None:
            problems.append(f"pressure {p['id']} has no catalogue row")
        elif r["theme"] != p["theme"]:
            problems.append(f"pressure {p['id']}: catalogue theme should be {p['theme']}")
        elif p.get("sources") and r["interim_path"] != p["sources"]:
            problems.append(f"pressure {p['id']}: catalogue interim_path should be {p['sources']}")
    return problems

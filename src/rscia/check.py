"""Report which inputs exist and which are still missing."""
from __future__ import annotations

import pandas as pd

from .config import Config
from .pipeline import _bio_oracle_path, climate_futures


def check_inputs(cfg: Config) -> pd.DataFrame:
    rows = []
    grid_t = cfg.path(cfg.project["grid"]["template_raster"])
    rows.append({"type": "grid", "id": "template", "file": str(grid_t), "exists": grid_t.exists()})
    cdir = cfg.path(cfg.project["paths"]["components_dir"])
    for c in cfg.components:
        f = cdir / f"{c['id']}.tif"
        rows.append({"type": "component", "id": c["id"], "file": str(f), "exists": f.exists()})
    for p in cfg.pressures:
        if p["method"] == "climate_delta":
            files = [_bio_oracle_path(cfg, p["variable"])] + [
                _bio_oracle_path(cfg, p["variable"], s, h) for s, h in climate_futures(cfg)]
        else:
            files = [cfg.path(p["sources"])]
        for f in files:
            rows.append({"type": "pressure", "id": p["id"], "file": str(f), "exists": f.exists()})
    for sc in cfg.scenarios:
        for ch in sc.get("development") or []:
            f = cfg.path(ch["file"])
            rows.append({"type": f"scenario:{sc['id']}", "id": ch["pressure"], "file": str(f), "exists": f.exists()})
    s = cfg.path(cfg.project["paths"]["surveys_file"])
    rows.append({"type": "survey", "id": "coral_surveys", "file": str(s), "exists": s.exists()})
    df = pd.DataFrame(rows).drop_duplicates(subset=["type", "file"])
    df["file"] = df["file"].str.replace(str(cfg.root) + "/", "", regex=False)
    return df

"""Load and validate the configuration files in config/."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml


@dataclass
class Config:
    root: Path
    project: dict
    components: list[dict]
    pressures: list[dict]
    bio_oracle: dict
    scenarios: list[dict]
    sensitivity: pd.DataFrame
    sensitivity_confidence: pd.DataFrame
    warnings: list[str] = field(default_factory=list)

    # ---- convenience -------------------------------------------------
    def path(self, rel: str | None) -> Path | None:
        if rel is None:
            return None
        p = Path(rel)
        return p if p.is_absolute() else self.root / p

    @property
    def component_ids(self) -> list[str]:
        return [c["id"] for c in self.components]

    @property
    def pressure_ids(self) -> list[str]:
        return [p["id"] for p in self.pressures]

    def pressure(self, pid: str) -> dict:
        for p in self.pressures:
            if p["id"] == pid:
                return p
        raise KeyError(f"Unknown pressure '{pid}'")

    def component(self, cid: str) -> dict:
        for c in self.components:
            if c["id"] == cid:
                return c
        raise KeyError(f"Unknown component '{cid}'")

    @property
    def outputs_dir(self) -> Path:
        return self.path(self.project["paths"]["outputs_dir"])


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(root: str | Path = ".") -> Config:
    root = Path(root).resolve()
    cdir = root / "config"
    project = _read_yaml(cdir / "project.yaml")
    comps = _read_yaml(cdir / "ecosystem_components.yaml")["components"]
    pdoc = _read_yaml(cdir / "pressures.yaml")
    scen = _read_yaml(cdir / "scenarios.yaml")["scenarios"]

    sens = pd.read_csv(root / project["model"]["sensitivity_matrix"], index_col=0)
    conf_path = root / project["model"]["sensitivity_confidence"]
    conf = pd.read_csv(conf_path, index_col=0) if conf_path.exists() else None

    cfg = Config(
        root=root,
        project=project,
        components=comps,
        pressures=pdoc["pressures"],
        bio_oracle=pdoc.get("bio_oracle", {}),
        scenarios=scen,
        sensitivity=sens,
        sensitivity_confidence=conf,
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    errors = []
    for kind, ids in (("component", cfg.component_ids), ("pressure", cfg.pressure_ids)):
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            errors.append(f"Duplicate {kind} ids: {sorted(dupes)}")

    s = cfg.sensitivity
    missing_rows = set(cfg.pressure_ids) - set(s.index)
    missing_cols = set(cfg.component_ids) - set(s.columns)
    if missing_rows:
        errors.append(f"Sensitivity matrix missing pressure rows: {sorted(missing_rows)}")
    if missing_cols:
        errors.append(f"Sensitivity matrix missing component columns: {sorted(missing_cols)}")
    extra = (set(s.index) - set(cfg.pressure_ids)) | (set(s.columns) - set(cfg.component_ids))
    if extra:
        cfg.warnings.append(f"Sensitivity matrix has unused entries (ignored): {sorted(extra)}")
    vals = s.to_numpy(dtype=float)
    if (vals < 0).any() or (vals > 1).any():
        errors.append("Sensitivity scores must be between 0 and 1")

    if cfg.sensitivity_confidence is None:
        cfg.warnings.append("No sensitivity confidence file; confidence set to 1 (low)")
        cfg.sensitivity_confidence = (s > 0).astype(int)

    for p in cfg.pressures:
        m = p.get("method")
        if m not in {"decay", "footprint", "density", "direct", "climate_delta"}:
            errors.append(f"Pressure {p['id']}: unknown method '{m}'")
        if m == "climate_delta" and p.get("direction") not in {"increase", "decrease", "absolute"}:
            errors.append(f"Pressure {p['id']}: direction must be increase, decrease or absolute")

    for sc in cfg.scenarios:
        for ch in sc.get("development") or []:
            if ch["pressure"] not in cfg.pressure_ids:
                errors.append(f"Scenario {sc['id']}: unknown pressure '{ch['pressure']}'")
            if ch["mode"] not in {"add_sources", "replace_raster", "add_raster"}:
                errors.append(f"Scenario {sc['id']}: unknown mode '{ch['mode']}'")

    if errors:
        raise ValueError("Configuration errors:\n  " + "\n  ".join(errors))

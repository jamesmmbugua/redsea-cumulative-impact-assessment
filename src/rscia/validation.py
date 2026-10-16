"""Validate modelled impact against coral reef survey sites."""
from __future__ import annotations

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from scipy.stats import spearmanr

from .config import Config
from .grid import Grid
from .reporting import run_dir

# Expected sign of the correlation between impact and each condition metric
EXPECTED = {
    "live_coral_cover_pct": -1,
    "recent_mortality_pct": +1,
    "bleaching_pct": +1,
    "macroalgae_cover_pct": +1,
    "coral_genera_richness": -1,
    "fish_biomass_kg_ha": -1,
}


def load_surveys(cfg: Config, grid: Grid) -> pd.DataFrame:
    f = cfg.path(cfg.project["paths"]["surveys_file"])
    if not f.exists():
        raise FileNotFoundError(f"Survey file not found: {f} (see config/templates/coral_surveys_template.csv)")
    df = pd.read_csv(f)
    for col in ("site_id", "latitude", "longitude"):
        if col not in df.columns:
            raise ValueError(f"Survey file needs column '{col}'")
    tr = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    x, y = tr.transform(df.longitude.to_numpy(), df.latitude.to_numpy())
    r, c = grid.rowcol(x, y)
    inside = (r >= 0) & (r < grid.height) & (c >= 0) & (c < grid.width)
    inside[inside] = grid.mask[r[inside], c[inside]]
    df["row"], df["col"], df["in_grid"] = r, c, inside
    return df


def _sample(path, df) -> pd.DataFrame:
    with rasterio.open(path) as src:
        arr = src.read(masked=True).filled(np.nan)
        names = [d or f"band{i+1}" for i, d in enumerate(src.descriptions)]
    ok = df.in_grid.to_numpy()
    vals = np.full((len(df), arr.shape[0]), np.nan)
    vals[ok] = arr[:, df.row[ok], df.col[ok]].T
    return pd.DataFrame(vals, columns=names, index=df.index)


def validate(cfg: Config, grid: Grid, run_id: str = "S0_baseline") -> pd.DataFrame:
    d = run_dir(cfg, run_id)
    df = load_surveys(cfg, grid)
    df["impact_total"] = _sample(d / "impact_total.tif", df).iloc[:, 0]
    df["confidence"] = _sample(d / "confidence.tif", df).iloc[:, 0]
    byp = _sample(d / "impact_by_pressure.tif", df).add_prefix("p_")
    df = pd.concat([df, byp], axis=1)

    # coral layer ground truth
    coral_f = cfg.component_file("coral_shallow")
    if coral_f.exists():
        df["coral_layer_value"] = grid.read(coral_f, "nearest")[df.row.clip(0, grid.height - 1), df.col.clip(0, grid.width - 1)]
        df.loc[~df.in_grid, "coral_layer_value"] = np.nan

    rows = []
    v = df[df.in_grid]
    for metric, sign in EXPECTED.items():
        if metric not in v.columns:
            continue
        sub = v[["impact_total", metric]].dropna()
        if len(sub) < 5:
            continue
        rho, p = spearmanr(sub.impact_total, sub[metric])
        agrees = bool(np.sign(rho) == sign) if np.isfinite(rho) else False
        rows.append({"metric": metric, "n_sites": len(sub), "spearman_rho": rho, "p_value": p,
                     "expected_sign": "+" if sign > 0 else "-", "direction_as_expected": agrees,
                     "significant_0.05": bool(p < 0.05)})
    summary = pd.DataFrame(rows)

    out = d / "validation"
    out.mkdir(exist_ok=True)
    df.drop(columns=["row", "col"]).to_csv(out / "validation_sites.csv", index=False)
    summary.to_csv(out / "validation_summary.csv", index=False)
    _write_report(out, run_id, df, summary)
    return summary


def _write_report(out, run_id, df, summary) -> None:
    n, n_in = len(df), int(df.in_grid.sum())
    lines = [f"# Validation against coral survey sites: {run_id}", "",
             f"Sites in file: {n}. Sites inside the study grid: {n_in}.", ""]
    if "coral_layer_value" in df:
        hit = int((df.loc[df.in_grid, "coral_layer_value"] > 0).sum())
        lines += [f"Coral layer check: {hit} of {n_in} surveyed sites fall in cells mapped as shallow coral.", ""]
    if summary.empty:
        lines.append("Not enough survey metrics to compute correlations.")
    else:
        lines += ["| Metric | n | Spearman rho | p | Expected | As expected |", "|---|---|---|---|---|---|"]
        for _, r in summary.iterrows():
            lines.append(f"| {r.metric} | {r.n_sites} | {r.spearman_rho:.2f} | {r.p_value:.3f} | {r.expected_sign} | {'yes' if r.direction_as_expected else 'no'} |")
        lines += ["", "Sites with the largest disagreement (high impact but high coral cover, or the reverse)",
                  "are listed by rank difference in validation_sites.csv and are the first places to",
                  "review pressure layers and sensitivity scores."]
    if "live_coral_cover_pct" in df:
        v = df[df.in_grid].dropna(subset=["impact_total", "live_coral_cover_pct"]).copy()
        if len(v):
            v["rank_gap"] = (v.impact_total.rank(pct=True) - (1 - v.live_coral_cover_pct.rank(pct=True))).abs()
            top = v.sort_values("rank_gap", ascending=False).head(10)
            lines += ["", "| Site | Impact | Live coral % | Rank gap |", "|---|---|---|---|"]
            for _, r in top.iterrows():
                lines.append(f"| {r.site_id} | {r.impact_total:.2f} | {r.live_coral_cover_pct:.1f} | {r.rank_gap:.2f} |")
    (out / "validation_report.md").write_text("\n".join(lines) + "\n")

"""Quick-look PNG maps and charts. For publication maps use QGIS with the GeoTIFF outputs."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .reporting import run_dir  # noqa: E402


def _extent(grid):
    t = grid.transform
    return (t.c / 1000, (t.c + grid.width * t.a) / 1000, (t.f + grid.height * t.e) / 1000, t.f / 1000)


def quicklook_maps(cfg, grid, run_ids, baseline_id="S0_baseline") -> None:
    out = cfg.outputs_dir / "maps"
    out.mkdir(parents=True, exist_ok=True)
    ext = _extent(grid)
    totals = {r: grid.read(run_dir(cfg, r) / "impact_total.tif", "nearest") for r in run_ids
              if (run_dir(cfg, r) / "impact_total.tif").exists()}
    if not totals:
        return
    vmax = np.nanpercentile(np.concatenate([v[np.isfinite(v)] for v in totals.values()]), 99.5)

    for r, a in totals.items():
        fig, ax = plt.subplots(figsize=(6, 7))
        im = ax.imshow(a, extent=ext, cmap="magma_r", vmin=0, vmax=vmax)
        ax.set_title(f"Cumulative impact: {r}", fontsize=10)
        ax.set_xlabel("km (Albers)"); ax.set_ylabel("km (Albers)")
        fig.colorbar(im, ax=ax, shrink=0.7, label="impact score")
        fig.tight_layout(); fig.savefig(out / f"impact_{r}.png", dpi=130); plt.close(fig)

        if r != baseline_id and baseline_id in totals:
            d = a - totals[baseline_id]
            lim = np.nanpercentile(np.abs(d[np.isfinite(d)]), 99.5) or 1e-6
            fig, ax = plt.subplots(figsize=(6, 7))
            im = ax.imshow(d, extent=ext, cmap="RdBu_r", vmin=-lim, vmax=lim)
            ax.set_title(f"Change vs baseline: {r}", fontsize=10)
            fig.colorbar(im, ax=ax, shrink=0.7, label="impact change")
            fig.tight_layout(); fig.savefig(out / f"change_{r}.png", dpi=130); plt.close(fig)

    # baseline contributions
    f = run_dir(cfg, baseline_id) / "summary_by_pressure.csv"
    if f.exists():
        sp = pd.read_csv(f).sort_values("impact")
        sp = sp[sp.impact > 0]
        fig, ax = plt.subplots(figsize=(7, 6))
        colors = ["#c0504d" if k == "climate" else "#4f81bd" for k in sp.kind]
        ax.barh(sp.name, sp.share_pct, color=colors)
        ax.set_xlabel("share of total impact (%)")
        ax.set_title("Baseline impact by pressure (blue local, red climate)", fontsize=10)
        fig.tight_layout(); fig.savefig(out / "baseline_pressure_contributions.png", dpi=130); plt.close(fig)

    # scenario totals
    f = cfg.outputs_dir / "comparisons" / "all_runs_summary.csv"
    if f.exists():
        t = pd.read_csv(f)
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.barh(t.run, t.change_pct, color="#4f81bd")
        ax.axvline(0, color="k", lw=0.8)
        ax.set_xlabel("change in total impact vs baseline (%)")
        ax.invert_yaxis()
        fig.tight_layout(); fig.savefig(out / "scenario_change.png", dpi=130); plt.close(fig)

"""Cumulative impact calculation."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ImpactResult:
    total: np.ndarray                  # (rows, cols)
    by_pressure: np.ndarray            # (n_pressures, rows, cols)
    by_component: np.ndarray           # (n_components, rows, cols)
    pressure_ids: list[str]
    component_ids: list[str]
    confidence: np.ndarray             # impact-weighted confidence, 1 (low) to 3 (high)
    component_count: np.ndarray        # components present per cell

    def pressure_totals(self) -> pd.Series:
        return pd.Series(np.nansum(self.by_pressure, axis=(1, 2)), index=self.pressure_ids)

    def component_totals(self) -> pd.Series:
        return pd.Series(np.nansum(self.by_component, axis=(1, 2)), index=self.component_ids)


def cumulative_impact(pressures: dict[str, np.ndarray], components: dict[str, np.ndarray],
                      sensitivity: pd.DataFrame, mask: np.ndarray,
                      sensitivity_confidence: pd.DataFrame | None = None,
                      pressure_confidence: dict[str, float] | None = None,
                      component_confidence: dict[str, float] | None = None) -> ImpactResult:
    """Impact = sum_p sum_c P_p x E_c x S_pc.

    Layers are 0 to 1 arrays on the same grid. NaN inside the mask is treated as 0.
    Confidence per pair is the mean of sensitivity confidence and the data confidence of
    the pressure and component (each 1 to 3); the cell value is the impact-weighted mean.
    """
    pids, cids = list(pressures), list(components)
    shape = mask.shape
    by_p = np.zeros((len(pids), *shape), dtype="float32")
    by_c = np.zeros((len(cids), *shape), dtype="float32")
    conf_num = np.zeros(shape, dtype="float64")

    P = {k: np.nan_to_num(v, nan=0.0) for k, v in pressures.items()}
    E = {k: np.nan_to_num(v, nan=0.0) for k, v in components.items()}
    pconf = pressure_confidence or {}
    cconf = component_confidence or {}

    for i, p in enumerate(pids):
        for j, c in enumerate(cids):
            s = float(sensitivity.at[p, c]) if (p in sensitivity.index and c in sensitivity.columns) else 0.0
            if s <= 0:
                continue
            contrib = P[p] * E[c] * s
            by_p[i] += contrib
            by_c[j] += contrib
            sc = 1.0
            if sensitivity_confidence is not None and p in sensitivity_confidence.index:
                sc = max(float(sensitivity_confidence.at[p, c]), 1.0)
            pair_conf = (sc + pconf.get(p, 2.0) + cconf.get(c, 2.0)) / 3.0
            conf_num += contrib * pair_conf

    total = by_p.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        confidence = np.where(total > 0, conf_num / total, np.nan).astype("float32")
    count = np.zeros(shape, dtype="float32")
    for v in E.values():
        count += (v > 0)

    for a in (total, confidence, count):
        a[~mask] = np.nan
    by_p[:, ~mask] = np.nan
    by_c[:, ~mask] = np.nan
    return ImpactResult(total, by_p, by_c, pids, cids, confidence, count)

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
    rarity_adjusted: np.ndarray | None = None   # impact with each component divided by its commonness

    def pressure_totals(self) -> pd.Series:
        return pd.Series(np.nansum(self.by_pressure, axis=(1, 2)), index=self.pressure_ids)

    def component_totals(self) -> pd.Series:
        return pd.Series(np.nansum(self.by_component, axis=(1, 2)), index=self.component_ids)


def commonness(components: dict[str, np.ndarray], mask: np.ndarray) -> dict[str, float]:
    """Share of the study area occupied by each component (mean value over all cells)."""
    n = float(mask.sum())
    return {k: float(np.nansum(np.where(mask, v, 0)) / n) if n else 0.0 for k, v in components.items()}


def _score(matrix: pd.DataFrame | None, p: str, c: str, default: float = 0.0) -> float:
    if matrix is None or p not in matrix.index or c not in matrix.columns:
        return default
    v = matrix.at[p, c]
    return float(v) if pd.notna(v) else default


def cumulative_impact(pressures: dict[str, np.ndarray], components: dict[str, np.ndarray],
                      sensitivity: pd.DataFrame | dict, mask: np.ndarray,
                      sensitivity_confidence: pd.DataFrame | None = None,
                      pressure_confidence: dict[str, float] | None = None,
                      component_confidence: dict[str, float] | None = None,
                      regions: np.ndarray | None = None,
                      rarity: dict[str, float] | None = None,
                      rarity_min_share: float = 0.0) -> ImpactResult:
    """Impact = sum_p sum_c P_p x E_c x S_pc.

    `sensitivity` is either one matrix, or a dict {region id: (matrix, confidence matrix)}
    used together with `regions`, a raster of region ids. Each cell then uses the matrix
    of its own region (id 0 for cells outside all regions).

    `rarity`, if given, maps each component to its commonness (share of the study area).
    A rarity-adjusted layer is then also returned, in which each component's impact is
    divided by its commonness. Components with commonness <= rarity_min_share are left
    out of that layer.

    Confidence per pair is the mean of sensitivity confidence and the data confidence of
    the pressure and component (each 1 to 3); the cell value is the impact-weighted mean.
    """
    pids, cids = list(pressures), list(components)
    shape = mask.shape

    if isinstance(sensitivity, dict):
        regional = sensitivity
    else:
        regional = {0: (sensitivity, sensitivity_confidence)}
    if regions is None or len(regional) == 1:
        region_masks = {next(iter(regional)): np.ones(shape, bool)}
    else:
        region_masks = {rid: regions == rid for rid in regional}

    by_p = np.zeros((len(pids), *shape), dtype="float32")
    by_c = np.zeros((len(cids), *shape), dtype="float32")
    rar = np.zeros(shape, dtype="float32") if rarity is not None else None
    conf_num = np.zeros(shape, dtype="float64")

    P = {k: np.nan_to_num(v, nan=0.0) for k, v in pressures.items()}
    E = {k: np.nan_to_num(v, nan=0.0) for k, v in components.items()}
    pconf = pressure_confidence or {}
    cconf = component_confidence or {}

    for i, p in enumerate(pids):
        for j, c in enumerate(cids):
            S = np.zeros(shape, dtype="float32")   # sensitivity map for this pair
            K = np.ones(shape, dtype="float32")    # sensitivity confidence map
            for rid, rmask in region_masks.items():
                smat, cmat = regional[rid]
                s = _score(smat, p, c)
                if s > 0:
                    S[rmask] = s
                    K[rmask] = max(_score(cmat, p, c, 1.0), 1.0)
            if not S.any():
                continue
            contrib = P[p] * E[c] * S
            by_p[i] += contrib
            by_c[j] += contrib
            if rar is not None and rarity.get(c, 0) > rarity_min_share:
                rar += contrib / rarity[c]
            pair_conf = (K + pconf.get(p, 2.0) + cconf.get(c, 2.0)) / 3.0
            conf_num += contrib * pair_conf

    total = by_p.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        confidence = np.where(total > 0, conf_num / total, np.nan).astype("float32")
    count = np.zeros(shape, dtype="float32")
    for v in E.values():
        count += (v > 0)

    for a in (total, confidence, count) + ((rar,) if rar is not None else ()):
        a[~mask] = np.nan
    by_p[:, ~mask] = np.nan
    by_c[:, ~mask] = np.nan
    return ImpactResult(total, by_p, by_c, pids, cids, confidence, count, rar)


def scale_0_100(arr: np.ndarray, reference: float) -> np.ndarray:
    """Express impact on a 0 to 100 scale where 100 = the reference (baseline percentile).

    Values above the reference are kept (they can exceed 100), so increases in scenarios
    stay visible.
    """
    if not reference or reference <= 0:
        return np.full_like(arr, np.nan)
    return (100.0 * arr / reference).astype("float32")

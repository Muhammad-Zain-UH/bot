"""Second-moment statistics that never form the mean of the series (blinded power checks).

All moments come from differences between observations:
    gamma_0 = sum_ij (x_i - x_j)^2 / (2 n^2)                 (= the 1/n sample variance)
    gamma_k = gamma_0 - sum_t (x_t - x_{t-k})^2 / (2 (n - k))  (variogram form of the lag-k autocovariance)
so a mean, cumulative or annualised return of `x` is never computed.
"""
from __future__ import annotations

import math

import numpy as np

Z_ALPHA = 2.128                        # one-sided alpha = 0.05 / 3
Z_POWER = 0.842                        # 80 % power


def gamma0(x) -> float:
    x = np.asarray(x, dtype=float)
    d = x[:, None] - x[None, :]
    return float((d * d).sum() / (2 * len(x) ** 2))


def autocov(x, k: int) -> float:
    x = np.asarray(x, dtype=float)
    if k == 0:
        return gamma0(x)
    v = x[k:] - x[:-k]
    return gamma0(x) - float((v * v).sum() / (2 * (len(x) - k)))


def sd(x) -> float:
    """Sample standard deviation (n - 1 in the denominator)."""
    n = len(x)
    return math.sqrt(gamma0(x) * n / (n - 1))


def autocorr(x, k: int = 1) -> float:
    return autocov(x, k) / gamma0(x)


def nw_se(x, lags: int = 3) -> float:
    """Newey-West (Bartlett weights) standard error of the mean of x, from autocovariances only."""
    s = gamma0(x) + 2 * sum((1 - k / (lags + 1)) * autocov(x, k) for k in range(1, lags + 1))
    return math.sqrt(max(s, 0.0) / len(x))


def normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def power_summary(se: float, e_ref: float) -> dict:
    """MDE = (z_alpha + z_power) x SE; power of the one-sided test at the reference effect."""
    mde = (Z_ALPHA + Z_POWER) * se
    return {"se": se, "mde": mde, "e_ref": e_ref, "mde_over_e_ref": mde / e_ref,
            "power_at_e_ref": normal_cdf(e_ref / se - Z_ALPHA), "verdict": "TESTABLE" if mde <= e_ref else "UNDERPOWERED"}

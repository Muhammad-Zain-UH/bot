"""H-PSX-01 results statistics on synthetic series (no PSX data)."""
import math
import unittest

import numpy as np
import pandas as pd

from psx.strategy import h_psx01 as h
from psx.strategy import results_h_psx01 as R
from psx.tests.test_h_psx01 import DAYS, make_panel

MONTHS = pd.period_range("2015-01", "2026-09", freq="M")


class TestInference(unittest.TestCase):
    def test_newey_west(self):
        x = np.array([0.03, -0.01, 0.02, 0.05, -0.04, 0.01, 0.00, 0.02])
        self.assertAlmostEqual(R.nw_se(x, 0), np.std(x) / math.sqrt(len(x)))
        d, n = x - x.mean(), len(x)
        g = lambda k: d[k:] @ d[:len(d) - k] / n
        want = math.sqrt((g(0) + 2 * (0.75 * g(1) + 0.5 * g(2) + 0.25 * g(3))) / n)
        self.assertAlmostEqual(R.nw_se(x, 3), want)

    def test_student_t_tail(self):
        self.assertAlmostEqual(R.t_sf(1.0, 1), 0.25, places=10)                         # Cauchy
        self.assertAlmostEqual(R.t_sf(2.0, 2), 0.5 * (1 - 2 / math.sqrt(6)), places=10)
        self.assertAlmostEqual(R.t_sf(2.228, 10), 0.025, places=3)
        self.assertAlmostEqual(R.t_sf(0.0, 7), 0.5)
        self.assertAlmostEqual(R.t_sf(-1.3, 7), 1 - R.t_sf(1.3, 7))
        self.assertAlmostEqual(R.t_sf(1.96, 1e6), 0.025, places=4)

    def test_mean_test(self):
        x = np.array([0.02, 0.01, 0.03, -0.01, 0.02])
        res = R.mean_test(x)
        self.assertAlmostEqual(res["t"], x.mean() / R.nw_se(x))
        self.assertAlmostEqual(res["p_one_sided"], R.t_sf(res["t"], 4))

    def test_sharpe_lo(self):
        rng = np.random.default_rng(5)
        x = rng.normal(0.01, 0.04, 20000)
        s = R.sharpe_lo(x, lags=0)
        self.assertAlmostEqual(s["eta"], math.sqrt(12))
        sr = s["sharpe_monthly"]
        self.assertAlmostEqual(s["se_monthly"], math.sqrt((1 + sr * sr / 2) / len(x)), delta=0.0003)
        s3 = R.sharpe_lo(x, lags=3)
        self.assertAlmostEqual(s3["sharpe_annual"], s3["eta"] * sr)
        self.assertEqual(len(s3["rho"]), 3)


class TestRules(unittest.TestCase):
    def series(self, a, b, c):
        return np.array([a] * 48 + [b] * 48 + [c] * 45)

    def test_eras_and_checks(self):
        x = self.series(0.01, 0.01, 0.002)
        eras = R.era_table(MONTHS, x)
        self.assertEqual([e["months"] for e in eras], [48, 48, 45])
        self.assertAlmostEqual(eras[0]["share_of_total"], 0.48 / (0.96 + 0.09))
        self.assertFalse(R.robustness(0.001, 0.002, R.era_table(MONTHS, self.series(0.01, 0.01, -0.005)))
                         ["no_era_over_60pct"])                                            # 0.48 / 0.735 = 65 %
        c = R.robustness(0.001, 0.002, eras)
        self.assertEqual(c, {"cost_2x_mean_ge_0": True, "delist_30_mean_gt_0": True,
                             "positive_in_2_of_3_eras": True, "no_era_over_60pct": True})
        self.assertFalse(R.robustness(0.001, 0.002, R.era_table(MONTHS, self.series(0.02, 0.001, 0.001)))["no_era_over_60pct"])
        neg = R.era_table(MONTHS, self.series(-0.01, 0.001, 0.001))
        self.assertFalse(R.robustness(0.0, 0.0, neg)["no_era_over_60pct"])                 # total <= 0 fails
        self.assertFalse(R.robustness(-1e-9, 0.002, eras)["cost_2x_mean_ge_0"])
        self.assertTrue(R.robustness(0.0, 0.002, eras)["cost_2x_mean_ge_0"])
        self.assertFalse(R.robustness(0.0, 0.0, eras)["delist_30_mean_gt_0"])

    def test_verdict(self):
        ok = {"a": True, "b": True}
        self.assertEqual(R.verdict(0.01, 0.004, ok), "SUPPORTED")
        self.assertEqual(R.verdict(0.05, 0.004, ok), "WEAK SUPPORT")
        self.assertEqual(R.verdict(0.001, 0.004, {"a": True, "b": False}), "NOT SUPPORTED")
        self.assertEqual(R.verdict(0.6, -0.001, ok), "NOT SUPPORTED")
        self.assertEqual(R.verdict(R.ALPHA, 0.004, ok), "WEAK SUPPORT")                    # p must be below alpha

    def test_cagr_and_drawdown(self):
        r = [0.1, -0.5, 0.2]
        self.assertAlmostEqual(R.max_drawdown(r), 0.5)
        self.assertAlmostEqual(R.cagr(r), 0.66 ** 4 - 1)
        self.assertAlmostEqual(R.max_drawdown([-0.1, 0.05]), 0.1)                           # from the start value


class TestBasisReplica(unittest.TestCase):
    d = DAYS[:6]

    def plans(self, a, b):
        return [h.MonthPlan(pd.Period("2019-01", "M"), 0, 1, 3, np.array(a)),
                h.MonthPlan(pd.Period("2019-02", "M"), 2, 3, 5, np.array(b))]

    def test_same_returns_as_the_pinned_engine(self):
        cases = [({"A": [10, 11, 11, 11, 11, 11], "B": [10, 10, 10, 9, 9.5, 9.5]}, ([0, 1], [0])),
                 ({"A": [10, 10, 10, 10, 10, 10], "D": [10, 10, 12, None, None, None]}, ([0, 1], [0, 1])),
                 ({"A": [10, 10, 15, 20, 20, 20], "B": [10, 10, 10, 10, 10, 10]}, ([0, 1], [1]))]
        for paths, (a, b) in cases:
            P = make_panel(paths, self.d)
            np.testing.assert_allclose(R.simulate_basis(P, self.plans(a, b))["ret_net"],
                                       h.simulate(P, self.plans(a, b))["ret_net"], rtol=0, atol=1e-12)

    def test_realised_gain_of_a_full_exit(self):
        P = make_panel({"A": [10, 10, 15, 20, 20, 20], "B": [10, 10, 10, 10, 10, 10]}, self.d)
        sb = R.simulate_basis(P, self.plans([0, 1], [1]))
        r = h.cost_rate(10.0, h.SPREAD_FLOOR)
        s = 1 / (1 + r)                                          # month 1: half the cash into each name
        bought, basis = 0.5 * s, 0.5 * s * (1 + r)
        sold = bought * 2                                        # A doubled by the second execution
        r20 = h.cost_rate(20.0, h.SPREAD_FLOOR)
        self.assertAlmostEqual(sb["realised"].iloc[0], 0.0)
        self.assertGreater(sb["realised"].iloc[1], 0)
        self.assertAlmostEqual(sb["realised"].iloc[1], sold * (1 - r20) - basis, places=12)

    def test_after_tax(self):
        sb = pd.DataFrame({"month": ["2019-11", "2019-12", "2020-01"], "ret_net": [0.1, 0.0, -0.05],
                           "realised": [0.2, -0.05, 0.3], "value_start": [1.0, 1.1, 1.1]})
        at = R.after_tax_by_year(sb)
        self.assertAlmostEqual(at[0]["pre_tax"], 0.1)
        self.assertAlmostEqual(at[0]["tax_drag"], 0.15 * 0.15)
        self.assertAlmostEqual(at[1]["after_tax"], -0.05 - 0.15 * 0.3 / 1.1)


if __name__ == "__main__":
    unittest.main()

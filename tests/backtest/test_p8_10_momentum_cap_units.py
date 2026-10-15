"""P8-10 -- the REGIME_SCALP momentum cap must compare like units.

``_check_regime_scalp_momentum`` check 4 measures how far price has run from the
structural break level and refuses an entry that has run too far. It computes::

    distance_pips    = abs(last_close - break_reference) / pip_size   -> PIPS
    max_allowed_pips = 1.2 * m5_atr / pip_size                        -> PIPS

``break_reference`` is a swing price and ``m5_atr`` resolves to ``atr_14``, a
price-based ATR, so both are quote-currency dollars. Before this repair the right
side was ``1.2 * m5_atr`` -- dollars compared against pips, which rejected at
``10 x D > 1.2 x A`` instead of ``D > 1.2 x A`` and so was ten times tighter than
the same-unit comparison its own variable name claimed.

**What these tests do and do not establish.** They pin the *dimensional*
contract: the boundary sits at ``1.2 * ATR / pip_size``, and a distance inside it
is admitted. They say nothing about whether the author historically intended pips
or dollars -- that remains unresolved and is recorded as such in
``docs/PHASE_8_RESEARCH_LEDGER.md``. They say nothing about profitability, signal
count or any performance property, and no such measure may be used to change
them.

**These tests fail under the old implementation**, deliberately and by
construction: ``test_the_fixture_discriminates_against_the_old_cap`` asserts
numerically that the admitted distance exceeds the old dollar-valued cap, so a
regression to ``1.2 * m5_atr`` turns the admitting cases red. That is asserted
from measured behaviour, never from matching source text -- the P8-15 lesson,
where two pins written against an implementation's spelling silently missed a
repair.

The seam is ``_check_regime_scalp_momentum`` itself, called directly. Checks 1-3
(sustained direction, volume, RSI band) are satisfied by construction so that
check 4 is the only thing under test; ``test_checks_one_to_three_pass_without_the_cap``
asserts that premise rather than assuming it.
"""

from __future__ import annotations

import unittest

import pandas as pd

import main_production

PIP_SIZE = 0.10  # XAUUSD, as check 4 uses
ATR = 5.0        # -> corrected cap 1.2 * 5.0 / 0.10 = 60.0 pips
CORRECTED_CAP_PIPS = 1.2 * ATR / PIP_SIZE
OLD_CAP_PIPS = 1.2 * ATR  # the pre-repair expression, in dollars but read as pips

# Deltas chosen so RSI-14 lands inside each side's band and the final three
# closes move monotonically in the breakout direction:
#   BUY  -> 5 losses then 9 gains -> RSI 64.29, band 55-75
#   SELL -> 5 gains then 9 losses -> RSI 35.71, band 25-45
_BUY_DELTAS = [0.0] * 7 + [-1.0] * 5 + [1.0] * 9
_SELL_DELTAS = [0.0] * 7 + [1.0] * 5 + [-1.0] * 9


def _frame(deltas: list[float], start: float = 4000.0) -> pd.DataFrame:
    """22 M5 bars whose last candle clears the volume baseline."""
    closes = [start]
    for delta in deltas:
        closes.append(closes[-1] + delta)
    return pd.DataFrame({
        "open": closes,
        "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes],
        "close": closes,
        "tick_volume": [100.0] * (len(closes) - 1) + [200.0],
    })


def _break_reference(frame: pd.DataFrame, side: str, distance_dollars: float) -> float:
    """A break level `distance_dollars` behind the last close, on the right side.

    BUY breaks *above* its last swing high, SELL *below* its last swing low, so
    the reference sits behind price in the direction of travel.
    """
    last_close = float(frame["close"].iloc[-1])
    return last_close - distance_dollars if side == "BUY" else last_close + distance_dollars


def _check(side: str, distance_dollars: float | None):
    frame = _frame(_BUY_DELTAS if side == "BUY" else _SELL_DELTAS)
    reference = None if distance_dollars is None else _break_reference(frame, side, distance_dollars)
    return main_production._check_regime_scalp_momentum(frame, side, reference, ATR)


class TheFixtureIsolatesCheckFour(unittest.TestCase):
    """Assert the premises, so a pass cannot be an accident of checks 1-3."""

    def test_checks_one_to_three_pass_without_the_cap(self) -> None:
        """With no break reference, check 4 is skipped entirely."""
        for side in ("BUY", "SELL"):
            with self.subTest(side=side):
                ok, reason = _check(side, None)
                self.assertTrue(ok, f"checks 1-3 do not pass, so check 4 is not isolated: {reason}")

    def test_the_fixture_discriminates_against_the_old_cap(self) -> None:
        """The admitted distance must exceed the old dollar-valued cap.

        This is what makes the admitting cases fail if production regresses to
        ``1.2 * m5_atr``. Asserted numerically from the fixture, not by reading
        the source.
        """
        admitted_pips = 30.0  # the inside case below, in pips
        self.assertLessEqual(admitted_pips, CORRECTED_CAP_PIPS)
        self.assertGreater(
            admitted_pips, OLD_CAP_PIPS,
            "the fixture no longer distinguishes the corrected cap from the old one",
        )


class TheCapComparesLikeUnits(unittest.TestCase):
    """The boundary sits at 1.2 x ATR / pip_size, measured in pips."""

    def test_a_distance_inside_the_corrected_cap_is_admitted(self) -> None:
        """30 pips against a 60-pip cap. Rejected by the old 6-'pip' cap."""
        for side in ("BUY", "SELL"):
            with self.subTest(side=side):
                ok, reason = _check(side, 3.0)
                self.assertTrue(
                    ok,
                    "a distance inside the same-unit cap was refused -- the cap is "
                    f"comparing pips against dollars again: {reason}",
                )

    def test_a_distance_outside_the_corrected_cap_is_refused(self) -> None:
        """70 pips against a 60-pip cap, and refused *by check 4*."""
        for side in ("BUY", "SELL"):
            with self.subTest(side=side):
                ok, reason = _check(side, 7.0)
                self.assertFalse(ok)
                self.assertIn("pip cap", reason, f"refused by a different check: {reason}")
                self.assertIn(f"{CORRECTED_CAP_PIPS:.1f} pip cap", reason)

    def test_the_boundary_is_exactly_one_point_two_atr_in_pips(self) -> None:
        """At the cap admits; a hair past it refuses. This pins the unit relation."""
        at_cap_dollars = CORRECTED_CAP_PIPS * PIP_SIZE          # 6.00 -> 60.0 pips
        past_cap_dollars = at_cap_dollars + PIP_SIZE / 100.0    # 6.001 -> 60.01 pips
        for side in ("BUY", "SELL"):
            with self.subTest(side=side, case="at the cap"):
                ok, reason = _check(side, at_cap_dollars)
                self.assertTrue(ok, f"the boundary is not inclusive at the cap: {reason}")
            with self.subTest(side=side, case="past the cap"):
                ok, reason = _check(side, past_cap_dollars)
                self.assertFalse(ok, "a distance beyond the cap was admitted")
                self.assertIn("pip cap", reason)

    def test_the_cap_scales_with_atr_in_the_same_units(self) -> None:
        """Doubling ATR doubles the cap in pips -- the relation, not a constant."""
        frame = _frame(_BUY_DELTAS)
        reference = _break_reference(frame, "BUY", 9.0)  # 90 pips
        refused, reason = main_production._check_regime_scalp_momentum(frame, "BUY", reference, ATR)
        self.assertFalse(refused, f"90 pips should exceed a 60-pip cap: {reason}")
        admitted, reason = main_production._check_regime_scalp_momentum(frame, "BUY", reference, ATR * 2)
        self.assertTrue(
            admitted,
            f"doubling ATR did not double the cap, so the units do not track: {reason}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

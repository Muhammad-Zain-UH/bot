"""Hand-computable bar fixtures for indicator tests.

The ATR fixture below is deliberately small enough that its expected value can be
derived on paper and checked in the test alongside the assertion. A golden number
nobody can re-derive is a number nobody can trust.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

__all__ = [
    "ATR_FIXTURE_EXPECTED",
    "FLAT_BARS",
    "atr_fixture_bars",
    "make_bars",
    "simple_bars",
]

UTC = timezone.utc


def make_bars(
    rows: list[tuple[float, float, float, float]],
    *,
    start: datetime | None = None,
    minutes: int = 5,
    volume: float = 100.0,
    with_time: bool = True,
) -> pd.DataFrame:
    """Build a bar frame from ``(open, high, low, close)`` tuples.

    Args:
        rows: One tuple per bar, in chronological order.
        start: Timestamp of the first bar. Defaults to 2026-01-01 00:00 UTC.
        minutes: Spacing between bars, in minutes.
        volume: Constant ``tick_volume`` for every bar.
        with_time: Whether to include a ``time`` column.

    Returns:
        A DataFrame with ``open``, ``high``, ``low``, ``close``, ``tick_volume``
        and optionally ``time``.
    """
    first = start or datetime(2026, 1, 1, tzinfo=UTC)
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"]).astype("float64")
    frame["tick_volume"] = float(volume)
    if with_time:
        frame.insert(
            0,
            "time",
            [first + timedelta(minutes=minutes * index) for index in range(len(rows))],
        )
    return frame


def simple_bars() -> pd.DataFrame:
    """Three ascending bars with unambiguous, distinct closes.

    Useful for convention tests where the question is only *which row* was
    selected, so the values must be trivially distinguishable.
    """
    return make_bars(
        [
            (100.0, 101.0, 99.0, 100.5),
            (100.5, 102.0, 100.0, 101.5),
            (101.5, 103.0, 101.0, 102.5),
        ]
    )


FLAT_BARS: list[tuple[float, float, float, float]] = [
    (100.0, 100.0, 100.0, 100.0),
    (100.0, 100.0, 100.0, 100.0),
    (100.0, 100.0, 100.0, 100.0),
]
"""Zero-range bars. Every true range is 0, so ATR must be exactly 0 -- not NaN."""


def atr_fixture_bars() -> pd.DataFrame:
    """Six bars whose Wilder ATR(3) is computable by hand.

    Worked derivation (bar 0 has no previous close, so its true range is
    undefined and dropped)::

        bar  H       L       C       prev_C   TR = max(H-L, |H-pC|, |L-pC|)
        0    101.00   99.00  100.00  --       (dropped)
        1    103.00  100.00  102.00  100.00   max(3.00, 3.00, 0.00) = 3.00
        2    104.00  101.00  101.50  102.00   max(3.00, 2.00, 1.00) = 3.00
        3    102.00   99.00  100.00  101.50   max(3.00, 0.50, 2.50) = 3.00
        4    105.00  100.00  104.00  100.00   max(5.00, 5.00, 0.00) = 5.00
        5    106.00  103.00  105.00  104.00   max(3.00, 2.00, 1.00) = 3.00

        seed   = mean(TR_1, TR_2, TR_3) = (3 + 3 + 3) / 3 = 3.00
        step 4 = (3.00 * 2 + 5.00) / 3   = 11.00 / 3 = 3.666666...
        step 5 = (3.666666... * 2 + 3.00) / 3        = 3.444444...

    Returns:
        The bar frame described above.
    """
    return make_bars(
        [
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 103.0, 100.0, 102.0),
            (102.0, 104.0, 101.0, 101.5),
            (101.5, 102.0, 99.0, 100.0),
            (100.0, 105.0, 100.0, 104.0),
            (104.0, 106.0, 103.0, 105.0),
        ]
    )


ATR_FIXTURE_EXPECTED: float = 31.0 / 9.0
"""Wilder ATR(3) of :func:`atr_fixture_bars`, in price units.

``31/9 = 3.444444...`` -- the exact rational result of the derivation in that
function's docstring, kept exact rather than as a rounded decimal.
"""

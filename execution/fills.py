"""Fill model: spread, slippage and commission.

Every assumption here is explicit, configurable, and reported in the run
manifest. None is silently applied -- an undisclosed cost assumption is
indistinguishable from a strategy effect once it reaches a P&L figure.

Phase 2A baseline
-----------------
=============  =========  ====================================================
Parameter      Baseline   Why
=============  =========  ====================================================
spread         2.0 pips   The live feed never recorded real spread, so no
                          historical series exists. $0.20 on gold is a plausible
                          London figure; it is an assumption, not a measurement.
slippage       0.0        Zero so that slippage effects remain attributable
                          later. The model supports it; the baseline excludes it.
commission     0.0/lot    No broker schedule available for this account.
latency        0 bars     Fills occur on the next bar's open (see below).
=============  =========  ====================================================

Entry timing
------------
A decision is taken **after** a bar closes, so filling at that same close would
be look-ahead: the strategy would trade at a price it could only know once the
opportunity had passed. Entries therefore fill at the **open of the next bar**,
adjusted for spread.

Gaps are modelled honestly: if the market gaps through a stop, the fill is the
bar's open, not the stop price. Assuming a stop always fills exactly is one of
the most common ways a backtest flatters itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.symbols import SymbolSpecification
from core.types import Side
from core.units import Pips, PriceDistance

__all__ = ["DEFAULT_FILL_MODEL", "FillModel"]


@dataclass(frozen=True, slots=True)
class FillModel:
    """Transaction-cost assumptions for the simulator.

    All distances are typed :class:`~core.units.Pips` so they can never be
    confused with raw price units -- the defect class that made ten live
    thresholds 10x their intended size.

    Attributes:
        spread: Assumed bid/ask spread.
        slippage: Additional adverse price movement applied to every fill.
        commission_per_lot: Round-turn commission in account currency per lot.
        apply_spread_on_exit: Whether exits also cross the spread. ``True``
            models the round turn honestly.
    """

    spread: Pips = Pips(2.0)
    slippage: Pips = Pips(0.0)
    commission_per_lot: float = 0.0
    apply_spread_on_exit: bool = True

    def __post_init__(self) -> None:
        """Validate the model.

        Raises:
            TypeError: If ``spread`` or ``slippage`` is not :class:`Pips`. A bare
                float is ambiguous between pips and price units.
            ValueError: If any value is negative.
        """
        for name in ("spread", "slippage"):
            value = getattr(self, name)
            if not isinstance(value, Pips):
                raise TypeError(
                    f"{name} must be Pips, got {type(value).__name__}; "
                    f"a bare number is ambiguous between pips and price units"
                )
            if value.value < 0.0:
                raise ValueError(f"{name} must be >= 0, got {value.value}")
        if self.commission_per_lot < 0.0:
            raise ValueError("commission_per_lot must be >= 0")

    # ------------------------------------------------------------------

    def entry_price(
        self,
        side: Side,
        reference_price: float,
        spec: SymbolSpecification,
    ) -> float:
        """Return the fill price for an entry.

        A BUY lifts the ask and a SELL hits the bid, so both are adjusted
        **against** the trade. Slippage is applied in the same adverse
        direction -- slippage that helps is not slippage.

        Args:
            side: Trade direction.
            reference_price: The mid/bar price being filled against, typically
                the next bar's open.
            spec: Broker specification supplying ``pip_size``.

        Returns:
            The adverse-adjusted fill price.
        """
        cost = PriceDistance(
            self.spread.to_price(spec).value + self.slippage.to_price(spec).value
        )
        return reference_price + cost.value * side.sign

    def exit_price(
        self,
        side: Side,
        reference_price: float,
        spec: SymbolSpecification,
    ) -> float:
        """Return the fill price for an exit.

        Closing a BUY means selling at the bid, so the adjustment is the
        opposite sign to :meth:`entry_price` and is again adverse.

        Args:
            side: Direction of the position being closed.
            reference_price: The price being filled against.
            spec: Broker specification supplying ``pip_size``.

        Returns:
            The adverse-adjusted fill price.
        """
        cost_pips = self.slippage.value
        if self.apply_spread_on_exit:
            cost_pips += self.spread.value
        cost = Pips(cost_pips).to_price(spec)
        return reference_price - cost.value * side.sign

    def commission_for(self, volume: float) -> float:
        """Return round-turn commission for ``volume`` lots.

        Args:
            volume: Position size in lots.

        Returns:
            Commission in account currency.
        """
        return self.commission_per_lot * volume

    def describe(self) -> dict[str, float | bool | str]:
        """Return the assumptions as a dict for the run manifest.

        Returns:
            A JSON-serialisable description. Every backtest result carries this
            so no cost assumption is ever implicit.
        """
        return {
            "spread_pips": self.spread.value,
            "slippage_pips": self.slippage.value,
            "commission_per_lot": self.commission_per_lot,
            "apply_spread_on_exit": self.apply_spread_on_exit,
            "entry_timing": "next_bar_open",
            "note": (
                "Spread is an ASSUMPTION - no historical spread series exists for "
                "this account. Slippage and commission are zero in the baseline so "
                "their effects remain attributable later."
            ),
        }


DEFAULT_FILL_MODEL = FillModel()
"""The Phase 2A baseline fill model. See the module docstring."""

"""Phase 2A.1 integration tests.

These drive the **real, unmodified** production strategy
(``main_production.detect_regime`` + ``main_production.analyze_entry``) through
the Phase 2A replay infrastructure to the PaperBroker and the trade ledger.

Nothing here mocks, stubs or patches the strategy. No signal dictionary is
manufactured and no trade is inserted into the ledger by hand. Every signal
originates from the actual L1-L8 path; if the strategy declines to signal, the
test reports which layer blocked it rather than forcing one.

The only patching that occurs is ``backtest.clock_patch.frozen_clock``, which
substitutes the replay instant for the ambient wall clock inside the strategy
modules. That is Phase 2A infrastructure, it changes no logic, and it is what
makes the run deterministic.
"""

from __future__ import annotations

__all__: list[str] = []

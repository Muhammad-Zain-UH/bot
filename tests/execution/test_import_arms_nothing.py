"""Importing the strategy must not arm any path that can send an order.

The backtest imports ``main_production`` in order to call ``analyze_entry`` and
``detect_regime``. That module also contains ``graceful_shutdown()``, which calls
``mt5.order_send`` to flatten open positions. The call is legitimate in its own
context -- it is a shutdown path in the live bot -- but it must be unreachable
during a replay.

Reading the source says it is: the signal handlers are installed inside
``main()``, and the baseline never calls ``main()``. That is an argument, not a
guarantee. Adding an ``atexit.register(graceful_shutdown)`` at module scope, or
moving the ``signal.signal`` calls out of ``main()``, would silently arm the path
for every process that imports the module -- including every backtest, which
would then attempt to close positions on exit.

So the property is asserted against a real interpreter: import the module in a
subprocess and check what it armed. A subprocess is required because signal
handlers and ``atexit`` registrations are process-global and cannot be undone
once the module has been imported into the test runner.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Runs in a fresh interpreter. Reports what importing the module armed.
PROBE = """
import atexit, json, signal, sys
sys.stdout.reconfigure(encoding="utf-8")

before_handlers = {name: signal.getsignal(getattr(signal, name))
                   for name in ("SIGINT", "SIGTERM")}

# Record *what* registers an exit hook, not merely how many do. Third-party
# imports legitimately register their own (logging.shutdown and friends);
# the property under test is that none of them belongs to this project.
registered = []
_real_register = atexit.register


def _recording_register(func, *args, **kwargs):
    registered.append({
        "module": getattr(func, "__module__", None),
        "name": getattr(func, "__qualname__", repr(func)),
    })
    return _real_register(func, *args, **kwargs)


atexit.register = _recording_register

import io, contextlib
sink = io.StringIO()
with contextlib.redirect_stdout(sink):
    import main_production

atexit.register = _real_register

after_handlers = {name: signal.getsignal(getattr(signal, name))
                  for name in ("SIGINT", "SIGTERM")}

result = {
    "handlers_changed": [n for n in before_handlers
                         if before_handlers[n] is not after_handlers[n]],
    "atexit_registered": registered,
    "has_graceful_shutdown": hasattr(main_production, "graceful_shutdown"),
    "live_trading_enabled": __import__("core.safety", fromlist=["x"]).LIVE_TRADING_ENABLED,
}
sys.stderr.write("PROBE" + json.dumps(result))
"""


def _is_third_party(module: str | None) -> bool:
    """Return whether an atexit hook came from outside this project."""
    if not module:
        return False
    root = module.split(".")[0]
    return root in _THIRD_PARTY_ROOTS


_THIRD_PARTY_ROOTS = {
    "logging", "concurrent", "multiprocessing", "asyncio", "tempfile",
    "pandas", "numpy", "matplotlib", "pandas_ta", "MetaTrader5", "atexit",
    "_weakrefset", "weakref", "threading", "subprocess", "faulthandler",
    "colorama", "tqdm", "joblib", "numba", "llvmlite", "scipy",
}


class TestImportingMainProductionArmsNothing(unittest.TestCase):
    """A bare import must leave the process exactly as it found it."""

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory(prefix="zoya-probe-") as temp:
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(REPO_ROOT)
            environment["PYTHONIOENCODING"] = "utf-8"
            # Keep the probe's logging away from the production record.
            for key, name in (
                ("TRADING_BOT_LOG_FILE", "trading_bot_production.log"),
                ("TRADING_BOT_MAIN_LOG_FILE", "trading_bot_main.log"),
                ("SIGNAL_LOG_FILE", "signal_log_v2.csv"),
                ("MAIN_SIGNAL_LOG_FILE", "signal_log_main_v2.csv"),
                ("LOG_FILE", "trading_bot.log"),
            ):
                environment[key] = str(Path(temp) / name)

            completed = subprocess.run(
                [sys.executable, "-c", PROBE],
                cwd=str(REPO_ROOT), env=environment,
                capture_output=True, text=True, timeout=300,
            )

        marker = "PROBE"
        if marker not in completed.stderr:
            raise AssertionError(
                f"probe did not report (exit {completed.returncode}):\n"
                f"stdout tail: {completed.stdout[-2000:]}\n"
                f"stderr tail: {completed.stderr[-2000:]}"
            )
        cls.result = json.loads(completed.stderr.split(marker, 1)[1].strip())

    def test_the_probe_actually_imported_the_module(self) -> None:
        """Guard against a pass that only proves the import failed quietly."""
        self.assertTrue(self.result["has_graceful_shutdown"])

    def test_no_signal_handler_was_installed(self) -> None:
        self.assertEqual(
            self.result["handlers_changed"], [],
            "importing the module installed a signal handler; "
            "graceful_shutdown (which calls order_send) is now reachable on Ctrl-C",
        )

    def test_no_project_code_registered_an_atexit_hook(self) -> None:
        """Third-party hooks are fine; one belonging to this project is not.

        An ``atexit`` hook from the project could reach ``graceful_shutdown``,
        and every backtest process would then try to close positions on exit.
        """
        project_hooks = [
            hook for hook in self.result["atexit_registered"]
            if not _is_third_party(hook["module"])
        ]
        self.assertEqual(project_hooks, [], f"all hooks: {self.result['atexit_registered']}")

    def test_no_shutdown_function_was_registered(self) -> None:
        """Named explicitly, so the check does not rely on module attribution."""
        names = [hook["name"].lower() for hook in self.result["atexit_registered"]]
        for forbidden in ("graceful_shutdown", "close_all_positions", "signal_handler"):
            with self.subTest(hook=forbidden):
                self.assertNotIn(forbidden, names)

    def test_live_trading_is_still_disabled_in_a_fresh_interpreter(self) -> None:
        self.assertIs(self.result["live_trading_enabled"], False)


if __name__ == "__main__":
    unittest.main()

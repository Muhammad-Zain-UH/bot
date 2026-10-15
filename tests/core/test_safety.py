"""Tests for the execution safety lock.

The Phase 0/1 invariant is ``LIVE TRADING = DISABLED``, unconditionally. These
tests assert that the lock holds and, just as importantly, that **no override
path exists** -- no environment variable, no config key, no keyword argument
re-enables live trading.
"""

from __future__ import annotations

import ast
import os
import unittest
import unittest.mock
from pathlib import Path

from core import safety
from core.safety import (
    LIVE_TRADING_ENABLED,
    ExecutionMode,
    ExecutionState,
    UnsafeExecutionStateError,
    assert_live_trading_disabled,
    describe_execution_state,
    resolve_execution_mode,
    validate_execution_environment,
)

SAFETY_SOURCE = Path(safety.__file__)


class PhaseInvariantTests(unittest.TestCase):
    """The lock itself."""

    def test_live_trading_is_disabled(self) -> None:
        self.assertIs(LIVE_TRADING_ENABLED, False)

    def test_assertion_helper_passes_while_locked(self) -> None:
        assert_live_trading_disabled()  # must not raise

    def test_assertion_helper_fires_if_the_lock_is_flipped(self) -> None:
        with unittest.mock.patch.object(safety, "LIVE_TRADING_ENABLED", True):
            with self.assertRaises(UnsafeExecutionStateError):
                safety.assert_live_trading_disabled()


class NoOverridePathTests(unittest.TestCase):
    """There must be no way to enable live trading from outside the source."""

    def test_lock_is_not_read_from_the_environment(self) -> None:
        """Parses the assignment: it must be a literal, not an os.getenv call."""
        tree = ast.parse(SAFETY_SOURCE.read_text(encoding="utf-8"))
        assignments = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "LIVE_TRADING_ENABLED"
        ]
        self.assertEqual(len(assignments), 1, "expected exactly one assignment")
        value = assignments[0].value
        self.assertIsInstance(value, ast.Constant, "lock must be a literal constant")
        self.assertIs(value.value, False)

    def test_module_does_not_touch_the_environment_at_all(self) -> None:
        tree = ast.parse(SAFETY_SOURCE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"getenv", "environ"}:
                self.fail("core.safety must not read the environment")

    def test_environment_variables_cannot_unlock_live_trading(self) -> None:
        """Try the obvious names an operator might reach for.

        Runs in a subprocess so the module is imported genuinely fresh with the
        variables already set. Reloading in-process would rebuild the enum
        classes and break identity checks for every other test in the run.
        """
        import subprocess
        import sys

        environment = dict(
            os.environ,
            LIVE_TRADING_ENABLED="1",
            ALLOW_LIVE_TRADING="1",
            ENABLE_LIVE_TRADING="true",
            TRADING_MODE="LIVE",
            DEMO_MODE="0",
            UNSAFE_ALLOW_LIVE="yes",
        )
        script = (
            "from core.safety import LIVE_TRADING_ENABLED, ExecutionMode, "
            "UnsafeExecutionStateError, validate_execution_environment\n"
            "assert LIVE_TRADING_ENABLED is False, 'lock was overridden'\n"
            "try:\n"
            "    validate_execution_environment(mode=ExecutionMode.LIVE)\n"
            "except UnsafeExecutionStateError:\n"
            "    print('REFUSED')\n"
            "else:\n"
            "    raise AssertionError('LIVE was permitted')\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(SAFETY_SOURCE.parents[1]),
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            completed.returncode, 0, f"stdout={completed.stdout} stderr={completed.stderr}"
        )
        self.assertIn("REFUSED", completed.stdout)

    def test_validate_takes_no_force_or_override_argument(self) -> None:
        import inspect

        parameters = set(inspect.signature(validate_execution_environment).parameters)
        for forbidden in ("force", "override", "allow_live", "unsafe", "bypass"):
            self.assertNotIn(forbidden, parameters)


class LiveModeRefusalTests(unittest.TestCase):
    """Requesting LIVE always raises, regardless of what else is supplied."""

    def test_live_refused_with_nothing_supplied(self) -> None:
        with self.assertRaises(UnsafeExecutionStateError):
            validate_execution_environment(mode=ExecutionMode.LIVE)

    def test_live_refused_even_with_a_full_set_of_collaborators(self) -> None:
        """A complete-looking setup must not be mistaken for permission."""
        with self.assertRaises(UnsafeExecutionStateError):
            validate_execution_environment(
                mode=ExecutionMode.LIVE,
                order_executor=object(),
                broker_handler=object(),
            )

    def test_refusal_explains_how_to_proceed_safely(self) -> None:
        with self.assertRaises(UnsafeExecutionStateError) as ctx:
            validate_execution_environment(mode=ExecutionMode.LIVE)
        message = str(ctx.exception)
        self.assertIn("ANALYSIS_ONLY", message)
        self.assertIn("SIMULATION", message)
        self.assertIn("REFUSING TO START", message)


class ModeResolutionTests(unittest.TestCase):
    """Mapping the legacy ``demo_mode`` boolean onto an explicit mode."""

    def test_demo_mode_false_means_live_intent(self) -> None:
        """This is the production default, and it is what must be refused."""
        self.assertIs(resolve_execution_mode(demo_mode=False), ExecutionMode.LIVE)

    def test_demo_mode_true_means_simulation(self) -> None:
        self.assertIs(resolve_execution_mode(demo_mode=True), ExecutionMode.SIMULATION)

    def test_missing_execution_module_downgrades_to_analysis_only(self) -> None:
        self.assertIs(
            resolve_execution_mode(demo_mode=False, execution_available=False),
            ExecutionMode.ANALYSIS_ONLY,
        )

    def test_production_config_default_is_refused_end_to_end(self) -> None:
        """The exact live configuration, refused."""
        mode = resolve_execution_mode(demo_mode=False, execution_available=True)
        with self.assertRaises(UnsafeExecutionStateError):
            validate_execution_environment(mode=mode, order_executor=object())


class PermittedModeTests(unittest.TestCase):
    """The two modes that are safe in this phase."""

    def test_analysis_only_is_permitted(self) -> None:
        state = validate_execution_environment(mode=ExecutionMode.ANALYSIS_ONLY)
        self.assertIsInstance(state, ExecutionState)
        self.assertIs(state.mode, ExecutionMode.ANALYSIS_ONLY)
        self.assertFalse(state.live_trading_enabled)

    def test_simulation_requires_an_executor(self) -> None:
        with self.assertRaises(UnsafeExecutionStateError):
            validate_execution_environment(mode=ExecutionMode.SIMULATION)

    def test_simulation_permitted_with_an_executor(self) -> None:
        state = validate_execution_environment(
            mode=ExecutionMode.SIMULATION, order_executor=object()
        )
        self.assertIs(state.mode, ExecutionMode.SIMULATION)
        self.assertTrue(state.has_order_executor)

    def test_state_records_collaborator_presence(self) -> None:
        state = validate_execution_environment(
            mode=ExecutionMode.SIMULATION,
            order_executor=object(),
            broker_handler=object(),
        )
        self.assertTrue(state.has_order_executor)
        self.assertTrue(state.has_broker_handler)

    def test_invalid_mode_type_rejected(self) -> None:
        with self.assertRaises(TypeError):
            validate_execution_environment(mode="LIVE")  # type: ignore[arg-type]

    def test_description_is_log_friendly(self) -> None:
        state = validate_execution_environment(mode=ExecutionMode.ANALYSIS_ONLY)
        description = describe_execution_state(state)
        self.assertIn("execution_mode=ANALYSIS_ONLY", description)
        self.assertIn("live_trading_enabled=False", description)
        self.assertEqual(len(description.splitlines()), 1)


class PurityTests(unittest.TestCase):
    """The lock must be a pure predicate, free of I/O and broker imports."""

    def test_no_broker_import(self) -> None:
        tree = ast.parse(SAFETY_SOURCE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name.split(".")[0], "MetaTrader5")
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotEqual(node.module.split(".")[0], "MetaTrader5")

    def test_no_order_send_anywhere_in_core(self) -> None:
        """Phase 0/1 forbids ``mt5.order_send`` in implementation and tests."""
        core_dir = SAFETY_SOURCE.parent
        for path in core_dir.glob("*.py"):
            with self.subTest(module=path.name):
                self.assertNotIn("order_send(", path.read_text(encoding="utf-8"))

    def test_validation_is_repeatable(self) -> None:
        """No hidden state: calling twice gives the same answer."""
        first = validate_execution_environment(mode=ExecutionMode.ANALYSIS_ONLY)
        second = validate_execution_environment(mode=ExecutionMode.ANALYSIS_ONLY)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

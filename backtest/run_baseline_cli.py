"""Produce one immutable baseline from the command line.

``backtest/baseline.py`` provides :func:`run_baseline` and
:func:`write_artifacts` but no entry point, so every baseline so far was
produced by an ad-hoc script that is not in the repository. That makes a
baseline hard to reproduce and easy to run with accidentally different
assumptions -- which is the one thing a baseline must not be.

This is that entry point. The execution assumptions it defaults to are
``baseline_008``'s, read from this file rather than remembered, so a new
baseline is comparable to the frozen one unless a flag says otherwise.

Usage::

    python -m backtest.run_baseline_cli --id baseline_009 \\
        --dataset data/raw --note "post-R1-R9 funnel neutrality check"

Safety: ``run_baseline`` itself refuses to start if logging would reach the
production record. This script points ``TRADING_BOT_LOG_FILE`` at a scratch
path **before** importing anything that builds a handler, because
``main_production`` creates its ``FileHandler`` at module scope.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Must happen before main_production is imported, directly or indirectly.
if not os.getenv("TRADING_BOT_LOG_FILE"):
    _scratch = Path(tempfile.mkdtemp(prefix="baseline_run_"))
    os.environ["TRADING_BOT_LOG_FILE"] = str(_scratch / "baseline.log")
    os.environ.setdefault("TRADING_BOT_SIGNAL_LOG", str(_scratch / "signals.csv"))
    os.environ.setdefault("TRADING_BOT_STATE_FILE", str(_scratch / "state.json"))

from backtest.baseline import run_baseline, write_artifacts  # noqa: E402
from core.types import Timeframe  # noqa: E402
from core.symbols import SymbolSpecification  # noqa: E402
from data.dataset import HistoricalDataset  # noqa: E402
from execution.intrabar import IntrabarPolicy  # noqa: E402

# baseline_008's recorded assumptions. Defaults, so a new run is comparable.
BASELINE_008_ASSUMPTIONS = {
    "spread_pips": 2.0,
    "slippage_pips": 0.0,
    "commission_per_lot": 0.0,
    "volume": 0.01,
    "max_open_positions": 3,
    "intrabar": IntrabarPolicy.CONSERVATIVE.value,
}


def git_commit() -> str:
    """The commit the strategy is at, or a marker when it cannot be read."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "UNKNOWN"


def dirty_tree() -> bool:
    """Whether tracked files differ from HEAD.

    A baseline from a dirty tree is not reproducible from its recorded commit,
    so this is refused unless explicitly allowed.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--id", required=True, help="baseline id and directory name")
    parser.add_argument("--dataset", default="data/raw",
                        help="directory of <SYMBOL>_<TF>.csv plus broker_metadata.json")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--note", default="", help="recorded in the manifest")
    parser.add_argument("--root", default="baselines")
    parser.add_argument("--spread-pips", type=float,
                        default=BASELINE_008_ASSUMPTIONS["spread_pips"])
    parser.add_argument("--volume", type=float,
                        default=BASELINE_008_ASSUMPTIONS["volume"])
    parser.add_argument("--max-open-positions", type=int,
                        default=BASELINE_008_ASSUMPTIONS["max_open_positions"])
    parser.add_argument("--intrabar", default=BASELINE_008_ASSUMPTIONS["intrabar"],
                        choices=[p.value for p in IntrabarPolicy])
    parser.add_argument("--allow-dirty", action="store_true",
                        help="permit a baseline from a modified working tree")
    args = parser.parse_args(argv)

    if dirty_tree() and not args.allow_dirty:
        print(
            "[FAIL] the working tree has uncommitted changes to tracked files.\n"
            "       A baseline records a git commit as the strategy it measured;\n"
            "       from a dirty tree that record is false. Commit first, or\n"
            "       pass --allow-dirty and accept that it is not reproducible.",
            file=sys.stderr,
        )
        return 2

    dataset_dir = (REPO_ROOT / args.dataset).resolve()
    metadata_path = dataset_dir / "broker_metadata.json"
    if not metadata_path.exists():
        print(f"[FAIL] no broker_metadata.json in {dataset_dir}", file=sys.stderr)
        return 1
    broker_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    try:
        dataset = HistoricalDataset.from_directory(str(dataset_dir), args.symbol)
    except (FileNotFoundError, ValueError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1

    spec = SymbolSpecification.from_broker_metadata(broker_metadata) \
        if hasattr(SymbolSpecification, "from_broker_metadata") else None
    if spec is None:
        from core.symbols import CalculationMode

        spec = SymbolSpecification(
            symbol=broker_metadata["symbol"],
            digits=int(broker_metadata["digits"]),
            point=float(broker_metadata["point"]),
            pip_size=0.10,
            tick_size=float(broker_metadata["trade_tick_size"]),
            tick_value=float(broker_metadata["trade_tick_value"]),
            contract_size=float(broker_metadata["trade_contract_size"]),
            volume_min=float(broker_metadata["volume_min"]),
            volume_max=float(broker_metadata["volume_max"]),
            volume_step=float(broker_metadata["volume_step"]),
            calc_mode=CalculationMode.CFD_LEVERAGE,
            base_currency=broker_metadata.get("currency_base", ""),
            quote_currency=broker_metadata.get("currency_profit", ""),
            account_currency=broker_metadata.get("account_currency", "USD"),
        )

    print(f"[RUN ] {args.id}  dataset={dataset_dir}  commit={git_commit()[:12]}")
    for timeframe in dataset.timeframes:
        first, last = dataset.coverage(timeframe)
        print(f"       {str(timeframe).split('.')[-1]:>4}  {first}  ->  {last}")

    artifacts = run_baseline(
        dataset,
        spec,
        baseline_id=args.id,
        git_commit=git_commit(),
        broker_metadata=broker_metadata,
        spread_pips=args.spread_pips,
        spread_is_assumed=True,
        slippage_pips=BASELINE_008_ASSUMPTIONS["slippage_pips"],
        commission_per_lot=BASELINE_008_ASSUMPTIONS["commission_per_lot"],
        intrabar_policy=IntrabarPolicy(args.intrabar),
        volume=args.volume,
        max_open_positions=args.max_open_positions,
        driving_timeframe=Timeframe.M5,
    )

    if args.note:
        artifacts.manifest["note"] = args.note

    directory = write_artifacts(artifacts, REPO_ROOT / args.root)
    print(f"[DONE] {directory}")
    funnel = artifacts.layer_funnel.get("blocked_at", {})
    total = sum(funnel.values()) or 1
    for layer, count in sorted(funnel.items(), key=lambda kv: -kv[1]):
        print(f"       {layer:<16} {count:>7}  {100.0 * count / total:>6.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Historical dataset loading and validation.

Validation policy
-----------------
**Corrupt data is reported, never repaired.** Silently dropping a duplicate
timestamp or clamping an impossible high would hide a data-quality problem
inside a backtest result, where it becomes indistinguishable from a strategy
effect. Every rejection names the offending row index and value.

The Phase 1 audit found the same failure mode in the production signal log: rows
were appended under a header that did not describe them for 39,709 rows because
nothing verified the contract.

What is rejected
----------------
* duplicate timestamps within a timeframe
* non-monotonic ordering
* ``high < low``
* ``high`` below, or ``low`` above, the open/close body
* non-positive prices
* NaN in any OHLC column
* naive (timezone-less) timestamps
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from core.types import Timeframe
from data.timeframes import resample_from_m1

__all__ = [
    "BAR_COLUMNS",
    "DataValidationError",
    "HistoricalDataset",
    "ValidationIssue",
    "load_bars_csv",
    "validate_bars",
]

BAR_COLUMNS: tuple[str, ...] = ("time", "open", "high", "low", "close", "tick_volume")
"""Exact column layout produced by ``mt5_handler.get_market_data``.

The replay feed must reproduce this precisely -- a missing column or a different
dtype changes strategy behaviour.
"""


class DataValidationError(ValueError):
    """Raised when a dataset fails validation.

    Carries every issue found, not merely the first, so a bad export can be
    fixed in one pass.
    """

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        summary = "\n".join(f"  - {issue}" for issue in issues[:20])
        more = f"\n  ... and {len(issues) - 20} more" if len(issues) > 20 else ""
        super().__init__(f"dataset failed validation ({len(issues)} issue(s)):\n{summary}{more}")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One specific data-quality problem.

    Attributes:
        kind: Short machine-readable category.
        row_index: Position of the offending row, or ``None`` if file-level.
        detail: Human-readable description including the offending values.
    """

    kind: str
    row_index: int | None
    detail: str

    def __str__(self) -> str:
        location = f"row {self.row_index}" if self.row_index is not None else "file"
        return f"[{self.kind}] {location}: {self.detail}"


def validate_bars(bars: pd.DataFrame, timeframe: Timeframe) -> list[ValidationIssue]:
    """Check a bar frame and return every problem found.

    Args:
        bars: Candidate bar frame.
        timeframe: Timeframe the frame claims to represent, used in messages.

    Returns:
        A list of :class:`ValidationIssue`; empty means the frame is valid.
    """
    issues: list[ValidationIssue] = []

    missing = [column for column in BAR_COLUMNS if column not in bars.columns]
    if missing:
        issues.append(
            ValidationIssue("missing_columns", None, f"absent: {missing}")
        )
        return issues  # nothing further can be checked reliably

    if len(bars) == 0:
        issues.append(ValidationIssue("empty", None, f"{timeframe.value} frame has no rows"))
        return issues

    times = bars["time"]
    if not pd.api.types.is_datetime64_any_dtype(times):
        issues.append(
            ValidationIssue("time_dtype", None, f"'time' is {times.dtype}, expected datetime64")
        )
        return issues

    if times.dt.tz is None:
        issues.append(
            ValidationIssue(
                "naive_timestamps",
                None,
                "'time' is timezone-naive; a naive timestamp is how local time "
                "silently gets compared against UTC market data",
            )
        )
        return issues

    # Duplicates -- reported individually so the export can be fixed.
    duplicated = times.duplicated(keep=False)
    if bool(duplicated.any()):
        for position in bars.index[duplicated][:20]:
            issues.append(
                ValidationIssue(
                    "duplicate_timestamp",
                    int(position),
                    f"timestamp {times.loc[position]} appears more than once",
                )
            )

    # Ordering.
    if not times.is_monotonic_increasing:
        differences = times.diff()
        for position in bars.index[differences <= pd.Timedelta(0)][:20]:
            issues.append(
                ValidationIssue(
                    "non_monotonic",
                    int(position),
                    f"timestamp {times.loc[position]} does not increase from the previous row",
                )
            )

    ohlc = bars[["open", "high", "low", "close"]]

    nan_rows = ohlc.isna().any(axis=1)
    for position in bars.index[nan_rows][:20]:
        issues.append(
            ValidationIssue("nan_ohlc", int(position), f"NaN in OHLC at {times.loc[position]}")
        )

    valid = ~nan_rows
    if bool(valid.any()):
        subset = bars[valid]
        non_positive = (subset[["open", "high", "low", "close"]] <= 0).any(axis=1)
        for position in subset.index[non_positive][:20]:
            issues.append(
                ValidationIssue(
                    "non_positive_price",
                    int(position),
                    f"non-positive price at {times.loc[position]}",
                )
            )

        high_below_low = subset["high"] < subset["low"]
        for position in subset.index[high_below_low][:20]:
            issues.append(
                ValidationIssue(
                    "high_below_low",
                    int(position),
                    f"high {subset['high'].loc[position]} < low {subset['low'].loc[position]} "
                    f"at {times.loc[position]}",
                )
            )

        body_top = subset[["open", "close"]].max(axis=1)
        body_bottom = subset[["open", "close"]].min(axis=1)
        for position in subset.index[subset["high"] < body_top][:20]:
            issues.append(
                ValidationIssue(
                    "high_below_body",
                    int(position),
                    f"high {subset['high'].loc[position]} below max(open, close) "
                    f"{body_top.loc[position]} at {times.loc[position]}",
                )
            )
        for position in subset.index[subset["low"] > body_bottom][:20]:
            issues.append(
                ValidationIssue(
                    "low_above_body",
                    int(position),
                    f"low {subset['low'].loc[position]} above min(open, close) "
                    f"{body_bottom.loc[position]} at {times.loc[position]}",
                )
            )

    return issues


def load_bars_csv(path: Path | str, timeframe: Timeframe) -> pd.DataFrame:
    """Load one timeframe's bars from CSV or Parquet.

    Args:
        path: File to read. ``.parquet``/``.pq`` are read as Parquet, otherwise CSV.
        timeframe: Timeframe the file represents.

    Returns:
        A validated frame with exactly :data:`BAR_COLUMNS`, sorted by time,
        with a fresh ``RangeIndex``.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        DataValidationError: If the data fails validation.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"no such dataset file: {file_path}")

    if file_path.suffix.lower() in {".parquet", ".pq"}:
        frame = pd.read_parquet(file_path)
    else:
        frame = pd.read_csv(file_path)

    if "volume" in frame.columns and "tick_volume" not in frame.columns:
        frame = frame.rename(columns={"volume": "tick_volume"})
    if "timestamp" in frame.columns and "time" not in frame.columns:
        frame = frame.rename(columns={"timestamp": "time"})

    if "time" in frame.columns:
        parsed = pd.to_datetime(frame["time"], utc=True, errors="coerce")
        frame["time"] = parsed

    issues = validate_bars(frame, timeframe)
    if issues:
        raise DataValidationError(issues)

    frame = frame[list(BAR_COLUMNS)].copy()
    frame["tick_volume"] = frame["tick_volume"].fillna(0.0)
    return frame.sort_values("time").reset_index(drop=True)


@dataclass(slots=True)
class HistoricalDataset:
    """Validated multi-timeframe historical bars for one symbol.

    Attributes:
        symbol: Instrument symbol.
        frames: Validated bars per timeframe.
        derived: Timeframes that were resampled from M1 rather than loaded
            natively. Recorded so a run manifest can disclose it -- derived bars
            use UTC boundaries, which may differ from the broker's own.
    """

    symbol: str
    frames: dict[Timeframe, pd.DataFrame] = field(default_factory=dict)
    derived: set[Timeframe] = field(default_factory=set)

    def __post_init__(self) -> None:
        """Validate every frame supplied at construction.

        Raises:
            DataValidationError: If any frame fails validation.
        """
        all_issues: list[ValidationIssue] = []
        for timeframe, frame in self.frames.items():
            for issue in validate_bars(frame, timeframe):
                all_issues.append(
                    ValidationIssue(issue.kind, issue.row_index, f"{timeframe.value}: {issue.detail}")
                )
        if all_issues:
            raise DataValidationError(all_issues)

    @property
    def timeframes(self) -> list[Timeframe]:
        """Timeframes present, coarsest first."""
        return sorted(self.frames, key=lambda tf: -tf.minutes)

    def frame(self, timeframe: Timeframe) -> pd.DataFrame:
        """Return the bars for ``timeframe``.

        Args:
            timeframe: Timeframe to fetch.

        Returns:
            The validated frame.

        Raises:
            KeyError: If the dataset has no data for that timeframe.
        """
        if timeframe not in self.frames:
            raise KeyError(
                f"dataset for {self.symbol} has no {timeframe.value} data "
                f"(available: {[tf.value for tf in self.timeframes]})"
            )
        return self.frames[timeframe]

    def coverage(self, timeframe: Timeframe) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Return the first and last bar open times for ``timeframe``.

        Args:
            timeframe: Timeframe to describe.

        Returns:
            ``(first_open_time, last_open_time)``.
        """
        times = self.frame(timeframe)["time"]
        return times.iloc[0], times.iloc[-1]

    def ensure_timeframes(self, required: list[Timeframe]) -> None:
        """Derive any missing timeframes from M1, if M1 is present.

        Args:
            required: Timeframes the replay needs.

        Raises:
            KeyError: If a timeframe is missing and cannot be derived because
                no M1 data is available.
        """
        for timeframe in required:
            if timeframe in self.frames:
                continue
            if Timeframe.M1 not in self.frames:
                raise KeyError(
                    f"{timeframe.value} is missing and cannot be derived: no M1 data"
                )
            self.frames[timeframe] = resample_from_m1(self.frames[Timeframe.M1], timeframe)
            self.derived.add(timeframe)

    @classmethod
    def from_directory(
        cls,
        directory: Path | str,
        symbol: str = "XAUUSD",
        timeframes: list[Timeframe] | None = None,
    ) -> HistoricalDataset:
        """Load ``<SYMBOL>_<TF>.csv`` files from a directory.

        Args:
            directory: Folder containing the exports.
            symbol: Symbol prefix on the filenames.
            timeframes: Timeframes to look for. Defaults to the six the
                production strategy uses.

        Returns:
            A validated dataset containing whichever files were found.

        Raises:
            FileNotFoundError: If no matching file exists at all.
        """
        folder = Path(directory)
        wanted = timeframes or [
            Timeframe.D1, Timeframe.H4, Timeframe.H1,
            Timeframe.M15, Timeframe.M5, Timeframe.M1,
        ]
        frames: dict[Timeframe, pd.DataFrame] = {}
        for timeframe in wanted:
            for suffix in (".csv", ".parquet", ".pq"):
                candidate = folder / f"{symbol}_{timeframe.value}{suffix}"
                if candidate.is_file():
                    frames[timeframe] = load_bars_csv(candidate, timeframe)
                    break
        if not frames:
            raise FileNotFoundError(
                f"no dataset files found in {folder} for {symbol} "
                f"(expected e.g. {symbol}_M5.csv)"
            )
        return cls(symbol=symbol, frames=frames)

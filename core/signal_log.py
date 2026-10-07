"""Schema-versioned signal log.

Why this module exists
----------------------
The Phase 1 audit found the system's only analytics datastore structurally
corrupt. ``signal_log.csv`` carried a **77-column header** from an abandoned
pipeline (``utils/result_writer.py`` + ``ai_analyst.py``)::

    timestamp,symbol,session,signal,setup_direction,...,wyckoff_phase,...,actual_pnl_pips

while ``main_production.log_signal`` wrote a **20-column** schema. Because
``csv.DictWriter`` only emits a header when the target file does not already
exist, the stale header was never corrected. Column *N* in the header did not
describe column *N* in the data: the field labelled ``symbol`` actually held
``signal_type``.

39,709 rows accumulated that way. The file is unrecoverable without guessing,
and guessing would fabricate data, so it was archived unmodified to
``archive/2026-09-16_signal_log_legacy_mixed_schema.csv`` and **not** repaired.

What this module guarantees
---------------------------
1. Every file carries an explicit :data:`SIGNAL_LOG_SCHEMA_VERSION` column, so a
   reader can tell which writer produced a row instead of inferring it.
2. The header is **verified before every append**, not just when creating the
   file. A schema change can no longer silently corrupt an existing log.
3. On mismatch the existing file is **rotated aside, never appended to and never
   overwritten**. Data is preserved; the new log starts clean.

Phase 0/1 scope
---------------
The column set is deliberately identical to what ``main_production`` already
emits, plus ``schema_version``. No field has been added, removed, renamed or
re-derived, so row *content* is unchanged and no historical data is fabricated.

Known issues left untouched and recorded in ``PHASE_2_ISSUES.md``:

* ``timestamp`` is a naive **local** datetime while market data is tz-aware UTC.
* The daily-trade counter re-reads the entire log on every 5-second cycle.

Both are behavioural changes and belong to a later phase.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Sequence

__all__ = [
    "SIGNAL_LOG_COLUMNS",
    "SIGNAL_LOG_SCHEMA_VERSION",
    "SCHEMA_VERSION_COLUMN",
    "SignalLogSchemaError",
    "append_signal_row",
    "ensure_signal_log",
    "iter_signal_rows",
    "read_header",
    "rotate_mismatched_log",
]

SIGNAL_LOG_SCHEMA_VERSION: Final[int] = 2
"""Current signal-log schema version.

Version 1 is the implicit, unversioned 20-column schema that
``main_production.log_signal`` wrote into a 77-column header. Version 2 is that
same column set with an explicit version marker in front of it.

Increment this whenever :data:`SIGNAL_LOG_COLUMNS` changes. A mismatched header
is then detected and rotated rather than silently appended to.
"""

SCHEMA_VERSION_COLUMN: Final[str] = "schema_version"
"""Name of the column carrying :data:`SIGNAL_LOG_SCHEMA_VERSION`."""

SIGNAL_LOG_COLUMNS: Final[tuple[str, ...]] = (
    SCHEMA_VERSION_COLUMN,
    "timestamp",
    "signal_type",
    "layers_passed",
    "layer_failed",
    "fail_reason",
    "l6_poi_type",
    "l6_poi_score",
    "entry_grade",
    "setup_type",
    "entry_method",
    "entry_mode",
    "trigger_type",
    "rr_valid",
    "entry_price",
    "stop_loss",
    "take_profit",
    "rr_ratio",
    "session",
    "position_type",
    "order_id",
)
"""Canonical v2 column order.

Identical to the legacy production column set, with :data:`SCHEMA_VERSION_COLUMN`
prepended. Kept byte-compatible on purpose so Phase 0 changes no row content.
"""


class SignalLogSchemaError(ValueError):
    """Raised when a signal log's header does not match the expected schema."""


def read_header(path: Path | str) -> tuple[str, ...] | None:
    """Return the header row of an existing signal log.

    Args:
        path: Path to the log file.

    Returns:
        The header fields, or ``None`` if the file does not exist or is empty.

    Raises:
        SignalLogSchemaError: If the file exists but cannot be read as CSV.
    """
    log_path = Path(path)
    if not log_path.is_file() or log_path.stat().st_size == 0:
        return None
    try:
        with log_path.open("r", newline="", encoding="utf-8", errors="replace") as handle:
            first_row = next(csv.reader(handle), None)
    except OSError as exc:  # pragma: no cover - environment dependent
        raise SignalLogSchemaError(f"cannot read signal log {log_path}: {exc}") from exc
    if first_row is None:
        return None
    return tuple(field.strip() for field in first_row)


def rotate_mismatched_log(path: Path | str, reason: str = "schema-mismatch") -> Path:
    """Move an existing log aside so a fresh one can be started.

    The file is **renamed, never truncated or deleted**. A numeric suffix is
    appended if the target name is taken, so repeated rotations never clobber an
    earlier one.

    Args:
        path: Path to the log file to rotate.
        reason: Short slug embedded in the rotated filename.

    Returns:
        The path the file was moved to.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
    """
    log_path = Path(path)
    if not log_path.exists():
        raise FileNotFoundError(f"cannot rotate missing file: {log_path}")

    index = 0
    while True:
        suffix = f".{reason}" if index == 0 else f".{reason}.{index}"
        target = log_path.with_name(f"{log_path.stem}{suffix}{log_path.suffix}")
        if not target.exists():
            break
        index += 1

    log_path.rename(target)
    return target


def ensure_signal_log(
    path: Path | str,
    columns: Sequence[str] = SIGNAL_LOG_COLUMNS,
    *,
    rotate_on_mismatch: bool = True,
) -> Path:
    """Ensure ``path`` is a signal log with exactly ``columns`` as its header.

    Creates the file with a header if it is absent or empty. If it exists with a
    different header, either rotates it aside and starts fresh, or raises.

    Args:
        path: Path to the signal log.
        columns: Expected header, in order.
        rotate_on_mismatch: If ``True``, move a mismatched file aside and create
            a new one. If ``False``, raise instead -- useful for read paths and
            for tests that must assert corruption is detected.

    Returns:
        The path to a log whose header matches ``columns``.

    Raises:
        SignalLogSchemaError: If the header does not match and
            ``rotate_on_mismatch`` is ``False``.
    """
    log_path = Path(path)
    expected = tuple(columns)

    existing = read_header(log_path)
    if existing == expected:
        return log_path

    if existing is not None:
        if not rotate_on_mismatch:
            raise SignalLogSchemaError(
                f"signal log {log_path} has {len(existing)} column(s) but "
                f"{len(expected)} were expected. Appending would produce rows "
                f"whose values do not correspond to the header -- the exact "
                f"corruption found in the legacy signal_log.csv. "
                f"Found: {existing[:5]}{'...' if len(existing) > 5 else ''}"
            )
        rotate_mismatched_log(log_path)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(expected)
    return log_path


def append_signal_row(
    path: Path | str,
    row: Mapping[str, Any],
    columns: Sequence[str] = SIGNAL_LOG_COLUMNS,
    *,
    schema_version: int = SIGNAL_LOG_SCHEMA_VERSION,
) -> None:
    """Append one row, verifying the header first.

    The header is checked on **every** call. That is marginally more I/O than
    checking only at creation time, and it is what prevents a schema change from
    silently corrupting an existing log -- the failure that produced 39,709
    mislabelled rows.

    ``schema_version`` is stamped automatically; any value for it in ``row`` is
    ignored. Unknown keys in ``row`` are dropped; missing keys are written empty.

    Args:
        path: Path to the signal log.
        row: Field values to write.
        columns: Expected header, in order.
        schema_version: Value to stamp into :data:`SCHEMA_VERSION_COLUMN`.

    Raises:
        SignalLogSchemaError: If the log exists with a mismatched header that
            could not be rotated.
    """
    log_path = ensure_signal_log(path, columns)
    payload = {key: row.get(key, "") for key in columns}
    payload[SCHEMA_VERSION_COLUMN] = schema_version
    with log_path.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore").writerow(payload)


def iter_signal_rows(path: Path | str) -> Iterable[dict[str, str]]:
    """Yield rows from a signal log, verifying the header first.

    Args:
        path: Path to the signal log.

    Yields:
        One dict per data row.

    Raises:
        SignalLogSchemaError: If the header does not match the current schema.
            Rotation is disabled here: a read must never mutate the file.
    """
    log_path = Path(path)
    if not log_path.is_file():
        return
    ensure_signal_log(log_path, SIGNAL_LOG_COLUMNS, rotate_on_mismatch=False)
    with log_path.open("r", newline="", encoding="utf-8", errors="replace") as handle:
        yield from csv.DictReader(handle)

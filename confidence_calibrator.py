"""Auto-calibrate technical confidence from historical trade outcomes.

This module keeps the live bot stable today while preparing it to move away
from hand-tuned confidence math. Once enough completed BUY/SELL trades exist
in ``signal_log.csv``, it trains a lightweight logistic regression on the
bot's own historical outcomes and returns a calibrated win-probability style
confidence score.

Until then, callers should fall back to the legacy heuristic confidence.
"""

from __future__ import annotations

import csv
import math
import os
from pathlib import Path
from typing import Any

from utils import log_debug

try:
    import numpy as np
except Exception:  # pragma: no cover - defensive import guard
    np = None


LOG_FILE = os.getenv("SIGNAL_LOG_FILE", "signal_log.csv")
MIN_COMPLETED_TRADES = 50
MIN_CLASS_TRADES = 10
DEFAULT_MAX_SCORE = 12.5
_EPSILON = 1e-9

_CACHE: dict[str, Any] = {
    "log_file": None,
    "mtime": None,
    "model": None,
    "status": "",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        parsed = float(value)
        if parsed != parsed:  # NaN
            return default
        return parsed
    except Exception:
        return default


def _safe_bool(value: Any) -> float:
    text = str(value).strip().lower()
    return 1.0 if text in {"true", "1", "yes"} else 0.0


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _direction_multiplier(signal: str) -> float:
    if signal == "BUY":
        return 1.0
    if signal == "SELL":
        return -1.0
    return 0.0


def _trend_alignment_score(trend: str, signal: str) -> float:
    text = str(trend or "Neutral")
    if signal == "BUY":
        if "Bullish" in text:
            return 1.0 if text.startswith("Strong") else 0.5
        if "Bearish" in text:
            return -1.0
    elif signal == "SELL":
        if "Bearish" in text:
            return 1.0 if text.startswith("Strong") else 0.5
        if "Bullish" in text:
            return -1.0
    return 0.0


def _build_feature_vector(
    *,
    signal: str,
    weighted_score: float,
    m15_rsi: float,
    m15_vol_ratio: float,
    m15_atr_ratio: float,
    mixed_signals: bool,
    high_impact_news: bool,
    rsi_caution: bool,
    m1_counter: bool,
    m15_trend: str,
    m5_trend: str,
    m1_trend: str,
) -> Any:
    if np is None:
        return None

    direction = _direction_multiplier(signal)
    if direction == 0.0:
        return None

    directional_score = _clip(direction * weighted_score / DEFAULT_MAX_SCORE, -1.5, 1.5)
    rsi_feature = _clip(direction * (m15_rsi - 50.0) / 20.0, -2.0, 2.0)
    volume_feature = _clip(m15_vol_ratio - 1.0, -1.5, 2.5)
    atr_feature = _clip(m15_atr_ratio - 1.0, -1.5, 2.5)

    return np.array(
        [
            directional_score,
            abs(directional_score),
            rsi_feature,
            volume_feature,
            atr_feature,
            _safe_bool(mixed_signals),
            _safe_bool(high_impact_news),
            _safe_bool(rsi_caution),
            _safe_bool(m1_counter),
            _trend_alignment_score(m15_trend, signal),
            _trend_alignment_score(m5_trend, signal),
            _trend_alignment_score(m1_trend, signal),
        ],
        dtype=float,
    )


def _build_row_features(row: dict[str, Any]) -> Any:
    return _build_feature_vector(
        signal=str(row.get("signal", "")).strip().upper(),
        weighted_score=_safe_float(row.get("weighted_score")),
        m15_rsi=_safe_float(row.get("m15_rsi"), 50.0),
        m15_vol_ratio=_safe_float(row.get("m15_vol_ratio"), 1.0),
        m15_atr_ratio=_safe_float(row.get("m15_atr_ratio"), 1.0),
        mixed_signals=_safe_bool(row.get("mixed_signals")),
        high_impact_news=_safe_bool(row.get("high_impact_news")),
        rsi_caution=_safe_bool(row.get("rsi_caution")),
        m1_counter=_safe_bool(row.get("m1_counter")),
        m15_trend=str(row.get("m15_trend", "Neutral")),
        m5_trend=str(row.get("m5_trend", "Neutral")),
        m1_trend=str(row.get("m1_trend", "Neutral")),
    )


def _sigmoid(value: Any) -> Any:
    clipped = np.clip(value, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _train_logistic_regression(features: Any, labels: Any) -> dict[str, Any] | None:
    if np is None or len(features) == 0:
        return None

    means = features.mean(axis=0)
    scales = features.std(axis=0)
    scales[scales < _EPSILON] = 1.0
    normalized = (features - means) / scales

    weights = np.zeros(normalized.shape[1], dtype=float)
    win_rate = float(labels.mean())
    bias = math.log((win_rate + 1e-3) / (1.0 - win_rate + 1e-3))
    learning_rate = 0.12
    l2_penalty = 0.01

    for _ in range(900):
        scores = normalized @ weights + bias
        probs = _sigmoid(scores)
        errors = probs - labels

        grad_w = (normalized.T @ errors) / len(labels) + (l2_penalty * weights)
        grad_b = float(errors.mean())

        weights -= learning_rate * grad_w
        bias -= learning_rate * grad_b

    return {
        "weights": weights,
        "bias": bias,
        "means": means,
        "scales": scales,
        "samples": int(len(labels)),
        "wins": int(labels.sum()),
        "losses": int(len(labels) - labels.sum()),
    }


def _train_from_log(log_file: str) -> tuple[dict[str, Any] | None, str]:
    if np is None:
        return None, "confidence calibration disabled: numpy unavailable"

    path = Path(log_file)
    if not path.is_file():
        return None, f"confidence calibration waiting: log file not found ({log_file})"

    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception as exc:
        return None, f"confidence calibration failed to read log: {exc}"

    samples: list[Any] = []
    labels: list[float] = []

    for row in rows:
        signal = str(row.get("signal", "")).strip().upper()
        outcome = str(row.get("outcome", "")).strip().upper()
        if signal not in {"BUY", "SELL"} or outcome not in {"WIN", "LOSS"}:
            continue

        feature_vector = _build_row_features(row)
        if feature_vector is None:
            continue

        samples.append(feature_vector)
        labels.append(1.0 if outcome == "WIN" else 0.0)

    total = len(samples)
    if total < MIN_COMPLETED_TRADES:
        return (
            None,
            f"confidence calibration waiting: {total}/{MIN_COMPLETED_TRADES} completed BUY/SELL trades",
        )

    wins = int(sum(labels))
    losses = total - wins
    if wins < MIN_CLASS_TRADES or losses < MIN_CLASS_TRADES:
        return (
            None,
            f"confidence calibration waiting: need at least {MIN_CLASS_TRADES} wins and losses "
            f"(wins={wins}, losses={losses})",
        )

    feature_matrix = np.vstack(samples)
    label_vector = np.asarray(labels, dtype=float)
    model = _train_logistic_regression(feature_matrix, label_vector)
    if model is None:
        return None, "confidence calibration failed: model training returned no result"

    status = (
        "confidence calibration ready: "
        f"{model['samples']} completed trades (wins={model['wins']}, losses={model['losses']})"
    )
    return model, status


def _get_cached_model(log_file: str = LOG_FILE) -> tuple[dict[str, Any] | None, str]:
    path = Path(log_file)
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = None

    if (
        _CACHE["log_file"] == log_file
        and _CACHE["mtime"] == mtime
    ):
        return _CACHE["model"], str(_CACHE["status"])

    model, status = _train_from_log(log_file)
    _CACHE.update(
        {
            "log_file": log_file,
            "mtime": mtime,
            "model": model,
            "status": status,
        }
    )
    log_debug(status)
    return model, status


def get_calibration_status(log_file: str = LOG_FILE) -> str:
    """Return the current readiness/training status for confidence calibration."""
    _, status = _get_cached_model(log_file)
    return status


def calibrate_technical_confidence(
    *,
    fallback_confidence: int,
    direction: str,
    scorecard: dict[str, Any],
    tfi: dict[str, dict[str, Any]],
    mixed_signals: bool,
    high_impact_news: bool,
    rsi_caution: bool,
    m1_counter: bool,
    log_file: str = LOG_FILE,
) -> tuple[int, str]:
    """Return a calibrated confidence if enough historical trade data exists."""
    model, _ = _get_cached_model(log_file)
    if model is None or direction not in {"BUY", "SELL"}:
        return fallback_confidence, "formula"

    m15 = tfi.get("M15", {})
    m5 = tfi.get("M5", {})
    m1 = tfi.get("M1", {})

    feature_vector = _build_feature_vector(
        signal=direction,
        weighted_score=_safe_float(scorecard.get("final_score")),
        m15_rsi=_safe_float(m15.get("rsi_14"), 50.0),
        m15_vol_ratio=_safe_float(m15.get("volume_ratio"), 1.0),
        m15_atr_ratio=_safe_float(m15.get("atr_ratio"), 1.0),
        mixed_signals=mixed_signals,
        high_impact_news=high_impact_news,
        rsi_caution=rsi_caution,
        m1_counter=m1_counter,
        m15_trend=str(m15.get("trend_classification", "Neutral")),
        m5_trend=str(m5.get("trend_classification", "Neutral")),
        m1_trend=str(m1.get("trend_classification", "Neutral")),
    )
    if feature_vector is None:
        return fallback_confidence, "formula"

    normalized = (feature_vector - model["means"]) / model["scales"]
    probability = float(_sigmoid(normalized @ model["weights"] + model["bias"]))
    calibrated = int(round(_clip(probability * 100.0, 5.0, 95.0)))

    log_debug(
        f"Confidence calibration applied: formula={fallback_confidence}% -> "
        f"calibrated={calibrated}% using {model['samples']} completed trades"
    )
    return calibrated, "logistic"

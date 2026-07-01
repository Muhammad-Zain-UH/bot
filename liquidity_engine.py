"""LAYER 4: LIQUIDITY ENGINE (CORE) - Systematic scoring and ranking of liquidity pools.

XAUUSD-Specific Liquidity Pool Types:

1. EQUAL LOWS / EQUAL HIGHS
   - Same level touched 2+ times (±1.5 pips tolerance for gold)
   - Clusters of stops sitting here
   - Scoring: Base 15 per touch

2. ASIAN SESSION EXTREME
   - Asian low (00:00-08:00 GMT): previous Asia session's low
   - Asian high: previous Asia session's high
   - Scoring: Base 20 + recency

3. PREVIOUS DAY EXTREME
   - PDL (Previous Day Low): yesterday's range low
   - PDH (Previous Day High): yesterday's range high
   - Scoring: Base 15 + recency

4. RECENT SWING LOW/HIGH
   - Last 20 M15 candles: swing points that are untested
   - Scoring: Base 20 - (age in candles)

5. ROUND NUMBERS
   - 2500, 2475, 2450, 2425, etc. for XAUUSD
   - 25-pip round numbers
   - Scoring: Base 10 + confluence

SCORING FORMULA:
Score = Base +
  (Number of touches × 15) +        # Each touch adds +15
  (Round alignment × 20) +           # Round number adds +20
  (HTF confluence × 25) +            # H1/H4 level adds +25
  (Recency within 24h × 10) +       # Within 24h adds +10
  (Volume support × 10)              # High volume at level adds +10
  ─────────────────────────────────
  Cap at 100 max

LIQUIDITY POOL QUALITY TIERS:
- S-Tier (80-100): Prime target, hunt aggressively
- A-Tier (70-79): Very good, hunt with confirmation
- B-Tier (60-69): Acceptable, requires strict rules
- Reject (<60): Skip this pool
"""

from __future__ import annotations
from typing import Any
import pandas as pd
from utils import log_debug


def _to_float(value: Any) -> float | None:
    """Safely convert to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cluster_price_points(
    points: list[tuple[int, float]],
    tolerance_pips: float,
) -> list[list[tuple[int, float]]]:
    """Group (candle_index, price) into single-linkage clusters within tolerance."""
    if not points:
        return []

    sorted_points = sorted(points, key=lambda item: item[1])
    clusters: list[list[tuple[int, float]]] = []
    current = [sorted_points[0]]

    for point in sorted_points[1:]:
        if point[1] - current[-1][1] <= tolerance_pips:
            current.append(point)
        else:
            if len(current) >= 2:
                clusters.append(current)
            current = [point]

    if len(current) >= 2:
        clusters.append(current)

    return clusters


def find_equal_levels(
    data: pd.DataFrame,
    tolerance_pips: float = 1.5,
    lookback: int = 100,
) -> list[dict[str, Any]]:
    """
    Find levels touched 2+ times within tolerance.
    
    Returns list of:
        {
            "level": float,
            "touches": int,
            "type": "equal_low | equal_high",
            "candle_indices": [int, ...],
        }
    """
    try:
        recent = data.tail(lookback).reset_index(drop=True)
        equal_levels: list[dict[str, Any]] = []

        for column, pool_type in (("high", "equal_high"), ("low", "equal_low")):
            points: list[tuple[int, float]] = []
            for i in range(len(recent)):
                price = _to_float(recent[column].iloc[i])
                if price is not None:
                    points.append((i, price))

            for cluster in _cluster_price_points(points, tolerance_pips):
                indices = sorted({idx for idx, _ in cluster})
                level = sum(price for _, price in cluster) / len(cluster)
                equal_levels.append({
                    "level": level,
                    "touches": len(indices),
                    "type": pool_type,
                    "candle_indices": indices,
                })

        # Merge clusters of the same type that overlap in price
        merged: list[dict[str, Any]] = []
        for pool in sorted(equal_levels, key=lambda item: item["level"]):
            merged_into_existing = False
            for existing in merged:
                if existing["type"] != pool["type"]:
                    continue
                if abs(existing["level"] - pool["level"]) <= tolerance_pips:
                    combined_indices = sorted(set(existing["candle_indices"]) | set(pool["candle_indices"]))
                    existing["candle_indices"] = combined_indices
                    existing["touches"] = len(combined_indices)
                    existing["level"] = (existing["level"] + pool["level"]) / 2.0
                    merged_into_existing = True
                    break
            if not merged_into_existing:
                merged.append(pool)

        return merged

    except Exception as exc:
        log_debug(f"Equal levels detection error: {exc}")
        return []


def find_previous_day_extremes(daily_data: pd.DataFrame | None) -> dict[str, Any]:
    """Previous completed daily candle high/low (PDH / PDL)."""
    try:
        if daily_data is None or len(daily_data) < 2:
            return {"pdh": None, "pdl": None}

        previous_day = daily_data.iloc[-2]
        return {
            "pdh": _to_float(previous_day.get("high")),
            "pdl": _to_float(previous_day.get("low")),
        }
    except Exception as exc:
        log_debug(f"Previous day extremes error: {exc}")
        return {"pdh": None, "pdl": None}


def _htf_confluence_strength(level: float, reference_levels: list[float | None], tolerance_pips: float = 2.0) -> float:
    """Return 0.0-1.0 based on proximity to any HTF reference level."""
    matches = 0
    checked = 0
    for ref in reference_levels:
        if ref is None:
            continue
        checked += 1
        if abs(level - ref) <= tolerance_pips:
            matches += 1
    if checked == 0:
        return 0.0
    return min(1.0, matches / checked)


def find_asian_extremes(data: pd.DataFrame) -> dict[str, Any]:
    """
    Find Asian session (00:00-08:00 GMT) extremes.
    
    Returns: {"asian_low": float, "asian_high": float}
    """
    try:
        if len(data) < 10:
            return {"asian_low": None, "asian_high": None}

        frame = data.copy()
        time_column = None
        for candidate in ("timestamp", "time", "datetime"):
            if candidate in frame.columns:
                time_column = candidate
                break

        if time_column is not None:
            session_times = pd.to_datetime(frame[time_column], utc=True, errors="coerce")
            asian_mask = session_times.dt.hour.between(0, 7, inclusive="both")
            asian_window = frame.loc[asian_mask]
            if len(asian_window) >= 3:
                return {
                    "asian_low": _to_float(asian_window["low"].min()),
                    "asian_high": _to_float(asian_window["high"].max()),
                }

        # Fallback: use the most recent span if timestamps are missing or no Asian bars found.
        recent = frame.tail(50)
        return {
            "asian_low": _to_float(recent["low"].min()),
            "asian_high": _to_float(recent["high"].max()),
        }
    
    except Exception as exc:
        log_debug(f"Asian extremes detection error: {exc}")
        return {"asian_low": None, "asian_high": None}


def find_round_numbers(current_price: float, range_pips: float = 100) -> list[float]:
    """
    Find round numbers near current price.
    
    XAUUSD round numbers: 2500, 2475, 2450, 2425, etc. (25-pip increments)
    
    Returns list of round levels within range_pips
    """
    try:
        # Round to nearest 25 pips for XAUUSD
        base_round = int(current_price / 25) * 25
        
        rounds = []
        for level in [base_round, base_round + 25, base_round - 25, base_round + 50, base_round - 50]:
            if abs(level - current_price) <= range_pips:
                rounds.append(level)
        
        return rounds
    
    except Exception as exc:
        log_debug(f"Round numbers detection error: {exc}")
        return []


def score_liquidity_pool(
    level: float,
    pool_type: str,
    equal_level_info: dict | None = None,
    is_round_number: bool = False,
    htf_confluence: float = 0.0,  # 0.0-1.0, how close to H1/H4 level
    age_hours: float = 0.0,  # How many hours old
    volume_ratio: float = 1.0,  # Volume at level vs average
    current_price: float | None = None,
) -> dict[str, Any]:
    """
    Score a single liquidity pool (0-100).
    
    Returns:
        {
            "level": float,
            "pool_type": str,
            "score": 0-100,
            "tier": "S | A | B | REJECT",
            "score_breakdown": {
                "base": int,
                "touches": int,
                "round_bonus": int,
                "confluence_bonus": int,
                "recency_bonus": int,
                "volume_bonus": int,
            },
            "confluence_reasons": [str, ...],
        }
    """
    try:
        score = 0
        score_breakdown = {
            "base": 0,
            "touches": 0,
            "round_bonus": 0,
            "confluence_bonus": 0,
            "recency_bonus": 0,
            "volume_bonus": 0,
            "distance_penalty": 0,
        }
        confluence_reasons = []
        
        # Base score by pool type
        if pool_type == "equal_low" or pool_type == "equal_high":
            score = 15
            score_breakdown["base"] = 15
        elif pool_type == "asian_low" or pool_type == "asian_high":
            score = 20
            score_breakdown["base"] = 20
        elif pool_type == "pdl" or pool_type == "pdh":
            score = 15
            score_breakdown["base"] = 15
        elif pool_type == "swing_low" or pool_type == "swing_high":
            score = 20
            score_breakdown["base"] = 20
        else:
            score = 10
            score_breakdown["base"] = 10
        
        # Add touches bonus (each touch +15)
        if equal_level_info and "touches" in equal_level_info:
            touches_bonus = equal_level_info["touches"] * 15
            score += touches_bonus
            score_breakdown["touches"] = touches_bonus
            confluence_reasons.append(f"{equal_level_info['touches']} touches at {level:.2f}")
        
        # Round number bonus (+20)
        if is_round_number:
            score += 20
            score_breakdown["round_bonus"] = 20
            confluence_reasons.append(f"Round number alignment")
        
        # HTF confluence bonus (+25 max)
        if htf_confluence > 0:
            confluence_bonus = int(25 * htf_confluence)
            score += confluence_bonus
            score_breakdown["confluence_bonus"] = confluence_bonus
            confluence_reasons.append(f"HTF confluence (strength: {htf_confluence:.1%})")
        
        # Recency bonus (+10 for within 24h)
        if age_hours < 24:
            recency_bonus = int(10 * (1 - age_hours / 24))
            score += recency_bonus
            score_breakdown["recency_bonus"] = recency_bonus
            confluence_reasons.append(f"Recency: {age_hours:.1f}h old")
        
        # Volume bonus (+10 for 1.5x+ average)
        if volume_ratio >= 1.5:
            volume_bonus = 10
            score += volume_bonus
            score_breakdown["volume_bonus"] = volume_bonus
            confluence_reasons.append(f"Volume support: {volume_ratio:.1f}x")
        elif volume_ratio >= 1.2:
            volume_bonus = 5
            score += volume_bonus
            score_breakdown["volume_bonus"] = volume_bonus
            confluence_reasons.append(f"Volume support: {volume_ratio:.1f}x")

        # FIX #2 (PHASE 4): PROXIMITY PENALTY REVERSAL
        # REMOVED: Old penalty for "too close" (<5 pips)
        # NEW: Proximity BONUS for pools within 2 pips (ideal sweep entry)
        # Pools far away (>50 pips) still penalized
        if current_price is not None:
            distance = abs(level - current_price)
            
            # PROXIMITY BONUS: Sweeps MUST be near price to work
            if distance <= 2.0:
                proximity_bonus = 25  # Large bonus for near-price pools
                score += proximity_bonus
                score_breakdown["proximity_bonus"] = proximity_bonus
                confluence_reasons.append(f"[BONUS] Proximity to price ({distance:.1f} pips) - ideal sweep level")
            
            # DISTANCE PENALTY: Only penalize very far pools
            distance_penalty = 0
            if distance > 50:
                distance_penalty = 20
                score -= distance_penalty
                score_breakdown["distance_penalty"] = -distance_penalty
                confluence_reasons.append(f"Distance penalty: {distance:.1f} pips (too far)")
            elif distance > 30:
                distance_penalty = 10
                score -= distance_penalty
                score_breakdown["distance_penalty"] = -distance_penalty
                confluence_reasons.append(f"Distance penalty: {distance:.1f} pips (far)")
        
        # Cap at 100
        score = max(0, min(100, score))
        
        # Determine tier
        if score >= 80:
            tier = "S"
        elif score >= 70:
            tier = "A"
        elif score >= 60:
            tier = "B"
        else:
            tier = "REJECT"
        
        return {
            "level": level,
            "pool_type": pool_type,
            "score": score,
            "tier": tier,
            "score_breakdown": score_breakdown,
            "confluence_reasons": confluence_reasons,
        }
    
    except Exception as exc:
        log_debug(f"Liquidity pool scoring error: {exc}")
        return {
            "level": level,
            "pool_type": pool_type,
            "score": 0,
            "tier": "REJECT",
            "score_breakdown": {"base": 0},
            "confluence_reasons": [str(exc)],
        }


def identify_liquidity_pools(
    m15_data: pd.DataFrame,
    h1_data: pd.DataFrame | None = None,
    h4_data: pd.DataFrame | None = None,
    daily_data: pd.DataFrame | None = None,
    current_price: float | None = None,
    side: str | None = None,  # Optional: 'BUY' or 'SELL' to compute sweep/tp
) -> dict[str, Any]:
    """
    Systematically identify and score all liquidity pools.
    
    Returns:
        {
            "liquidity_pools": [
                {
                    "level": float,
                    "pool_type": str,
                    "score": 0-100,
                    "tier": "S | A | B | REJECT",
                    "score_breakdown": {...},
                    "confluence_reasons": [str, ...],
                },
                ...
            ],
            "top_3_pools": [...],  # Top 3 by score
            "recommendation": "Hunt S-Tier | Hunt A-Tier | Wait for better pool",
        }
    """
    try:
        if m15_data is None or len(m15_data) < 10:
            return {
                "liquidity_pools": [],
                "top_3_pools": [],
                "recommendation": "Insufficient data",
            }
        
        current_price = current_price or _to_float(m15_data.iloc[-1]["close"])
        if current_price is None:
            return {
                "liquidity_pools": [],
                "top_3_pools": [],
                "recommendation": "Cannot determine current price",
            }
        
        pools = []
        htf_reference_levels: list[float | None] = []

        if h1_data is not None and len(h1_data) > 0:
            htf_reference_levels.extend([
                _to_float(h1_data["high"].max()),
                _to_float(h1_data["low"].min()),
            ])
        if h4_data is not None and len(h4_data) > 0:
            htf_reference_levels.extend([
                _to_float(h4_data["high"].max()),
                _to_float(h4_data["low"].min()),
            ])

        prev_day = find_previous_day_extremes(daily_data)
        if prev_day["pdh"]:
            htf_reference_levels.append(prev_day["pdh"])
        if prev_day["pdl"]:
            htf_reference_levels.append(prev_day["pdl"])

        # 1. Find equal lows/highs
        equal_levels = find_equal_levels(m15_data, tolerance_pips=1.5, lookback=100)
        for equal_level in equal_levels:
            pool_info = score_liquidity_pool(
                level=equal_level["level"],
                pool_type=equal_level["type"],
                equal_level_info=equal_level,
                is_round_number=False,
                htf_confluence=_htf_confluence_strength(equal_level["level"], htf_reference_levels),
                current_price=current_price,
            )
            pools.append(pool_info)
        
        # 2. Asian extremes
        asian = find_asian_extremes(m15_data)
        if asian["asian_low"]:
            pool_info = score_liquidity_pool(
                level=asian["asian_low"],
                pool_type="asian_low",
                is_round_number=False,
                htf_confluence=max(0.1, _htf_confluence_strength(asian["asian_low"], htf_reference_levels)),
                current_price=current_price,
            )
            pools.append(pool_info)
        
        if asian["asian_high"]:
            pool_info = score_liquidity_pool(
                level=asian["asian_high"],
                pool_type="asian_high",
                is_round_number=False,
                htf_confluence=max(0.1, _htf_confluence_strength(asian["asian_high"], htf_reference_levels)),
                current_price=current_price,
            )
            pools.append(pool_info)

        # 2b. Previous day high/low
        if prev_day["pdl"]:
            pool_info = score_liquidity_pool(
                level=prev_day["pdl"],
                pool_type="pdl",
                is_round_number=False,
                htf_confluence=0.35,
                current_price=current_price,
            )
            pools.append(pool_info)
        if prev_day["pdh"]:
            pool_info = score_liquidity_pool(
                level=prev_day["pdh"],
                pool_type="pdh",
                is_round_number=False,
                htf_confluence=0.35,
                current_price=current_price,
            )
            pools.append(pool_info)
        
        # 3. Round numbers
        round_numbers = find_round_numbers(current_price, range_pips=100)
        for round_num in round_numbers:
            # Check if this round is also an equal level
            is_equal = any(
                abs(equal["level"] - round_num) <= 1.5
                for equal in equal_levels
            )
            pool_info = score_liquidity_pool(
                level=round_num,
                pool_type="round_number",
                is_round_number=True,
                htf_confluence=0.15 if is_equal else 0.05,
                current_price=current_price,
            )
            pools.append(pool_info)
        
        # 4. Add H1/H4 levels as liquidity pools (if provided)
        if h1_data is not None and len(h1_data) > 0:
            h1_high = _to_float(h1_data["high"].max())
            h1_low = _to_float(h1_data["low"].min())
            if h1_low:
                pool_info = score_liquidity_pool(
                    level=h1_low,
                    pool_type="h1_level",
                    is_round_number=False,
                    htf_confluence=0.25,
                    current_price=current_price,
                )
                pools.append(pool_info)
            if h1_high:
                pool_info = score_liquidity_pool(
                    level=h1_high,
                    pool_type="h1_level",
                    is_round_number=False,
                    htf_confluence=0.25,
                    current_price=current_price,
                )
                pools.append(pool_info)

        if h4_data is not None and len(h4_data) > 0:
            h4_high = _to_float(h4_data["high"].max())
            h4_low = _to_float(h4_data["low"].min())
            if h4_low:
                pool_info = score_liquidity_pool(
                    level=h4_low,
                    pool_type="h4_level",
                    is_round_number=False,
                    htf_confluence=0.35,
                    current_price=current_price,
                )
                pools.append(pool_info)
            if h4_high:
                pool_info = score_liquidity_pool(
                    level=h4_high,
                    pool_type="h4_level",
                    is_round_number=False,
                    htf_confluence=0.35,
                    current_price=current_price,
                )
                pools.append(pool_info)
        
        # Remove duplicates (same level within tolerance)
        unique_pools = []
        for pool in pools:
            is_duplicate = False
            for existing in unique_pools:
                if abs(existing["level"] - pool["level"]) <= 1.5:
                    # Merge: keep higher score
                    if pool["score"] > existing["score"]:
                        unique_pools.remove(existing)
                    else:
                        is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_pools.append(pool)
        
        # Sort by score descending
        unique_pools.sort(key=lambda p: p["score"], reverse=True)
        
        # Get top 3
        top_3 = unique_pools[:3]
        
        # Recommendation
        if any(p["tier"] == "S" for p in unique_pools):
            recommendation = "Hunt S-Tier"
        elif any(p["tier"] == "A" for p in unique_pools):
            recommendation = "Hunt A-Tier"
        elif any(p["tier"] == "B" for p in unique_pools):
            recommendation = "Hunt B-Tier (risky)"
        else:
            recommendation = "Wait for better pool (no pool ≥60)"
        
        # Compute directional pools if side provided (for sweep vs TP roles)
        sweep_pool = None
        tp_pool = None

        def _rank_directional_pool(pool: dict[str, Any]) -> tuple[float, float, int]:
            """Prefer nearest valid pools, then higher score."""
            distance = abs(pool.get("level", current_price) - current_price) if current_price is not None else float("inf")
            tier_rank = 0 if pool.get("tier") in {"S", "A"} else 1
            return (distance, -float(pool.get("score", 0)), tier_rank)

        try:
            above_pools = [p for p in unique_pools if p.get("level", 0) > current_price]
            below_pools = [p for p in unique_pools if p.get("level", 0) < current_price]

            # Prefer meaningful pools first. If none exist, fall back to the closest pool
            # on the correct side so L4 can still reason about the next expected sweep/TP.
            above_candidates = [p for p in above_pools if p.get("score", 0) >= 60] or above_pools
            below_candidates = [p for p in below_pools if p.get("score", 0) >= 60] or below_pools

            if side == "SELL":
                # For a SELL, sweep should be above price (wick into resistance), TP below
                sweep_pool = min(above_candidates, key=_rank_directional_pool) if above_candidates else None
                tp_pool = min(below_candidates, key=_rank_directional_pool) if below_candidates else None
            elif side == "BUY":
                # For a BUY, sweep should be below price (wick into support), TP above
                sweep_pool = min(below_candidates, key=_rank_directional_pool) if below_candidates else None
                tp_pool = min(above_candidates, key=_rank_directional_pool) if above_candidates else None
        except Exception:
            sweep_pool = None
            tp_pool = None

        return {
            "liquidity_pools": unique_pools,
            "top_3_pools": top_3,
            "recommendation": recommendation,
            "sweep_pool": sweep_pool,
            "tp_pool": tp_pool,
        }
    
    except Exception as exc:
        log_debug(f"Liquidity pool identification error: {exc}")
        return {
            "liquidity_pools": [],
            "top_3_pools": [],
            "recommendation": f"Error: {str(exc)}",
        }


def assess_liquidity_gate(
    sweep_pool: dict[str, Any] | None,
    tp_pool: dict[str, Any] | None,
    current_price: float | None,
    side: str,
) -> dict[str, Any]:
    """Classify the liquidity setup as PASS, WATCH, or BLOCK.

    PASS means the directional pool quality is strong enough to continue.
    WATCH means the setup is close enough to keep observing, but it should
    not be treated like a confirmed liquidity target yet.
    BLOCK means the pool selection is too weak or missing.
    
    FIX #2 (PHASE 4): STRICT DIRECTIONAL ENFORCEMENT
    - For SELL: sweep_pool MUST be above price, tp_pool MUST be below
    - For BUY: sweep_pool MUST be below price, tp_pool MUST be above
    - If pools are on wrong side, BLOCK immediately
    """
    if current_price is None or side not in {"BUY", "SELL"}:
        return {
            "state": "BLOCK",
            "reason": "Missing current price or invalid side",
            "sweep_score": 0,
            "tp_score": 0,
            "sweep_distance": None,
            "thresholds": {},
        }

    if not sweep_pool or not tp_pool:
        return {
            "state": "BLOCK",
            "reason": "Missing sweep pool or TP pool",
            "sweep_score": sweep_pool.get("score", 0) if sweep_pool else 0,
            "tp_score": tp_pool.get("score", 0) if tp_pool else 0,
            "sweep_distance": abs(sweep_pool.get("level", current_price) - current_price) if sweep_pool else None,
            "thresholds": {},
        }

    # FIX #2: STRICT DIRECTIONAL FILTER
    sweep_level = float(sweep_pool.get("level", current_price))
    tp_level = float(tp_pool.get("level", current_price))
    
    if side == "SELL":
        # SELL: sweep must be ABOVE price, TP must be BELOW
        if sweep_level <= current_price:
            return {
                "state": "BLOCK",
                "reason": f"SELL directional error: sweep pool at {sweep_level:.2f} must be ABOVE price {current_price:.2f}",
                "sweep_score": 0,
                "tp_score": 0,
                "sweep_distance": 0,
                "thresholds": {},
            }
        if tp_level >= current_price:
            return {
                "state": "BLOCK",
                "reason": f"SELL directional error: TP pool at {tp_level:.2f} must be BELOW price {current_price:.2f}",
                "sweep_score": 0,
                "tp_score": 0,
                "sweep_distance": 0,
                "thresholds": {},
            }
    elif side == "BUY":
        # BUY: sweep must be BELOW price, TP must be ABOVE
        if sweep_level >= current_price:
            return {
                "state": "BLOCK",
                "reason": f"BUY directional error: sweep pool at {sweep_level:.2f} must be BELOW price {current_price:.2f}",
                "sweep_score": 0,
                "tp_score": 0,
                "sweep_distance": 0,
                "thresholds": {},
            }
        if tp_level <= current_price:
            return {
                "state": "BLOCK",
                "reason": f"BUY directional error: TP pool at {tp_level:.2f} must be ABOVE price {current_price:.2f}",
                "sweep_score": 0,
                "tp_score": 0,
                "sweep_distance": 0,
                "thresholds": {},
            }

    sweep_score = int(sweep_pool.get("score", 0))
    tp_score = int(tp_pool.get("score", 0))
    sweep_distance = abs(float(sweep_pool.get("level", current_price)) - float(current_price))
    is_fallback = "fallback" in str(sweep_pool.get("pool_type", "")).lower()

    min_sweep_score = 60 if is_fallback else 70
    min_tp_score = 60
    max_sweep_distance = 100.0 if is_fallback else 60.0

    watch_sweep_score = max(40, min_sweep_score - 30)
    watch_tp_score = 55
    watch_distance = max_sweep_distance * 1.25

    thresholds = {
        "min_sweep_score": min_sweep_score,
        "min_tp_score": min_tp_score,
        "max_sweep_distance": max_sweep_distance,
        "watch_sweep_score": watch_sweep_score,
        "watch_tp_score": watch_tp_score,
        "watch_distance": watch_distance,
    }

    if sweep_score >= min_sweep_score and tp_score >= min_tp_score and sweep_distance <= max_sweep_distance:
        return {
            "state": "PASS",
            "reason": (
                f"Sweep {sweep_score}/100, TP {tp_score}/100, dist {sweep_distance:.2f} within "
                f"thresholds (fallback={is_fallback})"
            ),
            "sweep_score": sweep_score,
            "tp_score": tp_score,
            "sweep_distance": sweep_distance,
            "thresholds": thresholds,
        }

    if sweep_score >= watch_sweep_score and tp_score >= watch_tp_score and sweep_distance <= watch_distance:
        return {
            "state": "WATCH",
            "reason": (
                f"Near-valid liquidity: sweep {sweep_score}/100, TP {tp_score}/100, "
                f"dist {sweep_distance:.2f}. Waiting for stronger confirmation."
            ),
            "sweep_score": sweep_score,
            "tp_score": tp_score,
            "sweep_distance": sweep_distance,
            "thresholds": thresholds,
        }

    return {
        "state": "BLOCK",
        "reason": (
            f"Sweep {sweep_score}/100, TP {tp_score}/100, dist {sweep_distance:.2f} "
            f"did not meet liquidity requirements"
        ),
        "sweep_score": sweep_score,
        "tp_score": tp_score,
        "sweep_distance": sweep_distance,
        "thresholds": thresholds,
    }


def get_liquidity_pools(
    m15_data: pd.DataFrame,
    h1_data: pd.DataFrame | None = None,
    h4_data: pd.DataFrame | None = None,
    daily_data: pd.DataFrame | None = None,
    current_price: float | None = None,
) -> dict[str, Any]:
    """
    Wrapper for liquidity pool identification.
    """
    return identify_liquidity_pools(m15_data, h1_data, h4_data, daily_data, current_price)

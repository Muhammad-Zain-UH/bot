"""LAYER 6: POI QUALITY ENGINE - Scores entry zones (Order Blocks, FVGs, Fibs).

POI Types and Scoring for XAUUSD:

ORDER BLOCK (OB):
- Bullish candle body that created displacement, now untested
- Strong momentum away from it = buyers committed
- Scoring: Base 30 points for OB type

FAIR VALUE GAP (FVG):
- Gap of 3+ pips between candles
- 50%+ of gap unfilled = good quality
- Formed with strong momentum candle
- Scoring: Base 25 points for FVG type

FIBONACCI RETRACEMENT:
- 0.5 or 0.618 retracement of last impulse leg
- HTF confluence (aligns with H1/H4 level)
- Not yet retested = untested
- Scoring: Base 25 points

BREAKER BLOCK:
- Failed OB that broke and is now support (bullish) / resistance (bearish)
- Recency (within 5 candles)
- Scoring: Base 20 points

POI SCORING FORMULA:
Score = POI_Type_Base +
  (Untested, first touch × 30) +     # Never tested = +30
  (Strong displacement × 20) +        # Far from POI = +20
  (HTF confluence × 20) +             # Aligns with H1/H4 = +20
  (Correct size × 15) +               # 5-15 pips deep (not too small) = +15
  (Zone clarity × 15)                 # Clear top/bottom boundaries = +15
  ─────────────────────────────────
  Maximum: 100

ENTRY THRESHOLD: ≥ 70 (only trade POIs scoring 70+)
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


def _zone_touched(
    m15_data: pd.DataFrame,
    zone_top: float,
    zone_bottom: float,
    after_idx: int,
) -> bool:
    """True if any candle after formation traded into the zone."""
    top = max(zone_top, zone_bottom)
    bottom = min(zone_top, zone_bottom)
    for i in range(after_idx + 1, len(m15_data)):
        low = _to_float(m15_data.iloc[i]["low"])
        high = _to_float(m15_data.iloc[i]["high"])
        if low is None or high is None:
            continue
        if low <= top and high >= bottom:
            return True
    return False


def _calc_displacement_pips(
    m15_data: pd.DataFrame,
    direction: str,
    zone_top: float,
    zone_bottom: float,
    formed_idx: int,
) -> float:
    """Measure impulse away from POI after it formed (pips)."""
    if formed_idx >= len(m15_data) - 1:
        return 0.0
    subsequent = m15_data.iloc[formed_idx + 1 :]
    zone_top_val = max(zone_top, zone_bottom)
    zone_bottom_val = min(zone_top, zone_bottom)
    if direction == "BUY":
        max_high = _to_float(subsequent["high"].max())
        return max(0.0, (max_high or zone_top_val) - zone_top_val)
    min_low = _to_float(subsequent["low"].min())
    return max(0.0, zone_bottom_val - (min_low or zone_bottom_val))


def _calc_htf_confluence(
    h1_data: pd.DataFrame | None,
    zone_top: float,
    zone_bottom: float,
    tolerance: float = 5.0,
) -> float:
    """Return 0.0-1.0 based on alignment with recent H1 levels."""
    if h1_data is None or len(h1_data) < 5:
        return 0.0
    zone_top_n = max(zone_top, zone_bottom)
    zone_bottom_n = min(zone_top, zone_bottom)
    zone_mid = (zone_top_n + zone_bottom_n) / 2
    confluence = 0.0

    h1_window = h1_data.tail(20)
    h1_high = _to_float(h1_window["high"].max())
    h1_low = _to_float(h1_window["low"].min())
    for level in (h1_high, h1_low):
        if level is None:
            continue
        if zone_bottom_n <= level <= zone_top_n or abs(zone_mid - level) <= tolerance:
            confluence = max(confluence, 0.7)

    for _, row in h1_window.tail(8).iterrows():
        for level in (_to_float(row["high"]), _to_float(row["low"])):
            if level is None:
                continue
            if zone_bottom_n - tolerance <= level <= zone_top_n + tolerance:
                confluence = max(confluence, 1.0)

    return min(1.0, confluence)


def _poi_short_name(zone_type: str) -> str:
    name = zone_type.upper()
    if "ORDER" in name:
        return "OB"
    if "FAIR" in name or "FVG" in name:
        return "FVG"
    if "FIB" in name:
        return "Fib"
    if "BREAKER" in name:
        return "BB"
    return zone_type[:6]


def detect_order_block(
    m15_data: pd.DataFrame,
    direction: str,
) -> dict[str, Any]:
    """
    Detect Order Block (OB) - strong displacement candle.
    
    Returns:
        {
            "ob_found": bool,
            "ob_top": float,
            "ob_bottom": float,
            "ob_size": float,  # pips
            "base_score": int,
            "candle_idx": int | None,
            "body_clarity": bool,
        }
    """
    try:
        if len(m15_data) < 10:
            return {
                "ob_found": False,
                "ob_top": None,
                "ob_bottom": None,
                "ob_size": None,
                "base_score": 0,
                "candle_idx": None,
                "body_clarity": False,
            }
        
        recent = m15_data.tail(10)
        start_idx = len(m15_data) - len(recent)
        
        if direction == "BUY":
            # Looking for the most recent unmitigated bullish candle that caused displacement.
            for idx in range(len(recent) - 2, -1, -1):
                candle = recent.iloc[idx]
                next_candle = recent.iloc[idx + 1]
                c_open = _to_float(candle["open"])
                c_close = _to_float(candle["close"])
                c_high = _to_float(candle["high"])
                c_low = _to_float(candle["low"])
                next_close = _to_float(next_candle["close"])
                
                if any(v is None for v in [c_open, c_close, c_high, c_low, next_close]):
                    continue
                
                # Bullish OB: close > open, large body, followed by displacement away.
                body = c_close - c_open
                full_range = c_high - c_low
                if body >= 5 and c_close > c_open:
                    displacement = next_close - c_close
                    if displacement < body * 0.8:
                        continue

                    ob_top = max(c_open, c_close)
                    ob_bottom = min(c_open, c_close)
                    subsequent = recent.iloc[idx + 1 :]
                    if any(_to_float(row["low"]) is not None and _to_float(row["low"]) <= ob_top for _, row in subsequent.iterrows()):
                        continue

                    return {
                        "ob_found": True,
                        "ob_top": ob_top,
                        "ob_bottom": ob_bottom,
                        "ob_size": full_range,
                        "base_score": 30,
                        "candle_idx": start_idx + idx,
                        "body_clarity": full_range > 0 and (body / full_range) >= 0.4,
                    }
        
        else:  # SELL
            # Looking for the most recent unmitigated bearish candle that caused displacement.
            for idx in range(len(recent) - 2, -1, -1):
                candle = recent.iloc[idx]
                next_candle = recent.iloc[idx + 1]
                c_open = _to_float(candle["open"])
                c_close = _to_float(candle["close"])
                c_high = _to_float(candle["high"])
                c_low = _to_float(candle["low"])
                next_close = _to_float(next_candle["close"])
                
                if any(v is None for v in [c_open, c_close, c_high, c_low, next_close]):
                    continue
                
                # Bearish OB: close < open, large body, followed by displacement away.
                body = c_open - c_close
                full_range = c_high - c_low
                if body >= 5 and c_close < c_open:
                    displacement = c_close - next_close
                    if displacement < body * 0.8:
                        continue

                    ob_top = max(c_open, c_close)
                    ob_bottom = min(c_open, c_close)
                    subsequent = recent.iloc[idx + 1 :]
                    if any(_to_float(row["high"]) is not None and _to_float(row["high"]) >= ob_bottom for _, row in subsequent.iterrows()):
                        continue

                    return {
                        "ob_found": True,
                        "ob_top": ob_top,
                        "ob_bottom": ob_bottom,
                        "ob_size": full_range,
                        "base_score": 30,
                        "candle_idx": start_idx + idx,
                        "body_clarity": full_range > 0 and (body / full_range) >= 0.4,
                    }
        
        return {
            "ob_found": False,
            "ob_top": None,
            "ob_bottom": None,
            "ob_size": None,
            "base_score": 0,
            "candle_idx": None,
            "body_clarity": False,
        }
    
    except Exception as exc:
        log_debug(f"OB detection error: {exc}")
        return {
            "ob_found": False,
            "ob_top": None,
            "ob_bottom": None,
            "ob_size": None,
            "base_score": 0,
            "candle_idx": None,
            "body_clarity": False,
        }


def detect_fvg(
    m15_data: pd.DataFrame,
    direction: str,
) -> dict[str, Any]:
    """
    Detect Fair Value Gap (FVG) - unfilled gap.
    
    Returns:
        {
            "fvg_found": bool,
            "fvg_top": float,
            "fvg_bottom": float,
            "fvg_size": float,  # pips
            "fill_percent": float,  # 0-100%
            "base_score": int,
            "candle_idx": int | None,
        }
    """
    try:
        if len(m15_data) < 5:
            return {
                "fvg_found": False,
                "fvg_top": None,
                "fvg_bottom": None,
                "fvg_size": None,
                "fill_percent": None,
                "base_score": 0,
                "candle_idx": None,
            }
        
        recent = m15_data.tail(10)
        start_idx = len(m15_data) - len(recent)
        
        # Look for gaps (gap = prev_low > curr_high or prev_high < curr_low)
        for idx in range(1, len(recent)):
            prev_candle = recent.iloc[idx - 1]
            curr_candle = recent.iloc[idx]
            
            prev_high = _to_float(prev_candle["high"])
            prev_low = _to_float(prev_candle["low"])
            curr_high = _to_float(curr_candle["high"])
            curr_low = _to_float(curr_candle["low"])
            
            if any(v is None for v in [prev_high, prev_low, curr_high, curr_low]):
                continue
            
            # Bullish FVG: gap up (curr_low > prev_high)
            if direction == "BUY" and curr_low > prev_high:
                gap_size = curr_low - prev_high
                if gap_size >= 3:  # At least 3 pips
                    # Check how much of gap is filled
                    fill = 0.0
                    for i in range(idx + 1, len(recent)):
                        test_low = _to_float(recent.iloc[i]["low"])
                        if test_low is not None and test_low < curr_low:
                            fill = max(fill, min(1.0, (curr_low - test_low) / gap_size))
                    
                    if fill < 0.5:  # Less than 50% filled = good FVG
                        return {
                            "fvg_found": True,
                            "fvg_top": curr_low,
                            "fvg_bottom": prev_high,
                            "fvg_size": gap_size,
                            "fill_percent": fill * 100,
                            "base_score": 25,
                            "candle_idx": start_idx + idx,
                        }
            
            # Bearish FVG: gap down (prev_low > curr_high)
            if direction == "SELL" and prev_low > curr_high:
                gap_size = prev_low - curr_high
                if gap_size >= 3:
                    # Check fill
                    fill = 0.0
                    for i in range(idx + 1, len(recent)):
                        test_high = _to_float(recent.iloc[i]["high"])
                        if test_high is not None and test_high > curr_high:
                            fill = max(fill, min(1.0, (test_high - curr_high) / gap_size))
                    
                    if fill < 0.5:
                        return {
                            "fvg_found": True,
                            "fvg_top": prev_low,
                            "fvg_bottom": curr_high,
                            "fvg_size": gap_size,
                            "fill_percent": fill * 100,
                            "base_score": 25,
                            "candle_idx": start_idx + idx,
                        }
        
        return {
            "fvg_found": False,
            "fvg_top": None,
            "fvg_bottom": None,
            "fvg_size": None,
            "fill_percent": None,
            "base_score": 0,
            "candle_idx": None,
        }
    
    except Exception as exc:
        log_debug(f"FVG detection error: {exc}")
        return {
            "fvg_found": False,
            "fvg_top": None,
            "fvg_bottom": None,
            "fvg_size": None,
            "fill_percent": None,
            "base_score": 0,
            "candle_idx": None,
        }


def score_poi(
    poi_type: str,
    poi_top: float,
    poi_bottom: float,
    base_score: int,
    is_untested: bool = False,
    displacement: float = 0.0,
    htf_confluence: float = 0.0,
    body_clarity: bool = False,
) -> dict[str, Any]:
    """
    Score a single POI (0-100).
    
    Returns:
        {
            "zone_type": str,
            "top": float,
            "bottom": float,
            "zone_width": float,
            "score": 0-100,
            "tier": "A+ | A | B | REJECT",
            "score_breakdown": {...},
        }
    """
    try:
        score = base_score
        breakdown = {
            "base": base_score,
            "untested": 0,
            "displacement": 0,
            "confluence": 0,
            "size": 0,
            "clarity": 0,
        }
        
        # Untested bonus (+30)
        if is_untested:
            score += 30
            breakdown["untested"] = 30
        
        # Displacement bonus (+20)
        if displacement >= 20:
            score += 20
            breakdown["displacement"] = 20
        elif displacement >= 10:
            score += 10
            breakdown["displacement"] = 10
        
        # HTF confluence bonus (+20)
        confluence_bonus = int(20 * htf_confluence)
        score += confluence_bonus
        breakdown["confluence"] = confluence_bonus
        
        # Size bonus (+15 for 5-15 pips)
        zone_size = abs(poi_top - poi_bottom)
        if 5 <= zone_size <= 15:
            score += 15
            breakdown["size"] = 15
        elif 3 <= zone_size < 5:
            score += 8
            breakdown["size"] = 8
        
        # Clarity bonus (+15 for well-defined body/zone)
        if body_clarity:
            score += 15
            breakdown["clarity"] = 15
        
        # Cap at 100
        score = min(100, score)
        
        # Determine tier
        if score >= 85:
            tier = "A+"
        elif score >= 70:
            tier = "A"
        elif score >= 60:
            tier = "B"
        else:
            tier = "REJECT"
        
        return {
            "zone_type": poi_type,
            "top": poi_top,
            "bottom": poi_bottom,
            "zone_width": zone_size,
            "score": score,
            "tier": tier,
            "untested": is_untested,
            "displacement_pips": displacement,
            "htf_confluence": htf_confluence,
            "score_breakdown": breakdown,
        }
    
    except Exception as exc:
        log_debug(f"POI scoring error: {exc}")
        return {
            "zone_type": poi_type,
            "top": poi_top,
            "bottom": poi_bottom,
            "zone_width": 0,
            "score": 0,
            "tier": "REJECT",
            "score_breakdown": {"error": str(exc)},
        }


def build_poi_layer_data(poi_result: dict[str, Any]) -> dict[str, Any]:
    """Serialize POI result for analysis logging."""
    best = poi_result.get("best_poi")
    if not best:
        return {
            "poi_type": "N/A",
            "score": 0,
            "zones_found": 0,
            "all_zones": [],
        }
    return {
        "poi_type": best.get("zone_type"),
        "score": best.get("score"),
        "tier": best.get("tier"),
        "zone_top": best.get("top"),
        "zone_bottom": best.get("bottom"),
        "zone_width": best.get("zone_width"),
        "untested": best.get("untested"),
        "displacement_pips": best.get("displacement_pips"),
        "htf_confluence": best.get("htf_confluence"),
        "score_breakdown": best.get("score_breakdown"),
        "zones_found": len(poi_result.get("poi_zones", [])),
        "all_zones": [
            {
                "type": z.get("zone_type"),
                "score": z.get("score"),
                "tier": z.get("tier"),
                "top": z.get("top"),
                "bottom": z.get("bottom"),
            }
            for z in poi_result.get("poi_zones", [])
        ],
        "recommendation": poi_result.get("recommendation"),
    }


def format_poi_layer_detail(poi_result: dict[str, Any], current_price: float) -> tuple[str, str]:
    """Return (reason, details) strings for L6 console output."""
    zones = poi_result.get("poi_zones", [])
    best = poi_result.get("best_poi")

    if not zones:
        return "No POI zones detected", f"scan={poi_result.get('recommendation', 'none')}"

    zone_scores = ", ".join(
        f"{_poi_short_name(z['zone_type'])}={z['score']:.0f}" for z in zones
    )

    if not best:
        return f"0/{len(zones)} zones qualify", f"candidates [{zone_scores}]"

    bd = best.get("score_breakdown", {})
    zone_lo = min(best.get("bottom", 0), best.get("top", 0))
    zone_hi = max(best.get("bottom", 0), best.get("top", 0))
    in_zone = zone_lo <= current_price <= zone_hi
    dist = abs(current_price - (zone_lo + zone_hi) / 2)
    tested_label = "untested" if best.get("untested") else "tested"

    reason = (
        f"BEST {best['zone_type']} {best['score']:.0f}/100 ({best.get('tier', '?')}) "
        f"@ {zone_lo:.2f}-{zone_hi:.2f} ({best.get('zone_width', 0):.1f}p)"
    )
    details = (
        f"found {len(zones)} [{zone_scores}] | "
        f"base={bd.get('base', 0)}+unt={bd.get('untested', 0)}+disp={bd.get('displacement', 0)}+"
        f"htf={bd.get('confluence', 0)}+size={bd.get('size', 0)}+clr={bd.get('clarity', 0)} | "
        f"{tested_label}, disp={best.get('displacement_pips', 0):.1f}p, "
        f"htf={best.get('htf_confluence', 0):.0%}, "
        f"price={'IN zone' if in_zone else f'{dist:.1f}p away'}"
    )
    return reason, details


def identify_poi(
    m15_data: pd.DataFrame,
    h1_data: pd.DataFrame | None = None,
    direction: str = "BUY",
    current_price: float | None = None,
) -> dict[str, Any]:
    """
    Identify and score POI zones.
    
    Returns:
        {
            "poi_zones": [
                {
                    "zone_type": str,
                    "top": float,
                    "bottom": float,
                    "zone_width": float,
                    "score": 0-100,
                    "tier": "A+ | A | B | REJECT",
                    "score_breakdown": {...},
                },
                ...
            ],
            "best_poi": dict,  # Highest scoring
            "recommendation": "ENTER | WAIT | INVALID",
        }
    """
    try:
        poi_zones = []
        price = _to_float(current_price)
        if price is None and len(m15_data) > 0:
            price = _to_float(m15_data.iloc[-1]["close"]) or 0.0
        price = price or 0.0
        
        # 1. Detect OB
        ob_result = detect_order_block(m15_data, direction)
        if ob_result["ob_found"]:
            ob_idx = ob_result["candle_idx"] or 0
            ob_top = ob_result["ob_top"]
            ob_bottom = ob_result["ob_bottom"]
            is_untested = not _zone_touched(m15_data, ob_top, ob_bottom, ob_idx)
            displacement = _calc_displacement_pips(m15_data, direction, ob_top, ob_bottom, ob_idx)
            htf_conf = _calc_htf_confluence(h1_data, ob_top, ob_bottom)
            poi_info = score_poi(
                poi_type="Order Block",
                poi_top=ob_top,
                poi_bottom=ob_bottom,
                base_score=ob_result["base_score"],
                is_untested=is_untested,
                displacement=displacement,
                htf_confluence=htf_conf,
                body_clarity=ob_result.get("body_clarity", False),
            )
            poi_zones.append(poi_info)
        
        # 2. Detect FVG
        fvg_result = detect_fvg(m15_data, direction)
        if fvg_result["fvg_found"]:
            fvg_idx = fvg_result["candle_idx"] or 0
            fvg_top = fvg_result["fvg_top"]
            fvg_bottom = fvg_result["fvg_bottom"]
            fill_pct = fvg_result["fill_percent"] or 0.0
            is_untested = fill_pct < 20 and not _zone_touched(m15_data, fvg_top, fvg_bottom, fvg_idx)
            displacement = _calc_displacement_pips(m15_data, direction, fvg_top, fvg_bottom, fvg_idx)
            htf_conf = _calc_htf_confluence(h1_data, fvg_top, fvg_bottom)
            poi_info = score_poi(
                poi_type="Fair Value Gap",
                poi_top=fvg_top,
                poi_bottom=fvg_bottom,
                base_score=fvg_result["base_score"],
                is_untested=is_untested,
                displacement=displacement,
                htf_confluence=htf_conf,
                body_clarity=True,
            )
            poi_zones.append(poi_info)
        
        # 3. Fibonacci 0.618 zone from recent M15 impulse
        if len(m15_data) >= 20:
            recent_low = m15_data.tail(20)["low"].min()
            recent_high = m15_data.tail(20)["high"].max()
            fib_618 = (
                recent_low + (recent_high - recent_low) * 0.618
                if direction == "BUY"
                else recent_high - (recent_high - recent_low) * 0.618
            )
            fib_top = fib_618 + 2
            fib_bottom = fib_618 - 2
            fib_idx = len(m15_data) - 20
            impulse_disp = abs(recent_high - recent_low) * 0.382
            is_untested = not _zone_touched(m15_data, fib_top, fib_bottom, fib_idx)
            htf_conf = _calc_htf_confluence(h1_data, fib_top, fib_bottom)
            poi_info = score_poi(
                poi_type="Fibonacci 0.618",
                poi_top=fib_top,
                poi_bottom=fib_bottom,
                base_score=25,
                is_untested=is_untested,
                displacement=impulse_disp,
                htf_confluence=htf_conf,
                body_clarity=True,
            )
            poi_zones.append(poi_info)
        
        # Sort by score descending
        poi_zones.sort(key=lambda p: p["score"], reverse=True)
        
        # Get best POI
        best_poi = poi_zones[0] if poi_zones else None
        
        # Recommendation
        if best_poi and best_poi["score"] >= 70:
            recommendation = f"ENTER (score: {best_poi['score']})"
        elif best_poi:
            recommendation = f"WAIT (best POI score: {best_poi['score']})"
        else:
            recommendation = f"WAIT (no qualifying POI found for {direction})"
        
        return {
            "poi_zones": poi_zones,
            "best_poi": best_poi,
            "recommendation": recommendation,
        }
    
    except Exception as exc:
        log_debug(f"POI identification error: {exc}")
        return {
            "poi_zones": [],
            "best_poi": None,
            "recommendation": f"Error: {str(exc)}",
        }

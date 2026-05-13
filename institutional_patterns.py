"""Institutional market patterns: Upthrust (fake breakout) and Liquidity Sweep (stop hunt)."""

from __future__ import annotations

from typing import Any
from utils import log_debug


class UpthrustvDetector:
    """Detects fake breakouts (upthrust) where price breaks resistance then reverses sharply."""

    @staticmethod
    def detect_upthrust(
        direction: str,
        tfi: dict[str, dict[str, Any]],
        tfa: dict[str, dict[str, Any]],
    ) -> tuple[bool, str, float]:
        """
        Detect upthrust pattern (bullish fake breakout that reverses down).
        
        Upthrust characteristics:
        - Price breaks above recent resistance on volume
        - M15 near/above previous high
        - Then M5/M1 reverses sharply down
        - Combined with overbought conditions
        
        Args:
            direction: Current signal direction ("BUY", "SELL", "WAIT")
            tfi: Timeframe indicators dict with M15, M5, M1
            tfa: Timeframe analysis dict
        
        Returns:
            (is_upthrust: bool, reason: str, severity: 0-1 float)
        """
        if direction != "BUY":
            return False, "", 0.0
        
        m15 = tfi.get("M15", {})
        m5 = tfi.get("M5", {})
        m1 = tfi.get("M1", {})
        
        m15_trend = m15.get("trend_classification", "")
        m15_rsi = m15.get("rsi_14", 0)
        m5_trend = m5.get("trend_classification", "")
        m1_trend = m1.get("trend_classification", "")
        m1_rsi = m1.get("rsi_14", 0)
        
        # Check for overbought M15 (weak bullish vs strong bearish)
        is_weak_bullish = "Weak Bullish" in m15_trend
        is_strong_bearish_m5 = "Strong Bearish" in m5_trend
        
        # Upthrust pattern: M15 weak bullish, M1 RSI very high (>65), M5/M1 reversing
        upthrust_score = 0.0
        reasons = []
        
        # Condition 1: M15 weak bullish (losing strength at top)
        if is_weak_bullish:
            upthrust_score += 0.25
            reasons.append("M15 weak bullish (losing momentum)")
        
        # Condition 2: M15 RSI overbought >70 (extreme condition)
        if m15_rsi > 70.0:
            upthrust_score += 0.25
            reasons.append(f"M15 RSI {m15_rsi:.1f} overbought")
        
        # Condition 3: M5 showing bearish reversal (strong bearish)
        if is_strong_bearish_m5:
            upthrust_score += 0.30
            reasons.append("M5 strong bearish reversal")
        
        # Condition 4: M1 RSI elevated (>60) but M1 trend STRONG bearish only
        if m1_rsi > 60.0 and m1_trend == "Strong Bearish":
            upthrust_score += 0.20
            reasons.append(f"M1 RSI {m1_rsi:.1f} with strong bearish reversal")
        
        is_upthrust = upthrust_score >= 0.70
        reason = " + ".join(reasons) if reasons else "Insufficient upthrust signals"
        
        return is_upthrust, reason, upthrust_score


class LiquiditySweepDetector:
    """Detects liquidity sweeps (stop hunts) where price hits extreme and reverses."""

    @staticmethod
    def detect_liquidity_sweep(
        direction: str,
        tfi: dict[str, dict[str, Any]],
        tfa: dict[str, dict[str, Any]],
    ) -> tuple[bool, str, float, str]:
        """
        Detect liquidity sweep pattern (stop hunt / fake breakout with reversal).
        
        Liquidity sweep characteristics:
        - BUY context: Price breaks below support, M1 RSI <30, then reverses up
        - SELL context: Price breaks above resistance, M1 RSI >70, then reverses down
        - High volume on initial break
        - Quick reversal indicates trapped stops
        
        Args:
            direction: Current signal direction ("BUY", "SELL", "WAIT")
            tfi: Timeframe indicators dict
            tfa: Timeframe analysis dict
        
        Returns:
            (is_sweep: bool, reason: str, severity: 0-1 float, sweep_type: str)
            sweep_type: "bullish_sweep", "bearish_sweep", or ""
        """
        m15 = tfi.get("M15", {})
        m5 = tfi.get("M5", {})
        m1 = tfi.get("M1", {})
        
        m15_trend = m15.get("trend_classification", "")
        m15_rsi = m15.get("rsi_14", 0)
        m5_trend = m5.get("trend_classification", "")
        m5_rsi = m5.get("rsi_14", 0)
        m1_trend = m1.get("trend_classification", "")
        m1_rsi = m1.get("rsi_14", 0)
        m5_vol = m5.get("volume_ratio", 0)
        
        sweep_score = 0.0
        reasons = []
        sweep_type = ""
        
        # ════════════════════════════════════════════════════════════════
        # BULLISH LIQUIDITY SWEEP (trapped shorts)
        # ════════════════════════════════════════════════════════════════
        if direction == "BUY":
            # Condition 1: M1 extreme oversold (<30)
            if m1_rsi < 30.0:
                sweep_score += 0.30
                reasons.append(f"M1 extreme oversold RSI {m1_rsi:.1f}")
            
            # Condition 1b: Confirm M1 is ACTUALLY reversing UP (critical!)
            if "Bullish" in m1_trend and m1_rsi > 25.0:  # Recovery signal
                sweep_score += 0.15
                reasons.append(f"M1 reversing UP (RSI {m1_rsi:.1f}) - reversal confirmed")
            
            # Condition 2: M5 showing strong bullish reversal
            if "Strong Bullish" in m5_trend:
                sweep_score += 0.25
                reasons.append("M5 strong bullish reversal")
            
            # Condition 3: High volume on reversal (volume_ratio >0.9)
            if m5_vol > 0.90:
                sweep_score += 0.25
                reasons.append(f"High M5 volume ratio {m5_vol:.2f}")
            
            # Condition 4: M15 transitioning to bullish (strong or weak bullish)
            if "Bullish" in m15_trend:
                sweep_score += 0.20
                reasons.append("M15 bullish structure")
            
            if sweep_score >= 0.70:
                sweep_type = "bullish_sweep"
        
        # ════════════════════════════════════════════════════════════════
        # BEARISH LIQUIDITY SWEEP (trapped longs)
        # ════════════════════════════════════════════════════════════════
        elif direction == "SELL":
            # Condition 1: M1 extreme overbought (>70)
            if m1_rsi > 70.0:
                sweep_score += 0.30
                reasons.append(f"M1 extreme overbought RSI {m1_rsi:.1f}")
            
            # Condition 1b: Confirm M1 is ACTUALLY reversing DOWN (critical!)
            if "Bearish" in m1_trend and m1_rsi < 65.0:  # Decline signal
                sweep_score += 0.15
                reasons.append(f"M1 reversing DOWN (RSI {m1_rsi:.1f}) - reversal confirmed")
            
            # Condition 2: M5 showing strong bearish reversal
            if "Strong Bearish" in m5_trend:
                sweep_score += 0.25
                reasons.append("M5 strong bearish reversal")
            
            # Condition 3: High volume on reversal (volume_ratio >0.9)
            if m5_vol > 0.90:
                sweep_score += 0.25
                reasons.append(f"High M5 volume ratio {m5_vol:.2f}")
            
            # Condition 4: M15 transitioning to bearish (strong or weak bearish)
            if "Bearish" in m15_trend:
                sweep_score += 0.20
                reasons.append("M15 bearish structure")
            
            if sweep_score >= 0.70:
                sweep_type = "bearish_sweep"
        
        is_sweep = sweep_score >= 0.70 and sweep_type != ""
        reason = " + ".join(reasons) if reasons else "Insufficient liquidity sweep signals"
        
        return is_sweep, reason, sweep_score, sweep_type


def detect_institutional_patterns(
    direction: str,
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Master detector for all institutional patterns.
    
    Returns comprehensive pattern analysis with detection flags and adjustments.
    """
    # Detect upthrust (fake breakout trap)
    is_upthrust, upthrust_reason, upthrust_severity = UpthrustvDetector.detect_upthrust(
        direction, tfi, tfa
    )
    
    # Detect liquidity sweep (stop hunt)
    is_sweep, sweep_reason, sweep_severity, sweep_type = LiquiditySweepDetector.detect_liquidity_sweep(
        direction, tfi, tfa
    )
    
    # Calculate confidence adjustment
    confidence_adjustment = 0.0
    adjustment_reason = ""
    
    # Upthrust penalty: -20 to -30 based on severity
    if is_upthrust:
        upthrust_penalty = -20.0 - (upthrust_severity * 10.0)
        confidence_adjustment += upthrust_penalty
        adjustment_reason += f"[UPTHRUST] {upthrust_reason} (penalty: {upthrust_penalty:.1f}%) "
    
    # Liquidity sweep bonus: +15 to +20 based on severity
    if is_sweep:
        sweep_bonus = 15.0 + (sweep_severity * 5.0)
        confidence_adjustment += sweep_bonus
        adjustment_reason += f"[LIQUIDITY SWEEP] {sweep_reason} (bonus: {sweep_bonus:.1f}%) "
    
    return {
        "is_upthrust": is_upthrust,
        "upthrust_reason": upthrust_reason,
        "upthrust_severity": upthrust_severity,
        "is_liquidity_sweep": is_sweep,
        "sweep_reason": sweep_reason,
        "sweep_severity": sweep_severity,
        "sweep_type": sweep_type,
        "confidence_adjustment": confidence_adjustment,
        "adjustment_reason": adjustment_reason.strip(),
    }


def get_patterns_summary(patterns: dict[str, Any]) -> str:
    """Format pattern analysis for diagnostic logging."""
    lines = []
    
    if patterns["is_upthrust"]:
        lines.append(
            f"[UPTHRUST] {patterns['upthrust_reason']} "
            f"(severity: {patterns['upthrust_severity']*100:.0f}%)"
        )
    
    if patterns["is_liquidity_sweep"]:
        lines.append(
            f"[LIQUIDITY SWEEP] {patterns['sweep_type'].upper()} - {patterns['sweep_reason']} "
            f"(severity: {patterns['sweep_severity']*100:.0f}%)"
        )
    
    return " | ".join(lines) if lines else ""

#!/usr/bin/env python3
"""
Test script to show new L6 POI signal log format.
Demonstrates how signal_log.csv now includes L6_POI_TYPE and L6_POI_SCORE columns.
"""

import csv
from io import StringIO
from datetime import datetime

# New columns with L6 details
NEW_COLUMNS = [
    "timestamp", "signal_type", "layers_passed", "layer_failed", 
    "fail_reason", "l6_poi_type", "l6_poi_score", 
    "entry_grade", "entry_price", "stop_loss", 
    "take_profit", "rr_ratio", "session", "position_type"
]

# Sample signal log entries showing different L6 scenarios
SAMPLE_SIGNALS = [
    {
        "timestamp": "2026-06-02T17:45:08+05:00",
        "signal_type": "PRE_ENTRY",
        "layers_passed": "L1_BIAS,L3_PULLBACK,L4_LIQUIDITY,L5_SWEEP",
        "layer_failed": "L6_POI",
        "fail_reason": "POI score too low (0 < 70)",
        "l6_poi_type": "N/A",
        "l6_poi_score": 0,
        "entry_grade": "N/A",
        "entry_price": "N/A",
        "stop_loss": "N/A",
        "take_profit": "N/A",
        "rr_ratio": "N/A",
        "session": "LONDON_OPEN",
        "position_type": "N/A",
    },
    {
        "timestamp": "2026-06-02T18:30:15+05:00",
        "signal_type": "PRE_ENTRY",
        "layers_passed": "L1_BIAS,L3_PULLBACK,L4_LIQUIDITY,L5_SWEEP",
        "layer_failed": "L6_POI",
        "fail_reason": "POI score too low (42 < 70)",
        "l6_poi_type": "FVG",
        "l6_poi_score": 42,
        "entry_grade": "N/A",
        "entry_price": "N/A",
        "stop_loss": "N/A",
        "take_profit": "N/A",
        "rr_ratio": "N/A",
        "session": "LONDON_OPEN",
        "position_type": "N/A",
    },
    {
        "timestamp": "2026-06-02T19:15:22+05:00",
        "signal_type": "PRE_ENTRY",
        "layers_passed": "L1_BIAS,L3_PULLBACK,L4_LIQUIDITY,L5_SWEEP",
        "layer_failed": "L6_POI",
        "fail_reason": "POI score too low (65 < 70)",
        "l6_poi_type": "ORDER_BLOCK",
        "l6_poi_score": 65,
        "entry_grade": "N/A",
        "entry_price": "N/A",
        "stop_loss": "N/A",
        "take_profit": "N/A",
        "rr_ratio": "N/A",
        "session": "LONDON",
        "position_type": "N/A",
    },
    {
        "timestamp": "2026-06-02T20:00:30+05:00",
        "signal_type": "ENTRY_SIGNAL",
        "layers_passed": "L1_BIAS,L3_PULLBACK,L4_LIQUIDITY,L5_SWEEP,L6_POI,L7_CONFIDENCE,L8_ENTRY",
        "layer_failed": "",
        "fail_reason": "",
        "l6_poi_type": "ORDER_BLOCK",
        "l6_poi_score": 78,
        "entry_grade": "A+",
        "entry_price": 2489.45,
        "stop_loss": 2485.20,
        "take_profit": 2498.75,
        "rr_ratio": 1.8,
        "session": "LONDON",
        "position_type": "BUY",
    },
    {
        "timestamp": "2026-06-02T20:45:45+05:00",
        "signal_type": "ENTRY_SIGNAL",
        "layers_passed": "L1_BIAS,L3_PULLBACK,L4_LIQUIDITY,L5_SWEEP,L6_POI,L7_CONFIDENCE,L8_ENTRY",
        "layer_failed": "",
        "fail_reason": "",
        "l6_poi_type": "FIBONACCI",
        "l6_poi_score": 82,
        "entry_grade": "A",
        "entry_price": 2487.10,
        "stop_loss": 2483.90,
        "take_profit": 2495.30,
        "rr_ratio": 1.7,
        "session": "LONDON",
        "position_type": "BUY",
    },
    {
        "timestamp": "2026-06-03T08:15:12+05:00",
        "signal_type": "ENTRY_SIGNAL",
        "layers_passed": "L1_BIAS,L3_PULLBACK,L4_LIQUIDITY,L5_SWEEP,L6_POI,L7_CONFIDENCE,L8_ENTRY",
        "layer_failed": "",
        "fail_reason": "",
        "l6_poi_type": "BREAKER_BLOCK",
        "l6_poi_score": 75,
        "entry_grade": "A",
        "entry_price": 2491.60,
        "stop_loss": 2487.40,
        "take_profit": 2502.80,
        "rr_ratio": 2.0,
        "session": "LONDON_OPEN",
        "position_type": "SELL",
    },
]

def print_signal_header():
    """Print formatted header."""
    print("\n" + "=" * 140)
    print("NEW SIGNAL LOG FORMAT - WITH L6 POI DETAILS")
    print("=" * 140)
    print("\n✅ NEW COLUMNS ADDED:")
    print("   - l6_poi_type : Type of POI found (ORDER_BLOCK, FVG, FIBONACCI, BREAKER_BLOCK, or N/A)")
    print("   - l6_poi_score: Quality score of POI (0-100, threshold is 70)")
    print("\n" + "=" * 140)


def print_csv_format():
    """Print sample data in CSV format."""
    print("\n📊 SAMPLE SIGNAL LOG (CSV Format):")
    print("-" * 140)
    
    # Create CSV output
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=NEW_COLUMNS)
    writer.writeheader()
    writer.writerows(SAMPLE_SIGNALS)
    
    csv_content = output.getvalue()
    print(csv_content)


def print_formatted_table():
    """Print formatted table with key columns."""
    print("\n📈 KEY SIGNALS WITH L6 DETAILS:")
    print("-" * 180)
    print(
        f"{'Timestamp':<25} | {'Signal':<12} | {'Layer Failed':<10} | "
        f"{'L6 Type':<14} | {'L6 Score':<8} | {'Reason':<45}"
    )
    print("-" * 180)
    
    for sig in SAMPLE_SIGNALS:
        timestamp = sig["timestamp"][:19]
        signal_type = sig["signal_type"][:12]
        layer_failed = sig["layer_failed"] or "NONE"
        l6_type = str(sig["l6_poi_type"])[:14]
        l6_score = str(sig["l6_poi_score"])[:8]
        reason = sig["fail_reason"][:45] if sig["fail_reason"] else "Entry Signal"
        
        # Determine color/status indicator
        if sig["layer_failed"] == "L6_POI":
            status = "❌ BLOCKED"
        else:
            status = "✅ PASSED"
        
        print(
            f"{timestamp:<25} | {signal_type:<12} | {layer_failed:<10} | "
            f"{l6_type:<14} | {l6_score:<8} | {reason:<45}"
        )


def print_entry_signals_summary():
    """Print summary of only entry signals."""
    print("\n🎯 SUCCESSFUL ENTRY SIGNALS (L6 Passed):")
    print("-" * 140)
    
    entry_signals = [s for s in SAMPLE_SIGNALS if s["signal_type"] == "ENTRY_SIGNAL"]
    
    print(
        f"{'Time':<25} | {'Direction':<6} | {'L6 Type':<14} | "
        f"{'L6 Score':<8} | {'Grade':<6} | {'Entry Price':<12} | {'SL':<10} | {'TP':<10} | {'RR':<5}"
    )
    print("-" * 140)
    
    for sig in entry_signals:
        timestamp = sig["timestamp"][:19]
        direction = sig["position_type"]
        l6_type = sig["l6_poi_type"]
        l6_score = sig["l6_poi_score"]
        grade = sig["entry_grade"]
        entry = f"{sig['entry_price']:.2f}"
        sl = f"{sig['stop_loss']:.2f}"
        tp = f"{sig['take_profit']:.2f}"
        rr = f"1:{sig['rr_ratio']:.1f}"
        
        print(
            f"{timestamp:<25} | {direction:<6} | {l6_type:<14} | "
            f"{l6_score:<8} | {grade:<6} | {entry:<12} | {sl:<10} | {tp:<10} | {rr:<5}"
        )


def print_l6_block_summary():
    """Print summary of L6 blocks."""
    print("\n❌ L6 POI REJECTIONS (Why trades didn't execute):")
    print("-" * 140)
    
    blocked = [s for s in SAMPLE_SIGNALS if s["layer_failed"] == "L6_POI"]
    
    print(
        f"{'Time':<25} | {'L6 Type Found':<14} | {'Score':<8} | {'Threshold':<11} | {'Reason':<40}"
    )
    print("-" * 140)
    
    for sig in blocked:
        timestamp = sig["timestamp"][:19]
        l6_type = sig["l6_poi_type"]
        score = sig["l6_poi_score"]
        threshold = "70 (min)"
        reason = sig["fail_reason"]
        
        print(
            f"{timestamp:<25} | {l6_type:<14} | {score:<8} | {threshold:<11} | {reason:<40}"
        )


def main():
    """Main execution."""
    print_signal_header()
    print_formatted_table()
    print_entry_signals_summary()
    print_l6_block_summary()
    print_csv_format()
    
    print("\n" + "=" * 140)
    print("✅ IMPLEMENTATION COMPLETE")
    print("=" * 140)
    print("\nNow when you run main.py or main_production.py:")
    print("  1. Each signal is logged to signal_log.csv")
    print("  2. L6 passes → logs POI type (OB/FVG/FIB/BREAKER) and score (70-100)")
    print("  3. L6 blocks → logs POI type (if found) and score (0-69), with 'BLOCK' reason")
    print("  4. You can filter by l6_poi_type to see which setups perform best")
    print("  5. You can identify why trades blocked (e.g., 'FVG at 42/100 - not high enough quality')")
    print("\n" + "=" * 140)


if __name__ == "__main__":
    main()

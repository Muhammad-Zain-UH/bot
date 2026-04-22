"""Dynamic sleep time calculation based on setup gaps and stage."""

from __future__ import annotations


def calculate_sleep_time(
    confidence: int = 0,
    required_confidence: int = 50,
    score: float = 0.0,
    required_score: float = 4.5,
    stage: int | str = 1,
) -> int:
    """Calculate dynamic sleep time based on how close we are to passing a gate.
    
    Args:
        confidence: Current confidence level (0-100)
        required_confidence: Threshold confidence needed to pass (typically 45-55)
        score: Current technical score
        required_score: Threshold score needed to pass (typically 4.5)
        stage: Which stage triggered the sleep (1, 2, 3, "hard_block", "post_trade")
    
    Returns:
        Sleep time in seconds
    
    Logic:
        Stage 1 (GATE 1 - technical):
            gap > 20% → 120 seconds
            gap 10-20% → 60 seconds
            gap < 10% → 30 seconds (very close)
        
        Stage 2 (intermarket hard blocks & headwind):
            → 90 seconds
        
        Hard blocks (A, B, C, D):
            → 120 seconds
        
        Post-trade cooldown:
            → 300 seconds
    
        Any other error/timeout:
            → 60 seconds
    """
    
    # Post-trade cooldown
    if stage == "post_trade":
        return 300
    
    # Hard block (A, B, C, D)
    if stage == "hard_block":
        return 120
    
    # Stage 2 (intermarket headwind or general block)
    if stage == 2 or stage == "stage2":
        return 90
    
    # Stage 1 (technical gate) — dynamic based on gap
    if stage == 1 or stage == "stage1":
        gap = required_confidence - confidence
        
        # Calculate gap as percentage of required threshold
        gap_pct = (gap / required_confidence * 100) if required_confidence > 0 else 0
        
        # Dynamic sleep based on closeness to threshold
        if gap_pct > 20:
            return 120  # Far from threshold, longer wait
        elif gap_pct > 10:
            return 60   # Moderately close
        else:
            return 30   # Very close, frequent checks
    
    # Default (any error or unclassified)
    return 60

DIMENSION_SCORES = {
    "signal_alignment": {"STRONG": 30, "ACCEPTABLE": 18, "CONFLICTED": 0},
    "entry_timing": {"IDEAL": 25, "ACCEPTABLE": 15, "POOR": 0},
    "momentum_quality": {"STRONG": 20, "MODERATE": 12, "WEAK": 0},
    "risk_reward_view": {"FAVORABLE": 15, "NEUTRAL": 8, "UNFAVORABLE": 0},
    "setup_concern": {"NONE": 10, "MINOR": 5, "SIGNIFICANT": 0},
}


def compute_confidence(decision: dict, market_context: dict | None = None) -> int:
    """Convert qualitative decision dimensions into an overall confidence score (0-100)"""
    score = 0
    score += DIMENSION_SCORES["signal_alignment"].get(
        decision.get("signal_alignment") or "", 0
    )
    score += DIMENSION_SCORES["entry_timing"].get(decision.get("entry_timing") or "", 0)
    score += DIMENSION_SCORES["momentum_quality"].get(
        decision.get("momentum_quality") or "", 0
    )
    score += DIMENSION_SCORES["risk_reward_view"].get(
        decision.get("risk_reward_view") or "", 0
    )
    score += DIMENSION_SCORES["setup_concern"].get(
        decision.get("setup_concern") or "", 0
    )

    ctx = market_context or {}
    nifty_day = ctx.get("nifty_day_pct", 0) or 0
    sector_day = ctx.get("sector_day_pct", 0) or 0
    divergence = ctx.get("divergence_note", "") or ""

    if nifty_day < -1.0:
        score -= 15
    if sector_day < -0.5:
        score -= 10
    if "relative strength" in divergence.lower():
        score += 10

    return max(0, min(100, score))

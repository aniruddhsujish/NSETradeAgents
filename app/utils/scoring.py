from app.core.config import settings

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

    if decision.get("momentum_quality") == "STRONG" and decision.get(
        "entry_timing"
    ) in (
        "ACCEPTABLE",
        "POOR",
    ):  # blocks entering after the move is done
        score -= 15

    # India VIX fear adjustment
    india_vix = ctx.get("india_vix") or 0
    if india_vix > settings.vix_high_fear_level:
        score -= settings.vix_high_fear_penalty
    elif india_vix > settings.vix_medium_fear_level:
        score -= settings.vix_medium_fear_penalty

    # Nifty multi-day trend
    nifty_10d = ctx.get("nifty_10d_pct", 0) or 0
    nifty_20d = ctx.get("nifty_20d_pct", 0) or 0
    if nifty_20d < settings.nifty_20d_decline_threshold:
        score -= 10
    if nifty_10d < settings.nifty_10d_decline_threshold:
        score -= 8

    return max(0, min(100, score))


def _rules_entry_timing(ind: dict) -> str:
    rsi = ind.get("rsi", 50)
    macd_hist = ind.get("macd_hist", 0)
    macd_hist_prev = ind.get("macd_hist_prev", 0)
    volume_ratio = ind.get("volume_ratio", 0)
    day_change = ind.get("day_change_pct", 0)
    current_price = ind.get("current_price", 0)

    if day_change > 5:
        return "POOR"
    if volume_ratio < 1.5:
        return "POOR"
    for level in settings.round_number_levels:
        if (
            current_price > 0
            and abs(current_price - level) / level < settings.resistance_proximity_pct
        ):
            return "POOR"

    conditions = [
        macd_hist > macd_hist_prev,
        rsi < 67,
        volume_ratio > 2,
        day_change < 3,
    ]
    met = sum(conditions)
    if met == 4:
        return "IDEAL"
    if met >= 3:
        return "ACCEPTABLE"
    return "POOR"


def _rules_momentum_quality(ind: dict) -> str:
    rsi = ind.get("rsi", 50)
    macd_hist_trend = ind.get("macd_hist_trend", "mixed")
    momentum_5d = ind.get("momentum_5d", 0)

    if rsi > settings.rsi_max or rsi < settings.rsi_min:
        return "WEAK"
    if macd_hist_trend == "contracting":
        return "WEAK"
    if momentum_5d > 10 or momentum_5d < 1:
        return "WEAK"
    if 62 <= rsi <= 67 and macd_hist_trend == "expanding" and 3 <= momentum_5d <= 8:
        return "STRONG"
    return "MODERATE"


def _rules_risk_reward(risk: dict, current_price: float) -> str:
    stop_loss = risk.get("stop_loss", 0)
    take_profit = risk.get("take_profit", 0)
    if not stop_loss or not take_profit or current_price <= stop_loss:
        return "NEUTRAL"
    rr = (take_profit - current_price) / (current_price - stop_loss)
    if rr >= 2.5:
        return "FAVORABLE"
    if rr >= 1.5:
        return "NEUTRAL"
    return "UNFAVORABLE"


def compute_rules_confidence(
    technical: dict, risk: dict, market_context: dict | None = None
) -> int:
    ind = technical.get("indicators") or {}
    current_price = ind.get("current_price", 0)

    rules_decision = {
        "entry_timing": _rules_entry_timing(ind),
        "momentum_quality": _rules_momentum_quality(ind),
        "risk_reward_view": _rules_risk_reward(risk, current_price),
        "setup_concern": "MINOR",
    }

    return compute_confidence(rules_decision, market_context)

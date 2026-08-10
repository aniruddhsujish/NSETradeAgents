import pytest
from app.utils.scoring import (
    compute_confidence,
    compute_rules_confidence,
    _rules_entry_timing,
    _rules_momentum_quality,
    _rules_risk_reward,
)

RSI_MIN = 55.0
RSI_MAX = 70.0


@pytest.fixture(autouse=True)
def patch_scoring_settings(monkeypatch):
    monkeypatch.setattr("app.utils.scoring.settings.rsi_min", RSI_MIN)
    monkeypatch.setattr("app.utils.scoring.settings.rsi_max", RSI_MAX)
    monkeypatch.setattr("app.utils.scoring.settings.vix_high_fear_level", 22.0)
    monkeypatch.setattr("app.utils.scoring.settings.vix_medium_fear_level", 18.0)
    monkeypatch.setattr("app.utils.scoring.settings.vix_high_fear_penalty", 20)
    monkeypatch.setattr("app.utils.scoring.settings.vix_medium_fear_penalty", 10)
    monkeypatch.setattr("app.utils.scoring.settings.nifty_20d_decline_threshold", -3.0)
    monkeypatch.setattr("app.utils.scoring.settings.nifty_10d_decline_threshold", -2.0)
    monkeypatch.setattr(
        "app.utils.scoring.settings.round_number_levels",
        [500.0, 1000.0, 2000.0, 5000.0],
    )
    monkeypatch.setattr("app.utils.scoring.settings.resistance_proximity_pct", 0.02)


# ── Shared fixtures ───────────────────────────────────────────────────────────

BEST_DECISION = {
    "signal_alignment": "STRONG",  # 30
    "entry_timing": "IDEAL",  # 25
    "momentum_quality": "STRONG",  # 20
    "risk_reward_view": "FAVORABLE",  # 15
    "setup_concern": "NONE",  # 10
}  # base = 100

NEUTRAL_CTX = {
    "nifty_day_pct": 0.0,
    "sector_day_pct": 0.0,
    "divergence_note": "",
    "india_vix": 15.0,
    "nifty_10d_pct": 0.0,
    "nifty_20d_pct": 0.0,
}

GOOD_TIMING_IND = {
    "rsi": 62.0,
    "macd_hist": 0.5,
    "macd_hist_prev": 0.3,
    "volume_ratio": 2.5,
    "day_change_pct": 1.5,
    "current_price": 750.0,
}


# ── _rules_entry_timing ───────────────────────────────────────────────────────


def test_entry_timing_ideal():
    assert _rules_entry_timing(GOOD_TIMING_IND) == "IDEAL"


def test_entry_timing_poor_day_change_too_high():
    assert _rules_entry_timing({**GOOD_TIMING_IND, "day_change_pct": 6.0}) == "POOR"


def test_entry_timing_poor_low_volume():
    assert _rules_entry_timing({**GOOD_TIMING_IND, "volume_ratio": 1.0}) == "POOR"


def test_entry_timing_poor_near_round_number():
    # 998 is within 2% of 1000
    assert _rules_entry_timing({**GOOD_TIMING_IND, "current_price": 998.0}) == "POOR"


def test_entry_timing_acceptable_three_of_four_conditions():
    # rsi 68 fails the rsi < 67 condition → 3/4 met → ACCEPTABLE
    assert _rules_entry_timing({**GOOD_TIMING_IND, "rsi": 68.0}) == "ACCEPTABLE"


def test_entry_timing_poor_macd_not_rising():
    # Fail macd rising (hist < prev) AND rsi < 67 → only 2/4 conditions met → POOR
    ind = {**GOOD_TIMING_IND, "macd_hist": 0.2, "macd_hist_prev": 0.5, "rsi": 68.0}
    assert _rules_entry_timing(ind) == "POOR"


# ── _rules_momentum_quality ───────────────────────────────────────────────────


def test_momentum_quality_strong():
    ind = {"rsi": 64.0, "macd_hist_trend": "expanding", "momentum_5d": 5.0}
    assert _rules_momentum_quality(ind) == "STRONG"


def test_momentum_quality_weak_rsi_too_high():
    ind = {"rsi": 72.0, "macd_hist_trend": "expanding", "momentum_5d": 5.0}
    assert _rules_momentum_quality(ind) == "WEAK"


def test_momentum_quality_weak_rsi_too_low():
    ind = {"rsi": 50.0, "macd_hist_trend": "expanding", "momentum_5d": 5.0}
    assert _rules_momentum_quality(ind) == "WEAK"


def test_momentum_quality_weak_contracting_macd():
    ind = {"rsi": 63.0, "macd_hist_trend": "contracting", "momentum_5d": 5.0}
    assert _rules_momentum_quality(ind) == "WEAK"


def test_momentum_quality_weak_momentum_too_high():
    ind = {"rsi": 63.0, "macd_hist_trend": "expanding", "momentum_5d": 12.0}
    assert _rules_momentum_quality(ind) == "WEAK"


def test_momentum_quality_weak_momentum_too_low():
    ind = {"rsi": 63.0, "macd_hist_trend": "expanding", "momentum_5d": 0.5}
    assert _rules_momentum_quality(ind) == "WEAK"


def test_momentum_quality_moderate():
    ind = {"rsi": 60.0, "macd_hist_trend": "mixed", "momentum_5d": 4.0}
    assert _rules_momentum_quality(ind) == "MODERATE"


# ── _rules_risk_reward ────────────────────────────────────────────────────────


def test_risk_reward_favorable():
    # R:R = (650 - 500) / (500 - 450) = 3.0, >= 2.5
    assert (
        _rules_risk_reward({"stop_loss": 450, "take_profit": 650}, 500) == "FAVORABLE"
    )


def test_risk_reward_neutral():
    # R:R = (580 - 500) / (500 - 450) = 1.6
    assert _rules_risk_reward({"stop_loss": 450, "take_profit": 580}, 500) == "NEUTRAL"


def test_risk_reward_unfavorable():
    # R:R = (540 - 500) / (500 - 450) = 0.8, < 1.5
    assert (
        _rules_risk_reward({"stop_loss": 450, "take_profit": 540}, 500) == "UNFAVORABLE"
    )


def test_risk_reward_missing_stop_loss():
    assert _rules_risk_reward({"take_profit": 650}, 500) == "NEUTRAL"


def test_risk_reward_price_at_or_below_stop():
    # current_price <= stop_loss is an invalid setup
    assert _rules_risk_reward({"stop_loss": 500, "take_profit": 650}, 500) == "NEUTRAL"


# ── compute_confidence ────────────────────────────────────────────────────────


def test_compute_confidence_perfect_setup():
    # 30 + 25 + 20 + 15 + 10 = 100
    assert compute_confidence(BEST_DECISION, NEUTRAL_CTX) == 100


def test_compute_confidence_zero_setup():
    decision = {
        "signal_alignment": "CONFLICTED",
        "entry_timing": "POOR",
        "momentum_quality": "WEAK",
        "risk_reward_view": "UNFAVORABLE",
        "setup_concern": "SIGNIFICANT",
    }
    assert compute_confidence(decision, NEUTRAL_CTX) == 0


def test_compute_confidence_vix_high_penalty():
    # Best setup = 100, minus 20 for high VIX → 80
    score = compute_confidence(BEST_DECISION, {**NEUTRAL_CTX, "india_vix": 25.0})
    assert score == 80


def test_compute_confidence_vix_medium_penalty():
    # Best setup = 100, minus 10 for medium VIX → 90
    score = compute_confidence(BEST_DECISION, {**NEUTRAL_CTX, "india_vix": 20.0})
    assert score == 90


def test_compute_confidence_bearish_nifty_day_penalty():
    # nifty_day < -1.0 → -15
    score = compute_confidence(BEST_DECISION, {**NEUTRAL_CTX, "nifty_day_pct": -1.5})
    assert score == 85


def test_compute_confidence_weak_sector_penalty():
    # sector_day < -0.5 → -10
    score = compute_confidence(BEST_DECISION, {**NEUTRAL_CTX, "sector_day_pct": -1.0})
    assert score == 90


def test_compute_confidence_relative_strength_bonus():
    # Use a sub-100 base decision so bonus has room
    decision = {
        "signal_alignment": "ACCEPTABLE",  # 18
        "entry_timing": "IDEAL",  # 25
        "momentum_quality": "STRONG",  # 20
        "risk_reward_view": "FAVORABLE",  # 15
        "setup_concern": "NONE",  # 10
    }  # base = 88
    score_without = compute_confidence(decision, NEUTRAL_CTX)
    score_with = compute_confidence(
        decision, {**NEUTRAL_CTX, "divergence_note": "relative strength divergence"}
    )
    assert score_without == 88
    assert score_with == 98


def test_compute_confidence_strong_momentum_late_entry_penalty():
    # STRONG momentum + ACCEPTABLE timing → extra -15
    decision = {
        "signal_alignment": "STRONG",  # 30
        "entry_timing": "ACCEPTABLE",  # 15, but triggers penalty
        "momentum_quality": "STRONG",  # 20
        "risk_reward_view": "FAVORABLE",  # 15
        "setup_concern": "NONE",  # 10
    }  # base = 90, -15 = 75
    assert compute_confidence(decision, NEUTRAL_CTX) == 75


def test_compute_confidence_nifty_20d_decline_penalty():
    # nifty_20d < -3.0 → -10
    score = compute_confidence(BEST_DECISION, {**NEUTRAL_CTX, "nifty_20d_pct": -4.0})
    assert score == 90


def test_compute_confidence_nifty_10d_decline_penalty():
    # nifty_10d < -2.0 → -8
    score = compute_confidence(BEST_DECISION, {**NEUTRAL_CTX, "nifty_10d_pct": -3.0})
    assert score == 92


def test_compute_confidence_clamped_at_zero():
    decision = {
        "signal_alignment": "CONFLICTED",
        "entry_timing": "POOR",
        "momentum_quality": "WEAK",
        "risk_reward_view": "UNFAVORABLE",
        "setup_concern": "SIGNIFICANT",
    }
    ctx = {
        **NEUTRAL_CTX,
        "nifty_day_pct": -2.0,
        "india_vix": 25.0,
        "nifty_20d_pct": -5.0,
        "nifty_10d_pct": -3.0,
    }
    assert compute_confidence(decision, ctx) == 0

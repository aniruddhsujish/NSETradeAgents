import pytest
from datetime import date

from app.portfolio.exits import (
    Bar,
    PositionView,
    evaluate_exit,
    stop_pct,
    target_pct,
)

MAX_HOLD_DAYS = 21
FLAT_STOP_PCT = 0.07
FLAT_TARGET_PCT = 0.18

ENTRY = date(2024, 1, 1)
# Entered at 100: stop 93, target 118
BASE = PositionView(
    entry_date=ENTRY,
    stop_price=93.0,
    target_price=118.0,
)


@pytest.fixture(autouse=True)
def patch_exit_settings(monkeypatch):
    """Pin thresholds so these tests don't depend on the local .env."""
    monkeypatch.setattr("app.portfolio.exits.settings.max_hold_days", MAX_HOLD_DAYS)
    monkeypatch.setattr("app.portfolio.exits.settings.stop_loss_pct", FLAT_STOP_PCT)
    monkeypatch.setattr("app.portfolio.exits.settings.take_profit_pct", FLAT_TARGET_PCT)


def day(n: int) -> date:
    """n calendar days after entry."""
    return date.fromordinal(ENTRY.toordinal() + n)


# ── holding ───────────────────────────────────────────────────────────────────


def test_holds_when_price_sits_between_stop_and_target():
    bar = Bar(open=100.0, high=105.0, low=97.0, close=102.0)
    assert evaluate_exit(BASE, bar, day(5)) is None


# ── stop ──────────────────────────────────────────────────────────────────────


def test_stop_fires_when_low_touches_it():
    bar = Bar(open=100.0, high=101.0, low=92.0, close=95.0)
    price, reason = evaluate_exit(BASE, bar, day(5))
    assert reason == "stop"
    assert price == 93.0  # filled at the stop, not the low


def test_stop_fires_at_exactly_the_stop_price():
    # Boundary: comparison is `<=`, so touching the stop exits
    bar = Bar(open=100.0, high=100.0, low=93.0, close=99.0)
    assert evaluate_exit(BASE, bar, day(5))[1] == "stop"


def test_gap_down_fills_at_the_open_not_the_stop():
    # Opens 12% below the stop — you cannot fill at 93 when the market
    # never traded there. This is the whole reason the backtest models gaps.
    bar = Bar(open=82.0, high=84.0, low=80.0, close=81.0)
    price, reason = evaluate_exit(BASE, bar, day(5))
    assert reason == "stop"
    assert price == 82.0


# ── trail ─────────────────────────────────────────────────────────────────────


def test_active_trail_supersedes_the_entry_stop():
    pos = PositionView(**{**vars(BASE), "trail_stop": 110.0})
    bar = Bar(open=112.0, high=113.0, low=109.0, close=111.0)
    price, reason = evaluate_exit(pos, bar, day(5))
    assert reason == "trail"
    assert price == 110.0


def test_trail_not_used_when_zero():
    pos = PositionView(**{**vars(BASE), "trail_stop": 0.0})
    bar = Bar(open=100.0, high=101.0, low=92.0, close=95.0)
    assert evaluate_exit(pos, bar, day(5))[1] == "stop"


# ── target ────────────────────────────────────────────────────────────────────


def test_target_fires_when_high_reaches_it():
    bar = Bar(open=115.0, high=119.0, low=114.0, close=118.5)
    price, reason = evaluate_exit(BASE, bar, day(5))
    assert reason == "target"
    assert price == 118.0


def test_gap_up_fills_at_the_open_not_the_target():
    bar = Bar(open=125.0, high=127.0, low=124.0, close=126.0)
    price, reason = evaluate_exit(BASE, bar, day(5))
    assert reason == "target"
    assert price == 125.0


# ── the tie ───────────────────────────────────────────────────────────────────


def test_bar_touching_both_stop_and_target_resolves_as_stop():
    """A daily bar hides the intraday path, so the pessimistic branch wins.

    This encodes a modelling decision, not a mechanic: assuming the target
    filled first would silently inflate every backtest that follows.
    """
    bar = Bar(open=100.0, high=120.0, low=90.0, close=110.0)
    price, reason = evaluate_exit(BASE, bar, day(5))
    assert reason == "stop"
    assert price == 93.0


def test_tie_is_labelled_stop_even_when_trailing():
    """The tie branch always reports 'stop', never 'trail'."""
    pos = PositionView(**{**vars(BASE), "trail_stop": 110.0})
    bar = Bar(open=112.0, high=120.0, low=105.0, close=115.0)
    assert evaluate_exit(pos, bar, day(5))[1] == "stop"


# ── timeout ───────────────────────────────────────────────────────────────────


def test_timeout_fires_on_the_max_hold_day():
    bar = Bar(open=100.0, high=101.0, low=99.0, close=100.5)
    price, reason = evaluate_exit(BASE, bar, day(MAX_HOLD_DAYS))
    assert reason == "timeout"
    assert price == 100.5  # closes at the bar's close


def test_no_timeout_the_day_before():
    bar = Bar(open=100.0, high=101.0, low=99.0, close=100.5)
    assert evaluate_exit(BASE, bar, day(MAX_HOLD_DAYS - 1)) is None


# ── hybrid positions ──────────────────────────────────────────────────────────


def test_hybrid_position_ignores_the_target():
    """Hybrid positions ride the trail instead of capping at the target."""
    pos = PositionView(**{**vars(BASE), "hybrid_active": True})
    bar = Bar(open=115.0, high=125.0, low=114.0, close=124.0)
    assert evaluate_exit(pos, bar, day(5)) is None


def test_hybrid_position_ignores_the_timeout():
    pos = PositionView(**{**vars(BASE), "hybrid_active": True})
    bar = Bar(open=100.0, high=101.0, low=99.0, close=100.5)
    assert evaluate_exit(pos, bar, day(MAX_HOLD_DAYS + 30)) is None


def test_hybrid_position_still_honours_its_stop():
    pos = PositionView(**{**vars(BASE), "hybrid_active": True, "trail_stop": 110.0})
    bar = Bar(open=112.0, high=113.0, low=108.0, close=109.0)
    assert evaluate_exit(pos, bar, day(5))[1] == "trail"


# ── Bar.flat (the live path) ──────────────────────────────────────────────────


def test_flat_bar_triggers_stop_at_the_stop_price():
    """Live passes a single tick; the ladder must behave identically."""
    price, reason = evaluate_exit(BASE, Bar.flat(92.0), day(5))
    assert reason == "stop"
    assert price == 92.0  # min(open, stop) collapses to the observed price


def test_flat_bar_holds_between_the_levels():
    assert evaluate_exit(BASE, Bar.flat(100.0), day(5)) is None


def test_flat_bar_hits_target():
    price, reason = evaluate_exit(BASE, Bar.flat(120.0), day(5))
    assert reason == "target"
    assert price == 120.0


# ── stop and target distances ─────────────────────────────────────────────────
#
# Shared by the live risk agent and the backtest engine, which each used to
# carry their own copy of this arithmetic.


@pytest.mark.parametrize(
    "atr_pct,expected",
    [
        (0.5, 0.05),    # floor
        (1.5, 0.05),    # floor — the screener's minimum ATR
        (2.0, 0.05),    # floor, exactly where it stops binding
        (2.4, 0.06),
        (3.0, 0.075),
        (4.0, 0.10),    # cap, exactly where it starts binding
        (6.0, 0.10),    # cap
    ],
)
def test_stop_distance_is_2_5x_atr_bounded_5_to_10(atr_pct, expected):
    assert stop_pct(atr_pct) == pytest.approx(expected)


def test_the_bounds_bind_below_2_and_above_4_percent_atr():
    """Worth pinning: these are the points where risk/reward stops varying
    with volatility, which is what makes an ATR-scaled target a live question."""
    assert stop_pct(1.99) == 0.05
    assert stop_pct(2.01) > 0.05
    assert stop_pct(3.99) < 0.10
    assert stop_pct(4.01) == 0.10


@pytest.mark.parametrize("missing", [None, 0.0, -1.0])
def test_missing_atr_falls_back_to_the_flat_stop(missing):
    """The two call sites guarded this differently — the engine would have
    raised on None — so the fallback lives in one place now."""
    assert stop_pct(missing) == FLAT_STOP_PCT


def test_target_is_flat_today_and_ignores_atr():
    """target_pct takes atr_pct only as the seam for an ATR-scaled target.
    When this test starts failing, that change has landed."""
    assert target_pct(2.0) == FLAT_TARGET_PCT
    assert target_pct(6.0) == FLAT_TARGET_PCT
    assert target_pct(None) == FLAT_TARGET_PCT


def test_reward_to_risk_currently_varies_with_volatility():
    """Today a calm stock is graded far better than a jumpy one. An ATR-scaled
    target collapses this to a constant, which is why the scoring dimension
    has to be dealt with in the same change."""
    calm = target_pct(2.0) / stop_pct(2.0)
    jumpy = target_pct(4.0) / stop_pct(4.0)

    assert calm == pytest.approx(3.6)
    assert jumpy == pytest.approx(1.8)

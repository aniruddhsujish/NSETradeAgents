import pytest
from datetime import date

from app.portfolio.exits import Bar, PositionView, evaluate_exit

MAX_HOLD_DAYS = 21

ENTRY = date(2024, 1, 1)
# Entered at 100: stop 93, target 118
BASE = PositionView(
    entry_date=ENTRY,
    stop_price=93.0,
    target_price=118.0,
)


@pytest.fixture(autouse=True)
def patch_exit_settings(monkeypatch):
    monkeypatch.setattr("app.portfolio.exits.settings.max_hold_days", MAX_HOLD_DAYS)


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

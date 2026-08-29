from datetime import date, timedelta

import pytest
import pandas as pd
from unittest.mock import patch
from app.screener.filters import breadth_pct, regime_blocked_by_breadth, screen

SCREENER_SETTINGS = {
    "min_avg_daily_value": 20_000_000,
    "min_price": 100.0,
    "min_atr_pct": 1.5,
    "max_day_change_pct": 8.0,
    "min_volume_ratio": 2.0,
    "min_volume_shares": 50000,
    "rsi_min": 55.0,
    "rsi_max": 70.0,
    "regime_sma_period": 50,
}


@pytest.fixture(autouse=True)
def patch_screener_settings(monkeypatch):
    """Pin thresholds so these tests don't depend on the local .env."""
    for key, value in SCREENER_SETTINGS.items():
        monkeypatch.setattr(f"app.screener.filters.settings.{key}", value)

# Indicators that pass all 7 filters
GOOD_INDICATORS = {
    "avg_daily_value": 50_000_000,
    "current_price": 500.0,
    "sma50": 480.0,
    "sma200": 400.0,
    "atr_pct": 2.0,
    "day_change_pct": 3.0,
    "volume_ratio": 3.0,
    "today_vol": 100_000,
    "rsi": 62.0,
    "momentum_5d": 5.0,
}


def make_fake_df(last_day: date | None = None):
    """Minimal 30-row OHLCV DataFrame to pass the len(df) < 25 guard.

    Dated so the final bar is today's. The screener requires that: the scan
    runs late in the session and screens today's partial bar deliberately, so
    a stale last bar means the feed has not published the session being
    screened.
    """
    end = pd.Timestamp(last_day or date.today())
    return pd.DataFrame(
        {
            "Close": [500.0] * 30,
            "Volume": [100000] * 30,
        },
        index=pd.date_range(end=end, periods=30, freq="D"),
    )


def test_empty_tickers_return_empty():
    result = screen([])
    assert result == []


def test_passes_all_filters():
    fake_df = make_fake_df()

    with patch("app.screener.filters.safe_yf_download") as mock_download, patch(
        "app.screener.filters.compute_indicators", return_value=GOOD_INDICATORS
    ):

        mock_download.return_value = fake_df

        result = screen(["TITAN.NS"])

    assert len(result) == 1
    assert result[0]["ticker"] == "TITAN.NS"


def test_blocked_by_trend():
    fake_df = make_fake_df()
    bad_indicators = {
        **GOOD_INDICATORS,
        "current_price": 400.0,
        "sma50": 480.0,
        "sma200": 400.0,
    }  # Price below SMA50

    with patch("app.screener.filters.safe_yf_download") as mock_download, patch(
        "app.screener.filters.compute_indicators", return_value=bad_indicators
    ):

        mock_download.return_value = fake_df
        result = screen(["TITAN.NS"])

    assert result == []


def test_blocked_by_rsi_too_high():
    fake_df = make_fake_df()
    bad_indicators = {**GOOD_INDICATORS, "rsi": 72.0}  # RSI above max

    with patch("app.screener.filters.safe_yf_download") as mock_download, patch(
        "app.screener.filters.compute_indicators", return_value=bad_indicators
    ):

        mock_download.return_value = fake_df
        result = screen(["TITAN.NS"])

    assert result == []


def test_blocked_by_low_volume():
    fake_df = make_fake_df()
    bad_indicators = {**GOOD_INDICATORS, "volume_ratio": 1.5}  # Below min_volume_ratio

    with patch("app.screener.filters.safe_yf_download") as mock_download, patch(
        "app.screener.filters.compute_indicators", return_value=bad_indicators
    ):

        mock_download.return_value = fake_df
        result = screen(["TITAN.NS"])

    assert result == []


def test_ranking_order():
    fake_df = make_fake_df()
    high_score = {
        **GOOD_INDICATORS,
        "volume_ratio": 5.0,
        "momentum_5d": 15.0,
        "atr_pct": 5.0,
    }  # Higher volume ratio should boost score
    low_score = {
        **GOOD_INDICATORS,
        "volume_ratio": 2.0,
        "momentum_5d": 2.5,
        "atr_pct": 1.5,
    }

    with patch("app.screener.filters.safe_yf_download") as mock_download, patch(
        "app.screener.filters.compute_indicators"
    ) as mock_indicators:

        mock_download.return_value = fake_df
        mock_indicators.side_effect = [high_score, low_score]

        result = screen(["TITAN.NS", "RELIANCE.NS"])

    assert len(result) == 2
    assert result[0]["ticker"] == "TITAN.NS"  # Higher
    assert result[1]["ticker"] == "RELIANCE.NS"  # Lower


PERIOD = SCREENER_SETTINGS["regime_sma_period"]


# ── breadth regime ────────────────────────────────────────────────────────────
#
# The index gate measured Nifty 50 while the system trades mid/smallcaps. In
# 2025 Nifty rose 9.2% while the median universe stock fell 5.3%, so the gate
# stayed green through a market that was falling underneath it.


def universe_frame(specs: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """Build a closes frame from {ticker: (sma_level, last_price)}."""
    return pd.DataFrame(
        {t: [level] * (PERIOD - 1) + [last] for t, (level, last) in specs.items()}
    )


def test_breadth_is_the_percentage_above_own_average():
    df = universe_frame({
        "A": (100.0, 120.0),   # above
        "B": (100.0, 120.0),   # above
        "C": (100.0, 120.0),   # above
        "D": (100.0, 80.0),    # below
    })
    assert breadth_pct(df) == pytest.approx(75.0)


def test_breadth_counts_only_tickers_with_data():
    """A missing series compares as False and would be counted as a downtrend,
    dragging breadth down whenever the universe is incompletely covered."""
    df = universe_frame({"A": (100.0, 120.0), "B": (100.0, 80.0)})
    df["C"] = float("nan")

    assert breadth_pct(df) == pytest.approx(50.0)  # C ignored, not counted as below


def test_breadth_is_none_when_history_is_too_short():
    df = pd.DataFrame({"A": [100.0] * (PERIOD - 1)})
    assert breadth_pct(df) is None


@pytest.mark.parametrize("empty", [None, pd.DataFrame()])
def test_breadth_is_none_when_there_is_nothing_to_measure(empty):
    assert breadth_pct(empty) is None


def test_gate_blocks_when_most_of_the_universe_is_below():
    df = universe_frame({
        "A": (100.0, 80.0), "B": (100.0, 80.0),
        "C": (100.0, 80.0), "D": (100.0, 120.0),
    })
    assert regime_blocked_by_breadth(df) is True


def test_gate_opens_at_exactly_the_floor():
    """Comparison is `<`, so 50% is open, not blocked."""
    df = universe_frame({"A": (100.0, 120.0), "B": (100.0, 80.0)})
    assert regime_blocked_by_breadth(df) is False


def test_gate_fails_open_when_breadth_is_unknowable():
    """Same contract as the index gate — a halted bot looks like a quiet market."""
    assert regime_blocked_by_breadth(None) is False
    assert regime_blocked_by_breadth(pd.DataFrame()) is False


# ── staleness guard ───────────────────────────────────────────────────────────


def test_a_stale_last_bar_is_skipped():
    """Without this the screener reads yesterday's completed data while the
    system buys at today's price — the old entry model, silently."""
    stale = make_fake_df(last_day=date.today() - timedelta(days=1))

    with patch("app.screener.filters.safe_yf_download") as dl, patch(
        "app.screener.filters.compute_indicators", return_value=GOOD_INDICATORS
    ):
        dl.return_value = stale
        result = screen(["TITAN.NS"])

    assert result == []


def test_todays_bar_is_screened_normally():
    """The partial bar is wanted, not avoided — it is the session being traded."""
    with patch("app.screener.filters.safe_yf_download") as dl, patch(
        "app.screener.filters.compute_indicators", return_value=GOOD_INDICATORS
    ):
        dl.return_value = make_fake_df()
        result = screen(["TITAN.NS"])

    assert len(result) == 1

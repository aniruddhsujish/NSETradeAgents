import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from app.screener.filters import screen

CONFIG = {
    "min_avg_daily_value": 20_000_000,
    "min_price": 100.0,
    "min_atr_pct": 1.5,
    "max_day_change_pct": 8.0,
    "min_volume_ratio": 2.0,
    "min_volume_shares": 50000,
    "rsi_min": 55.0,
    "rsi_max": 70.0,
}

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


def make_fake_df():
    """Minimal 30-row OHLCV Dataframe to pass the len(df) < 25 guard"""
    return pd.DataFrame(
        {
            "Close": [500.0] * 30,
            "Volume": [100000] * 30,
        }
    )


def test_empty_tickers_return_empty():
    result = screen([], CONFIG)
    assert result == []


def test_passes_all_filters():
    fake_df = make_fake_df()

    with patch("app.screener.filters.yf.download") as mock_download, patch(
        "app.screener.filters.compute_indicators", return_value=GOOD_INDICATORS
    ):

        mock_download.return_value = fake_df

        result = screen(["TITAN.NS"], CONFIG)

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

    with patch("app.screener.filters.yf.download") as mock_download, patch(
        "app.screener.filters.compute_indicators", return_value=bad_indicators
    ):

        mock_download.return_value = fake_df
        result = screen(["TITAN.NS"], CONFIG)

    assert result == []


def test_blocked_by_rsi_too_high():
    fake_df = make_fake_df()
    bad_indicators = {**GOOD_INDICATORS, "rsi": 72.0}  # RSI above max

    with patch("app.screener.filters.yf.download") as mock_download, patch(
        "app.screener.filters.compute_indicators", return_value=bad_indicators
    ):

        mock_download.return_value = fake_df
        result = screen(["TITAN.NS"], CONFIG)

    assert result == []


def test_blocked_by_low_volume():
    fake_df = make_fake_df()
    bad_indicators = {**GOOD_INDICATORS, "volume_ratio": 1.5}  # Below min_volume_ratio

    with patch("app.screener.filters.yf.download") as mock_download, patch(
        "app.screener.filters.compute_indicators", return_value=bad_indicators
    ):

        mock_download.return_value = fake_df
        result = screen(["TITAN.NS"], CONFIG)

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
        "momentum_5d": 1.0,
        "atr_pct": 1.5,
    }

    with patch("app.screener.filters.yf.download") as mock_download, patch(
        "app.screener.filters.compute_indicators"
    ) as mock_indicators:

        mock_download.return_value = fake_df
        mock_indicators.side_effect = [high_score, low_score]

        result = screen(["TITAN.NS", "RELIANCE.NS"], CONFIG)

    assert len(result) == 2
    assert result[0]["ticker"] == "TITAN.NS"  # Higher
    assert result[1]["ticker"] == "RELIANCE.NS"  # Lower

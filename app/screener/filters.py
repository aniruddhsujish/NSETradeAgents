import pandas as pd
import structlog
from app.utils.indicators import compute_indicators
from app.utils.market_data import safe_yf_download, extract_ticker_df
from app.core.config import settings

logger = structlog.get_logger()


def evaluate_candidate(ind: dict) -> tuple[dict | None, str]:
    """Apply the screener filters to one ticker's indicators.

    Returns (candidate, "passed"), or (None, reason) where reason is one of:
    no_data, liquidity, price, trend, volatility, day_change, volume, rsi, momentum.
    """
    if ind["avg_daily_value"] < settings.min_avg_daily_value:
        return None, "liquidity"
    if ind["current_price"] < settings.min_price:
        return None, "price"
    if ind["sma200"] is None:
        return None, "no_data"
    if not (ind["current_price"] > ind["sma50"] > ind["sma200"]):
        return None, "trend"
    if ind["atr_pct"] < settings.min_atr_pct:
        return None, "volatility"
    if ind["day_change_pct"] > settings.max_day_change_pct:
        return None, "day_change"
    if ind["volume_ratio"] < settings.min_volume_ratio:
        return None, "volume"
    if ind["today_vol"] < settings.min_volume_shares:
        return None, "volume"
    if ind["day_change_pct"] <= 0.5:
        return None, "volume"
    if not (settings.rsi_min <= ind["rsi"] <= settings.rsi_max):
        return None, "rsi"
    if ind["momentum_5d"] < 2.0:
        return None, "momentum"

    vol_norm = min(ind["volume_ratio"] / 5.0, 1.0)
    momentum_norm = min(max(ind["momentum_5d"], -15), 15) / 15
    atr_norm = min(ind["atr_pct"] / 5.0, 1.0)

    return {
        "current_price": ind["current_price"],
        "volume_ratio": ind["volume_ratio"],
        "avg_daily_value": ind["avg_daily_value"],
        "day_change_pct": ind["day_change_pct"],
        "momentum_5d": ind["momentum_5d"],
        "rsi": ind["rsi"],
        "atr_pct": ind["atr_pct"],
        "sma50": ind["sma50"],
        "sma200": ind["sma200"],
        "screener_score": (vol_norm * 0.40)
        + (momentum_norm * 0.35)
        + (atr_norm * 0.25),
    }, "passed"


def regime_blocked(index_close: pd.Series | None) -> bool:
    """True when the index is below it's regime SMA - block new entries"""
    if index_close is None:
        return False
    try:
        if len(index_close) < settings.regime_sma_period:
            return False
        sma = float(index_close.tail(settings.regime_sma_period).mean())
        return float(index_close.iloc[-1]) < sma
    except Exception:
        return False


def screen(tickers: list[str]) -> list[dict]:
    """
    Download price/volume data for all tickers at once and apply
    math filters. Returns ranked list of candidates.

    config keys:
        min_volume_ratio      float  e.g. 2.0  (today vs 20d avg)
        min_volume_shares     int    e.g. 50000
        min_avg_daily_value   float  e.g. 2_00_00_000  (₹2 crore liquidity floor)
        max_day_change_pct    float  e.g. 8.0  (skip stocks that already ran)
        min_price             float  e.g. 100.0
        min_atr_pct           float  e.g. 1.5
        rsi_min               float  e.g. 55.0
        rsi_max               float  e.g. 70.0
    """
    try:
        _nifty = safe_yf_download("^NSEI", period="60d")
        if not _nifty.empty and regime_blocked(_nifty["Close"].squeeze()):
            logger.info(
                "screener_regime_blocked",
                reason="Nifty50 below 50d SMA - skipping new entries",
            )
            return []
    except Exception as e:
        logger.warning("regime_check_failed", error=str(e))

    logger.info("screener_start", total=len(tickers))

    if not tickers:
        logger.warning("screener_empty_universe")
        return []

    # Download all tickers in one batch
    raw = safe_yf_download(tickers, period="12mo", group_by="ticker")

    candidates = []
    counts = {
        "no_data": 0,
        "liquidity": 0,
        "price": 0,
        "trend": 0,
        "volatility": 0,
        "day_change": 0,
        "volume": 0,
        "rsi": 0,
        "passed": 0,
        "momentum": 0,
    }

    for ticker in tickers:
        try:
            df = extract_ticker_df(raw, ticker)
            if df is None:
                counts["no_data"] += 1
                continue

            df = df.dropna(subset=["Close", "Volume"])

            if len(df) < 25:
                counts["no_data"] += 1
                continue

            ind = compute_indicators(df)

            candidate, reason = evaluate_candidate(ind)
            counts[reason] += 1

            if candidate is None:
                continue

            candidates.append(
                {"ticker": ticker, "score": candidate["screener_score"], **candidate}
            )

        except Exception as e:
            logger.warning("ticker_screen_failed", ticker=ticker, error=str(e))
            counts["no_data"] += 1

    candidates.sort(key=lambda x: x["score"], reverse=True)
    logger.info("screener_done", **counts)
    return candidates

import yfinance as yf
import pandas as pd
import warnings
import structlog
from app.utils.indicators import compute_indicators

logger = structlog.get_logger()


def screen(tickers: list[str], config: dict) -> list[dict]:
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
    logger.info("screener_start", total=len(tickers))

    if not tickers:
        logger.warning("screener_empty_universe")
        return []

    # Download all tickers in one batch
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = yf.download(
            tickers,
            period="12mo",
            interval="1d",
            group_by="ticker",
            progress=False,
            auto_adjust=True,
        )

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
    }

    for ticker in tickers:
        try:
            # Extract this ticker's slice from the batch download
            if isinstance(raw.columns, pd.MultiIndex):
                if ticker not in raw.columns.get_level_values(0):
                    counts["no_data"] += 1
                    continue
                df = raw[ticker]
            else:
                df = raw

            df = df.dropna(subset=["Close", "Volume"])

            if len(df) < 25:
                counts["no_data"] += 1
                continue

            ind = compute_indicators(df)

            # Filter 1: liquidity
            if ind["avg_daily_value"] < config["min_avg_daily_value"]:
                counts["liquidity"] += 1
                continue

            # Filter 2: minimum price
            if ind["current_price"] < config["min_price"]:
                counts["price"] += 1
                continue

            # Filter 3: trend — price above SMA50 above SMA200
            if ind["sma200"] is None:
                counts["no_data"] += 1
                continue
            if not (ind["current_price"] > ind["sma50"] > ind["sma200"]):
                counts["trend"] += 1
                continue

            # Filter 4: volatility
            if ind["atr_pct"] < config["min_atr_pct"]:
                counts["volatility"] += 1
                continue

            # Filter 5: skip stocks that already surged today
            if ind["day_change_pct"] > config["max_day_change_pct"]:
                counts["day_change"] += 1
                continue

            # Filter 6: unusual volume
            if ind["volume_ratio"] < config["min_volume_ratio"]:
                counts["volume"] += 1
                continue
            if ind["today_vol"] < config["min_volume_shares"]:
                counts["volume"] += 1
                continue

            # Filter 7: RSI in tradeable range
            if not (config["rsi_min"] <= ind["rsi"] <= config["rsi_max"]):
                counts["rsi"] += 1
                continue

            # Passed — compute ranking score
            momentum_norm = min(max(ind["momentum_5d"], -15), 15) / 15
            atr_norm      = min(ind["atr_pct"] / 5.0, 1.0)
            score = (ind["volume_ratio"] * 0.40) + (momentum_norm * 0.35) + (atr_norm * 0.25)

            candidates.append({
                "ticker":          ticker,
                "current_price":   ind["current_price"],
                "volume_ratio":    ind["volume_ratio"],
                "avg_daily_value": ind["avg_daily_value"],
                "day_change_pct":  ind["day_change_pct"],
                "momentum_5d":     ind["momentum_5d"],
                "rsi":             ind["rsi"],
                "atr_pct":         ind["atr_pct"],
                "sma50":           ind["sma50"],
                "sma200":          ind["sma200"],
                "score":           round(score, 3),
            })
            counts["passed"] += 1

        except Exception as e:
            logger.warning("ticker_screen_failed", ticker=ticker, error=str(e))
            counts["no_data"] += 1

    candidates.sort(key=lambda x: x["score"], reverse=True)
    logger.info("screener_done", **counts)
    return candidates

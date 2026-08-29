from datetime import date

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


def breadth_pct(closes: pd.DataFrame | None) -> float | None:
    """Percentage of the universe trading above its own 50-day average.

    Only tickers with usable data are counted — a missing series compares as
    False and would otherwise be counted as a downtrend, dragging breadth down
    early in a run. Returns None when it cannot be computed, so callers can
    fail open.
    """
    if closes is None or closes.empty or len(closes) < settings.regime_sma_period:
        return None
    try:
        last = closes.iloc[-1]
        sma = closes.tail(settings.regime_sma_period).mean()
        valid = last.notna() & sma.notna()
        if not valid.any():
            return None
        return float((last[valid] > sma[valid]).mean() * 100)
    except Exception:
        return None


def regime_blocked_by_breadth(closes: pd.DataFrame | None) -> bool:
    """True when most of the universe sits below its own moving average.

    Fails open like the index gate: a silently halted bot looks exactly like a
    quiet market.
    """
    b = breadth_pct(closes)
    return False if b is None else b < settings.breadth_floor_pct


def screen(tickers: list[str]) -> list[dict]:
    """Run the full universe through the regime gate and the screener filters.

    Downloads every ticker in one batch, then applies `evaluate_candidate` to
    each. Returns survivors sorted best-first by ranking score, or an empty
    list if the regime gate is closed.
    """
    logger.info("screener_start", total=len(tickers))

    if not tickers:
        logger.warning("screener_empty_universe")
        return []

    # Download all tickers in one batch
    raw = safe_yf_download(tickers, period="12mo", group_by="ticker")

    # The regime gate runs after the download because breadth is measured on
    # the universe itself, which this batch already contains.
    try:
        try:
            closes = raw.xs("Close", axis=1, level=1)
        except Exception:
            closes = None
        if regime_blocked_by_breadth(closes):
            logger.info(
                "screener_regime_blocked",
                reason="under half the universe above its 50d SMA",
            )
            return []
    except Exception as e:
        logger.warning("regime_check_failed", error=str(e))

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
        "stale": 0,
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

            # The scan runs late in the session and screens today's partial
            # bar deliberately. If the feed has not published it yet, the last
            # bar is yesterday's — we would screen yesterday's completed data
            # while buying at today's price, silently reverting to the old
            # entry model with no error.
            if df.index[-1].date() != date.today():
                counts["stale"] += 1
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

    # One stale ticker is a quiet listing; most of the universe stale means the
    # feed has not published today yet and this scan saw almost nothing.
    if tickers and counts["stale"] > len(tickers) / 2:
        logger.error(
            "screener_feed_stale",
            stale=counts["stale"],
            total=len(tickers),
            reason="today's bar missing for most of the universe",
        )

    return candidates

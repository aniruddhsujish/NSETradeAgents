import yfinance as yf
import pandas as pd
import structlog

logger = structlog.get_logger()

# Maps yfinance sector names → NSE sector index ticker
# yfinance returns names like "Technology", "Financial Services" — not "NIFTY IT"
SECTOR_MAP = {
    "Technology": "^CNXIT",
    "Financial Services": "^NSEBANK",
    "Healthcare": "^CNXPHARMA",
    "Consumer Cyclical": "^CNXAUTO",
    "Consumer Defensive": "^CNXFMCG",
    "Basic Materials": "^CNXMETAL",
    "Real Estate": "^CNXREALTY",
    "Energy": "^CNXENERGY",
    "Industrials": "^CNXINFRA",
    "Communication Services": "^CNXMEDIA",
    "Utilities": "^CNXENERGY",  # closest proxy
}


def _day_change_pct(ticker_sym: str, df: pd.DataFrame | None = None) -> float | None:
    """Return today's % change for a given yfinance ticker symbol.
    If df is provided (pre-fetched), uses it directly instead of downloading."""
    try:
        if df is not None and len(df) >= 2:
            close = df["Close"].squeeze()
        else:
            data = yf.download(
                ticker_sym, period="5d", interval="1d", progress=False, auto_adjust=True
            )
            if data is None or len(data) < 2:
                return None
            close = data["Close"].squeeze()
        return float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)
    except Exception:
        return None


def fetch_market_context(
    ticker: str,
    ticker_df: pd.DataFrame | None = None,
    ticker_info: dict | None = None,
    nifty_df: pd.DataFrame | None = None,
    sector_dfs: dict[str, pd.DataFrame] | None = None,
) -> dict:
    """
    Collect market-wide and stock-level context

    Returns:
        nifty_day_pct      float   Nifty 50 day change %
        nifty_5d_pct       float   Nifty 50 5-day change %
        market_label       str     "bullish" / "bearish" / "neutral"
        sector             str     Sector name from stock info (or "Unknown")
        sector_day_pct     float   Sector index day change % (or None)
        pct_from_52w_high  float   How far stock is below its 52-week high
        pct_from_52w_low   float   How far stock is above its 52-week low
        divergence_note    str     e.g. "Stock up while sector down"
    """
    logger.info("market_context_start", ticker=ticker)

    # --- 1. Nifty 50 — use pre-fetched df if available --------------------------------
    try:
        nifty_raw = (
            nifty_df
            if nifty_df is not None
            else yf.download(
                "^NSEI", period="10d", interval="1d", progress=False, auto_adjust=True
            )
        )
        nifty_close = nifty_raw["Close"].squeeze()
        nifty_day_pct = float(
            (nifty_close.iloc[-1] - nifty_close.iloc[-2]) / nifty_close.iloc[-2] * 100
        )
        nifty_5d_pct = (
            float(
                (nifty_close.iloc[-1] - nifty_close.iloc[-6])
                / nifty_close.iloc[-6]
                * 100
            )
            if len(nifty_close) >= 6
            else 0.0
        )
    except Exception as e:
        logger.warning("nifty_fetch_failed", error=str(e))
        nifty_day_pct = 0.0
        nifty_5d_pct = 0.0

    if nifty_day_pct > 0.5:
        market_label = "bullish"
    elif nifty_day_pct < -0.5:
        market_label = "bearish"
    else:
        market_label = "neutral"

    # --- 2. Sector — use pre-fetched info if available --------------------------------
    sector = "Unknown"
    sector_day_pct = None
    try:
        info = ticker_info if ticker_info is not None else yf.Ticker(ticker).info
        sector = info.get("sector") or info.get("industry") or "Unknown"

        # Direct lookup — keys match yfinance sector names exactly
        matched_index = SECTOR_MAP.get(sector)
        if matched_index:
            injected = sector_dfs.get(matched_index) if sector_dfs else None
            sector_day_pct = _day_change_pct(matched_index, df=injected)
    except Exception as e:
        logger.warning("sector_fetch_failed", ticker=ticker, error=str(e))

    # --- 3. 52-week position — use pre-fetched ticker_df (12mo covers 52wk) ----------
    pct_from_52w_high = None
    pct_from_52w_low = None
    try:
        hist = (
            ticker_df
            if ticker_df is not None
            else yf.download(
                ticker, period="52wk", interval="1d", progress=False, auto_adjust=True
            )
        )

        if hist is not None and len(hist) > 0:
            current = float(hist["Close"].squeeze().iloc[-1])
            high_52w = float(hist["High"].squeeze().max())
            low_52w = float(hist["Low"].squeeze().min())
            pct_from_52w_high = round((current - high_52w) / high_52w * 100, 2)
            pct_from_52w_low = round((current - low_52w) / low_52w * 100, 2)
    except Exception as e:
        logger.warning("52w_fetch_failed", ticker=ticker, error=str(e))

    # --- 4. Divergence note — compute from pre-fetched ticker_df if available --------
    stock_day_pct = _day_change_pct(ticker, df=ticker_df)
    divergence_note = ""
    if stock_day_pct is not None and sector_day_pct is not None:
        if stock_day_pct > 1.0 and sector_day_pct < -0.5:
            divergence_note = "Stock rising while sector falling - relative strength"
        elif stock_day_pct < -1.0 and sector_day_pct > 0.5:
            divergence_note = "Stock falling while sector rising - relative weakness"
        else:
            divergence_note = "Stock moving in line with sector"

    context = {
        "nifty_day_pct": round(nifty_day_pct, 2),
        "nifty_5d_pct": round(nifty_5d_pct, 2),
        "market_label": market_label,
        "sector": sector,
        "sector_day_pct": (
            round(sector_day_pct, 2) if sector_day_pct is not None else None
        ),
        "pct_from_52w_high": pct_from_52w_high,
        "pct_from_52w_low": pct_from_52w_low,
        "divergence_note": divergence_note,
    }
    logger.info(
        "market_context_done",
        ticker=ticker,
        market=market_label,
        nifty_day=nifty_day_pct,
    )
    return context

import warnings
import pandas as pd
import yfinance as yf

_OHLCV_FIELDS = frozenset({"Close", "Open", "High", "Low", "Volume", "Adj Close"})


def safe_yf_download(ticker, period: str, interval: str = "1d", **kwargs) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return yf.download(
            ticker, period=period, interval=interval,
            progress=False, auto_adjust=True, **kwargs
        )


def extract_ticker_df(raw: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """
    Extract a single ticker's DataFrame from a yfinance download.
    - Batch (ticker, field) MultiIndex: extracts the ticker's slice; None if ticker missing
    - Single-ticker (field, ticker) MultiIndex: flattens to plain column names
    - Flat DataFrame: returns as-is
    """
    if not isinstance(raw.columns, pd.MultiIndex):
        return raw

    level0 = set(raw.columns.get_level_values(0))

    if ticker in level0:
        # Batch download — ticker is at level 0
        df = raw[ticker].copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df

    if level0 & _OHLCV_FIELDS:
        # Single-ticker download — field names are at level 0; just flatten
        df = raw.copy()
        df.columns = df.columns.get_level_values(0)
        return df

    # Ticker not present in this batch download
    return None

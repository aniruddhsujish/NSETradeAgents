import sqlite3
from datetime import date
import pandas as pd


class BacktestStore:
    def __init__(self, db_path: str = "backtest_data.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)

    def get_trading_days(self, start: date, end: date) -> list[date]:
        cur = self._conn.execute(
            "SELECT DISTINCT date FROM bars "
            "WHERE ticker='^NSEI' AND date>=? and date<=? ORDER BY date",
            (start.isoformat(), end.isoformat()),
        )
        return [date.fromisoformat(row[0]) for row in cur.fetchall()]

    def get_universe(self) -> list[str]:
        cur = self._conn.execute(
            "SELECT DISTINCT ticker FROM bars WHERE ticker NOT LIKE '^%' ORDER BY ticker"
        )
        return [row[0] for row in cur.fetchall()]

    def preload(self, warmup_start: date, end: date) -> dict[str, pd.DataFrame]:
        df = pd.read_sql_query(
            "SELECT ticker, date, open, high, low, close, volume "
            "FROM bars WHERE date>=? AND date<=? ORDER BY ticker, date",
            self._conn,
            params=(warmup_start.isoformat(), end.isoformat()),
        )
        if df.empty:
            return {}
        df["date"] = pd.to_datetime(df["date"])
        df = df.rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            }
        )
        result = {}
        for ticker, group in df.groupby("ticker"):
            result[str(ticker)] = (
                group.drop("ticker", axis=1).set_index("date").sort_index()
            )
        return result

    def close(self):
        self._conn.close()

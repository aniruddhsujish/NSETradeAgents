import pytest
from app.portfolio.simulator import PortfolioSimulator

TRADE_RESULT = {
    "ticker": "TITAN.NS",
    "price": 500.0,
    "quantity": 50,
    "position_size_inr": 25000.0,
    "stop_loss": 465.0,
    "take_profit": 590.0,
    "confidence": 85,
    "reasoning": "Strong uptrend",
}

TECHNICAL = {"summary": "Bullish MACD crossover"}
SENTIMENT = {"summary": "Positive news flow"}


def test_open_trade(mock_db, monkeypatch):
    monkeypatch.setattr("app.portfolio.simulator.settings.starting_capital", 100000)

    sim = PortfolioSimulator()
    trade = sim.open_trade(TRADE_RESULT, TECHNICAL, SENTIMENT)

    assert trade is not None
    assert trade.ticker == "TITAN.NS"
    assert trade.entry_price == 500.0
    assert trade.quantity == 50
    assert trade.status == "open"
    assert trade.stop_loss == 465.0
    assert trade.take_profit == 590.0


def test_open_trade_duplicate_blocked(mock_db, monkeypatch):
    monkeypatch.setattr("app.portfolio.simulator.settings.starting_capital", 100000)

    sim = PortfolioSimulator()
    first = sim.open_trade(TRADE_RESULT, TECHNICAL, SENTIMENT)
    second = sim.open_trade(TRADE_RESULT, TECHNICAL, SENTIMENT)

    assert first is not None
    assert second is None


def test_open_trade_insufficient_funds(mock_db, monkeypatch):
    monkeypatch.setattr("app.portfolio.simulator.settings.starting_capital", 10000)

    sim = PortfolioSimulator()
    trade = sim.open_trade(TRADE_RESULT, TECHNICAL, SENTIMENT)

    assert trade is None


def test_close_trade(mock_db, monkeypatch):
    monkeypatch.setattr("app.portfolio.simulator.settings.starting_capital", 100000)

    sim = PortfolioSimulator()
    sim.open_trade(TRADE_RESULT, TECHNICAL, SENTIMENT)
    trade = sim.close_trade("TITAN.NS", 550.0, "tp")

    assert trade is not None
    assert trade.status == "closed"
    assert trade.close_price == 550.0
    assert trade.close_reason == "tp"
    assert trade.pnl == 2500.0  # (550 - 500) * 50 shares
    assert trade.pnl_pct == 10.0  # 10% gain


def test_close_trade_not_found(mock_db, monkeypatch):
    monkeypatch.setattr("app.portfolio.simulator.settings.starting_capital", 100000)

    sim = PortfolioSimulator()
    trade = sim.close_trade("RELIANCE.NS", 550.0, "tp")

    assert trade is None


def test_save_snapshot(mock_db, monkeypatch):
    monkeypatch.setattr("app.portfolio.simulator.settings.starting_capital", 100000)

    sim = PortfolioSimulator()
    sim.open_trade(TRADE_RESULT, TECHNICAL, SENTIMENT)
    snapshot = sim.save_snapshot()

    assert snapshot is not None
    assert snapshot.open_positions == 1
    assert snapshot.invested == 25000.0
    assert snapshot.cash == 75000.0
    assert snapshot.total_value == 100000.0

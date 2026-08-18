"""Tests for run_scan, the daily live entry point.

Collaborators (universe, screener, graph, simulator) are stubbed so these cover
the scan's own control flow: what gets recorded, when it stops early, and how it
handles a ticker that fails.
"""

from contextlib import contextmanager

import pytest

import main
from app.core import health
from app.models.models import DecisionRecord, ScanRun


def candidate(ticker: str, score: float = 0.8) -> dict:
    return {"ticker": ticker, "score": score}


def state(*, executed: bool, rules_score: int = 71) -> dict:
    """A plausible final graph state."""
    return {
        "trade_result": (
            {
                "executed": True,
                "action": "BUY",
                "ticker": "X",
                "price": 500.0,
                "quantity": 50,
                "position_size_inr": 25000.0,
                "stop_loss": 465.0,
                "take_profit": 590.0,
                "sector": "IT",
                "atr_pct": 2.4,
                "confidence": rules_score,
                "reasoning": "",
            }
            if executed
            else {"action": "BLOCKED", "executed": False, "reasons": ["score too low"]}
        ),
        "rules_score": rules_score,
        "rules_bands": {
            "entry_timing": "ACCEPTABLE",
            "momentum_quality": "STRONG",
            "risk_reward_view": "FAVORABLE",
            "market_regime": "NEUTRAL",
        },
        "technical_signals": {
            "indicators": {
                "current_price": 500.0,
                "rsi": 62.0,
                "atr_pct": 2.4,
                "volume_ratio": 3.1,
                "momentum_5d": 5.2,
                "day_change_pct": 1.8,
            }
        },
    }


def portfolio(open_positions: int = 0, positions: list | None = None) -> dict:
    return {
        "cash": 200000.0,
        "open_positions": open_positions,
        "positions": positions or [],
    }


@pytest.fixture
def scan_env(db_session, monkeypatch):
    """Wire run_scan to an in-memory DB and stubbed collaborators."""

    @contextmanager
    def _get_db():
        yield db_session

    monkeypatch.setattr(main, "get_db", _get_db)
    monkeypatch.setattr(main, "fetch_universe", lambda: ["A.NS", "B.NS"])
    monkeypatch.setattr(main.simulator, "is_circuit_breaker_active", lambda: False)
    monkeypatch.setattr(main.simulator, "get_portfolio_state", lambda: portfolio())
    monkeypatch.setattr(main.simulator, "save_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(main.simulator, "open_trade", lambda **k: None)
    monkeypatch.setattr(main.settings, "max_positions", 5)
    return db_session


def records(db):
    return db.query(DecisionRecord).all()


# ── the happy path ───────────────────────────────────────────────────────────


def test_scan_runs_end_to_end_and_writes_a_record(scan_env, monkeypatch):
    monkeypatch.setattr(main, "screen", lambda t: [candidate("A.NS")])
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=True))

    main.run_scan()

    rows = records(scan_env)
    assert len(rows) == 1
    assert rows[0].ticker == "A.NS"
    assert rows[0].score == 71
    assert rows[0].entered is True
    assert rows[0].as_of is not None


def test_screen_is_called_with_tickers_only(scan_env, monkeypatch):
    """screen() takes the ticker list and nothing else."""
    seen = {}

    def fake_screen(tickers):
        seen["tickers"] = tickers
        return []

    monkeypatch.setattr(main, "screen", fake_screen)
    main.run_scan()
    assert seen["tickers"] == ["A.NS", "B.NS"]


# ── records are written for rejections too ───────────────────────────────────


def test_blocked_candidate_still_gets_a_record(scan_env, monkeypatch):
    """The whole point of decision records: we keep the 'no' decisions."""
    monkeypatch.setattr(main, "screen", lambda t: [candidate("A.NS")])
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))

    main.run_scan()

    rows = records(scan_env)
    assert len(rows) == 1
    assert rows[0].entered is False
    assert rows[0].block_reason == "score too low"


def test_record_captures_bands_and_indicators(scan_env, monkeypatch):
    monkeypatch.setattr(main, "screen", lambda t: [candidate("A.NS")])
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))

    main.run_scan()

    row = records(scan_env)[0]
    assert row.market_regime == "NEUTRAL"
    assert row.momentum_quality == "STRONG"
    assert row.rsi == 62.0
    assert row.atr_pct == 2.4
    assert row.veto_verdict is None  # not wired up yet
    assert row.outcome_pnl_pct is None  # post-mortem fills this later


# ── early exits ──────────────────────────────────────────────────────────────


def test_no_candidates_writes_nothing(scan_env, monkeypatch):
    monkeypatch.setattr(main, "screen", lambda t: [])
    main.run_scan()
    assert records(scan_env) == []


def test_circuit_breaker_stops_the_scan(scan_env, monkeypatch):
    monkeypatch.setattr(main, "screen", lambda t: [candidate("A.NS")])
    monkeypatch.setattr(main.simulator, "is_circuit_breaker_active", lambda: True)
    monkeypatch.setattr(
        main, "analyze_ticker", lambda **k: pytest.fail("should not analyse")
    )

    main.run_scan()
    assert records(scan_env) == []


def test_stops_when_portfolio_is_full(scan_env, monkeypatch):
    monkeypatch.setattr(main, "screen", lambda t: [candidate("A.NS")])
    monkeypatch.setattr(main.simulator, "get_portfolio_state", lambda: portfolio(5))
    monkeypatch.setattr(
        main, "analyze_ticker", lambda **k: pytest.fail("should not analyse")
    )

    main.run_scan()
    assert records(scan_env) == []


def test_skips_tickers_already_held(scan_env, monkeypatch):
    held = portfolio(1, [{"ticker": "A.NS", "sector": "IT"}])
    monkeypatch.setattr(main, "screen", lambda t: [candidate("A.NS")])
    monkeypatch.setattr(main.simulator, "get_portfolio_state", lambda: held)
    monkeypatch.setattr(
        main, "analyze_ticker", lambda **k: pytest.fail("should not analyse")
    )

    main.run_scan()
    assert records(scan_env) == []


# ── failure handling ─────────────────────────────────────────────────────────


def test_one_bad_ticker_does_not_stop_the_scan(scan_env, monkeypatch):
    """A single ticker blowing up must not cost us the rest of the day."""

    def flaky(*, ticker, **k):
        if ticker == "A.NS":
            raise RuntimeError("yfinance exploded")
        return state(executed=False)

    monkeypatch.setattr(
        main, "screen", lambda t: [candidate("A.NS"), candidate("B.NS")]
    )
    monkeypatch.setattr(main, "analyze_ticker", flaky)

    main.run_scan()

    rows = records(scan_env)
    assert [r.ticker for r in rows] == ["B.NS"]


# ── the heartbeat ────────────────────────────────────────────────────────────


def runs(db):
    return db.query(ScanRun).order_by(ScanRun.id).all()


def test_scan_records_a_run_even_when_nothing_is_found(scan_env, monkeypatch):
    """The reason ScanRun exists rather than counting DecisionRecords.

    A quiet day writes no decisions, and so does a scheduler that never fired.
    Without this row the health check cannot tell them apart.
    """
    monkeypatch.setattr(main, "screen", lambda t: [])

    main.run_scan()

    assert records(scan_env) == []
    rows = runs(scan_env)
    assert len(rows) == 1
    assert rows[0].candidates_found == 0
    assert rows[0].error is None
    assert rows[0].ran_at is not None


def test_scan_records_the_candidate_count(scan_env, monkeypatch):
    monkeypatch.setattr(
        main, "screen", lambda t: [candidate("A.NS"), candidate("B.NS")]
    )
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))

    main.run_scan()

    assert runs(scan_env)[0].candidates_found == 2


def test_circuit_breaker_still_records_a_run(scan_env, monkeypatch):
    """An early return is still a run — finally fires on the way out."""
    monkeypatch.setattr(main, "screen", lambda t: [candidate("A.NS")])
    monkeypatch.setattr(main.simulator, "is_circuit_breaker_active", lambda: True)

    main.run_scan()

    rows = runs(scan_env)
    assert len(rows) == 1
    assert rows[0].candidates_found == 1  # found them, just didn't act on them


def test_scan_records_the_error_when_it_crashes(scan_env, monkeypatch):
    """A crashed scan must leave a trace, not just vanish."""

    def boom(tickers):
        raise RuntimeError("universe fetch died")

    monkeypatch.setattr(main, "screen", boom)

    with pytest.raises(RuntimeError):
        main.run_scan()

    rows = runs(scan_env)
    assert len(rows) == 1
    assert "universe fetch died" in rows[0].error


def test_a_broken_heartbeat_write_does_not_mask_the_real_error(monkeypatch):
    """An exception raised inside finally replaces the one on its way out.

    If the database is down, the useful error is whatever actually failed —
    not the follow-on failure to record that it failed.
    """

    @contextmanager
    def dead_db():
        raise RuntimeError("database unreachable")
        yield  # pragma: no cover

    monkeypatch.setattr(main, "get_db", dead_db)
    monkeypatch.setattr(main, "fetch_universe", lambda: ["A.NS"])
    monkeypatch.setattr(
        main, "screen", lambda t: (_ for _ in ()).throw(ValueError("the real problem"))
    )

    with pytest.raises(ValueError, match="the real problem"):
        main.run_scan()


def test_the_heartbeat_is_reported_in_memory_too(scan_env, monkeypatch):
    """/health reads the cached value rather than querying, so the scan must
    push it — otherwise health stays stale until the process restarts."""
    monkeypatch.setattr(main, "screen", lambda t: [])

    main.run_scan()

    assert health._last_scan is not None
    assert health._loaded is True

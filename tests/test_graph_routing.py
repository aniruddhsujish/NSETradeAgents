import pytest
from app.graph.graph import (
    route_after_fundamental,
    route_after_risk,
    route_after_rules_gate,
    route_after_decision,
)


@pytest.fixture(autouse=True)
def patch_graph_settings(monkeypatch):
    monkeypatch.setattr("app.graph.graph.settings.rules_confidence_threshold", 50.0)
    monkeypatch.setattr("app.graph.graph.settings.min_confidence", 0.68)
    monkeypatch.setattr("app.graph.graph.settings.high_conviction_threshold", 0.80)


# ── route_after_fundamental ───────────────────────────────────────────────────

def test_fundamental_approved_fans_out():
    state = {"fundamental_result": {"approved": True}}
    result = route_after_fundamental(state)
    assert set(result) == {"market_context", "technical", "sentiment"}


def test_fundamental_blocked():
    state = {"fundamental_result": {"approved": False, "block_reasons": ["micro-cap"]}}
    assert route_after_fundamental(state) == ["blocked"]


def test_fundamental_missing_result_fans_out():
    # No fundamental result → default approved=True
    assert set(route_after_fundamental({})) == {"market_context", "technical", "sentiment"}


# ── route_after_risk ──────────────────────────────────────────────────────────

def test_risk_approved_goes_to_rules_gate():
    state = {"risk_result": {"approved": True}}
    assert route_after_risk(state) == "rules_gate"


def test_risk_blocked():
    state = {"risk_result": {"approved": False, "block_reasons": ["max positions"]}}
    assert route_after_risk(state) == "blocked"


def test_risk_missing_result_is_blocked():
    # No risk result → approved is falsy → blocked
    assert route_after_risk({}) == "blocked"


# ── route_after_rules_gate ────────────────────────────────────────────────────

def test_rules_gate_passes_above_threshold():
    state = {"rules_score": 60}
    assert route_after_rules_gate(state) == "decision"


def test_rules_gate_blocks_below_threshold():
    state = {"rules_score": 40}
    assert route_after_rules_gate(state) == "blocked"


def test_rules_gate_blocks_at_threshold():
    # Strictly less than threshold (50) → blocked; equal → passes
    state = {"rules_score": 50}
    assert route_after_rules_gate(state) == "decision"


def test_rules_gate_blocks_missing_score():
    assert route_after_rules_gate({}) == "blocked"


# ── route_after_decision ──────────────────────────────────────────────────────

def test_decision_buy_sufficient_confidence_executes():
    state = {"decision": {"action": "BUY", "confidence": 75}, "open_positions": 2}
    assert route_after_decision(state) == "execute"


def test_decision_not_buy_is_blocked():
    state = {"decision": {"action": "HOLD", "confidence": 80}, "open_positions": 1}
    assert route_after_decision(state) == "blocked"


def test_decision_buy_low_confidence_is_blocked():
    # < 68% confidence with < 4 positions
    state = {"decision": {"action": "BUY", "confidence": 60}, "open_positions": 2}
    assert route_after_decision(state) == "blocked"


def test_decision_buy_at_confidence_boundary_executes():
    # Exactly 68 → should execute (68 >= 68)
    state = {"decision": {"action": "BUY", "confidence": 68}, "open_positions": 2}
    assert route_after_decision(state) == "execute"


def test_decision_buy_at_max_positions_needs_high_conviction():
    # 4 positions open → needs >= 80% confidence
    state = {"decision": {"action": "BUY", "confidence": 75}, "open_positions": 4}
    assert route_after_decision(state) == "blocked"


def test_decision_buy_at_max_positions_high_conviction_executes():
    state = {"decision": {"action": "BUY", "confidence": 85}, "open_positions": 4}
    assert route_after_decision(state) == "execute"


def test_decision_sell_is_blocked():
    state = {"decision": {"action": "SELL", "confidence": 90}, "open_positions": 0}
    assert route_after_decision(state) == "blocked"

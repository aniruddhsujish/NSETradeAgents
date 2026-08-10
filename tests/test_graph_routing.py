import pytest
from app.graph.graph import (
    route_after_fundamental,
    route_after_risk,
    route_after_rules_gate,
)


@pytest.fixture(autouse=True)
def patch_graph_settings(monkeypatch):
    monkeypatch.setattr("app.graph.graph.settings.rules_confidence_threshold", 50.0)


# ── route_after_fundamental ───────────────────────────────────────────────────

def test_fundamental_approved_fans_out():
    state = {"fundamental_result": {"approved": True}}
    result = route_after_fundamental(state)
    assert set(result) == {"market_context", "technical"}


def test_fundamental_blocked():
    state = {"fundamental_result": {"approved": False, "block_reasons": ["micro-cap"]}}
    assert route_after_fundamental(state) == ["blocked"]


def test_fundamental_missing_result_fans_out():
    # No fundamental result → default approved=True
    assert set(route_after_fundamental({})) == {"market_context", "technical"}


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
    assert route_after_rules_gate(state) == "execute"


def test_rules_gate_blocks_below_threshold():
    state = {"rules_score": 40}
    assert route_after_rules_gate(state) == "blocked"


def test_rules_gate_passes_at_threshold():
    # Strictly less than threshold (50) → blocked; equal → passes
    state = {"rules_score": 50}
    assert route_after_rules_gate(state) == "execute"


def test_rules_gate_blocks_missing_score():
    assert route_after_rules_gate({}) == "blocked"

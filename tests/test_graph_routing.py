import pytest
from app.graph.graph import (
    route_after_fundamental,
    route_after_risk,
    route_after_rules_gate,
    route_after_veto,
)


@pytest.fixture(autouse=True)
def patch_graph_settings(monkeypatch):
    monkeypatch.setattr("app.graph.graph.settings.rules_confidence_threshold", 50.0)
    monkeypatch.setattr("app.graph.graph.settings.veto_mode", "shadow")


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
    assert route_after_rules_gate(state) == "veto"


def test_rules_gate_blocks_below_threshold():
    state = {"rules_score": 40}
    assert route_after_rules_gate(state) == "blocked"


def test_rules_gate_passes_at_threshold():
    # Strictly less than threshold (50) → blocked; equal → passes
    state = {"rules_score": 50}
    assert route_after_rules_gate(state) == "veto"


def test_rules_gate_blocks_missing_score():
    assert route_after_rules_gate({}) == "blocked"


def test_rules_gate_skips_veto_when_off(monkeypatch):
    monkeypatch.setattr("app.graph.graph.settings.veto_mode", "off")
    assert route_after_rules_gate({"rules_score": 60}) == "execute"


# ── route_after_veto ──────────────────────────────────────────────────────────
#
# Shadow mode never blocks, so the KILL branch below is the only coverage the
# acting path gets until the flag is flipped in production.


def test_shadow_mode_executes_despite_a_kill():
    """The whole point of shadow mode: record the verdict, change nothing."""
    state = {"veto_result": {"verdict": "KILL", "reason": "ADVERSE_NEWS"}}
    assert route_after_veto(state) == "execute"


def test_shadow_mode_executes_on_pass():
    assert route_after_veto({"veto_result": {"verdict": "PASS"}}) == "execute"


def test_acting_mode_blocks_on_kill(monkeypatch):
    monkeypatch.setattr("app.graph.graph.settings.veto_mode", "acting")
    state = {"veto_result": {"verdict": "KILL", "reason": "SUPPLY_OVERHANG"}}
    assert route_after_veto(state) == "blocked"


def test_acting_mode_executes_on_pass(monkeypatch):
    monkeypatch.setattr("app.graph.graph.settings.veto_mode", "acting")
    assert route_after_veto({"veto_result": {"verdict": "PASS"}}) == "execute"


def test_acting_mode_fails_open_when_veto_missing(monkeypatch):
    """No verdict must not block the trade — the deterministic system is the
    validated one, so an outage degrades to it rather than halting."""
    monkeypatch.setattr("app.graph.graph.settings.veto_mode", "acting")
    assert route_after_veto({}) == "execute"

"""Which gate stopped a candidate — shown in the table, not just on expand."""
from datetime import date

import pytest

from app.api.routes import _blocked_by
from app.core.config import settings
from app.models.models import DecisionRecord


def rec(**kw) -> DecisionRecord:
    base = dict(as_of=date(2026, 9, 4), ticker="X.NS", score=80,
                entered=False, regime_open=True, veto_verdict=None)
    return DecisionRecord(**{**base, **kw})


def test_a_taken_trade_has_no_blocker():
    assert _blocked_by(rec(entered=True)) is None


def test_a_low_score_is_attributed_to_the_score():
    assert _blocked_by(rec(score=52)) == "score"


def test_score_wins_over_a_shut_regime():
    """Ordered by where the gates sit: a candidate that failed on score never
    reached the regime check, so blaming the regime would be wrong."""
    assert _blocked_by(rec(score=52, regime_open=False)) == "score"


def test_a_cleared_score_with_a_shut_regime_is_attributed_to_the_regime():
    """The case that prompted this: veto passed, nothing traded, and the table
    showed no reason at all."""
    assert _blocked_by(rec(score=70, regime_open=False, veto_verdict="PASS")) == "regime"


def test_a_kill_in_an_open_regime_is_attributed_to_the_veto():
    assert _blocked_by(rec(score=92, regime_open=True, veto_verdict="KILL")) == "veto"


def test_the_regime_outranks_a_kill_because_shadow_mode_does_not_block():
    """In shadow mode a KILL does not stop the trade, so when both apply the
    regime is what actually prevented it."""
    assert _blocked_by(rec(score=92, regime_open=False, veto_verdict="KILL")) == "regime"


def test_an_unscored_candidate_falls_back_rather_than_crashing():
    assert _blocked_by(rec(score=None, regime_open=None)) == "blocked"

# NSETradeAgents — Plan of Record

> The plan for turning this from a working swing-trade bot into (a) a defensible
> multi-agent system and (b) a strategy worth funding. Doubles as the syllabus:
> each phase names the orchestration concepts it teaches.
>
> **Scope note:** This document describes **`main`** and only `main`. An earlier
> attempt at a unified engine lives on branch `redesign-decicision-agent` and is
> **abandoned** — do not plan against it. (Stale `.pyc` files under
> `app/engine/__pycache__` and `app/data/__pycache__` are debris from it; there
> are no `.py` sources on `main`.)

---

## 1. Goals

1. **Learn multi-agent orchestration.** This project is the vehicle. Concepts get
   built by hand, not imported wholesale.
2. **A resume piece that survives scrutiny.** Specifically a multi-agent system
   that uses LangGraph and can *justify* the framework — see §5.
3. **Eventually, a real edge worth real capital.** This raises the bar on
   measurement in ways goals 1 and 2 don't (§3).

Goals 2 and 3 point the same direction: the strongest artifact this project can
produce is an honest ablation study — *does the LLM actually add alpha?* — and
that study **is** the measurement harness's output. Building the measuring stick
is not a detour from the resume goal. It is the resume goal.

---

## 2. Where things actually stand

### What runs today

**Live path** — `main.py`
```
fetch_universe() → filters.screen() → for each candidate: analyze_ticker() → simulator
```

**The graph** — `app/graph/graph.py`
```
START → fetch_data → fundamental ─[blocked]→ blocked → END
                                 └[approved]→ ┌ market_context ┐
                                              ├ technical      ├→ fetch_price → risk
                                              └ sentiment      ┘
risk ─[blocked]→ blocked
     └[ok]→ rules_gate ─[score < 50]→ blocked
                       └[score ≥ 50]→ decision (LLM) ─[not BUY / conf < 68]→ blocked
                                                     └[BUY]→ execute → END
```

**Backtest path** — `app/backtest/engine.py`, a **separate implementation** that
re-derives the same logic in a day loop. CLI: `python backtest.py`.

### Baseline numbers (2022–2025, ₹2L, rules-only)

| Metric | Value |
|---|---|
| Total return | +83.3% |
| CAGR | +16.4% |
| Sharpe | 1.41 |
| Max drawdown | 12.6% |
| Trades / win rate | 232 / 50.9% |
| Profit factor | 1.59 |
| Avg hold | 18.9 days |

Exit mix: **stop 72 · target 17 · timeout 108 · trail 35**

Year-by-year: 2022 **+33.5%** · 2023 **+33.0%** · 2024 **+8.7%** · 2025 **−6.6%**

### The three problems

**Problem 1 — The LLM layer is redundant and unmeasured.**

`rules_gate` (`graph.py:112`) calls `compute_rules_confidence()`, which derives
the five dimensions deterministically from indicators and scores them through
`compute_confidence()`. Then `decision` (`graph.py:123`) asks Sonnet to produce
**those same five dimensions**, scored by **the same function**. The LLM
re-derives arithmetic the computer already did — a calculator in a costume.

Worse: the +83.3% baseline **never invoked the LLM**. `engine.py:315` calls
`compute_rules_confidence` and stops. So the validated strategy is the
deterministic core, and the entire LLM layer sits on top contributing an unknown
amount — possibly negative.

> The one hint available is not encouraging: an older backtest of the
> LLM-in-the-loop system returned **+36.8%** (Jan 2023–Dec 2025). Different
> period *and* different code, so not a clean comparison — but it is not
> evidence the LLM helps, either. Settling this is Phase A's job.

**Problem 2 — Backtest ≠ live, and they've already drifted.**

The backtester re-implements rather than reuses. All eight screener filters are
inlined at `engine.py:290-311`, duplicating `filters.py:76-121`; exits, regime
gate, and market context likewise. A concrete drift already exists:
`_rules_signal_alignment` (`scoring.py:67`) consumes sentiment, but the
backtest hardcodes `{"signal": "HOLD", "score": 0}` → always `ACCEPTABLE`
(18 pts), while live sentiment can yield `STRONG` (30) or `CONFLICTED` (0).
**The same setup scores up to 30 points differently depending on which code path
you're in.** The backtested threshold of 50 therefore does not mean the same
thing live.

**Problem 3 — 47% of trades are dead money.** 108 of 232 exits are the 21-day
timeout: bought, held three weeks, closed mechanically for roughly nothing.
That is the largest single pool of wasted capital in the system.

---

## 3. What "real money" demands that a toy doesn't

The +83.3% is **in-sample, gross, and survivorship-biased**. Specifically:

1. **In-sample.** The git history is a record of fitting parameters to backtest
   output — `fc3fbb7` (revert RSI thresholds, add a momentum/entry-timing
   penalty), `3e1eab4` ("improvements from backtest results"), `3a1a928`
   (stop-loss cap). There is currently **no held-out period**, so there is zero
   out-of-sample evidence.
2. **Gross.** `engine.py` models no STT, no brokerage, no slippage. On
   smallcap/midcap names, across 232 round trips, this is not a rounding error.
3. **Survivorship-biased.** Universe seeded from *today's* constituents;
   delisted names — disproportionately losers — are absent.

None of this makes the strategy bad. It means the honest number is unknown and
lower. Correcting it is cheap, and *"I found my own backtest was inflated and
fixed it"* is a stronger interview story than a large number that can't be
defended.

---

## 4. Principles

1. **Backtest == live.** One source of truth per rule. Duplication drifts; it
   already has.
2. **LLM only where it reads text or exercises judgment** — never where a
   function computes the answer.
3. **Deterministic core, gradeable LLM edges.** The LLM's contribution must be
   isolatable and measurable as a delta.
4. **Measure before believing.** Every LLM change beats a rules-only baseline on
   the harness, or it doesn't ship.
5. **LangGraph must earn its place** (§5) — not be decoration.
6. **The user writes the code.** This is a learning project; guidance and review,
   not delivery.

---

## 5. The LangGraph justification problem

State it plainly: **the current graph does not justify LangGraph.** It is a
linear pipeline with a single fan-out of three independent nodes. It would be
~30 lines of plain Python. Adding a veto node doesn't fix that — it's one more
box in the same straight line. Anyone who knows the framework will notice.

Four things genuinely require it, and the plan below builds all four:

| Capability | Where it lands |
|---|---|
| **Checkpointed durable threads** — each open position is a graph thread resumed daily, carrying its own accumulated history | Phase B3 |
| **Cycles** — reflection → lesson → retrieved into future decisions is a loop, not a DAG | Phase B4 |
| **Tool-calling subgraphs** — the veto gathers evidence in its own inner loop | Phase B2 |
| **Human-in-the-loop `interrupt()`** — approval gate before live orders | Phase D |

**State-split decision (locked):** the authoritative trade ledger — entry price,
shares, stops, realized P&L — stays in SQLAlchemy. Financial records don't
belong in a framework's serialization format, particularly with a Postgres
migration ahead. The *agent's* memory for a position — entry thesis, prior
reviews, evidence already seen — lives in the LangGraph checkpointer keyed by
position ID. **LangGraph persists reasoning; the DB persists the books.**

---

## Phase A — Honest measurement

**Nothing in Phase B ships before this.** Without it, every later change is
tuned blind and every number is unfalsifiable.

| # | Task | Where |
|---|---|---|
| A1 | Pluggable **candidate-filter** and **allocator** hooks in the backtester, so any agent can be ablated in/out of a run | `app/backtest/engine.py` |
| A2 | **Decision records** — one row per candidate evaluated, bought *and* blocked, dimensions and indicators as columns | new module + `models.py` |
| A3 | **Run versioning** — every run stamped with git SHA + config hash | with A2 |
| A4 | Fix the **live/backtest divergences** — sentiment in `_rules_signal_alignment`; the hardcoded `>= 4` in `route_after_decision` (`graph.py:236`) vs `max_positions = 5` | `scoring.py`, `graph.py` |
| A5 | **Costs + slippage** — STT, brokerage, impact | `engine.py` |
| A6 | **Train/holdout split** — tune on 2022–24, freeze 2025, log every peek at the holdout | `backtest.py` |

**Concepts:** experiment design for stochastic systems · ablation methodology ·
why per-candidate records (not just executed trades) give ~10× the eval data ·
data snooping and how versioning makes it visible instead of invisible.

**Done when:** any config produces a number traceable to exact code + settings,
and rules-only vs LLM can be run head-to-head on identical inputs.

---

## Phase B — The agents

Four agents, distinct objectives, distinct cadences, sharing the records
substrate. Ordered by how cleanly each can be **proven**, not by how interesting
it is.

### B1 — Allocator (ranking + portfolio construction)

One call sees **all** surviving candidates plus current holdings and allocates
open slots. Replaces first-come slot-filling (`main.py:46`) and the
`0.40·vol + 0.35·momentum + 0.25·atr` blend.

*Why an LLM:* comparative judgment. Models are markedly better at "which of
these eight is most compelling, given I already hold these three" than at
"score this one 0–100 in isolation." It can also reason about concentration and
correlation, which the current sector gate does crudely.

*Backtestable:* **fully.** Cleanest measurement in the whole plan — hence first.

**Concepts:** listwise vs pointwise judgment · why per-call scoring quotas can't
work across independent calls · structured output over a variable-length slate.

### B2 — Forensic veto (entry gate)

Stop asking "is this a good buy?" — the screener already picked it for jumping,
so the model plays yes-man. Ask **"what specifically kills this trade?"** Output
is kill/pass **with a cited specific** — a date, a level, a filing — never a vibe.

**Subsumes the sentiment agent.** Don't run two news-reading LLMs. One text
agent, two outputs: any disqualifier (the veto) and any genuine catalyst (what
sentiment was meant to provide). The current mood-scorer is confirmation-prone,
neutral-in-backtest, and the source of the Problem-2 divergence. It retires here.

*Backtestability split — the critical design constraint:*
- **Rewindable (backtests cleanly):** earnings dates, chart structure from
  stored bars (resistance walls, block-deal-shaped volume), filings such as
  promoter pledging. Feed the model *anonymized* facts in backtest so it can't
  recall outcomes.
- **Un-rewindable (forward-test only):** general news mood. No point-in-time
  archive, and the model knows the endings. Validated live by grading (B4), never
  by backtest.

The constraint *improves* the design — it pushes the veto toward concrete,
gradeable disqualifiers and away from news mush.

**Concepts:** tool-calling subgraphs · adversarial prompting vs confirmation
bias · evidence anonymization to defeat training-data lookahead · designing for
gradeability.

### B3 — Position review (thesis maintenance)

Daily, per open position, **resuming a checkpointed thread**: is the entry
thesis still intact? A rule sees days-held and P&L. An agent can see *"bought for
a 3× volume breakout; volume has decayed to 0.6× and it's chopped sideways below
the breakout level for eight sessions — the reason to own this is gone."*

*Targets Problem 3* — the 108 timeouts. Note a deterministic stale-exit rule
(e.g. day 9 / <+4%) captures some of this for free, so **the honest experiment is
LLM-review vs deterministic-stale-exit**, not vs doing nothing.

**Concepts:** checkpointers and `thread_id` · resuming vs re-invoking · what
belongs in graph state vs the DB (§5) · agents on a different cadence over the
same node logic.

### B4 — Reflection + grader (the learning loop)

On every close: realized return, alpha vs Midcap 150, reflection on
outcome-vs-thesis, and a **grade on whether the cited kill_case actually
materialized**. Lessons retrieved by situation similarity into future B2/B3
calls.

This closes the loop and is the only mechanism that validates the
un-backtestable half of B2. It's also the most defensible LLM use case in an
interview: pure text synthesis over structured records, graded against realized
outcomes.

**Concepts:** cyclic graphs and termination · memory/retrieval design · grading
predictions against outcomes rather than vibes.

### Deferred

- **Empirical reweighting** (logistic regression over dimensions → outcome,
  replacing hand-tuned `DIMENSION_SCORES`). That's sklearn, not an agent, and it
  needs ~100 graded trades that don't exist yet.
- **Earnings-calendar blocking.** Real risk, but the fix is a date lookup — ship
  it as a deterministic Phase C rule, don't dress it as an agent.
- **Not worth doing:** deep financial-statement analysis (horizon too short),
  macro regime classification (low signal for 1–4 week holds).

---

## Phase C — Strategy fixes

Independent of B; each validated on the Phase A harness.

- **C1 — Regime dial, not switch.** Replace the binary Nifty<SMA50 freeze with a
  graduated gate: strong → 5 slots full size, neutral → 3, weak → 2 at half
  size. Never a total freeze. Attacks the dead months and the 2025 drawdown —
  likely the single biggest return lever in the plan.
- **C2 — Risk-normalized sizing.** `quantity = risk_budget / (entry − stop)` at
  ~0.9% of equity. Equalizes risk across volatility regimes; targets Sharpe.
- **C3 — Compounding.** Size off current equity, not `starting_capital`
  (`engine.py:154` sizes off the constant).
- **C4 — Entry quality.** Earnings-date block; close-in-top-30%-of-range filter;
  replace the ATR term in ranking with 20-day relative strength vs the midcap
  index.

---

## Phase D — Ship it

- **D1 — Next.js dashboard.** Replaces the Jinja templates in `app/templates/`.
  Buildable in parallel with Phase B once A2 records exist. Publishing the
  ablation results publicly is the showcase.
- **D2 — Cloud daily runs.** Laptop cron isn't sustainable. Decide DB shape
  first — the 58MB `backtest_data.db` of OHLCV shouldn't necessarily move
  wherever the app DB goes.
- **D3 — Human-in-the-loop gate.** LangGraph `interrupt()` before any live
  order. Practically necessary and a genuine framework capability.
- **D4 — Alerts + forward-test collector.** Live trades vs actuals, benchmarked
  against **Midcap 150** (the honest benchmark, not Nifty 50).
- **D5 — The writeup.** *"Does the LLM actually add alpha? An ablation study"* —
  a byproduct of Phase A, and the strongest artifact here.

---

## Sequencing

```
Phase A  ──►  the measuring stick            (blocks everything)
Phase B  ──►  agents, each measured vs baseline  ─┐ largely
Phase C  ──►  strategy fixes, each validated     ─┘ independent
Phase D  ──►  ship + write up                (D1 can start after A2)
```

**The one hard rule:** nothing in B or C ships without passing the Phase A
harness. Otherwise this is back to fitting the backtest by iteration — the exact
bias §3 documents.

---

## Known limitations (stated honestly, kept visible)

1. **Survivorship bias.** Universe seeded from today's constituents. Returns are
   inflated until point-in-time membership lands.
2. **Adjustment restatement.** `auto_adjust=True` back-adjusts old bars for later
   splits — a mild lookahead.
3. **The news-reading half of the veto is not backtestable.** No point-in-time
   archive, and the model knows the outcomes. Forward-graded only (B4).
4. **Fundamentals are point-in-time-absent.** `yfinance .info` is a current
   snapshot — used live, skipped in backtest.
5. **Sector context absent in backtest**, so concentration limits bind live but
   not historically.
6. **Relative strength is a live-only signal — accepted knowingly.** `market_regime`
   scores from four warnings live but only three in backtest, because
   `engine.py` hardcodes `sector_day_pct = 0.0` and `divergence_note = ""`. So the
   weak-sector warning and the relative-strength cancellation that answers it
   both fire live and never in backtest. Kept on the reasoning that a stock
   rising while its sector falls shows stock-specific demand rather than beta —
   but it is unvalidated, and it is a live/backtest divergence of the same shape
   as the sentiment one removed in Phase A. Proper fix is point-in-time sector
   indices (see limitation 5); until then, treat any regime-driven result as
   measured on three-quarters of its live inputs.

---

## Appendix — The forensic veto, in plain words

**Today:** the decision LLM is asked "is this a good buy?" and answers by
re-checking RSI/MACD thresholds the computer already checked. Worse than
useless — it's a yes-man, because the screener handed it a stock *selected for
jumping*, and the jump itself generated the bullish news it will find.

**The flip:** ask *"what would kill this trade?"* That forces a hunt for the
landmine instead of a cheer. The screener already found the upside; the veto's
only job is to remove downside.

**The analogy:** the screener is a recruiter surfacing strong résumés. The rules
are the test score — objective, and gameable. The veto is the **skeptical hiring
manager doing the background check**, looking for the dealbreaker the résumé
can't show: *earnings in two days · the founder just sold · this is breaking into
a resistance wall · that volume spike was a single block deal.*

**Why it targets the biggest leak:** 72 of 232 trades stopped out. Many have a
factual tell that exists in text somewhere. The veto doesn't need to find
winners — killing even a third of the worst trades moves the whole P&L.

**How we'll know it worked:** every veto cites a specific, falsifiable reason.
B4 later checks: did that thing happen, and did the trade lose? After ~100
graded decisions that's a real measurement of whether the model's skepticism
predicts outcomes. Not vibes.

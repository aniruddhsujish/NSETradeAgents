# NSETradeAgents — Plan of Record

> The plan for turning a working swing-trade bot into (a) a defensible multi-agent
> system and (b) a strategy worth funding. Doubles as the syllabus: each phase
> names the orchestration concepts it teaches.
>
> **Scope:** describes branch `veto-agent`, cut from `main`. The older
> `redesign-decicision-agent` branch is **abandoned** — do not plan against it.
> Stale `.pyc` files under `app/engine/` and `app/data/` are debris from it.

---

## 1. Goals

1. **Learn multi-agent orchestration.** This project is the vehicle; concepts get
   built by hand.
2. **A resume piece that survives scrutiny** — a multi-agent system that uses
   LangGraph and can *justify* the framework (§5).
3. **Eventually, a real edge worth real capital.**

---

## 2. Where things stand

### Current pipeline — fully deterministic, zero LLM calls

```
START → fetch_data → fundamental ─[blocked]→ blocked → END
                                 └[ok]→ ┌ market_context ┐
                                        └ technical      ┴→ fetch_price → risk
risk ─[blocked]→ blocked
     └[ok]→ rules_gate ─[score < 65]→ blocked
                       └[score ≥ 65]→ execute → END
```

`langchain-anthropic` is no longer imported anywhere in `app/`. This is deliberate:
it is the honest "before" that every LLM addition gets measured against.

### Baseline (2022–2025, ₹2L, threshold 65)

| Metric | Value |
|---|---|
| Total return | +82.6% |
| CAGR | +16.3% |
| Sharpe | 1.38 |
| Max drawdown | 12.9% |
| Trades / win rate | 235 / 49.8% |
| Profit factor | 1.51 |

Exits: **stop 80 · target 17 · timeout 110 · trail 28**

### Scoring — four banded dimensions, exactly 100 points

`entry_timing` 30/18/0 · `momentum_quality` 25/15/0 · `risk_reward_view` 20/12/0 ·
`market_regime` 25/15/0. Nothing subtractive; no clamp needed.
`compute_rules_confidence` returns the score **and the bands**, so callers can
record *why* a candidate scored what it did.

---

## 3. What we learned that changed the plan

**The score barely predicts outcomes.** Buckets are non-monotonic — the 80–100
bucket had the *worst* average P&L (−0.18%). A threshold sweep gave
32→+71%, 50→+49%, 60→+61%, 65→+83%, 70→+88%: a wobble, not a trend, with ~25
trades separating the extremes.

Interpretation: **the screener does the real selection work.** A rubric that
re-reads the same indicators adds little. This is the argument for the veto
bringing *different* information — and the argument against adding more
arithmetic over the same inputs.

**LLM alpha cannot be backtested here.** Two independent reasons: no
point-in-time news archive, and the model was trained on the outcome window. So
LLM contribution is validated **forward, by grading**, not by backtest. That is
accepted, not worked around.

**Chart-structure detection is not an LLM job.** Resistance walls, gaps, and
block-deal volume are all computable in ~20 lines. Handing an LLM 300 numbers to
find them is the calculator-in-a-costume error in new clothes. If built, they are
deterministic features — and their alpha case is unproven, so they are deferred.

**The backtest is still valuable — for the deterministic track.** Its job changed:
not validating agents, but validating strategy fixes. That is where the evidence
actually points (110 timeout exits, no compounding, a binary regime gate).

### The exit distribution diagnoses the strategy

**stop 80 · target 17 · timeout 110 · trail 28.** Only ~19% of trades (target +
trail) win meaningfully; profit factor 1.51 says the entire edge lives in those.

The cause is that **stop and target are mis-scaled to volatility.** The stop is
`2.5 × ATR%` (floor 5%, cap 10%); the target is a flat **18%**. For a typical
2.5%-ATR candidate:

- stop sits ≈ **2.5 daily ranges** below entry
- target sits ≈ **7 daily ranges** above entry
- 21 days of random walk covers ≈ √21 ≈ **4.6 daily ranges**

So noise alone reaches the stop comfortably and rarely reaches the target. The
paper R:R of 2.9:1 is illusory: **the stop is inside the noise band and the
target is outside the plausible range.** 80 stops against 17 targets is exactly
that signature, and the 110 timeouts are trades drifting toward a target that was
never reachable.

**Second diagnosis — entries buy the top of the pop.** The signal fires on a
close with `day_change > 0.5%` and `volume ≥ 2×`, and the order goes in at the
*next open* — frequently the local high, often a gap up. That is what feeds the
stop count.

**Third — absolute momentum is the wrong screen for a downtape.** `momentum_5d ≥
2.0` is measured against zero, so in a falling market it either finds nothing
(the dead months) or finds the few things pumping, which in a downtape skew
toward junk and reversals. 2025's 36.8% win rate is that failure.

The two levers that follow: **kill the dead 47% faster** and **make the winning
19% bigger.** The trailing stop already does the second; most of Phase B is the
first.

---

## 4. Principles

1. **Backtest == live.** One source of truth per rule. Duplication drifts — it
   already did once, via sentiment.
2. **LLM only where it reads text or exercises judgment** — never where a
   function can compute the answer.
3. **Deterministic core, gradeable LLM edges.**
4. **Records before agents.** A decision you did not capture is one you can never
   grade, and grading is now the only validation path.
5. **Measure what can be measured; forward-test the rest, and say which is which.**
6. **LangGraph must earn its place** (§5).
7. **The user writes the code.** Guidance and review, not delivery.

---

## 5. The LangGraph justification

Stated plainly: **the current graph does not justify LangGraph.** It is a linear
pipeline with one fan-out of two independent nodes — ~30 lines of plain Python.
Adding a veto node does not fix that; it is one more box in the same line.

Four things genuinely require the framework, and the plan builds all four:

| Capability | Lands in |
|---|---|
| **Checkpointed durable threads** — each open position is a thread resumed daily with its own accumulated history | C2 |
| **Cycles** — reflection → lesson → retrieved into future decisions is a loop, not a DAG | C3 |
| **Tool-calling subgraphs** — the veto gathers evidence in its own inner loop | C1 |
| **Human-in-the-loop `interrupt()`** — approval gate before live orders | D3 |

**State-split decision (locked):** the authoritative trade ledger — entry price,
shares, stops, realized P&L — stays in SQLAlchemy. The *agent's* memory for a
position — entry thesis, prior reviews, evidence already seen — lives in the
LangGraph checkpointer keyed by position ID. **LangGraph persists reasoning; the
DB persists the books.**

---

## Phase A — Unify and record

### A1 — Backtester calls the same functions as live
`app/backtest/engine.py` currently re-implements the eight screener filters
(`engine.py:290-311` duplicating `filters.py:76-121`), the exit ladder, market
context, and the regime gate. Extract each as a **pure function over data**
(indicators dict / DataFrame in, verdict out) and have both paths call it. The
split that makes this work: *fetching* data differs between live and backtest;
*deciding* on it must not.

### A2 — Decision records
One row per candidate evaluated — bought **and** blocked — with the dimension
bands, indicators, and (later) the veto verdict as **columns**, not JSON. This is
simultaneously the eval dataset, the grader's corpus, and the dashboard's
backing table.

### A3 — Costs, slippage, train/holdout
STT, brokerage, impact. Tune on 2022–24; touch 2025 once.
*Debt already incurred: threshold 65 was picked from a sweep on the full period,
so the holdout has been seen once. Recorded rather than hidden.*

**Concepts:** pure functions as the seam between environments · why per-candidate
records give ~2× the eval data of per-trade · data snooping and how versioning
makes it visible.

---

## Phase B — Deterministic strategy fixes

Backtestable, and where the measurable alpha probably is. Each validated on A,
each shipped **alone** so the harness can attribute the change.

Ordered by expected value ÷ cost:

### B1 — ATR-scaled target *(one line)*
Replace the flat 18% with `target = entry × (1 + 4 × ATR%)`. A 2.5%-ATR stock
targets 10%; a 4.5%-ATR stock targets 18%. Puts the target *inside* the
distribution of achievable 21-day moves. **Directly attacks the 110 timeouts and
the 17-target problem** — the highest-value single change identified.

### B2 — Relative momentum instead of absolute *(needs index data in the store)*
Rank and filter on performance **versus the Midcap 150**, not versus zero. In a
−5% tape a stock at −1% is genuinely strong; in a +5% tape a stock at +2% is a
laggard the current screen buys happily. Self-adjusts across regimes rather than
needing a regime switch bolted on, and cross-sectional momentum is the version
with actual empirical support. **The real fix for bad regimes.**

### B3 — Close-in-top-of-range filter *(one line)*
Require `(close − low) / (high − low) > 0.6`. A 3× volume day closing in the
bottom third of its range is distribution, not accumulation — someone is selling
into the buying. Removes the worst entries for free.

### B4 — Stale exit *(small)*
Exit at ~day 9 if under ~+4%. Note it does **not** improve win rate; it improves
**capital velocity**. With 5 slots, freeing a dead position 12 days early is
roughly an extra trade per slot per quarter.

### B5 — Compounding *(one line)*
`engine.py:154` sizes off `starting_capital`, not current equity, so the system
never compounds. Nearly free.

### B6 — Not-extended filter *(one line)*
Reject entries where `(price − sma20) / sma20` exceeds ~8%. A stock stretched far
above its short MA mean-reverts, and that reversion is what hits the stops.

### B7 — Breadth-based regime dial *(moderate)*
Replace the binary `Nifty < SMA50` freeze with **% of universe above its own
SMA50** — continuous and *leading* (breadth deteriorates before the index does).
Feeds a dial: strong → 5 slots full size, neutral → 3, weak → 2 at half size.
Never a total freeze. Attacks the dead months.

### B8 — Risk-normalized sizing *(moderate)*
`quantity = risk_budget / (entry − stop)` at ~0.9% of equity. Equalizes risk
across volatility regimes; targets Sharpe.

### B9 — Pullback limit entry *(changes the fill model)*
Instead of a market order at the next open, rest a limit near the prior close.
Misses the runaway gappers but gains several percent of cushion above the stop on
everything that fills. Fill rate is measurable directly from stored bars — check
how often the next day's low reaches the prior close before building it.

### B10 — Scale out in two pieces *(simulator work)*
Sell half at +1.5×ATR, trail the remainder. Converts part of the 110 timeouts
into small wins while keeping the tail. Needs partial-fill bookkeeping in the
simulator.

*Deferred, unproven:* chart-structure detectors (resistance, gaps, volume
concentration). A crude version already exists in `_rules_entry_timing`'s
round-number check and has not demonstrated value.

> B1, B3, B5 and B6 are all one-liners that can be A/B'd on the harness the day
> A1 lands — which is the practical argument for finishing the unification before
> touching strategy.

---

## Phase C — The LLM agents

The showcase, and the learning. Validated forward by grading, never by backtest.

### C1 — Forensic veto
Ask **"what specifically kills this trade?"** not "is this a good buy?" — the
screener already picked it for jumping, so a "good buy?" prompt gets a yes-man.
Output is kill/pass **with a cited specific**, never a vibe.

**Ships in shadow mode:** runs on every candidate, records its verdict, routes
nothing. Zero risk to the portfolio, and every trade becomes a labelled data
point — including the ones it wanted to kill, whose outcomes you would otherwise
never observe. Flip to acting via config once the data justifies it.

*v1 scope:* one call, Tavily search, structured output, fail-open on error.
*Not v1:* earnings calendar, filings parsing, multi-step evidence gathering.

### C2 — Position review (thesis maintenance)
Daily, per open position, **resuming a checkpointed thread**: is the entry thesis
still intact? Targets the same 110 timeouts as B1 — which makes the honest
experiment **LLM review vs the B1 deterministic rule on identical bars**, not LLM
vs nothing. Expect the rule to be hard to beat; run it anyway, because the result
is a real finding either way and the architecture is the point.

### C3 — Reflection and grading
On every close: realized return, alpha vs Midcap 150, and a **grade on whether
the cited kill_case actually materialized**. Lessons retrieved by situation
similarity into future C1/C2 calls.

Two independent questions, and they fail independently:
**is the cited evidence true?** and **did acting on it help?** Accurate evidence
with bad P&L means the veto is right about things that do not matter.

### Not scheduled
Empirical reweighting (that is sklearn, not an agent, and needs ~100 graded
trades). Allocator/ranking — ranking numeric candidates gives an LLM no
information the formula lacks; the earlier case for it was overstated.

---

## Phase D — Ship

- **D1 — Deploy the deterministic system now.** It works and it is validated.
  Every week it sits on a laptop is a week of forward control data that cannot be
  recovered. This is the control group for every LLM experiment that follows.
- **D2 — Next.js dashboard**, replacing `app/templates/`. Buildable in parallel
  once A2 records exist.
- **D3 — Human-in-the-loop gate** — LangGraph `interrupt()` before any live order.
- **D4 — Forward-test collector** — live trades vs actuals, benchmarked against
  **Midcap 150**, not Nifty 50.
- **D5 — The writeup** — what the ablations showed, honestly.

---

## Sequencing

```
A  ── unify + record          (blocks C: records before agents)
D1 ── deploy deterministic    (parallel with A; starts the forward clock)
B  ── deterministic fixes     ← measurable alpha
C  ── LLM agents              ← showcase + learning
D  ── dashboard, HITL, writeup
```

B and C interleave freely. The one hard rule: **A2 lands before C1**, because a
shadow deployment that does not record teaches nothing.

---

## Expectations, honestly

At ~59 trades/year, three months of forward data is ~15 trades — not enough to
conclude anything. Six to twelve months before grading says much.

**So the resume value must not depend on proving alpha.** The defensible story is
the apparatus: a multi-agent system where every decision is recorded and graded
against outcomes, an honest account of what the data does and does not show, and
three LLMs removed because they were not earning their place. That is true today
and stronger than any backtest number.

---

## Known limitations

1. **Survivorship bias.** Universe seeded from today's constituents; delisted
   losers absent. Returns inflated until point-in-time membership lands.
2. **Adjustment restatement.** `auto_adjust=True` back-adjusts old bars for later
   splits — a mild lookahead.
3. **LLM alpha is not backtestable.** No point-in-time archive; the model knows
   the endings. Forward-graded only.
4. **Fundamentals are point-in-time absent.** `yfinance .info` is a current
   snapshot — used live, skipped in backtest.
5. **Sector data absent in backtest.** `sector_day_pct` hardcoded `0.0`.
6. **Relative strength is live-only — accepted knowingly.** `market_regime` scores
   from four warnings live, three in backtest, because of (5). Kept on the
   reasoning that a stock rising while its sector falls shows stock-specific
   demand rather than beta. Unvalidated. Proper fix is point-in-time sector
   indices.
7. **Threshold 65 saw the holdout once** (§A3).

---

## Appendix — The forensic veto, in plain words

**Today's failure mode:** ask an LLM "is this a good buy?" about a stock the
screener selected *for jumping*, and the jump itself generated the bullish news
it will find. It becomes a yes-man with a search tool.

**The flip:** ask *"what would kill this trade?"* That forces a hunt for the
landmine instead of a cheer. The screener already found the upside; the veto's
only job is to remove downside.

**The analogy:** the screener is a recruiter surfacing strong résumés. The rules
are the test score — objective and gameable. The veto is the **skeptical hiring
manager doing the background check**, looking for the dealbreaker the résumé
cannot show: *earnings in two days · the founder just sold · a regulatory notice
last week.*

**Why it targets the biggest leak:** 80 of 235 trades stopped out. Many have a
factual tell that exists in text somewhere. The veto does not need to find
winners — killing a third of the worst trades moves the whole P&L.

**How we will know:** every veto cites a specific, falsifiable reason. C3 checks
whether that thing happened and whether the trade lost. After ~100 graded
decisions that is a real measurement of whether the model's skepticism predicts
outcomes.

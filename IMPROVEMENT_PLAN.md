# NSETradeAgents — Re-Engineering Plan

> Full plan of record for the swing-bot overhaul: motivation, principles, every
> phase (done and planned), design rationale, and honest limitations.
>
> **Branch note:** Phases 0–1 are **implemented on a separate feature branch**
> (the unified engine). This branch is the original pre-engine codebase. Status
> tags below reflect what is built, not what is present on the current branch.

---

## 1. Why this exists (the problem)

Baseline backtest (Jan 2023 – Dec 2025, ₹2,00,000, claude-sonnet-4-6, sentiment neutral):

- **+36.81% total / 11.04% CAGR**, Sharpe **0.455**, max DD **-10.46%** (231-day duration).
- **Underperformed** Nifty 50 (+42.5%) and badly trailed Midcap 150 (+84.3%).
- Trade mix: **39% hit stop-loss** (avg −5.5%), **40% timed out** at 21 days for ~+1–2%, profit factor 1.88 driven by a handful of trail exits.
- Long stretches **fully in cash** (Oct–Nov 2024, Jan–Feb 2025) — the binary regime filter.

Three root causes:

1. **Backtest ≠ live.** The backtest was a throwaway script; the live bot is different code. So the backtest never predicted live behaviour (e.g. it ran sentiment-neutral; live runs Tavily sentiment).
2. **The LLM does arithmetic, not judgment.** 4 of the decision agent's 5 dimensions are deterministic math the LLM merely re-derives; signal-alignment was constant (neutral sentiment) so contributed nothing.
3. **Capital-efficiency leaks.** No compounding (sized off starting capital), dead-money timeouts, binary regime freezes, fixed-fraction sizing ignoring volatility.

---

## 2. Guiding principles

1. **Backtest == live.** One engine, one code path; only the inputs differ (historical date vs today, rules vs LLM). This is the spine.
2. **LLM only where it reads text or makes judgment** — never where a function can compute the answer. (Technical analysis → deterministic. Veto/news → LLM.)
3. **Deterministic core, gradeable LLM edges.** Signals, sizing, exits, scoring are pure Python and testable; the LLM's contribution is isolated and measured.
4. **Measure before believing.** Every LLM change must beat a rules-only baseline on the backtest harness; record every decision so claims are checkable.
5. **LangGraph stays the orchestration core.** `run_cycle` *drives* the graph per candidate; it does not replace it. (Resume + architecture requirement.)
6. **Strangler / branch migration.** Build the new engine alongside the old path; cut over only when validated.

**Status legend:** ✅ Implemented · ◻ Planned · ⏸ Deferred

---

## Phase 0 — Immediate fixes ✅

Bug-level fixes that improve the bot regardless of the larger rebuild.

| # | Change | Where |
|---|---|---|
| 0.1 | **Compound position sizing** — size off current equity (cash + invested), not `starting_capital`. | `risk.py`, threaded via graph state |
| 0.2 | **Fix the hardcoded slot gate** — `open_positions >= settings.max_positions - 1`, not a literal `>= 4`. | `graph.py` `route_after_decision` |
| 0.3 | **De-duplicate market-wide penalties** — VIX/Nifty penalised once (in `compute_confidence`), not also by the decision LLM. | `scoring.py` / `decision.py` prompt |
| 0.4 | **Feed the decision agent real data** — raw indicators dict + compact 60-day OHLCV table, not just Haiku's paraphrase. | `decision.py`, `prompt_helpers.py` |

---

## Phase 1 — The spine (unified engine) ✅

One engine both live and backtest call. The hard part of the whole project.

### 1.2 — Point-in-time data layer ✅ — `app/data/store.py`
- Local SQLite cache of OHLCV + index/VIX bars; **every read takes `as_of`** and never returns a bar past it (no lookahead, by construction).
- Why a cache (not live `yf.download(end=as_of)` per step): a backtest is ~700 days × hundreds of tickers — per-step calls get throttled, are slow, and drift between runs. Ingest once, slice in memory → fast + reproducible.
- Dated `constituents` table (point-in-time membership ready); a `get_bars` shape that drops straight into the existing `compute_indicators`.
- **Known v1 limitations (documented in the module):** survivorship bias (seed-from-today universe — dead/delisted tickers absent) and adjustment restatement (`auto_adjust=True` back-adjusts old bars for later splits).

### 1.4 — Unified exit policy ✅ — `app/engine/exits.py`
- One pure function `evaluate_exit(position, bar, as_of)` replacing logic scattered across two scheduler functions; the hybrid/non-hybrid split is **deleted**.
- The ladder, evaluated in order: **ATR stop → breakeven ratchet (+5.5%) → ATR-width trailing stop (+8%) → stale exit (day 9 / <+4%) → hard timeout (21d)**.
- No-lookahead: stop floors checked against the day's *low* using prior-close state; trailing state advances on the day's high/close (known at the bell). Gap-downs fill at the open (realistic).
- Thresholds in `ExitPolicyParams` (not global settings).

### 1.1 — The engine
- **1.1a — Point-in-time screener** ✅ `app/engine/screener.py`: `screen_asof(store, universe, as_of, config)` + `regime_blocked(...)`; reuses the shared `evaluate_candidate` (single source of truth for the 8 filters + ranking) so live and backtest screen identically.
- **1.1b — Rules-only decision** ✅ `app/engine/decision_rules.py`: `decide_rules(...)` — the rubric ported to ~deterministic Python (the Phase 2.2 baseline). Produces the 5 dimension labels; reuses the existing `compute_confidence` scorer. Mirrors `run_decision`'s signature so the two are interchangeable.
- **1.1c-i — Deterministic technical** ✅ `app/agents/technical.py`: LLM removed (this is Phase 4.1 pulled forward). Trend gate → BUY/HOLD; weighted 0–100 strength (RSI position 30% / MACD 25% / volume 25% / momentum 20%).
- **1.1c-ii — Graph wiring** ✅ `app/graph/graph.py` + `state.py`: LangGraph topology unchanged; node internals made point-in-time and mode-aware. Added `as_of`, `mode`, `use_llm_decision` to `TradingState`. `fetch_data` reads the store; `sentiment` and `decision` switch LLM↔deterministic; `technical` always deterministic.
- **1.1c-iii — `run_cycle`** ✅ `app/engine/cycle.py`: the single entry point both live and backtest call. Exits-first → regime gate → screen → drive the graph per candidate within limits → returns decisions (no DB writes; caller applies). Local-state threading keeps sequential decisions correct within a cycle.
- **1.1c-iv — Dead-code sweep + live driver** ✅: deleted the old `filters.screen()` live path, the scheduler's `review_positions`/`review_trail_eod`, the entire hybrid concept (`hybrid_active` → `breakeven_armed`), and dead trail/hybrid config. `main.py` rewritten as the live driver (ingest → `run_cycle(mode="live")` → apply to simulator → snapshot). Scheduler reduced to one post-close daily job.

### 1.3 — Decision records ✅ — `app/engine/records.py`
- `RecordStore.decision_records`: **one row per candidate the engine evaluates each cycle** (not just executed trades) — bought *and* blocked.
- Decision dimensions + key indicators stored as **columns** (not JSON) so calibration queries are trivial. This is the apparatus for shadow portfolios ("did rank-5 beat rank-1?", "did vetoed trades lose?") and ~10× the eval data.

### 1.5 — Experiment versioning ✅ — `app/engine/records.py`
- `RecordStore.runs`: every backtest/live session stamped with **git SHA + config hash + params**. Makes "we tried N variants" a queryable fact instead of invisible data-snooping; every result traces to exact code + config.

### Live operating model (design, partially ⏸)
- **Decide on completed bars, act at next open.** The engine reads the last *completed* daily bar (`as_of` = yesterday's close), buys at today's open. This is the only honest, backtest-reproducible timing — and it fixes a real bug where the old live screener peeked at the half-formed intraday bar.
- **Two cadences, one rulebook:** a once-daily decision pass (`run_cycle`) sets each position's safety lines; a thin **15-min intraday stop watcher** (⏸ deferred) enforces those lines with live prices via the same `evaluate_exit` (`Bar.flat(price)` hook already exists). The watcher is a live-ops follow-up before going live.

---

## Phase 2 — Trustworthy measurement ◻

Build the measuring stick. **Nothing in Phases 3–4 ships without passing this harness.**

- **2.1 — Backtester on the engine.** A loop: `for day in history: apply(run_cycle(...), portfolio)`; point-in-time universe, realistic 9:30/next-open fills, slippage + STT + brokerage. Establish a **train/holdout split** (tune 2023–24, hold out 2025+) and log every peek at the holdout.
- **2.2 — Rules-only ablation baseline.** Backtest rules-only (`decide_rules`) vs LLM (`run_decision`), same everything else. **The delta is the LLM's actual alpha** — the bar every Phase 4 change must clear.
- **2.3 — Contamination test.** Re-run with **anonymized tickers + relative dates**; the gap vs the named run quantifies training-data lookahead (the LLM "remembering" 2023–25 outcomes).
- **2.4 — Calibration check.** On the decision records: do STRONG-momentum setups actually out-return MODERATE? Does SETUP_CONCERN rank-order outcomes? Decides which dimensions deserve weight (and refutes the ones that don't).

> Expect the historical +36.8% to **shrink** here (survivorship + honest fills). That's the system getting honest, not worse.

---

## Phase 3 — Strategy fixes ◻

Each change validated on the Phase 2 harness.

- **3.1 — Regime dial, not switch.** Replace the binary Nifty-50 freeze with a graduated gate on **Midcap-150 / universe breadth**: strong → 5 slots full size, neutral → 3, weak → 2 at half size; never a total freeze. Attacks the dead months, the 231-day drawdown, and the Midcap-150 gap — the single biggest return lever.
- **3.2 — Risk-normalized sizing.** `quantity = risk_budget / (entry − stop)` at ~0.9% of equity per trade (optionally scaled by confidence). Equalizes risk across volatility regimes; directly targets the 0.455 Sharpe.
- **3.3 — Entry quality.** Earnings-calendar block (no entries within 2 days of results); close-in-top-30%-of-range filter (buy days buyers finished in control, not faded spikes); replace the ATR term in screener ranking with **20-day relative strength vs the midcap index**.

---

## Phase 4 — The LLM redesign ◻

The decision-agent rebuild. **Comes after Phase 2** because its entire justification is "adds alpha over the rules baseline" — unmeasurable without the baseline + records.

- **4.1 — Demote the technical agent** ✅ (already done in Phase 1.1c-i).
- **4.2 — Forensic veto agent** ← the decision LLM redesign. See the appendix for the full explanation. In short: stop asking the LLM "is this a good buy?" (which makes it a yes-man confirming a pre-selected bullish setup) and ask **"what specifically kills this trade?"** — fed evidence rules can't read. Output is **kill / pass with a *cited specific*** (a date, a level, a filing), not a vibe.
  - **It subsumes the sentiment agent** rather than running alongside it. Don't run two news-reading LLMs. One text agent, two outputs: any **disqualifier** (the veto) and any genuine **catalyst** (the positive case sentiment was meant to provide). The old mood-score sentiment was confirmation-prone and neutral-in-backtest (useless) — it retires into the veto.
  - **Backtestability split (critical):** the veto's evidence divides into *rewindable facts* and *un-rewindable news*:
    - **Rewindable (backtestable):** earnings dates (NSE history), chart structure (from stored bars — resistance walls, block-deal-shaped volume), filings (promoter pledging, shareholding). Much of this can be **deterministic rules** — fully backtestable, free, no cheating. For an LLM in backtest, feed *only* anonymized facts so it can't recall outcomes.
    - **Un-rewindable (forward-test only):** general news mood. No clean point-in-time archive, and the model knows the endings. **Validate this part live by grading**, never by backtest — true of any news-driven strategy.
  - The constraint *improves* the design: it pushes the veto toward concrete, gradeable disqualifiers (where the real edge is) and away from news mush.
- **4.3 — Portfolio allocation / ranking call.** One LLM call sees all surviving candidates + current holdings and ranks for open slots — **comparative** judgment (LLMs are good at it) replacing absolute scoring (they're not), and portfolio-level thinking replacing first-come slot-filling. Delete the per-call distribution quota (it can't work across independent calls).
- **4.4 — Reflection memory with grading.** On every close: realized return + alpha vs Midcap 150, a reflection on outcome-vs-thesis, and a **grade on whether the stated kill_case materialized**. Retrieve past lessons by situation similarity into future veto/ranking calls. The decision records (1.3) are the dataset; this is how the news-reading veto gets validated forward.
- **4.5 — Empirical reweighting.** After ~100 graded trades, fit a simple logistic regression (dimensions + veto + rank → outcome) and replace the hand-tuned `DIMENSION_SCORES`. The system learns its own weights from evidence.

### Future LLM surface areas (evaluated, not yet scheduled)

These are additional places an LLM adds genuine value over deterministic rules — i.e., reading unstructured text or reasoning about things that are hard to encode. Ordered by expected ROI:

- **Earnings / events calendar.** The pipeline currently has zero awareness of upcoming binary events — earnings in 3 days, RBI policy, budget session. A blocking rule using NSE's announcements API is the deterministic fix (Phase 3.3); an LLM layer on top could read the announcement *context* ("beat consensus by 12%, guidance raised") for the veto. Either way, this is the biggest uncovered risk — a swing trade entered 2 days before results is a different trade.
- **Promoter / bulk-deal activity.** BSE bulk-deal filings are public but unstructured. Large promoter selling while technicals look bullish is a classic trap. Already partially captured in Phase 4.2's "filings (promoter pledging)" bullet; the LLM reads recent bulk-deal disclosures and flags it as a veto kill-case. This is rewindable (filings are dated) so it backtests cleanly.
- **Post-mortem calibration.** Already Phase 4.4. Calling it out here because it's the most defensible LLM use case in interviews: pure text synthesis from structured records, no market data required, graded by realized outcomes. After ~50 closed trades the decision records contain a dataset no deterministic function can summarise.
- **Not prioritised:** deep financial statement analysis (too slow, swing-trade horizon doesn't need it), macro regime classification (high complexity, low signal for 1–4 week holds), generic sector news summary (covered by the veto).

---

## Phase 5 — Operations & resume layer ◻

- **Forward-test collector** — live trades vs actuals; alpha vs **Midcap 150** (the honest benchmark), win rate, Sharpe.
- **Alerts** — Telegram/email on open/close/veto.
- **CI** — run the test suite on every push.
- **README** — architecture diagram + an honest "known limitations" section.
- **Writeup** — "Does the LLM actually add alpha? An ablation study" — generated as a byproduct of Phase 2; the strongest interview artifact.

---

## Sequencing & dependency rules

```
Phase 0 ──► live bot improved immediately
Phase 1 ──► spine (engine, data, exits, records)   ─┐
Phase 2 ──► honest measurement (the measuring stick) ├─ branch-based; old path
Phase 3 ──► strategy fixes, each validated           │  remains until cut over
Phase 4 ──► LLM redesign, each measured vs baseline  ─┘
Phase 5 ──► ops + writeup, continuous
```

- The one strict rule: **nothing in Phases 3–4 ships without passing the Phase 2 harness** — otherwise we're back to fitting the backtest by iteration (the bias the git history already shows).
- Phases 3 and 4 are largely independent; 2 → 4 → 3 is acceptable, but **Phase 2 is always first**.

---

## Known limitations (honest caveats)

1. **Survivorship bias (v1).** Universe is seeded from *today's* constituents; delisted/dropped (mostly losing) names are absent. Backtest returns are inflated until point-in-time membership lands. Documented loudly in `store.py`.
2. **Adjustment restatement.** Prices use `auto_adjust=True`, so old bars are back-adjusted for later splits/dividends — a mild lookahead. Match-live for now; raw-OHLC + point-in-time adjustment is the eventual fix.
3. **News-reading LLM is not backtestable.** No point-in-time news archive, and the model knows the outcomes. The factual/deterministic half of the veto backtests; the news half is forward-tested by grading only.
4. **Fundamentals are a point-in-time gap.** `yfinance .info` is a current snapshot — used live, skipped in backtest.
5. **Sector context absent in backtest.** No point-in-time sector indices yet → sector-concentration limits don't bind in backtest (they do live).

---

## Appendix — The forensic veto model, in plain words

**Today:** the decision LLM is asked "is this a good buy?" and answers by re-checking RSI/MACD thresholds — math the computer already did. It's a calculator in a costume, and worse, a yes-man: asked about a stock the screener already picked for jumping, it finds bullish reasons (the jump *caused* the news).

**The flip:** ask **"what would kill this trade?"** That forces the LLM to hunt for the landmine instead of cheering. The screener already found the upside; the veto's job is to remove the downside.

**Analogy:** the screener is the recruiter (great résumés), the rules are the test score (objective, gamed), the veto is the **skeptical hiring manager doing the background check** — looking for the dealbreaker the résumé can't show ("earnings in 2 days," "founder just sold shares," "breaking into a resistance wall," "that volume spike was one block deal").

**What it adds over the old sentiment agent:** (1) adversarial framing (sentiment confirms; veto attacks), (2) evidence beyond news mood (earnings dates, filings, chart structure), (3) a hard gate vs a soft blended score, (4) gradeability (cited specifics can be checked against outcomes). It **replaces** sentiment, not duplicates it.

**Why it targets the biggest leak:** ~39% of trades stopped out; many have a textual/factual tell. The veto doesn't need to find winners — cutting even a third of the worst trades shifts the whole P&L.

**How we'll know it works:** every veto cites a specific reason; later we check "did that happen, did it lose?" After ~100 graded trades, that's a real measurement of whether the LLM's skepticism predicts outcomes — not vibes.

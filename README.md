# NSETradeAgents

An automated swing-trading system for NSE smallcap and midcap stocks. It scans
about 400 stocks every morning, picks the best setups, sizes positions, and
manages exits — holding for one to four weeks.

It runs in simulation mode against real market data. No real money yet.

**The system is currently fully deterministic — there are no LLM calls in it.**
That is deliberate, and the reason is the most interesting thing about the
project. See [Why there is no AI in it right now](#why-there-is-no-ai-in-it-right-now).

---

## How it works

```
400 NSE stocks (Smallcap 250 + Midcap 150)
        ↓
Regime gate ────────────► skip the day entirely if Nifty 50 is below its 50-day average
        ↓
Screener (10 filters) ──► rank what survives by volume, momentum, and volatility
        ↓
For each candidate, run the LangGraph pipeline:

     fetch_data ──► fundamental ──┬──► market_context ──┐
                                  └──► technical ───────┴──► risk ──► score
        ↓
Score 0-100. Buy if ≥ 65.
        ↓
Portfolio simulator (SQLite) — cash, positions, stops, P&L
```

Every stage can reject a candidate. Most do.

### The daily rhythm

| When | What happens |
|---|---|
| 09:30 IST | Morning scan — find and buy new positions |
| Every 15 min | Check open positions against their stop and target |
| 15:35 IST | Update trailing stops using the day's closing price |

---

## Why there is no AI in it right now

The system used to have three Claude agents: one reading technical indicators,
one searching news for sentiment, and one making the final buy decision.

All three were removed. Here is why.

**The decision agent was doing arithmetic, not judgement.** It was asked to score
a setup across five dimensions — but four of those dimensions were things a
Python function had already calculated. The model was re-deriving RSI and MACD
thresholds the computer knew exactly. A calculator in a costume.

**The measurements did not support keeping it.** The backtest that produced the
headline numbers below never called an LLM at all. So the entire AI layer sat on
top of a validated deterministic strategy, costing money and time, with no
measured contribution.

**The sentiment agent made the backtest lie.** It fed the scoring system live,
but the backtest replaced it with a fixed neutral value. The same stock could
score 30 points differently depending on which code path you were in — so the
backtest was not testing the system that actually ran.

Removing all three changed the backtest result by less than one percent.

**What comes next** is a *forensic veto agent*: instead of asking a model "is
this a good buy?" (which produces a yes-man, since the screener already picked
the stock for jumping), it asks **"what specifically kills this trade?"** — and
must cite a real, checkable reason. It only removes trades, never adds them, so
its value can be measured as a clear before-and-after.

It will ship in shadow mode first: running on every candidate and recording its
verdict, but not acting on it. That way every trade becomes a labelled data
point, including the ones the model wanted to block.

---

## Backtest results

Four years of real NSE daily data, ₹2,00,000 starting capital, entry threshold 65.

| Metric | Value |
|---|---|
| Total return | +82.6% |
| CAGR | +16.3% |
| Sharpe ratio | 1.38 |
| Max drawdown | 12.9% |
| Total trades | 235 |
| Win rate | 49.8% |
| Profit factor | 1.51 |
| Average hold | 18.1 days |

**How trades ended:** 80 stopped out · 110 timed out · 28 trailing stop · 17 hit target

| Year | Return | Trades | Win% | Max drawdown |
|---|---|---|---|---|
| 2022 | +19.9% | 49 | 51.0% | 8.1% |
| 2023 | +47.6% | 50 | 62.0% | 3.5% |
| 2024 | +6.1% | 78 | 51.3% | 9.4% |
| 2025 | −4.9% | 58 | 36.2% | 7.5% |

2025 is the weak spot. The regime gate stops new entries in a downtrend but
cannot help positions already open, and the screener looks for *absolute*
momentum — in a falling market that finds either nothing or the few things
still spiking, which are often the wrong things.

### Read these numbers carefully

They are better than the system would have done in reality, for three reasons:

1. **No trading costs.** Brokerage, STT, and slippage are not modelled. Across
   235 round trips on smallcaps, that is not a rounding error.
2. **Survivorship bias.** The stock universe comes from *today's* index
   membership, so companies that were delisted — mostly losers — are missing.
3. **Tuned on the same data it is measured on.** Thresholds were adjusted while
   looking at these results. There is no untouched holdout period yet.

Fixing all three is planned work, and the honest number will be lower.

### What the numbers say about the strategy

**110 of 235 trades simply timed out** — held three weeks, closed for roughly
nothing. That is the biggest leak.

The cause is that the stop and the target are scaled differently. For a typical
stock, the stop sits about 2.5 daily price ranges below entry while the target
sits about 7 above — and three weeks of normal movement covers about 4.6. So
random noise reaches the stop easily and rarely reaches the target. The fix is
to scale the target to each stock's volatility instead of using a flat 18%.

---

## Trading strategy

### Universe
Nifty Smallcap 250 + Midcap 150. These move more than large caps, which is what
a one-to-four-week trade needs.

### Regime gate
If Nifty 50 closes below its 50-day average, no new positions that day. Existing
positions carry on as normal. It fails open — missing or broken data never stops
trading, because a silent halt is the worst failure this system can have.

### Screener — 10 filters, all must pass

| Filter | Threshold | Why |
|---|---|---|
| Price > SMA50 > SMA200 | required | Confirms a real uptrend, short and long term |
| RSI (14) | 55–70 | Moving, but not yet overbought |
| ATR% | > 1.5% | Enough daily movement to make the trade worth it |
| Volume ratio | > 2× 20-day average | Unusual volume means institutions are involved |
| Day change | > 0.5% | Big volume on a down day is selling, not buying |
| Day change | < 8% | Do not chase something that has already run |
| 5-day momentum | > 2% | Technically sound but not actually moving is not a trade |
| Volume | > 50,000 shares | Liquidity floor |
| Traded value | > ₹2 crore/day | Enough turnover to get in and out |
| Price | > ₹100 | Avoids penny-stock behaviour |

Survivors are ranked: 40% volume ratio, 35% 5-day momentum, 25% ATR%.

### Fundamental check
Rejects structurally broken companies: market cap under ₹500 crore, debt/equity
above 2× (skipped for banks, where leverage is normal), negative return on
equity.

### Scoring — four dimensions, 100 points

| Dimension | Best | Middle | Worst |
|---|---|---|---|
| Entry timing | 30 | 18 | 0 |
| Momentum quality | 25 | 15 | 0 |
| Risk/reward | 20 | 12 | 0 |
| Market regime | 25 | 15 | 0 |

Nothing subtracts. The score cannot leave 0–100, so no clamping is needed.
**Buy at 65 or above.**

Market regime folds VIX, Nifty trend, and sector strength into one band. A stock
rising while its sector falls counts as strength — it cancels the weak-sector
warning, because outperforming a weak sector is the opposite of a problem.

Momentum quality is downgraded if the entry is late: textbook momentum you
arrived at too late is not textbook momentum.

### Exits

One function, `app/portfolio/exits.py`, decides every exit. Both the live system
and the backtest call it, so they cannot drift apart.

| Exit | Trigger |
|---|---|
| Stop | ATR-based: `2.5 × ATR%`, floor 5%, cap 10% |
| Trailing stop | Activates at +12%, trails `2 × ATR%` behind the peak (5–8%) |
| Target | +18% above entry |
| Timeout | 21 days |

Once a position gains 12%, up to three positions at a time switch to "hybrid"
mode: the target and timeout are removed, and the trailing stop becomes the only
exit. This lets genuine winners run.

**Circuit breaker:** if the portfolio falls more than 8% from its 30-day peak, new
entries pause until it recovers.

---

## Tech stack

| Layer | Technology |
|---|---|
| Pipeline orchestration | LangGraph — typed state, parallel fan-out, conditional routing |
| Market data | yfinance (NSE via Yahoo Finance) |
| Scheduling | APScheduler, NSE holiday-aware via the official NSE API |
| Database | SQLAlchemy 2.0 + SQLite |
| API | FastAPI + Jinja2 |
| Frontend | Tailwind + Chart.js + Alpine.js (CDN) |
| Config | Pydantic Settings (`.env`) |
| Logging | structlog — console + in-memory buffer streamed to the browser over SSE |
| CI | GitHub Actions — pytest on every push |

---

## Project structure

```
app/
├── agents/
│   ├── fundamental.py    # Market cap, debt/equity, ROE checks
│   ├── market_context.py # Nifty, sector, VIX, 52-week position
│   ├── technical.py      # Indicators → signal + strength
│   └── risk.py           # Position sizing and hard gates
├── screener/
│   ├── universe.py       # Fetch the NSE stock list
│   └── filters.py        # evaluate_candidate() + regime_blocked()  ← shared
├── portfolio/
│   ├── exits.py          # evaluate_exit() — every exit decision  ← shared
│   └── simulator.py      # Cash, trades, P&L, snapshots
├── graph/
│   ├── state.py          # LangGraph typed state
│   └── graph.py          # The pipeline
├── backtest/
│   ├── engine.py         # Day-by-day simulation
│   ├── store.py          # Local OHLCV cache
│   ├── ingest.py         # Downloads history into the cache
│   └── report.py         # Results tables and charts
├── utils/
│   ├── indicators.py     # RSI, MACD, Bollinger, ATR, SMA, momentum
│   └── scoring.py        # The four scoring dimensions
├── scheduler/scheduler.py
├── api/routes.py
├── templates/            # Dashboard pages
└── core/                 # Config, database, logging
main.py                   # One-off scan
backtest.py               # Run a backtest
```

The two files marked **shared** are the point: the live system and the backtest
call the same functions, so a change to trading rules cannot apply to one and not
the other. They used to be separate copies, and they had already drifted.

---

## Setup

Requires Python 3.10+.

```bash
git clone <repo>
cd NSETradeAgents
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

**Run the dashboard and scheduler:**
```bash
uvicorn app.api.routes:app --reload --reload-dir app
```
Then open `http://localhost:8000`.

**Run a single scan:**
```bash
python main.py
```

**Run a backtest:**
```bash
python backtest.py                      # 2022-2025
python backtest.py --start 2023-01-01   # custom range
python backtest.py --compare-hybrid     # A/B the hybrid exit mode
```

The first backtest run downloads about four years of daily data for 400 stocks
into `backtest_data.db`. That takes a while; later runs reuse the cache.

**Run tests:**
```bash
pytest -q
```

112 tests covering the screener filters, regime gate, exit ladder, scoring
dimensions, risk gates, fundamental checks, indicators, and the portfolio
simulator.

---

## Known limitations

Written down deliberately, because a backtest you cannot criticise is a backtest
you cannot trust.

1. **No trading costs or slippage** in the backtest.
2. **Survivorship bias** — the universe comes from today's index membership.
3. **No untouched holdout period** — thresholds were picked while looking at the
   full result.
4. **Price history is split-adjusted retroactively**, a mild form of hindsight.
5. **No sector data in the backtest**, so sector-based rules only work live.
6. **Fundamentals are current, not historical**, so that check runs live only.
7. **An LLM's contribution cannot be backtested here** — there is no point-in-time
   news archive, and any model has already read the news from the test period.
   That is why the veto agent will be validated forward, by grading its
   predictions against what actually happened.

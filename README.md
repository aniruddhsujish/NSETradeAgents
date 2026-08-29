# NSETradeAgents

An automated swing-trading system for NSE smallcap and midcap stocks. It scans
about 400 stocks every morning, screens and scores the setups, sizes positions,
and manages exits — holding for one to four weeks.

It runs in simulation mode against real market data. No real money.

The trading logic is entirely deterministic. A single LLM agent — a **forensic
veto** — runs alongside it in shadow mode, recording a verdict on every candidate
without being allowed to block anything. The reasoning behind that split is in
[Design decisions](#design-decisions).

---

## How it works

```
400 NSE stocks (Smallcap 250 + Midcap 150)
        ↓
Breadth gate ───────────► skip the day if under half the universe is above its own 50-day average
        ↓
Screener (10 filters) ──► rank what survives by volume, momentum, and volatility
        ↓
For each candidate, run the LangGraph pipeline:

  fetch_data ──► fundamental ──┬──► market_context ──┐
                               └──► technical ───────┴──► risk ──► score ──► veto
        ↓
Score 0–100. Buy at 65 or above. The veto records a verdict but does not block.
        ↓
Buy before the 15:30 close — the signal is a claim about today
        ↓
Decision record written for every candidate, bought or not
```

Every stage can reject a candidate. Most do.

### Daily schedule

| When (IST) | Job |
|---|---|
| 15:00 | Scan — screen, score, and open new positions before the 15:30 close |
| every 15 min | Check open positions against stop and target (market hours only) |
| 15:35 | Update trailing stops from the day's close |
| 16:00 | Post-mortem — fill in what past decisions actually returned |

---

## Trading strategy

### Universe
Nifty Smallcap 250 + Midcap 150, fetched from NSE's published index lists.

### Regime gate
If fewer than 50% of the universe are trading above their own 50-day average, no
new positions that day. Existing positions are unaffected.

Breadth rather than an index, because the index is not what gets traded: Nifty 50
rose 9.2% in 2025 while the median mid/smallcap fell 5.3%.

### Screener — 10 filters, all must pass

| Filter | Threshold | Purpose |
|---|---|---|
| Price > SMA50 > SMA200 | required | Uptrend on both short and long horizons |
| RSI (14) | 55–70 | Moving, not yet overbought |
| ATR% | > 1.5% | Enough daily range for the trade to be worth taking |
| Volume ratio | > 2× 20-day average | Unusual volume implies institutional activity |
| Day change | > 0.5% | High volume on a down day is distribution |
| Day change | < 8% | Avoids chasing a move that has already run |
| 5-day momentum | > 2% | Must actually be moving |
| Volume | > 50,000 shares | Liquidity floor |
| Traded value | > ₹2 crore/day | Enough turnover to enter and exit |
| Price | > ₹100 | Excludes penny-stock behaviour |

Survivors are ranked: 40% volume ratio, 35% 5-day momentum, 25% ATR%.

### Fundamental check
Rejects market cap under ₹500 crore, debt/equity above 2× (skipped for banks),
and negative return on equity.

### Scoring — four dimensions, 100 points

| Dimension | Best | Middle | Worst |
|---|---|---|---|
| Entry timing | 30 | 18 | 0 |
| Momentum quality | 25 | 15 | 0 |
| Risk/reward | 20 | 12 | 0 |
| Market regime | 25 | 15 | 0 |

Every dimension is banded and additive; nothing subtracts. **Entry threshold: 65.**

Market regime folds VIX, Nifty trend, and sector strength into one band. A stock
rising while its sector falls counts as strength. Momentum quality is downgraded
one band when entry timing is not ideal.

### Exits

`app/portfolio/exits.py` decides every exit, for both the live system and the
backtest.

Every level is scaled to the stock's own volatility, so a calm stock and a wild
one are asked to do proportionally the same thing.

| Exit | Trigger |
|---|---|
| Stop | `2.5 × ATR%` below entry, floor 5%, cap 10% |
| Trailing stop | Arms at `2 × ATR%` gain, then trails `2 × ATR%` behind the peak (5–8%) |
| Target | `4 × ATR%` above entry, floor 6%, cap 20% |
| Timeout | 21 days |

The trail must arm below the target or it never arms at all. Once armed, the
target stays live — whichever level the price reaches first ends the trade.

**Circuit breaker:** if the portfolio falls more than 8% from its 30-day peak,
new entries pause until it recovers.

**Position limits:** 5 concurrent positions, one per ticker.

**Entry timing:** the scan runs at 15:00 and buys before the close, so a setup is
evaluated and bought on the same day.

---

## The veto agent

`app/agents/veto.py` — a ReAct agent (Claude Opus 5 + Tavily search) that runs on
each candidate after it passes scoring. It is asked one question: *what
specifically kills this trade?*

It may only reject for one of five reasons, and every rejection must cite a
checkable fact — a date, a filing, a named event.

| Reason | Meaning |
|---|---|
| `EARNINGS_IMMINENT` | Results or board meeting within ~3 trading days |
| `ADVERSE_NEWS` | Regulatory action, auditor resignation, guidance cut, downgrade, key departure |
| `SUPPLY_OVERHANG` | Promoter selling or pledging, block deal, announced QIP/OFS |
| `NEWS_ALREADY_PRICED` | The move being bought was itself the reaction to now-public news |
| `PENDING_EVENT` | An unscheduled binary event is close |

Anything else is a pass. Search is capped at 8 queries per candidate, with a
LangGraph recursion limit as a backstop.

**Modes** — `VETO_MODE` is `off`, `shadow`, or `acting`. Default is `shadow`:
the verdict is recorded on the decision record and shown on the dashboard, but
the trade proceeds regardless.

**Failure behaviour** — any error returns a pass, with the error text stored in
the record's `checked` field. The dashboard counts these separately, because a
broken veto and a lenient one are otherwise indistinguishable.

---

## Measurement

Every candidate the scan evaluates produces a `DecisionRecord` — bought or not —
holding the score, the four bands, six indicators, the git commit, the block
reason, and the veto's full verdict.

The 16:00 post-mortem replays each decision through the same exit ladder the live
system uses and fills in what it would have returned. Rejected candidates get
graded alongside accepted ones.

The `/decisions` page shows all of this, plus:

- **kill rate** and a breakdown of which reasons the vetoes are made of
- **veto errors** — outage detection, since failures are recorded as passes
- **veto edge** — mean outcome of killed candidates minus mean outcome of passed
  ones. Negative means the veto is blocking trades that went on to do worse.

---

## Backtest results

Four years of NSE daily data, ₹2,00,000 starting capital, entry threshold 65.

| Metric | Value |
|---|---|
| Total return | +115.7% |
| CAGR | +21.2% |
| Sharpe ratio | 2.07 |
| Max drawdown | 13.4% |
| Total trades | 268 |
| Win rate | 56.3% |
| Profit factor | 1.89 |
| Average hold | 15.6 days |

**Exit distribution:** 65 stopped out · 114 timed out · 25 trailing stop · 64 target

| Year | Return | Trades | Win% | PF | Max drawdown |
|---|---|---|---|---|---|
| 2022 | +25.9% | 53 | 43.4% | 1.84 | 13.4% |
| 2023 | +47.5% | 74 | 71.6% | 4.17 | 4.8% |
| 2024 | +20.1% | 84 | 63.1% | 2.11 | 5.6% |
| 2025 | −4.2% | 57 | 38.6% | 0.78 | 8.3% |

### Against buying the universe and holding it

The honest benchmark, and the first thing worth knowing:

| | Strategy | Equal-weight universe, buy & hold |
|---|---|---|
| Total return | +115.7% | **+181.7%** |
| CAGR | +21.2% | **+29.6%** |
| Max drawdown | **13.4%** | 25.8% |
| Sharpe | **2.07** | 1.42 |

**Buying all 400 stocks on day one and doing nothing beat this system by 66 percentage points.** Indian smallcaps had an exceptional four years; almost anything long made money.

What the strategy did deliver is risk: a little over half the drawdown, and a materially better Sharpe, while holding at most five positions and sitting in cash whenever breadth is weak. That is a real result, but it is a *risk-adjusted* one — over this period the selection logic did not add return over its own universe.

Both figures carry the same survivorship bias, so the comparison between them is fair even though neither is achievable.

These numbers are optimistic. See [Known limitations](#known-limitations) for
what is not modelled.

**What the exit distribution shows:** 110 of 235 trades timed out — held three
weeks and closed for roughly nothing. The stop sits about 2.5 daily ranges below
entry while the target sits about 7 above, and three weeks of ordinary movement
covers about 4.6. Noise reaches the stop easily and rarely reaches the target.
Scaling the target to each stock's volatility, rather than a flat 18%, is the
open fix.

---

## Design decisions

### Trading logic is deterministic; the LLM only subtracts

An earlier version had three Claude agents — technical reading, news sentiment,
and a final buy decision. All three were removed.

The decision agent scored setups across dimensions that Python had already
computed, so it was re-deriving known values rather than adding information. The
sentiment agent fed live scoring but was replaced by a constant in the backtest,
which meant the backtest was not measuring the system that actually ran. Removing
all three moved the backtest result by under one percent.

The rule that replaced them: an LLM earns its place only where it brings
information the code cannot compute — and it may only remove trades, never add
them.

### The veto asks what kills a trade, not whether it is good

Asking a model to approve a setup the screener already selected produces
agreement, not analysis. Asking it to find a specific disqualifying fact produces
either a citation or a pass. The closed list of five reasons is enforced in code,
not only in the prompt: a verdict citing anything else is downgraded to a pass.

### Shadow mode before acting

The veto records verdicts without blocking, so every trade becomes a labelled
data point — including the ones the model wanted to stop. Its contribution can
then be measured as a difference in outcomes rather than argued for.

This matters because an LLM's contribution cannot be backtested here: there is no
point-in-time news archive, and any model has already read the news from the test
period. Forward validation is the only honest option.

### The exit ladder is scaled to volatility, and it was measured

An earlier ladder mixed units: the stop scaled with ATR while the target and the
trail arming point were flat percentages. A 2%-ATR stock and a 5%-ATR stock were
given stops proportional to their own movement and then asked to reach the same
fixed 18%.

Fixing it was not a matter of picking a multiplier. `3 × ATR` was tested first and
lost badly (+53% against +82%); `4 × ATR` won. A 21% swing from one parameter is
itself a warning that the strategy is sensitive to it, which is why the multiplier
is pinned by a test rather than left to drift.

The trail arming point had to move with the target. A flat 12% arming point sits
*above* an ATR-scaled target on most stocks, so the trail would never arm.

### Hybrid mode was removed, not disabled

An earlier version removed the target and timeout from up to three winners so they
could run indefinitely. It produced 80% of returns from ~28 long holds out of 232
trades.

It was deleted. A system earning from 250 ordinary trades degrades more gracefully
than one depending on a handful of exceptional ones — and that handful is exactly
where survivorship bias and overfitting concentrate, since the small illiquid names
that ran for 40 days are the ones that survived to still be listed. Under the ATR
ladder, turning it off was better outright (+85% against +74%).

### Buy on the signal day, not the next morning

The signal is a claim about today's action, so acting on it tomorrow means acting
on a condition that has already begun resolving. Three measurements agreed: the
median signal-close-to-next-open gap is **+0.47%**; that first night is worth
**1.5×** a typical held night (+0.474% against +0.312%, at identical volatility);
and the backtest improved on return, Sharpe and drawdown together.

The cost is honesty. The backtest decides on a bar and fills at that same bar's
close, which is a price it could not have known. Live closes most of the gap by
scanning at 15:00 — when the filters are ~92% resolved — and buying before 15:30.
The residual optimism is recorded under Known limitations.

### No configuration flags for settled questions

Every strategy question here was decided by measurement, and the losing branch was
deleted rather than left behind a flag. Dead paths drift: they stop being
exercised, stop being tested, and eventually stop working, while still looking
like a supported option. Git history is the record of what was tried.

### Everything fails open

The regime gate, the veto, the holiday check, and the heartbeat write all
degrade to "carry on" when they break. A silent halt is the worst failure mode
for this system — a stopped scan produces no error and no trades, and looks
identical to a quiet market.

### Live and backtest share the same code

`app/screener/filters.py` and `app/portfolio/exits.py` are called by both paths,
so a change to trading rules cannot apply to one and not the other. Every
extraction into these modules was verified by a byte-identical backtest output.

### Rejected candidates are recorded, not discarded

A system that only stores its trades can never learn what it was right to skip.
Decision records plus the post-mortem make the "no" decisions gradeable, which is
what turns the veto into a measurable experiment rather than a feature.

### One process, one worker

The scheduler runs inside the FastAPI lifespan, so a single `uvicorn` process
serves the dashboard and drives the pipeline. Running multiple workers would
start multiple schedulers and open duplicate positions.

### SQLite locally, Postgres when deployed

No raw SQL anywhere, so `DATABASE_URL` is the only thing that changes. SQLite is
the right fit for one process writing a handful of rows a day; hosted Postgres is
used when the data needs to outlive the server it runs on.

### Health is a heartbeat, not a row count

A quiet day writes no decision records, and so does a scheduler that never fired.
`ScanRun` records that a scan happened, separately from what it found. `/health`
serves it from memory and returns 503 once it goes stale, so an external monitor
catches a stopped scheduler as well as a dead host — and polling never wakes a
metered database.

---

## Tech stack

| Layer | Technology |
|---|---|
| Pipeline orchestration | LangGraph — typed state, parallel fan-out, conditional routing |
| Veto agent | LangChain `create_agent` (ReAct) + Claude Opus 5 + Tavily |
| Market data | yfinance (NSE via Yahoo Finance) |
| Scheduling | APScheduler, NSE holiday-aware via the official NSE API |
| Database | SQLAlchemy 2.0 — SQLite or Postgres |
| API | FastAPI + Jinja2 |
| Frontend | Tailwind + Chart.js + Alpine.js (CDN) |
| Config | Pydantic Settings (`.env`) |
| Logging | structlog — console plus an in-memory buffer streamed over SSE |
| CI | GitHub Actions — pytest on every push |

---

## Project structure

```
app/
├── agents/
│   ├── fundamental.py    # Market cap, debt/equity, ROE
│   ├── market_context.py # Nifty, sector, VIX, 52-week position
│   ├── technical.py      # Indicators → signal + strength
│   ├── risk.py           # Position sizing and hard gates
│   └── veto.py           # Forensic veto (ReAct + search)
├── screener/
│   ├── universe.py       # Fetch the NSE stock list
│   └── filters.py        # evaluate_candidate() + regime_blocked()  ← shared
├── portfolio/
│   ├── exits.py          # evaluate_exit() + update_trail()  ← shared
│   ├── simulator.py      # Cash, trades, P&L, snapshots
│   └── postmortem.py     # Grades past decisions against real outcomes
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
│   ├── market_data.py    # yfinance wrappers
│   └── scoring.py        # The four scoring dimensions
├── core/
│   ├── config.py         # Settings
│   ├── database.py       # Engine and session
│   ├── health.py         # Last-scan state behind /health
│   └── logging.py
├── scheduler/scheduler.py
├── api/routes.py
└── templates/            # Dashboard pages
main.py                   # One-off scan
backtest.py               # Run a backtest
```

---

## Setup

Requires Python 3.12.

```bash
git clone <repo>
cd NSETradeAgents
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add ANTHROPIC_API_KEY and TAVILY_API_KEY
```

**Dashboard and scheduler:**
```bash
uvicorn app.api.routes:app --reload --reload-dir app
```
Then open `http://localhost:8000`.

**One-off scan:**
```bash
python main.py
```

**Backtest:**
```bash
python backtest.py                      # 2022–2025
python backtest.py --start 2023-01-01   # custom range
python backtest.py --compare-hybrid     # A/B the hybrid exit mode
```

The first run downloads roughly four years of daily data for 400 stocks into
`backtest_data.db`; later runs reuse the cache.

**Tests:**
```bash
pytest -q
```

224 tests covering the screener, breadth gate, exit ladder, scoring, risk gates,
fundamentals, indicators, the simulator, the scan's control flow, the post-mortem,
the veto (fully stubbed, no API calls), and the health endpoint.

---

## Deployment

The whole system is one process. A single small VPS is enough.

| Piece | Choice |
|---|---|
| Host | One small instance, India region — NSE and Yahoo both throttle unfamiliar datacenter IPs |
| Process | `uvicorn app.api.routes:app --workers 1` under systemd, no `--reload` |
| Database | Hosted Postgres, so data survives the host |
| TLS | Caddy in front, on a domain |
| Monitoring | Any external uptime monitor pointed at `/health` |

`WorkingDirectory` matters in the systemd unit: both the SQLite path and the
`.env` lookup are relative. Keep `git` installed — decisions are stamped with the
current commit.

Verify outbound connectivity from the host before provisioning anything
permanent: one `screen()` call proves both NSE's index CSVs and the yfinance
batch download work from that IP.

---

## Known limitations

Recorded deliberately — a backtest you cannot criticise is a backtest you cannot
trust.

1. **No trading costs or slippage** modelled. Across 235 round trips on
   smallcaps, this is not a rounding error.
2. **Survivorship bias** — the universe comes from today's index membership, so
   delisted companies are absent.
3. **No untouched holdout period** — thresholds were chosen while looking at the
   full result.
4. **Price history is split-adjusted retroactively**, a mild form of hindsight.
5. **No sector data in the backtest**, so sector rules only apply live.
6. **Fundamentals are current, not historical**, so that check runs live only.
7. **The veto cannot be backtested** — no point-in-time news archive exists, and
   any model has already read the news from the test period. It is validated
   forward instead.
8. **`safe_yf_download` has no retry** — a single rate-limit response on the
   400-ticker batch ends that day's scan.
9. **Buy-and-hold beat it.** Equal-weight holding the same universe returned
   +181.7% against the strategy's +115.7%. The strategy's contribution over this
   period was risk reduction, not return.
10. **Trading costs are not in the engine.** Statutory NSE delivery charges are
    0.26% per round trip and were estimated post-hoc; at 257 trades they consume
    roughly a fifth of gross P&L before any slippage assumption.
11. **The backtest fills at a price it could not have known.** A signal is decided
    on a bar and filled at that bar's close. Live scans at 15:00 with ~92% of the
    session's volume in and fills near 15:25, roughly 0.2–0.4% from the close.
    Symmetric, but unquantified without intraday data.
12. **Live under-reads volume at scan time.** At 15:00 only ~90–93% of the day's
    volume has traded, so `volume_ratio` reads low and live takes fewer trades
    than the backtest. Conservative, but the backtest overstates trade count.
13. **The parameters have been fitted to this period.** The entry threshold, the
    ATR multiplier and the breadth floor were all chosen or confirmed against the
    same four years, across roughly twenty backtests. There is no untouched
    holdout, so the live result should be expected to be worse.

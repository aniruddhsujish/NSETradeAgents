# TODO — Swing Bot Improvements

---

## V2 Features

### Agents
- [ ] Position review agent — daily re-check of open position thesis, early exit signals
- [ ] Macro agent — dedicated Nifty/VIX/FII flow check before any trade (currently inside risk agent)
- [ ] Fundamental agent — revenue growth, D/E ratio, ROE, promoter holding filter before LLM
- [ ] Portfolio optimisation agent — rank multiple BUY signals by conviction when cash is limited
- [ ] Earnings calendar agent — tighten stops / flag positions ahead of results

### Screener
- [ ] Store Industry/sector from NSE CSV — use for sector exposure tracking
- [ ] Add fundamental pre-filter: P/E ratio, revenue growth, debt levels
- [ ] Add minimum market cap filter

### Risk & Position Sizing
- [ ] Sector exposure limit — block new trade if >40% already in same sector
- [ ] Time-based exit — close position if no significant move after N days

### Analysis & LLM
- [ ] Pass earnings date to decision agent — avoid entering 2 days before results
- [ ] Fine-tune prompts with real trade outcomes after 3-6 months of data

### Portfolio
- [ ] Trailing stops — activate once position is up X%, move stop to lock in gains
- [ ] EOD portfolio snapshot for P&L chart over time

### Scheduler
- [ ] Position monitor — hourly check on open positions during market hours
- [ ] Catchup missed jobs — fire missed jobs when laptop wakes from sleep

### Dashboard
- [ ] P&L chart over time (needs EOD snapshots)
- [ ] Sector exposure bar chart
- [ ] System logs tab — live bot output visible in dashboard

### Infrastructure
- [ ] Swap SQLite → PostgreSQL for production
- [ ] Telegram / email alerts on trade open/close
- [ ] Backtesting module — run strategy on historical data
- [ ] Kite API integration for live trading (Phase 2)
- [ ] Structured JSON logging for production (swap ConsoleRenderer → JSONRenderer)

---

## V1 Scope (building now)

- [x] Screener — universe fetch + math filters (SMA, ATR, volume, RSI, liquidity)
- [x] Config — pydantic-settings, type-safe
- [x] Database — SQLAlchemy + models
- [x] Logging — structlog
- [ ] Market context — Nifty day change, sector performance, 52w position, divergence
- [ ] Technical agent — indicators + Claude Haiku interpretation
- [ ] Sentiment agent — Tavily news + Claude Haiku scoring
- [ ] Risk agent — deterministic position sizing and trade gates
- [ ] Decision agent — Claude Sonnet final BUY/HOLD/SELL
- [ ] LangGraph orchestrator — parallel agents, state management
- [ ] Portfolio simulator — cash, positions, P&L tracking
- [ ] Scheduler — morning scan job
- [ ] FastAPI dashboard — portfolio, positions, trade history

# TODO — Swing Bot V2 Improvements

---

## Agents
- [ ] Deferred reflection system — after trade closes, LLM reflects on outcome vs thesis, persists lesson per ticker, injects into future decisions (inspired by TradingAgents)
- [ ] Bull/Bear debate — replace single decision agent with adversarial researcher pair + judge; reduces groupthink
- [ ] Position review agent — daily LLM re-check of open position thesis, flags early exit
- [ ] Macro agent — dedicated Nifty/VIX/FII check before any trade (currently embedded in risk agent)
- [ ] Portfolio optimisation agent — rank multiple BUY signals by conviction when cash is limited
- [ ] Earnings calendar agent — block entries within 2 days of results

## Risk & Sizing
- [ ] ATR-based stop loss — `price - 2×ATR` instead of fixed 7%; adapts to each stock's volatility
- [ ] Cash buffer — enforce 20-30% uninvested; currently 4×25% = 100% deployed
- [ ] Sector exposure limit — block if >40% portfolio in same sector
- [ ] Time-based exit — close if no meaningful move after N days
- [ ] Trailing stop — ratchet stop up once position is profitable

## Analysis
- [ ] Pass earnings date to decision agent — avoid entering 2 days before results
- [ ] Fine-tune prompts with real trade outcomes after 3-6 months of data
- [ ] Fundamental agent — add P/E and revenue growth checks (currently only market cap, D/E, ROE)

## Testing & Eval
- [ ] Unit test suite — risk, simulator, fundamental, indicators, screener, market hours
- [ ] Integration tests — full pipeline with mocked LLMs
- [ ] CI — GitHub Actions on every push
- [ ] Eval benchmark — historical screener + technical rules backtest vs baselines
- [ ] Forward test collector — reads real DB trades, fetches actual outcomes, computes win rate / Sharpe / alpha vs Nifty

## Dashboard
- [ ] Sector exposure chart
- [ ] Unrealised P&L over time (snapshots already being saved)

## Infrastructure
- [ ] Telegram / email alerts on trade open/close
- [ ] Kite API integration — live order placement (`simulation_mode=False`)
- [ ] Swap SQLite → PostgreSQL for production
- [ ] Backtesting module — screener + deterministic rules on historical OHLCV

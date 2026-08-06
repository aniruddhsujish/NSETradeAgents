import argparse
from datetime import date


def main():
    parser = argparse.ArgumentParser(description="Run NSE swing-trade backtest")
    parser.add_argument("--db", default="backtest_data.db")
    parser.add_argument(
        "--force-ingest",
        action="store_true",
        help="Re-download data even if DB already exists",
    )
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--csv", default="backtest_trades.csv")
    parser.add_argument(
        "--compare-hybrid",
        action="store_true",
        help="Run both trail+hybrid and trail-only variants and print side-by-side",
    )
    args = parser.parse_args()

    from app.backtest.ingest import run_ingest

    run_ingest(db_path=args.db, force=args.force_ingest)

    from app.backtest.engine import run_backtest
    from app.backtest.report import print_report

    if args.compare_hybrid:
        _run_comparison(args)
        return

    trades, equity_curve, all_scores = run_backtest(
        db_path=args.db,
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
    )
    print_report(trades, equity_curve, all_scores=all_scores, csv_path=args.csv)


def _run_comparison(args):
    import math
    from app.backtest.engine import run_backtest, ClosedTrade
    from datetime import date as _date

    start = _date.fromisoformat(args.start)
    end   = _date.fromisoformat(args.end)

    print("\nRunning variant A: trail + hybrid (target/timeout removed after trail)...")
    trades_h, curve_h, _ = run_backtest(db_path=args.db, start=start, end=end, hybrid_mode=True)

    print("Running variant B: trail + no hybrid (target/timeout still apply)...")
    trades_n, curve_n, _ = run_backtest(db_path=args.db, start=start, end=end, hybrid_mode=False)

    def _stats(trades: list[ClosedTrade], curve: list):
        if not curve:
            return {}
        sv, ev = curve[0][1], curve[-1][1]
        years = (curve[-1][0] - curve[0][0]).days / 365.25
        total_ret = (ev - sv) / sv * 100
        cagr = ((ev / sv) ** (1 / years) - 1) * 100 if years > 0 else 0

        daily = []
        for i in range(1, len(curve)):
            p, c = curve[i-1][1], curve[i][1]
            if p > 0:
                daily.append((c - p) / p)
        n = len(daily)
        if n >= 2:
            mean = sum(daily) / n
            std  = math.sqrt(sum((r - mean) ** 2 for r in daily) / (n - 1))
            sharpe = (mean / std) * math.sqrt(252) if std > 0 else 0
        else:
            sharpe = 0

        peak, max_dd = 0.0, 0.0
        for _, v in curve:
            if v > peak:
                peak = v
            if peak > 0:
                max_dd = max(max_dd, (peak - v) / peak * 100)

        completed = [t for t in trades if t.exit_reason != "end_of_backtest"]
        wins   = [t for t in completed if t.pnl > 0]
        losses = [t for t in completed if t.pnl <= 0]
        win_pct = len(wins) / len(completed) * 100 if completed else 0
        gross_loss = sum(t.pnl for t in losses)
        pf = sum(t.pnl for t in wins) / abs(gross_loss) if gross_loss != 0 else float("inf")
        avg_hold = sum((t.exit_date - t.entry_date).days for t in completed) / len(completed) if completed else 0
        exits = {}
        for t in completed:
            exits[t.exit_reason] = exits.get(t.exit_reason, 0) + 1

        return {
            "end_val": ev, "total_ret": total_ret, "cagr": cagr,
            "sharpe": sharpe, "max_dd": max_dd,
            "trades": len(completed), "win_pct": win_pct, "pf": pf,
            "avg_hold": avg_hold, "exits": exits,
        }

    h = _stats(trades_h, curve_h)
    n = _stats(trades_n, curve_n)

    W = 26
    print()
    print("=" * (W * 2 + 5))
    print(f"  {'HYBRID (trail, no cap/timeout)':<{W}}  {'NO HYBRID (trail + cap/timeout)':<{W}}")
    print("=" * (W * 2 + 5))
    print(f"  {'Ending capital':<20} ₹{h['end_val']:>10,.0f}           ₹{n['end_val']:>10,.0f}")
    print(f"  {'Total return':<20} {h['total_ret']:>+8.1f}%           {n['total_ret']:>+8.1f}%")
    print(f"  {'CAGR':<20} {h['cagr']:>+8.1f}%           {n['cagr']:>+8.1f}%")
    print(f"  {'Sharpe ratio':<20} {h['sharpe']:>9.2f}           {n['sharpe']:>9.2f}")
    print(f"  {'Max drawdown':<20} {h['max_dd']:>8.1f}%           {n['max_dd']:>8.1f}%")
    print("-" * (W * 2 + 5))
    print(f"  {'Total trades':<20} {h['trades']:>9}           {n['trades']:>9}")
    print(f"  {'Win rate':<20} {h['win_pct']:>8.1f}%           {n['win_pct']:>8.1f}%")
    pf_h = f"{h['pf']:.2f}" if h['pf'] != float('inf') else "  ∞"
    pf_n = f"{n['pf']:.2f}" if n['pf'] != float('inf') else "  ∞"
    print(f"  {'Profit factor':<20} {pf_h:>9}           {pf_n:>9}")
    print(f"  {'Avg hold days':<20} {h['avg_hold']:>9.1f}           {n['avg_hold']:>9.1f}")

    def _fmt_exits(e):
        return (f"stop={e.get('stop',0)} target={e.get('target',0)} "
                f"timeout={e.get('timeout',0)} trail={e.get('trail',0)}")
    print(f"  {'Exits':<20} {_fmt_exits(h['exits'])}")
    print(f"  {'':<20} {_fmt_exits(n['exits'])}")
    print("=" * (W * 2 + 5))


if __name__ == "__main__":
    main()

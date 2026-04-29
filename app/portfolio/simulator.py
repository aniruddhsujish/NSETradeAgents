import structlog
from datetime import datetime, date
from app.core.config import settings
from app.core.database import get_db

from app.models.models import Trade, PortfolioSnapshot

logger = structlog.get_logger()


class PortfolioSimulator:
    """Paper trading portfolio - all state persists in the DB"""

    def _compute_cash(self, db) -> float:
        open_invested = sum(
            t.entry_value for t in db.query(Trade).filter(Trade.status == "open").all()
        )
        realised_pnl = sum(
            t.pnl
            for t in db.query(Trade).filter(Trade.status == "closed").all()
            if t.pnl is not None
        )
        return settings.starting_capital - open_invested + realised_pnl

    def get_portfolio_state(self) -> dict:
        with get_db() as db:
            open_trades = db.query(Trade).filter(Trade.status == "open").all()
            cash = self._compute_cash(db)
            positions = [
                {
                    "ticker": t.ticker,
                    "entry_price": t.entry_price,
                    "quantity": t.quantity,
                    "entry_value": t.entry_value,
                    "stop_loss": t.stop_loss,
                    "take_profit": t.take_profit,
                    "opened_at": t.opened_at,
                }
                for t in open_trades
            ]
        return {
            "cash": round(cash, 2),
            "open_positions": len(open_trades),
            "positions": positions,
        }

    def open_trade(
        self,
        trade_result: dict,
        technical: dict,
        sentiment: dict,
    ) -> Trade | None:
        ticker = trade_result["ticker"]
        logger.info("simulator_open_trade", ticker=ticker)

        with get_db() as db:
            # Guard 1: never double buy the same ticker
            if (
                db.query(Trade)
                .filter(Trade.ticker == ticker, Trade.status == "open")
                .first()
            ):
                logger.warning("open_trade_duplicate", ticker=ticker)
                return None

            # Guard 2: cash check inside the same session - consistent with current DB state
            cash = self._compute_cash(db)
            entry_value = trade_result["position_size_inr"]
            if entry_value > cash:
                logger.warning(
                    "open_trade_insufficient_cash",
                    ticker=ticker,
                    required=entry_value,
                    available=cash,
                )
                return None

            trade = Trade(
                ticker=ticker,
                entry_price=trade_result["price"],
                quantity=trade_result["quantity"],
                entry_value=entry_value,
                stop_loss=trade_result["stop_loss"],
                take_profit=trade_result["take_profit"],
                status="open",
                confidence=trade_result["confidence"],
                reasoning=trade_result["reasoning"],
                technical_summary=technical.get("summary"),
                sentiment_summary=sentiment.get("summary"),
            )
            db.add(trade)
            db.flush()

            logger.info(
                "trade_opened",
                ticker=ticker,
                entry_price=trade.entry_price,
                quantity=trade.quantity,
                entry_value=entry_value,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit,
            )
            return trade

    def close_trade(self, ticker: str, close_price: float, reason: str) -> Trade | None:
        logger.info(
            "simulator_close_trade",
            ticker=ticker,
            close_price=close_price,
            reason=reason,
        )

        with get_db() as db:
            trade = (
                db.query(Trade)
                .filter(Trade.ticker == ticker, Trade.status == "open")
                .first()
            )
            if not trade:
                logger.warning("close_trade_not_found", ticker=ticker)
                return None

            pnl = round((close_price - trade.entry_price) * trade.quantity, 2)
            pnl_pct = round(
                (close_price - trade.entry_price) / trade.entry_price * 100, 2
            )

            trade.status = "closed"
            trade.close_price = close_price
            trade.close_reason = reason
            trade.pnl = pnl
            trade.pnl_pct = pnl_pct
            trade.closed_at = datetime.now()

            logger.info(
                "trade_closed",
                ticker=ticker,
                close_price=close_price,
                pnl=pnl,
                pnl_pct=pnl_pct,
                reason=reason,
            )
            return trade

    def save_snapshot(
        self, open_prices: dict[str, float] | None = None
    ) -> PortfolioSnapshot:
        with get_db() as db:
            open_trades = db.query(Trade).filter(Trade.status == "open").all()
            closed_trades = db.query(Trade).filter(Trade.status == "closed").all()

            invested = sum(t.entry_value for t in open_trades)
            realised_pnl = sum(t.pnl for t in closed_trades if t.pnl is not None)
            cash = settings.starting_capital - invested + realised_pnl

            if open_prices:
                market_value = sum(
                    open_prices.get(t.ticker, t.entry_price) * t.quantity
                    for t in open_trades
                )
                unrealised_pnl = round(market_value - invested, 2)
                total_value = cash + market_value
            else:
                unrealised_pnl = 0.0
                total_value = cash + invested

            today = date.today()
            daily_pnl = sum(
                t.pnl
                for t in closed_trades
                if t.pnl is not None
                and t.closed_at is not None
                and t.closed_at.date() == today
            )

            snapshot = PortfolioSnapshot(
                total_value=round(total_value, 2),
                cash=round(cash, 2),
                invested=round(invested, 2),
                open_positions=len(open_trades),
                daily_pnl=round(daily_pnl, 2),
                cumulative_pnl=round(realised_pnl, 2),
                unrealised_pnl=unrealised_pnl,
            )
            db.add(snapshot)
            db.flush()

            logger.info(
                "snapshot_saved",
                total_value=snapshot.total_value,
                cash=snapshot.cash,
                unrealised_pnl=snapshot.unrealised_pnl,
                daily_pnl=snapshot.daily_pnl,
                cumulative_pnl=snapshot.cumulative_pnl,
            )
            return snapshot


simulator = PortfolioSimulator()

from dataclasses import dataclass
from datetime import date

from app.core.config import settings


@dataclass(frozen=True)
class Bar:
    """One price observation.

    The backtest passes a real daily OHLC bar; live passes a single tick via
    `flat()`. Writing the exit rules against one shape keeps both paths
    identical.
    """

    open: float
    high: float
    low: float
    close: float

    @classmethod
    def flat(cls, price: float) -> "Bar":
        """A bar for a single observed price, where open, high, low and close are equal."""
        return cls(price, price, price, price)


@dataclass(frozen=True)
class PositionView:
    """The fields the exit rules need, independent of how a position is stored.

    Lets the backtest's dataclass and the live DB row feed the same logic.
    """

    entry_date: date
    stop_price: float
    target_price: float
    trail_stop: float = 0.0
    hybrid_active: bool = False


def stop_pct(atr_pct: float | None) -> float:
    """Stop distance as a fraction of entry price.

    2.5x the stock's ATR, floored at 5% and capped at 10%. Falls back to the
    flat default when ATR is missing or zero"""
    if atr_pct is None or atr_pct <= 0:
        return settings.stop_loss_pct
    return min(max(2.5 * atr_pct / 100, 0.05), 0.10)


def target_pct(atr_pct: float | None) -> float:
    """Target distance as a fraction of entry price.

    Takes atr_pct — currently unused — so the flat target can become
    ATR-scaled by changing this function alone.
    """
    return settings.take_profit_pct


def evaluate_exit(pos: PositionView, bar: Bar, today: date) -> tuple[float, str] | None:
    """Single source of truth for whether a position exits, and at what price.

    Returns (exit_price, reason) or None to hold.
    Reasons: stop | trail | target | timeout.
    """

    effective_stop = pos.trail_stop if pos.trail_stop > 0 else pos.stop_price
    stop_hit = bar.low <= effective_stop
    target_hit = (not pos.hybrid_active) and bar.high >= pos.target_price
    days_held = (today - pos.entry_date).days

    # On a daily bar we cannot know whether the low or the high came first,
    # so a bar that touches both is resolved pessimistically as a stop.
    if stop_hit and target_hit:
        return min(bar.open, effective_stop), "stop"
    if stop_hit:
        return min(bar.open, effective_stop), "trail" if pos.trail_stop > 0 else "stop"
    if target_hit:
        return max(bar.open, pos.target_price), "target"
    if (not pos.hybrid_active) and days_held >= settings.max_hold_days:
        return bar.close, "timeout"
    return None  # hold


def update_trail(
    *,
    close: float,
    entry_price: float,
    atr_pct: float,
    peak_price: float,
    trail_stop: float,
    stop_price: float,
) -> tuple[float, float, bool]:
    """Ratchet the trailing stop against a closing price.

    The trail arms once the position is up by the activation threshold, then
    follows the peak at a distance scaled to the stock's ATR. It never moves
    down, and never sits below the original stop.

    Returns (peak, trail_stop, active), where `active` means the position is
    above the activation threshold today.
    """
    peak = max(peak_price, close)
    active = close >= entry_price * (1 + settings.trail_activation_pct)
    if not active:
        return peak, trail_stop, False
    trail_pct = (
        min(max(2.0 * atr_pct / 100, settings.trail_min_pct), settings.trail_max_pct)
        if atr_pct > 0
        else settings.trail_min_pct
    )
    new_trail = max(peak * (1 - trail_pct), trail_stop, stop_price)
    return peak, new_trail, True

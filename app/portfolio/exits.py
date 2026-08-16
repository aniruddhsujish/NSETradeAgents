from dataclasses import dataclass
from datetime import date

from app.core.config import settings


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float

    @classmethod
    def flat(cls, price: float) -> "Bar":
        return cls(price, price, price, price)


@dataclass(frozen=True)
class PositionView:
    """The only fields the exit ladder needs"""

    entry_date: date
    stop_price: float
    target_price: float
    trail_stop: float = 0.0
    hybrid_active: bool = False


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

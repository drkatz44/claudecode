"""Recommender — converts signals into actionable trade recommendations.

Bridges market-agent signals to tastytrade execution. Produces order leg dicts
compatible with tasty-agent MCP's place_order(legs=[...]) for equities, options,
and crypto. Claude passes these directly to the MCP server.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..analysis.screener import ScreenResult
from ..data.models import Signal, SignalDirection


@dataclass
class OptionsStrategy:
    """Suggested options strategy for a signal."""
    strategy_type: str  # short_put, iron_condor, strangle, vertical_spread, covered_call
    dte_range: tuple[int, int] = (30, 45)  # min/max days to expiration
    delta_target: Optional[float] = None  # target delta for short strikes
    width: Optional[int] = None  # spread width in strikes (for verticals/condors)
    rationale: str = ""
    # Resolved fields (populated by options.resolve_strategy)
    expiration: Optional[str] = None
    legs: Optional[list[dict]] = None
    credit: Optional[Decimal] = None
    max_loss: Optional[Decimal] = None
    breakevens: Optional[list[Decimal]] = None

    def to_dict(self) -> dict:
        d = {
            "strategy_type": self.strategy_type,
            "dte_min": self.dte_range[0],
            "dte_max": self.dte_range[1],
            "rationale": self.rationale,
        }
        if self.delta_target is not None:
            d["delta_target"] = self.delta_target
        if self.width is not None:
            d["spread_width"] = self.width
        if self.expiration:
            d["expiration"] = self.expiration
        if self.legs:
            d["legs"] = self.legs
        if self.credit is not None:
            d["credit"] = float(self.credit)
        if self.max_loss is not None:
            d["max_loss"] = float(self.max_loss)
        if self.breakevens:
            d["breakevens"] = [float(b) for b in self.breakevens]
        return d


@dataclass
class Recommendation:
    """Actionable trade recommendation."""
    symbol: str
    action: str  # "buy_equity", "sell_premium", "sell_equity", "watch"
    direction: str  # "long", "short", "neutral"
    confidence: float  # 0-1
    strategy_name: str
    entry_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    risk_reward: Optional[float] = None
    position_size_pct: float = 5.0  # % of portfolio
    options_strategy: Optional[OptionsStrategy] = None
    rationale: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def risk_per_share(self) -> Optional[Decimal]:
        if self.entry_price and self.stop_loss:
            return abs(self.entry_price - self.stop_loss)
        return None

    def to_order_legs(self, quantity: int = 100) -> list[dict]:
        """Convert recommendation to tastytrade-compatible order legs.

        Produces dicts matching tasty-agent MCP OrderLeg schema:
            - symbol, action, quantity
            - option_type, strike_price, expiration_date (for options)

        Args:
            quantity: Number of shares (equities) or contracts (options).
                      Default 100 shares for equities.

        Returns:
            List of order leg dicts ready for place_order(legs=[...]).
        """
        if self.action == "sell_premium" and self.options_strategy and self.options_strategy.legs:
            # Options: use resolved strategy legs
            legs = []
            for leg in self.options_strategy.legs:
                order_leg = {
                    "symbol": self.symbol,
                    "quantity": quantity,
                    "option_type": "P" if leg["type"] == "put" else "C",
                    "strike_price": leg["strike"],
                    "expiration_date": self.options_strategy.expiration,
                }
                if leg["side"] == "sell":
                    order_leg["action"] = "Sell to Open"
                else:
                    order_leg["action"] = "Buy to Open"
                legs.append(order_leg)
            return legs

        elif self.action == "buy_equity":
            return [{"symbol": self.symbol, "action": "Buy", "quantity": quantity}]

        elif self.action == "sell_equity":
            return [{"symbol": self.symbol, "action": "Sell", "quantity": quantity}]

        return []

    def to_dict(self) -> dict:
        d = {
            "symbol": self.symbol,
            "action": self.action,
            "direction": self.direction,
            "confidence": round(self.confidence, 2),
            "strategy": self.strategy_name,
            "rationale": self.rationale,
        }
        if self.entry_price:
            d["entry_price"] = float(self.entry_price)
        if self.stop_loss:
            d["stop_loss"] = float(self.stop_loss)
        if self.take_profit:
            d["take_profit"] = float(self.take_profit)
        if self.risk_reward:
            d["risk_reward"] = round(self.risk_reward, 2)
        if self.options_strategy:
            d["options_strategy"] = self.options_strategy.to_dict()
        order_legs = self.to_order_legs()
        if order_legs:
            d["order_legs"] = order_legs
        return d


def recommend_from_signal(signal: Signal) -> Recommendation:
    """Convert a Signal into a Recommendation with strategy details."""
    rationale = []
    options_strat = None

    if signal.direction == SignalDirection.LONG:
        action = "buy_equity"
        rationale.append(f"Long signal from {signal.strategy}")
        if signal.metadata.get("rsi"):
            rationale.append(f"RSI: {signal.metadata['rsi']}")
        if signal.risk_reward:
            rationale.append(f"R/R: {signal.risk_reward:.1f}:1")

    elif signal.direction == SignalDirection.SHORT:
        action = "sell_equity"
        rationale.append(f"Short signal from {signal.strategy}")

    elif signal.direction == SignalDirection.NEUTRAL:
        action = "sell_premium"
        rationale.append(f"Neutral/volatility signal from {signal.strategy}")
        options_strat = _suggest_options_strategy(signal)

    else:
        action = "watch"
        rationale.append("Signal strength too low for action")

    # Scale position size by confidence
    pos_size = _position_size(signal.strength)

    return Recommendation(
        symbol=signal.symbol,
        action=action,
        direction=signal.direction.value,
        confidence=signal.strength,
        strategy_name=signal.strategy,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        risk_reward=signal.risk_reward,
        position_size_pct=pos_size,
        options_strategy=options_strat,
        rationale=rationale,
        metadata=signal.metadata,
    )


def recommend_from_momentum(result: ScreenResult, signal: Signal) -> Recommendation:
    """Build recommendation from momentum screen + signal."""
    rec = recommend_from_signal(signal)

    # Augment with screen data
    rec.rationale.append(f"Screen score: {result.score}")
    rec.rationale.append(f"Trend: {result.trend}")
    if result.volume_ratio > 1.5:
        rec.rationale.append(f"Volume surge: {result.volume_ratio:.1f}x average")

    # Offer options alternative for high-confidence momentum
    if signal.strength > 0.7 and signal.direction == SignalDirection.LONG:
        rec.options_strategy = OptionsStrategy(
            strategy_type="short_put",
            dte_range=(30, 45),
            delta_target=0.25,
            rationale="Strong bullish momentum — sell puts below support",
        )
    return rec


def recommend_from_reversion(result: ScreenResult, signal: Signal) -> Recommendation:
    """Build recommendation from mean reversion screen + signal."""
    rec = recommend_from_signal(signal)
    rec.rationale.append(f"BB %B: {result.bb_pct_b:.2f} (oversold)")
    rec.rationale.append(f"Target: SMA-20 at {result.sma_20:.2f}")

    # Mean reversion — smaller position, tighter stops
    rec.position_size_pct = min(rec.position_size_pct, 3.0)
    return rec


def recommend_from_volatility(result: ScreenResult, signal: Signal) -> Recommendation:
    """Build recommendation from volatility screen + signal."""
    rec = recommend_from_signal(signal)
    rec.rationale.append(f"ATR: {result.atr_pct:.1f}% — high realized vol")

    suggested = signal.metadata.get("suggested_strategy", "strangle")
    rec.options_strategy = _build_vol_strategy(suggested, result)
    return rec


def _suggest_options_strategy(signal: Signal) -> OptionsStrategy:
    """Pick an options strategy based on signal metadata."""
    suggested = signal.metadata.get("suggested_strategy", "short_put")
    atr_pct = signal.metadata.get("atr_pct", 3.0)
    trend = signal.metadata.get("trend", "neutral")

    if suggested == "iron_condor":
        return OptionsStrategy(
            strategy_type="iron_condor",
            dte_range=(30, 45),
            delta_target=0.16,
            width=5,
            rationale=f"Neutral/bearish trend with {atr_pct:.1f}% ATR — defined risk",
        )
    elif suggested == "strangle":
        return OptionsStrategy(
            strategy_type="strangle",
            dte_range=(30, 45),
            delta_target=0.16,
            rationale=f"Neutral trend with moderate vol — sell both sides",
        )
    else:  # short_put default
        return OptionsStrategy(
            strategy_type="short_put",
            dte_range=(30, 45),
            delta_target=0.20 if trend == "bullish" else 0.15,
            rationale=f"{trend} trend — sell puts at safe delta",
        )


def _build_vol_strategy(suggested: str, result: ScreenResult) -> OptionsStrategy:
    """Build options strategy from volatility screen."""
    if suggested == "iron_condor":
        return OptionsStrategy(
            strategy_type="iron_condor",
            dte_range=(30, 45),
            delta_target=0.16,
            width=5 if result.close > 100 else 2,
            rationale=f"{result.trend} with {result.atr_pct:.1f}% ATR — iron condor for defined risk",
        )
    elif suggested == "strangle":
        return OptionsStrategy(
            strategy_type="strangle",
            dte_range=(30, 45),
            delta_target=0.16,
            rationale=f"Neutral with {result.atr_pct:.1f}% ATR — sell OTM strangle",
        )
    else:
        return OptionsStrategy(
            strategy_type="short_put",
            dte_range=(30, 45),
            delta_target=0.20,
            rationale=f"{result.trend} — sell puts below support",
        )


def _position_size(confidence: float) -> float:
    """Scale position size by confidence. Max 10%, min 2%."""
    if confidence >= 0.8:
        return 10.0
    elif confidence >= 0.6:
        return 7.0
    elif confidence >= 0.4:
        return 5.0
    else:
        return 2.0


def generate_recommendations(
    signals: list[Signal],
    max_recommendations: int = 10,
    min_confidence: float = 0.3,
) -> list[Recommendation]:
    """Convert a list of signals into ranked recommendations."""
    recs = []
    for signal in signals:
        if signal.strength < min_confidence:
            continue
        rec = recommend_from_signal(signal)
        recs.append(rec)

    # Sort by confidence descending
    recs.sort(key=lambda r: r.confidence, reverse=True)
    return recs[:max_recommendations]

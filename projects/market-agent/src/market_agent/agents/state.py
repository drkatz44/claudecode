"""Shared state models for the agent system.

All agents read and write to PortfolioState — the single source of truth
passed through the orchestrator pipeline.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class VolRegime(str, Enum):
    LOW = "low"        # VIX < 15
    NORMAL = "normal"  # 15 <= VIX <= 25
    HIGH = "high"      # VIX > 25


class RegimeState(BaseModel):
    """Current market regime derived from VIX and IV metrics."""

    vix_level: float
    vix_5d_change: float
    regime: VolRegime
    ivr: float = Field(ge=0, le=100)  # IV rank 0-100
    ivx: float = Field(ge=0)          # 30-day expected move
    ivr_5d_change: float = 0.0
    vix_term_structure: str = "contango"  # contango|backwardation|flat
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=None))


class TradeProposal(BaseModel):
    """A concrete trade proposal with strategy, legs, and risk parameters."""

    symbol: str
    strategy_type: str  # strangle, jade_lizard, calendar, diagonal, back_ratio, bwb, etc.
    legs: list[dict]
    regime: VolRegime
    position_size_pct: float = Field(ge=0, le=10)  # 1-5% typical
    profit_target_pct: float = 50.0   # 50% default, 25% for 0DTE, 80% directional
    max_dte: int = 45
    rationale: list[str] = Field(default_factory=list)
    risk_score: float = Field(default=0.0, ge=0, le=1)
    eval_stats: Optional[dict] = None  # Populated by evaluator (Phase 2)
    is_madman: bool = False
    credit: Optional[float] = None
    max_loss: Optional[float] = None
    breakevens: list[float] = Field(default_factory=list)


class PortfolioState(BaseModel):
    """Shared state passed through the agent pipeline.

    Each agent reads what it needs and writes its output section.
    """

    net_liq: Decimal = Decimal("75000")
    buying_power: Decimal = Decimal("75000")
    bp_usage_pct: float = 0.0
    open_positions: list[dict] = Field(default_factory=list)
    portfolio_delta: float = 0.0
    portfolio_theta: float = 0.0
    portfolio_vega: float = 0.0
    regime: Optional[RegimeState] = None
    proposals: list[TradeProposal] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    scan_symbols: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=None))

"""Risk management: portfolio validation and trade risk checks.

Validates proposed trades against portfolio-level risk rules before
passing orders to the MCP place_order tool.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from .models import OrderLeg, RiskProfile, StrategyType

# ---------------------------------------------------------------------------
# Portfolio models
# ---------------------------------------------------------------------------

class PositionSummary(BaseModel):
    """Summary of a single position."""

    underlying: str
    strategy_type: StrategyType | None = None
    quantity: int = 0
    mark: Decimal = Decimal("0")
    notional: Decimal = Decimal("0")


class PortfolioSnapshot(BaseModel):
    """Current portfolio state, built from MCP get_positions / get_balances."""

    net_liquidating_value: Decimal = Field(..., description="Net liquidating value")
    buying_power: Decimal = Field(..., description="Available buying power")
    positions: list[PositionSummary] = Field(default_factory=list)
    portfolio_delta: Decimal = Decimal("0")
    portfolio_theta: Decimal = Decimal("0")
    portfolio_vega: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Risk rules
# ---------------------------------------------------------------------------

class RiskRules(BaseModel):
    """Portfolio risk limits."""

    max_position_pct: Decimal = Field(
        default=Decimal("0.05"),
        description="Max loss per position as fraction of NLV (default 5%)",
    )
    max_bp_usage_pct: Decimal = Field(
        default=Decimal("0.50"),
        description="Max buying power usage as fraction of total BP (default 50%)",
    )
    min_dte: int = Field(
        default=7,
        description="Minimum days to expiration (default 7)",
    )
    max_correlated_positions: int = Field(
        default=3,
        description="Max positions in the same underlying",
    )


# ---------------------------------------------------------------------------
# Risk check result
# ---------------------------------------------------------------------------

class RiskCheckResult(BaseModel):
    """Result of a risk validation check."""

    approved: bool
    violations: list[str] = Field(
        default_factory=list, description="Hard violations (trade blocked)"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Soft warnings (trade allowed)"
    )


# ---------------------------------------------------------------------------
# Risk check logic
# ---------------------------------------------------------------------------

def check_trade(
    risk_profile: RiskProfile,
    legs: list[OrderLeg],
    portfolio: PortfolioSnapshot,
    rules: RiskRules | None = None,
) -> RiskCheckResult:
    """Validate a proposed trade against portfolio risk rules.

    Args:
        risk_profile: The strategy's risk profile (max loss, max profit, etc.)
        legs: Order legs for the proposed trade.
        portfolio: Current portfolio snapshot.
        rules: Risk rules to check against. Uses defaults if None.

    Returns:
        RiskCheckResult with approved status, violations, and warnings.
    """
    if rules is None:
        rules = RiskRules()

    violations: list[str] = []
    warnings: list[str] = []

    # Check position size vs NLV
    if portfolio.net_liquidating_value > 0:
        position_pct = risk_profile.max_loss / portfolio.net_liquidating_value
        if position_pct > rules.max_position_pct:
            violations.append(
                f"Position risk {position_pct:.1%} exceeds max {rules.max_position_pct:.1%} of NLV "
                f"(max_loss=${risk_profile.max_loss}, NLV=${portfolio.net_liquidating_value})"
            )
        elif position_pct > rules.max_position_pct * Decimal("0.8"):
            warnings.append(
                f"Position risk {position_pct:.1%} approaching limit of "
                f"{rules.max_position_pct:.1%}"
            )

    # Check DTE
    for leg in legs:
        if leg.expiration_date:
            from datetime import date, datetime

            try:
                exp = datetime.strptime(leg.expiration_date, "%Y-%m-%d").date()
                dte = (exp - date.today()).days
                if dte < rules.min_dte:
                    violations.append(
                        f"{leg.symbol} expiration {leg.expiration_date} is {dte} DTE "
                        f"(minimum: {rules.min_dte})"
                    )
            except ValueError:
                warnings.append(f"Could not parse expiration date: {leg.expiration_date}")

    # Check correlated positions
    if legs:
        underlying = legs[0].symbol
        existing_count = sum(
            1 for p in portfolio.positions if p.underlying == underlying
        )
        if existing_count >= rules.max_correlated_positions:
            violations.append(
                f"Already {existing_count} positions in {underlying} "
                f"(max: {rules.max_correlated_positions})"
            )

    # Check buying power usage
    if portfolio.buying_power > 0:
        # Estimate BP reduction as max_loss (conservative)
        bp_after = portfolio.buying_power - risk_profile.max_loss
        total_bp = portfolio.buying_power
        usage_after = 1 - (bp_after / total_bp)
        if usage_after > rules.max_bp_usage_pct:
            violations.append(
                f"Trade would push BP usage to {usage_after:.1%} "
                f"(max: {rules.max_bp_usage_pct:.1%})"
            )

    # Risk/reward warning
    if risk_profile.risk_reward_ratio is not None and risk_profile.risk_reward_ratio > 5:
        warnings.append(
            f"Poor risk/reward ratio: {risk_profile.risk_reward_ratio:.1f}:1"
        )

    return RiskCheckResult(
        approved=len(violations) == 0,
        violations=violations,
        warnings=warnings,
    )


def portfolio_from_positions(
    positions_data: list[dict],
    balances_data: dict,
) -> PortfolioSnapshot:
    """Build a PortfolioSnapshot from raw MCP response data.

    Args:
        positions_data: List of position dicts from MCP get_positions.
        balances_data: Balance dict from MCP get_balances.

    Returns:
        PortfolioSnapshot ready for risk checks.
    """
    positions = []
    for p in positions_data:
        positions.append(PositionSummary(
            underlying=p.get("underlying-symbol", p.get("symbol", "")),
            quantity=int(p.get("quantity", 0)),
            mark=Decimal(str(p.get("mark", 0))),
            notional=Decimal(str(p.get("mark", 0))) * int(p.get("quantity", 0)),
        ))

    return PortfolioSnapshot(
        net_liquidating_value=Decimal(str(balances_data.get("net-liquidating-value", 0))),
        buying_power=Decimal(str(balances_data.get("derivative-buying-power", 0))),
        positions=positions,
    )

"""Risk Monitor agent.

Two responsibilities:
  1. Entry-time: compute risk_score (0-1) for each proposal
  2. In-trade: generate alerts for open positions needing management

Entry risk score components (all weighted 0-1, higher = riskier):
  - BP impact:    larger position relative to available BP = higher risk
  - Correlation:  same underlying already in portfolio = higher risk
  - Regime fit:   strategy matches regime = lower risk
  - IVR:          higher IVR = lower risk for premium sellers

Adjustment triggers for open positions:
  - 21 DTE → roll alert
  - P&L > 2x credit → close alert (winner going against)
  - Position delta > 0.30 → direction breach alert
  - Prob-of-touch >50% exceeded → roll strikes

Reads:  state.proposals, state.open_positions, state.regime
Writes: proposal.risk_score, state.alerts
"""

import logging
from decimal import Decimal

from ..analysis.sectors import get_sector, sector_headroom
from .state import PortfolioState, TradeProposal, VolRegime

logger = logging.getLogger(__name__)

# Strategy → ideal regime mapping (lower penalty when aligned)
STRATEGY_REGIME_FIT: dict[str, set[VolRegime]] = {
    "calendar":       {VolRegime.LOW},
    "diagonal":       {VolRegime.LOW},
    "bwb":            {VolRegime.LOW, VolRegime.HIGH},
    "vertical_spread": {VolRegime.LOW, VolRegime.NORMAL},
    "iron_condor":    {VolRegime.NORMAL},
    "strangle":       {VolRegime.NORMAL, VolRegime.HIGH},
    "jade_lizard":    {VolRegime.NORMAL, VolRegime.HIGH},
    "back_ratio":     {VolRegime.HIGH},
    "short_put":      {VolRegime.NORMAL, VolRegime.HIGH},
}

# Alert thresholds for open positions
DTE_ROLL_THRESHOLD = 21        # Roll at or below this DTE
DELTA_BREACH_THRESHOLD = 0.30  # Abs delta above which to alert
LOSS_MULTIPLIER_CLOSE = 2.0    # Close alert when loss > 2x credit

# Portfolio heat thresholds (delta as % of net liq)
DELTA_HEAT_ALERT_PCT = 25.0    # Warn when portfolio delta exceeds this %
DELTA_HEAT_SCORE_HIGH = 20.0   # Heat score = 0.8 above this
DELTA_HEAT_SCORE_MED = 10.0    # Heat score = 0.4 above this
THETA_HEAT_ALERT_PCT = 1.0     # Warn when daily theta > 1% of net liq


class RiskMonitor:
    """Computes entry-time risk scores and generates in-trade adjustment alerts.

    Reads:  state.proposals, state.open_positions, state.regime
    Writes: proposal.risk_score, state.alerts
    """

    def run(self, state: PortfolioState) -> PortfolioState:
        """Score proposals and audit open positions."""
        # Score new proposals
        for proposal in state.proposals:
            proposal.risk_score = self._score_proposal(proposal, state)

        # Check open positions for adjustment triggers
        self._check_open_positions(state)

        # Portfolio-level heat alerts (independent of individual positions)
        self._check_portfolio_heat(state)

        logger.info(
            "Risk Monitor: scored %d proposals, checked %d open positions",
            len(state.proposals), len(state.open_positions),
        )
        return state

    # ------------------------------------------------------------------
    # Entry-time scoring
    # ------------------------------------------------------------------

    def _score_proposal(self, proposal: TradeProposal, state: PortfolioState) -> float:
        """Compute composite risk score in [0, 1]. Higher = riskier."""
        scores: list[float] = []

        # 1. BP impact (0 = negligible, 1 = at limit)
        bp_score = self._bp_impact_score(proposal, state)
        scores.append(bp_score * 0.30)  # 30% weight

        # 2. Sector correlation / concentration (0 = unique sector, 1 = at cap)
        corr_score = self._correlation_score(proposal, state)
        scores.append(corr_score * 0.20)  # 20% weight

        # 3. Regime fit (0 = perfectly aligned, 1 = wrong regime)
        regime_score = self._regime_fit_score(proposal, state)
        scores.append(regime_score * 0.25)  # 25% weight

        # 4. IVR score (0 = very high IVR = good entry, 1 = very low IVR = risky)
        ivr_score = self._ivr_score(state)
        scores.append(ivr_score * 0.10)  # 10% weight

        # 5. Portfolio heat (0 = cool portfolio, 0.8 = already heavily directional)
        heat_score = self._portfolio_heat_score(proposal, state)
        scores.append(heat_score * 0.15)  # 15% weight

        composite = sum(scores)
        return round(min(max(composite, 0.0), 1.0), 3)

    def _bp_impact_score(self, proposal: TradeProposal, state: PortfolioState) -> float:
        """Higher score if position uses more BP relative to available."""
        net_liq = float(state.net_liq)
        buying_power = float(state.buying_power)
        if net_liq <= 0 or buying_power <= 0:
            return 1.0

        position_bp = net_liq * proposal.position_size_pct / 100
        bp_fraction = position_bp / buying_power  # 0-1
        return min(bp_fraction * 3.0, 1.0)  # Scale: 33% of BP = score 1.0

    def _correlation_score(self, proposal: TradeProposal, state: PortfolioState) -> float:
        """Higher score if same underlying or same sector is concentrated in portfolio."""
        # Same-symbol concentration (hard limit — most correlated)
        same_underlying = sum(
            1 for p in state.open_positions
            if p.get("symbol", "").upper() == proposal.symbol.upper()
        )
        symbol_score = min(same_underlying * 0.5, 1.0)

        # Sector concentration — how much headroom remains in this sector
        sector = get_sector(proposal.symbol)
        headroom = sector_headroom(sector, state.open_positions, float(state.net_liq))
        if headroom < 0:
            sector_score = 1.0   # Already over sector limit
        elif headroom < 10:
            sector_score = 0.5   # Sector getting full
        else:
            sector_score = 0.0   # Plenty of room

        return max(symbol_score, sector_score)

    def _regime_fit_score(self, proposal: TradeProposal, state: PortfolioState) -> float:
        """Lower score when strategy is well-matched to the current regime."""
        if not state.regime:
            return 0.5  # Unknown regime = moderate risk
        current = state.regime.regime
        ideal_regimes = STRATEGY_REGIME_FIT.get(proposal.strategy_type, set())
        if not ideal_regimes:
            return 0.5
        return 0.0 if current in ideal_regimes else 0.8

    def _ivr_score(self, state: PortfolioState) -> float:
        """Lower score (better entry) when IVR is high."""
        if not state.regime:
            return 0.5
        ivr = state.regime.ivr  # 0-100
        # IVR 75+ = 0.0 (great), IVR 25 = 0.5, IVR <10 = 1.0 (terrible)
        return max(0.0, min((75 - ivr) / 75, 1.0))

    def _portfolio_heat_score(self, proposal: TradeProposal, state: PortfolioState) -> float:
        """Higher score when portfolio is already heavily directional.

        Discourages adding exposure to an already-hot portfolio — one of the
        key lessons from blow-ups where directional risk builds unnoticed.
        """
        net_liq = float(state.net_liq)
        if net_liq <= 0:
            return 0.5
        delta_pct = abs(state.portfolio_delta) * 100 / net_liq
        if delta_pct > DELTA_HEAT_SCORE_HIGH:
            return 0.8
        elif delta_pct > DELTA_HEAT_SCORE_MED:
            return 0.4
        return 0.0

    # ------------------------------------------------------------------
    # In-trade alerts
    # ------------------------------------------------------------------

    def _check_portfolio_heat(self, state: PortfolioState) -> None:
        """Generate portfolio-level heat alerts. Hard stops, not suggestions."""
        net_liq = float(state.net_liq)
        if net_liq <= 0:
            return

        delta_pct = abs(state.portfolio_delta) * 100 / net_liq
        if delta_pct > DELTA_HEAT_ALERT_PCT:
            state.alerts.append(
                f"WARN: Portfolio delta {delta_pct:.1f}% of net liq "
                f"(>{DELTA_HEAT_ALERT_PCT}%) — reduce directional exposure"
            )

        if state.portfolio_theta != 0:
            theta_daily_pct = abs(state.portfolio_theta) / net_liq * 100
            if theta_daily_pct > THETA_HEAT_ALERT_PCT:
                state.alerts.append(
                    f"WARN: Portfolio theta {theta_daily_pct:.2f}%/day "
                    f"(>{THETA_HEAT_ALERT_PCT}%) — premium concentration high"
                )

    def _check_open_positions(self, state: PortfolioState) -> None:
        """Generate adjustment alerts for open positions."""
        from datetime import datetime, date

        today = date.today()

        for pos in state.open_positions:
            symbol = pos.get("symbol", "?")
            strategy = pos.get("strategy_type", pos.get("strategy", "?"))

            # --- 21 DTE roll alert ---
            expiry_str = pos.get("expiration") or pos.get("expiry")
            if expiry_str:
                try:
                    if isinstance(expiry_str, str):
                        exp_date = datetime.strptime(expiry_str[:10], "%Y-%m-%d").date()
                    else:
                        exp_date = expiry_str
                    dte = (exp_date - today).days
                    if dte <= DTE_ROLL_THRESHOLD:
                        state.alerts.append(
                            f"ROLL: {symbol} {strategy} at {dte} DTE — "
                            f"roll or close by {exp_date}"
                        )
                except (ValueError, TypeError):
                    pass

            # --- P&L > 2x credit alert ---
            credit = pos.get("credit", 0) or 0
            current_pnl = pos.get("unrealized_pnl", pos.get("pnl", 0)) or 0
            if credit and current_pnl:
                if abs(current_pnl) > LOSS_MULTIPLIER_CLOSE * abs(credit):
                    state.alerts.append(
                        f"CLOSE: {symbol} {strategy} loss ${abs(current_pnl):.0f} "
                        f"exceeds {LOSS_MULTIPLIER_CLOSE:.0f}x credit ${abs(credit):.0f}"
                    )

            # --- Delta breach alert ---
            position_delta = pos.get("delta", pos.get("position_delta", None))
            if position_delta is not None:
                try:
                    if abs(float(position_delta)) > DELTA_BREACH_THRESHOLD:
                        direction = "long" if float(position_delta) > 0 else "short"
                        state.alerts.append(
                            f"ADJUST: {symbol} {strategy} delta {float(position_delta):+.2f} "
                            f"({direction} breach > {DELTA_BREACH_THRESHOLD}) — "
                            f"roll untested side"
                        )
                except (ValueError, TypeError):
                    pass

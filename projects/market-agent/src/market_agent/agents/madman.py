"""Madman Scout agent — asymmetric opportunity scanner.

Scans for high-convexity setups where the risk/reward is extremely asymmetric:
small premium at risk, large potential payoff. These are NOT premium-selling
setups — they are cheap long volatility / tail-risk plays.

Position sizing: 0.10-0.20% per trade (hard cap), max 5% aggregate.
Setting is_madman=True on proposals triggers special handling throughout
the pipeline (Kelly sizing, separate display in CLI, risk monitor bypass).

Triggers scanned:
  1. Earnings calendars  — far OTM calendars 5-15 days before earnings
  2. VIX call spreads    — cheap vol protection before FOMC in low-vol regime
  3. Back ratios         — net-credit put back ratios in high-vol regime
  4. 0DTE gamma plays    — same-day expiry (flagged only, not auto-proposed)

Reads:  state.regime, state.scan_symbols
Writes: state.proposals (appends madman proposals), state.alerts
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from .state import PortfolioState, TradeProposal, VolRegime

logger = logging.getLogger(__name__)

MADMAN_POSITION_PCT = 0.15   # 0.10-0.20% of portfolio
MADMAN_MAX_TOTAL_PCT = 5.0   # Hard cap on aggregate madman allocation
MAX_MADMAN_PROPOSALS = 3     # Maximum new madman proposals per run

# FOMC meeting dates — update quarterly; used for VIX call spread trigger
# These are approximate 2026 dates (update as needed from federalreserve.gov)
FOMC_DATES_2026 = [
    date(2026, 1, 29),
    date(2026, 3, 19),
    date(2026, 4, 30),
    date(2026, 6, 18),
    date(2026, 7, 30),
    date(2026, 9, 17),
    date(2026, 10, 29),
    date(2026, 12, 10),
]


def _days_to_next_fomc(today: date) -> int | None:
    """Return days to the next FOMC meeting, or None if none found."""
    future = [d for d in FOMC_DATES_2026 if d >= today]
    if not future:
        return None
    return (future[0] - today).days


def _get_next_earnings(symbol: str) -> date | None:
    """Return next earnings date for symbol via yfinance fundamentals."""
    try:
        from ..data.fetcher import get_fundamentals
        info = get_fundamentals(symbol)
        if info and info.next_earnings:
            dt = info.next_earnings
            if hasattr(dt, "date"):
                return dt.date()
            if isinstance(dt, date):
                return dt
    except Exception:
        pass
    return None


class MadmanScout:
    """Scans for asymmetric, high-convexity trade setups.

    Reads:  state.regime, state.scan_symbols
    Writes: state.proposals (appends), state.alerts
    """

    def run(self, state: PortfolioState) -> PortfolioState:
        """Run all madman scans and append qualified proposals."""
        if not state.regime:
            return state

        today = date.today()
        regime = state.regime.regime
        vix = state.regime.vix_level
        symbols = state.scan_symbols or []
        new_proposals: list[TradeProposal] = []

        # --- Scan 1: Earnings calendars ---
        for symbol in symbols:
            if len(new_proposals) >= MAX_MADMAN_PROPOSALS:
                break
            proposal = self._check_earnings_calendar(symbol, today, regime)
            if proposal:
                new_proposals.append(proposal)
                logger.info("Madman: earnings calendar opportunity on %s", symbol)

        # --- Scan 2: VIX call spread before FOMC ---
        if len(new_proposals) < MAX_MADMAN_PROPOSALS:
            proposal = self._check_vix_call_spread(today, vix, regime)
            if proposal:
                new_proposals.append(proposal)
                logger.info("Madman: VIX call spread opportunity (FOMC in range)")

        # --- Scan 3: Back ratios in high vol ---
        if len(new_proposals) < MAX_MADMAN_PROPOSALS and regime == VolRegime.HIGH:
            for symbol in symbols:
                if len(new_proposals) >= MAX_MADMAN_PROPOSALS:
                    break
                proposal = self._check_back_ratio(symbol, today, regime)
                if proposal:
                    new_proposals.append(proposal)
                    logger.info("Madman: back ratio opportunity on %s (high vol)", symbol)

        # --- Scan 4: 0DTE alert (flag only, no proposal) ---
        self._flag_zero_dte(today, state)

        # Enforce aggregate madman allocation cap
        existing_madman_pct = sum(
            p.position_size_pct for p in state.proposals if p.is_madman
        )
        for p in new_proposals:
            if existing_madman_pct + p.position_size_pct > MADMAN_MAX_TOTAL_PCT:
                state.alerts.append(
                    f"INFO: Madman cap reached ({MADMAN_MAX_TOTAL_PCT}%) — "
                    f"skipping {p.symbol} {p.strategy_type}"
                )
                break
            state.proposals.append(p)
            existing_madman_pct += p.position_size_pct

        logger.info("Madman Scout: %d new proposals added", len(new_proposals))
        return state

    # ------------------------------------------------------------------
    # Individual scanners
    # ------------------------------------------------------------------

    def _check_earnings_calendar(
        self, symbol: str, today: date, regime: VolRegime
    ) -> TradeProposal | None:
        """Generate far-OTM calendar if earnings is 5-15 days away.

        Earnings catalysts inflate near-term IV while longer-dated IV stays
        elevated — calendars profit from this term-structure compression.
        """
        earnings_date = _get_next_earnings(symbol)
        if not earnings_date:
            return None

        days_to_earnings = (earnings_date - today).days
        if not (5 <= days_to_earnings <= 15):
            return None

        # Build the proposal without resolving full legs (architect will resolve)
        return TradeProposal(
            symbol=symbol,
            strategy_type="calendar",
            legs=[],  # Will be resolved if user approves
            regime=regime,
            position_size_pct=MADMAN_POSITION_PCT,
            profit_target_pct=100.0,  # Target doubling the premium
            max_dte=days_to_earnings + 5,
            rationale=[
                f"Earnings in {days_to_earnings}d ({earnings_date}) — front-month IV crush play",
                "Calendar: sell front-month ATM, buy post-earnings expiry",
                f"Madman allocation: {MADMAN_POSITION_PCT}% of portfolio",
            ],
            is_madman=True,
        )

    def _check_vix_call_spread(
        self, today: date, vix: float, regime: VolRegime
    ) -> TradeProposal | None:
        """Generate VIX call spread when VIX is low and FOMC is near.

        Cheap tail-risk protection: buy OTM VIX call spread before FOMC
        in low-vol environment where VIX calls are cheap.
        """
        if regime != VolRegime.LOW:
            return None  # Only worth buying VIX protection when vol is cheap
        if vix >= 16:
            return None  # Too expensive already

        days_to_fomc = _days_to_next_fomc(today)
        if days_to_fomc is None or not (7 <= days_to_fomc <= 21):
            return None

        return TradeProposal(
            symbol="VIX",
            strategy_type="vertical_spread",  # Buy call spread
            legs=[],
            regime=regime,
            position_size_pct=MADMAN_POSITION_PCT,
            profit_target_pct=200.0,  # 2x on the spread
            max_dte=days_to_fomc + 3,
            rationale=[
                f"FOMC in {days_to_fomc}d — VIX call spread (tail-risk hedge)",
                f"VIX at {vix:.1f} (LOW regime) — call spread is cheap",
                "Buy OTM VIX call spread: 20/25 or 25/30 depending on term structure",
                f"Madman allocation: {MADMAN_POSITION_PCT}% of portfolio",
            ],
            is_madman=True,
        )

    def _check_back_ratio(
        self, symbol: str, today: date, regime: VolRegime
    ) -> TradeProposal | None:
        """Generate put back ratio opportunity in high-vol environment.

        In high vol, OTM puts are expensive. A net-credit back ratio
        (sell 1 ATM put, buy 2 OTM puts) collects credit while providing
        convex payoff on a large down move.
        """
        try:
            from ..analysis.options import resolve_strategy, options_summary
            from ..data.fetcher import get_bars

            # Quick check: does this symbol have adequate options liquidity?
            bars = get_bars(symbol, period="1mo", interval="1d")
            if not bars:
                return None

            underlying_price = Decimal(str(float(bars[-1].close)))
            structure = resolve_strategy(
                symbol=symbol,
                strategy_type="back_ratio",
                underlying_price=underlying_price,
                delta_target=0.20,
                dte_range=(30, 60),
            )
            if not structure:
                return None

            # Only recommend if back ratio results in a credit
            if not structure.get("credit") or structure["credit"] <= 0:
                return None

            return TradeProposal(
                symbol=symbol,
                strategy_type="back_ratio",
                legs=structure.get("legs", []),
                regime=regime,
                position_size_pct=MADMAN_POSITION_PCT,
                profit_target_pct=200.0,
                max_dte=60,
                rationale=[
                    f"High-vol back ratio at net credit ${structure['credit']:.2f}",
                    "Sell 1 ATM put, buy 2 OTM puts — convex payoff on large move",
                    f"Madman allocation: {MADMAN_POSITION_PCT}% of portfolio",
                ],
                credit=structure.get("credit"),
                max_loss=structure.get("max_loss"),
                breakevens=structure.get("breakevens", []),
                is_madman=True,
            )
        except Exception:
            logger.exception("Error checking back ratio for %s", symbol)
            return None

    def _flag_zero_dte(self, today: date, state: PortfolioState) -> None:
        """Alert on 0DTE gamma play conditions (informational, no proposal)."""
        # 0DTE is most active on Mon/Wed/Fri for SPY; Tue/Thu for QQQ
        weekday = today.weekday()  # 0=Mon, 4=Fri

        if weekday not in (0, 2, 4):  # Not Mon/Wed/Fri
            return

        if state.regime and state.regime.regime == VolRegime.HIGH:
            state.alerts.append(
                f"INFO: 0DTE opportunity — {today.strftime('%A')} "
                f"(VIX {state.regime.vix_level:.1f}, HIGH regime). "
                "Consider SPY 0DTE iron condor at market open."
            )

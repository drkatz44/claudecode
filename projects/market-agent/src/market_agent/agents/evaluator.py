"""Trade Evaluator agent.

For each proposal from the Architect, runs a historical backtest via
options_engine.py and attaches eval_stats + Kelly-adjusted position sizing.

Reads:  state.proposals
Writes: proposal.eval_stats, proposal.position_size_pct, state.alerts
"""

import logging

from ..analysis.kelly import expected_value, position_size_pct
from ..backtest.options_engine import OptionsBacktestResult, backtest_structure
from .state import PortfolioState, TradeProposal

logger = logging.getLogger(__name__)

MIN_SAMPLE_SIZE = 10       # Minimum trades for statistical significance
LOW_WIN_RATE_THRESHOLD = 40.0  # Warn if win rate below this
LOOKBACK_DAYS = 252        # ~1 year of trading days


class TradeEvaluator:
    """Runs historical option structure backtests for each proposal.

    Reads:  state.proposals
    Writes: proposal.eval_stats, proposal.position_size_pct, state.alerts

    Backend priority (first available wins):
      1. TastytradeBacktester — real fills via tastytrade backtesting API
         (requires tastytrade_token in config.yaml)
      2. YFinanceOptionsProvider — proxy via theta decay + price moves

    NOTE: This agent is slow. Enable with `--eval` flag in agent_pipeline.py.
    """

    def __init__(
        self,
        lookback_days: int = LOOKBACK_DAYS,
        min_sample_size: int = MIN_SAMPLE_SIZE,
        provider=None,
        backtester=None,
    ):
        self.lookback_days = lookback_days
        self.min_sample_size = min_sample_size
        self.provider = provider    # OptionsDataProvider (yfinance / theta)
        self.backtester = backtester  # TastytradeBacktester or None

    def run(self, state: PortfolioState) -> PortfolioState:
        """Evaluate each proposal with historical backtest data."""
        if not state.proposals:
            return state

        # Resolve backtester (tastytrade API — real fills)
        backtester = self.backtester
        if backtester is None:
            from ..data.tasty_backtest import get_backtester
            backtester = get_backtester()

        # Resolve chain provider (yfinance proxy fallback)
        provider = self.provider
        if provider is None:
            from ..data.theta import get_provider
            provider = get_provider()

        backend = "TastytradeBacktester" if backtester else type(provider).__name__
        logger.info("Evaluator backend: %s", backend)

        for proposal in state.proposals:
            try:
                result = self._evaluate_proposal(proposal, backtester, provider)
                self._attach_stats(proposal, result, state)
            except Exception:
                logger.exception("Evaluator error for %s %s", proposal.symbol, proposal.strategy_type)

        logger.info("Evaluator: processed %d proposals", len(state.proposals))
        return state

    def _evaluate_proposal(
        self, proposal: TradeProposal, backtester, provider
    ) -> OptionsBacktestResult:
        """Run backtest for a single proposal, preferring tastytrade API."""
        dte_max = proposal.max_dte
        dte_min = max(dte_max - 15, 21)

        if backtester is not None:
            return backtester.run_backtest(
                symbol=proposal.symbol,
                strategy_type=proposal.strategy_type,
                delta_target=0.16,
                dte_range=(dte_min, dte_max),
                lookback_days=self.lookback_days,
                profit_target_pct=proposal.profit_target_pct,
                stop_loss_pct=200.0,
                max_dte_exit=21,
            )

        return backtest_structure(
            symbol=proposal.symbol,
            strategy_type=proposal.strategy_type,
            delta_target=0.16,
            dte_range=(dte_min, dte_max),
            lookback_days=self.lookback_days,
            profit_target_pct=proposal.profit_target_pct,
            stop_loss_pct=200.0,
            provider=provider,
        )

    def _attach_stats(
        self,
        proposal: TradeProposal,
        result: OptionsBacktestResult,
        state: PortfolioState,
    ) -> None:
        """Attach eval_stats to proposal and apply Kelly position sizing."""
        if result.sample_size < self.min_sample_size:
            proposal.eval_stats = {
                "win_rate": None,
                "avg_pnl": None,
                "avg_dit": None,
                "sample_size": result.sample_size,
                "sharpe": None,
                "note": f"Insufficient data ({result.sample_size} trades < {self.min_sample_size} min)",
                "provider": result.provider_type,
            }
            return

        proposal.eval_stats = {
            "win_rate": result.win_rate,
            "avg_pnl": result.avg_pnl,
            "avg_dit": result.avg_dit,
            "sample_size": result.sample_size,
            "sharpe": result.sharpe,
            "max_mae": result.max_adverse_excursion,
            "provider": result.provider_type,
        }

        # Alert on poor historical win rate
        if result.win_rate < LOW_WIN_RATE_THRESHOLD:
            state.alerts.append(
                f"WARN: {proposal.symbol} {proposal.strategy_type} "
                f"win_rate={result.win_rate:.0f}% below {LOW_WIN_RATE_THRESHOLD}% threshold"
            )

        # Alert on negative expected value
        # Assume avg_win = profit_target_pct, avg_loss ~150% (typical managed stop)
        avg_win = proposal.profit_target_pct
        avg_loss = 150.0
        ev = expected_value(result.win_rate, avg_win, avg_loss)
        if ev < 0:
            state.alerts.append(
                f"INFO: {proposal.symbol} {proposal.strategy_type} negative EV "
                f"({ev:.1f}%) — review management rules"
            )

        # Apply Kelly-adjusted position sizing
        new_size = position_size_pct(
            win_rate=result.win_rate,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            default_pct=proposal.position_size_pct,
            min_pct=0.5,
            max_pct=5.0,
            is_madman=proposal.is_madman,
        )
        proposal.position_size_pct = new_size
        logger.debug(
            "%s %s: win_rate=%.0f%% Kelly_size=%.2f%%",
            proposal.symbol, proposal.strategy_type, result.win_rate, new_size,
        )

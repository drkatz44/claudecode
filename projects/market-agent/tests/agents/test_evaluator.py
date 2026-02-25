"""Tests for TradeEvaluator agent."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from market_agent.agents.evaluator import TradeEvaluator, MIN_SAMPLE_SIZE, LOW_WIN_RATE_THRESHOLD
from market_agent.agents.state import PortfolioState, RegimeState, TradeProposal, VolRegime
from market_agent.backtest.options_engine import OptionsBacktestResult, OptionsTrade
from datetime import date, timedelta


def _make_state(**kwargs) -> PortfolioState:
    return PortfolioState(
        net_liq=Decimal("75000"),
        buying_power=Decimal("75000"),
        **kwargs,
    )


def _make_proposal(**kwargs) -> TradeProposal:
    defaults = dict(
        symbol="SPY",
        strategy_type="strangle",
        legs=[],
        regime=VolRegime.NORMAL,
        position_size_pct=2.0,
        rationale=["test"],
    )
    defaults.update(kwargs)
    return TradeProposal(**defaults)


def _make_result(
    win_rate: float = 65.0,
    sample_size: int = 20,
    avg_pnl: float = 25.0,
    avg_dit: float = 18.0,
    sharpe: float = 1.2,
) -> OptionsBacktestResult:
    return OptionsBacktestResult(
        symbol="SPY",
        strategy_type="strangle",
        sample_size=sample_size,
        win_rate=win_rate,
        avg_pnl=avg_pnl,
        avg_dit=avg_dit,
        max_adverse_excursion=-40.0,
        sharpe=sharpe,
        provider_type="yfinance",
    )


class TestTradeEvaluatorRun:
    def test_empty_proposals_returns_state(self):
        state = _make_state()
        evaluator = TradeEvaluator(provider=MagicMock())
        result = evaluator.run(state)
        assert result is state

    @patch("market_agent.agents.evaluator.backtest_structure")
    def test_attaches_eval_stats(self, mock_bt):
        mock_bt.return_value = _make_result(win_rate=65.0, sample_size=20)
        proposal = _make_proposal()
        state = _make_state(proposals=[proposal])
        evaluator = TradeEvaluator(provider=MagicMock())
        evaluator.run(state)

        assert proposal.eval_stats is not None
        assert "win_rate" in proposal.eval_stats
        assert proposal.eval_stats["win_rate"] == pytest.approx(65.0)

    @patch("market_agent.agents.evaluator.backtest_structure")
    def test_insufficient_sample_sets_none_stats(self, mock_bt):
        mock_bt.return_value = _make_result(sample_size=3, win_rate=70.0)
        proposal = _make_proposal()
        state = _make_state(proposals=[proposal])
        evaluator = TradeEvaluator(min_sample_size=10, provider=MagicMock())
        evaluator.run(state)

        assert proposal.eval_stats is not None
        assert proposal.eval_stats["win_rate"] is None
        assert "note" in proposal.eval_stats

    @patch("market_agent.agents.evaluator.backtest_structure")
    def test_low_win_rate_adds_alert(self, mock_bt):
        mock_bt.return_value = _make_result(win_rate=30.0, sample_size=15)
        proposal = _make_proposal()
        state = _make_state(proposals=[proposal])
        evaluator = TradeEvaluator(provider=MagicMock())
        evaluator.run(state)

        assert any("win_rate" in a and "30" in a for a in state.alerts)

    @patch("market_agent.agents.evaluator.backtest_structure")
    def test_good_win_rate_no_alert(self, mock_bt):
        mock_bt.return_value = _make_result(win_rate=70.0, sample_size=20)
        proposal = _make_proposal()
        state = _make_state(proposals=[proposal])
        evaluator = TradeEvaluator(provider=MagicMock())
        evaluator.run(state)

        warn_alerts = [a for a in state.alerts if "win_rate" in a]
        assert len(warn_alerts) == 0

    @patch("market_agent.agents.evaluator.backtest_structure")
    def test_applies_kelly_size_adjustment(self, mock_bt):
        # Very high win rate → Kelly multiplier should increase size
        mock_bt.return_value = _make_result(win_rate=90.0, sample_size=20, avg_pnl=50.0)
        proposal = _make_proposal(position_size_pct=2.0)
        original_size = proposal.position_size_pct
        state = _make_state(proposals=[proposal])
        evaluator = TradeEvaluator(provider=MagicMock())
        evaluator.run(state)

        # Kelly multiplier 1.5x → 3.0% (still within max)
        assert proposal.position_size_pct >= original_size * 1.4  # Allow small float variance

    @patch("market_agent.agents.evaluator.backtest_structure")
    def test_madman_proposal_capped_at_015(self, mock_bt):
        mock_bt.return_value = _make_result(win_rate=90.0, sample_size=20)
        proposal = _make_proposal(position_size_pct=0.15, is_madman=True)
        state = _make_state(proposals=[proposal])
        evaluator = TradeEvaluator(provider=MagicMock())
        evaluator.run(state)

        assert proposal.position_size_pct == pytest.approx(0.15)

    @patch("market_agent.agents.evaluator.backtest_structure")
    def test_negative_ev_adds_info_alert(self, mock_bt):
        # Very low win rate with worse payoff → negative EV
        mock_bt.return_value = _make_result(win_rate=20.0, sample_size=15)
        proposal = _make_proposal()
        state = _make_state(proposals=[proposal])
        evaluator = TradeEvaluator(provider=MagicMock())
        evaluator.run(state)

        assert any("negative EV" in a or "EV" in a for a in state.alerts)

    @patch("market_agent.agents.evaluator.backtest_structure")
    def test_exception_in_backtest_does_not_crash(self, mock_bt):
        mock_bt.side_effect = RuntimeError("yfinance unavailable")
        proposal = _make_proposal()
        state = _make_state(proposals=[proposal])
        evaluator = TradeEvaluator(provider=MagicMock())
        # Should not raise
        result = evaluator.run(state)
        assert result is state

    @patch("market_agent.agents.evaluator.backtest_structure")
    def test_multiple_proposals_all_evaluated(self, mock_bt):
        mock_bt.return_value = _make_result(win_rate=65.0, sample_size=20)
        proposals = [_make_proposal(symbol=s) for s in ["SPY", "QQQ", "GLD"]]
        state = _make_state(proposals=proposals)
        evaluator = TradeEvaluator(provider=MagicMock())
        evaluator.run(state)

        assert mock_bt.call_count == 3
        assert all(p.eval_stats is not None for p in proposals)

    @patch("market_agent.agents.evaluator.backtest_structure")
    def test_eval_stats_includes_provider_key(self, mock_bt):
        mock_bt.return_value = _make_result(sample_size=15)
        proposal = _make_proposal()
        state = _make_state(proposals=[proposal])
        evaluator = TradeEvaluator(provider=MagicMock())
        evaluator.run(state)

        assert "provider" in proposal.eval_stats

    @patch("market_agent.agents.evaluator.backtest_structure")
    def test_respects_min_pct_floor(self, mock_bt):
        # Very weak edge → 0.5x multiplier → default=2.0 → 1.0%, min=0.5% — check floor
        mock_bt.return_value = _make_result(win_rate=30.0, sample_size=15)
        proposal = _make_proposal(position_size_pct=0.3)  # Below min
        state = _make_state(proposals=[proposal])
        evaluator = TradeEvaluator(provider=MagicMock())
        evaluator.run(state)

        assert proposal.position_size_pct >= 0.5


class TestTradeEvaluatorConfig:
    def test_default_lookback(self):
        ev = TradeEvaluator()
        assert ev.lookback_days == 252

    def test_custom_lookback(self):
        ev = TradeEvaluator(lookback_days=126)
        assert ev.lookback_days == 126

    def test_default_min_sample(self):
        ev = TradeEvaluator()
        assert ev.min_sample_size == MIN_SAMPLE_SIZE

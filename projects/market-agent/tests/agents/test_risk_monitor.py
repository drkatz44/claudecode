"""Tests for RiskMonitor agent."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from market_agent.agents.risk_monitor import (
    RiskMonitor,
    STRATEGY_REGIME_FIT,
    DTE_ROLL_THRESHOLD,
    DELTA_BREACH_THRESHOLD,
    DELTA_HEAT_ALERT_PCT,
    DELTA_HEAT_SCORE_HIGH,
    DELTA_HEAT_SCORE_MED,
    LOSS_MULTIPLIER_CLOSE,
    THETA_HEAT_ALERT_PCT,
)
from market_agent.agents.state import PortfolioState, RegimeState, TradeProposal, VolRegime


def _make_regime(
    regime: VolRegime = VolRegime.NORMAL,
    vix: float = 18.0,
    ivr: float = 50.0,
) -> RegimeState:
    return RegimeState(
        vix_level=vix,
        vix_5d_change=0.0,
        regime=regime,
        ivr=ivr,
        ivx=18.0,
    )


def _make_state(
    regime: RegimeState | None = None,
    proposals: list | None = None,
    open_positions: list | None = None,
    net_liq: float = 75000,
    buying_power: float = 75000,
) -> PortfolioState:
    return PortfolioState(
        net_liq=Decimal(str(net_liq)),
        buying_power=Decimal(str(buying_power)),
        regime=regime or _make_regime(),
        proposals=proposals or [],
        open_positions=open_positions or [],
    )


def _make_proposal(
    symbol: str = "SPY",
    strategy_type: str = "strangle",
    regime: VolRegime = VolRegime.NORMAL,
    position_size_pct: float = 2.0,
    **kwargs,
) -> TradeProposal:
    return TradeProposal(
        symbol=symbol,
        strategy_type=strategy_type,
        legs=[],
        regime=regime,
        position_size_pct=position_size_pct,
        rationale=["test"],
        **kwargs,
    )


class TestRiskMonitorRun:
    def test_run_returns_state(self):
        state = _make_state()
        monitor = RiskMonitor()
        result = monitor.run(state)
        assert result is state

    def test_attaches_risk_score_to_proposals(self):
        proposal = _make_proposal()
        state = _make_state(proposals=[proposal])
        RiskMonitor().run(state)
        assert 0.0 <= proposal.risk_score <= 1.0

    def test_risk_score_in_bounds_always(self):
        monitor = RiskMonitor()
        for regime in [VolRegime.LOW, VolRegime.NORMAL, VolRegime.HIGH]:
            for strategy in list(STRATEGY_REGIME_FIT.keys()):
                proposal = _make_proposal(strategy_type=strategy, regime=regime)
                state = _make_state(regime=_make_regime(regime=regime))
                state.proposals = [proposal]
                monitor.run(state)
                assert 0.0 <= proposal.risk_score <= 1.0, \
                    f"risk_score out of bounds for {strategy}/{regime}"


class TestBpImpactScore:
    def test_large_position_higher_score(self):
        monitor = RiskMonitor()
        small = _make_proposal(position_size_pct=0.5)
        large = _make_proposal(position_size_pct=4.0)
        state = _make_state(net_liq=75000, buying_power=75000)

        small_score = monitor._bp_impact_score(small, state)
        large_score = monitor._bp_impact_score(large, state)
        assert large_score > small_score

    def test_zero_buying_power_returns_one(self):
        monitor = RiskMonitor()
        proposal = _make_proposal()
        state = _make_state(buying_power=0)
        score = monitor._bp_impact_score(proposal, state)
        assert score == 1.0

    def test_small_position_low_score(self):
        monitor = RiskMonitor()
        proposal = _make_proposal(position_size_pct=0.1)
        state = _make_state(net_liq=75000, buying_power=75000)
        score = monitor._bp_impact_score(proposal, state)
        assert score < 0.2


class TestCorrelationScore:
    def test_no_open_positions_zero_score(self):
        monitor = RiskMonitor()
        proposal = _make_proposal(symbol="SPY")
        state = _make_state(open_positions=[])
        assert monitor._correlation_score(proposal, state) == 0.0

    def test_one_same_underlying_half(self):
        monitor = RiskMonitor()
        proposal = _make_proposal(symbol="SPY")
        state = _make_state(open_positions=[{"symbol": "SPY"}])
        assert monitor._correlation_score(proposal, state) == pytest.approx(0.5)

    def test_two_same_underlying_max(self):
        monitor = RiskMonitor()
        proposal = _make_proposal(symbol="SPY")
        state = _make_state(open_positions=[{"symbol": "SPY"}, {"symbol": "SPY"}])
        assert monitor._correlation_score(proposal, state) == pytest.approx(1.0)

    def test_different_underlying_zero(self):
        monitor = RiskMonitor()
        proposal = _make_proposal(symbol="SPY")
        state = _make_state(open_positions=[{"symbol": "QQQ"}, {"symbol": "GLD"}])
        assert monitor._correlation_score(proposal, state) == 0.0

    def test_case_insensitive(self):
        monitor = RiskMonitor()
        proposal = _make_proposal(symbol="spy")
        state = _make_state(open_positions=[{"symbol": "SPY"}])
        assert monitor._correlation_score(proposal, state) > 0


class TestRegimeFitScore:
    def test_aligned_strategy_low_score(self):
        monitor = RiskMonitor()
        # strangle fits NORMAL regime
        proposal = _make_proposal(strategy_type="strangle")
        state = _make_state(regime=_make_regime(regime=VolRegime.NORMAL))
        score = monitor._regime_fit_score(proposal, state)
        assert score == 0.0

    def test_misaligned_strategy_high_score(self):
        monitor = RiskMonitor()
        # calendar fits LOW, but we're in HIGH regime
        proposal = _make_proposal(strategy_type="calendar")
        state = _make_state(regime=_make_regime(regime=VolRegime.HIGH))
        score = monitor._regime_fit_score(proposal, state)
        assert score == pytest.approx(0.8)

    def test_no_regime_returns_moderate(self):
        monitor = RiskMonitor()
        proposal = _make_proposal()
        state = _make_state()
        state.regime = None
        score = monitor._regime_fit_score(proposal, state)
        assert score == pytest.approx(0.5)

    def test_unknown_strategy_returns_moderate(self):
        monitor = RiskMonitor()
        proposal = _make_proposal(strategy_type="unknown_xyz")
        state = _make_state(regime=_make_regime(regime=VolRegime.NORMAL))
        score = monitor._regime_fit_score(proposal, state)
        assert score == pytest.approx(0.5)


class TestIvrScore:
    def test_high_ivr_low_risk_score(self):
        monitor = RiskMonitor()
        state = _make_state(regime=_make_regime(ivr=80.0))
        score = monitor._ivr_score(state)
        assert score == pytest.approx(0.0)  # IVR 75+ → 0.0

    def test_low_ivr_high_risk_score(self):
        monitor = RiskMonitor()
        state = _make_state(regime=_make_regime(ivr=0.0))
        score = monitor._ivr_score(state)
        assert score == pytest.approx(1.0)

    def test_medium_ivr_moderate_score(self):
        monitor = RiskMonitor()
        state = _make_state(regime=_make_regime(ivr=37.5))
        score = monitor._ivr_score(state)
        assert 0.4 < score < 0.6

    def test_no_regime_moderate_score(self):
        monitor = RiskMonitor()
        state = _make_state()
        state.regime = None
        assert monitor._ivr_score(state) == pytest.approx(0.5)


class TestInTradeAlerts:
    def test_21_dte_generates_roll_alert(self):
        today = date.today()
        exp = today + timedelta(days=15)  # Below 21 DTE threshold
        state = _make_state(open_positions=[{
            "symbol": "SPY", "strategy_type": "strangle",
            "expiration": exp.strftime("%Y-%m-%d"),
        }])
        RiskMonitor().run(state)
        assert any("ROLL" in a and "SPY" in a for a in state.alerts)

    def test_far_dte_no_roll_alert(self):
        today = date.today()
        exp = today + timedelta(days=45)  # Above threshold
        state = _make_state(open_positions=[{
            "symbol": "SPY", "strategy_type": "strangle",
            "expiration": exp.strftime("%Y-%m-%d"),
        }])
        RiskMonitor().run(state)
        assert not any("ROLL" in a for a in state.alerts)

    def test_2x_credit_loss_generates_close_alert(self):
        state = _make_state(open_positions=[{
            "symbol": "AAPL", "strategy": "short_put",
            "credit": 2.0, "unrealized_pnl": -5.0,  # > 2x credit
        }])
        RiskMonitor().run(state)
        assert any("CLOSE" in a and "AAPL" in a for a in state.alerts)

    def test_small_loss_no_close_alert(self):
        state = _make_state(open_positions=[{
            "symbol": "AAPL", "strategy": "short_put",
            "credit": 2.0, "unrealized_pnl": -1.0,  # < 2x credit
        }])
        RiskMonitor().run(state)
        assert not any("CLOSE" in a for a in state.alerts)

    def test_delta_breach_generates_adjust_alert(self):
        state = _make_state(open_positions=[{
            "symbol": "SPY", "strategy_type": "strangle",
            "delta": 0.45,  # Above 0.30 threshold
        }])
        RiskMonitor().run(state)
        assert any("ADJUST" in a and "SPY" in a for a in state.alerts)

    def test_small_delta_no_adjust_alert(self):
        state = _make_state(open_positions=[{
            "symbol": "SPY", "strategy_type": "strangle",
            "delta": 0.10,  # Below threshold
        }])
        RiskMonitor().run(state)
        assert not any("ADJUST" in a for a in state.alerts)

    def test_negative_delta_breach_also_alerts(self):
        state = _make_state(open_positions=[{
            "symbol": "SPY", "strategy_type": "strangle",
            "delta": -0.40,  # Abs value above threshold
        }])
        RiskMonitor().run(state)
        assert any("ADJUST" in a for a in state.alerts)

    def test_missing_expiry_no_crash(self):
        state = _make_state(open_positions=[{
            "symbol": "SPY", "strategy_type": "strangle",
            # No expiration field
        }])
        # Should not raise
        RiskMonitor().run(state)

    def test_malformed_expiry_no_crash(self):
        state = _make_state(open_positions=[{
            "symbol": "SPY", "strategy_type": "strangle",
            "expiration": "not-a-date",
        }])
        RiskMonitor().run(state)

    def test_empty_open_positions_no_alerts(self):
        state = _make_state(proposals=[_make_proposal()])
        initial_alerts = list(state.alerts)
        RiskMonitor().run(state)
        new_alerts = [a for a in state.alerts if a not in initial_alerts]
        assert not any("ROLL" in a or "CLOSE" in a or "ADJUST" in a for a in new_alerts)


class TestSectorCorrelationScore:
    def test_empty_positions_zero_score(self):
        monitor = RiskMonitor()
        proposal = _make_proposal(symbol="SPY")
        state = _make_state(open_positions=[])
        assert monitor._correlation_score(proposal, state) == 0.0

    def test_same_symbol_raises_score(self):
        monitor = RiskMonitor()
        proposal = _make_proposal(symbol="SPY")
        state = _make_state(open_positions=[{"symbol": "SPY"}])
        score = monitor._correlation_score(proposal, state)
        assert score == pytest.approx(0.5)

    def test_different_symbol_same_sector_tight_returns_sector_score(self):
        # SPY and IWM are both "broad" sector
        # Fill broad sector to near cap so headroom < 10
        monitor = RiskMonitor()
        proposal = _make_proposal(symbol="SPY")
        positions = [{"symbol": "IWM", "position_size_pct": 22.0}]  # 22% used → 8% headroom
        state = _make_state(open_positions=positions)
        score = monitor._correlation_score(proposal, state)
        assert score == pytest.approx(0.5)  # headroom < 10 → sector_score = 0.5

    def test_sector_over_limit_returns_one(self):
        monitor = RiskMonitor()
        proposal = _make_proposal(symbol="SPY")
        # 35% in broad sector → over the 30% limit → headroom < 0
        positions = [{"symbol": "IWM", "position_size_pct": 35.0}]
        state = _make_state(open_positions=positions)
        score = monitor._correlation_score(proposal, state)
        assert score == pytest.approx(1.0)

    def test_different_sector_zero_score(self):
        monitor = RiskMonitor()
        proposal = _make_proposal(symbol="SPY")  # broad
        # QQQ=tech, GLD=metals — neither broad
        state = _make_state(open_positions=[{"symbol": "QQQ"}, {"symbol": "GLD"}])
        assert monitor._correlation_score(proposal, state) == 0.0


class TestPortfolioHeatScore:
    def test_cool_portfolio_zero_score(self):
        monitor = RiskMonitor()
        proposal = _make_proposal()
        state = _make_state()
        state.portfolio_delta = 0.0
        score = monitor._portfolio_heat_score(proposal, state)
        assert score == 0.0

    def test_moderate_delta_medium_score(self):
        monitor = RiskMonitor()
        proposal = _make_proposal()
        state = _make_state(net_liq=100000)
        # delta_pct = 12000 / 100000 * 100 = 12% — above MED threshold
        state.portfolio_delta = 12000.0
        score = monitor._portfolio_heat_score(proposal, state)
        assert score == pytest.approx(0.4)

    def test_high_delta_high_score(self):
        monitor = RiskMonitor()
        proposal = _make_proposal()
        state = _make_state(net_liq=100000)
        # delta_pct = 25000 / 100000 * 100 = 25% — above HIGH threshold
        state.portfolio_delta = 25000.0
        score = monitor._portfolio_heat_score(proposal, state)
        assert score == pytest.approx(0.8)

    def test_negative_delta_uses_abs_value(self):
        monitor = RiskMonitor()
        proposal = _make_proposal()
        state = _make_state(net_liq=100000)
        state.portfolio_delta = -25000.0  # same magnitude, negative direction
        score = monitor._portfolio_heat_score(proposal, state)
        assert score == pytest.approx(0.8)

    def test_zero_net_liq_returns_moderate(self):
        monitor = RiskMonitor()
        proposal = _make_proposal()
        state = _make_state(net_liq=0)
        score = monitor._portfolio_heat_score(proposal, state)
        assert score == pytest.approx(0.5)


class TestPortfolioHeatAlerts:
    def test_high_delta_generates_alert(self):
        state = _make_state(net_liq=100000)
        state.portfolio_delta = 30000.0  # 30% > 25% threshold
        RiskMonitor().run(state)
        assert any("Portfolio delta" in a and "WARN" in a for a in state.alerts)

    def test_normal_delta_no_alert(self):
        state = _make_state(net_liq=100000)
        state.portfolio_delta = 5000.0  # 5% < 25% threshold
        RiskMonitor().run(state)
        assert not any("Portfolio delta" in a for a in state.alerts)

    def test_high_theta_generates_alert(self):
        state = _make_state(net_liq=100000)
        # theta_daily_pct = 1500 / 100000 * 100 = 1.5% > 1.0% threshold
        state.portfolio_theta = 1500.0
        RiskMonitor().run(state)
        assert any("theta" in a and "WARN" in a for a in state.alerts)

    def test_normal_theta_no_alert(self):
        state = _make_state(net_liq=100000)
        state.portfolio_theta = 500.0  # 0.5% < 1.0% threshold
        RiskMonitor().run(state)
        assert not any("theta" in a for a in state.alerts)

    def test_zero_theta_no_alert(self):
        state = _make_state(net_liq=100000)
        state.portfolio_theta = 0.0
        RiskMonitor().run(state)
        assert not any("theta" in a for a in state.alerts)


class TestStrategyRegimeFitConstants:
    def test_all_strategies_defined(self):
        expected = {"calendar", "diagonal", "strangle", "iron_condor",
                    "jade_lizard", "back_ratio", "short_put", "bwb", "vertical_spread"}
        assert expected.issubset(set(STRATEGY_REGIME_FIT.keys()))

    def test_regime_values_are_vol_regime(self):
        for strategy, regimes in STRATEGY_REGIME_FIT.items():
            for r in regimes:
                assert isinstance(r, VolRegime), f"{strategy}: {r} is not VolRegime"

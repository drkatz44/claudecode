"""Tests for shared state models."""

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from market_agent.agents.state import (
    PortfolioState,
    RegimeState,
    TradeProposal,
    VolRegime,
)


class TestVolRegime:
    def test_enum_values(self):
        assert VolRegime.LOW == "low"
        assert VolRegime.NORMAL == "normal"
        assert VolRegime.HIGH == "high"

    def test_enum_from_string(self):
        assert VolRegime("low") == VolRegime.LOW
        assert VolRegime("high") == VolRegime.HIGH


class TestRegimeState:
    def test_basic_creation(self):
        rs = RegimeState(
            vix_level=18.5,
            vix_5d_change=-2.3,
            regime=VolRegime.NORMAL,
            ivr=45.0,
            ivx=4.2,
        )
        assert rs.vix_level == 18.5
        assert rs.regime == VolRegime.NORMAL
        assert rs.vix_term_structure == "contango"  # default

    def test_ivr_bounds(self):
        with pytest.raises(ValidationError):
            RegimeState(
                vix_level=20, vix_5d_change=0,
                regime=VolRegime.NORMAL, ivr=150, ivx=5,
            )

    def test_timestamp_auto(self):
        rs = RegimeState(
            vix_level=20, vix_5d_change=0,
            regime=VolRegime.NORMAL, ivr=50, ivx=5,
        )
        assert isinstance(rs.timestamp, datetime)


class TestTradeProposal:
    def test_basic_proposal(self):
        tp = TradeProposal(
            symbol="SPY",
            strategy_type="strangle",
            legs=[
                {"strike": 440, "type": "put", "side": "sell"},
                {"strike": 470, "type": "call", "side": "sell"},
            ],
            regime=VolRegime.NORMAL,
            position_size_pct=2.0,
        )
        assert tp.symbol == "SPY"
        assert tp.profit_target_pct == 50.0  # default
        assert not tp.is_madman

    def test_position_size_bounds(self):
        with pytest.raises(ValidationError):
            TradeProposal(
                symbol="SPY", strategy_type="strangle",
                legs=[], regime=VolRegime.NORMAL,
                position_size_pct=15.0,  # > 10 max
            )

    def test_risk_score_bounds(self):
        with pytest.raises(ValidationError):
            TradeProposal(
                symbol="SPY", strategy_type="strangle",
                legs=[], regime=VolRegime.NORMAL,
                position_size_pct=2.0, risk_score=1.5,
            )

    def test_madman_flag(self):
        tp = TradeProposal(
            symbol="GC", strategy_type="back_ratio",
            legs=[], regime=VolRegime.HIGH,
            position_size_pct=1.0, is_madman=True,
        )
        assert tp.is_madman


class TestPortfolioState:
    def test_defaults(self):
        ps = PortfolioState()
        assert ps.net_liq == Decimal("75000")
        assert ps.bp_usage_pct == 0.0
        assert ps.regime is None
        assert ps.proposals == []
        assert ps.alerts == []

    def test_custom_values(self):
        ps = PortfolioState(
            net_liq=Decimal("100000"),
            buying_power=Decimal("80000"),
            bp_usage_pct=20.0,
            portfolio_delta=-0.5,
            portfolio_theta=150.0,
        )
        assert ps.net_liq == Decimal("100000")
        assert ps.portfolio_theta == 150.0

    def test_with_regime_and_proposals(self):
        ps = PortfolioState()
        ps.regime = RegimeState(
            vix_level=18, vix_5d_change=0,
            regime=VolRegime.NORMAL, ivr=50, ivx=5,
        )
        ps.proposals = [
            TradeProposal(
                symbol="SPY", strategy_type="strangle",
                legs=[], regime=VolRegime.NORMAL,
                position_size_pct=2.0,
            )
        ]
        assert len(ps.proposals) == 1
        assert ps.regime.regime == VolRegime.NORMAL

    def test_scan_symbols(self):
        ps = PortfolioState(scan_symbols=["SPY", "QQQ", "GLD"])
        assert len(ps.scan_symbols) == 3

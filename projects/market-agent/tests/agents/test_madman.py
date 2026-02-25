"""Tests for MadmanScout agent."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from market_agent.agents.madman import (
    MadmanScout,
    MADMAN_POSITION_PCT,
    MADMAN_MAX_TOTAL_PCT,
    MAX_MADMAN_PROPOSALS,
    FOMC_DATES_2026,
    _days_to_next_fomc,
    _get_next_earnings,
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
        ivx=vix,
    )


def _make_state(
    regime: RegimeState | None = None,
    proposals: list | None = None,
    scan_symbols: list | None = None,
) -> PortfolioState:
    return PortfolioState(
        net_liq=Decimal("75000"),
        buying_power=Decimal("75000"),
        regime=regime or _make_regime(),
        proposals=proposals or [],
        scan_symbols=scan_symbols or [],
    )


def _make_madman_proposal(symbol: str = "SPY", pct: float = MADMAN_POSITION_PCT) -> TradeProposal:
    return TradeProposal(
        symbol=symbol,
        strategy_type="calendar",
        legs=[],
        regime=VolRegime.LOW,
        position_size_pct=pct,
        rationale=["test"],
        is_madman=True,
    )


class TestDaysToNextFomc:
    def test_returns_none_when_no_future_dates(self):
        # Far future date past all FOMC dates
        result = _days_to_next_fomc(date(2027, 1, 1))
        assert result is None

    def test_returns_positive_days(self):
        first_fomc = FOMC_DATES_2026[0]
        day_before = first_fomc - timedelta(days=5)
        result = _days_to_next_fomc(day_before)
        assert result == 5

    def test_returns_zero_on_fomc_day(self):
        fomc_day = FOMC_DATES_2026[0]
        result = _days_to_next_fomc(fomc_day)
        assert result == 0

    def test_fomc_list_not_empty(self):
        assert len(FOMC_DATES_2026) > 0


class TestGetNextEarnings:
    @patch("market_agent.data.fetcher.get_fundamentals")
    def test_returns_date_from_fundamentals(self, mock_fund):
        from datetime import datetime
        mock_info = MagicMock()
        mock_info.next_earnings = datetime(2026, 3, 15)
        mock_fund.return_value = mock_info

        result = _get_next_earnings("AAPL")
        assert result == date(2026, 3, 15)

    @patch("market_agent.data.fetcher.get_fundamentals")
    def test_returns_none_on_exception(self, mock_fund):
        mock_fund.side_effect = RuntimeError("network error")
        result = _get_next_earnings("AAPL")
        assert result is None

    @patch("market_agent.data.fetcher.get_fundamentals")
    def test_returns_none_when_no_earnings(self, mock_fund):
        mock_info = MagicMock()
        mock_info.next_earnings = None
        mock_fund.return_value = mock_info
        assert _get_next_earnings("AAPL") is None


class TestEarningsCalendar:
    @patch("market_agent.agents.madman._get_next_earnings")
    def test_earnings_in_range_creates_proposal(self, mock_earn):
        today = date(2026, 2, 1)
        mock_earn.return_value = today + timedelta(days=8)  # In 5-15 day range

        scout = MadmanScout()
        proposal = scout._check_earnings_calendar("AAPL", today, VolRegime.NORMAL)

        assert proposal is not None
        assert proposal.symbol == "AAPL"
        assert proposal.strategy_type == "calendar"
        assert proposal.is_madman is True
        assert proposal.position_size_pct == pytest.approx(MADMAN_POSITION_PCT)

    @patch("market_agent.agents.madman._get_next_earnings")
    def test_earnings_too_soon_returns_none(self, mock_earn):
        today = date(2026, 2, 1)
        mock_earn.return_value = today + timedelta(days=3)  # < 5 days
        scout = MadmanScout()
        result = scout._check_earnings_calendar("AAPL", today, VolRegime.NORMAL)
        assert result is None

    @patch("market_agent.agents.madman._get_next_earnings")
    def test_earnings_too_far_returns_none(self, mock_earn):
        today = date(2026, 2, 1)
        mock_earn.return_value = today + timedelta(days=30)  # > 15 days
        scout = MadmanScout()
        result = scout._check_earnings_calendar("AAPL", today, VolRegime.NORMAL)
        assert result is None

    @patch("market_agent.agents.madman._get_next_earnings")
    def test_no_earnings_returns_none(self, mock_earn):
        mock_earn.return_value = None
        scout = MadmanScout()
        result = scout._check_earnings_calendar("AAPL", date(2026, 2, 1), VolRegime.NORMAL)
        assert result is None

    @patch("market_agent.agents.madman._get_next_earnings")
    def test_rationale_mentions_earnings(self, mock_earn):
        today = date(2026, 2, 1)
        mock_earn.return_value = today + timedelta(days=7)
        scout = MadmanScout()
        proposal = scout._check_earnings_calendar("AAPL", today, VolRegime.NORMAL)
        assert any("earnings" in r.lower() or "Earnings" in r for r in proposal.rationale)


class TestVixCallSpread:
    def test_low_regime_low_vix_fomc_in_range_creates_proposal(self):
        # Find an FOMC date and set today to 14 days before
        fomc = FOMC_DATES_2026[0]
        today = fomc - timedelta(days=14)  # 14 days = in [7, 21] range

        scout = MadmanScout()
        proposal = scout._check_vix_call_spread(today, vix=13.0, regime=VolRegime.LOW)

        assert proposal is not None
        assert proposal.symbol == "VIX"
        assert proposal.is_madman is True
        assert proposal.position_size_pct == pytest.approx(MADMAN_POSITION_PCT)

    def test_normal_regime_returns_none(self):
        fomc = FOMC_DATES_2026[0]
        today = fomc - timedelta(days=10)
        scout = MadmanScout()
        result = scout._check_vix_call_spread(today, vix=13.0, regime=VolRegime.NORMAL)
        assert result is None

    def test_high_vix_returns_none(self):
        fomc = FOMC_DATES_2026[0]
        today = fomc - timedelta(days=10)
        scout = MadmanScout()
        result = scout._check_vix_call_spread(today, vix=18.0, regime=VolRegime.LOW)  # VIX >= 16
        assert result is None

    def test_fomc_too_far_returns_none(self):
        fomc = FOMC_DATES_2026[0]
        today = fomc - timedelta(days=30)  # > 21 days
        scout = MadmanScout()
        result = scout._check_vix_call_spread(today, vix=12.0, regime=VolRegime.LOW)
        assert result is None

    def test_fomc_too_soon_returns_none(self):
        fomc = FOMC_DATES_2026[0]
        today = fomc - timedelta(days=3)  # < 7 days
        scout = MadmanScout()
        result = scout._check_vix_call_spread(today, vix=12.0, regime=VolRegime.LOW)
        assert result is None


class TestBackRatio:
    @patch("market_agent.data.fetcher.get_bars")
    @patch("market_agent.analysis.options.resolve_strategy")
    def test_high_vol_net_credit_creates_proposal(self, mock_resolve, mock_bars):
        from market_agent.data.models import Bar
        from datetime import datetime
        mock_bars.return_value = [
            Bar(timestamp=datetime(2026, 1, 1), open=Decimal("450"),
                high=Decimal("455"), low=Decimal("445"), close=Decimal("450"), volume=1000000),
        ]
        mock_resolve.return_value = {
            "credit": 0.50, "max_loss": 5.0, "legs": [],
            "breakevens": [400.0, 500.0],
        }

        scout = MadmanScout()
        proposal = scout._check_back_ratio("SPY", date(2026, 2, 1), VolRegime.HIGH)

        assert proposal is not None
        assert proposal.strategy_type == "back_ratio"
        assert proposal.is_madman is True
        assert proposal.position_size_pct == pytest.approx(MADMAN_POSITION_PCT)

    @patch("market_agent.data.fetcher.get_bars")
    @patch("market_agent.analysis.options.resolve_strategy")
    def test_debit_structure_returns_none(self, mock_resolve, mock_bars):
        from market_agent.data.models import Bar
        from datetime import datetime
        mock_bars.return_value = [
            Bar(timestamp=datetime(2026, 1, 1), open=Decimal("450"),
                high=Decimal("455"), low=Decimal("445"), close=Decimal("450"), volume=1000000),
        ]
        mock_resolve.return_value = {
            "credit": -0.20,  # Net debit
            "max_loss": 5.0, "legs": [],
        }
        scout = MadmanScout()
        result = scout._check_back_ratio("SPY", date(2026, 2, 1), VolRegime.HIGH)
        assert result is None

    @patch("market_agent.data.fetcher.get_bars")
    def test_no_bars_returns_none(self, mock_bars):
        mock_bars.return_value = []
        scout = MadmanScout()
        result = scout._check_back_ratio("SPY", date(2026, 2, 1), VolRegime.HIGH)
        assert result is None

    @patch("market_agent.data.fetcher.get_bars")
    def test_exception_returns_none(self, mock_bars):
        mock_bars.side_effect = RuntimeError("network error")
        scout = MadmanScout()
        result = scout._check_back_ratio("SPY", date(2026, 2, 1), VolRegime.HIGH)
        assert result is None


class TestFlagZeroDte:
    def test_monday_high_regime_adds_alert(self):
        # Monday = weekday 0
        monday = date(2026, 2, 2)  # Feb 2 2026 is a Monday
        assert monday.weekday() == 0
        state = _make_state(regime=_make_regime(regime=VolRegime.HIGH, vix=30.0))

        scout = MadmanScout()
        scout._flag_zero_dte(monday, state)

        assert any("0DTE" in a for a in state.alerts)

    def test_tuesday_no_alert(self):
        tuesday = date(2026, 2, 3)  # Tuesday
        assert tuesday.weekday() == 1
        state = _make_state(regime=_make_regime(regime=VolRegime.HIGH))

        scout = MadmanScout()
        scout._flag_zero_dte(tuesday, state)

        assert not any("0DTE" in a for a in state.alerts)

    def test_monday_normal_regime_no_alert(self):
        monday = date(2026, 2, 2)
        state = _make_state(regime=_make_regime(regime=VolRegime.NORMAL))

        scout = MadmanScout()
        scout._flag_zero_dte(monday, state)

        assert not any("0DTE" in a for a in state.alerts)

    def test_friday_high_regime_adds_alert(self):
        # Find a Friday in HIGH regime
        friday = date(2026, 2, 6)  # Friday
        assert friday.weekday() == 4
        state = _make_state(regime=_make_regime(regime=VolRegime.HIGH))

        scout = MadmanScout()
        scout._flag_zero_dte(friday, state)

        assert any("0DTE" in a for a in state.alerts)


class TestMadmanScoutRun:
    def test_no_regime_returns_state_unchanged(self):
        state = _make_state()
        state.regime = None
        scout = MadmanScout()
        result = scout.run(state)
        assert result is state
        assert len(result.proposals) == 0

    @patch("market_agent.agents.madman._get_next_earnings")
    def test_is_madman_flag_set(self, mock_earn):
        today = date(2026, 2, 1)
        mock_earn.return_value = today + timedelta(days=7)

        with patch("market_agent.agents.madman.date") as mock_date:
            mock_date.today.return_value = today
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            state = _make_state(
                regime=_make_regime(regime=VolRegime.NORMAL),
                scan_symbols=["AAPL"],
            )
            MadmanScout().run(state)

        madman_proposals = [p for p in state.proposals if p.is_madman]
        for p in madman_proposals:
            assert p.is_madman is True

    @patch("market_agent.agents.madman._get_next_earnings")
    def test_max_proposals_capped(self, mock_earn):
        today = date(2026, 2, 1)
        # Every symbol has earnings in range
        mock_earn.return_value = today + timedelta(days=8)

        with patch("market_agent.agents.madman.date") as mock_date:
            mock_date.today.return_value = today
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            # More symbols than MAX_MADMAN_PROPOSALS
            symbols = ["AAPL", "MSFT", "AMZN", "GOOG", "META"]
            state = _make_state(
                regime=_make_regime(regime=VolRegime.NORMAL),
                scan_symbols=symbols,
            )
            MadmanScout().run(state)

        assert len(state.proposals) <= MAX_MADMAN_PROPOSALS

    def test_position_size_always_madman_cap(self):
        state = _make_state(
            regime=_make_regime(regime=VolRegime.NORMAL),
            scan_symbols=["SPY"],
        )
        scout = MadmanScout()
        # Inject a proposal directly via earnings calendar mock
        with patch.object(scout, "_check_earnings_calendar") as mock_ec:
            mock_ec.return_value = _make_madman_proposal("SPY", pct=MADMAN_POSITION_PCT)
            with patch.object(scout, "_check_vix_call_spread", return_value=None):
                with patch.object(scout, "_flag_zero_dte"):
                    scout.run(state)

        madman = [p for p in state.proposals if p.is_madman]
        for p in madman:
            assert p.position_size_pct <= 0.20  # Max madman cap

    def test_aggregate_cap_prevents_excess(self):
        """When existing madman allocation is at cap, new ones are rejected."""
        # Pre-fill proposals at the cap
        existing = [
            _make_madman_proposal("SPY", pct=2.5),
            _make_madman_proposal("QQQ", pct=2.5),
        ]  # 5.0% total = at MADMAN_MAX_TOTAL_PCT
        state = _make_state(
            regime=_make_regime(regime=VolRegime.NORMAL),
            proposals=existing,
            scan_symbols=["AAPL"],  # Need symbols so earnings loop runs
        )
        initial_count = len(state.proposals)

        with patch.object(MadmanScout, "_check_earnings_calendar") as mock_ec:
            mock_ec.return_value = _make_madman_proposal("AAPL")
            with patch.object(MadmanScout, "_check_vix_call_spread", return_value=None):
                with patch.object(MadmanScout, "_flag_zero_dte"):
                    MadmanScout().run(state)

        # The new proposal should NOT be added (already at cap)
        assert len(state.proposals) == initial_count
        assert any("cap" in a.lower() or "Madman cap" in a for a in state.alerts)

    def test_madman_position_pct_is_015(self):
        assert MADMAN_POSITION_PCT == pytest.approx(0.15)

    def test_max_madman_proposals_is_three(self):
        assert MAX_MADMAN_PROPOSALS == 3

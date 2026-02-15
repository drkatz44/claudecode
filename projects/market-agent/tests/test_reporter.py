"""Tests for backtest report generation."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from market_agent.backtest.engine import BacktestResult, Trade
from market_agent.backtest.reporter import (
    generate_report,
    generate_multi_report,
    save_report,
    _safe_name,
)
from market_agent.data.models import SignalDirection


def _make_trade(pnl_pct=2.0, direction=SignalDirection.LONG):
    pnl = Decimal(str(pnl_pct))
    return Trade(
        symbol="AAPL",
        direction=direction,
        strategy="test",
        entry_time=datetime(2024, 3, 1),
        entry_price=Decimal("150.00"),
        exit_time=datetime(2024, 3, 15),
        exit_price=Decimal(str(150 + float(pnl))),
        stop_loss=Decimal("145.00"),
        take_profit=Decimal("160.00"),
        pnl=pnl,
        pnl_pct=float(pnl_pct),
        bars_held=10,
        exit_reason="take_profit" if pnl_pct > 0 else "stop_loss",
    )


def _make_result(total_return=15.0, trades=None, benchmark=None):
    if trades is None:
        trades = [_make_trade(2.0), _make_trade(-1.0), _make_trade(3.0)]
    base = datetime(2024, 1, 2)
    curve = [(base + timedelta(days=i), 10000 + i * 10) for i in range(100)]
    return BacktestResult(
        trades=trades,
        initial_capital=Decimal("10000"),
        final_capital=Decimal(str(10000 + total_return * 100)),
        total_return_pct=total_return,
        win_rate=66.7,
        avg_win=2.5,
        avg_loss=-1.0,
        profit_factor=2.5,
        max_drawdown_pct=5.0,
        sharpe_ratio=1.2,
        total_trades=len(trades),
        avg_bars_held=8.0,
        equity_curve=curve,
        sortino_ratio=1.5,
        calmar_ratio=3.0,
        benchmark_return_pct=benchmark,
        alpha=total_return - benchmark if benchmark is not None else None,
    )


class TestGenerateReport:
    def test_basic_report(self):
        results = {"momentum": _make_result(15.0)}
        report = generate_report("AAPL", results)
        assert "# Backtest Report: AAPL" in report
        assert "momentum" in report
        assert "15.0%" in report

    def test_multi_strategy(self):
        results = {
            "momentum": _make_result(15.0),
            "mean_reversion": _make_result(8.0),
        }
        report = generate_report("AAPL", results)
        assert "Strategy Comparison" in report
        assert "momentum" in report
        assert "mean_reversion" in report
        assert "Best strategy" in report

    def test_with_benchmark(self):
        results = {"momentum": _make_result(15.0, benchmark=10.0)}
        report = generate_report("AAPL", results)
        assert "+5.0%" in report  # alpha

    def test_with_walk_forward(self):
        results = {"momentum": _make_result(15.0)}
        wf = {
            "momentum": {
                "windows": [{"return_pct": 5.0}],
                "total_windows": 3,
                "avg_return": 5.0,
                "avg_sharpe": 1.1,
                "best_return": 8.0,
                "worst_return": 2.0,
                "consistency": 100.0,
            }
        }
        report = generate_report("AAPL", results, walk_forward=wf)
        assert "Walk-Forward" in report

    def test_with_chart_paths(self):
        results = {"momentum": _make_result(15.0)}
        charts = {"momentum": Path("/tmp/chart.png")}
        report = generate_report("AAPL", results, chart_paths=charts)
        assert "Charts" in report
        assert "/tmp/chart.png" in report

    def test_empty_results(self):
        report = generate_report("AAPL", {})
        assert "No backtest results available" in report

    def test_trade_table(self):
        report = generate_report("AAPL", {"momentum": _make_result(15.0)})
        assert "Recent Trades" in report
        assert "take_profit" in report


class TestGenerateMultiReport:
    def test_multi_symbol(self):
        all_results = {
            "AAPL": {"momentum": _make_result(15.0), "macd": _make_result(8.0)},
            "NVDA": {"momentum": _make_result(20.0), "macd": _make_result(12.0)},
        }
        report = generate_multi_report(all_results)
        assert "Multi-Symbol" in report
        assert "AAPL" in report
        assert "NVDA" in report
        assert "Strategy Rankings" in report
        assert "Best Strategy Per Symbol" in report


class TestSaveReport:
    def test_saves_markdown(self, tmp_path, monkeypatch):
        import market_agent.backtest.reporter as rep_mod
        monkeypatch.setattr(rep_mod, "REPORTS_DIR", tmp_path)

        content = "# Test Report\nSome content"
        path = save_report(content, "AAPL")
        assert path.exists()
        assert path.suffix == ".md"
        assert "AAPL" in path.name
        assert path.read_text() == content

    def test_safe_filename(self, tmp_path, monkeypatch):
        import market_agent.backtest.reporter as rep_mod
        monkeypatch.setattr(rep_mod, "REPORTS_DIR", tmp_path)

        path = save_report("test", "../../../etc/passwd")
        assert ".." not in str(path.name)
        assert path.exists()

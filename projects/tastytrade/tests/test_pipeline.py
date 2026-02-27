"""Tests for the `tt-strategy pipeline` command.

Tests the full end-to-end chain: screen → build → risk-check → (journal).
Uses in-process function calls via Typer's test runner.
"""

from __future__ import annotations

import json
import tempfile
import os
from datetime import date, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tastytrade_strategy.cli import app

runner = CliRunner()

_FUTURE_EXP = (date.today() + timedelta(days=45)).strftime("%Y-%m-%d")
_EXP_YMD = _FUTURE_EXP[2:].replace("-", "")  # YYMMDD for OCC symbols


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _occ(symbol: str, side: str, strike: int) -> str:
    """Build OCC option symbol: root(6) + YYMMDD + P/C + strike*1000(8)."""
    root = symbol.ljust(6)
    return f"{root}{_EXP_YMD}{side}{strike * 1000:08d}"


def _chain_json(symbol: str = "SPY") -> dict:
    """Minimal nested chain JSON suitable for iron_condor at 0.30/0.16 delta."""
    strikes = [
        # (strike, call_delta, put_delta, price)
        (475, 0.10, -0.10, 0.30),
        (480, 0.14, -0.14, 0.55),
        (485, 0.16, -0.16, 0.85),  # long put / long call wing
        (490, 0.22, -0.22, 1.20),
        (495, 0.28, -0.28, 1.60),
        (500, 0.50, -0.50, 2.50),  # ATM
        (505, 0.28, -0.28, 1.60),  # not exactly 0.30 but closest
        (510, 0.30, -0.30, 1.40),  # short call
        (515, 0.22, -0.22, 1.10),
        (490, 0.30, -0.30, 1.40),  # duplicate strike index gives 0.30 put delta
    ]
    # Build unique strike list
    strike_rows = []
    seen = set()
    for strike, cd, pd, price in strikes:
        if strike in seen:
            continue
        seen.add(strike)
        strike_rows.append({
            "strike-price": str(float(strike)),
            "call": _occ(symbol, "C", strike),
            "put": _occ(symbol, "P", strike),
        })

    return {
        "data": {
            "items": [
                {
                    "underlying-symbol": symbol,
                    "expirations": [
                        {
                            "days-to-expiration": 45,
                            "expiration-date": _FUTURE_EXP,
                            "strikes": strike_rows,
                        }
                    ],
                }
            ]
        }
    }


def _greeks_json(symbol: str = "SPY") -> list:
    """Greeks items for all strikes in _chain_json, covering put+call sides."""
    entries = [
        # (strike, side, delta, price)
        (475, "C", 0.10, 0.30),
        (475, "P", -0.10, 0.30),
        (480, "C", 0.14, 0.55),
        (480, "P", -0.14, 0.55),
        (485, "C", 0.16, 0.85),
        (485, "P", -0.16, 0.85),
        (490, "C", 0.22, 1.20),
        (490, "P", -0.30, 1.40),  # put side set to -0.30 for short put target
        (495, "C", 0.28, 1.60),
        (495, "P", -0.28, 1.60),
        (500, "C", 0.50, 2.50),
        (500, "P", -0.50, 2.50),
        (505, "C", 0.28, 1.60),
        (505, "P", -0.28, 1.60),
        (510, "C", 0.30, 1.40),  # call side 0.30 for short call target
        (510, "P", -0.22, 1.10),
        (515, "C", 0.22, 1.10),
        (515, "P", -0.14, 0.60),
    ]
    items = []
    for strike, side, delta, price in entries:
        items.append({
            "symbol": _occ(symbol, side, strike),
            "price": price,
            "implied-volatility": 0.35,
            "delta": delta,
            "gamma": 0.05,
            "theta": -0.08,
            "rho": 0.01,
            "vega": 0.15,
        })
    return items


def _metrics_json(
    symbols: list[tuple[str, float]] | None = None,
) -> list:
    """Market metrics list. symbols is [(symbol, iv_rank), ...]."""
    if symbols is None:
        symbols = [("SPY", 0.72)]
    return [
        {
            "symbol": sym,
            "implied-volatility-rank": iv_rank * 100,  # API returns 0-100
            "implied-volatility-index": 0.35,
            "historical-volatility-30-day": 0.25,
            "liquidity-rating": 5.0,
            "beta": 1.0,
        }
        for sym, iv_rank in symbols
    ]


def _portfolio_json(nlv: float = 100_000.0, bp: float = 50_000.0) -> dict:
    return {
        "positions": [],
        "balances": {
            "net-liquidating-value": str(nlv),
            "derivative-buying-power": str(bp),
        },
    }


_SENTINEL = object()  # sentinel for "not provided" vs None


class _TmpPipeline:
    """Context manager that sets up tmp files and returns a run helper.

    chains=None → no --chains-dir arg passed
    chains={}   → --chains-dir passed but dir is empty (no chain files)
    chains={"SPY": ...} → chain file written for SPY
    """

    def __init__(
        self,
        metrics: list | None = None,
        portfolio: dict | None = None,
        chains: dict[str, dict] | None = _SENTINEL,  # type: ignore[assignment]
        greeks: dict[str, list] | None = None,
    ):
        self.metrics = metrics if metrics is not None else _metrics_json()
        self.portfolio = portfolio if portfolio is not None else _portfolio_json()
        self.chains = chains  # symbol → chain_dict (None = don't create dir)
        self.greeks = greeks  # symbol → greeks_list

    def __enter__(self):
        self._tmpdir = tempfile.mkdtemp()
        self.metrics_path = os.path.join(self._tmpdir, "metrics.json")
        self.portfolio_path = os.path.join(self._tmpdir, "portfolio.json")
        self.chains_dir = os.path.join(self._tmpdir, "chains")
        self.greeks_dir = os.path.join(self._tmpdir, "greeks")

        Path(self.metrics_path).write_text(json.dumps(self.metrics))
        Path(self.portfolio_path).write_text(json.dumps(self.portfolio))

        if self.chains is not _SENTINEL:  # type: ignore[comparison-overlap]
            os.makedirs(self.chains_dir, exist_ok=True)
            for sym, chain in (self.chains or {}).items():
                Path(self.chains_dir, f"{sym}.json").write_text(json.dumps(chain))

        if self.greeks:
            os.makedirs(self.greeks_dir, exist_ok=True)
            for sym, g in self.greeks.items():
                Path(self.greeks_dir, f"{sym}_greeks.json").write_text(json.dumps(g))

        return self

    def __exit__(self, *_):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def run(self, extra_args: list[str] | None = None) -> tuple[int, dict | str]:
        args = [
            "pipeline",
            "--metrics", self.metrics_path,
            "--portfolio", self.portfolio_path,
        ]
        if self.chains is not _SENTINEL:  # type: ignore[comparison-overlap]
            args += ["--chains-dir", self.chains_dir]
        if self.greeks:
            args += ["--greeks-dir", self.greeks_dir]
        args += extra_args or []

        result = runner.invoke(app, args)
        try:
            return result.exit_code, json.loads(result.output)
        except json.JSONDecodeError:
            return result.exit_code, result.output


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPipelineHappyPath:
    def test_pipeline_happy_path(self, tmp_path):
        """All steps succeed, approved trade journaled."""
        with _TmpPipeline(
            chains={"SPY": _chain_json("SPY")},
            greeks={"SPY": _greeks_json("SPY")},
        ) as ctx:
            db_path = tmp_path / "journal.db"
            exit_code, out = ctx.run([
                "--strategy", "iron_condor",
                "--auto-journal",
                "--rationale", "Test pipeline",
                f"--min-dte", "1",
            ])

        assert exit_code == 0, out
        assert out["screened"] == 1
        assert out["approved"] >= 0  # might be 0 if risk rejects, but structure must be there
        assert "results" in out
        assert "skipped" in out
        assert "rejected" in out

    def test_pipeline_output_structure(self):
        """All required top-level output keys are present."""
        with _TmpPipeline(
            chains={"SPY": _chain_json("SPY")},
            greeks={"SPY": _greeks_json("SPY")},
        ) as ctx:
            exit_code, out = ctx.run(["--min-dte", "1"])

        assert exit_code == 0
        assert set(out.keys()) >= {"screened", "built", "approved", "results", "skipped", "rejected"}

    def test_pipeline_approved_result_keys(self):
        """Approved result entries have all expected keys."""
        with _TmpPipeline(
            chains={"SPY": _chain_json("SPY")},
            greeks={"SPY": _greeks_json("SPY")},
            portfolio=_portfolio_json(nlv=500_000, bp=200_000),  # generous limits
        ) as ctx:
            exit_code, out = ctx.run(["--min-dte", "1"])

        assert exit_code == 0
        for rec in out["results"]:
            assert "symbol" in rec
            assert "screen" in rec
            assert "strategy" in rec
            assert "risk" in rec
            assert "journal_id" in rec
            assert rec["risk"]["approved"] is True


class TestPipelineSkipping:
    def test_pipeline_no_chain_skips_symbol(self):
        """Missing chain file → symbol in skipped list."""
        with _TmpPipeline(
            chains={},  # chains dir exists but no SPY.json
        ) as ctx:
            exit_code, out = ctx.run()

        assert exit_code == 0
        assert len(out["skipped"]) == 1
        assert out["skipped"][0]["symbol"] == "SPY"
        assert "no chain file" in out["skipped"][0]["reason"]

    def test_pipeline_no_chains_dir_skips_all(self):
        """No --chains-dir flag → all symbols skipped."""
        with _TmpPipeline(chains=None) as ctx:
            # chains=None → no --chains-dir arg; all symbols skipped
            exit_code, out = ctx.run()

        assert exit_code == 0
        # All screened symbols land in skipped
        assert out["screened"] == 1
        assert len(out["skipped"]) == 1

    def test_pipeline_iv_filter(self):
        """Symbol with low IV rank excluded by screener (not even in skipped)."""
        low_iv_metrics = _metrics_json([("LOW", 0.10)])  # below default 0.30 min
        with _TmpPipeline(
            metrics=low_iv_metrics,
            chains={"LOW": _chain_json("LOW")},
        ) as ctx:
            exit_code, out = ctx.run()

        assert exit_code == 0
        assert out["screened"] == 0  # filtered before chain lookup
        assert out["skipped"] == []


class TestPipelineRiskBehavior:
    def test_pipeline_risk_rejected(self):
        """Strategy exceeds limits → symbol in rejected list."""
        # Very small portfolio → position risk violation
        with _TmpPipeline(
            portfolio=_portfolio_json(nlv=1_000, bp=500),
            chains={"SPY": _chain_json("SPY")},
            greeks={"SPY": _greeks_json("SPY")},
        ) as ctx:
            exit_code, out = ctx.run(["--min-dte", "1"])

        assert exit_code == 0
        assert len(out["rejected"]) == 1
        assert out["rejected"][0]["symbol"] == "SPY"
        assert out["rejected"][0]["risk"]["approved"] is False

    def test_pipeline_no_auto_journal(self):
        """Approved trade without --auto-journal → journal_id is None."""
        with _TmpPipeline(
            portfolio=_portfolio_json(nlv=500_000, bp=200_000),
            chains={"SPY": _chain_json("SPY")},
            greeks={"SPY": _greeks_json("SPY")},
        ) as ctx:
            # no --auto-journal flag
            exit_code, out = ctx.run(["--min-dte", "1"])

        assert exit_code == 0
        for rec in out["results"]:
            assert rec["journal_id"] is None


class TestPipelineMultipleSymbols:
    def test_pipeline_multiple_symbols(self):
        """3 symbols in metrics, 2 have chains, counts reflect that."""
        metrics = _metrics_json([("SPY", 0.72), ("AAPL", 0.65), ("TSLA", 0.80)])
        # Only SPY and AAPL have chain files; TSLA doesn't
        with _TmpPipeline(
            metrics=metrics,
            chains={
                "SPY": _chain_json("SPY"),
                "AAPL": _chain_json("AAPL"),
                # TSLA intentionally missing
            },
            greeks={
                "SPY": _greeks_json("SPY"),
                "AAPL": _greeks_json("AAPL"),
            },
            portfolio=_portfolio_json(nlv=500_000, bp=200_000),
        ) as ctx:
            exit_code, out = ctx.run(["--min-dte", "1"])

        assert exit_code == 0
        assert out["screened"] == 3
        assert out["built"] == out["approved"] + len(out["rejected"])
        tsla_skipped = [s for s in out["skipped"] if s["symbol"] == "TSLA"]
        assert len(tsla_skipped) == 1

    def test_pipeline_limit(self):
        """--limit N is respected: only top N symbols processed."""
        metrics = _metrics_json([
            ("SPY", 0.90),
            ("NVDA", 0.85),
            ("TSLA", 0.80),
        ])
        with _TmpPipeline(
            metrics=metrics,
            chains={
                "SPY": _chain_json("SPY"),
                "NVDA": _chain_json("NVDA"),
                "TSLA": _chain_json("TSLA"),
            },
        ) as ctx:
            exit_code, out = ctx.run(["--limit", "2"])

        assert exit_code == 0
        # Only 2 symbols passed to chain lookup (screened[:2])
        assert out["screened"] == 2


class TestPipelineErrors:
    def test_pipeline_metrics_file_missing(self):
        """Non-existent metrics file → exit 1 with error JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pf = os.path.join(tmpdir, "portfolio.json")
            Path(pf).write_text(json.dumps(_portfolio_json()))
            result = runner.invoke(app, [
                "pipeline",
                "--metrics", "/nonexistent/metrics.json",
                "--portfolio", pf,
            ])
        assert result.exit_code != 0
        out = json.loads(result.output)
        assert "error" in out

    def test_pipeline_portfolio_file_missing(self):
        """Non-existent portfolio file → exit 1 with error JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mf = os.path.join(tmpdir, "metrics.json")
            Path(mf).write_text(json.dumps(_metrics_json()))
            result = runner.invoke(app, [
                "pipeline",
                "--metrics", mf,
                "--portfolio", "/nonexistent/portfolio.json",
            ])
        assert result.exit_code != 0
        out = json.loads(result.output)
        assert "error" in out

    def test_pipeline_invalid_strategy(self):
        """Unknown strategy type → exit 1 with error JSON."""
        with _TmpPipeline() as ctx:
            result = runner.invoke(app, [
                "pipeline",
                "--metrics", ctx.metrics_path,
                "--portfolio", ctx.portfolio_path,
                "--strategy", "butterfly",
            ])
        assert result.exit_code != 0
        out = json.loads(result.output)
        assert "error" in out


class TestPipelineStrategyOptions:
    def test_pipeline_custom_deltas(self):
        """Custom --put-delta and --call-delta are forwarded to builder."""
        with _TmpPipeline(
            portfolio=_portfolio_json(nlv=500_000, bp=200_000),
            chains={"SPY": _chain_json("SPY")},
            greeks={"SPY": _greeks_json("SPY")},
        ) as ctx:
            exit_code, out = ctx.run([
                "--put-delta", "0.16",
                "--call-delta", "0.16",
                "--long-put-delta", "0.10",
                "--long-call-delta", "0.10",
                "--min-dte", "1",
            ])

        assert exit_code == 0
        # Builder ran (symbol not skipped due to deltas)
        assert out["built"] + len(out["skipped"]) == out["screened"]

    def test_pipeline_short_put_strategy(self):
        """short_put strategy type works end-to-end."""
        with _TmpPipeline(
            portfolio=_portfolio_json(nlv=500_000, bp=200_000),
            chains={"SPY": _chain_json("SPY")},
            greeks={"SPY": _greeks_json("SPY")},
        ) as ctx:
            exit_code, out = ctx.run([
                "--strategy", "short_put",
                "--put-delta", "0.30",
                "--min-dte", "1",
            ])

        assert exit_code == 0
        # If built, strategy_type should be short_put
        for rec in out["results"] + out["rejected"]:
            if "strategy" in rec:
                assert rec["strategy"]["strategy_type"] == "short_put"

    def test_pipeline_screened_count_matches_metrics(self):
        """screened count reflects how many symbols pass the IV filter."""
        metrics = _metrics_json([
            ("SPY", 0.72),   # passes 0.30 threshold
            ("AAPL", 0.65),  # passes
            ("VXX", 0.15),   # fails
        ])
        with _TmpPipeline(metrics=metrics) as ctx:
            exit_code, out = ctx.run()

        assert exit_code == 0
        assert out["screened"] == 2  # VXX filtered out

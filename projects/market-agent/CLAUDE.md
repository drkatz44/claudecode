# Project: market-agent

## Purpose
Financial markets analysis and trading signal generation. Broker-agnostic research
and analysis layer that feeds tastytrade for execution (equities, options, crypto).

## Status
active

## Stack
Python (uv, pandas, numpy, pydantic, rich, yfinance, matplotlib, pytest, ruff)

## Architecture
```
MCP Integrations (data + execution)
  ├── polygon-io    — market data, news, fundamentals
  └── tasty-agent   — broker for equities, options, crypto + greeks/IV

market-agent (this project)
  ├── data/         — fetcher (yfinance+options), models, watchlists, config
  ├── analysis/     — technical (15), screener (3), options, charts
  ├── signals/      — generator, recommender (tastytrade bridge)
  └── backtest/     — engine, strategies (4), reporter

tastytrade (sibling project)
  └── execution layer for options strategies
```

## Key Files
- `src/market_agent/data/models.py` — Bar, Quote, Signal, Fundamentals (Pydantic v2)
- `src/market_agent/data/fetcher.py` — yfinance backend (get_bars, get_quote, get_fundamentals)
- `src/market_agent/data/watchlist.py` — YAML-persistent watchlists (~/.market-agent/watchlists/)
- `src/market_agent/analysis/technical.py` — 15 indicators (SMA, EMA, MACD, RSI, BB, ATR, etc.)
- `src/market_agent/analysis/screener.py` — momentum, mean reversion, volatility screens
- `src/market_agent/signals/generator.py` — Signal generation from screen results
- `src/market_agent/signals/recommender.py` — Recommendation engine + tastytrade bridge
- `src/market_agent/backtest/engine.py` — No-look-ahead backtesting engine
- `src/market_agent/backtest/strategies.py` — momentum_crossover, mean_reversion_bb, macd_momentum, breakout_volume
- `src/market_agent/backtest/reporter.py` — Markdown report generation + multi-symbol summaries
- `src/market_agent/analysis/options.py` — IV rank, skew, strike selection, strategy resolution
- `src/market_agent/analysis/charts.py` — Technical, equity curve, options chain charts (matplotlib)
- `src/market_agent/data/config.py` — YAML config management (~/.market-agent/config.yaml)
- `scripts/pipeline.py` — Full scan → signal → recommend workflow (primary entry point)
- `scripts/scan.py` — Quick market scanner
- `scripts/backtest.py` — Strategy backtesting runner
- `scripts/report.py` — Generate backtest reports with charts
- `scripts/scheduled_scan.py` — Scheduled scanning with change detection + launchd install

## Usage
```bash
cd projects/market-agent
uv sync

# Full pipeline (daily analysis)
uv run python scripts/pipeline.py                    # all scans
uv run python scripts/pipeline.py momentum           # momentum only
uv run python scripts/pipeline.py volatility          # premium selling
uv run python scripts/pipeline.py symbol AAPL         # single symbol deep dive
uv run python scripts/pipeline.py watchlist my_list   # scan saved watchlist

# Quick scan
uv run python scripts/scan.py all
uv run python scripts/scan.py symbol AAPL

# Backtest
uv run python scripts/backtest.py AAPL
uv run python scripts/backtest.py SPY,QQQ,AAPL momentum_crossover
uv run python scripts/backtest.py AAPL --walk-forward

# Reports (backtest + charts)
uv run python scripts/report.py AAPL
uv run python scripts/report.py AAPL,NVDA,SPY --walk-forward

# Scheduled scan
uv run python scripts/scheduled_scan.py              # run scan now
uv run python scripts/scheduled_scan.py --install     # install daily launchd job
uv run python scripts/scheduled_scan.py --uninstall   # remove launchd job

# Tests (179 tests)
uv run python -m pytest tests/ -v
```

## Asset Classes
- Equities (momentum, swing, mean reversion)
- Options (premium selling, volatility strategies)
- Crypto (momentum, trend following)
- ETFs (sector rotation, macro)

## Screener Watchlists
- `SP500_TOP` — 30 large-cap equities
- `HIGH_IV_NAMES` — 16 high-volatility names for options premium
- `SECTOR_ETFS` — 11 sector ETFs (XLK, XLF, XLE, etc.)
- `CRYPTO_MAJORS` — 10 major cryptocurrencies

## Recommendation → Tastytrade Bridge
The recommender module converts signals into actionable recommendations that include
tastytrade-compatible options strategy suggestions:
- `short_put` — bullish momentum (sell puts below support)
- `iron_condor` — high vol + bearish/neutral (defined risk)
- `strangle` — moderate vol + neutral (sell both sides)
- `vertical_spread` — directional with defined risk

Each OptionsStrategy includes: strategy_type, DTE range, delta target, spread width.
Claude can pass these directly to the tastytrade project's strategy constructors.

## MCP Servers
- **polygon-io**: Market data, news, fundamentals — `uvx mcp_polygon` (configured)
- **tasty-agent**: Broker (equities, options, crypto) + greeks/IV — `uvx tasty-agent` (configured)

## Options Analysis
- IV rank/percentile using HV as proxy (yfinance has no Greeks)
- Delta approximation via moneyness (0.30 delta ≈ 5% OTM, 0.16 delta ≈ 8-10% OTM)
- Strategy resolution: converts abstract OptionsStrategy → concrete strikes/premium/risk
- Supports: short_put, iron_condor, strangle, vertical_spread

## Output Directories
- `~/.market-agent/charts/` — PNG chart files
- `~/.market-agent/reports/` — Markdown backtest/scan reports
- `~/.market-agent/cache/` — Market data cache (4hr TTL)
- `~/.market-agent/config.yaml` — Scan configuration
- `~/.market-agent/last_scan.json` — Previous scan for change detection

## Conventions
- All prices as Decimal for precision
- UTC timestamps everywhere
- Signal output format compatible with tastytrade project models
- Watchlists stored in ~/.market-agent/watchlists/ as YAML
- Filenames sanitized via `_safe_name()` (no path traversal)

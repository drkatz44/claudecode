# Project: market-agent

## Purpose
Financial markets analysis and trading signal generation. Broker-agnostic research
and analysis layer that feeds execution engines (tastytrade for options, Alpaca for
equities/crypto).

## Status
active

## Stack
Python (uv, pandas, numpy, pydantic, rich, yfinance, pytest, ruff)

## Architecture
```
MCP Integrations (data + execution)
  ├── polygon-io    — market data, news, fundamentals
  ├── alpha-vantage — technical indicators, options data
  ├── alpaca        — equities/crypto broker + paper trading
  └── tasty-agent   — options execution (existing)

market-agent (this project)
  ├── data/         — fetcher (yfinance), models, watchlists
  ├── analysis/     — technical indicators (15), screener (3 modes)
  ├── signals/      — generator, recommender (tastytrade bridge)
  └── backtest/     — engine, strategies (3)

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
- `src/market_agent/backtest/strategies.py` — momentum_crossover, mean_reversion_bb, macd_momentum
- `scripts/pipeline.py` — Full scan → signal → recommend workflow (primary entry point)
- `scripts/scan.py` — Quick market scanner
- `scripts/backtest.py` — Strategy backtesting runner

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

## MCP Servers (pending API keys)
- **polygon-io**: Market data — `uvx mcp_polygon`
- **alpha-vantage**: Technical indicators — remote SSE server
- **alpaca**: Broker — `uvx alpaca-mcp-server`
- **tasty-agent**: Options broker — `uvx tasty-agent` (configured in workspace root)

## Conventions
- All prices as Decimal for precision
- UTC timestamps everywhere
- Signal output format compatible with tastytrade project models
- Watchlists stored in ~/.market-agent/watchlists/ as YAML

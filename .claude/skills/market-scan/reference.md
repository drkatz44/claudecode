# Market Scan — Reference

## Project Location
```
/Users/drk/Code/claudecode/projects/market-agent/
```
All commands: `cd` there and use `uv run`.

## Pipeline Commands

```bash
# Full daily scan
uv run python scripts/pipeline.py all

# Targeted modes
uv run python scripts/pipeline.py momentum    # S&P 500 top names
uv run python scripts/pipeline.py reversion   # oversold (RSI < 35)
uv run python scripts/pipeline.py volatility  # high-IV premium selling
uv run python scripts/pipeline.py sectors     # 11 sector ETFs
uv run python scripts/pipeline.py crypto      # 10 major cryptos

# Single symbol deep dive
uv run python scripts/pipeline.py symbol AAPL

# Watchlist scan
uv run python scripts/pipeline.py watchlist mylist

# Quick scan (no recommendations)
uv run python scripts/scan.py all
uv run python scripts/scan.py symbol TSLA

# Backtest
uv run python scripts/backtest.py AAPL
uv run python scripts/backtest.py SPY momentum_crossover
uv run python scripts/backtest.py AAPL --walk-forward
uv run python scripts/backtest.py AAPL,NVDA,SPY

# Report with charts
uv run python scripts/report.py AAPL
uv run python scripts/report.py AAPL,NVDA,SPY --walk-forward
```

## Recommendation Fields

| Field | Meaning |
|-------|---------|
| `action` | `buy_equity`, `sell_premium`, `sell_equity`, `watch` |
| `confidence` | 0–100% signal strength |
| `entry_price` | Suggested entry |
| `stop_loss` | ATR-based risk level |
| `take_profit` | Profit target |
| `R/R` | Risk/reward ratio (target: ≥1.5) |
| `size` | Position size as % of portfolio |
| `options` | Strategy type + delta (e.g. `short_put d30`) |
| `rationale` | Top 2 reasons for the signal |

## Options Strategies (tastytrade-ready)

| Strategy | Triggered By | Risk Profile | Params |
|----------|-------------|--------------|--------|
| `short_put` | Bullish momentum | Defined by strike | delta 0.30, DTE 30–45 |
| `iron_condor` | High IV + neutral | Max loss = width − credit | delta 0.16 each side |
| `strangle` | Moderate IV + neutral | Unlimited (requires margin) | delta 0.20 each side |
| `vertical_spread` | Directional + defined risk | Debit or credit spread | delta 0.40 long leg |

Each `OptionsStrategy` object includes: `strategy_type`, `dte_min`, `dte_max`,
`delta_target`, `spread_width` — ready for tastytrade chain-builder.

## Institutional Context (metals tickers)

### Supported Tickers
| Commodity | Tickers |
|-----------|---------|
| GOLD | GLD, IAU, GDX, GDXJ, NEM, GOLD, AEM, KGC, AU, FNV, WPM, RGLD |
| SILVER | AG, PAAS, HL, SLV, SIVR, SIL |
| COPPER | FCX, SCCO, TECK, CPER, COPX |
| PLATINUM | PPLT |
| PALLADIUM | PALL |

### COT Positioning Signals
| Signal | Meaning | Confidence Adj |
|--------|---------|----------------|
| `extreme_long` | Crowded — pullback risk | 0.85 |
| `extreme_short` | Contrarian bullish — capitulation | 1.1–1.2 |
| `neutral` | No directional bias | 1.0 |

### COMEX Warehouse Trends
| Trend | Meaning | Confidence Adj |
|-------|---------|----------------|
| `drawing` | Physical tightening → bullish | 1.05 |
| `building` | Supply increasing → bearish/neutral | 0.9 |

### Combined Bias Labels
| Bias | COT + COMEX | Conf Adj |
|------|-------------|---------|
| `bullish_capitulation` | extreme_short + drawing | 1.2 |
| `bullish_crowded` | extreme_long + drawing | 0.85 |
| `bearish_excess` | extreme_long + building | 0.8 |
| `neutral_abundant` | neutral + building | 0.9 |
| `neutral_rebuilding` | extreme_short + building | 0.95 |
| `bullish_physical` | any + drawing | 1.05 |

## Screener Watchlists

| List | Count | Contents |
|------|-------|---------|
| `SP500_TOP` | 30 | AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, BRK-B, JPM, V… |
| `HIGH_IV_NAMES` | 16 | TSLA, NVDA, MSTR, COIN, PLTR, GME, AMC, RIVN, LCID… |
| `SECTOR_ETFS` | 11 | XLK, XLF, XLE, XLV, XLI, XLB, XLY, XLP, XLU, XLRE, XLC |
| `CRYPTO_MAJORS` | 10 | BTC-USD, ETH-USD, SOL-USD, BNB-USD, XRP-USD… |

## Technical Indicators
SMA-20/50/200, EMA-12/26, MACD + histogram + signal line, RSI-14,
Bollinger Bands (%B + bandwidth), ATR-14, Stochastic %K/%D,
Volume SMA ratio, OBV, ADX, Williams %R, composite Trend Score.

## Strategies Available for Backtesting
| Strategy | Description |
|----------|-------------|
| `momentum_crossover` | SMA-20/50 crossover + volume confirmation |
| `mean_reversion_bb` | Bollinger Band %B reversion (buy <0.1, sell >0.9) |
| `macd_momentum` | MACD histogram direction changes |
| `breakout_volume` | Price breakout with 1.5x+ volume surge |

## Backtest Output Fields
`total_return`, `annualized_return`, `sharpe_ratio`, `max_drawdown`,
`win_rate`, `profit_factor`, `avg_trade`, `num_trades`

## Output Files
```
~/.market-agent/
  charts/      PNG charts (technical, equity curve)
  reports/     Markdown backtest + scan reports
  cache/       Market data (4hr TTL)
  watchlists/  YAML-persisted watchlists
  config.yaml  Scan configuration
```

## Passing to tastytrade
Recommendations from this agent feed directly into the tastytrade project's
chain-builder. Each `OptionsStrategy` can be passed to `recommend_from_signal()`
in the tastytrade project's strategy constructors.

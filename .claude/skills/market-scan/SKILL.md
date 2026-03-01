---
name: market-scan
description: >
  Run market analysis pipeline across equities, ETFs, crypto, and metals.
  Use when asked to scan the market, find trading setups, analyze a specific
  ticker, check momentum/volatility/mean-reversion signals, generate tastytrade
  options recommendations, view institutional COT positioning, or run backtests.
  Covers S&P 500 names, sector ETFs, high-IV options candidates, major crypto,
  and metals tickers with CFTC + COMEX institutional context.
context: fork
argument-hint: "[symbol TICKER | momentum | volatility | reversion | sectors | crypto | all | backtest TICKER]"
---

# Market Analysis Agent

## Live Pipeline Output

!`cd /Users/drk/Code/claudecode/projects/market-agent && ARGS="${ARGUMENTS:-all}"; case "$ARGS" in backtest*) SYMBOL=$(echo $ARGS | awk '{print $2}'); uv run python scripts/backtest.py ${SYMBOL:-SPY} 2>&1 | head -120 ;; *) uv run python scripts/pipeline.py $ARGS 2>&1 | head -200 ;; esac`

---

Interpret the pipeline output above for the user. Focus on:

1. **Top recommendations** by confidence — highlight anything >70%
2. **Options strategy details** (strategy type, delta, DTE) for `sell_premium` actions
3. **Institutional bias** for any metals tickers — explain what COT + COMEX signals mean
4. **Backtest stats** if backtest mode — summarize win rate, Sharpe, max drawdown, total return
5. **Cross-asset patterns** — note any broad themes (risk-on/off, sector rotation, vol regime)

If the output shows errors or no data, diagnose the likely cause and suggest a fix.

See [reference.md](reference.md) for output field definitions, all pipeline commands,
options strategy details, and institutional signal lookup tables.

See [examples/sample-output.md](examples/sample-output.md) for annotated examples of
each scan mode with interpretation guidance.

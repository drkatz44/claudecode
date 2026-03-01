# Sample Pipeline Output

## Example: `/market-scan momentum`

```
╭─────────────────────────────────────╮
│ Market Analysis Pipeline            │
│ 2026-02-27 09:15                    │
╰─────────────────────────────────────╯

Momentum scan...

          Momentum — Equities
┌────────┬──────────────┬──────┬────────┬────────┬────────┬─────┬──────┬──────────────┬──────────────────────────────────┐
│ Symbol │ Action       │ Conf │  Entry │   Stop │ Target │ R/R │ Size │ Options      │ Rationale                        │
├────────┼──────────────┼──────┼────────┼────────┼────────┼─────┼──────┼──────────────┼──────────────────────────────────┤
│ NVDA   │ buy_equity   │  82% │ 875.20 │ 843.50 │ 940.00 │ 2.1 │  4%  │ short_put d30│ SMA20>SMA50, RSI 61 w/ vol surge │
│ META   │ buy_equity   │  76% │ 612.40 │ 588.10 │ 661.00 │ 2.0 │  3%  │ short_put d30│ Bullish trend, MACD positive     │
│ AMZN   │ buy_equity   │  71% │ 228.90 │ 220.50 │ 246.00 │ 1.9 │  3%  │ -            │ Vol breakout, SMA crossover      │
│ GS     │ buy_equity   │  68% │ 582.00 │ 561.00 │ 623.00 │ 2.0 │  3%  │ short_put d30│ Financial sector leading, RSI 58 │
│ UNH    │ buy_equity   │  65% │ 542.10 │ 523.80 │ 579.00 │ 2.0 │  2%  │ -            │ Defensive momentum, low ATR      │
└────────┴──────────────┴──────┴────────┴────────┴────────┴─────┴──────┴──────────────┴──────────────────────────────────┘

╭──────────────────────────────────────────────╮
│ Summary: 5 recommendations                   │
│   Buy equity: 5                              │
│   Sell premium: 0                            │
│   High confidence (>70%): 3                  │
╰──────────────────────────────────────────────╯
Top picks saved to watchlist 'pipeline_picks'
```

**Interpretation:** NVDA and META are the highest-conviction momentum setups. NVDA has
a vol surge + SMA crossover — consider the `short_put d30` at the $843 support level
(~0.30 delta, 35 DTE). META is confirming bullish trend with MACD positive. GS reflects
strength in XLF which may signal broader risk-on rotation.

---

## Example: `/market-scan symbol GLD`

```
╭────────────────────╮
│ Deep Dive: GLD     │
╰────────────────────╯

  Close        $241.80     Trend     bullish
  SMA-20       $238.40     SMA-50    $231.20
  RSI-14       63.4        MACD Hist 1.82
  BB %B        0.74        ATR-14    $3.41
  Trend Score  72          Signals   6B / 2S

         Recommendations for GLD
┌────────┬────────────┬──────┬────────┬────────┬────────┬─────┬──────┬─────────┬──────────────────────────────────┐
│ Symbol │ Action     │ Conf │  Entry │   Stop │ Target │ R/R │ Size │ Options │ Rationale                        │
├────────┼────────────┼──────┼────────┼────────┼────────┼─────┼──────┼─────────┼──────────────────────────────────┤
│ GLD    │ buy_equity │  61% │ 241.80 │ 234.99 │ 255.62 │ 2.0 │  3%  │ -       │ Bullish trend; RSI momentum      │
└────────┴────────────┴──────┴────────┴────────┴────────┴─────┴──────┴─────────┴──────────────────────────────────┘

Institutional Context (GOLD)
  Bias: bullish_crowded
  Confidence adj: 0.85
  MM net +187,423 (+34.2% OI), z=+1.82 → extreme_long; COMEX drawing (-8.3% 30d),
  registered 22%; Crowded long but physical drawdown supports price

  Chart saved: ~/.market-agent/charts/GLD_technical.png
```

**Interpretation:** GLD is technically bullish (trend score 72, RSI 63) but the institutional
picture is mixed. Managed money is extremely net-long (z=+1.82) which raises reversal risk,
but physical COMEX inventory is drawing down — a real squeeze floor. Confidence adjusted from
72% → 61% (×0.85). Trade with tighter stops or smaller size; watch for MM unwind.

---

## Example: `/market-scan volatility`

```
Volatility / premium selling scan...

             Premium Selling — Options
┌────────┬──────────────┬──────┬────────┬────────┬────────┬─────┬──────┬──────────────────┬──────────────────────────────────┐
│ Symbol │ Action       │ Conf │  Entry │   Stop │ Target │ R/R │ Size │ Options          │ Rationale                        │
├────────┼──────────────┼──────┼────────┼────────┼────────┼─────┼──────┼──────────────────┼──────────────────────────────────┤
│ TSLA   │ sell_premium │  79% │ 248.60 │      - │      - │   - │  2%  │ iron_condor d16  │ IV rank 78, neutral trend        │
│ NVDA   │ sell_premium │  73% │ 875.20 │      - │      - │   - │  2%  │ short_put d30    │ IV rank 65, bullish bias         │
│ MSTR   │ sell_premium │  68% │ 312.10 │      - │      - │   - │  1%  │ strangle d20     │ IV rank 85, mean-reverting       │
│ COIN   │ sell_premium │  65% │ 198.40 │      - │      - │   - │  1%  │ iron_condor d16  │ IV rank 71, sideways range       │
└────────┴──────────────┴──────┴────────┴────────┴────────┴─────┴──────┴──────────────────┴──────────────────────────────────┘
```

**Interpretation:** TSLA is the top premium-selling candidate — IV rank 78 with neutral
trend is ideal for an iron condor. Sell the 16-delta wings ~35 DTE. MSTR has the highest
IV rank (85) but is more volatile; the strangle is smaller size (1%). NVDA IV is lower
but bullish bias makes the short put preferable to a condor.

---

## Example: `/market-scan backtest AAPL`

```
Strategy: momentum_crossover | AAPL | 2023-01-01 → 2025-12-31

  Total Return:        +47.3%
  Annualized Return:   +15.8%
  Sharpe Ratio:         1.42
  Max Drawdown:        -12.4%
  Win Rate:            58.3%
  Profit Factor:        1.87
  Avg Trade:           +1.9%
  Num Trades:           36

Walk-forward (6 windows):
  Consistent Sharpe > 1.0 in 5/6 windows
  Worst window: 2024-Q2 Sharpe 0.71 (NVDA sector rotation)
```

**Interpretation:** `momentum_crossover` on AAPL shows robust out-of-sample performance.
Sharpe 1.42 and 58% win rate with 1.87 profit factor is solid. The single weak window
in 2024-Q2 coincides with the NVDA-led tech rotation — AAPL underperformed the sector
briefly. Strategy holds up well across 5/6 walk-forward windows.

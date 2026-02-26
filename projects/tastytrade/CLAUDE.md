# Project: tastytrade

## Purpose
Options trading strategy and analysis platform built on the tasty-agent MCP server.

## Status
active

## Stack
- Python 3.11+ (uv, ruff, pytest)
- Pydantic v2 for all models
- Typer + Rich for CLI
- tasty-agent MCP server for brokerage connectivity

## Architecture
```
MCP Layer (tasty-agent)        ← brokerage connectivity, market data, order execution
  ↕ (Claude orchestrates)
Strategy Layer (this project)  ← screening, strategy construction, risk rules, journaling
```

Claude is the orchestrator. Typical flow:
1. MCP `get_market_metrics` → screener filters/ranks
2. MCP `get_option_chain` + `get_greeks` → strategy constructor
3. Risk check against portfolio rules
4. MCP `place_order(dry_run=True)` → review
5. Journal entry logged

## Key Files
- `src/tastytrade_strategy/models.py` - Core Pydantic types (OrderLeg, spreads, greeks, risk profiles)
- `src/tastytrade_strategy/strategies.py` - Construct spreads from strikes
- `src/tastytrade_strategy/screener.py` - Filter/rank symbols by IV rank, liquidity
- `src/tastytrade_strategy/risk.py` - Validate trades against portfolio risk rules
- `src/tastytrade_strategy/journal.py` - SQLite trade journal
- `src/tastytrade_strategy/cli.py` - Typer CLI
- `tests/` - Full test coverage (70 tests)

## Design Decisions
- **No MCP dependency in code.** Pure Python library. Produces dicts that Claude passes to MCP tools.
- **Models mirror MCP schemas exactly.** `OrderLeg.model_dump()` → straight to `place_order(legs=[...])`.
- **Decimal everywhere** for prices (serializes to float for MCP compat).
- **Spreads own their leg generation.** Each spread type has `to_order_legs()` → `list[OrderLeg]`.

## Usage
```bash
cd projects/tastytrade
uv sync --dev

# Run tests
uv run pytest tests/ -v

# CLI
uv run tt-strategy --help
uv run tt-strategy journal-list
uv run tt-strategy journal-stats
uv run tt-strategy screen-cmd metrics.json --iv-min 0.30
uv run tt-strategy risk-check portfolio.json --max-loss 3000 --max-profit 1500
```

## Current State (2026-02)

### Working
- Strategy construction (spreads, iron condors, strangles)
- Screener with IV rank filtering
- Risk validation against portfolio rules
- Trade journal (SQLite)
- Full test coverage (70 tests)

### Integration
- Works with market-agent for signal generation
- Claude orchestrates MCP calls to tasty-agent

## Screener Agent

Use this Task prompt to spawn a screener subagent. It absorbs all the market-data token cost and returns a compact ranked list.

```
subagent_type: "general-purpose"
model: "haiku"
prompt: |
  You are a tastytrade screener agent. Your job:
  1. Call MCP get_market_metrics(symbols=<SYMBOLS>) via the tasty-agent server
  2. Pipe the JSON response to the screener:
       echo '<MCP_RESPONSE>' | uv run -C /Users/drk/Code/claudecode/projects/tastytrade \
         tt-strategy screen-agent \
         --iv-min <IV_MIN> \
         --limit <LIMIT> \
         [--liq-min <LIQ>] [--beta-max <BETA>] [--earnings-days <DAYS>]
  3. Return the JSON output exactly as-is.

  Inputs:
  - symbols: <SYMBOLS>          # comma-separated e.g. "AAPL,TSLA,SPY"
  - iv_min: <IV_MIN>            # default 0.30
  - limit: <LIMIT>              # default 10
  - liq_min: <LIQ>              # optional, default none
  - beta_max: <BETA>            # optional, default none
  - earnings_days: <DAYS>       # optional, default 7

  Return only the JSON output from screen-agent. No commentary.
```

Output shape:
```json
{
  "count": 5,
  "criteria": { "iv_rank_min": "0.30", ... },
  "results": [
    {
      "symbol": "TSLA",
      "score": 72.4,
      "iv_rank": 0.85,
      "iv": 0.68,
      "hv": 0.42,
      "liquidity": 5.0,
      "beta": 1.8,
      "earnings_date": null,
      "reasons": ["High IV rank: 0.85", "Good liquidity: 5", "IV/HV edge: 1.62x"]
    }
  ]
}
```

## Chain Builder Agent

Use this Task prompt to spawn a chain-builder subagent. It absorbs option chain + greeks data and returns a compact order-ready strategy dict.

```
subagent_type: "general-purpose"
model: "haiku"
prompt: |
  You are a tastytrade chain-builder agent. Your job:
  1. Call MCP get_option_chain(symbol=<SYMBOL>, nested=True) via tasty-agent
  2. Save response to /tmp/chain.json
  3. Identify candidate strikes for target DTE <DTE> and strategy <STRATEGY>
  4. Call MCP get_greeks(symbols=[...candidate OCC symbols...]) for those strikes
  5. Save greeks response to /tmp/greeks.json
  6. Run the builder:
       uv run -C /Users/drk/Code/claudecode/projects/tastytrade \
         tt-strategy build-strategy <STRATEGY> \
         --dte <DTE> \
         --put-delta <PUT_DELTA> \
         --call-delta <CALL_DELTA> \
         --long-put-delta <LONG_PUT_DELTA> \
         --long-call-delta <LONG_CALL_DELTA> \
         --chain /tmp/chain.json \
         --greeks /tmp/greeks.json \
         --quantity <QUANTITY>
  7. Return the JSON output exactly as-is.

  Inputs:
  - symbol: <SYMBOL>            # e.g. "SPY"
  - strategy: <STRATEGY>        # short_put | vertical_spread | iron_condor | strangle
  - dte: <DTE>                  # target days to expiration, e.g. 45
  - put_delta: <PUT_DELTA>      # short put/call delta, e.g. 0.30
  - call_delta: <CALL_DELTA>    # default same as put_delta
  - long_put_delta: <LONG_PUT_DELTA>   # wing delta, e.g. 0.16
  - long_call_delta: <LONG_CALL_DELTA> # default same as long_put_delta
  - quantity: <QUANTITY>        # default 1

  Return only the JSON output. No commentary.
```

Output shape:
```json
{
  "strategy_type": "iron_condor",
  "underlying": "SPY",
  "expiration_date": "2024-04-19",
  "put_strikes": { "short": 490.0, "long": 485.0, "width": 5.0 },
  "call_strikes": { "short": 510.0, "long": 515.0, "width": 5.0 },
  "credit": 1.85,
  "quantity": 1,
  "legs": [
    { "symbol": "SPY   240419P00485000", "action": "Buy to Open", "quantity": 1, "option_type": "P", "strike_price": 485.0, "expiration_date": "2024-04-19" },
    ...
  ],
  "risk": { "max_profit": 185.0, "max_loss": 315.0, "breakevens": [488.15, 511.85], "risk_reward_ratio": 1.70 },
  "summary": "Iron Condor: SPY 2024-04-19 485/490/510/515 x1 @ 1.85"
}
```

## Risk Check Agent

Pipe `build-strategy` output directly into the risk check. Returns pass/fail with full detail.

```
subagent_type: "general-purpose"
model: "haiku"
prompt: |
  You are a tastytrade risk-check agent. Your job:
  1. Call MCP get_positions(account_number=<ACCOUNT>) via tasty-agent
  2. Call MCP get_balances(account_number=<ACCOUNT>) via tasty-agent
  3. Save combined response to /tmp/portfolio.json:
       {"positions": <positions_items>, "balances": <balances_data>}
  4. Run the risk check (piping the strategy JSON):
       echo '<STRATEGY_JSON>' | \
         uv run -C /Users/drk/Code/claudecode/projects/tastytrade \
           tt-strategy risk-agent /tmp/portfolio.json \
           [--max-position-pct <PCT>] \
           [--max-bp-pct <PCT>] \
           [--min-dte <DAYS>] \
           [--max-correlated <N>]
  5. Return the JSON output exactly as-is.

  Inputs:
  - account_number: <ACCOUNT>
  - strategy_json: <STRATEGY_JSON>   # output from build-strategy agent
  - max_position_pct: 0.05           # optional, fraction of NLV
  - max_bp_pct: 0.50                 # optional, fraction of buying power
  - min_dte: 7                       # optional
  - max_correlated: 3                # optional, max positions per underlying

  Return only the JSON output. No commentary.
```

Output shape:
```json
{
  "approved": true,
  "violations": [],
  "warnings": ["Position risk 4.2% approaching limit of 5.0%"],
  "summary": "APPROVED — SPY Iron Condor 2024-04-19",
  "strategy": { "type": "iron_condor", "underlying": "SPY", "max_loss": 315.0, ... },
  "portfolio": { "nlv": 100000.0, "buying_power": 50000.0, "open_positions": 3 },
  "checks": {
    "position_size_pct": 0.0315,
    "position_size_limit": 0.05,
    "bp_usage_after": 0.123,
    "bp_usage_limit": 0.5,
    "dte": 45,
    "dte_min": 7,
    "correlated_positions": 1,
    "correlated_limit": 3
  }
}
```

## Roadmap

Potential next areas (in no particular order):
- **market-agent integration** — wire signal pipeline so screener outputs feed directly into strategy construction
- **new strategy types** — calendar spreads, butterflies, ratio spreads, LEAPS
- **live trading orchestration loop** — screen → construct → risk check → dry-run → review → submit
- **journaling enhancements** — P&L tracking, trade analytics, win rate, expected value reporting
- **backtesting** — use tastytrade backtesting API (`backtester.vast.tastyworks.com`) to test strategies historically
- **account streaming** — real-time order/fill/position updates via account WebSocket
- **market data streaming** — DXLink WebSocket for live greeks, quotes, candles

## Notes
- tasty-agent MCP provides: portfolio, quotes, greeks, IV metrics, order management
- OAuth credentials required: client secret + refresh token from my.tastytrade.com
- Rate limit: 2 req/s enforced by MCP server
- Dry-run mode available for order testing
- Journal stored at `~/.tastytrade-strategy/journal.db`

## tastytrade API Reference

Docs: https://developer.tastytrade.com/
Archives in `docs/`:
- `docs/api-reference.md` — complete endpoint reference (auth, accounts, positions, instruments, chains, metrics, margin)
- `docs/orders.md` — order types, leg schema, JSON examples, lifecycle/status flow, complex orders
- `docs/streaming.md` — DXLink market data streaming + account data WebSocket
- `docs/backtesting.md` — backtesting API (`backtester.vast.tastyworks.com`)
- `docs/tastytrade-api-overview.md` — original overview (conventions, symbology, status codes)

### Auth
- OAuth2 bearer tokens via `POST /oauth/token`; expire every **15 minutes**
- Header: `Authorization: Bearer <token>`
- All requests need `User-Agent: <product>/<version>`

### Symbology
| Instrument | Format | Example |
|---|---|---|
| Equity | Alphanumeric | `AAPL`, `BRK/A` |
| Equity option | OCC: root(6) + yymmdd + P/C + strike×1000(8) | `AAPL  220617P00150000` |
| Future | `/<product><month><year>` | `/ESZ2` |
| Future option | `./[future] [option-product][date][type][strike]` | `./CLZ2 LO1X2 221104C91` |
| Crypto | `BASE/USD` | `BTC/USD` |

Month codes: F G H J K M N Q U V X Z (Jan–Dec)

### Order Constraints
- Max **4 legs** per order
- Cannot hold long + short simultaneously in same symbol
- Actions: `Buy to Open`, `Sell to Open`, `Buy to Close`, `Sell to Close`
- JSON keys are **dasherized** (e.g., `"order-type"`, `"time-in-force"`)

### Response Envelope
```json
{ "data": { "items": [...] }, "context": "..." }   // multi-object
{ "data": {...}, "context": "..." }                  // single object
{ "error": { "code": "...", "message": "..." } }    // error
```

### Key Status Codes
- `401` expired token (refresh needed) · `422` business logic rejection · `429` rate limited

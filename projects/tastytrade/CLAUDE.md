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

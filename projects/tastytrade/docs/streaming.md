# tastytrade Streaming Reference

Source: https://developer.tastytrade.com/streaming-market-data/, /streaming-account-data/
Archived: 2026-02-25

---

## Market Data Streaming (DXLink)

### Step 1: Get Quote Token
**GET** `/api-quote-tokens`

Response:
```json
{
  "data": {
    "token": "<token>",
    "dxlink-url": "wss://tasty-openapi-ws.dxfeed.com/realtime",
    "level": "api"
  }
}
```
- Token expires after **24 hours**
- Requires a full tastytrade account (not just login credentials)

### Step 2: Connect to DXLink WebSocket

Connect to the `dxlink-url` from the token response.

### Step 3: Message Sequence

**1. SETUP** — client sends protocol version + keepalive timeout; server confirms

**2. AUTH** — after receiving `AUTH_STATE: UNAUTHORIZED`, send the token; server returns `AUTH_STATE: AUTHORIZED` with user ID

**3. CHANNEL_REQUEST** — open a numbered channel; server returns `CHANNEL_OPENED` + format

**4. FEED_SETUP** — specify which fields to receive per event type:
```json
{
  "Trade":   ["eventType","eventSymbol","price","dayVolume","size"],
  "Quote":   ["eventType","eventSymbol","bidPrice","askPrice","bidSize","askSize"],
  "Greeks":  ["eventType","eventSymbol","volatility","delta","gamma","theta","rho","vega"],
  "Profile": ["eventType","eventSymbol","description","shortSaleRestriction","tradingStatus",
               "statusReason","haltStartTime","haltEndTime","highLimitPrice","lowLimitPrice",
               "high52WeekPrice","low52WeekPrice"],
  "Summary": ["eventType","eventSymbol","openInterest","dayOpenPrice","dayHighPrice",
               "dayLowPrice","prevDayClosePrice"]
}
```

**5. FEED_SUBSCRIPTION** — subscribe to symbols:
```json
{ "add": [{ "type": "Quote", "symbol": "AAPL" }] }
```
Unsubscribe:
```json
{ "remove": [{ "type": "Quote", "symbol": "AAPL" }] }
```

**6. KEEPALIVE** — send every **30 seconds** (60s timeout; 30s recommended interval) to maintain connection

### Supported Event Types
- `Trade` — last trade price, size, day volume
- `TradeETH` — extended hours trade
- `Quote` — bid/ask prices and sizes
- `Greeks` — vol, delta, gamma, theta, rho, vega
- `Profile` — instrument metadata, trading status, 52-week highs/lows
- `Summary` — open interest, OHLC, prev close
- `Candle` — time-aggregated OHLC (historical + live)

### Streamer Symbols

Use `streamer-symbol` field from instrument API responses, not the order symbol:
- Equities: use ticker directly (`AAPL`, `SPY`)
- Futures: `/6AM3` → `/6AM23:XCME`
- Future Options: use `call-streamer-symbol` / `put-streamer-symbol` from option chain

Streamer symbol sources:
- `GET /instruments/equities/{symbol}`
- `GET /instruments/futures`
- `GET /instruments/cryptocurrencies`
- `GET /option-chains/{underlying_symbol}/nested`
- `GET /futures-option-chains/{product_code}/nested`

### Candle Subscriptions (Historical OHLC)

Symbol format: `{SYMBOL}{=PERIODtype}`

Examples:
- `AAPL{=5m}` — 5-minute candles
- `SPY{=1h}` — 1-hour candles
- `/ES{=1d}` — daily candles for E-mini S&P

Period types: `m` (minutes), `h` (hours), `d` (days)

**Recommended intervals by time range:**

| Time Range | Interval |
|---|---|
| 1 day | `{=1m}` |
| 1 week | `{=5m}` |
| 1 month | `{=30m}` |
| 3 months | `{=1h}` |
| 6 months | `{=2h}` |
| 1+ year | `{=1d}` |

**Note:** The last candle is always "live" (updating until the period closes). Requesting 12 months of 1-minute data ≈ 500k events — use appropriate granularity.

Also include `fromTime` (Unix epoch ms) to specify the data window start.

---

## Account Data Streaming

### WebSocket Hosts
- Production: `wss://streamer.tastyworks.com`
- Sandbox: `wss://streamer.cert.tastyworks.com`

### Connection Sequence (order matters)
1. Open WebSocket
2. Subscribe to accounts (`connect` action)
3. Send periodic heartbeats

**Critical:** Sending heartbeats before `connect` returns `"not implemented"` error.

### Message Format
All messages include `auth-token` (same Bearer token used for REST):

```json
{
  "action": "<action>",
  "value": "<value>",
  "auth-token": "<bearer_token>",
  "request-id": 1
}
```

### Actions

**Subscribe to accounts:**
```json
{
  "action": "connect",
  "value": ["5WT00000", "5WT00001"],
  "auth-token": "<token>",
  "request-id": 2
}
```

**Heartbeat** (send every 2s–60s):
```json
{
  "action": "heartbeat",
  "auth-token": "<token>",
  "request-id": 1
}
```

**Subscribe to public watchlist updates:**
```json
{ "action": "public-watchlists-subscribe", "auth-token": "<token>" }
```

**Subscribe to quote alerts:**
```json
{ "action": "quote-alerts-subscribe", "auth-token": "<token>" }
```

**Subscribe to user messages:**
```json
{
  "action": "user-message-subscribe",
  "value": "<user_external_id>",
  "auth-token": "<token>"
}
```

### Incoming Notification Format

All notifications are **complete object representations** (not partial/differential):

```json
{
  "type": "Order",
  "data": {
    "id": 1,
    "account-number": "5WT00000",
    "time-in-force": "Day",
    "order-type": "Market",
    "size": 100,
    "underlying-symbol": "AAPL",
    "underlying-instrument-type": "Equity",
    "status": "Live",
    "cancellable": true,
    "editable": true,
    "edited": false,
    "legs": [
      {
        "instrument-type": "Equity",
        "symbol": "AAPL",
        "quantity": 100,
        "remaining-quantity": 100,
        "action": "Buy to Open",
        "fills": []
      }
    ]
  },
  "timestamp": 1688595114405
}
```

**Streamed data types:** Orders (status changes, fills), Balances, Positions, Quote alerts, Watchlist updates

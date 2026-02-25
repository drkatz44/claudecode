# tastytrade API Reference

Source: https://developer.tastytrade.com
Archived: 2026-02-25

---

## Base URLs

| Environment | REST | WebSocket (Account) |
|---|---|---|
| Production | `https://api.tastyworks.com` | `wss://streamer.tastyworks.com` |
| Sandbox | `https://api.cert.tastyworks.com` | `wss://streamer.cert.tastyworks.com` |

Backtesting API: `https://backtester.vast.tastyworks.com`

---

## Authentication

### Token Endpoint
**POST** `/oauth/token`

```
grant_type=refresh_token
refresh_token=<your_refresh_token>
client_secret=<your_client_secret>
scope=read trade
```

Response:
```json
{
  "access_token": "<bearer_token>",
  "expires_in": 900,
  "token_type": "Bearer"
}
```

- Tokens expire after **15 minutes** (900s); cannot be extended, must refresh
- Subtract ~30s for clock skew in practice
- Missing/expired token → HTTP 401

### Required Headers (all requests)
```
Authorization: Bearer <access_token>
Content-Type: application/json
Accept: application/json
User-Agent: <product>/<version>
```

Optional versioning header: `Accept-Version: YYYYMMDD`

---

## Conventions

- JSON keys: **dasherized** (`"this-key-is-dasherized"`)
- GET: parameters as query strings; arrays as `my-key[]=val1&my-key[]=val2`
- POST/PUT/PATCH/DELETE: JSON body

### Response Envelope
```json
// Single object
{ "data": {...}, "context": "/endpoint/path" }

// Array
{ "data": { "items": [...] }, "context": "/endpoint/path" }

// Error
{ "error": { "code": "error_code", "message": "Human readable message" } }
```

### HTTP Status Codes
| Code | Meaning |
|---|---|
| 400 | Invalid request parameters |
| 401 | Expired/invalid token |
| 403 | Insufficient permission |
| 404 | Endpoint or resource not found |
| 422 | Business logic rejection |
| 429 | Rate limit exceeded |
| 500 | Server error |

---

## Symbology

| Instrument | Format | Example |
|---|---|---|
| Equity | Alphanumeric | `AAPL`, `BRK/A` |
| Equity Option | OCC: root(6 padded) + yymmdd + P/C + strike×1000(8 digits) | `AAPL  220617P00150000` |
| Future | `/product+month+year` | `/ESZ2` |
| Future Option | `./[future] [option-product][date][type][strike]` | `./CLZ2 LO1X2 221104C91` |
| Cryptocurrency | `BASE/QUOTE` | `BTC/USD` |

**Month codes:** F=Jan G=Feb H=Mar J=Apr K=May M=Jun N=Jul Q=Aug U=Sep V=Oct X=Nov Z=Dec

For streaming, use `streamer-symbol` from instrument API responses (e.g., `/6AM3` → `/6AM23:XCME`).

---

## Customer & Account Endpoints

### Customer
- `GET /customers/me` — current customer profile
- `GET /customers/me/accounts` — list all accounts; items include `account.account-number`, `account.margin-or-cash`
- `GET /customers/me/accounts/{account_number}` — single account

### Quote Token
- `GET /api-quote-tokens` — DXLink streaming token (expires 24h)

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

### Account Status & Risk
- `GET /accounts/{account_number}/trading-status` — which strategies the account can trade
- `GET /accounts/{account_number}/position-limit` — position limit
- `GET /accounts/{account_number}/margin-requirements/{underlying_symbol}/effective`

---

## Positions & Balances

### Positions
- `GET /accounts/{account_number}/positions` — all positions
  - Query: `symbol`, `underlying-symbol`
  - Response fields: `symbol`, `quantity` (always positive), `quantity-direction` (`Long`/`Short`), `instrument-type`

### Balances
- `GET /accounts/{account_number}/balances` — real-time balances
  - Fields: `cash-balance`, `available-trading-funds`, buying power, position values
- `GET /accounts/{account_number}/balance-snapshots` — most recent snapshot + current
- `GET /accounts/{account_number}/net-liq` — current net liquidating value
- `GET /accounts/{account_number}/net-liq/history` — historical net liq snapshots

---

## Transactions
- `GET /accounts/{account_number}/transactions` — paginated history (default: Desc)
  - Query: `sort` (`Asc`/`Desc`), date range params
  - Fields: `description`, `transaction-sub-type` (fills, dividends, fees, deposits, withdrawals)
- `GET /accounts/{account_number}/transactions/{id}` — single transaction
- `GET /accounts/{account_number}/transactions/total-fees` — total fees for a given day

---

## Instruments

### Cryptocurrencies
- `GET /instruments/cryptocurrencies` — all (filter by `symbol[]`)
- `GET /instruments/cryptocurrencies/{symbol}` — single (URL-encode: `BTC%2FUSD`)

### Equities
- `GET /instruments/equities/active` — all active equities (paginated)
- `GET /instruments/equities` — set by `symbol[]`
- `GET /instruments/equities/{symbol}` — single
  - Check `is-fractional-quantity-eligible` for Notional Market eligibility

### Equity Options
- `GET /instruments/equity-options` — set by `symbol[]`; params: `active` (bool), `withExpired` (bool)
- `GET /instruments/equity-options/{symbol}` — single (OCC symbol)

### Futures
- `GET /instruments/futures` — set; filter by `product-code`
- `GET /instruments/futures/{symbol}` — single (e.g., `/CLU3`)
- `GET /instruments/future-products` — metadata for all futures products
- `GET /instruments/future-products/{exchange}/{code}` — single (e.g., `CME`/`ES`)

### Future Options
- `GET /instruments/future-options` — set by `symbol[]`
- `GET /instruments/future-options/{symbol}` — single
- `GET /instruments/future-option-products` — metadata
- `GET /instruments/future-option-products/{exchange}/{root_symbol}` — single

### Miscellaneous
- `GET /instruments/quantity-decimal-precisions`
- `GET /instruments/warrants` — set (queryParams supported)
- `GET /instruments/warrants/{symbol}`

### Symbol Search
- `GET /symbols/search/{symbol}` — search results array

---

## Option Chains

### Equity Options
- `GET /option-chains/{underlying_symbol}` — full instrument data
- `GET /option-chains/{underlying_symbol}/nested` — grouped by expiration (**recommended**)
- `GET /option-chains/{underlying_symbol}/compact` — flat, minimal

Nested response shape:
```
response[]
  .expirations[]
    .strikes[]
      .call  (OCC symbol)
      .put   (OCC symbol)
```

### Futures Options
- `GET /futures-option-chains/{product_code}` — e.g., `ES`
- `GET /futures-option-chains/{product_code}/nested`

Nested strike shape:
```json
{
  "strike-price": "5750.0",
  "call": "./ESU4 EW4Q4 240823C5750",
  "call-streamer-symbol": "./EW4Q24C5750:XCME",
  "put": "./ESU4 EW4Q4 240823P5750",
  "put-streamer-symbol": "./EW4Q24P5750:XCME"
}
```

---

## Market Metrics

- `GET /market-metrics` — IV data for symbols; query: `symbols[]`
- `GET /market-metrics/historic-corporate-events/dividends/{symbol}`
- `GET /market-metrics/historic-corporate-events/earnings-reports/{symbol}`

---

## Margin

- `GET /margin/accounts/{account_number}/requirements` — current margin/capital requirements
- `POST /margin/accounts/{account_number}/dry-run` — estimate margin for hypothetical order (same body as order submission)

---

## Watchlists

- `GET /public-watchlists` — tastytrade curated (optional: `counts-only`)
- `GET /public-watchlists/{name}`
- `GET /pairs-watchlists` / `GET /pairs-watchlists/{name}`
- `GET /watchlists` — user watchlists
- `GET /watchlists/{name}`
- `POST /watchlists` — create
- `PUT /watchlists/{name}` — replace
- `DELETE /watchlists/{name}`

---

## Sandbox Notes

- Base URL: `https://api.cert.tastyworks.com`
- WebSocket: `wss://streamer.cert.tastyworks.com`
- Resets every 24 hours (trades/positions cleared; users/accounts preserved)
- Quotes always 15-minute delayed
- Register at: https://developer.tastytrade.com/sandbox/

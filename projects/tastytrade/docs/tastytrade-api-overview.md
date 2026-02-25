# tastytrade API Overview

Source: https://developer.tastytrade.com/api-overview/
Archived: 2026-02-24

---

## API Conventions (REST / JSON)

- All requests must include a `User-Agent` header: `<product>/<version>`
- `Content-Type` and `Accept` headers: `application/json`
- JSON keys are **dasherized** in requests and responses (e.g., `"this-key-is-dasherized"`)
- GET parameters sent via URL query string; arrays as `key[]=value`
- Other methods (POST/PUT/DELETE) use JSON body

### Response Format
```json
{ "data": {...}, "context": "..." }
```
Multi-object responses:
```json
{ "data": { "items": [...] }, "context": "..." }
```
Error responses:
```json
{ "error": { "code": "...", "message": "..." } }
```

---

## Authentication

- **Method**: OAuth2 bearer tokens
- **Token endpoint**: `POST /oauth/token`
- **Token lifetime**: 15 minutes — must be refreshed on expiry
- **Header format**: `Authorization: Bearer <access_token>`
- Requests without Authorization header → HTTP 401
- Expired tokens → HTTP 401

---

## Symbology

### Equities
Alphanumeric, occasional `/` (e.g., `AAPL`, `BRK/A`)

### Equity Options (OCC format)
`<root>(6, space-padded)<yymmdd><P|C><strike(8 digits, ×1000)>`

Example: `AAPL  220617P00150000` = AAPL June 17 2022 $150 Put

### Futures
Slash-prefixed: `/<product><month><year>`

Example: `/ESZ2` = E-mini S&P 500 December 2022

Month codes: F=Jan G=Feb H=Mar J=Apr K=May M=Jun N=Jul Q=Aug U=Sep V=Oct X=Nov Z=Dec

### Future Options
`./[future]/[option-product][date][type][strike]`

Example: `./CLZ2 LO1X2 221104C91`

### Cryptocurrencies
Retrieved via `GET /instruments/cryptocurrencies`
Examples: `BTC/USD`, `BCH/USD`

---

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 400  | Invalid request parameters |
| 401  | Expired or invalid token/credentials |
| 403  | Insufficient authorization for resource |
| 404  | Endpoint or resource not found |
| 422  | Unprocessable (business logic rejection — invalid action context) |
| 429  | Rate limit exceeded |
| 500  | Server error (includes support identifier) |

---

## Core Concepts

### Orders
- Maximum **4 legs** per order
- Each leg: symbol, quantity, action (direction + effect)
  - `Buy to Open` — increases position
  - `Sell to Close` — decreases existing position
- Cannot hold simultaneous long AND short position in same symbol
- Quantity always positive; direction flips to short if selling past zero

### Positions
- One position per symbol
- Created when orders fill
- Include: symbol, quantity, direction (long/short)

### Accounts
- All API endpoints are account-scoped
- One account per request

### Trading Statuses
- Linked to account privileges: futures, crypto, options strategies

### Balances
- Real-time: cash, buying power, position values, net liquidating value

### Transactions
- Historical ledger: fills, dividends, fees, deposits, withdrawals

### Instruments
- Single tradeable securities identified by unique symbol

---

## Streaming

- WebSocket-based streaming for market data and account updates
- **DXLink streamer** used for market data (separate symbology)

---

## Key Endpoints (referenced in docs)

- `POST /oauth/token` — auth token
- `GET /instruments/cryptocurrencies` — crypto symbols
- Accounts: status, positions, balances, transactions
- Orders: placement (up to 4 legs), status
- Options chains, greeks
- Market data, quotes
- Margin requirements, risk parameters

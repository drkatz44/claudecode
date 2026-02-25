# tastytrade Orders Reference

Source: https://developer.tastytrade.com/order-submission/, /order-flow/, /order-management/
Archived: 2026-02-25

---

## Order Endpoints

| Action | Method | Endpoint |
|---|---|---|
| Search orders | GET | `/accounts/{account_number}/orders` |
| Live orders (today) | GET | `/accounts/{account_number}/orders/live` |
| Single order | GET | `/accounts/{account_number}/orders/{id}` |
| Dry run | POST | `/accounts/{account_number}/orders/dry-run` |
| Submit order | POST | `/accounts/{account_number}/orders` |
| Cancel | DELETE | `/accounts/{account_number}/orders/{id}` |
| Cancel-replace | PUT | `/accounts/{account_number}/orders/{id}` |
| Edit price/execution | PATCH | `/accounts/{account_number}/orders/{id}` |
| Reconfirm | POST | `/accounts/{account_number}/orders/{id}/reconfirm` |
| Replacement dry run | POST | `/accounts/{account_number}/orders/{id}/dry-run` |
| Customer orders | GET | `/customers/{customer_id}/orders` |
| Customer live orders | GET | `/customers/{customer_id}/orders/live` |

### Search Query Parameters
- `start-date` / `end-date`
- `underlying-symbol`
- `status[]` — filter by status
- `futures-symbol`
- `underlying-instrument-type`
- `sort` — `Asc` or `Desc` (default: `Desc`)
- `start-at` / `end-at`

### Cancel-Replace Modifiable Fields
Only these fields may change: `price`, `order-type`, `time-in-force`. All other params must match original.

---

## Order Types

| Type | Price Required | Notes |
|---|---|---|
| `Limit` | Yes (`price` + `price-effect`) | Fills at specified price or better |
| `Market` | No | Single leg only; no GTC; market must be open |
| `Stop` | No (`stop-trigger` required) | Market order triggered at stop price; no GTC for opening orders |
| `Stop Limit` | Yes + `stop-trigger` | Limit order triggered at stop price |
| `Notional Market` | No (`value` + `value-effect`) | Dollar-amount based; single leg; crypto + fractional-eligible equities only; market must be open for opening |

---

## Order Body Schema

### Root Level Fields

| Field | Required | Type | Notes |
|---|---|---|---|
| `time-in-force` | Yes | String | `Day`, `GTC`, `GTD` |
| `order-type` | Yes | String | See Order Types above |
| `price` | Conditional | Decimal | Limit and Stop Limit only |
| `price-effect` | Conditional | String | `Debit` or `Credit` |
| `gtc-date` | Conditional | String `yyyy-mm-dd` | GTD orders only |
| `legs` | Yes | Array | Min 1 leg |
| `stop-trigger` | Conditional | Decimal | Stop and Stop Limit |
| `value` | Conditional | Decimal | Notional Market only |
| `value-effect` | Conditional | String | `Debit` or `Credit` |
| `source` | No | String | Origin label |
| `advanced-instructions` | No | Object | See below |

### Leg Fields

| Field | Required | Type | Notes |
|---|---|---|---|
| `action` | Yes | String | See Leg Actions |
| `instrument-type` | Yes | String | See Instrument Types |
| `quantity` | Conditional | Decimal | Not for Notional Market; must be positive; integers for all except crypto |
| `symbol` | Yes | String | Unique per leg |

### Leg Actions
- `Buy to Open` — initiate long (cannot have existing short)
- `Sell to Open` — initiate short (cannot have existing long)
- `Buy to Close` — exit short (must have existing short)
- `Sell to Close` — exit long (must have existing long)
- `Buy` / `Sell` — futures outright single-leg only (system converts automatically)

### Instrument Types
`Equity`, `Equity Option`, `Future`, `Future Option`, `Cryptocurrency`

### Leg Constraints
- Equities, Futures, Cryptocurrency: **max 1 leg**
- Equity Options, Future Options: **max 4 legs**
- All legs must have distinct symbols

### Advanced Instructions
```json
{ "strict-position-effect-validation": true }
```
When `true`, closing actions require an existing position. Default is `false` (permissive).

---

## JSON Examples

### Bull Call Spread (Limit, Day)
```json
{
  "time-in-force": "Day",
  "order-type": "Limit",
  "price": "1.09",
  "price-effect": "Debit",
  "legs": [
    {
      "action": "Buy to Open",
      "symbol": "AAPL 230818C00197500",
      "quantity": 1,
      "instrument-type": "Equity Option"
    },
    {
      "action": "Sell to Open",
      "symbol": "AAPL 230818C00200000",
      "quantity": 1,
      "instrument-type": "Equity Option"
    }
  ]
}
```

### Equity Market Order
```json
{
  "time-in-force": "Day",
  "order-type": "Market",
  "legs": [
    {
      "instrument-type": "Equity",
      "symbol": "AAPL",
      "quantity": 100,
      "action": "Buy to Open"
    }
  ]
}
```

### Stop Order (GTC)
```json
{
  "time-in-force": "GTC",
  "order-type": "Stop",
  "stop-trigger": 105,
  "legs": [
    {
      "instrument-type": "Equity",
      "symbol": "AAPL",
      "quantity": 100,
      "action": "Sell to Close"
    }
  ]
}
```

### Stop Limit Order
```json
{
  "time-in-force": "GTC",
  "order-type": "Stop Limit",
  "stop-trigger": 110,
  "price": 115,
  "price-effect": "Debit",
  "legs": [
    {
      "instrument-type": "Equity",
      "symbol": "AAPL",
      "quantity": 100,
      "action": "Buy to Open"
    }
  ]
}
```

### Notional Market (Cryptocurrency)
```json
{
  "time-in-force": "Day",
  "order-type": "Notional Market",
  "value": 10,
  "value-effect": "Debit",
  "legs": [
    {
      "instrument-type": "Cryptocurrency",
      "symbol": "BTC/USD",
      "action": "Buy to Open"
    }
  ]
}
```

### With Strict Position Validation
```json
{
  "time-in-force": "Day",
  "order-type": "Limit",
  "price": 175.25,
  "price-effect": "Credit",
  "advanced-instructions": {
    "strict-position-effect-validation": true
  },
  "legs": [
    {
      "instrument-type": "Equity",
      "quantity": 100,
      "symbol": "META",
      "action": "Sell to Close"
    }
  ]
}
```

---

## Dry Run Response

```
buying-power-effect:
  change-in-margin-requirement / effect
  change-in-buying-power / effect
  current/new buying-power / effect
  isolated-order-margin-requirement
  is-spread
  impact
  effect

fee-calculation:
  regulatory-fees / effect
  clearing-fees / effect
  commission / effect
  proprietary-index-option-fees / effect
  total-fees / effect

warnings: []

order:
  id, account-number, time-in-force, order-type, size
  underlying-symbol, underlying-instrument-type
  status, cancellable, editable, edited
  legs[]:
    instrument-type, symbol, quantity, remaining-quantity, action, fills[]
```

---

## Order Lifecycle (Status Flow)

### Phase 1 — Submission
`Received` → `Routed` → `In Flight`

- `Received` — submitted during market closure; will route when open
- `Routed` — being submitted to exchange
- `In Flight` — left system, awaiting exchange confirmation
- `Contingent` — complex/replacement order waiting for trigger

### Phase 2 — Working
`Live` → `Cancel Requested` | `Replace Requested`

- `Live` — exchange confirmed; eligible for cancellation/replacement
- `Cancel Requested` — cancellation pending at exchange
- `Replace Requested` — original awaiting cancel so replacement can route

### Phase 3 — Terminal (final, no further updates)
`Filled` | `Canceled` | `Rejected` | `Expired` | `Removed` | `Partially Removed`

### Common Flows
```
Normal fill:     Received → Routed → In Flight → Live → Filled
Cancellation:    ... → Live → Cancel Requested → Canceled
Day expiration:  ... → Live → Expired
Early rejection: Received → Rejected
```

---

## Complex Orders

### Types
- **OTOCO** (One-Triggers-One-Cancels-Other): entry + stop loss + profit target; contingents cancel each other on fill
- **OTO** (One-Triggers-Other): entry + up to 3 contingents; all route on fill, no auto-cancel
- **OCO** (One-Cancels-Other): no trigger; two closing orders; one fills → other cancels

### Endpoints
- `POST /accounts/{account_number}/complex-orders` — submit
- `DELETE /accounts/{account_number}/complex-orders/{id}` — cancel (use complex order ID, not sub-order IDs)
- `GET /accounts/{account_number}/complex-orders/{id}` — fetch

---

## Validation Rules

1. No overlapping symbols within a single order
2. Closing actions require existing positions (unless `strict-position-effect-validation: false`)
3. Cannot include both `price` and `value` in the same order
4. Market orders cannot open during market closure
5. Notional Market orders cannot open during market closure
6. Market and Stop orders cannot use GTC for opening orders

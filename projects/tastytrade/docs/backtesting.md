# tastytrade Backtesting API Reference

Source: https://developer.tastytrade.com/open-api-spec/backtesting/
Archived: 2026-02-25

Base URL: `https://backtester.vast.tastyworks.com`

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/backtests` | List all user backtests (returns array of IDs) |
| POST | `/backtests` | Create a new backtest |
| GET | `/backtests/{id}` | Get backtest details |
| GET | `/backtests/{id}/logs` | Get backtest logs |
| POST | `/backtests/{id}/cancel` | Cancel running backtest (204 No Content) |
| GET | `/available-dates` | List available historical date ranges per symbol |
| POST | `/simulate-trade` | Get historical prices for a trade scenario |

### POST /backtests Response Codes
- `200` — Backtest ready immediately (BacktestGet)
- `201` — Backtest pending/running (BacktestGet)

---

## Schemas

### BacktestPost

```json
{
  "symbol": "AAPL",
  "startDate": "2023-01-01",
  "endDate": "2023-12-31",
  "legs": [...],
  "entryConditions": {...},
  "exitConditions": {...}
}
```

### BacktestGet (response)

```json
{
  "id": "string",
  "symbol": "AAPL",
  "startDate": "2023-01-01",
  "endDate": "2023-12-31",
  "legs": [...],
  "entryConditions": {...},
  "exitConditions": {...},
  "ETA": 12.5,
  "progress": 0.45,
  "status": "pending | running | completed",
  "statistics": [...],
  "trials": [...],
  "snapshots": [...],
  "notices": ["string"]
}
```

### Leg

Required fields: `type`, `direction`, `quantity`, `strikeSelection`, `daysUntilExpiration`

```json
{
  "type": "equity | equity-option",
  "direction": "long | short",
  "side": "call | put",
  "quantity": 1,
  "strikeSelection": "delta | percentageOTM | percentageOTMRelative | currentPriceOffset | currentPriceOffsetRelative | currentPriceExactOffsetRelative | premium",
  "strikeRelativeLeg": 0,
  "delta": 30,
  "percentageOTM": 5.0,
  "currentPriceOffset": 5.0,
  "premium": 1.50,
  "daysUntilExpiration": 45
}
```

- `quantity`: integer 1–100
- `delta`: integer 1–100 (e.g., `30` = 0.30 delta)
- `currentPriceOffset` / `premium`: max 50000
- `strikeRelativeLeg`: index of another leg to use as reference for relative strike methods

### EntryConditions

```json
{
  "frequency": "every day | on specific days of the week | on exact days to expiration match",
  "specificDays": [1, 3, 5],
  "maximumActiveTrials": 1,
  "maximumActiveTrialsBehavior": "don't enter | close oldest",
  "minimumVIX": 15,
  "maximumVIX": 30
}
```

All fields nullable/optional.

- `frequency`: how often to look for entry
- `specificDays`: day-of-week integers (used with `on specific days of the week`)
- `maximumActiveTrials`: cap on concurrent open trades
- `maximumActiveTrialsBehavior`: what to do when cap is hit — skip entry or close oldest trade
- `minimumVIX` / `maximumVIX`: VIX filter for entry

### ExitConditions

```json
{
  "takeProfitPercentage": 50,
  "stopLossPercentage": 200,
  "afterDaysInTrade": 21,
  "atDaysToExpiration": 7,
  "minimumVIX": 40
}
```

All fields nullable/optional. All integers.

- `takeProfitPercentage`: close at X% of max profit
- `stopLossPercentage`: close at X% of max loss
- `afterDaysInTrade`: close after N days in trade
- `atDaysToExpiration`: close when N DTE reached
- `minimumVIX`: close if VIX spikes above threshold

### Trial (in response)

```json
{
  "openDateTime": "2023-06-15T14:30:00Z",
  "closeDateTime": "2023-07-06T14:30:00Z",
  "profitLoss": 125.00
}
```

### Snapshot (in response)

```json
{
  "dateTime": "2023-06-20T14:30:00Z",
  "profitLoss": 45.00,
  "underlyingPrice": 185.50
}
```

---

## POST /simulate-trade

Returns historical prices for a hypothetical trade across a date range.

### Request Body
```json
{
  "legs": [
    {
      "type": "equity-option",
      "side": "call",
      "direction": "long",
      "strikeSelection": "delta",
      "delta": 0.30,
      "daysUntilExpiration": 45
    }
  ]
}
```

### Response
Array of price objects:
```json
[
  {
    "dateTime": "2023-06-15T14:30:00Z",
    "price": 2.45,
    "effect": "Debit",
    "underlyingPrice": 185.50,
    "delta": 0.31
  }
]
```

---

## GET /available-dates

Returns available historical data ranges per symbol:
```json
[
  {
    "symbol": "AAPL",
    "startDate": "2010-01-04",
    "endDate": "2024-12-31"
  }
]
```

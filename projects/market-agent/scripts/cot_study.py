#!/usr/bin/env python3
"""Commodity COT Toggle Study — multi-commodity commercial hedger analysis.

Based on Dave Druz's methodology: use CFTC commercial positioning to label
historical price data, identify toggle dates (regime shifts), compute forward
returns, determine optimal exit criteria, and recommend strategies.

Usage:
    uv run python scripts/cot_study.py gold
    uv run python scripts/cot_study.py oil
    uv run python scripts/cot_study.py silver
    uv run python scripts/cot_study.py natgas

Data sources:
  - Legacy COT (1986-present):  CFTC Socrata 6dca-aqww
  - Disaggregated COT (2006-present): CFTC Socrata 72hh-3qpy
  - Prices: Stooq (gold, silver) | FRED (oil, natgas) | yfinance fallback

Output: ~/.market-agent/studies/{commodity}/
    annotated.csv   — merged weekly dataset
    toggles.csv     — toggle events with forward returns + exit info
    study.png       — COT vs price chart with toggle markers
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass, field
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STUDY_BASE   = Path.home() / ".market-agent" / "studies"
LEGACY_URL   = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
DISAGG_URL   = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"

PERCENTILE_WINDOW = 156    # weeks (~3 years)
TOGGLE_EXTREME    = 20     # bottom/top N%
SMA_WINDOW        = 20     # weeks, tactical stop
SMA200_WINDOW     = 200    # weeks, macro trend filter
FORWARD_HORIZONS  = [4, 8, 13, 26, 52]


@dataclass
class CommodityConfig:
    name:         str
    cftc_code:    str          # legacy + disagg market code
    price_source: str          # "stooq" | "fred"
    price_symbol: str          # Stooq symbol or FRED series ID
    price_label:  str
    price_unit:   str
    eras: list[tuple] = field(default_factory=list)  # (label, start, end)
    log_scale:    bool = True
    clip_price_min: float = 0.01  # for log scale; clips negatives/zero


COMMODITIES: dict[str, CommodityConfig] = {
    "gold": CommodityConfig(
        name="Gold",
        cftc_code="088691",
        price_source="stooq",
        price_symbol="xauusd",
        price_label="Gold price (USD/troy oz)",
        price_unit="USD/oz",
        eras=[
            ("Bear / Flat", "1986-01-01", "2000-01-01"),
            ("Secular Bull", "2000-01-01", "2012-01-01"),
            ("Consolidation / New Bull", "2012-01-01", "2030-01-01"),
        ],
    ),
    "silver": CommodityConfig(
        name="Silver",
        cftc_code="084691",
        price_source="stooq",
        price_symbol="xagusd",
        price_label="Silver price (USD/troy oz)",
        price_unit="USD/oz",
        eras=[
            ("Bear Era", "1986-01-01", "2004-01-01"),
            ("Bull Era", "2004-01-01", "2012-01-01"),
            ("Consolidation", "2012-01-01", "2030-01-01"),
        ],
    ),
    "oil": CommodityConfig(
        name="WTI Crude Oil",
        cftc_code="067651",
        price_source="fred",
        price_symbol="DCOILWTICO",
        price_label="WTI price (USD/bbl)",
        price_unit="USD/bbl",
        clip_price_min=1.0,   # 2020 COVID negative price event
        eras=[
            ("Low-price era", "1986-01-01", "2000-01-01"),
            ("Bull / Volatility", "2000-01-01", "2015-01-01"),
            ("Shale / New Range", "2015-01-01", "2030-01-01"),
        ],
    ),
    "natgas": CommodityConfig(
        name="Natural Gas",
        cftc_code="023651",
        price_source="fred",
        price_symbol="DHHNGSP",    # Henry Hub daily spot
        price_label="Henry Hub price (USD/MMBtu)",
        price_unit="USD/MMBtu",
        eras=[
            ("Regulated Era", "1990-01-01", "2000-01-01"),
            ("Boom/Bust", "2000-01-01", "2012-01-01"),
            ("Shale Glut", "2012-01-01", "2030-01-01"),
        ],
    ),
}


# ---------------------------------------------------------------------------
# Price fetchers
# ---------------------------------------------------------------------------

def _fetch_stooq(symbol: str, start: str, end: str) -> pd.DataFrame:
    url = "https://stooq.com/q/d/l/?s={}&d1={}&d2={}&i=w".format(
        symbol, start.replace("-", ""), end.replace("-", ""),
    )
    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    if "Date" not in df.columns or "Close" not in df.columns:
        raise ValueError(f"Stooq returned unexpected data for {symbol}: {resp.text[:200]}")
    df = df.rename(columns={"Date": "date", "Close": "price"})[["date", "price"]]
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").dropna(subset=["price"]).reset_index(drop=True)


def _fetch_fred(series_id: str, start: str, end: str) -> pd.DataFrame:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    resp = requests.get(url, params={"id": series_id}, timeout=30,
                        headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = ["date", "price"]
    df["date"]  = pd.to_datetime(df["date"])
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    # Resample daily → weekly (last valid price)
    df = df.set_index("date").resample("W-FRI").last().reset_index()
    df = df.dropna(subset=["price"])
    mask = (df["date"] >= start) & (df["date"] <= end)
    return df.loc[mask].sort_values("date").reset_index(drop=True)


def fetch_prices(cfg: CommodityConfig, start: str, end: str) -> pd.DataFrame:
    print(f"Fetching {cfg.name} prices ({cfg.price_source.upper()} {cfg.price_symbol})...")
    if cfg.price_source == "stooq":
        df = _fetch_stooq(cfg.price_symbol, start, end)
    elif cfg.price_source == "fred":
        df = _fetch_fred(cfg.price_symbol, start, end)
    else:
        raise ValueError(f"Unknown price source: {cfg.price_source}")
    print(f"  {len(df)} bars  {df['date'].iloc[0].date()} – {df['date'].iloc[-1].date()}"
          f"  range: {df['price'].min():.2f} – {df['price'].max():.2f} {cfg.price_unit}")
    return df


# ---------------------------------------------------------------------------
# COT fetchers
# ---------------------------------------------------------------------------

def _paginate_cftc(url: str, code: str, extra: dict | None = None) -> list[dict]:
    all_rows: list[dict] = []
    limit, offset = 1000, 0
    while True:
        params = {
            "cftc_contract_market_code": code,
            "$order": "report_date_as_yyyy_mm_dd ASC",
            "$limit": str(limit),
            "$offset": str(offset),
            **(extra or {}),
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < limit:
            break
        offset += limit
    return all_rows


def fetch_legacy_cot(code: str) -> pd.DataFrame:
    print(f"Fetching legacy COT (1986-present, code={code})...")
    rows = _paginate_cftc(LEGACY_URL, code)
    print(f"  {len(rows)} records")
    records = []
    for row in rows:
        try:
            records.append({
                "date":       pd.to_datetime(row["report_date_as_yyyy_mm_dd"][:10]),
                "comm_long":  int(row.get("comm_positions_long_all",   0)),
                "comm_short": int(row.get("comm_positions_short_all",  0)),
                "nc_long":    int(row.get("noncomm_positions_long_all",  0)),
                "nc_short":   int(row.get("noncomm_positions_short_all", 0)),
                "oi":         int(row.get("open_interest_all",           0)),
            })
        except (KeyError, ValueError, TypeError):
            continue
    df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    df["comm_net"] = df["comm_long"] - df["comm_short"]
    df["nc_net"]   = df["nc_long"]   - df["nc_short"]
    return df


def fetch_disagg_cot(code: str) -> pd.DataFrame:
    print(f"Fetching disaggregated COT (2006-present, code={code})...")
    rows = _paginate_cftc(DISAGG_URL, code)
    print(f"  {len(rows)} records")
    if not rows:
        return pd.DataFrame(columns=["date", "prod_merc_net", "mm_net"])
    records = []
    for row in rows:
        try:
            records.append({
                "date":           pd.to_datetime(row["report_date_as_yyyy_mm_dd"][:10]),
                "prod_merc_long":  int(row.get("prod_merc_positions_long",  0)),
                "prod_merc_short": int(row.get("prod_merc_positions_short", 0)),
                "mm_long":         int(row.get("m_money_positions_long_all",  0)),
                "mm_short":        int(row.get("m_money_positions_short_all", 0)),
            })
        except (KeyError, ValueError, TypeError):
            continue
    df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    df["prod_merc_net"] = df["prod_merc_long"] - df["prod_merc_short"]
    df["mm_net"]        = df["mm_long"] - df["mm_short"]
    return df


# ---------------------------------------------------------------------------
# Build study dataframe
# ---------------------------------------------------------------------------

def rolling_pct_rank(series: pd.Series, window: int) -> pd.Series:
    ranks = []
    arr = series.values
    for i in range(len(arr)):
        start_i = max(0, i - window + 1)
        window_vals = arr[start_i : i + 1]
        valid = window_vals[~pd.isna(window_vals)]
        if len(valid) < max(4, window // 8):
            ranks.append(float("nan"))
        else:
            rank = (valid < arr[i]).sum() / len(valid) * 100
            ranks.append(round(float(rank), 1))
    return pd.Series(ranks, index=series.index)


def build_study_df(legacy: pd.DataFrame, disagg: pd.DataFrame,
                   prices: pd.DataFrame, cfg: CommodityConfig) -> pd.DataFrame:
    merged = legacy.merge(
        disagg[["date", "prod_merc_net", "mm_net"]].rename(columns={"mm_net": "mm_net_disagg"}),
        on="date", how="left",
    )

    # Attach nearest prior price
    prices_sorted = prices.sort_values("date")
    price_vals = []
    for d in merged["date"]:
        mask = prices_sorted["date"] <= d
        price_vals.append(float(prices_sorted.loc[mask, "price"].iloc[-1]) if mask.any() else float("nan"))
    merged["price"] = price_vals
    merged = merged.dropna(subset=["price"]).reset_index(drop=True)

    # For log-scale / return calculations: clip extreme negative prices
    merged["price_calc"] = merged["price"].clip(lower=cfg.clip_price_min)

    print("Computing rolling percentile ranks...")
    merged["comm_pct_rank"] = rolling_pct_rank(merged["comm_net"], PERCENTILE_WINDOW)
    merged["price_sma20"]   = merged["price"].rolling(SMA_WINDOW,    min_periods=SMA_WINDOW // 2).mean()
    merged["price_sma200"]  = merged["price"].rolling(SMA200_WINDOW, min_periods=SMA200_WINDOW // 4).mean()
    merged["above_sma200"]  = (merged["price"] > merged["price_sma200"]).astype(int)

    prev_rank = merged["comm_pct_rank"].shift(1)
    now_rank  = merged["comm_pct_rank"]
    in_low    = now_rank  < TOGGLE_EXTREME
    in_high   = now_rank  > (100 - TOGGLE_EXTREME)
    was_low   = prev_rank < TOGGLE_EXTREME
    was_high  = prev_rank > (100 - TOGGLE_EXTREME)

    merged["toggle_up"]   = (was_low  & ~in_low  & ~in_high).astype(int)
    merged["toggle_down"] = (was_high & ~in_high & ~in_low ).astype(int)
    merged["toggle"]      = merged["toggle_up"] - merged["toggle_down"]

    return merged


# ---------------------------------------------------------------------------
# Forward returns + exit analysis
# ---------------------------------------------------------------------------

def compute_forward_returns(df: pd.DataFrame) -> pd.DataFrame:
    toggle_indices = df.index[df["toggle"] != 0].tolist()
    records = []

    for i, idx in enumerate(toggle_indices):
        row = df.loc[idx]
        entry = float(row["price_calc"])
        if entry <= 0:
            continue
        direction = "UP" if row["toggle"] > 0 else "DOWN"

        rec: dict = {
            "date":            row["date"],
            "direction":       direction,
            "comm_net":        row["comm_net"],
            "comm_pct_rank":   row["comm_pct_rank"],
            "price_at_toggle": float(row["price"]),
            "above_sma200":    int(row.get("above_sma200", 1)),
        }

        # Fixed-horizon returns
        for weeks in FORWARD_HORIZONS:
            fi = idx + weeks
            if fi < len(df):
                fp = float(df.loc[fi, "price_calc"])
                if fp > 0:
                    raw = (fp - entry) / entry * 100
                    directional = raw if direction == "UP" else -raw
                    rec[f"fwd_{weeks}w_raw"]         = round(raw, 2)
                    rec[f"fwd_{weeks}w_directional"] = round(directional, 2)
                else:
                    rec[f"fwd_{weeks}w_raw"]         = None
                    rec[f"fwd_{weeks}w_directional"] = None
            else:
                rec[f"fwd_{weeks}w_raw"]         = None
                rec[f"fwd_{weeks}w_directional"] = None

        # Exit: next opposite toggle
        if direction == "UP":
            opp = [j for j in toggle_indices[i+1:] if df.loc[j, "toggle"] < 0]
        else:
            opp = [j for j in toggle_indices[i+1:] if df.loc[j, "toggle"] > 0]

        if opp:
            ei   = opp[0]
            ep   = float(df.loc[ei, "price_calc"])
            raw  = (ep - entry) / entry * 100 if ep > 0 else None
            drec = round((raw if direction == "UP" else -raw), 2) if raw is not None else None
            rec["exit_toggle_date"]  = df.loc[ei, "date"]
            rec["exit_toggle_weeks"] = int(ei - idx)
            rec["exit_toggle_ret"]   = drec
        else:
            rec["exit_toggle_date"]  = None
            rec["exit_toggle_weeks"] = None
            rec["exit_toggle_ret"]   = None

        # Exit: SMA-20 breach (too tight; kept for reference)
        sma_idx = None
        for j in range(idx + 1, min(idx + 104, len(df))):
            p, sm = float(df.loc[j, "price_calc"]), df.loc[j, "price_sma20"]
            if pd.isna(sm):
                continue
            if direction == "UP" and p < sm:
                sma_idx = j; break
            elif direction == "DOWN" and p > sm:
                sma_idx = j; break

        if sma_idx is not None:
            sp   = float(df.loc[sma_idx, "price_calc"])
            raw  = (sp - entry) / entry * 100 if sp > 0 else None
            drec = round((raw if direction == "UP" else -raw), 2) if raw is not None else None
            rec["exit_sma_date"]  = df.loc[sma_idx, "date"]
            rec["exit_sma_weeks"] = int(sma_idx - idx)
            rec["exit_sma_ret"]   = drec
        else:
            rec["exit_sma_date"]  = None
            rec["exit_sma_weeks"] = None
            rec["exit_sma_ret"]   = None

        # Best exit (first trigger)
        exits = []
        if rec.get("exit_toggle_weeks") is not None:
            exits.append(("toggle", rec["exit_toggle_weeks"], rec["exit_toggle_ret"]))
        if rec.get("exit_sma_weeks") is not None:
            exits.append(("sma", rec["exit_sma_weeks"], rec["exit_sma_ret"]))
        if exits:
            best = min(exits, key=lambda x: x[1])
            rec["exit_best_type"]  = best[0]
            rec["exit_best_weeks"] = best[1]
            rec["exit_best_ret"]   = best[2]
        else:
            rec["exit_best_type"]  = None
            rec["exit_best_weeks"] = None
            rec["exit_best_ret"]   = None

        records.append(rec)

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Strategy backtest
# ---------------------------------------------------------------------------

def _equity_stats(returns: list[float]) -> dict:
    if not returns:
        return {}
    arr = np.array(returns)
    equity = np.cumprod(1 + arr / 100)
    total  = (equity[-1] - 1) * 100
    peak, max_dd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = min(max_dd, (v - peak) / peak * 100)
    return {
        "n_trades":     len(arr),
        "avg_ret":      round(arr.mean(), 2),
        "win_pct":      round((arr > 0).mean() * 100, 1),
        "total_ret":    round(total, 1),
        "max_drawdown": round(max_dd, 1),
        "expectancy":   round(arr.mean() * (arr > 0).mean(), 2),
    }


def backtest_strategy(toggles: pd.DataFrame) -> dict:
    up = toggles[toggles["direction"] == "UP"]
    results = {}

    # A: All UP toggles, hold to DOWN toggle
    a = up.dropna(subset=["exit_toggle_ret"])["exit_toggle_ret"].tolist()
    results["A_long_all"] = _equity_stats(a)

    # B: UP + above 200w SMA, hold to DOWN toggle (the quality filter)
    b = up[up["above_sma200"] == 1].dropna(subset=["exit_toggle_ret"])["exit_toggle_ret"].tolist()
    results["B_long_filtered"] = _equity_stats(b)

    # C: Both directions, hold to opposite toggle
    c = toggles.dropna(subset=["exit_toggle_ret"])["exit_toggle_ret"].tolist()
    results["C_both_raw"] = _equity_stats(c)

    # D: Both directions filtered by 200w SMA side
    d_up   = up[up["above_sma200"] == 1].dropna(subset=["exit_toggle_ret"])["exit_toggle_ret"].tolist()
    dn     = toggles[toggles["direction"] == "DOWN"]
    d_down = dn[dn["above_sma200"] == 0].dropna(subset=["exit_toggle_ret"])["exit_toggle_ret"].tolist()
    results["D_both_filtered"] = _equity_stats(d_up + d_down)

    return results


# ---------------------------------------------------------------------------
# Print summary
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame, toggles: pd.DataFrame,
                  strat: dict, cfg: CommodityConfig):
    n_up, n_dn = (toggles["direction"] == "UP").sum(), (toggles["direction"] == "DOWN").sum()

    print()
    print("=" * 72)
    print(f"COT TOGGLE STUDY — {cfg.name.upper()}  ({cfg.cftc_code})")
    print("=" * 72)
    print(f"Dataset:  {df['date'].iloc[0].date()} – {df['date'].iloc[-1].date()}")
    print(f"Weeks:    {len(df)}  |  Toggles UP: {n_up}  DOWN: {n_dn}")
    print(f"Toggle:   comm net exits {TOGGLE_EXTREME}th/{100-TOGGLE_EXTREME}th pct "
          f"(trailing {PERCENTILE_WINDOW}w window)")
    print()

    # Fixed-horizon
    print("FIXED-HORIZON DIRECTIONAL RETURNS")
    print(f"{'Horizon':<8} | {'UP n':>5} {'UP avg':>8} {'UP win%':>8} "
          f"| {'DN n':>5} {'DN avg':>8} {'DN win%':>8}")
    print("-" * 60)
    for w in FORWARD_HORIZONS:
        col = f"fwd_{w}w_directional"
        uv = toggles.loc[toggles["direction"] == "UP",   col].dropna()
        dv = toggles.loc[toggles["direction"] == "DOWN", col].dropna()
        print(f"{w}w{'':<5} | "
              f"{len(uv):>5} {uv.mean():>+7.1f}%  {(uv>0).mean()*100:>6.0f}%  "
              f"| {len(dv):>5} {dv.mean():>+7.1f}%   {(dv>0).mean()*100:>5.0f}%")

    # Era breakdown
    print()
    print("BY ERA — 26-week directional return:")
    print(f"  {'Era':<18} {'UP n':>5} {'UP avg':>8} {'UP%':>6}  {'DN n':>5} {'DN avg':>8} {'DN%':>6}")
    print("  " + "-" * 64)
    col26 = "fwd_26w_directional"
    for label, start, end in cfg.eras:
        et = toggles[(toggles["date"] >= start) & (toggles["date"] < end)]
        uv = et.loc[et["direction"] == "UP",   col26].dropna()
        dv = et.loc[et["direction"] == "DOWN", col26].dropna()
        ua = f"{uv.mean():+.1f}%" if len(uv) else "  n/a"
        da = f"{dv.mean():+.1f}%" if len(dv) else "  n/a"
        uw = f"{(uv>0).mean()*100:.0f}%" if len(uv) else "n/a"
        dw = f"{(dv>0).mean()*100:.0f}%" if len(dv) else "n/a"
        print(f"  {label:<18} {len(uv):>5} {ua:>8} {uw:>6}  {len(dv):>5} {da:>8} {dw:>6}")

    # 200w SMA filter
    print()
    print("FILTERED BY 200-WEEK SMA (macro trend qualifier):")
    print(f"  {'Condition':<38} {'n':>4} {'26w avg':>8} {'26w win%':>9}")
    print("  " + "-" * 62)
    for lbl, dirn, above in [
        ("UP  + above 200w SMA  [quality long]",   "UP",   1),
        ("UP  + below 200w SMA  [avoid]",          "UP",   0),
        ("DOWN + above 200w SMA  [premature short]","DOWN", 1),
        ("DOWN + below 200w SMA  [quality short]", "DOWN", 0),
    ]:
        mask = (toggles["direction"] == dirn) & (toggles["above_sma200"] == above)
        sub  = toggles.loc[mask, col26].dropna()
        if len(sub):
            print(f"  {lbl:<38} {len(sub):>4} {sub.mean():>+7.1f}%  {(sub>0).mean()*100:>6.0f}%")
        else:
            print(f"  {lbl:<38}  n/a")

    # Exit analysis
    print()
    print("EXIT ANALYSIS — HOLD TO OPPOSITE TOGGLE:")
    for dirn in ("UP", "DOWN"):
        t = toggles[toggles["direction"] == dirn].dropna(subset=["exit_toggle_ret"])
        if len(t):
            print(f"  {dirn}: {len(t)} trades | held {t['exit_toggle_weeks'].mean():.0f}w avg | "
                  f"return {t['exit_toggle_ret'].mean():+.1f}% avg | "
                  f"{(t['exit_toggle_ret']>0).mean()*100:.0f}% win")

    # Strategy backtest
    print()
    print("STRATEGY BACKTEST (compounded, sequential):")
    print(f"  {'Strategy':<42} {'n':>5} {'Avg%':>7} {'Win%':>6} {'Total%':>8} {'MaxDD%':>8}")
    print("  " + "-" * 80)
    labels = {
        "A_long_all":      "A: Long (all UP toggles) → DOWN toggle",
        "B_long_filtered": "B: Long (above 200w SMA) → DOWN toggle  ★",
        "C_both_raw":      "C: Both dirs (raw) → opposite toggle",
        "D_both_filtered": "D: Both dirs (200w filter) → opposite toggle",
    }
    for key, lbl in labels.items():
        r = strat.get(key, {})
        if not r:
            print(f"  {lbl:<42}  (no data)")
        else:
            print(f"  {lbl:<42} {r['n_trades']:>5} {r['avg_ret']:>+6.1f}% "
                  f"{r['win_pct']:>5.0f}% {r['total_ret']:>+8.1f}% {r['max_drawdown']:>+7.1f}%")

    # Toggle event table (most recent 30)
    recent = toggles.tail(30)
    print()
    print(f"RECENT TOGGLE EVENTS (last {len(recent)}):")
    fwd_hdr = "  ".join(f"{w}w" for w in FORWARD_HORIZONS)
    print(f"  {'Date':<12} {'Dir':<6} {'PctRnk':>7} {'CommNet':>10} {'SMA200':>7}  {fwd_hdr}")
    print("  " + "-" * 82)
    for _, row in recent.iterrows():
        fwds = "  ".join(
            f"{row[f'fwd_{w}w_raw']:>+6.1f}%" if row.get(f"fwd_{w}w_raw") is not None else "    n/a"
            for w in FORWARD_HORIZONS
        )
        sma_flag = ">" if row.get("above_sma200") else "<"
        print(f"  {str(row['date'].date()):<12} {row['direction']:<6} "
              f"{row['comm_pct_rank']:>6.0f}%  {row['comm_net']:>10,.0f} {sma_flag}200w  {fwds}")
    print()


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

def save_chart(df: pd.DataFrame, toggles: pd.DataFrame,
               path: Path, cfg: CommodityConfig):
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(18, 10), sharex=True,
        gridspec_kw={"height_ratios": [2, 1]},
    )
    fig.suptitle(
        f"{cfg.name}: Commercial Hedger COT vs Price — Toggle Study (1986–present)",
        fontsize=13, fontweight="bold",
    )

    dates = df["date"]
    price_plot = df["price"].clip(lower=cfg.clip_price_min)

    ax1.plot(dates, price_plot, color="#2471A3", linewidth=0.9, label=cfg.name, zorder=2)
    if "price_sma20" in df.columns:
        ax1.plot(dates, df["price_sma20"].clip(lower=cfg.clip_price_min),
                 color="#808080", linewidth=0.7, linestyle="--", alpha=0.6, label="SMA-20w", zorder=1)
    if "price_sma200" in df.columns:
        ax1.plot(dates, df["price_sma200"].clip(lower=cfg.clip_price_min),
                 color="#E74C3C", linewidth=1.0, linestyle="-.", alpha=0.7, label="SMA-200w", zorder=1)

    if cfg.log_scale:
        ax1.set_yscale("log")
    ax1.set_ylabel(cfg.price_label, fontsize=10)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax1.grid(True, alpha=0.2)

    up_d = toggles[toggles["direction"] == "UP"]["date"]
    dn_d = toggles[toggles["direction"] == "DOWN"]["date"]

    for d in up_d:
        p = df.loc[df["date"] == d, "price"]
        if not p.empty:
            pv = max(float(p.values[0]), cfg.clip_price_min)
            ax1.axvline(d, color="green", alpha=0.25, linewidth=0.7, linestyle="--")
            ax1.scatter(d, pv, color="green", s=30, zorder=5, marker="^")
    for d in dn_d:
        p = df.loc[df["date"] == d, "price"]
        if not p.empty:
            pv = max(float(p.values[0]), cfg.clip_price_min)
            ax1.axvline(d, color="red", alpha=0.25, linewidth=0.7, linestyle="--")
            ax1.scatter(d, pv, color="red", s=30, zorder=5, marker="v")

    ax1.scatter([], [], color="green", marker="^", s=50, label="Toggle UP  (bullish)")
    ax1.scatter([], [], color="red",   marker="v", s=50, label="Toggle DOWN (bearish)")
    ax1.legend(loc="upper left", fontsize=9)

    # Era shading
    era_colors = ["#FADBD8", "#D5F5E3", "#D6EAF8"]
    for (label, start, end), color in zip(cfg.eras, era_colors):
        ax1.axvspan(pd.Timestamp(start), pd.Timestamp(end), alpha=0.08, color=color, label="_era")

    # COT panel
    ax2.plot(dates, df["comm_net"] / 1000, color="#2471A3", linewidth=0.9, label="Comm net (k contracts)")
    if "mm_net_disagg" in df.columns:
        ax2.plot(dates, df["mm_net_disagg"] / 1000, color="#E67E22", linewidth=0.6,
                 linestyle=":", alpha=0.7, label="Managed money net (2006+)")

    low_q  = df["comm_net"].quantile(TOGGLE_EXTREME / 100)
    high_q = df["comm_net"].quantile(1 - TOGGLE_EXTREME / 100)
    ymin, ymax = df["comm_net"].min(), df["comm_net"].max()
    ax2.axhspan(ymin / 1000, low_q / 1000,   alpha=0.08, color="green", label=f"Bot {TOGGLE_EXTREME}th pct (bullish zone)")
    ax2.axhspan(high_q / 1000, ymax / 1000,  alpha=0.08, color="red",   label=f"Top {100-TOGGLE_EXTREME}th pct (bearish zone)")
    ax2.axhline(0, color="black", linewidth=0.5, alpha=0.3)
    ax2.set_ylabel("Commercial net (k contracts)", fontsize=10)
    ax2.grid(True, alpha=0.2)
    ax2.legend(loc="upper left", fontsize=8)

    for d in up_d:
        ax2.axvline(d, color="green", alpha=0.2, linewidth=0.6, linestyle="--")
    for d in dn_d:
        ax2.axvline(d, color="red", alpha=0.2, linewidth=0.6, linestyle="--")

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax2.xaxis.set_major_locator(mdates.YearLocator(2))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha="right")

    plt.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Chart saved: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_study(commodity: str):
    if commodity not in COMMODITIES:
        print(f"Unknown commodity '{commodity}'. Available: {', '.join(COMMODITIES)}")
        sys.exit(1)

    cfg = COMMODITIES[commodity]
    study_dir = STUDY_BASE / commodity
    study_dir.mkdir(parents=True, exist_ok=True)

    legacy = fetch_legacy_cot(cfg.cftc_code)
    disagg = fetch_disagg_cot(cfg.cftc_code)

    start = (legacy["date"].min() - timedelta(days=365)).strftime("%Y-%m-%d")
    end   = (legacy["date"].max() + timedelta(days=14)).strftime("%Y-%m-%d")
    prices = fetch_prices(cfg, start, end)

    df = build_study_df(legacy, disagg, prices, cfg)
    n_up, n_dn = df["toggle_up"].sum(), df["toggle_down"].sum()
    print(f"Study dataset: {len(df)} weeks, {n_up} UP toggles, {n_dn} DOWN toggles")

    toggles = compute_forward_returns(df)
    strat   = backtest_strategy(toggles)

    csv_path = study_dir / "annotated.csv"
    tog_path = study_dir / "toggles.csv"
    df.to_csv(csv_path, index=False)
    toggles.to_csv(tog_path, index=False)
    print(f"CSV:     {csv_path}  ({csv_path.stat().st_size // 1024} KB)")
    print(f"Toggles: {tog_path}  ({tog_path.stat().st_size // 1024} KB)")

    print_summary(df, toggles, strat, cfg)
    save_chart(df, toggles, study_dir / "study.png", cfg)

    total_kb = sum(f.stat().st_size for f in study_dir.iterdir() if f.is_file()) // 1024
    print(f"Total study disk ({commodity}): {total_kb} KB")


if __name__ == "__main__":
    commodity = sys.argv[1].lower() if len(sys.argv) > 1 else "gold"
    run_study(commodity)

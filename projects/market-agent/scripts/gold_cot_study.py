#!/usr/bin/env python3
"""Gold COT Toggle Study — 40-year commercial hedger analysis vs gold price.

Based on Dave Druz's methodology: use CFTC commercial positioning to label
historical price data, identify toggle dates (regime shifts), then study
what forward price returns look like after those toggles.

Data sources:
  - Legacy COT (1986-present):  CFTC Socrata 6dca-aqww
      comm_positions_long_all / comm_positions_short_all (all hedgers)
  - Disaggregated COT (2006-present): CFTC Socrata 72hh-3qpy
      prod_merc_positions_long / prod_merc_positions_short (producers only)
  - Gold price: GC=F continuous futures via yfinance

Usage:
    uv run python scripts/gold_cot_study.py

Output (all in ~/.market-agent/studies/, ~10 MB total):
    gold_cot_annotated.csv   — merged weekly dataset, 40 years
    gold_cot_toggles.csv     — toggle events with forward returns
    gold_cot_study.png       — COT vs price chart with toggle markers
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import yfinance as yf
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STUDY_DIR = Path.home() / ".market-agent" / "studies"

LEGACY_URL  = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"   # 1986-present
DISAGG_URL  = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"   # 2006-present
GOLD_CODE   = "088691"
PRICE_TICKER = "GC=F"

PERCENTILE_WINDOW = 156    # weeks for rolling percentile (~3 years)
TOGGLE_EXTREME    = 20     # bottom/top N% = extreme zone
FORWARD_HORIZONS  = [4, 8, 13, 26, 52]  # weeks


# ---------------------------------------------------------------------------
# Step 1: Fetch full COT history
# ---------------------------------------------------------------------------

def _paginate_cftc(url: str, extra_params: dict) -> list[dict]:
    """Paginate a CFTC Socrata endpoint, returning all matching rows."""
    all_rows: list[dict] = []
    limit, offset = 1000, 0
    while True:
        params = {
            "cftc_contract_market_code": GOLD_CODE,
            "$order": "report_date_as_yyyy_mm_dd ASC",
            "$limit": str(limit),
            "$offset": str(offset),
            **extra_params,
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


def fetch_legacy_cot() -> pd.DataFrame:
    """Fetch legacy COT (1986-present) — all commercials combined."""
    print("Fetching legacy COT (1986-present)...")
    rows = _paginate_cftc(LEGACY_URL, {})
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
                "source":     "legacy",
            })
        except (KeyError, ValueError, TypeError):
            continue

    df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    df["comm_net"] = df["comm_long"] - df["comm_short"]
    df["nc_net"]   = df["nc_long"]  - df["nc_short"]
    return df


def fetch_disagg_cot() -> pd.DataFrame:
    """Fetch disaggregated COT (2006-present) — producer/merchant only."""
    print("Fetching disaggregated COT (2006-present)...")
    rows = _paginate_cftc(DISAGG_URL, {})
    print(f"  {len(rows)} records")

    records = []
    for row in rows:
        try:
            records.append({
                "date":           pd.to_datetime(row["report_date_as_yyyy_mm_dd"][:10]),
                "prod_merc_long":  int(row.get("prod_merc_positions_long",  0)),
                "prod_merc_short": int(row.get("prod_merc_positions_short", 0)),
                "mm_long":         int(row.get("m_money_positions_long_all",  0)),
                "mm_short":        int(row.get("m_money_positions_short_all", 0)),
                "oi":              int(row.get("open_interest_all",           0)),
            })
        except (KeyError, ValueError, TypeError):
            continue

    df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    df["prod_merc_net"] = df["prod_merc_long"] - df["prod_merc_short"]
    df["mm_net"]        = df["mm_long"] - df["mm_short"]
    return df


# ---------------------------------------------------------------------------
# Step 2: Gold price (GC=F continuous futures, back to 1974)
# ---------------------------------------------------------------------------

def fetch_gold_prices(start: str, end: str) -> pd.DataFrame:
    print(f"Fetching gold prices ({PRICE_TICKER}, {start} – {end})...")
    df = yf.download(PRICE_TICKER, start=start, end=end, progress=False, auto_adjust=True)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Close"]].rename(columns={"Close": "price"})
    df.index = pd.to_datetime(df.index)
    df.index.name = "date"
    print(f"  {len(df)} daily bars  ({df.index[0].date()} – {df.index[-1].date()})")
    return df


# ---------------------------------------------------------------------------
# Step 3: Merge, percentile rank, toggle detection
# ---------------------------------------------------------------------------

def rolling_pct_rank(series: pd.Series, window: int) -> pd.Series:
    """Percentile rank of each value within its trailing window (0–100)."""
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


def build_study_df(
    legacy: pd.DataFrame,
    disagg: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    """Merge COT (weekly) with nearest prior price; compute percentile + toggles."""
    prices_daily = prices.reset_index()

    # Merge disaggregated into legacy on date
    merged = legacy.merge(
        disagg[["date", "prod_merc_net", "mm_net"]].rename(
            columns={"mm_net": "mm_net_disagg"}
        ),
        on="date", how="left",
    )

    # Attach price: for each COT date use the closing price on or before
    price_vals = []
    for d in merged["date"]:
        mask = prices_daily["date"] <= d
        if mask.any():
            price_vals.append(float(prices_daily.loc[mask, "price"].iloc[-1]))
        else:
            price_vals.append(float("nan"))
    merged["price"] = price_vals

    merged = merged.dropna(subset=["price"]).reset_index(drop=True)

    print("Computing rolling percentile ranks...")
    merged["comm_pct_rank"] = rolling_pct_rank(merged["comm_net"], PERCENTILE_WINDOW)

    # Also compute for producer/merchant where available
    if "prod_merc_net" in merged.columns:
        merged["prod_merc_pct_rank"] = rolling_pct_rank(
            merged["prod_merc_net"].fillna(merged["comm_net"]),
            PERCENTILE_WINDOW,
        )

    # Toggle detection: percentile exits extreme zone
    prev_rank = merged["comm_pct_rank"].shift(1)
    now_rank  = merged["comm_pct_rank"]

    in_low  = now_rank  < TOGGLE_EXTREME
    in_high = now_rank  > (100 - TOGGLE_EXTREME)
    was_low = prev_rank < TOGGLE_EXTREME
    was_high= prev_rank > (100 - TOGGLE_EXTREME)

    # Toggle UP:   was in low extreme, now exits → commercials reducing shorts (bullish)
    # Toggle DOWN: was in high extreme, now exits → commercials adding shorts (bearish)
    merged["toggle_up"]   = (was_low  & ~in_low  & ~in_high).astype(int)
    merged["toggle_down"] = (was_high & ~in_high & ~in_low ).astype(int)
    merged["toggle"]      = merged["toggle_up"] - merged["toggle_down"]

    return merged


# ---------------------------------------------------------------------------
# Step 4: Forward returns at each toggle
# ---------------------------------------------------------------------------

def compute_forward_returns(df: pd.DataFrame) -> pd.DataFrame:
    toggle_mask = df["toggle"] != 0
    records = []

    for idx in df.index[toggle_mask]:
        row = df.loc[idx]
        entry = row["price"]
        direction = "UP" if row["toggle"] > 0 else "DOWN"
        rec: dict = {
            "date":            row["date"],
            "direction":       direction,
            "comm_net":        row["comm_net"],
            "comm_pct_rank":   row["comm_pct_rank"],
            "price_at_toggle": entry,
        }
        for weeks in FORWARD_HORIZONS:
            future_idx = idx + weeks
            if future_idx < len(df):
                fp = df.loc[future_idx, "price"]
                raw = (fp - entry) / entry * 100
                directional = raw if direction == "UP" else -raw
                rec[f"fwd_{weeks}w_raw"]         = round(raw, 2)
                rec[f"fwd_{weeks}w_directional"] = round(directional, 2)
            else:
                rec[f"fwd_{weeks}w_raw"]         = None
                rec[f"fwd_{weeks}w_directional"] = None
        records.append(rec)

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Step 5: Summary statistics
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame, toggles: pd.DataFrame):
    n_up   = (toggles["direction"] == "UP").sum()
    n_down = (toggles["direction"] == "DOWN").sum()

    print()
    print("=" * 70)
    print("GOLD COT TOGGLE STUDY — FORWARD RETURN SUMMARY (ALL COMMERCIALS)")
    print("=" * 70)
    print(f"Dataset:  {df['date'].iloc[0].date()} – {df['date'].iloc[-1].date()}")
    print(f"Weeks:    {len(df)}  |  Toggles UP: {n_up}  DOWN: {n_down}")
    print(f"Toggle:   commercial net exits {TOGGLE_EXTREME}th/{100-TOGGLE_EXTREME}th"
          f" pct-rank (trailing {PERCENTILE_WINDOW}w window)")
    print()

    # Full-period table
    print(f"{'Horizon':<8} | {'UP n':>5} {'UP avg':>8} {'UP win%':>8} "
          f"| {'DOWN n':>6} {'DOWN avg':>9} {'DOWN win%':>10}")
    print("-" * 68)

    for weeks in FORWARD_HORIZONS:
        col = f"fwd_{weeks}w_directional"
        up_v   = toggles.loc[toggles["direction"] == "UP",   col].dropna()
        dn_v   = toggles.loc[toggles["direction"] == "DOWN", col].dropna()
        print(
            f"{weeks}w{'':<5} | "
            f"{len(up_v):>5} {up_v.mean():>+7.1f}%  {(up_v > 0).mean()*100:>6.0f}%  "
            f"| {len(dn_v):>6} {dn_v.mean():>+8.1f}%   {(dn_v > 0).mean()*100:>6.0f}%"
        )

    # Era breakdown (pre/post 2006, pre/post 2012 gold peak)
    eras = [
        ("1986–1999", "1986-01-01", "2000-01-01"),
        ("2000–2011", "2000-01-01", "2012-01-01"),
        ("2012–2025", "2012-01-01", "2026-01-01"),
    ]
    print()
    print("BY ERA — 26-week directional return:")
    print(f"  {'Era':<12} {'UP n':>5} {'UP avg':>8} {'UP win%':>8} "
          f"{'DOWN n':>7} {'DOWN avg':>9} {'DOWN win%':>10}")
    print("  " + "-" * 64)
    for label, start, end in eras:
        era_t = toggles[
            (toggles["date"] >= start) & (toggles["date"] < end)
        ]
        col = "fwd_26w_directional"
        up_v = era_t.loc[era_t["direction"] == "UP",   col].dropna()
        dn_v = era_t.loc[era_t["direction"] == "DOWN", col].dropna()
        up_avg = f"{up_v.mean():+.1f}%" if len(up_v) else "  n/a"
        dn_avg = f"{dn_v.mean():+.1f}%" if len(dn_v) else "  n/a"
        up_win = f"{(up_v > 0).mean()*100:.0f}%" if len(up_v) else "n/a"
        dn_win = f"{(dn_v > 0).mean()*100:.0f}%" if len(dn_v) else "n/a"
        print(f"  {label:<12} {len(up_v):>5} {up_avg:>8} {up_win:>8} "
              f"{len(dn_v):>7} {dn_avg:>9} {dn_win:>10}")

    print()
    print("All toggle events:")
    hdr_cols = "  ".join(f"{w}w" for w in FORWARD_HORIZONS)
    print(f"  {'Date':<12} {'Dir':<6} {'PctRank':>8} {'CommNet':>10}   {hdr_cols}")
    print("  " + "-" * 80)
    for _, row in toggles.iterrows():
        fwds = "  ".join(
            f"{row[f'fwd_{w}w_raw']:>+6.1f}%" if row[f"fwd_{w}w_raw"] is not None else "    n/a"
            for w in FORWARD_HORIZONS
        )
        print(f"  {str(row['date'].date()):<12} {row['direction']:<6} "
              f"{row['comm_pct_rank']:>7.0f}%  {row['comm_net']:>10,}   {fwds}")
    print()


# ---------------------------------------------------------------------------
# Step 6: Chart
# ---------------------------------------------------------------------------

def save_chart(df: pd.DataFrame, toggles: pd.DataFrame, path: Path):
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(16, 9), sharex=True,
        gridspec_kw={"height_ratios": [2, 1]},
    )
    fig.suptitle(
        "Gold: Commercial Hedger COT vs Price — Toggle Study  (1986–2025)",
        fontsize=13, fontweight="bold",
    )

    dates = df["date"]

    # ── Top: gold price ──────────────────────────────────────────────────────
    ax1.plot(dates, df["price"], color="#C9A84C", linewidth=1.0, label="Gold (GC=F)")
    ax1.set_ylabel("Gold price (USD)", fontsize=10)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax1.set_yscale("log")
    ax1.grid(True, alpha=0.2)

    up_dates   = toggles[toggles["direction"] == "UP"]["date"]
    down_dates = toggles[toggles["direction"] == "DOWN"]["date"]

    for d in up_dates:
        p = df.loc[df["date"] == d, "price"]
        if not p.empty:
            ax1.axvline(d, color="green", alpha=0.35, linewidth=0.8, linestyle="--")
            ax1.scatter(d, p.values[0], color="green", s=40, zorder=5, marker="^")

    for d in down_dates:
        p = df.loc[df["date"] == d, "price"]
        if not p.empty:
            ax1.axvline(d, color="red", alpha=0.35, linewidth=0.8, linestyle="--")
            ax1.scatter(d, p.values[0], color="red", s=40, zorder=5, marker="v")

    ax1.scatter([], [], color="green", marker="^", s=50, label="Toggle UP  (bullish)")
    ax1.scatter([], [], color="red",   marker="v", s=50, label="Toggle DOWN (bearish)")
    ax1.legend(loc="upper left", fontsize=9)

    # ── Bottom: commercial net position ──────────────────────────────────────
    ax2.plot(dates, df["comm_net"], color="#2471A3", linewidth=0.9, label="Comm net (all hedgers)")

    # Shade extreme zones using actual percentile thresholds from the data
    low_q  = df["comm_net"].quantile(TOGGLE_EXTREME / 100)
    high_q = df["comm_net"].quantile(1 - TOGGLE_EXTREME / 100)
    ymin, ymax = df["comm_net"].min(), df["comm_net"].max()
    ax2.axhspan(ymin, low_q,   alpha=0.07, color="red",   label=f"Bot {TOGGLE_EXTREME}th pct")
    ax2.axhspan(high_q, ymax,  alpha=0.07, color="green", label=f"Top {100-TOGGLE_EXTREME}th pct")
    ax2.axhline(0, color="black", linewidth=0.5, alpha=0.4)
    ax2.set_ylabel("Commercial net contracts", fontsize=10)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x/1000:.0f}k"))
    ax2.grid(True, alpha=0.2)
    ax2.legend(loc="upper left", fontsize=8)

    for d in up_dates:
        ax2.axvline(d, color="green", alpha=0.3, linewidth=0.7, linestyle="--")
    for d in down_dates:
        ax2.axvline(d, color="red", alpha=0.3, linewidth=0.7, linestyle="--")

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax2.xaxis.set_major_locator(mdates.YearLocator(5))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha="right")

    plt.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Chart saved: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    STUDY_DIR.mkdir(parents=True, exist_ok=True)

    legacy = fetch_legacy_cot()
    disagg = fetch_disagg_cot()

    start = (legacy["date"].min() - timedelta(days=30)).strftime("%Y-%m-%d")
    end   = (legacy["date"].max() + timedelta(days=7)).strftime("%Y-%m-%d")
    prices = fetch_gold_prices(start, end)

    df = build_study_df(legacy, disagg, prices)

    n_up   = df["toggle_up"].sum()
    n_down = df["toggle_down"].sum()
    print(f"Study dataset: {len(df)} weeks, {n_up} UP toggles, {n_down} DOWN toggles")

    toggles = compute_forward_returns(df)

    csv_path = STUDY_DIR / "gold_cot_annotated.csv"
    tog_path = STUDY_DIR / "gold_cot_toggles.csv"
    df.to_csv(csv_path, index=False)
    toggles.to_csv(tog_path, index=False)
    print(f"CSV:     {csv_path}  ({csv_path.stat().st_size // 1024} KB)")
    print(f"Toggles: {tog_path}  ({tog_path.stat().st_size // 1024} KB)")

    print_summary(df, toggles)
    save_chart(df, toggles, STUDY_DIR / "gold_cot_study.png")

    total_kb = sum(
        f.stat().st_size for f in STUDY_DIR.iterdir() if f.is_file()
    ) // 1024
    print(f"Total study disk: {total_kb} KB")


if __name__ == "__main__":
    main()

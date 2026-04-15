"""
Quality Momentum Scoring Engine

Scores S&P 500 universe on:
- 12-1 month momentum (60%): 12-month return minus 1-month return (avoids short-term reversal)
- 6-month momentum (40%): 6-month return
- Annualized 90-day volatility (-30%): penalizes high-vol names
- Quality filter: excludes stocks below $10 and with inadequate history

Composite score = 0.6 * z(mom_12_1) + 0.4 * z(mom_6) - 0.3 * z(vol_90)

Higher score = better momentum candidate.
"""
from __future__ import annotations

from sqlalchemy import text
from datetime import datetime
import pytz
import pandas as pd
import numpy as np

from src.config import DB_PATH
from src.db import get_engine

ET = pytz.timezone("America/New_York")

# Windows in trading days
W_12M = 252
W_6M = 126
W_1M = 21
W_VOL = 90

MIN_ROWS = W_12M + 20  # minimum history required
MIN_PRICE = 10.0       # quality filter: exclude penny stocks


def zscore(s: pd.Series) -> pd.Series:
    s = s.astype(float)
    mu = s.mean()
    sd = s.std(ddof=0)
    if not np.isfinite(sd) or sd < 1e-12:
        return s * 0.0
    return (s - mu) / (sd + 1e-12)


def main():
    run_date = datetime.now(ET).date().isoformat()
    engine = get_engine(DB_PATH)

    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT symbol, date, adj_close, close
            FROM prices_daily
            ORDER BY symbol, date
        """)).fetchall()

    if not rows:
        print("No prices in DB. Run ingest_prices first.")
        return

    df = pd.DataFrame(rows, columns=["symbol", "date", "adj_close", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df["adj_close"] = df["adj_close"].astype(float)
    df["close"] = df["close"].astype(float)

    # Quality filter: get most recent price per symbol, exclude below $10
    latest_prices = df.sort_values("date").groupby("symbol").last()["close"]
    quality_symbols = set(latest_prices[latest_prices >= MIN_PRICE].index)

    df = df[df["symbol"].isin(quality_symbols)].copy()

    # Compute returns
    df["ret"] = df.groupby("symbol")["adj_close"].pct_change()

    g = df.groupby("symbol", group_keys=False)

    # Momentum signals
    df["mom_12_1"] = (
        df["adj_close"] / g["adj_close"].shift(W_12M) - 1.0
    ) - (
        df["adj_close"] / g["adj_close"].shift(W_1M) - 1.0
    )
    df["mom_6"] = df["adj_close"] / g["adj_close"].shift(W_6M) - 1.0
    df["vol_90"] = (
        g["ret"].rolling(W_VOL).std().reset_index(level=0, drop=True) * np.sqrt(252)
    )

    # Take most recent row per symbol
    last = df.sort_values(["symbol", "date"]).groupby("symbol").tail(1)

    # Require minimum history
    counts = df.groupby("symbol").size()
    last = last[last["symbol"].map(counts) >= MIN_ROWS]

    # Drop NaN signals
    last = last.dropna(subset=["mom_12_1", "mom_6", "vol_90"])

    if last.empty:
        print("No symbols had enough history for scoring.")
        return

    m121 = last.set_index("symbol")["mom_12_1"]
    m6 = last.set_index("symbol")["mom_6"]
    v90 = last.set_index("symbol")["vol_90"]

    # Composite score
    score = 0.6 * zscore(m121) + 0.4 * zscore(m6) - 0.3 * zscore(v90)

    out = pd.DataFrame({
        "symbol": score.index,
        "score": score.values,
        "mom_12_1": m121.loc[score.index].values,
        "mom_6": m6.loc[score.index].values,
        "vol_90": v90.loc[score.index].values,
        "quality_flag": 1,
    }).dropna()

    with engine.begin() as conn:
        for _, r in out.iterrows():
            conn.execute(text("""
                INSERT INTO scores(run_date, symbol, score, mom_12_1, mom_6, vol_90, quality_flag)
                VALUES (:d, :s, :sc, :m121, :m6, :v90, :qf)
                ON CONFLICT(run_date, symbol) DO UPDATE SET
                  score=excluded.score,
                  mom_12_1=excluded.mom_12_1,
                  mom_6=excluded.mom_6,
                  vol_90=excluded.vol_90,
                  quality_flag=excluded.quality_flag
            """), {
                "d": run_date,
                "s": str(r["symbol"]),
                "sc": float(r["score"]),
                "m121": float(r["mom_12_1"]),
                "m6": float(r["mom_6"]),
                "v90": float(r["vol_90"]),
                "qf": int(r["quality_flag"]),
            })

    # Prune old scores (keep 90 days)
    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM scores
            WHERE run_date < date(:d, '-90 days')
        """), {"d": run_date})

    latest_dt = last["date"].max()
    scored_count = len(out)
    excluded_count = len(latest_prices) - len(quality_symbols)
    print(f"Scored {scored_count} symbols for {run_date} (px date={latest_dt.date()}, excluded {excluded_count} below ${MIN_PRICE})")


if __name__ == "__main__":
    main()

"""
Price ingestion using yfinance 0.2.x stable API.
Fetches last 5 days of prices for all universe symbols.
Automatically excludes delisted/broken symbols.
Prunes price history older than 8 years to prevent unbounded growth.
"""
import time
import random
from datetime import datetime, timezone, timedelta
import pytz
import pandas as pd
import yfinance as yf
from sqlalchemy import text

from src.config import DB_PATH
from src.db import get_engine

ET = pytz.timezone("America/New_York")

BATCH_SIZE = 50
PERIOD = "5d"
SLEEP_BETWEEN_BATCHES = 1.0
MAX_RETRIES = 3
# Keep 8 years of history (need ~7 years for 252*7 trading days + buffer)
PRICE_HISTORY_YEARS = 8


def log(msg: str):
    ts = datetime.now(ET).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def exclude_symbol(conn, sym: str, reason: str):
    conn.execute(text("""
      INSERT INTO universe_exclusions(symbol, reason, first_seen_utc)
      VALUES (:s, :r, :t)
      ON CONFLICT(symbol) DO UPDATE SET reason=excluded.reason
    """), {
        "s": sym, "r": reason,
        "t": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    })


def get_universe_symbols(conn) -> list:
    rows = conn.execute(text("""
      SELECT u.symbol FROM universe u
      LEFT JOIN universe_exclusions x ON x.symbol = u.symbol
      WHERE x.symbol IS NULL
      ORDER BY u.symbol
    """)).fetchall()
    return [r[0] for r in rows]


def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]


def fetch_batch(symbols: list, period: str = PERIOD) -> dict:
    """
    Fetch prices for a batch of symbols.
    Returns dict of {symbol: DataFrame} with columns [date, close, adj_close].
    Compatible with yfinance 0.2.x.
    """
    out = {}
    if not symbols:
        return out

    for attempt in range(MAX_RETRIES):
        try:
            if len(symbols) == 1:
                ticker = yf.Ticker(symbols[0])
                data = ticker.history(period=period, auto_adjust=False)
                if data is not None and not data.empty:
                    df = pd.DataFrame({
                        "close": data["Close"].values,
                        "adj_close": data["Adj Close"].values if "Adj Close" in data.columns else data["Close"].values,
                    }, index=data.index)
                    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
                    out[symbols[0]] = df.dropna(subset=["close"])
            else:
                tickers = yf.Tickers(" ".join(symbols))
                for sym in symbols:
                    try:
                        t = tickers.tickers.get(sym)
                        if t is None:
                            continue
                        data = t.history(period=period, auto_adjust=False)
                        if data is None or data.empty:
                            continue
                        df = pd.DataFrame({
                            "close": data["Close"].values,
                            "adj_close": data["Adj Close"].values if "Adj Close" in data.columns else data["Close"].values,
                        }, index=data.index)
                        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
                        df = df.dropna(subset=["close"])
                        if not df.empty:
                            out[sym] = df
                    except Exception:
                        continue
            return out
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                log(f"Batch failed after {MAX_RETRIES} attempts: {e}")
                return out
            wait = (2 ** attempt) + random.random()
            log(f"Retry {attempt+1}/{MAX_RETRIES} after {wait:.1f}s: {e}")
            time.sleep(wait)

    return out


def fetch_long_history(symbols: list, years: int = PRICE_HISTORY_YEARS) -> dict:
    """Fetch multi-year history for initial load or backfill."""
    period = f"{years}y"
    out = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            data = ticker.history(period=period, auto_adjust=False)
            if data is None or data.empty:
                continue
            df = pd.DataFrame({
                "close": data["Close"].values,
                "adj_close": data["Adj Close"].values if "Adj Close" in data.columns else data["Close"].values,
            }, index=data.index)
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            df = df.dropna(subset=["close"])
            if not df.empty:
                out[sym] = df
        except Exception as e:
            log(f"  {sym}: {e}")
        time.sleep(0.3)
    return out


def upsert_prices(conn, symbol: str, df: pd.DataFrame):
    for idx, row in df.iterrows():
        d = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        conn.execute(text("""
            INSERT INTO prices_daily(symbol, date, adj_close, close)
            VALUES (:symbol, :date, :adj_close, :close)
            ON CONFLICT(symbol, date) DO UPDATE SET
              adj_close=excluded.adj_close,
              close=excluded.close
        """), {
            "symbol": symbol,
            "date": d,
            "adj_close": float(row["adj_close"]),
            "close": float(row["close"]),
        })


def prune_old_prices(conn):
    """Remove price data older than PRICE_HISTORY_YEARS to prevent unbounded growth."""
    cutoff = (datetime.now() - timedelta(days=365 * PRICE_HISTORY_YEARS)).strftime("%Y-%m-%d")
    result = conn.execute(text("""
        DELETE FROM prices_daily WHERE date < :cutoff
    """), {"cutoff": cutoff})
    deleted = result.rowcount
    if deleted > 0:
        log(f"Pruned {deleted} price rows older than {cutoff}")


def needs_backfill(conn, symbol: str) -> bool:
    """Check if a symbol needs long-history backfill (fewer than 1500 rows)."""
    row = conn.execute(text(
        "SELECT COUNT(*) FROM prices_daily WHERE symbol=:s"
    ), {"s": symbol}).fetchone()
    return (row[0] if row else 0) < 1500


def main(backfill: bool = False):
    engine = get_engine(DB_PATH)

    with engine.begin() as conn:
        symbols = get_universe_symbols(conn)

    if not symbols:
        log("Universe is empty. Run update_universe_sp500 first.")
        return

    total = len(symbols)
    wrote = 0
    excluded = 0

    # Determine which symbols need backfill
    if backfill:
        backfill_needed = symbols
    else:
        with engine.begin() as conn:
            backfill_needed = [s for s in symbols if needs_backfill(conn, s)]

    if backfill_needed:
        log(f"Backfilling {len(backfill_needed)} symbols with {PRICE_HISTORY_YEARS}y history...")
        for sym in backfill_needed:
            data = fetch_long_history([sym], years=PRICE_HISTORY_YEARS)
            if sym in data:
                with engine.begin() as conn:
                    upsert_prices(conn, sym, data[sym])
                wrote += 1
            else:
                with engine.begin() as conn:
                    exclude_symbol(conn, sym, "No historical data from yfinance")
                excluded += 1
        log(f"Backfill complete: {wrote} symbols loaded, {excluded} excluded")
        wrote = 0

    # Daily update: fetch recent 5d for all symbols
    log(f"Fetching recent prices for {total} symbols...")
    for batch in chunk(symbols, BATCH_SIZE):
        data = fetch_batch(batch)

        bad = [s for s in batch if s not in data]
        if bad:
            with engine.begin() as conn:
                for s in bad:
                    exclude_symbol(conn, s, "No recent data (possibly delisted)")
            excluded += len(bad)

        with engine.begin() as conn:
            for sym, df in data.items():
                upsert_prices(conn, sym, df)
        wrote += len(data)

        log(f"batch {batch[0]}..{batch[-1]}  got={len(data)}/{len(batch)}  total≈{wrote}/{total}")
        time.sleep(SLEEP_BETWEEN_BATCHES)

    # Prune old data
    with engine.begin() as conn:
        prune_old_prices(conn)

    now_et = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")
    log(f"Price ingest complete at {now_et}. Symbols updated={wrote}/{total}. Excluded={excluded}")


if __name__ == "__main__":
    import sys
    main(backfill="--backfill" in sys.argv)

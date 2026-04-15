"""
Update the stock universe from the current S&P 500 composition.
Uses Wikipedia as the source (no API key required).
Runs automatically monthly via cron.
"""
import pandas as pd
from sqlalchemy import text
from datetime import datetime, timezone

from src.config import DB_PATH
from src.db import get_engine


def fetch_sp500_symbols() -> list:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        tables = pd.read_html(url)
        df = tables[0]
        symbols = df["Symbol"].tolist()
        # Clean up: replace dots with hyphens (BRK.B → BRK-B)
        symbols = [str(s).replace(".", "-").strip() for s in symbols]
        return sorted(set(symbols))
    except Exception as e:
        print(f"Failed to fetch S&P 500 list: {e}")
        return []


def main():
    symbols = fetch_sp500_symbols()
    if not symbols:
        print("No symbols fetched — universe not updated")
        return

    engine = get_engine(DB_PATH)
    with engine.begin() as conn:
        # Get current universe
        existing = set(r[0] for r in conn.execute(text("SELECT symbol FROM universe")).fetchall())

        added = 0
        for sym in symbols:
            if sym not in existing:
                conn.execute(text(
                    "INSERT OR IGNORE INTO universe(symbol) VALUES (:s)"
                ), {"s": sym})
                added += 1

        # Note: we don't remove symbols that left the S&P 500
        # They'll get excluded naturally if yfinance can't fetch them
        # Removing them would force sells which triggers tax events

    print(f"Universe updated: {len(symbols)} S&P 500 symbols | {added} new additions | Total: {len(existing) + added}")


if __name__ == "__main__":
    main()

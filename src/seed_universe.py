from sqlalchemy import text
from src.config import DB_PATH
from src.db import get_engine

TICKERS = [
    "AAPL","MSFT","GOOGL","AMZN","NVDA",
    "META","BRK-B","JPM","UNH","XOM",
    "COST","AVGO","LLY","HD","V"
]

if __name__ == "__main__":
    engine = get_engine(DB_PATH)
    with engine.begin() as conn:
        for t in TICKERS:
            conn.execute(text("INSERT OR IGNORE INTO universe(symbol) VALUES (:s)"), {"s": t})
    print(f"Seeded universe with {len(TICKERS)} symbols.")

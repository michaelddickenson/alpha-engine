from sqlalchemy import text
from src.config import DB_PATH
from src.db import get_engine

if __name__ == "__main__":
    engine = get_engine(DB_PATH)
    with engine.begin() as conn:
        conn.execute(text("""
          INSERT INTO holdings(symbol, shares, avg_cost)
          VALUES ('AAPL', 10, 150)
          ON CONFLICT(symbol) DO UPDATE SET shares=excluded.shares, avg_cost=excluded.avg_cost
        """))
        conn.execute(text("""
          INSERT INTO state(key, value)
          VALUES ('cash', '0')
          ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """))
    print("Seeded AAPL holding.")

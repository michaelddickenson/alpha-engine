from sqlalchemy import text
from src.config import DB_PATH
from src.db import get_engine

if __name__ == "__main__":
    engine = get_engine(DB_PATH)
    with engine.begin() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM universe")).fetchone()[0]
        print("universe count =", n)
        sample = conn.execute(text("SELECT symbol FROM universe ORDER BY symbol LIMIT 25")).fetchall()
        print("first 25:", [r[0] for r in sample])

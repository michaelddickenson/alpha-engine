from sqlalchemy import text
from datetime import datetime, timezone

from src.config import DB_PATH
from src.db import get_engine

SEED_BUY_TIME_UTC = "2024-01-01 00:00:00"  # make it long-term for testing

def main():
    engine = get_engine(DB_PATH)
    with engine.begin() as conn:
        holdings = conn.execute(text("SELECT symbol, shares, avg_cost FROM holdings WHERE shares > 0")).fetchall()

        for sym, sh, avg_cost in holdings:
            sh = float(sh)
            avg_cost = float(avg_cost)

            lot_row = conn.execute(text("""
              SELECT COALESCE(SUM(shares_remaining), 0)
              FROM lots
              WHERE symbol=:sym
            """), {"sym": sym}).fetchone()
            lot_shares = float(lot_row[0]) if lot_row and lot_row[0] is not None else 0.0

            missing = sh - lot_shares
            if missing > 1e-8:
                conn.execute(text("""
                  INSERT INTO lots(symbol, buy_time_utc, shares_remaining, cost_per_share)
                  VALUES (:sym, :t, :sh, :cps)
                """), {"sym": sym, "t": SEED_BUY_TIME_UTC, "sh": missing, "cps": avg_cost})

                print(f"{sym}: added seed lot for {missing:.6f} shares @ {avg_cost:.2f}")
            else:
                print(f"{sym}: lots OK (holdings={sh:.6f}, lots={lot_shares:.6f})")

if __name__ == "__main__":
    main()

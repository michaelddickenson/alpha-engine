from sqlalchemy import text
from src.config import DB_PATH
from src.db import get_engine

def main():
    engine = get_engine(DB_PATH)
    with engine.begin() as conn:
        cash_row = conn.execute(text("SELECT value FROM state WHERE key='cash'")).fetchone()
        cash = float(cash_row[0]) if cash_row else 0.0

        print(f"\nCASH: ${cash:,.2f}\n")

        print("HOLDINGS:")
        rows = conn.execute(text("""
          SELECT symbol, shares, avg_cost
          FROM holdings
          WHERE shares > 0
          ORDER BY symbol
        """)).fetchall()

        for sym, sh, ac in rows:
            print(f"  {sym:6s}  {float(sh):10.6f} sh   avg_cost={float(ac):.2f}")

        print("\nLOTS (by symbol, total remaining):")
        lot_rows = conn.execute(text("""
          SELECT symbol, COUNT(*) as n_lots, SUM(shares_remaining) as sh
          FROM lots
          WHERE shares_remaining > 0
          GROUP BY symbol
          ORDER BY symbol
        """)).fetchall()

        for sym, n, sh in lot_rows:
            print(f"  {sym:6s}  lots={int(n):2d}   shares={float(sh):10.6f}")

        print("\nLAST 10 FILLS:")
        fills = conn.execute(text("""
          SELECT fill_time_utc, symbol, side, shares, price
          FROM fills
          ORDER BY id DESC
          LIMIT 10
        """)).fetchall()

        for t, sym, side, sh, px in fills:
            print(f"  {t}  {sym:6s} {side:4s}  {float(sh):10.6f} @ {float(px):.2f}")

        next_reb = conn.execute(text("""
          SELECT value FROM portfolio_meta WHERE key='next_rebalance_date'
        """)).fetchone()
        if next_reb:
            print(f"\nNEXT REBALANCE (ET): {next_reb[0]}\n")

if __name__ == "__main__":
    main()

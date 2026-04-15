"""
Mark to market: records daily portfolio NAV vs SPY for performance tracking.
"""
from datetime import datetime
import pytz
import yfinance as yf
from sqlalchemy import text

from src.config import DB_PATH
from src.db import get_engine

ET = pytz.timezone("America/New_York")


def get_spy_price() -> float | None:
    try:
        ticker = yf.Ticker("SPY")
        hist = ticker.history(period="5d", auto_adjust=False)
        if hist is not None and not hist.empty:
            return float(hist["Close"].dropna().iloc[-1])
    except Exception:
        pass
    return None


def main():
    engine = get_engine(DB_PATH)
    asof_date = datetime.now(ET).date().isoformat()

    with engine.begin() as conn:
        cash_row = conn.execute(text("SELECT value FROM state WHERE key='cash'")).fetchone()
        cash = float(cash_row[0]) if cash_row else 0.0

        holdings = conn.execute(text(
            "SELECT symbol, shares, avg_cost FROM holdings WHERE shares > 0.0001"
        )).fetchall()

        total_value = cash
        total_cost = cash
        missing = []

        for sym, shares, avg_cost in holdings:
            row = conn.execute(text("""
                SELECT adj_close FROM prices_daily
                WHERE symbol=:s ORDER BY date DESC LIMIT 1
            """), {"s": sym}).fetchone()

            if row:
                px = float(row[0])
                total_value += float(shares) * px
                total_cost += float(shares) * float(avg_cost)
            else:
                missing.append(sym)

        unrealized = total_value - total_cost
        spy_price = get_spy_price()

        conn.execute(text("""
            INSERT INTO nav_history(asof_date, total_value, total_cost, cash, unrealized_pnl, spy_close)
            VALUES (:d, :tv, :tc, :cash, :u, :spy)
            ON CONFLICT(asof_date) DO UPDATE SET
              total_value=excluded.total_value,
              total_cost=excluded.total_cost,
              cash=excluded.cash,
              unrealized_pnl=excluded.unrealized_pnl,
              spy_close=excluded.spy_close
        """), {
            "d": asof_date,
            "tv": total_value,
            "tc": total_cost,
            "cash": cash,
            "u": unrealized,
            "spy": spy_price,
        })

        # Prune NAV history older than 5 years
        conn.execute(text("""
            DELETE FROM nav_history WHERE asof_date < date(:d, '-5 years')
        """), {"d": asof_date})

    status = f"NAV={total_value:,.2f} | Unrealized={unrealized:+,.2f} | SPY=${spy_price:.2f}" if spy_price else f"NAV={total_value:,.2f}"
    if missing:
        print(f"NAV saved for {asof_date}: {status} (missing prices: {missing})")
    else:
        print(f"NAV saved for {asof_date}: {status}")


if __name__ == "__main__":
    main()

from sqlalchemy import text
import pandas as pd
from datetime import datetime
import math

from src.config import DB_PATH
from src.db import get_engine

def _to_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")

def xirr(cashflows: list[tuple[datetime, float]], guess: float = 0.10) -> float:
    """
    cashflows: list of (date, amount)
      - contributions should be NEGATIVE (cash out)
      - final value should be POSITIVE (cash in)
    returns annualized IRR
    """
    # Newton's method
    r = guess
    for _ in range(100):
        f = 0.0
        df = 0.0
        t0 = cashflows[0][0]
        for (t, c) in cashflows:
            years = (t - t0).days / 365.25
            denom = (1.0 + r) ** years
            f += c / denom
            # derivative
            if denom != 0:
                df += (-years * c) / ((1.0 + r) ** (years + 1.0))
        if abs(df) < 1e-12:
            break
        new_r = r - f / df
        if abs(new_r - r) < 1e-10:
            r = new_r
            break
        r = new_r
    return r

def main():
    engine = get_engine(DB_PATH)
    with engine.begin() as conn:
        rid = conn.execute(text("SELECT MAX(run_id) FROM bt_runs")).fetchone()[0]
        if not rid:
            print("No backtest runs.")
            return

        rows = conn.execute(text("""
          SELECT date, port_value, spy_value, turnover_dollars, contribution
          FROM bt_daily
          WHERE run_id=:rid
          ORDER BY date
        """), {"rid": rid}).fetchall()

    df = pd.DataFrame(rows, columns=["date", "port", "spy", "turnover", "contrib"])
    if df.empty:
        print("No bt_daily rows.")
        return

    # Basic info
    total_contrib = float(df["contrib"].sum())
    end_port = float(df["port"].iloc[-1])
    end_spy = float(df["spy"].iloc[-1])

    # Build cashflows for XIRR:
    # contributions are cash OUT (negative), final value is cash IN (positive)
    cfs_port = []
    cfs_spy = []
    for _, r in df.iterrows():
        d = _to_dt(r["date"])
        c = float(r["contrib"])
        if c != 0:
            cfs_port.append((d, -c))
            cfs_spy.append((d, -c))

    # add final liquidation value on last date
    end_date = _to_dt(df["date"].iloc[-1])
    cfs_port.append((end_date, end_port))
    cfs_spy.append((end_date, end_spy))

    # If somehow no contributions, avoid crash
    if len(cfs_port) < 2 or total_contrib <= 0:
        print(f"Run: {rid}")
        print("No contributions recorded; cannot compute XIRR.")
        return

    irr_port = xirr(cfs_port, guess=0.12)
    irr_spy = xirr(cfs_spy, guess=0.10)

    # Turnover
    total_turnover = float(df["turnover"].sum())
    turnover_ratio = total_turnover / total_contrib if total_contrib > 0 else 0.0

    print(f"Run: {rid}")
    print(f"Period: {df['date'].iloc[0]} -> {df['date'].iloc[-1]}")
    print(f"Total contributed: ${total_contrib:,.2f}")
    print(f"End value (strategy): ${end_port:,.2f}")
    print(f"End value (SPY):      ${end_spy:,.2f}")
    print(f"Multiple on contrib (strategy): {end_port/total_contrib:.2f}x")
    print(f"Multiple on contrib (SPY):      {end_spy/total_contrib:.2f}x")
    print(f"XIRR (strategy): {irr_port*100:.2f}%")
    print(f"XIRR (SPY):      {irr_spy*100:.2f}%")
    print(f"Turnover $: ${total_turnover:,.2f}")
    print(f"Turnover / contributed: {turnover_ratio:.2f}x")

if __name__ == "__main__":
    main()

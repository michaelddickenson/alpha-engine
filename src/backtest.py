# src/backtest.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
import pytz
import pandas as pd
from sqlalchemy import text

from src.config import DB_PATH
from src.db import get_engine

ET = pytz.timezone("America/New_York")

HOLD_N = 20
BUFFER_RANK = 60

# Momentum settings (12-1 momentum using trading days)
MOM_LONG_DAYS = 252   # ~12 months
MOM_SKIP_DAYS = 21    # ~1 month

VOL_LOOKBACK_DAYS = 126
VOL_FLOOR = 0.10

MIN_TRADE_DOLLARS = 10.0
CASH_RESERVE = 5.00
MAX_BUY_FRACTION_OF_CONTRIB = 0.50

# Backtest-only contribution fallback (so you can backtest 2016-2026 even if your real schedule starts 2026-01-02)
DEFAULT_BACKTEST_CONTRIB = 200.0  # change this for research runs as desired

@dataclass
class LotPick:
    lot_id: int
    buy_time_utc: str
    shares: float
    cost_per_share: float
    holding_days: int
    term: str  # SHORT/LONG


def is_biweekly_friday(d: date, anchor: date) -> bool:
    # Biweekly contributions on Fridays starting at anchor
    if d.weekday() != 4:  # Friday
        return False
    delta = (d - anchor).days
    return delta >= 0 and (delta % 14 == 0)


def get_trading_dates(conn, start: str, end: str) -> list[str]:
    rows = conn.execute(text("""
      SELECT DISTINCT date
      FROM prices_daily
      WHERE date BETWEEN :s AND :e
      ORDER BY date
    """), {"s": start, "e": end}).fetchall()
    return [r[0] for r in rows]


def get_close(conn, sym: str, d: str) -> float | None:
    r = conn.execute(text("""
      SELECT close FROM prices_daily WHERE symbol=:s AND date=:d
    """), {"s": sym, "d": d}).fetchone()
    return float(r[0]) if r and r[0] is not None else None


def get_universe(conn) -> list[str]:
    rows = conn.execute(text("SELECT symbol FROM universe ORDER BY symbol")).fetchall()
    # exclude benchmark from selection
    return [r[0] for r in rows if r[0] != "SPY"]


def score_universe_asof(conn, universe: list[str], asof_date: str) -> list[tuple[str, float]]:
    """
    12-1 momentum score (using closes up to asof_date).
    Score = (price at t-21) / (price at t-252) - 1
    Requires enough history.
    """
    scored: list[tuple[str, float]] = []

    need = MOM_LONG_DAYS + MOM_SKIP_DAYS + 5  # small buffer
    for sym in universe:
        rows = conn.execute(text("""
          SELECT date, close
          FROM prices_daily
          WHERE symbol=:sym AND date <= :d AND close IS NOT NULL
          ORDER BY date DESC
          LIMIT :n
        """), {"sym": sym, "d": asof_date, "n": need}).fetchall()

        if len(rows) < (MOM_LONG_DAYS + MOM_SKIP_DAYS + 1):
            continue

        # reverse so oldest -> newest
        rows = list(reversed(rows))
        closes = [float(r[1]) for r in rows]

        # index from end (newest is -1)
        p_skip = closes[-(MOM_SKIP_DAYS + 1)]     # close at t-21
        p_long = closes[-(MOM_LONG_DAYS + 1)]     # close at t-252

        if p_skip <= 0 or p_long <= 0:
            continue

        score = (p_skip / p_long) - 1.0
        scored.append((sym, float(score)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def dedupe_share_classes(scored: list[tuple[str, float]]) -> list[tuple[str, float]]:
    scores = {sym: float(sc) for sym, sc in scored}
    if "GOOG" in scores and "GOOGL" in scores:
        if scores["GOOG"] >= scores["GOOGL"]:
            del scores["GOOGL"]
        else:
            del scores["GOOG"]
    if "BRK-A" in scores and "BRK-B" in scores:
        if scores["BRK-A"] >= scores["BRK-B"]:
            del scores["BRK-B"]
        else:
            del scores["BRK-A"]
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def compute_inverse_vol_weights_asof(conn, symbols: list[str], asof_date: str) -> dict[str, float]:
    inv = {}
    for s in symbols:
        rows = conn.execute(text("""
          SELECT date, close
          FROM prices_daily
          WHERE symbol=:sym AND date <= :d AND close IS NOT NULL
          ORDER BY date DESC
          LIMIT :n
        """), {"sym": s, "d": asof_date, "n": VOL_LOOKBACK_DAYS + 1}).fetchall()

        if len(rows) < 30:
            continue

        rows = list(reversed(rows))
        closes = pd.Series([float(r[1]) for r in rows])
        rets = closes.pct_change().dropna()
        if len(rets) < 20:
            continue

        vol = float(rets.std()) * (252 ** 0.5)
        vol = max(vol, VOL_FLOOR)
        inv[s] = 1.0 / vol

    if not inv:
        w = 1.0 / len(symbols)
        return {s: w for s in symbols}

    tot = sum(inv.values())
    return {s: inv.get(s, 0.0) / tot for s in symbols}


def select_targets_asof(scored: list[tuple[str, float]], current_holdings: list[str]) -> list[str]:
    rank = {sym: i + 1 for i, (sym, _) in enumerate(scored)}
    topN = [sym for sym, _ in scored[:HOLD_N]]

    keep = []
    for sym in current_holdings:
        r = rank.get(sym)
        if r is not None and r <= BUFFER_RANK:
            keep.append(sym)

    targets = []
    for sym in keep + topN:
        if sym not in targets:
            targets.append(sym)
        if len(targets) >= HOLD_N:
            break
    return targets


def get_contrib_amount(conn, d: str) -> float:
    """
    Backtest behavior:
    - If contribution_schedule has an amount effective on or before date d, use it.
    - Otherwise fall back to DEFAULT_BACKTEST_CONTRIB so you can backtest pre-2026.
    """
    row = conn.execute(text("""
      SELECT amount FROM contribution_schedule
      WHERE effective_date <= :d
      ORDER BY effective_date DESC
      LIMIT 1
    """), {"d": d}).fetchone()
    if row:
        return float(row[0])
    return float(DEFAULT_BACKTEST_CONTRIB)


def main():
    name = "bt_realistic_v1"

    # For 10y research prior to 2026-01-02 real start:
    anchor = date(2016, 1, 8)   # Friday anchor near start
    start_date = "2016-01-01"
    end_date   = "2026-02-11"

    engine = get_engine(DB_PATH)
    with engine.begin() as conn:
        conn.execute(text("""
          INSERT INTO bt_runs(name, start_date, end_date, created_utc)
          VALUES (:n, :s, :e, :t)
        """), {"n": name, "s": start_date, "e": end_date,
               "t": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")})
        run_id = conn.execute(text("SELECT MAX(run_id) FROM bt_runs")).fetchone()[0]

    # Sim state (paper portfolio)
    cash = 0.0
    holdings: dict[str, float] = {}
    lots: list[dict] = []  # not fully used yet (placeholder for future sell logic)
    spy_shares = 0.0

    with engine.begin() as conn:
        dates = get_trading_dates(conn, start_date, end_date)
        universe = get_universe(conn)

    for d in dates:
        dt = datetime.strptime(d, "%Y-%m-%d").date()

        turnover_dollars = 0.0
        contribution = 0.0
        realized = 0.0
        realized_short = 0.0
        realized_long = 0.0

        if is_biweekly_friday(dt, anchor):
            with engine.begin() as conn:
                contrib = get_contrib_amount(conn, d)

            contribution = float(contrib)
            if contribution > 0:
                cash += contribution


                # benchmark: buy SPY with full contrib at close
                with engine.begin() as conn:
                    spy_px = get_close(conn, "SPY", d)
                if spy_px and spy_px > 0:
                    spy_shares += contrib / spy_px

                # scoring/targets/weights as-of d
                with engine.begin() as conn:
                    scored = score_universe_asof(conn, universe, d)
                scored = dedupe_share_classes(scored)

                current_names = [s for s, sh in holdings.items() if sh > 1e-12]
                targets = select_targets_asof(scored, current_names)

                with engine.begin() as conn:
                    px = {s: get_close(conn, s, d) for s in targets}
                px = {k: v for k, v in px.items() if v is not None and v > 0}

                if len(px) >= 5:
                    # inverse-vol target values
                    with engine.begin() as conn:
                        w = compute_inverse_vol_weights_asof(conn, list(px.keys()), d)

                    port_value = cash + sum(holdings.get(s, 0.0) * px.get(s, 0.0) for s in px.keys())
                    target_values = {s: port_value * w.get(s, 0.0) for s in px.keys()}

                    max_buy_per_symbol = max(MIN_TRADE_DOLLARS, contrib * MAX_BUY_FRACTION_OF_CONTRIB)

                    # BUY-ONLY backtest v1 (low turnover). Later we can add selective sells.
                    gaps = []
                    for s in px.keys():
                        cur_val = holdings.get(s, 0.0) * px[s]
                        gap = target_values.get(s, 0.0) - cur_val
                        if gap > 0:
                            gaps.append((s, gap))
                    gaps.sort(key=lambda x: x[1], reverse=True)

                    for s, gap in gaps:
                        if cash <= CASH_RESERVE:
                            break
                        buy_dollars = min(gap, cash - CASH_RESERVE, max_buy_per_symbol)
                        if buy_dollars < MIN_TRADE_DOLLARS:
                            continue
                        buy_sh = buy_dollars / px[s]
                        holdings[s] = holdings.get(s, 0.0) + buy_sh
                        cash -= buy_dollars
                        turnover_dollars += buy_dollars
                        lots.append({"symbol": s, "buy_date": d, "shares": buy_sh, "cps": px[s]})

        # daily value calc (end of day)
        with engine.begin() as conn:
            val = cash
            for s, sh in holdings.items():
                if sh <= 1e-12:
                    continue
                p = get_close(conn, s, d)
                if p and p > 0:
                    val += sh * p

            spy_px = get_close(conn, "SPY", d)
            spy_val = (spy_shares * spy_px) if spy_px and spy_px > 0 else 0.0

            conn.execute(text("""
            INSERT OR REPLACE INTO bt_daily(
                run_id,
                date,
                port_value,
                spy_value,
                cash,
                contribution,
                turnover_dollars,
                realized_gain,
                realized_gain_short,
                realized_gain_long
            ) VALUES (
                :rid,
                :d,
                :pv,
                :sv,
                :cash,
                :contrib,
                :to,
                :rg,
                :rgs,
                :rgl
            )
            """), {
                "rid": run_id,
                "d": d,
                "pv": val,
                "sv": spy_val,
                "cash": cash,
                "contrib": contribution,   # <-- NEW
                "to": turnover_dollars,
                "rg": realized,
                "rgs": realized_short,
                "rgl": realized_long
            })

    print("Backtest complete. Run report_bt to summarize.")


if __name__ == "__main__":
    main()

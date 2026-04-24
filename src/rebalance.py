"""
Rebalance Engine

Strategy:
- Quality momentum: top scored S&P 500 stocks (price > $10, adequate history)
- Dynamic hold count: floor(account_value / 50), capped 5-15
- RISK ON (SPY > 200-day MA): deploy to top-N positions, full rebalance
- RISK OFF (SPY < 200-day MA): deploy contribution to top 5 only, no trims
- Tax-aware: never sell positions held < 365 days
- Full exits allowed only for positions held 365+ days that fall out of targets
- Biweekly Friday cadence

This module ONLY generates a plan (no DB writes when called normally).
The web UI records actual executed trades.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from typing import Optional

import pytz
import yfinance as yf
import pandas as pd
from sqlalchemy import text

from src.config import DB_PATH
from src.db import get_engine

ET = pytz.timezone("America/New_York")
NEXT_REBALANCE_KEY = "next_rebalance_date"
FIRST_REBALANCE_DATE = os.getenv("FIRST_REBALANCE_DATE")
if not FIRST_REBALANCE_DATE:
    raise ValueError(
        "FIRST_REBALANCE_DATE env var must be set to a Friday in YYYY-MM-DD format. "
        "This is the anchor date for the biweekly rebalance schedule — a wrong or "
        "missing value would silently misalign every rebalance. See .env.example."
    )

# Dynamic hold count parameters
MIN_POSITION_DOLLARS = 50.0
MIN_HOLD_N = 5
MAX_HOLD_N = 15

# Buffer: keep holdings ranked up to this buffer multiple of hold_n
BUFFER_RANK_MULTIPLE = 4  # keep if rank <= hold_n * 4

# Tax rule
MIN_HOLD_DAYS_TO_SELL = 365

# Risk management
VOL_LOOKBACK_DAYS = 126
VOL_FLOOR = 0.10

# Trade minimums
MIN_TRADE_DOLLARS = 10.0
CASH_RESERVE = 5.0
SELL_DRIFT_BAND = 0.15
MIN_SELL_DOLLARS = 150.0

RISK_OFF_MAX_POSITIONS = 5  # during RISK OFF, only deploy to top 5


def _ensure_out_dir() -> Path:
    out_dir = Path(os.getenv("OUT_DIR", "out"))
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def compute_dynamic_hold_n(account_value: float) -> int:
    """Dynamically size portfolio based on account value."""
    n = int(account_value / MIN_POSITION_DOLLARS)
    return max(MIN_HOLD_N, min(MAX_HOLD_N, n))


def next_biweekly_friday(on_or_after: date, anchor: date) -> date:
    d = on_or_after
    days_to_fri = (4 - d.weekday()) % 7
    d = d + timedelta(days=days_to_fri)
    if d < anchor:
        return anchor
    delta_days = (d - anchor).days
    mod = delta_days % 14
    if mod != 0:
        d = d + timedelta(days=(14 - mod))
    return d


def is_market_risk_on() -> bool:
    try:
        ticker = yf.Ticker("SPY")
        hist = ticker.history(period="1y", auto_adjust=False)
        if hist is None or hist.empty or len(hist) < 200:
            print("SPY data insufficient — defaulting RISK ON")
            return True
        closes = hist["Close"].dropna()
        ma200 = closes.rolling(200).mean().iloc[-1]
        last = closes.iloc[-1]
        risk_on = bool(last > ma200)
        pct = (last / ma200 - 1) * 100
        print(f"SPY ${last:.2f} vs 200-MA ${ma200:.2f} ({pct:+.1f}%) → {'RISK ON' if risk_on else 'RISK OFF'}")
        return risk_on
    except Exception as e:
        print(f"SPY check failed ({e}) — defaulting RISK ON")
        return True


def get_prices_batch(symbols: list) -> dict:
    if not symbols:
        return {}
    prices = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d", auto_adjust=False)
            if hist is not None and not hist.empty:
                close = hist["Close"].dropna()
                if not close.empty:
                    prices[sym] = float(close.iloc[-1])
        except Exception:
            continue
    return prices


def compute_inverse_vol_weights(conn, symbols: list, asof_date: str) -> dict:
    inv = {}
    for s in symbols:
        rows = conn.execute(text("""
          SELECT close FROM prices_daily
          WHERE symbol=:s AND date <= :d
          ORDER BY date DESC LIMIT :n
        """), {"s": s, "d": asof_date, "n": VOL_LOOKBACK_DAYS + 1}).fetchall()
        if len(rows) < 30:
            continue
        closes = pd.Series([float(r[0]) for r in reversed(rows)])
        rets = closes.pct_change().dropna()
        vol = float(rets.std()) * (252 ** 0.5)
        vol = max(vol, VOL_FLOOR)
        inv[s] = 1.0 / vol

    if not inv:
        w = 1.0 / len(symbols)
        return {s: w for s in symbols}

    total = sum(inv.values())
    return {s: inv.get(s, 0.0) / total for s in symbols}


def dedupe_share_classes(scored: list) -> list:
    keep = dict(scored)
    if "GOOG" in keep and "GOOGL" in keep:
        del keep["GOOG" if keep["GOOG"] < keep["GOOGL"] else "GOOGL"]
    if "BRK-A" in keep and "BRK-B" in keep:
        del keep["BRK-A" if keep["BRK-A"] < keep["BRK-B"] else "BRK-B"]
    return sorted(keep.items(), key=lambda x: x[1], reverse=True)


def get_meta(conn, key: str) -> Optional[str]:
    row = conn.execute(text("SELECT value FROM portfolio_meta WHERE key=:k"), {"k": key}).fetchone()
    return row[0] if row else None


def set_meta(conn, key: str, value: str):
    conn.execute(text("""
      INSERT INTO portfolio_meta(key, value) VALUES (:k, :v)
      ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """), {"k": key, "v": value})


def get_cash(conn) -> float:
    row = conn.execute(text("SELECT value FROM state WHERE key='cash'")).fetchone()
    return float(row[0]) if row else 0.0


def get_contribution(conn, asof: str) -> float:
    row = conn.execute(text("""
        SELECT amount FROM contribution_schedule
        WHERE effective_date <= :d
        ORDER BY effective_date DESC LIMIT 1
    """), {"d": asof}).fetchone()
    if row:
        return float(row[0])
    default = get_meta(conn, "default_contribution")
    return float(default) if default else 0.0


def get_holdings(conn) -> dict:
    rows = conn.execute(text("SELECT symbol, shares FROM holdings WHERE shares > 0.0001")).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def get_latest_scores(conn):
    latest = conn.execute(text("SELECT MAX(run_date) FROM scores")).fetchone()[0]
    if not latest:
        return [], None
    rows = conn.execute(text("""
      SELECT symbol, score FROM scores
      WHERE run_date=:d ORDER BY score DESC
    """), {"d": latest}).fetchall()
    return [(r[0], float(r[1])) for r in rows], latest


def check_lot_eligibility(conn, symbol: str, sell_time_utc: str) -> dict:
    """Returns info about a symbol's lots and whether any are eligible to sell."""
    sell_dt = datetime.strptime(sell_time_utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    lots = conn.execute(text("""
        SELECT lot_id, buy_time_utc, shares_remaining, cost_per_share
        FROM lots WHERE symbol=:sym AND shares_remaining > 0
    """), {"sym": symbol}).fetchall()

    total_shares = sum(float(r[2]) for r in lots)
    eligible_shares = 0.0
    eligible_lots = []

    for lot_id, buy_time_utc, sh_rem, cps in lots:
        buy_dt = datetime.strptime(buy_time_utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        holding_days = (sell_dt - buy_dt).days
        if holding_days >= MIN_HOLD_DAYS_TO_SELL:
            eligible_shares += float(sh_rem)
            eligible_lots.append({
                "lot_id": int(lot_id),
                "shares": float(sh_rem),
                "cost_per_share": float(cps),
                "holding_days": holding_days,
                "term": "LONG",
            })

    return {
        "total_shares": total_shares,
        "eligible_shares": eligible_shares,
        "eligible_lots": eligible_lots,
        "can_fully_exit": eligible_shares >= total_shares * 0.999,
    }


def _write_plan_files(plan_date: str, risk_on: bool, contrib: float,
                      cash_before: float, cash_after: float,
                      hold_n: int, account_value: float,
                      sells: list, buys: list, targets: list,
                      score_date: str) -> tuple:
    out_dir = _ensure_out_dir()
    csv_path = out_dir / f"trade_plan_{plan_date}.csv"
    txt_path = out_dir / f"trade_plan_{plan_date}.txt"

    # CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "action", "symbol", "dollars", "shares_est",
                    "ref_price", "order_type", "notes"])
        for s in sells:
            w.writerow([plan_date, "SELL", s["symbol"],
                        f"{s['dollars']:.2f}", f"{s['shares']:.6f}",
                        f"{s['ref_price']:.2f}", "Market (shares)", s.get("notes", "")])
        for b in buys:
            w.writerow([plan_date, "BUY", b["symbol"],
                        f"{b['dollars']:.2f}", f"{b['shares_est']:.6f}",
                        f"{b['ref_price']:.2f}", "Market (dollars)", b.get("notes", "")])

    # Human-readable TXT
    lines = [
        f"═══════════════════════════════════════════════════════",
        f"  ALPHA ENGINE TRADE PLAN — {plan_date}",
        f"═══════════════════════════════════════════════════════",
        f"",
        f"  Market Regime : {'✅ RISK ON'  if risk_on else '⚠️  RISK OFF (deploying to top 5 only)'}",
        f"  Score Date    : {score_date}",
        f"  Account Value : ${account_value:,.2f}",
        f"  Cash Before   : ${cash_before:,.2f}",
        f"  Contribution  : ${contrib:,.2f}",
        f"  Cash After    : ${cash_after:,.2f}",
        f"  Target Positions: {hold_n}",
        f"",
        f"───────────────────────────────────────────────────────",
        f"  SELLS  (execute first in your broker)",
        f"───────────────────────────────────────────────────────",
    ]

    if not sells:
        lines.append("  None — all positions too young to sell (<1 year) or no exits needed")
    else:
        for s in sells:
            lines.append(f"  SELL {s['symbol']:6s}  {s['shares']:.4f} shares  ≈${s['dollars']:.2f}  @ ref ${s['ref_price']:.2f}")
            if s.get("notes"):
                lines.append(f"         └─ {s['notes']}")

    lines += [
        f"",
        f"───────────────────────────────────────────────────────",
        f"  BUYS  (dollar-amount orders in your broker)",
        f"───────────────────────────────────────────────────────",
    ]

    if not buys:
        lines.append("  None")
    else:
        for b in buys:
            lines.append(f"  BUY  {b['symbol']:6s}  ${b['dollars']:.2f}  ≈{b['shares_est']:.4f} sh  @ ref ${b['ref_price']:.2f}")

    lines += [
        f"",
        f"───────────────────────────────────────────────────────",
        f"  CURRENT TARGET PORTFOLIO ({hold_n} positions)",
        f"───────────────────────────────────────────────────────",
    ]
    for i, t in enumerate(targets, 1):
        lines.append(f"  {i:2d}. {t}")

    lines += [
        f"",
        f"  ⚠️  Prices are reference only. Your fills may differ.",
        f"  📝  Log your actual trades at your Alpha Engine dashboard.",
        f"═══════════════════════════════════════════════════════",
    ]

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, txt_path


def main():
    import sys
    force = "--force" in sys.argv

    now_et = datetime.now(ET)
    today = now_et.date()
    today_str = today.isoformat()
    anchor = _parse_date(FIRST_REBALANCE_DATE)

    engine = get_engine(DB_PATH)

    # Check if due
    with engine.begin() as conn:
        next_reb_str = get_meta(conn, NEXT_REBALANCE_KEY)
        next_reb = _parse_date(next_reb_str) if next_reb_str else anchor

    if today < next_reb and not force:
        print(f"Not due. Next rebalance={next_reb.isoformat()}, today={today_str}")
        return

    # Market regime
    risk_on = is_market_risk_on()

    # Load state
    with engine.begin() as conn:
        cash0 = get_cash(conn)
        contrib = get_contribution(conn, today_str)
        holdings0 = get_holdings(conn)
        current_syms = list(holdings0.keys())

        scored, score_date = get_latest_scores(conn)
        if not scored:
            print("No scores available. Run: python -m src.score_universe")
            return
        scored = dedupe_share_classes(scored)

    # Compute account value for dynamic hold count
    # Use a quick price fetch to estimate
    all_syms = list(set(current_syms + [s for s, _ in scored[:20]]))
    px = get_prices_batch(all_syms)

    invested_value = sum(holdings0.get(s, 0.0) * px.get(s, 0.0) for s in current_syms if s in px)
    account_value = cash0 + contrib + invested_value
    hold_n = compute_dynamic_hold_n(account_value)

    # Effective max positions based on regime
    effective_max = hold_n if risk_on else min(RISK_OFF_MAX_POSITIONS, hold_n)

    # Build target list
    rank = {sym: i + 1 for i, (sym, _) in enumerate(scored)}
    topN = [sym for sym, _ in scored[:effective_max]]
    buffer_rank = hold_n * BUFFER_RANK_MULTIPLE

    sell_time_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Keep current holdings that are still ranked within buffer
    keep = [s for s in current_syms if rank.get(s, 9999) <= buffer_rank]

    targets = []
    for s in keep + topN:
        if s not in targets:
            targets.append(s)
        if len(targets) >= effective_max:
            break

    # Get prices for everything we need
    needed_syms = list(set(targets) | set(current_syms))
    more_px = get_prices_batch([s for s in needed_syms if s not in px])
    px.update(more_px)

    # Compute weights
    with engine.begin() as conn:
        weights = compute_inverse_vol_weights(conn, targets, today_str)

    cash = cash0 + contrib
    port_value = cash + sum(holdings0.get(s, 0.0) * px.get(s, 0.0)
                            for s in current_syms if s in px)
    target_values = {s: port_value * weights[s] for s in targets}

    # ─── SELL PLAN ───
    sells = []
    for sym in current_syms:
        if sym not in px:
            continue
        cur_sh = holdings0.get(sym, 0.0)
        if cur_sh <= 0:
            continue

        must_exit = sym not in targets
        if not must_exit and not risk_on:
            continue  # During risk off, no trims

        cur_val = cur_sh * px[sym]

        # Check lot eligibility
        with engine.begin() as conn:
            lot_info = check_lot_eligibility(conn, sym, sell_time_utc)

        if must_exit:
            # Full exit only if ALL shares are long-term eligible
            if not lot_info["can_fully_exit"]:
                continue  # Too young, hold it
            shares_to_sell = cur_sh
            notes = "EXIT — dropped from targets (all lots ≥1 year)"
        else:
            # Trim only if significantly overweight
            tgt = target_values.get(sym, 0.0)
            if cur_val <= tgt * (1.0 + SELL_DRIFT_BAND):
                continue
            excess = cur_val - tgt
            if excess < MIN_SELL_DOLLARS:
                continue
            # Only trim eligible shares
            if lot_info["eligible_shares"] <= 0:
                continue
            trim_val = min(excess, lot_info["eligible_shares"] * px[sym])
            shares_to_sell = trim_val / px[sym]
            if shares_to_sell < 0.001:
                continue
            notes = f"TRIM — overweight (eligible lots ≥1 year only)"

        dollars = shares_to_sell * px[sym]
        sells.append({
            "symbol": sym,
            "shares": float(shares_to_sell),
            "dollars": float(dollars),
            "ref_price": float(px[sym]),
            "notes": notes,
        })
        cash += dollars

    # ─── BUY PLAN ───
    buys = []
    gaps = []
    for sym in targets:
        if sym not in px:
            continue
        cur_val = holdings0.get(sym, 0.0) * px[sym]
        gap = target_values.get(sym, 0.0) - cur_val
        if gap > 0:
            gaps.append((sym, gap))

    gaps.sort(key=lambda x: x[1], reverse=True)

    for sym, gap in gaps:
        if cash <= CASH_RESERVE:
            break
        buy_dollars = min(gap, cash - CASH_RESERVE)
        if buy_dollars < MIN_TRADE_DOLLARS:
            continue
        shares_est = buy_dollars / px[sym]
        buys.append({
            "symbol": sym,
            "dollars": float(buy_dollars),
            "shares_est": float(shares_est),
            "ref_price": float(px[sym]),
        })
        cash -= buy_dollars

    cash_after = cash
    next_date = next_biweekly_friday(today + timedelta(days=1), anchor)

    # Write plan files
    csv_path, txt_path = _write_plan_files(
        plan_date=today_str,
        risk_on=risk_on,
        contrib=contrib,
        cash_before=cash0,
        cash_after=cash_after,
        hold_n=hold_n,
        account_value=account_value,
        sells=sells,
        buys=buys,
        targets=targets,
        score_date=score_date or "N/A",
    )

    # Update next rebalance date in DB
    with engine.begin() as conn:
        existing = get_meta(conn, NEXT_REBALANCE_KEY)
        if existing is None:
            set_meta(conn, NEXT_REBALANCE_KEY, anchor.isoformat())
        set_meta(conn, NEXT_REBALANCE_KEY, next_date.isoformat())

    print(f"Plan complete for {today_str}")
    print(f"  Regime: {'RISK ON' if risk_on else 'RISK OFF'} | Hold N: {hold_n} | Score: {score_date}")
    print(f"  Contrib: ${contrib:.2f} | Cash: ${cash0:.2f} → ${cash_after:.2f}")
    print(f"  Sells: {len(sells)} | Buys: {len(buys)}")
    print(f"  Next rebalance: {next_date.isoformat()}")
    print(f"  Plan: {txt_path}")
    print(f"  CSV:  {csv_path}")
    return str(txt_path), str(csv_path)


if __name__ == "__main__":
    main()

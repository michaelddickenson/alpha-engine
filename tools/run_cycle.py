"""
Main cron orchestrator.
Runs daily at 10am ET via cron.
On biweekly Fridays: generates plan + sends email.
Every day: ingests prices, scores universe, marks to market.
First Monday of month: updates S&P 500 universe.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, date
from pathlib import Path

import pytz
from sqlalchemy import text

from src.config import DB_PATH, VENV_PYTHON
from src.db import get_engine, init_db

ET = pytz.timezone("America/New_York")
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "schema.sql"
OUT_DIR = Path(__file__).resolve().parents[1] / "out"


def log_cron_run(engine, run_date: str, status: str, steps: list, error: str = ""):
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO cron_runs(run_date, started_utc, finished_utc, status, steps_completed, error_message)
                VALUES (:d, :s, :f, :st, :steps, :err)
            """), {
                "d": run_date,
                "s": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "f": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "st": status,
                "steps": ", ".join(steps),
                "err": error,
            })
            # Prune old cron run logs (keep 90 days)
            conn.execute(text("""
                DELETE FROM cron_runs WHERE run_date < date(:d, '-90 days')
            """), {"d": run_date})
    except Exception:
        pass


def is_biweekly_friday(today: date, anchor_str: str = os.getenv("FIRST_REBALANCE_DATE", "2026-01-02")) -> bool:
    anchor = datetime.strptime(anchor_str, "%Y-%m-%d").date()
    if today.weekday() != 4:
        return False
    delta = (today - anchor).days
    return delta >= 0 and (delta % 14 == 0)


def is_first_monday_of_month(today: date) -> bool:
    return today.weekday() == 0 and today.day <= 7


def get_anchor(engine) -> str:
    try:
        with engine.begin() as conn:
            row = conn.execute(text(
                "SELECT MIN(effective_date) FROM contribution_schedule"
            )).fetchone()
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    return os.getenv("FIRST_REBALANCE_DATE", "2026-01-02")


def run_step(name: str, fn, steps_done: list, errors: list):
    """Run a step, capture errors without crashing."""
    print(f"\n>>> {name}", flush=True)
    try:
        fn()
        steps_done.append(name)
        print(f"    ✓ {name} complete", flush=True)
    except Exception as e:
        err = f"{name}: {traceback.format_exc()}"
        errors.append(err)
        print(f"    ✗ {name} FAILED: {e}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--send", choices=["gmail", "none"], default="gmail")
    args = ap.parse_args()

    today = datetime.now(ET).date()
    today_str = today.isoformat()
    steps_done = []
    errors = []

    print(f"═══ Alpha Engine Cron — {today_str} ═══", flush=True)

    # Ensure DB is initialized
    engine = get_engine(DB_PATH)
    try:
        init_db(engine, str(SCHEMA_PATH))
    except Exception as e:
        print(f"DB init warning: {e}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ─── Daily steps (always run) ───
    from src import ingest_prices, score_universe, mark_to_market

    run_step("ingest_prices", ingest_prices.main, steps_done, errors)
    run_step("score_universe", score_universe.main, steps_done, errors)
    run_step("mark_to_market", mark_to_market.main, steps_done, errors)

    # ─── Monthly: update S&P 500 universe ───
    if is_first_monday_of_month(today):
        from src import update_universe_sp500
        run_step("update_universe", update_universe_sp500.main, steps_done, errors)

    # ─── Biweekly Friday: generate plan + email ───
    anchor = get_anchor(engine)
    is_rebalance_day = args.force or is_biweekly_friday(today, anchor)

    if not is_rebalance_day:
        print(f"\nNot a rebalance day (anchor={anchor}). Data updated, no plan needed.")
        log_cron_run(engine, today_str, "ok_no_rebalance", steps_done)
        return

    print(f"\n{'─'*40}", flush=True)
    print(f"REBALANCE DAY — generating plan...", flush=True)

    # Generate plan
    txt_path = csv_path = None
    try:
        from src.rebalance import main as rebalance_main
        result = rebalance_main()
        if result:
            txt_path, csv_path = result
            steps_done.append("rebalance_plan")
        else:
            errors.append("rebalance: returned no plan files")
    except Exception as e:
        errors.append(f"rebalance: {traceback.format_exc()}")
        print(f"    ✗ rebalance FAILED: {e}", flush=True)

    # Send email (never crash cron if email fails)
    if txt_path and csv_path and args.send == "gmail":
        try:
            from tools.send_gmail import send_plan_email
            send_plan_email(Path(txt_path), Path(csv_path))
            steps_done.append("email_sent")
        except Exception as e:
            err = f"email: {e}"
            errors.append(err)
            print(f"    ✗ Email failed: {e}", flush=True)
            print(f"    Plan files are available at {txt_path}", flush=True)
    elif args.send == "none":
        print("    Email disabled (--send none)")

    # Log result
    status = "ok" if not errors else "partial" if steps_done else "failed"
    error_summary = " | ".join(errors) if errors else ""
    log_cron_run(engine, today_str, status, steps_done, error_summary)

    if errors:
        print(f"\n⚠️  Completed with errors:", flush=True)
        for e in errors:
            print(f"   • {e[:200]}", flush=True)
    else:
        print(f"\n✓ All steps complete", flush=True)


if __name__ == "__main__":
    main()

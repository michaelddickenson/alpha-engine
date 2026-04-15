from sqlalchemy import text
from datetime import datetime
import pytz

from src.config import DB_PATH
from src.db import get_engine

ET = pytz.timezone("America/New_York")

HOLD_N = 20
BUFFER_RANK = 60

def dedupe_share_classes(scored: list[tuple[str, float]]) -> list[tuple[str, float]]:
    # scored is list of (symbol, score) sorted desc
    scores = {sym: float(score) for sym, score in scored}

    # Alphabet: keep higher score of GOOG vs GOOGL
    if "GOOG" in scores and "GOOGL" in scores:
        if scores["GOOG"] >= scores["GOOGL"]:
            del scores["GOOGL"]
        else:
            del scores["GOOG"]

    # Berkshire: if both appear, keep higher
    if "BRK-A" in scores and "BRK-B" in scores:
        if scores["BRK-A"] >= scores["BRK-B"]:
            del scores["BRK-B"]
        else:
            del scores["BRK-A"]

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)

def main():
    run_date = datetime.now(ET).date().isoformat()

    engine = get_engine(DB_PATH)
    with engine.begin() as conn:
        # Get today's scores (fallback to latest available date if missing)
        row = conn.execute(text("""
          SELECT MAX(run_date) FROM scores
        """)).fetchone()
        latest = row[0]
        if not latest:
            print("No scores found. Run score_universe first.")
            return

        # Rankings for latest score date
        scored = conn.execute(text("""
          SELECT symbol, score
          FROM scores
          WHERE run_date=:d
          ORDER BY score DESC
        """), {"d": latest}).fetchall()

        scored = dedupe_share_classes(scored)

        rank = {sym: i+1 for i, (sym, _) in enumerate(scored)}
        topN = [sym for sym, _ in scored[:HOLD_N]]

        current = [r[0] for r in conn.execute(text("""
          SELECT symbol FROM holdings WHERE shares > 0
        """)).fetchall()]

        # Buffer rule: keep current holdings unless they fall below BUFFER_RANK
        keep = []
        for sym in current:
            r = rank.get(sym)
            if r is not None and r <= BUFFER_RANK:
                keep.append(sym)

        # Final targets = keep + fill from topN, unique, up to HOLD_N
        targets = []
        for sym in keep + topN:
            if sym not in targets:
                targets.append(sym)
            if len(targets) >= HOLD_N:
                break

        print(f"Score date used: {latest}")
        print(f"Current holdings: {len(current)}")
        print(f"Keep (<= rank {BUFFER_RANK}): {len(keep)}")
        print(f"Targets: {len(targets)}")
        print("Top targets:", targets[:20])

if __name__ == "__main__":
    main()

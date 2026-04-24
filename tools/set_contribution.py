from sqlalchemy import text
from src.db import get_engine
from src.config import DB_PATH

EFFECTIVE_DATE = os.getenv("FIRST_REBALANCE_DATE", "2026-01-02")
AMOUNT = 200.0  # change this

e = get_engine(DB_PATH)

with e.begin() as c:
    c.execute(
        text("INSERT OR REPLACE INTO contribution_schedule(effective_date, amount) VALUES (:d, :a)"),
        {"d": EFFECTIVE_DATE, "a": AMOUNT},
    )
    row = c.execute(
        text("SELECT effective_date, amount FROM contribution_schedule ORDER BY effective_date DESC LIMIT 5")
    ).fetchall()

print("OK. Latest contribution_schedule rows:")
for r in row:
    print(r)

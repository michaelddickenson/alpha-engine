from sqlalchemy import text
from src.db import get_engine
from src.config import DB_PATH

e = get_engine(DB_PATH)
with e.begin() as c:
    cash = c.execute(text("SELECT value FROM state WHERE key='cash'")).fetchone()
    next_reb = c.execute(text("SELECT value FROM portfolio_meta WHERE key='next_rebalance_date'")).fetchone()

print("cash =", cash[0] if cash else None)
print("next_rebalance_date =", next_reb[0] if next_reb else None)

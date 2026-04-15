from src.config import DB_PATH, PROJECT_ROOT
from src.db import get_engine, init_db

if __name__ == "__main__":
    engine = get_engine(DB_PATH)
    init_db(engine, str(PROJECT_ROOT / "src" / "schema.sql"))
    print(f"DB initialized at {DB_PATH}")

from pathlib import Path
from sqlalchemy import create_engine, text


def get_engine(db_path: str):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", future=True)


def init_db(engine, schema_sql_path: str):
    schema = Path(schema_sql_path).read_text(encoding="utf-8")
    with engine.begin() as conn:
        for raw in schema.split(";"):
            stmt = raw.strip()
            if not stmt:
                continue
            lines = [ln.strip() for ln in stmt.splitlines()
                     if ln.strip() and not ln.strip().startswith("--")]
            if not lines:
                continue
            conn.execute(text("\n".join(lines)))

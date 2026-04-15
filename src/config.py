from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.getenv("DB_PATH", str(PROJECT_ROOT / "data" / "portfolio.db"))
VENV_PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python3")

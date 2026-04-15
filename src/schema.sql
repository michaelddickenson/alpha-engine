PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS holdings (
  symbol TEXT PRIMARY KEY,
  shares REAL NOT NULL DEFAULT 0.0,
  avg_cost REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fill_time_utc TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
  shares REAL NOT NULL,
  price REAL NOT NULL,
  fees REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS lots (
  lot_id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  buy_time_utc TEXT NOT NULL,
  shares_remaining REAL NOT NULL,
  cost_per_share REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS nav_history (
  asof_date TEXT PRIMARY KEY,
  total_value REAL NOT NULL,
  total_cost REAL NOT NULL,
  cash REAL NOT NULL,
  unrealized_pnl REAL NOT NULL,
  spy_close REAL
);

CREATE TABLE IF NOT EXISTS prices_daily (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  adj_close REAL NOT NULL,
  close REAL NOT NULL,
  PRIMARY KEY(symbol, date)
);

CREATE TABLE IF NOT EXISTS state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contribution_schedule (
  effective_date TEXT NOT NULL,
  amount REAL NOT NULL,
  PRIMARY KEY(effective_date)
);

CREATE TABLE IF NOT EXISTS portfolio_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS universe (
  symbol TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS realized_gains (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sell_time_utc TEXT NOT NULL,
  symbol TEXT NOT NULL,
  lot_id INTEGER NOT NULL,
  shares REAL NOT NULL,
  proceeds REAL NOT NULL,
  cost_basis REAL NOT NULL,
  gain REAL NOT NULL,
  holding_days INTEGER NOT NULL,
  term TEXT NOT NULL CHECK(term IN ('SHORT','LONG')),
  FOREIGN KEY(lot_id) REFERENCES lots(lot_id)
);

CREATE TABLE IF NOT EXISTS scores (
  run_date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  score REAL NOT NULL,
  mom_12_1 REAL,
  mom_6 REAL,
  vol_90 REAL,
  quality_flag INTEGER DEFAULT 1,
  PRIMARY KEY(run_date, symbol)
);

CREATE TABLE IF NOT EXISTS universe_exclusions (
  symbol TEXT PRIMARY KEY,
  reason TEXT NOT NULL,
  first_seen_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp_utc TEXT NOT NULL,
  action TEXT NOT NULL,
  user TEXT NOT NULL DEFAULT 'system',
  details TEXT DEFAULT '',
  success INTEGER NOT NULL DEFAULT 1,
  error_message TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cron_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_date TEXT NOT NULL,
  started_utc TEXT NOT NULL,
  finished_utc TEXT,
  status TEXT NOT NULL DEFAULT 'running',
  steps_completed TEXT DEFAULT '',
  error_message TEXT DEFAULT ''
)

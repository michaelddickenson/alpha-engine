-- Migration 003: Add Admin Activity Log
-- Tracks administrative actions taken through the web UI

CREATE TABLE IF NOT EXISTS admin_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp_utc TEXT NOT NULL,
  action TEXT NOT NULL,           -- e.g., 'force_rebalance', 'refresh_prices', 'update_universe'
  user TEXT,                       -- username if available
  details TEXT,                    -- JSON or text details
  success INTEGER NOT NULL DEFAULT 1,  -- 1=success, 0=failed
  error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_admin_log_time ON admin_log(timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_admin_log_action ON admin_log(action, timestamp_utc DESC);

-- Verify
SELECT 'Admin log table created successfully' as result;

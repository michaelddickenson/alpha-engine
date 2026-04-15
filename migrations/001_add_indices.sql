-- Migration 001: Add Performance Indices
-- This dramatically speeds up queries on heavily-used tables

-- Prices table (most queried)
CREATE INDEX IF NOT EXISTS idx_prices_symbol_date ON prices_daily(symbol, date DESC);

-- Scores table (used for ranking)
CREATE INDEX IF NOT EXISTS idx_scores_date_symbol ON scores(run_date DESC, symbol);
CREATE INDEX IF NOT EXISTS idx_scores_symbol_date ON scores(symbol, run_date DESC);

-- Lots table (tax lot selection)
CREATE INDEX IF NOT EXISTS idx_lots_symbol_remaining ON lots(symbol, shares_remaining) WHERE shares_remaining > 0;
CREATE INDEX IF NOT EXISTS idx_lots_symbol_buy_time ON lots(symbol, buy_time_utc);

-- Fills table (recent history)
CREATE INDEX IF NOT EXISTS idx_fills_time ON fills(fill_time_utc DESC);
CREATE INDEX IF NOT EXISTS idx_fills_symbol ON fills(symbol, fill_time_utc DESC);

-- Holdings table (active positions)
CREATE INDEX IF NOT EXISTS idx_holdings_shares ON holdings(symbol) WHERE shares > 0;

-- Nav history (performance tracking)
CREATE INDEX IF NOT EXISTS idx_nav_date ON nav_history(asof_date DESC);

-- Realized gains (tax reporting)
CREATE INDEX IF NOT EXISTS idx_realized_gains_time ON realized_gains(sell_time_utc DESC);
CREATE INDEX IF NOT EXISTS idx_realized_gains_symbol ON realized_gains(symbol, sell_time_utc DESC);

-- Universe exclusions
CREATE INDEX IF NOT EXISTS idx_exclusions_symbol ON universe_exclusions(symbol);

-- Contribution schedule
CREATE INDEX IF NOT EXISTS idx_contribution_date ON contribution_schedule(effective_date DESC);

-- Verify indices were created
SELECT 'Indices created successfully. Count: ' || COUNT(*) as result
FROM sqlite_master
WHERE type = 'index'
AND name LIKE 'idx_%';

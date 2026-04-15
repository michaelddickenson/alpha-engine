-- Migration 002: Add Default Contribution Meta Key
-- This allows users to set a "standing contribution" that applies to all rebalances

-- Insert default_contribution if it doesn't exist (default to 0)
INSERT OR IGNORE INTO portfolio_meta(key, value)
VALUES ('default_contribution', '0.00');

-- Verify
SELECT 'Default contribution key added. Current value: $' || value as result
FROM portfolio_meta
WHERE key = 'default_contribution';

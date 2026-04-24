-- Add quality_flag column to scores table.
-- schema.sql was updated but no migration was written; live DBs created
-- before this change are missing the column and cause score_universe to
-- fail with: table scores has no column named quality_flag.
ALTER TABLE scores ADD COLUMN quality_flag INTEGER DEFAULT 1;

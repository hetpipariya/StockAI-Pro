-- ====================================================================
-- STOCKAI PRO - DATABASE MIGRATION 001
-- INDEX CLEANUP AND SCALING OPTIMIZATION
-- ====================================================================

-- 1. CLEANUP DUPLICATE AND REDUNDANT INDEXES (To speed up INSERTs and save memory)
-- Drop ix_candle_lookup because uq_candle already enforces a UNIQUE index on (symbol, timeframe, timestamp)
DROP INDEX IF EXISTS ix_candle_lookup;

-- Drop standard indexes covered by unique constraints in instruments table
DROP INDEX IF EXISTS ix_instruments_exchange_symbol;
DROP INDEX IF EXISTS ix_instruments_exchange_token;

-- Drop standard index covered by unique constraint in user_trading_state table
DROP INDEX IF EXISTS ix_user_trading_state_user_id;

-- 2. CREATE SCALING INDEXES FOR HIGH-TRAFFIC FIELDS
-- Orders Table scale indexes
CREATE INDEX IF NOT EXISTS ix_orders_status ON orders (status);
CREATE INDEX IF NOT EXISTS ix_orders_user_timestamp_desc ON orders (user_id, timestamp DESC);

-- Predictions Table scale indexes
CREATE INDEX IF NOT EXISTS ix_predictions_user_timestamp_desc ON predictions (user_id, timestamp DESC);

-- Trade Logs Table scale indexes
CREATE INDEX IF NOT EXISTS ix_trade_logs_user_timestamp_desc ON trade_logs (user_id, timestamp DESC);

-- 3. QUANT_ENGINE SPECIFIC INDEXES (Applies when running on quant_engine database)
-- Add explicit single-column indexes on market_data if they don't exist
CREATE INDEX IF NOT EXISTS ix_market_data_symbol ON market_data (symbol);
CREATE INDEX IF NOT EXISTS ix_market_data_time_desc ON market_data ("time" DESC);

-- Add explicit symbol index on market_ticks
CREATE INDEX IF NOT EXISTS ix_market_ticks_symbol ON market_ticks (symbol);
CREATE INDEX IF NOT EXISTS ix_market_ticks_time_desc ON market_ticks ("time" DESC);

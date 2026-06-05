-- ====================================================================
-- STOCKAI PRO - DATABASE MIGRATION 002
-- TIMESCALEDB HYPERTABLE CONVERSION, COMPRESSION, AND RETENTION POLICIES
-- ====================================================================

DO $$
BEGIN
    -- 1. Create extension conditionally
    BEGIN
        CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
        RAISE NOTICE 'TimescaleDB extension loaded successfully.';
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'TimescaleDB extension not available. Falling back to standard PostgreSQL partitioning/indexing.';
        RETURN;
    END;

    -- 2. Convert 'candles' to hypertable if table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'candles') THEN
        -- Check if it's already a hypertable
        IF NOT EXISTS (SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'candles') THEN
            -- Drop constraints if they exist
            ALTER TABLE candles DROP CONSTRAINT IF EXISTS candles_pkey;
            ALTER TABLE candles DROP CONSTRAINT IF EXISTS uq_candle;
            
            -- Add composite primary key including timestamp
            ALTER TABLE candles ADD PRIMARY KEY (timestamp, symbol, timeframe);
            
            -- Create hypertable (7-day partitions)
            PERFORM create_hypertable('candles', 'timestamp', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
            RAISE NOTICE 'candles table converted to hypertable successfully.';
            
            -- Enable compression (segment by symbol and timeframe)
            ALTER TABLE candles SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol, timeframe');
            PERFORM add_compression_policy('candles', INTERVAL '7 days', if_not_exists => TRUE);
            RAISE NOTICE 'candles table compression policy added.';
            
            -- Add retention policy (365 days)
            PERFORM add_retention_policy('candles', INTERVAL '365 days', if_not_exists => TRUE);
            RAISE NOTICE 'candles table retention policy (365 days) added.';
        END IF;
    END IF;

    -- 3. Convert 'market_data' to hypertable if table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'market_data') THEN
        IF NOT EXISTS (SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'market_data') THEN
            -- Note: primary key on market_data is already (time, symbol, timeframe), which contains the time column.
            PERFORM create_hypertable('market_data', 'time', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
            RAISE NOTICE 'market_data table converted to hypertable successfully.';
            
            -- Enable compression
            ALTER TABLE market_data SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol, timeframe');
            PERFORM add_compression_policy('market_data', INTERVAL '7 days', if_not_exists => TRUE);
            RAISE NOTICE 'market_data table compression policy added.';
            
            -- Add retention policy (180 days)
            PERFORM add_retention_policy('market_data', INTERVAL '180 days', if_not_exists => TRUE);
            RAISE NOTICE 'market_data table retention policy (180 days) added.';
        END IF;
    END IF;

    -- 4. Convert 'market_ticks' to hypertable if table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'market_ticks') THEN
        IF NOT EXISTS (SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'market_ticks') THEN
            -- Drop constraint on standard PK id
            ALTER TABLE market_ticks DROP CONSTRAINT IF EXISTS market_ticks_pkey;
            
            -- Add composite primary key including time
            ALTER TABLE market_ticks ADD PRIMARY KEY (time, id);
            
            -- Create hypertable (7-day partitions)
            PERFORM create_hypertable('market_ticks', 'time', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
            RAISE NOTICE 'market_ticks table converted to hypertable successfully.';
            
            -- Enable compression (segment by symbol)
            ALTER TABLE market_ticks SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol');
            PERFORM add_compression_policy('market_ticks', INTERVAL '7 days', if_not_exists => TRUE);
            RAISE NOTICE 'market_ticks table compression policy added.';
            
            -- Add retention policy (30 days)
            PERFORM add_retention_policy('market_ticks', INTERVAL '30 days', if_not_exists => TRUE);
            RAISE NOTICE 'market_ticks table retention policy (30 days) added.';
        END IF;
    END IF;

END $$;

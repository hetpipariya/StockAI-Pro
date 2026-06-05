# SRE Disaster Recovery Runbook: Market Feed Recovery & Ingestor Standby Failover

## 1. Failure Symptoms
*   `market-feed` Primary container crash or Docker engine segmentation faults.
*   Candle persistent writes stop.
*   standby container logs do not display active election reports.

## 2. Detection Steps
*   **Check Active Ingestor Heartbeat lease:**
    ```bash
    redis-cli get stockai:market_feed:heartbeat
    ```
    Assert the current owner instance ID.
*   **Check logs of the Standby container:**
    ```bash
    docker logs stockai_market_feed_standby
    ```
    Verify it is reporting `Standby Mode. Primary instance is <id>`.

## 3. Recovery Steps
*   **Force Standby Ingestor Election:**
    If the Primary has locked the lease but is not streaming, manually delete the stale heartbeat key:
    ```bash
    redis-cli del stockai:market_feed:heartbeat
    ```
    This triggers immediate Standby election within 2 seconds.
*   **Restart Feed Stack:**
    If all instances are desynced:
    ```bash
    docker restart stockai_market_feed stockai_market_feed_standby
    ```

## 4. Verification Steps
*   Assert election success logs: `[FEED] ELECTION SUCCESS. This instance is now PRIMARY.`
*   Verify live WS streaming feeds.

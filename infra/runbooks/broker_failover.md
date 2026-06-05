# SRE Disaster Recovery Runbook: Broker Ingestion Failover

## 1. Failure Symptoms
*   `market-feed` logs report `[FEED-WS] Angel One stream start failed: ConnectionClosed` or similar Upstox websocket exceptions.
*   The live tick stream stops; client charts freeze; new ticks are not published to `stockai:realtime:tick`.

## 2. Detection Steps
*   **Check Active Feeds in Market Feed:**
    Check the log outputs of the market feed service:
    ```bash
    docker logs stockai_market_feed
    ```
    Assert if any broker is actively streaming: `[FEED-WS] Upstox (Secondary) standby stream started successfully.`
*   **Validate Tick Deduplication Health:**
    Assert that unique ticks are successfully persisting to Redis and database while duplicates are dropped.

## 3. Recovery Steps
*   **Manual Trigger of Standby Promotion:**
    If the Primary Broker is banned or rate-limited:
    *   Set the primary broker config key to Upstox.
    *   Restart the primary market-feed container to force active subscription re-registration.
*   **Re-login Broker Sessions:**
    If auth is blocked, trigger dynamic token refresh:
    ```bash
    curl -X POST http://localhost:8000/api/v1/auth/token/refresh -H "Authorization: Bearer <token>"
    ```

## 4. Verification Steps
*   Check the `/health/ready` endpoint of `market-feed` (Port 8002).
*   Verify tick propagation:
    ```bash
    redis-cli monitor | grep "stockai:realtime:tick"
    ```

# SRE Disaster Recovery Runbook: Redis Sentinel Failover

## 1. Failure Symptoms
*   FastAPI logs output warnings: `[REDIS] async connection failed, fallback mode: TimeoutError`.
*   System switches to in-memory `degraded fallback mode`, and metrics `stockai_redis_degraded_mode` increments to `1`.
*   Interservice tick Pub/Sub propagation halts, delaying WebSocket gateway delivery.

## 2. Detection Steps
*   **Query Sentinel Master Status:**
    ```bash
    redis-cli -p 26379 SENTINEL get-master-addr-by-name mymaster
    ```
    Verify if Sentinel correctly returned the promoted IP address of the healthy replica.
*   **Verify Replica Replication States:**
    ```bash
    redis-cli -h localhost -p 6379 INFO replication
    ```

## 3. Recovery Steps
*   **Force Manual Failover via Sentinel:**
    If Sentinel did not trigger auto-promotion due to network partition ties, manually force failover:
    ```bash
    redis-cli -p 26379 SENTINEL failover mymaster
    ```
*   **Restart Degraded Redis Containers:**
    Relaunch failed Redis nodes to join the cluster as replicas:
    ```bash
    docker restart stockai_redis_master_ha
    ```

## 4. Verification Steps
*   Check the circuit breaker metrics: `stockai_redis_degraded_mode` should reset to `0`.
*   Verify that backend logs display connection recovery: `[REDIS] async connected & circuit breaker reset`.

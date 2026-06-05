# SRE Disaster Recovery Runbook: PostgreSQL HA Failover (Patroni)

## 1. Failure Symptoms
*   FastAPI logs print `ConnectionRefusedError` or `asyncpg.exceptions.InterfaceError: cannot connect to PostgreSQL`.
*   PgBouncer pooler logs raise `server conn crashed` or `backend server is offline`.
*   HTTP endpoints returning write mutations (e.g. `/orders`, `/trading/execute`) return HTTP `500 Internal Server Error`.

## 2. Detection Steps
*   **Check Patroni Cluster Status:**
    ```bash
    docker exec -it stockai_pg_node_1 patronictl -c /etc/patroni/patroni.yml list
    ```
    Assert which node is the current leader and check its state (should be `running`).
*   **Check etcd Consensus Logs:**
    ```bash
    docker logs stockai_etcd
    ```
    Verify if there are split-brain network partition alerts.

## 3. Recovery Steps
*   **Manual Trigger of Patroni Failover:**
    If the leader is stuck in a degraded loop, trigger a manual failover:
    ```bash
    docker exec -it stockai_pg_node_1 patronictl -c /etc/patroni/patroni.yml failover
    ```
    Select the scope `stockai_postgres_cluster` and promote a healthy replica node (`pg-node-2` or `pg-node-3`).
*   **Re-initialize Broken Node:**
    Once the crashed hardware recovers, re-sync it to the new cluster leader:
    ```bash
    docker exec -it stockai_pg_node_3 patronictl -c /etc/patroni/patroni.yml reinit stockai_postgres_cluster pg-node-3
    ```

## 4. Verification Steps
*   Run the Patroni list command and verify that a healthy replica has been promoted to `Leader` state.
*   Query PgBouncer directly to ensure that queries are routed correctly to the new master:
    ```bash
    psql -h localhost -p 6432 -U postgres -d stockai -c "SELECT pg_is_in_recovery();"
    ```
    (Should return `f`, confirming it is a write-capable master).

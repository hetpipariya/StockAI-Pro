# SRE Disaster Recovery Runbook: Nginx Gateway & Keepalived VIP Failover

## 1. Failure Symptoms
*   Clients receive connection timeouts when hitting the API domain `https://api.stockai.pro`.
*   Direct curl requests to Nginx gateway port 80 fail.

## 2. Detection Steps
*   **Check VIP Binding on Ingress Interfaces:**
    ```bash
    ip addr show eth0
    ```
    Verify if the Virtual IP `192.168.1.200` is currently bound to the ingress interface of the primary (`Nginx-A`) or backup (`Nginx-B`) node.
*   **Check Keepalived Service States:**
    ```bash
    systemctl status keepalived
    ```

## 3. Recovery Steps
*   **Force VIP Promotion to Backup Node:**
    If `Nginx-A` is degraded but VRRP didn't trigger failover, stop keepalived on `Nginx-A` to force promotion:
    ```bash
    systemctl stop keepalived
    ```
    This immediately migrates the VIP to the backup node `Nginx-B` (priority 100).
*   **Validate Ingress Routes:**
    Ensure Nginx is running and able to bind properly on the VIP.

## 4. Verification Steps
*   Execute external health requests against the VIP:
    ```bash
    curl -I http://192.168.1.200/health/live
    ```
    (Should return `HTTP 200 OK`).

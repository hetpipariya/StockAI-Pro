# StockAI Pro Production Readiness Runbook

## 1. Priority Audit Findings

### P0 (must fix before scale)
- CORS defaults included wildcard origin while credentialed requests are enabled. Fixed in backend middleware.
- Production startup accepted missing `DATABASE_URL` by falling back to local DSN in some paths. Fixed to fail fast in production.
- Backend container startup previously ignored migration failures. Fixed with strict startup behavior by default.

### P1 (high impact)
- CI had no dependency review gate and no container build smoke test.
- Frontend pipeline had no test hook (now conditional test step).
- Existing CD only covered Render + Cloudflare path and lacked VPS image pipeline.

### P2 (recommended)
- Add SLO dashboards and alert routing (PagerDuty/Slack).
- Add canary release path and synthetic checks for trading-critical APIs.

## 2. Target Production Architecture

```text
Users
  |
  v
Cloudflare DNS/CDN
  |
  v
Nginx (TLS termination, rate limit, WS upgrade)
  |------------------------------|
  v                              v
Frontend container               FastAPI backend
(static SPA)                     (REST + WebSocket + inference)
                                    |
                        -------------------------
                        |                       |
                        v                       v
                    PostgreSQL                Redis
                        |
                        v
                 Prometheus + Grafana
```

## 3. CI/CD Workflows

### CI
- File: `.github/workflows/ci.yml`
- Adds:
  - PR dependency-review gate.
  - Backend dependency audit visibility (`pip-audit`, report-only).
  - Frontend dependency audit visibility (`npm audit`, report-only).
  - Docker build smoke tests for backend and frontend images.

### CD (Render + Cloudflare)
- File: `.github/workflows/cd.yml`
- Adds:
  - Manual deploy commit validation against GitHub check status.
  - Production environment tagging for deploy jobs.

### CD (VPS Docker Compose)
- File: `.github/workflows/cd-vps.yml`
- Flow:
  - Resolve deploy SHA from successful CI run or manual input.
  - Validate Docker Hub + VPS secrets.
  - Build and push immutable SHA-tagged backend/frontend images.
  - SSH deploy on VPS using `infra/docker-compose.prod.yml`.
  - Health verification for backend and frontend.

## 4. VPS Deployment Files

- `infra/docker-compose.prod.yml`
  - Internal network for backend/db/redis/frontend.
  - No public DB/Redis exposure.
  - Optional monitoring profile.
- `nginx/nginx.prod.conf`
  - Reverse proxy for SPA, API, and WebSocket.
  - Rate limiting and security headers.
- `infra/.env.prod.example`
  - Required production environment template.

## 5. Required GitHub Secrets

### Render + Cloudflare CD
- `RENDER_API_KEY`
- `RENDER_SERVICE_ID`
- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_PROJECT_NAME`

### VPS CD
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`
- `VPS_HOST`
- `VPS_SSH_USER`
- `VPS_SSH_KEY`
- `VPS_SSH_PORT` (optional)
- `VPS_APP_DIR` (example: `/opt/stockai-pro`)
- `BACKEND_HEALTH_URL` (optional)
- `FRONTEND_HEALTH_URL` (optional)

## 6. VPS First-Time Bootstrap

1. Clone repo on VPS into `VPS_APP_DIR`.
2. Copy `infra/.env.prod.example` to `infra/.env.prod` and fill all values.
3. Ensure Docker Engine + Compose plugin are installed.
4. Ensure DNS points to VPS and ports 80/443 are open.
5. Install TLS certs (for example, certbot) and mount `/etc/letsencrypt`.
6. Trigger `.github/workflows/cd-vps.yml` manually for first deploy.

## 7. Security Checklist

- Enforce branch protection on `main`.
- Require approval on `production` environment in GitHub.
- Rotate JWT secret and broker credentials on a schedule.
- Keep Docker images immutable by deploying SHA tags.
- Restrict Grafana/Prometheus to localhost or VPN only.
- Use `workflow_dispatch` for first production rollout, then keep `workflow_run` deploys after rollback drill is validated.

## 8. Rollback Procedure (VPS)

1. Identify previous known-good image SHA.
2. Update `BACKEND_IMAGE` and `FRONTEND_IMAGE` in `infra/.env.prod`.
3. Run:
   - `docker compose -f infra/docker-compose.prod.yml pull`
   - `docker compose -f infra/docker-compose.prod.yml up -d --remove-orphans`
4. Verify:
   - Backend `/api/v1/health`
   - Frontend root page and authenticated dashboard route

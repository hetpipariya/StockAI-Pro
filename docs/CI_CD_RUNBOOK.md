# StockAI Pro CI/CD Runbook

This runbook documents the production CI/CD pipeline implemented for StockAI Pro.

## Pipeline summary

### CI workflow

File:

- .github/workflows/ci.yml

Trigger:

- push to main
- pull_request

Checks:

1. Backend dependency install with pip cache
2. Env template validation using scripts/validate_env.py
3. Lint checks (black --check, flake8)
4. Backend tests (pytest) with optional coverage threshold
5. Frontend dependency install with npm cache
6. Frontend production build

### CD workflow

File:

- .github/workflows/cd.yml

Trigger:

- workflow_run on CI (only after CI success on main)
- workflow_dispatch for manual deploys

Deploy sequence:

1. Validate deployment secrets
2. Deploy backend to Render using Render API and the exact CI commit SHA
3. Poll Render deploy status until live
4. Check backend health endpoint
5. Deploy frontend preview to Cloudflare Pages
6. Verify preview URL
7. Deploy frontend production
8. Verify production URL

Rollback behavior:

- Backend: automatic Render rollback to previous live deploy on failure
- Frontend: automatic rollback by redeploying previous commit to production branch

## Workspace structure added for CI/CD

.
|- .github/
|  |- workflows/
|     |- ci.yml
|     |- cd.yml
|- backend/
|  |- .flake8
|  |- pyproject.toml
|  |- pytest.ini
|  |- requirements-dev.txt
|- scripts/
|  |- validate_env.py
|- docs/
   |- GITHUB_SECRETS_SETUP.md
   |- CI_CD_RUNBOOK.md

## Environment contract validation

Script:

- scripts/validate_env.py

What it validates:

- root .env.example exists and has required backend contract keys
- backend/.env.example has required backend keys
- frontend/.env.example has required frontend build keys
- duplicate env keys and malformed entries are rejected

## Deployment strategy recommendation

### Recommended now: Render + Cloudflare Pages

Why this fits StockAI Pro MVP:

- You are already on Render
- Native support for FastAPI web services and managed Redis/Postgres
- Cloudflare Pages provides fast global static delivery for React/Vite bundle
- Low operations overhead while keeping rollback and health checks in pipeline

### Alternative comparison

Render:

- Pros: simple ops, easy PostgreSQL/Redis integration, good MVP velocity
- Cons: can become expensive at high sustained throughput

Railway:

- Pros: fast DX, clean project environments
- Cons: less enterprise controls than larger cloud platforms

GCP Cloud Run:

- Pros: strong autoscaling, regional controls, mature observability
- Cons: higher platform complexity and setup overhead for MVP stage

## Scaling strategy for real-time trading workload

### Phase 1 (current MVP)

- 1-2 backend instances on Render
- Managed Postgres + managed Redis
- Cloudflare Pages frontend

### Phase 2 (growth)

- Split websocket worker from REST API process
- Add Redis pub/sub channel for websocket fan-out
- Enable read replicas for Postgres-heavy analytics traffic

### Phase 3 (high-throughput)

- Migrate websocket fan-out to dedicated event service
- Add queue for inference/trading decision workloads
- Move to multi-region edge + regional backend routing

## WebSocket production guidance

Use these settings for reliability and latency:

- Keep websocket endpoint fixed at /live for frontend
- Ensure VITE_WS_URL uses wss://api.stockai-pro.in/live
- Keep connection state in Redis for multi-instance broadcast support
- Add ping/pong heartbeat every 20-30 seconds
- Configure idle timeout higher than heartbeat interval at proxy/load balancer

## Redis production guidance

- Use managed Redis in same region as backend
- Enable persistence (AOF or snapshot) based on durability needs
- Reserve separate Redis logical DB or instance for:
  - cache
  - pub/sub websocket fan-out
  - rate limiting state

## Low-latency tuning checklist

- Deploy backend, Redis, and Postgres in same region
- Keep inference model loaded in memory on startup
- Cache hot market snapshots in Redis with short TTL
- Avoid synchronous network calls in websocket tick handlers
- Keep health checks lightweight (/api/health, /ping)

## Operational best practices

- Protect main with required CI status checks
- Require pull requests for all production changes
- Run database migrations during backend startup only after backup checks
- Rotate deployment API tokens on fixed schedule
- Alert on backend health check failures and websocket disconnect spikes

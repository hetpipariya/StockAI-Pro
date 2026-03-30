# GitHub Secrets Setup for StockAI Pro

This repository uses two GitHub Actions workflows:

- .github/workflows/ci.yml
- .github/workflows/cd.yml

## 1) Required GitHub Secrets

Add these in GitHub:

- Repository Settings -> Secrets and variables -> Actions -> New repository secret

### Backend deploy (Render)

- RENDER_API_KEY
  - Personal API key from Render account settings.
- RENDER_SERVICE_ID
  - Service ID of the backend web service (starts with srv-).

### Frontend deploy (Cloudflare Pages)

- CLOUDFLARE_API_TOKEN
  - Token with Cloudflare Pages edit permissions.
- CLOUDFLARE_ACCOUNT_ID
  - Cloudflare account identifier.
- CLOUDFLARE_PROJECT_NAME
  - Pages project name for frontend deployment.

## 2) Recommended GitHub Variables (non-secret)

Add these in GitHub:

- Repository Settings -> Secrets and variables -> Actions -> Variables tab

- BACKEND_HEALTH_URL
  - Example: https://api.stockai-pro.in/api/health
- FRONTEND_PROD_URL
  - Example: https://stockai-pro.in
- VITE_API_BASE_URL
  - Example: https://api.stockai-pro.in
- VITE_WS_URL
  - Example: wss://api.stockai-pro.in/live
- MIN_BACKEND_COVERAGE
  - Example: 65
  - If omitted, coverage still runs but does not fail the build by threshold.

## 3) Runtime Secrets stay in Render, not in GitHub

These belong in Render service environment variables, not in GitHub workflow secrets:

- JWT_SECRET
- DATABASE_URL
- REDIS_URL
- SMARTAPI_API_KEY
- SMARTAPI_CLIENT_ID
- SMARTAPI_CLIENT_PWD
- SMARTAPI_TOTP_SECRET
- NEWS_API_KEY

Reason:

- GitHub secrets are for deployment automation credentials.
- Runtime app secrets should be injected by the runtime platform (Render), never baked into build logs or committed files.

## 4) Render configuration checks

For zero-downtime behavior and stable health-based traffic switching:

- Set Render health check path to /api/health
- Keep at least 1 always-on instance
- Enable auto deploy from GitHub branch main only

## 5) Rotation policy

- Rotate RENDER_API_KEY and CLOUDFLARE_API_TOKEN every 60-90 days.
- Rotate JWT_SECRET only through planned maintenance windows (token invalidation impact).
- Revoke any token immediately if exposed.

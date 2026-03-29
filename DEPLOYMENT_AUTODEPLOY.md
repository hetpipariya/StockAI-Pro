# Auto-Deploy Setup (GitHub -> Cloudflare Pages + Render)

This repository includes three GitHub Actions workflows:

- .github/workflows/ci.yml
- .github/workflows/deploy-frontend-cloudflare.yml
- .github/workflows/deploy-backend-render.yml

## 1) Required GitHub Secrets

Configure these in repository settings -> Secrets and variables -> Actions.

### Frontend (Cloudflare Pages)

- CLOUDFLARE_API_TOKEN
- CLOUDFLARE_ACCOUNT_ID
- CLOUDFLARE_PROJECT_NAME
- VITE_API_URL
- REACT_APP_API_URL
- VITE_WS_URL

Recommended values:

- VITE_API_URL = https://api.stockai-pro.in
- REACT_APP_API_URL = https://api.stockai-pro.in
- VITE_WS_URL = wss://api.stockai-pro.in/ws

### Backend (Render)

- RENDER_DEPLOY_HOOK_URL
- BACKEND_HEALTH_URL (optional)

Recommended value:

- BACKEND_HEALTH_URL = https://api.stockai-pro.in/health

## 2) Render Environment Variables

Set these in Render dashboard for backend service.

- APP_ENV=production
- ENV=production
- DATABASE_URL=<Render PostgreSQL URL>
- JWT_SECRET=<strong random secret>
- REDIS_URL=<redis url or fallback>
- CORS_ORIGINS=https://stockai-pro.in,https://www.stockai-pro.in,https://stockai-pro.pages.dev
- FRONTEND_URL=https://stockai-pro.in

## 3) Cloudflare Pages Environment Variables

Set these in Cloudflare Pages project environment.

- VITE_API_URL=https://api.stockai-pro.in
- REACT_APP_API_URL=https://api.stockai-pro.in
- VITE_WS_URL=wss://api.stockai-pro.in/ws

## 4) Trigger behavior

- CI runs on pull requests and pushes to main.
- Frontend deploy runs on changes under frontend/ on main.
- Backend deploy runs on changes under backend/ on main.

## 5) Verification checklist after deploy

- Frontend URL loads: https://stockai-pro.pages.dev
- Backend health returns 200: https://api.stockai-pro.in/health
- CORS preflight includes https://stockai-pro.in
- Auth login works and returns access token
- WebSocket connection with token works on /ws
- WebSocket without token is rejected

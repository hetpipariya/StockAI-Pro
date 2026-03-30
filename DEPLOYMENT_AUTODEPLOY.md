# Auto Deploy Setup (GitHub -> Render + Cloudflare Pages)

This repository now uses two GitHub Actions workflows:

- .github/workflows/ci.yml
- .github/workflows/cd.yml

## Source of truth docs

- docs/GITHUB_SECRETS_SETUP.md
- docs/CI_CD_RUNBOOK.md

## Quick summary

1. CI runs on pull requests and pushes to main.
2. CD triggers only after CI succeeds on main.
3. Backend deploys to Render via API using the exact CI commit SHA.
4. Frontend deploys to Cloudflare Pages with preview health verification before production deployment.
5. Rollback is automatic:
	- Render rollback to previous live deploy if backend deployment fails.
	- Frontend rollback by redeploying previous commit if production health check fails.

## Runtime environment reminder

Keep runtime secrets in Render environment variables:

- JWT_SECRET
- DATABASE_URL
- REDIS_URL
- SMARTAPI_API_KEY
- SMARTAPI_CLIENT_ID
- SMARTAPI_CLIENT_PWD
- SMARTAPI_TOTP_SECRET

Do not store runtime application secrets in GitHub workflow files.


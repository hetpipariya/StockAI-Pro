<#
PowerShell helper to remove `.env` from git index and give guidance for history purge.
Run from repository root in a PowerShell terminal.

This script does NOT rewrite history automatically. It will:
- remove tracked `.env` from the index and commit
- remind you about history purge tools and rotation

#>

param()

Write-Host "Removing .env from git index (staged only)..." -ForegroundColor Yellow
git rm --cached .env
if ($LASTEXITCODE -ne 0) {
    Write-Host "git rm failed or .env not tracked. Check git status." -ForegroundColor Red
    exit 1
}

git commit -m "chore: remove .env from repository"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Commit failed. Inspect the repository state." -ForegroundColor Red
    exit 1
}

Write-Host "Pushed local removal. Note: this does not remove .env from git history." -ForegroundColor Yellow
Write-Host "Use git-filter-repo or BFG to purge history (instructions in ../secrets_rotation.md)." -ForegroundColor Cyan
Write-Host "After history purge, rotate all secrets immediately and verify no secret values remain in the repo." -ForegroundColor Red

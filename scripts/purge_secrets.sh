#!/usr/bin/env bash
set -euo pipefail

echo "This helper shows recommended commands to purge .env from history using git-filter-repo or BFG."

echo "1) Using git-filter-repo (recommended):"
cat <<'CMD'
# Install: pip install git-filter-repo
git clone --mirror <repo_url> repo-mirror.git
cd repo-mirror.git
git filter-repo --invert-paths --path .env
git push --force
CMD

echo "2) Using BFG (alternate):"
cat <<'CMD'
# Download bfg.jar
java -jar bfg.jar --delete-files .env
git reflog expire --expire=now --all && git gc --prune=now --aggressive
git push --force
CMD

echo "After history purge: rotate secrets and verify with a fresh clone. See ../secrets_rotation.md for full guidance."

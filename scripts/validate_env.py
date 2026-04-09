#!/usr/bin/env python3
"""Validate .env example files used by CI/CD and runtime onboarding."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


REQUIRED_KEYS = {
    "root": {
        "APP_ENV",
        "ENV",
        "DATABASE_URL",
        "REDIS_URL",
        "JWT_SECRET",
        "CORS_ORIGINS",
    },
    "backend": {
        "APP_ENV",
        "ENV",
        "DATABASE_URL",
        "REDIS_URL",
        "JWT_SECRET",
        "SMARTAPI_API_KEY",
        "SMARTAPI_CLIENT_ID",
        "SMARTAPI_CLIENT_PWD",
        "SMARTAPI_TOTP_SECRET",
        "CORS_ORIGINS",
        "BACKEND_HOST",
        "BACKEND_PORT",
    },
    "frontend": {
        "VITE_API_BASE_URL",
        "VITE_WS_URL",
    },
}


FILE_MAP = {
    "root": Path(".env.example"),
    "backend": Path("backend/.env.example"),
    "frontend": Path("frontend/.env.example"),
}


def parse_env_file(file_path: Path) -> tuple[set[str], list[str]]:
    keys: set[str] = set()
    issues: list[str] = []

    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return set(), [f"{file_path}: could not read file ({exc})"]

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            issues.append(f"{file_path}:{line_no}: expected KEY=VALUE format")
            continue

        key, _ = line.split("=", 1)
        key = key.strip()
        if not KEY_PATTERN.match(key):
            issues.append(f"{file_path}:{line_no}: invalid env var name '{key}'")
            continue

        if key in keys:
            issues.append(f"{file_path}:{line_no}: duplicate env var '{key}'")
            continue

        keys.add(key)

    return keys, issues


def validate_profile(project_root: Path, profile: str) -> list[str]:
    relative_path = FILE_MAP[profile]
    full_path = project_root / relative_path
    issues: list[str] = []

    if not full_path.is_file():
        return [f"Missing expected env example file: {relative_path}"]

    keys, parse_issues = parse_env_file(full_path)
    issues.extend(parse_issues)

    missing = sorted(REQUIRED_KEYS[profile] - keys)
    if missing:
        issues.append(f"{relative_path}: missing required keys -> {', '.join(missing)}")

    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate environment template files for CI/CD readiness."
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Repository root path (defaults to current directory).",
    )
    parser.add_argument(
        "--profiles",
        nargs="+",
        choices=sorted(REQUIRED_KEYS.keys()),
        default=sorted(REQUIRED_KEYS.keys()),
        help="Subset of env profiles to validate.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_root = Path(args.project_root).resolve()

    all_issues: list[str] = []
    for profile in args.profiles:
        all_issues.extend(validate_profile(project_root, profile))

    if all_issues:
        print("Environment template validation failed:\n")
        for issue in all_issues:
            print(f"- {issue}")
        return 1

    print(
        "Environment template validation passed for profiles:", ", ".join(args.profiles)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

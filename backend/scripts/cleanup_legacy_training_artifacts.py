from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

LEGACY_PATTERNS = [
    "**/feature_cols.json",
    "**/feature_schema.pkl",
    "**/features.pkl",
    "**/*legacy*model*.pkl",
    "**/*deprecated*scaler*.pkl",
    "**/*old*mapping*.json",
    "**/*abandoned*experiment*",
]

SAFE_SCOPE = [
    ROOT / "backend" / "models",
    ROOT / "experiments_v2" / "outputs",
]


def iter_legacy_files() -> list[Path]:
    found: list[Path] = []
    for base in SAFE_SCOPE:
        if not base.exists():
            continue
        for pattern in LEGACY_PATTERNS:
            found.extend(path for path in base.glob(pattern) if path.is_file())
    # Preserve stable order and uniqueness
    uniq: dict[str, Path] = {}
    for p in found:
        uniq[str(p.resolve())] = p
    return sorted(uniq.values(), key=lambda p: str(p))


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup deprecated training artifacts")
    parser.add_argument("--apply", action="store_true", help="Delete files. Default is dry-run")
    args = parser.parse_args()

    files = iter_legacy_files()
    if not files:
        print("No legacy artifacts found.")
        return

    print(f"Found {len(files)} legacy artifacts")
    for f in files:
        print(f" - {f}")

    if not args.apply:
        print("Dry run complete. Re-run with --apply to delete.")
        return

    deleted = 0
    for f in files:
        try:
            f.unlink(missing_ok=True)
            deleted += 1
        except Exception as exc:
            print(f"Failed to delete {f}: {exc}")

    print(f"Deleted {deleted}/{len(files)} artifacts")


if __name__ == "__main__":
    main()

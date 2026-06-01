import sys
from pathlib import Path

shared = Path(__file__).resolve().parent / "shared"

sys.path.insert(0, str(shared))

print("Running Import Verification...")

try:
    from stockai_shared.config.config import *
    print("[OK] Config imports")
except Exception as e:
    print("[FAIL] Config:", e)

try:
    from stockai_shared.db.db import *
    print("[OK] DB imports")
except Exception as e:
    print("[FAIL] DB:", e)

try:
    from stockai_shared.cache.redis_client import *
    print("[OK] Redis imports")
except Exception as e:
    print("[FAIL] Redis:", e)

print("Verification Complete.")
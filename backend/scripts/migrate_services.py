
#!/usr/bin/env python3
"""
StockAI Pro — Enterprise Service Separation & Refactor Engine

SAFE VERSION
-------------
This version is redesigned for:
- safer migration
- rollback-friendly execution
- proper service bootstrapping
- cleaner shared package generation
- better import handling
- Docker compatibility
- production-grade structure

IMPORTANT:
- This script COPIES files (never deletes originals)
- Existing monolith remains untouched
- Safe for iterative migration

Author:
Enterprise Backend Refactor Assistant
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path
from typing import Dict, List

# ============================================================
# PATHS
# ============================================================

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
APP_ROOT = BACKEND_ROOT / "app"
SERVICES_ROOT = REPO_ROOT / "services"

print(f"\n[INFO] Repository Root: {REPO_ROOT}")
print(f"[INFO] Backend Root:    {BACKEND_ROOT}")
print(f"[INFO] Services Root:   {SERVICES_ROOT}")

# ============================================================
# SERVICE STRUCTURE
# ============================================================

SERVICE_STRUCTURE = {
    "shared": [
        "stockai_shared",
        "stockai_shared/config",
        "stockai_shared/db",
        "stockai_shared/cache",
        "stockai_shared/logging",
        "stockai_shared/metrics",
        "stockai_shared/schemas",
        "stockai_shared/utils",
    ],
    "api-backend": [
        "app",
        "app/routes",
        "app/services",
        "app/middleware",
    ],
    "websocket-gateway": [
        "app",
        "app/ws",
    ],
    "market-feed": [
        "app",
        "app/feed",
    ],
    "ai-engine": [
        "app",
        "app/inference",
    ],
    "trading-engine": [
        "app",
        "app/trading",
    ],
}

# ============================================================
# FILE MIGRATION MAP
# ============================================================

MIGRATION_MAP: Dict[Path, Path] = {

    # ========================================================
    # SHARED
    # ========================================================

    APP_ROOT / "config.py":
        SERVICES_ROOT / "shared/stockai_shared/config/config.py",

    APP_ROOT / "logging_setup.py":
        SERVICES_ROOT / "shared/stockai_shared/logging/logging.py",

    APP_ROOT / "services/db.py":
        SERVICES_ROOT / "shared/stockai_shared/db/db.py",

    APP_ROOT / "services/redis_client.py":
        SERVICES_ROOT / "shared/stockai_shared/cache/redis_client.py",

    APP_ROOT / "services/metrics.py":
        SERVICES_ROOT / "shared/stockai_shared/metrics/metrics.py",

    # ========================================================
    # API BACKEND
    # ========================================================

    APP_ROOT / "main.py":
        SERVICES_ROOT / "api-backend/app/main.py",

    APP_ROOT / "middleware.py":
        SERVICES_ROOT / "api-backend/app/middleware.py",

    APP_ROOT / "lifespan.py":
        SERVICES_ROOT / "api-backend/app/lifespan.py",

    # ========================================================
    # WEBSOCKET GATEWAY
    # ========================================================

    APP_ROOT / "websocket/handler.py":
        SERVICES_ROOT / "websocket-gateway/app/ws/handler.py",

    APP_ROOT / "websocket/relay.py":
        SERVICES_ROOT / "websocket-gateway/app/ws/relay.py",

    # ========================================================
    # MARKET FEED
    # ========================================================

    APP_ROOT / "services/realtime_data_service.py":
        SERVICES_ROOT / "market-feed/app/feed/realtime_data_service.py",

    APP_ROOT / "services/tick_aggregator.py":
        SERVICES_ROOT / "market-feed/app/feed/tick_aggregator.py",

    # ========================================================
    # AI ENGINE
    # ========================================================

    APP_ROOT / "inference/runner.py":
        SERVICES_ROOT / "ai-engine/app/inference/runner.py",

    APP_ROOT / "inference/feature_engineering.py":
        SERVICES_ROOT / "ai-engine/app/inference/feature_engineering.py",

    APP_ROOT / "inference/models.py":
        SERVICES_ROOT / "ai-engine/app/inference/models.py",

    APP_ROOT / "services/native_accelerators.py":
        SERVICES_ROOT / "ai-engine/app/inference/native_accelerators.py",

    # ========================================================
    # TRADING ENGINE
    # ========================================================

    APP_ROOT / "services/trade_decision_engine.py":
        SERVICES_ROOT / "trading-engine/app/trading/trade_decision_engine.py",
}

# ============================================================
# SAFE IMPORT REPLACEMENTS
# ============================================================

IMPORT_REPLACEMENTS = {
    "from app.services.db import":
        "from stockai_shared.db.db import",

    "from app.services.redis_client import":
        "from stockai_shared.cache.redis_client import",

    "from app.logging_setup import":
        "from stockai_shared.logging.logging import",

    "from app.services.metrics import":
        "from stockai_shared.metrics.metrics import",

    "from app.config import":
        "from stockai_shared.config.config import",

    "from app.schemas":
        "from stockai_shared.schemas",
}

# ============================================================
# HELPERS
# ============================================================

def ensure_init(directory: Path):
    init_file = directory / "__init__.py"

    if not init_file.exists():
        init_file.write_text(
            '"""StockAI Pro Package"""\n',
            encoding="utf-8"
        )

def safe_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(src, dst)

    print(f"[COPY] {src.relative_to(REPO_ROOT)}")
    print(f"       -> {dst.relative_to(REPO_ROOT)}")

def rewrite_imports(file_path: Path):

    if file_path.suffix != ".py":
        return

    content = file_path.read_text(
        encoding="utf-8",
        errors="ignore"
    )

    original = content

    for old, new in IMPORT_REPLACEMENTS.items():
        content = content.replace(old, new)

    if content != original:
        file_path.write_text(content, encoding="utf-8")
        print(f"[IMPORTS UPDATED] {file_path.relative_to(REPO_ROOT)}")

# ============================================================
# CREATE STRUCTURE
# ============================================================

def create_structure():

    print("\n[PHASE 1] Creating Service Structure...\n")

    for service, paths in SERVICE_STRUCTURE.items():

        for relative in paths:

            full_path = SERVICES_ROOT / service / relative

            full_path.mkdir(
                parents=True,
                exist_ok=True
            )

            ensure_init(full_path)

            print(f"[DIR] {full_path.relative_to(REPO_ROOT)}")

# ============================================================
# CREATE SHARED PACKAGE
# ============================================================

def create_shared_setup():

    print("\n[PHASE 2] Creating Shared Package...\n")

    setup_py = SERVICES_ROOT / "shared/setup.py"

    setup_py.write_text(
        """
from setuptools import setup, find_packages

setup(
    name="stockai_shared",
    version="0.1.0",
    packages=find_packages(),
)
""".strip(),
        encoding="utf-8"
    )

    print("[OK] setup.py created")

# ============================================================
# MIGRATE FILES
# ============================================================

def migrate_files():

    print("\n[PHASE 3] Migrating Files...\n")

    total = 0

    for src, dst in MIGRATION_MAP.items():

        if not src.exists():

            print(f"[SKIP] Missing: {src.relative_to(REPO_ROOT)}")
            continue

        safe_copy(src, dst)

        rewrite_imports(dst)

        total += 1

    print(f"\n[OK] Total migrated files: {total}")

# ============================================================
# COPY ROUTES
# ============================================================

def copy_routes():

    print("\n[PHASE 4] Copying Routes...\n")

    routes_src = APP_ROOT / "routes"
    routes_dst = SERVICES_ROOT / "api-backend/app/routes"

    if not routes_src.exists():
        return

    for route in routes_src.glob("*.py"):

        safe_copy(route, routes_dst / route.name)

        rewrite_imports(routes_dst / route.name)

# ============================================================
# COPY SCHEMAS
# ============================================================

def copy_schemas():

    print("\n[PHASE 5] Copying Schemas...\n")

    schemas_src = APP_ROOT / "schemas"
    schemas_dst = SERVICES_ROOT / "shared/stockai_shared/schemas"

    if not schemas_src.exists():
        return

    for schema in schemas_src.glob("*.py"):

        safe_copy(schema, schemas_dst / schema.name)

# ============================================================
# CREATE MAIN FILES
# ============================================================

API_MAIN = """
from fastapi import FastAPI

app = FastAPI(title="StockAI API Backend")

@app.get("/")
async def health():
    return {"status": "ok"}
"""

WS_MAIN = """
from fastapi import FastAPI

app = FastAPI(title="StockAI WebSocket Gateway")

@app.get("/")
async def health():
    return {"status": "ok"}
"""

def create_main_files():

    print("\n[PHASE 6] Creating Bootstrap Files...\n")

    api_main = SERVICES_ROOT / "api-backend/app/main.py"

    if not api_main.exists():
        api_main.write_text(API_MAIN)

    ws_main = SERVICES_ROOT / "websocket-gateway/app/main.py"

    if not ws_main.exists():
        ws_main.write_text(WS_MAIN)

# ============================================================
# REQUIREMENTS
# ============================================================

REQUIREMENTS = {
    "api-backend": """
fastapi
uvicorn
sqlalchemy
redis
pydantic
python-jose
passlib
bcrypt
orjson
""",

    "websocket-gateway": """
fastapi
uvicorn
redis
orjson
""",

    "market-feed": """
redis
httpx
websocket-client
orjson
""",

    "ai-engine": """
numpy
pandas
xgboost
scikit-learn
redis
""",

    "trading-engine": """
sqlalchemy
redis
httpx
orjson
"""
}

def create_requirements():

    print("\n[PHASE 7] Creating Requirements...\n")

    for service, content in REQUIREMENTS.items():

        req = SERVICES_ROOT / service / "requirements.txt"

        req.write_text(
            content.strip(),
            encoding="utf-8"
        )

        print(f"[REQ] {service}")

# ============================================================
# DOCKERFILES
# ============================================================

DOCKER_TEMPLATE = """
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE {port}

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "{port}"]
"""

def create_dockerfiles():

    print("\n[PHASE 8] Creating Dockerfiles...\n")

    ports = {
        "api-backend": 8000,
        "websocket-gateway": 8001,
    }

    for service, port in ports.items():

        dockerfile = SERVICES_ROOT / service / "Dockerfile"

        dockerfile.write_text(
            DOCKER_TEMPLATE.format(port=port),
            encoding="utf-8"
        )

        print(f"[DOCKER] {service}")

# ============================================================
# VERIFY IMPORTS
# ============================================================

VERIFY_SCRIPT = """
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
"""

def create_verify_script():

    verify = SERVICES_ROOT / "verify_imports.py"

    verify.write_text(
        VERIFY_SCRIPT.strip(),
        encoding="utf-8"
    )

    print("[OK] verify_imports.py created")

# ============================================================
# AST VALIDATION
# ============================================================

def validate_python_syntax():

    print("\n[PHASE 9] Validating Python Syntax...\n")

    for py_file in SERVICES_ROOT.rglob("*.py"):

        try:

            ast.parse(
                py_file.read_text(
                    encoding="utf-8",
                    errors="ignore"
                )
            )

            print(f"[OK] {py_file.relative_to(REPO_ROOT)}")

        except Exception as exc:

            print(f"[SYNTAX ERROR] {py_file}")
            print(exc)

# ============================================================
# MAIN
# ============================================================

def run():

    print("\n" + "=" * 70)
    print(" STOCKAI PRO — ENTERPRISE SERVICE REFACTOR ENGINE ")
    print("=" * 70)

    create_structure()

    create_shared_setup()

    migrate_files()

    copy_routes()

    copy_schemas()

    create_main_files()

    create_requirements()

    create_dockerfiles()

    create_verify_script()

    validate_python_syntax()

    print("\n" + "=" * 70)
    print(" SERVICE SEPARATION COMPLETED ")
    print("=" * 70)

    print("\nNEXT STEPS:\n")

    print("1. Install shared package:")
    print("   pip install -e services/shared\n")

    print("2. Verify imports:")
    print("   python services/verify_imports.py\n")

    print("3. Start API backend:")
    print("   cd services/api-backend")
    print("   uvicorn app.main:app --reload\n")

if __name__ == "__main__":
    run()

#!/usr/bin/env python
"""
StockAI Pro — Automated Service Separation & Refactoring Script

This script programmatically refactors the monolithic StockAI Pro backend
into a separated, service-oriented architecture:
  1. Creates service directories: api-backend, websocket-gateway, market-feed, ai-engine, trading-engine, shared.
  2. Sets up `stockai_shared` as an installable local Python package.
  3. Moves database, caching, logging, metrics, config, and schemas to `stockai_shared`.
  4. Migrates specialized service files into their respective service directories.
  5. Automatically parses and updates import paths to point to the new shared package structure.
  6. Generates setup.py, requirements.txt, and Dockerfile layers for each service.
"""

import os
import shutil
import re
from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
APP_ROOT = BACKEND_ROOT / "app"
SERVICES_ROOT = REPO_ROOT / "services"

print(f"[*] Repository root resolved to: {REPO_ROOT}")
print(f"[*] Monolithic backend resolved to: {BACKEND_ROOT}")

# 1. Directory Structure Definition
STRUCTURE = [
    SERVICES_ROOT / "shared" / "stockai_shared" / "db",
    SERVICES_ROOT / "shared" / "stockai_shared" / "cache",
    SERVICES_ROOT / "shared" / "stockai_shared" / "logging",
    SERVICES_ROOT / "shared" / "stockai_shared" / "metrics",
    SERVICES_ROOT / "shared" / "stockai_shared" / "schemas",
    SERVICES_ROOT / "shared" / "stockai_shared" / "config",
    
    SERVICES_ROOT / "api-backend" / "app" / "routes",
    SERVICES_ROOT / "api-backend" / "app" / "services",
    
    SERVICES_ROOT / "websocket-gateway" / "app",
    
    SERVICES_ROOT / "market-feed" / "app",
    
    SERVICES_ROOT / "ai-engine" / "app" / "inference",
    
    SERVICES_ROOT / "trading-engine" / "app" / "trading",
]

def initialize_structure():
    print("[*] Phase 1: Initializing New Service Directories...")
    for path in STRUCTURE:
        path.mkdir(parents=True, exist_ok=True)
        # Create __init__.py for standard package imports
        init_file = path / "__init__.py"
        if not init_file.exists():
            init_file.write_text('"""StockAI Pro Service Segment"""\n')
    print("[+] Services directory structure initialized.")

# 2. Local Shared Package setup.py
SHARED_SETUP = """from setuptools import setup, find_packages

setup(
    name="stockai_shared",
    version="0.1.0",
    description="StockAI Pro centralized core and shared utilities library",
    packages=find_packages(),
    install_requires=[
        "sqlalchemy",
        "redis",
        "pydantic",
        "passlib",
        "orjson",
        "httpx",
    ],
)
"""

def create_shared_package_files():
    print("[*] Phase 2: Creating setup.py and base requirements for the shared package...")
    setup_file = SERVICES_ROOT / "shared" / "setup.py"
    setup_file.write_text(SHARED_SETUP)
    
    init_shared = SERVICES_ROOT / "shared" / "stockai_shared" / "__init__.py"
    init_shared.write_text('"""StockAI Pro Centralized shared Package"""\n')
    print("[+] Shared package setup file successfully written.")

# 3. File Migration Mapping
MIGRATION_MAP = {
    # ── Shared Package Files ──
    APP_ROOT / "config.py": SERVICES_ROOT / "shared" / "stockai_shared" / "config" / "config.py",
    APP_ROOT / "logging_setup.py": SERVICES_ROOT / "shared" / "stockai_shared" / "logging" / "logging.py",
    APP_ROOT / "services" / "db.py": SERVICES_ROOT / "shared" / "stockai_shared" / "db" / "db.py",
    APP_ROOT / "services" / "redis_client.py": SERVICES_ROOT / "shared" / "stockai_shared" / "cache" / "redis_client.py",
    APP_ROOT / "services" / "metrics.py": SERVICES_ROOT / "shared" / "stockai_shared" / "metrics" / "metrics.py",
    
    # ── API Backend Service ──
    APP_ROOT / "main.py": SERVICES_ROOT / "api-backend" / "app" / "main.py",
    APP_ROOT / "server.py": SERVICES_ROOT / "api-backend" / "app" / "server.py",
    APP_ROOT / "middleware.py": SERVICES_ROOT / "api-backend" / "app" / "middleware.py",
    APP_ROOT / "lifespan.py": SERVICES_ROOT / "api-backend" / "app" / "lifespan.py",
    
    # ── WebSocket Gateway ──
    APP_ROOT / "websocket" / "handler.py": SERVICES_ROOT / "websocket-gateway" / "app" / "handler.py",
    APP_ROOT / "websocket" / "relay.py": SERVICES_ROOT / "websocket-gateway" / "app" / "relay.py",
    
    # ── Market Feed Ingestion ──
    APP_ROOT / "services" / "realtime_data_service.py": SERVICES_ROOT / "market-feed" / "app" / "realtime_data_service.py",
    APP_ROOT / "services" / "tick_aggregator.py": SERVICES_ROOT / "market-feed" / "app" / "tick_aggregator.py",
    
    # ── AI Inference Engine ──
    APP_ROOT / "inference" / "runner.py": SERVICES_ROOT / "ai-engine" / "app" / "runner.py",
    APP_ROOT / "inference" / "feature_engineering.py": SERVICES_ROOT / "ai-engine" / "app" / "feature_engineering.py",
    APP_ROOT / "inference" / "models.py": SERVICES_ROOT / "ai-engine" / "app" / "models.py",
    APP_ROOT / "services" / "native_accelerators.py": SERVICES_ROOT / "ai-engine" / "app" / "native_accelerators.py",
    
    # ── Trading & Execution Engine ──
    APP_ROOT / "services" / "trade_decision_engine.py": SERVICES_ROOT / "trading-engine" / "app" / "trade_decision_engine.py",
}

def migrate_files():
    print("[*] Phase 3: Copying files to target service locations...")
    migrated_count = 0
    for src, dst in MIGRATION_MAP.items():
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  [Copy] {src.relative_to(REPO_ROOT)} -> {dst.relative_to(REPO_ROOT)}")
            migrated_count += 1
        else:
            print(f"  [Skip] (Missing Monolith File): {src.relative_to(REPO_ROOT)}")
            
    # Copy all routes to api-backend routes
    routes_src = APP_ROOT / "routes"
    routes_dst = SERVICES_ROOT / "api-backend" / "app" / "routes"
    if routes_src.exists():
        for item in routes_src.iterdir():
            if item.is_file():
                shutil.copy2(item, routes_dst / item.name)
                print(f"  [Copy Route] {item.relative_to(REPO_ROOT)} -> {(routes_dst / item.name).relative_to(REPO_ROOT)}")
                migrated_count += 1
                
    # Copy Pydantic schemas to shared package
    schemas_src = APP_ROOT / "schemas"
    schemas_dst = SERVICES_ROOT / "shared" / "stockai_shared" / "schemas"
    if schemas_src.exists():
        for item in schemas_src.iterdir():
            if item.is_file():
                shutil.copy2(item, schemas_dst / item.name)
                print(f"  [Copy Schema] {item.relative_to(REPO_ROOT)} -> {(schemas_dst / item.name).relative_to(REPO_ROOT)}")
                migrated_count += 1
                
    print(f"[+] Total files copied: {migrated_count}")

# 4. Import Path Replacement Logic
IMPORT_REPLACEMENTS = [
    (re.compile(r"from\s+app\.services\.db\s+import"), "from stockai_shared.db.db import"),
    (re.compile(r"import\s+app\.services\.db"), "import stockai_shared.db.db as db"),
    
    (re.compile(r"from\s+app\.services\.redis_client\s+import"), "from stockai_shared.cache.redis_client import"),
    (re.compile(r"import\s+app\.services\.redis_client"), "import stockai_shared.cache.redis_client as redis_client"),
    
    (re.compile(r"from\s+app\.logging_setup\s+import"), "from stockai_shared.logging.logging import"),
    
    (re.compile(r"from\s+app\.services\.metrics\s+import"), "from stockai_shared.metrics.metrics import"),
    
    (re.compile(r"from\s+app\.config\s+import"), "from stockai_shared.config.config import"),
    (re.compile(r"import\s+app\.config"), "import stockai_shared.config.config as config"),
    
    (re.compile(r"from\s+app\.schemas\b"), "from stockai_shared.schemas"),
]

def refactor_file_imports(file_path: Path):
    if not file_path.exists() or file_path.suffix != ".py":
        return
    
    content = file_path.read_text(encoding="utf-8")
    original = content
    
    for pattern, replacement in IMPORT_REPLACEMENTS:
        content = pattern.sub(replacement, content)
        
    if content != original:
        file_path.write_text(content, encoding="utf-8")
        print(f"  [Refactored Imports] {file_path.relative_to(REPO_ROOT)}")

def refactor_all_service_imports():
    print("[*] Phase 4: Parsing and updating import paths to reference stockai_shared...")
    for root, _, files in os.walk(str(SERVICES_ROOT)):
        for file in files:
            path = Path(root) / file
            refactor_file_imports(path)
    print("[+] Import paths updated across all service packages.")

# 5. Service Configurations & Requirements Setup
REQUIREMENTS_API = """fastapi
uvicorn
gunicorn
pydantic
sqlalchemy
redis
orjson
python-jose
passlib
bcrypt
prometheus-fastapi-instrumentator
"""

REQUIREMENTS_WS = """fastapi
uvicorn
redis
orjson
python-jose
"""

REQUIREMENTS_FEED = """redis
orjson
websocket-client
httpx
"""

REQUIREMENTS_AI = """redis
numpy
pandas
xgboost
scikit-learn
pybind11
"""

REQUIREMENTS_TRADE = """redis
orjson
sqlalchemy
httpx
"""

def create_requirements_files():
    print("[*] Phase 5: Generating service-specific requirements.txt files...")
    (SERVICES_ROOT / "api-backend" / "requirements.txt").write_text(REQUIREMENTS_API)
    (SERVICES_ROOT / "websocket-gateway" / "requirements.txt").write_text(REQUIREMENTS_WS)
    (SERVICES_ROOT / "market-feed" / "requirements.txt").write_text(REQUIREMENTS_FEED)
    (SERVICES_ROOT / "ai-engine" / "requirements.txt").write_text(REQUIREMENTS_AI)
    (SERVICES_ROOT / "trading-engine" / "requirements.txt").write_text(REQUIREMENTS_TRADE)
    print("[+] Service requirements.txt files successfully generated.")

# 6. Service Dockerfile Configurations
DOCKER_API = """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=shared-builder /shared /shared
RUN pip install -e /shared
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

DOCKER_WS = """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=shared-builder /shared /shared
RUN pip install -e /shared
COPY . .
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
"""

DOCKER_FEED = """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=shared-builder /shared /shared
RUN pip install -e /shared
COPY . .
CMD ["python", "app/realtime_data_service.py"]
"""

DOCKER_AI = """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=shared-builder /shared /shared
RUN pip install -e /shared
COPY . .
CMD ["python", "app/runner.py"]
"""

DOCKER_TRADE = """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=shared-builder /shared /shared
RUN pip install -e /shared
COPY . .
CMD ["python", "app/trade_decision_engine.py"]
"""

def create_dockerfiles():
    print("[*] Phase 6: Generating service-specific Dockerfile configurations...")
    (SERVICES_ROOT / "api-backend" / "Dockerfile").write_text(DOCKER_API)
    (SERVICES_ROOT / "websocket-gateway" / "Dockerfile").write_text(DOCKER_WS)
    (SERVICES_ROOT / "market-feed" / "Dockerfile").write_text(DOCKER_FEED)
    (SERVICES_ROOT / "ai-engine" / "Dockerfile").write_text(DOCKER_AI)
    (SERVICES_ROOT / "trading-engine" / "Dockerfile").write_text(DOCKER_TRADE)
    print("[+] Service Dockerfile layers successfully generated.")

# 7. Verification Smoke Tests
TEST_IMPORTS = """import sys
from pathlib import Path

# Insert services shared path to verify resolution
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))

print("[*] Smoke Test: Verifying stockai_shared import channels...")

try:
    from stockai_shared.config.config import DATABASE_URL, REDIS_URL
    print("  [OK] Centralized configurations successfully resolved.")
except Exception as exc:
    print("  [FAIL] Config resolution failed:", exc)

try:
    from stockai_shared.db.db import check_db_connection
    print("  [OK] Database ORM models successfully resolved.")
except Exception as exc:
    print("  [FAIL] Database ORM resolution failed:", exc)

try:
    from stockai_shared.cache.redis_client import init_redis
    print("  [OK] High-speed cache connectors successfully resolved.")
except Exception as exc:
    print("  [FAIL] Cache connector resolution failed:", exc)

try:
    from stockai_shared.logging.logging import StructuredJsonLogFormatter
    print("  [OK] JSON logger modules successfully resolved.")
except Exception as exc:
    print("  [FAIL] JSON logger resolution failed:", exc)

print("[+] Import verification suite complete.")
"""

def create_test_runner():
    print("[*] Phase 7: Generating validation test suite for import resolution verification...")
    (SERVICES_ROOT / "verify_imports.py").write_text(TEST_IMPORTS)
    print("[+] verify_imports.py validation suite generated.")

def run_migration():
    print("\n" + "="*60)
    print("   STOCKAI PRO — SERVICE SEPARATION MASTER REFACTOR")
    print("="*60 + "\n")
    
    initialize_structure()
    create_shared_package_files()
    migrate_files()
    refactor_all_service_imports()
    create_requirements_files()
    create_dockerfiles()
    create_test_runner()
    
    print("\n" + "="*60)
    print("   REFACTOR AND SEPARATION COMPLETED SUCCESSFULLY")
    print("="*60 + "\n")
    print("[*] Follow these steps to verify and run the refactored backend:")
    print("  1. Install the local shared package in editable development mode:")
    print("     pip install -e services/shared")
    print("  2. Verify that imports resolve without any error across services:")
    print("     python services/verify_imports.py")
    print("  3. Run the new API backend using Uvicorn:")
    print("     cd services/api-backend")
    print("     uvicorn app.main:app --port 8000 --reload")
    print("\n[+] Service migration complete. Ready for enterprise launch!")

if __name__ == "__main__":
    run_migration()

#!/usr/bin/env python
"""Startup script to run the backend API server."""

import sys
import os

# Add backend directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import uvicorn
    from app.config import (BACKEND_HOST, BACKEND_PORT, LOG_LEVEL,
                            UVICORN_ACCESS_LOG, UVICORN_LOOP,
                            UVICORN_TIMEOUT_KEEP_ALIVE, UVICORN_WORKERS)

    uvicorn.run(
        "app.main:app",
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        log_level=str(LOG_LEVEL).lower(),
        reload=False,
        workers=UVICORN_WORKERS,
        timeout_keep_alive=UVICORN_TIMEOUT_KEEP_ALIVE,
        loop=UVICORN_LOOP,
        access_log=UVICORN_ACCESS_LOG,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )

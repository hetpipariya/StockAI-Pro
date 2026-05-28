#!/usr/bin/env python
"""
StockAI Pro — Startup script.

Execution order:
  1. Compile C++ engine  (app/cpp_engine via CMake)
  2. Launch FastAPI / Uvicorn backend
"""

import os
import sys
import subprocess
import shutil
import time
from pathlib import Path

# ── Colour helpers (work on Windows 10+ with ANSI support) ─────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"


def _enable_ansi():
    """Enable ANSI escape codes on Windows."""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32          # type: ignore[attr-defined]
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


def banner(text: str) -> None:
    width = 64
    print(f"\n{BOLD}{CYAN}{'─' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}\n")


def info(msg: str) -> None:
    print(f"{CYAN}[INFO]{RESET}  {msg}")


def ok(msg: str) -> None:
    print(f"{GREEN}[ OK ]{RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET}  {msg}")


def error(msg: str) -> None:
    print(f"{RED}[ERR ]{RESET}  {msg}", file=sys.stderr)


def step(n: int, total: int, msg: str) -> None:
    print(f"{BOLD}[{n}/{total}]{RESET} {msg}")


# ── CMake helpers ───────────────────────────────────────────────────────────

def _cmake_cmd() -> list[str]:
    """Return cmake executable (system or via python -m cmake)."""
    if shutil.which("cmake"):
        return ["cmake"]
    return [sys.executable, "-m", "cmake"]


def _stream(proc: subprocess.Popen) -> int:
    """Stream stdout+stderr of *proc* line-by-line; return exit code."""
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        # Colour-code cmake output slightly
        if any(kw in line for kw in ("error", "Error", "ERROR", "fatal")):
            print(f"  {RED}{line}{RESET}")
        elif any(kw in line for kw in ("warning", "Warning", "WARN")):
            print(f"  {YELLOW}{line}{RESET}")
        elif any(kw in line for kw in ("--", "Building", "Linking", "Compiling", "Copying")):
            print(f"  {CYAN}{line}{RESET}")
        else:
            print(f"  {DIM}{line}{RESET}")
    proc.wait()
    return proc.returncode


def compile_cpp_engine() -> bool:
    """
    Compile the C++ engine using CMake.

    Returns True on success, False on failure.
    """
    cpp_engine_dir = Path(__file__).resolve().parent / "app" / "cpp_engine"
    build_dir      = cpp_engine_dir / "build"

    if not cpp_engine_dir.exists():
        warn(f"cpp_engine directory not found at {cpp_engine_dir} — skipping C++ build.")
        return True   # non-fatal; engine might already be compiled

    build_dir.mkdir(parents=True, exist_ok=True)

    # ── Detect pybind11 cmake dir ───────────────────────────────────────────
    try:
        pybind11_cmake_dir = subprocess.check_output(
            [sys.executable, "-m", "pybind11", "--cmakedir"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        warn("pybind11 cmake dir not found; CMake will try to locate it automatically.")
        pybind11_cmake_dir = ""

    cmake = _cmake_cmd()

    # ── Step A: cmake configure ─────────────────────────────────────────────
    step(1, 2, "CMake configure …")
    configure_cmd = cmake + [
        str(cpp_engine_dir),
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DPYTHON_EXECUTABLE={sys.executable}",
    ]
    if pybind11_cmake_dir:
        configure_cmd.append(f"-Dpybind11_DIR={pybind11_cmake_dir}")

    # Prefer Ninja on Windows when available
    if sys.platform == "win32" and shutil.which("ninja"):
        configure_cmd += ["-G", "Ninja"]

    info(f"Configure command: {' '.join(configure_cmd)}")

    t0 = time.perf_counter()
    proc = subprocess.Popen(
        configure_cmd,
        cwd=str(build_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    rc = _stream(proc)
    elapsed = time.perf_counter() - t0

    if rc != 0:
        error(f"CMake configure FAILED (exit {rc})  [{elapsed:.1f}s]")
        return False
    ok(f"CMake configure succeeded  [{elapsed:.1f}s]")

    # ── Step B: cmake build ─────────────────────────────────────────────────
    step(2, 2, "CMake build (Release) …")
    build_cmd = cmake + ["--build", ".", "--config", "Release", "--parallel"]
    info(f"Build command: {' '.join(build_cmd)}")

    t0 = time.perf_counter()
    proc = subprocess.Popen(
        build_cmd,
        cwd=str(build_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    rc = _stream(proc)
    elapsed = time.perf_counter() - t0

    if rc != 0:
        error(f"CMake build FAILED (exit {rc})  [{elapsed:.1f}s]")
        return False
    ok(f"C++ engine compiled successfully  [{elapsed:.1f}s]")

    # Confirm .pyd / .so exists
    pyd_candidates = list(cpp_engine_dir.glob("stockai_cpp_engine*.pyd")) + \
                     list(cpp_engine_dir.glob("stockai_cpp_engine*.so"))
    if pyd_candidates:
        ok(f"Binary artifact: {pyd_candidates[0].name}")
    else:
        warn("Expected .pyd/.so not found in cpp_engine dir after build.")

    return True


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    _enable_ansi()

    banner("StockAI Pro — Backend Startup")

    # ── 1. C++ Engine ───────────────────────────────────────────────────────
    banner("Phase 1 of 2 · Compiling C++ Engine")
    info("Starting C++ engine compilation …")

    success = compile_cpp_engine()

    if not success:
        error("C++ engine compilation failed. Backend will start but may run in pure-Python fallback mode.")
        warn("Check errors above. Continuing in 3 s …")
        time.sleep(3)
    else:
        ok("C++ engine is ready.")

    # ── 2. Backend server ───────────────────────────────────────────────────
    banner("Phase 2 of 2 · Starting FastAPI Backend")

    # Add backend directory to Python path so `app.*` imports work
    backend_dir = str(Path(__file__).resolve().parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    import uvicorn
    from app.config import (
        BACKEND_HOST,
        BACKEND_PORT,
        LOG_LEVEL,
        UVICORN_ACCESS_LOG,
        UVICORN_LOOP,
        UVICORN_TIMEOUT_KEEP_ALIVE,
        UVICORN_WORKERS,
    )

    info(f"Host    : {BACKEND_HOST}")
    info(f"Port    : {BACKEND_PORT}")
    info(f"Workers : {UVICORN_WORKERS}")
    info(f"Loop    : {UVICORN_LOOP}")
    info(f"LogLevel: {LOG_LEVEL}")
    print()

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


if __name__ == "__main__":
    main()

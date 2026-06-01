import logging
import os
import secrets
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv

# Traverse up the tree to find and load the nearest .env file
for parent in Path(__file__).resolve().parents:
    env_file = parent / ".env"
    if env_file.is_file():
        load_dotenv(dotenv_path=env_file, override=False)
        break

_BACKEND_DIR = Path(".").resolve()
_cfg_logger = logging.getLogger(__name__)


def _as_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


SMARTAPI_API_KEY = os.getenv("SMARTAPI_API_KEY", "")
SMARTAPI_CLIENT_ID = os.getenv("SMARTAPI_CLIENT_ID", "")
SMARTAPI_PASSWORD = os.getenv("SMARTAPI_PASSWORD", os.getenv("SMARTAPI_CLIENT_PWD", ""))
SMARTAPI_CLIENT_PWD = SMARTAPI_PASSWORD
SMARTAPI_TOTP_SECRET = os.getenv("SMARTAPI_TOTP_SECRET", "")
SMARTAPI_EXCHANGE = os.getenv("SMARTAPI_EXCHANGE", "NSE")

UPSTOX_API_KEY = os.getenv("UPSTOX_API_KEY", "")
UPSTOX_API_SECRET = os.getenv("UPSTOX_API_SECRET", "")
UPSTOX_REDIRECT_URI = os.getenv("UPSTOX_REDIRECT_URI", "")
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")
UPSTOX_REFRESH_TOKEN = os.getenv("UPSTOX_REFRESH_TOKEN", "")
UPSTOX_AUTH_CODE = os.getenv("UPSTOX_AUTH_CODE", "")
UPSTOX_WS_URL = os.getenv("UPSTOX_WS_URL", "wss://api.upstox.com/v2/feed/market-data-feed")

BROKER_PRIMARY = os.getenv("BROKER_PRIMARY", "smartapi").strip().lower() or "smartapi"
BROKER_FALLBACK = os.getenv("BROKER_FALLBACK", "upstox").strip().lower() or "upstox"
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("PORT", os.getenv("BACKEND_PORT", "8000")))
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://stockai-pro.pages.dev")

# ─── Auth & APIs ───
# ── JWT Secret Validation (Zero-Tolerance for Weak Secrets) ──
_env = os.getenv("APP_ENV", os.getenv("ENV", "development")).lower()
_jwt = os.getenv("JWT_SECRET", "").strip()
APP_ENV = _env

_KNOWN_INSECURE_KEYS = {
    "super-secret-jwt-key-for-stockai-pro",
    "dev-only-insecure-key-CHANGE-ME",
    "dev-only-insecure-fallback-key-CHANGE-FOR-PROD-32!!",
    "secret",
    "changeme",
    "stockai",
    "",
}

if _env == "production":
    if not _jwt or _jwt in _KNOWN_INSECURE_KEYS or len(_jwt) < 32:
        raise RuntimeError(
            "\n" + "=" * 60 + "\n"
            "FATAL: JWT_SECRET is missing or insecure.\n"
            "Production requires a strong secret (≥32 chars).\n"
            "Generate one now:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(64))"\n'
            "Then set it in your .env file as JWT_SECRET=<generated_value>\n" + "=" * 60
        )
else:
    # Development: warn but allow weak key
    if not _jwt or _jwt in _KNOWN_INSECURE_KEYS or len(_jwt) < 32:
        _jwt = secrets.token_urlsafe(48)
        _cfg_logger.warning(
            "[DEV ONLY] JWT_SECRET missing/insecure. Generated ephemeral secret "
            "for this process; set JWT_SECRET in .env for stable sessions."
        )

JWT_SECRET: str = _jwt
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "1"))
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
MAX_BETA_USERS: int = int(os.getenv("MAX_BETA_USERS", "5"))
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_MASTER_NAME = os.getenv("REDIS_MASTER_NAME", "mymaster")
REDIS_SENTINELS = os.getenv("REDIS_SENTINELS", "")
REDIS_REPLICA_URL = os.getenv("REDIS_REPLICA_URL", "")
REDIS_TLS_SKIP_VERIFY = os.getenv("REDIS_TLS_SKIP_VERIFY", "false").lower() == "true"
REQUIRE_POSTGRES = os.getenv("REQUIRE_POSTGRES", "true").lower() == "true"
DB_SLOW_QUERY_MS = int(os.getenv("DB_SLOW_QUERY_MS", "100"))
API_RATE_LIMIT = int(os.getenv("API_RATE_LIMIT", "200"))
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "40"))
DB_POOL_TIMEOUT_SECONDS = float(os.getenv("DB_POOL_TIMEOUT_SECONDS", "30"))
DB_POOL_RECYCLE_SECONDS = int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800"))
DB_COMMAND_TIMEOUT_SECONDS = float(os.getenv("DB_COMMAND_TIMEOUT_SECONDS", "30"))
DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "5000"))
DB_LOCK_TIMEOUT_MS = int(os.getenv("DB_LOCK_TIMEOUT_MS", "3000"))
DB_MAX_RETRIES = int(os.getenv("DB_MAX_RETRIES", "3"))
DB_RETRY_BASE_DELAY_SECONDS = float(os.getenv("DB_RETRY_BASE_DELAY_SECONDS", "0.2"))
_DEFAULT_LOG_LEVEL = "INFO"
LOG_LEVEL = os.getenv("LOG_LEVEL", _DEFAULT_LOG_LEVEL).upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()
LOG_QUEUE_MAXSIZE = max(0, int(os.getenv("LOG_QUEUE_MAXSIZE", "10000")))
SLOW_REQUEST_LOG_MS = max(50, int(os.getenv("SLOW_REQUEST_LOG_MS", "300")))
UVICORN_ACCESS_LOG = _as_bool(
    os.getenv("UVICORN_ACCESS_LOG"),
    default=APP_ENV != "production",
)
UVICORN_WORKERS = max(1, int(os.getenv("UVICORN_WORKERS", "1" if APP_ENV != "production" else "2")))
UVICORN_TIMEOUT_KEEP_ALIVE = max(
    5, int(os.getenv("UVICORN_TIMEOUT_KEEP_ALIVE", "20"))
)
UVICORN_LOOP = os.getenv(
    "UVICORN_LOOP",
    "asyncio" if os.name == "nt" else ("uvloop" if APP_ENV == "production" else "asyncio"),
).strip() or "asyncio"
SQLALCHEMY_ECHO = _as_bool(os.getenv("SQLALCHEMY_ECHO"), default=False)
DB_LOG_SLOW_QUERIES = _as_bool(os.getenv("DB_LOG_SLOW_QUERIES"), default=True)

CACHE_TTL_SNAPSHOT_SECONDS = int(os.getenv("CACHE_TTL_SNAPSHOT_SECONDS", "3"))
CACHE_TTL_CANDLES_SECONDS = int(os.getenv("CACHE_TTL_CANDLES_SECONDS", "10"))
CACHE_TTL_PREDICTION_SECONDS = int(os.getenv("CACHE_TTL_PREDICTION_SECONDS", "5"))
CACHE_TTL_BUNDLE_SECONDS = int(os.getenv("CACHE_TTL_BUNDLE_SECONDS", "30"))

# WebSocket is enabled by default for real-time data
# Set ENABLE_WS=false only if you want to disable real-time streaming
ENABLE_WS = os.getenv("ENABLE_WS", "true").lower() == "true"
WS_AUTH_DB_TIMEOUT_SECONDS = float(os.getenv("WS_AUTH_DB_TIMEOUT_SECONDS", "2.0"))
SCHEDULER_JOB_TIMEOUT_SECONDS = float(os.getenv("SCHEDULER_JOB_TIMEOUT_SECONDS", "120"))
SCHEDULER_JOB_MAX_INSTANCES = int(os.getenv("SCHEDULER_JOB_MAX_INSTANCES", "1"))
BUNDLE_PREWARM_CONCURRENCY = int(os.getenv("BUNDLE_PREWARM_CONCURRENCY", "3"))
FAST_STARTUP_MODE = os.getenv("FAST_STARTUP_MODE", "true").lower() == "true"
FAST_STARTUP_DB_INIT_TIMEOUT_SECONDS = float(
    os.getenv("FAST_STARTUP_DB_INIT_TIMEOUT_SECONDS", "6.0")
)
RESET_SQLITE_ON_START = os.getenv("RESET_SQLITE_ON_START", "true").lower() == "true"
INSTRUMENT_MASTER_URL = os.getenv(
    "INSTRUMENT_MASTER_URL",
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
)
INSTRUMENT_FETCH_TIMEOUT_SECONDS = float(
    os.getenv("INSTRUMENT_FETCH_TIMEOUT_SECONDS", "30")
)
INSTRUMENT_FETCH_RETRIES = int(os.getenv("INSTRUMENT_FETCH_RETRIES", "3"))
INSTRUMENT_REDIS_TTL_SECONDS = int(
    os.getenv("INSTRUMENT_REDIS_TTL_SECONDS", str(24 * 60 * 60))
)
INSTRUMENT_REFRESH_HOUR = int(os.getenv("INSTRUMENT_REFRESH_HOUR", "8"))
INSTRUMENT_REFRESH_MINUTE = int(os.getenv("INSTRUMENT_REFRESH_MINUTE", "0"))

_SQLITE_FALLBACK = "sqlite+aiosqlite:///./stockai.db"
_POSTGRES_FALLBACK = os.getenv(
    "POSTGRES_FALLBACK_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/stockai",
)


def _sanitize_database_url(raw: str) -> str:
    cleaned = str(raw or "").strip()

    # Common multiline separators and accidental PowerShell escaped markers.
    for sep in ("\n", "\r", "`n", "`r"):
        cleaned = cleaned.split(sep)[0]

    # Guard against concatenated env fragments from malformed .env lines.
    for marker in ("JWT_SECRET=", "APP_ENV=", "ENV=", "REDIS_URL="):
        idx = cleaned.find(marker)
        if idx != -1:
            cleaned = cleaned[:idx]

    return cleaned.strip()


def _resolve_database_url() -> str:
    """Resolve a valid async DATABASE_URL for the running environment.

    Resolution order:
    1. Read DATABASE_URL from the environment.
     2. If empty and REQUIRE_POSTGRES=true → fall back to local PostgreSQL DSN.
     3. If empty and REQUIRE_POSTGRES=false → fall back to SQLite.
    3. Railway provides ``postgres://`` scheme → rewrite to
       ``postgresql+asyncpg://``.
    4. If the hostname is the docker-compose service name ``postgres``
         (not resolvable outside Docker) and REQUIRE_POSTGRES=false → fall back to SQLite.
    5. Ensure ``postgresql://`` URLs get the ``+asyncpg`` driver prefix.
    """
    raw = _sanitize_database_url(os.getenv("DATABASE_URL", ""))

    # Guard against malformed multiline env values to avoid parsing surprises.
    if any(
        marker in os.getenv("DATABASE_URL", "")
        for marker in ("\n", "\r", "`n", "`r", "JWT_SECRET=")
    ):
        _cfg_logger.warning(
            "[DB] DATABASE_URL contained malformed content; sanitized before use"
        )

    if not raw:
        if _env == "production":
            raise RuntimeError(
                "FATAL: DATABASE_URL is required in production and must point to PostgreSQL."
            )

        if REQUIRE_POSTGRES:
            _cfg_logger.info(
                "[DB] DATABASE_URL not set — using PostgreSQL fallback (%s)",
                _POSTGRES_FALLBACK,
            )
            raw = _POSTGRES_FALLBACK
        else:
            _cfg_logger.info(
                "[DB] DATABASE_URL not set — using SQLite fallback (%s)", _SQLITE_FALLBACK
            )
            return _SQLITE_FALLBACK

    # Railway uses the legacy 'postgres://' scheme; SQLAlchemy needs 'postgresql://'
    if raw.startswith("postgres://"):
        raw = "postgresql+asyncpg://" + raw[len("postgres://"):]
        _cfg_logger.info("[DB] Rewrote 'postgres://' → 'postgresql+asyncpg://'")

    # SQLite URLs — ensure the aiosqlite driver is present
    if raw.startswith("sqlite"):
        if _env == "production" or REQUIRE_POSTGRES:
            raise RuntimeError(
                "FATAL: SQLite is not allowed when REQUIRE_POSTGRES=true. Use PostgreSQL."
            )
        if "+aiosqlite" not in raw:
            raw = raw.replace("sqlite://", "sqlite+aiosqlite://", 1)
        _cfg_logger.info("[DB] Using SQLite: %s", raw)
        return raw

    # For PostgreSQL URLs, inspect the hostname
    try:
        parsed = urlparse(raw)
        hostname = (parsed.hostname or "").lower()
        if hostname == "postgres":
            if _env == "production":
                raise RuntimeError(
                    "FATAL: DATABASE_URL points to docker hostname 'postgres' in production. "
                    "Set a resolvable PostgreSQL host."
                )
            if not REQUIRE_POSTGRES:
                _cfg_logger.warning(
                    "[DB] DATABASE_URL hostname is 'postgres' (docker-compose local name) "
                    "which is not reachable in this environment — falling back to SQLite (%s)",
                    _SQLITE_FALLBACK,
                )
                return _SQLITE_FALLBACK
    except Exception as exc:
        if _env == "production":
            raise RuntimeError(
                f"FATAL: Could not parse DATABASE_URL in production: {exc}"
            ) from exc
        if REQUIRE_POSTGRES:
            raise RuntimeError(f"FATAL: Could not parse PostgreSQL DATABASE_URL: {exc}") from exc
        _cfg_logger.warning("[DB] Could not parse DATABASE_URL (%s) — falling back to SQLite", exc)
        return _SQLITE_FALLBACK

    # Ensure the asyncpg driver is specified for plain postgresql:// URLs
    if raw.startswith("postgresql://") and "+asyncpg" not in raw:
        raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)

    _cfg_logger.info("[DB] Using PostgreSQL (asyncpg)")
    return raw


DATABASE_URL: str = _resolve_database_url()

MARKET_OPEN = os.getenv("MARKET_OPEN", "09:15")
MARKET_CLOSE = os.getenv("MARKET_CLOSE", "15:30")

# ─── Trading Safety ───
TRADING_MODE = os.getenv("TRADING_MODE", "PAPER").upper()
TRADING_ENABLED = os.getenv("TRADING_ENABLED", "true").lower() == "true"
LIVE_CONFIRMED = os.getenv("LIVE_CONFIRMED", "false").lower() == "true"
ENABLE_MOCK_DATA = os.getenv("ENABLE_MOCK_DATA", "false").lower() == "true"
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "https://stockai-pro.in,https://www.stockai-pro.in,http://localhost:5173,http://127.0.0.1:5173",
)

# ─── Capital & Risk ───
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", "100000"))
MIN_ACCOUNT_BALANCE = float(os.getenv("MIN_ACCOUNT_BALANCE", "10000"))
MAX_RISK_PER_TRADE_PCT = float(os.getenv("MAX_RISK_PER_TRADE_PCT", "0.02"))
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "10"))
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_CONCURRENT_POSITIONS", "3"))
DAILY_LOSS_LIMIT_PCT = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.035"))

# ─── 5m Live Engine ───
_default_live_5m_model = _BACKEND_DIR / "models" / "entry_5m" / "model.pkl"
_fallback_live_5m_model = (
    _BACKEND_DIR / "models" / "model.pkl"
)

if _default_live_5m_model.exists():
    _resolved_live_5m_model = _default_live_5m_model
elif _fallback_live_5m_model.exists():
    _resolved_live_5m_model = _fallback_live_5m_model
else:
    _resolved_live_5m_model = _default_live_5m_model

LIVE_5M_MODEL_PATH = os.getenv("LIVE_5M_MODEL_PATH", str(_resolved_live_5m_model))
LIVE_5M_AUTO_EXECUTION_ENABLED = (
    os.getenv("LIVE_5M_AUTO_EXECUTION_ENABLED", "false").lower() == "true"
)
LIVE_5M_EXECUTE_ALL_ACTIVE_USERS = (
    os.getenv("LIVE_5M_EXECUTE_ALL_ACTIVE_USERS", "false").lower() == "true"
)
LIVE_5M_CONFIDENCE_THRESHOLD = float(
    os.getenv("LIVE_5M_CONFIDENCE_THRESHOLD", "0.70")
)
LIVE_5M_TREND_THRESHOLD = float(
    os.getenv("LIVE_5M_TREND_THRESHOLD", "0.003991270018741487")
)
LIVE_5M_VOLATILITY_THRESHOLD = float(
    os.getenv("LIVE_5M_VOLATILITY_THRESHOLD", "0.001896510226652026")
)
LIVE_5M_ADX_THRESHOLD = float(os.getenv("LIVE_5M_ADX_THRESHOLD", "20"))
LIVE_5M_BBWIDTH_THRESHOLD = float(os.getenv("LIVE_5M_BBWIDTH_THRESHOLD", "0.0005"))
LIVE_5M_STOP_LOSS_PCT = float(os.getenv("LIVE_5M_STOP_LOSS_PCT", "0.005"))
LIVE_5M_TAKE_PROFIT_PCT = float(os.getenv("LIVE_5M_TAKE_PROFIT_PCT", "0.015"))
LIVE_5M_MAX_HOLDING_BARS = int(os.getenv("LIVE_5M_MAX_HOLDING_BARS", "6"))
LIVE_5M_HISTORY_LIMIT = int(os.getenv("LIVE_5M_HISTORY_LIMIT", "240"))

import os
import secrets
import logging
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent

# Prefer explicit .env file paths because backend/.env may be a directory in this repo.
for _env_path in (_BACKEND_DIR / ".env", _REPO_ROOT / ".env"):
    if _env_path.is_file():
        load_dotenv(dotenv_path=_env_path, override=False)

_cfg_logger = logging.getLogger(__name__)

SMARTAPI_API_KEY = os.getenv("SMARTAPI_API_KEY", "")
SMARTAPI_CLIENT_ID = os.getenv("SMARTAPI_CLIENT_ID", "")
SMARTAPI_CLIENT_PWD = os.getenv("SMARTAPI_CLIENT_PWD", "")
SMARTAPI_TOTP_SECRET = os.getenv("SMARTAPI_TOTP_SECRET", "")
SMARTAPI_EXCHANGE = os.getenv("SMARTAPI_EXCHANGE", "NSE")
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
            "Then set it in your .env file as JWT_SECRET=<generated_value>\n"
            + "=" * 60
        )
else:
    # Development: warn but allow weak key
    if not _jwt or _jwt in _KNOWN_INSECURE_KEYS or len(_jwt) < 32:
        _jwt = secrets.token_urlsafe(48)
        _cfg_logger.warning(
            "[DEV ONLY] JWT_SECRET missing/insecure. Generated ephemeral secret for this process; set JWT_SECRET in .env for stable sessions."
        )

JWT_SECRET: str = _jwt
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REQUIRE_POSTGRES = os.getenv("REQUIRE_POSTGRES", "true").lower() == "true"
DB_SLOW_QUERY_MS = int(os.getenv("DB_SLOW_QUERY_MS", "100"))
API_RATE_LIMIT = int(os.getenv("API_RATE_LIMIT", "200"))

CACHE_TTL_SNAPSHOT_SECONDS = int(os.getenv("CACHE_TTL_SNAPSHOT_SECONDS", "5"))
CACHE_TTL_CANDLES_SECONDS = int(os.getenv("CACHE_TTL_CANDLES_SECONDS", "10"))
CACHE_TTL_PREDICTION_SECONDS = int(os.getenv("CACHE_TTL_PREDICTION_SECONDS", "5"))
CACHE_TTL_BUNDLE_SECONDS = int(os.getenv("CACHE_TTL_BUNDLE_SECONDS", "5"))

_SQLITE_FALLBACK = "sqlite+aiosqlite:///./stockai.db"


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
    2. If empty → fall back to SQLite.
    3. Railway provides ``postgres://`` scheme → rewrite to
       ``postgresql+asyncpg://``.
    4. If the hostname is the docker-compose service name ``postgres``
       (not resolvable outside Docker) → fall back to SQLite.
    5. Ensure ``postgresql://`` URLs get the ``+asyncpg`` driver prefix.
    """
    raw = _sanitize_database_url(os.getenv("DATABASE_URL", ""))

    # Guard against malformed multiline env values to avoid parsing surprises.
    if any(marker in os.getenv("DATABASE_URL", "") for marker in ("\n", "\r", "`n", "`r", "JWT_SECRET=")):
        _cfg_logger.warning("[DB] DATABASE_URL contained malformed content; sanitized before use")

    if not raw:
        if _env == "production":
            raise RuntimeError(
                "FATAL: DATABASE_URL is required in production and must point to PostgreSQL."
            )
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
        if _env == "production":
            raise RuntimeError("FATAL: SQLite is not allowed in production. Use PostgreSQL.")
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
            _cfg_logger.warning(
                "[DB] DATABASE_URL hostname is 'postgres' (docker-compose local name) "
                "which is not reachable in this environment — falling back to SQLite (%s)",
                _SQLITE_FALLBACK,
            )
            return _SQLITE_FALLBACK
    except Exception as exc:
        if _env == "production":
            raise RuntimeError(f"FATAL: Could not parse DATABASE_URL in production: {exc}") from exc
        _cfg_logger.warning(
            "[DB] Could not parse DATABASE_URL (%s) — falling back to SQLite", exc
        )
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
ENABLE_MOCK_DATA = os.getenv("ENABLE_MOCK_DATA", "true").lower() == "true"
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "https://stockai-pro.in,https://www.stockai-pro.in,http://localhost:5173,http://127.0.0.1:5173",
)

# ─── Capital & Risk ───
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", "100000"))
MIN_ACCOUNT_BALANCE = float(os.getenv("MIN_ACCOUNT_BALANCE", "10000"))
MAX_RISK_PER_TRADE_PCT = float(os.getenv("MAX_RISK_PER_TRADE_PCT", "0.01"))
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "10"))
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_CONCURRENT_POSITIONS", "3"))
DAILY_LOSS_LIMIT_PCT = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.03"))

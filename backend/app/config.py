import os
import logging
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

_cfg_logger = logging.getLogger(__name__)

SMARTAPI_API_KEY = os.getenv("SMARTAPI_API_KEY", "")
SMARTAPI_CLIENT_ID = os.getenv("SMARTAPI_CLIENT_ID", "")
SMARTAPI_CLIENT_PWD = os.getenv("SMARTAPI_CLIENT_PWD", "")
SMARTAPI_TOTP_SECRET = os.getenv("SMARTAPI_TOTP_SECRET", "")
SMARTAPI_EXCHANGE = os.getenv("SMARTAPI_EXCHANGE", "NSE")
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

# ─── Auth & APIs ───
_jwt = os.getenv("JWT_SECRET", "")
if not _jwt or _jwt == "super-secret-jwt-key-for-stockai-pro":
    import warnings
    warnings.warn(
        "JWT_SECRET is missing or using the insecure default. "
        "Set a strong random secret in .env for production!",
        RuntimeWarning,
        stacklevel=2,
    )
    _jwt = _jwt or "dev-only-insecure-key-CHANGE-ME"
JWT_SECRET: str = _jwt
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_SQLITE_FALLBACK = "sqlite+aiosqlite:///./stockai.db"


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
    raw = os.getenv("DATABASE_URL", "").strip()

    if not raw:
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
        if "+aiosqlite" not in raw:
            raw = raw.replace("sqlite://", "sqlite+aiosqlite://", 1)
        _cfg_logger.info("[DB] Using SQLite: %s", raw)
        return raw

    # For PostgreSQL URLs, inspect the hostname
    try:
        parsed = urlparse(raw)
        hostname = (parsed.hostname or "").lower()
        if hostname == "postgres":
            _cfg_logger.warning(
                "[DB] DATABASE_URL hostname is 'postgres' (docker-compose local name) "
                "which is not reachable in this environment — falling back to SQLite (%s)",
                _SQLITE_FALLBACK,
            )
            return _SQLITE_FALLBACK
    except Exception as exc:
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
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

# ─── Capital & Risk ───
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", "100000"))
MIN_ACCOUNT_BALANCE = float(os.getenv("MIN_ACCOUNT_BALANCE", "10000"))
MAX_RISK_PER_TRADE_PCT = float(os.getenv("MAX_RISK_PER_TRADE_PCT", "0.01"))
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "10"))
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_CONCURRENT_POSITIONS", "3"))
DAILY_LOSS_LIMIT_PCT = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.03"))

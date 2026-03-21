import os
import logging
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
    1. Read DATABASE_URL from environment (Railway auto-injects this)
    2. If empty → use SQLite fallback (development only)
    3. Convert postgres:// → postgresql+asyncpg:// (Railway legacy format)
    4. Ensure postgresql:// URLs have +asyncpg driver
    5. Return the URL as-is if already valid
    """
    raw = os.getenv("DATABASE_URL", "").strip()

    # No DATABASE_URL set → use SQLite (development/fallback only)
    if not raw:
        _cfg_logger.warning(
            "[DB] DATABASE_URL not set — using SQLite fallback (%s). "
            "For production, ensure DATABASE_URL is set via Railway environment.",
            _SQLITE_FALLBACK
        )
        return _SQLITE_FALLBACK

    # Convert Railway's legacy postgres:// scheme to postgresql+asyncpg://
    if raw.startswith("postgres://"):
        raw = "postgresql+asyncpg://" + raw[len("postgres://"):]
        _cfg_logger.info("[DB] Converted postgres:// → postgresql+asyncpg://")
        return raw

    # Handle SQLite URLs
    if raw.startswith("sqlite"):
        if "+aiosqlite" not in raw:
            raw = raw.replace("sqlite://", "sqlite+aiosqlite://", 1)
        _cfg_logger.info("[DB] Using SQLite: %s", raw)
        return raw

    # Ensure PostgreSQL URLs have asyncpg driver
    if raw.startswith("postgresql://") and "+asyncpg" not in raw:
        raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
        _cfg_logger.info("[DB] Added asyncpg driver to postgresql:// URL")
        return raw

    # URL is already valid (postgresql+asyncpg://, etc.)
    if raw.startswith("postgresql+asyncpg://"):
        _cfg_logger.info("[DB] Using PostgreSQL with asyncpg driver")
        return raw

    # Fallback for any other URL format
    _cfg_logger.warning("[DB] Using DATABASE_URL as-is: %s", raw[:50])
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

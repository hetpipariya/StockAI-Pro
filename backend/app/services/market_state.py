from datetime import datetime, date
import pytz
import logging
from app.config import MARKET_OPEN, MARKET_CLOSE

logger = logging.getLogger(__name__)

# Indian Standard Time
IST = pytz.timezone("Asia/Kolkata")

def _parse_time(time_str: str) -> dict:
    parts = time_str.split(":")
    return {"hour": int(parts[0]), "minute": int(parts[1])}

def is_market_open() -> bool:
    """
    Check if the Indian stock market is currently open.
    Mon-Fri, between MARKET_OPEN and MARKET_CLOSE IST.
    """
    now_ist = datetime.now(IST)
    
    # Weekend check (0 = Mon, 6 = Sun)
    if now_ist.weekday() > 4:
        return False
        
    open_time = _parse_time(MARKET_OPEN)
    close_time = _parse_time(MARKET_CLOSE)
    
    open_dt = now_ist.replace(hour=open_time["hour"], minute=open_time["minute"], second=0, microsecond=0)
    close_dt = now_ist.replace(hour=close_time["hour"], minute=close_time["minute"], second=0, microsecond=0)
    
    return open_dt <= now_ist <= close_dt

def get_market_status() -> dict:
    """Return comprehensive market status."""
    now_ist = datetime.now(IST)
    is_open = is_market_open()
    
    open_time = _parse_time(MARKET_OPEN)
    close_time = _parse_time(MARKET_CLOSE)
    
    today_open = now_ist.replace(hour=open_time["hour"], minute=open_time["minute"], second=0, microsecond=0)
    today_close = now_ist.replace(hour=close_time["hour"], minute=close_time["minute"], second=0, microsecond=0)
    
    status = {
        "is_open": is_open,
        "current_time": now_ist.isoformat(),
        "market_open_time": today_open.isoformat(),
        "market_close_time": today_close.isoformat(),
    }
    
    if is_open:
        status["message"] = "Market is open"
        status["next_event"] = "close"
        status["next_event_time"] = today_close.isoformat()
    else:
        status["message"] = "Market is closed"
        status["next_event"] = "open"
        
        # Calculate next open time
        next_open = today_open
        if now_ist > today_close:
            # End of day, next open is tomorrow
            from datetime import timedelta
            next_open = next_open + timedelta(days=1)
            
        # Skip weekends
        while next_open.weekday() > 4:
            from datetime import timedelta
            next_open = next_open + timedelta(days=1)
            
        status["next_event_time"] = next_open.isoformat()
        
    return status

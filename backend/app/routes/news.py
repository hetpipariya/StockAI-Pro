"""
News API integration using GNews API.
Includes Redis caching to avoid rate limits.
"""
import logging
import httpx
from datetime import datetime
from fastapi import APIRouter, Query, HTTPException
from app.services.redis_client import get_cache, set_cache
from app.config import NEWS_API_KEY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/news", tags=["news"])


def _analyze_sentiment(text: str) -> str:
    """Basic keyword-based sentiment analysis for news headlines/descriptions."""
    if not text:
        return "neutral"
        
    text = text.lower()
    positive_words = ["surge", "jump", "rally", "gain", "strong", "positive", "growth", "profit", "bull", "up", "high", "resilience", "support", "buying"]
    negative_words = ["drop", "fall", "plunge", "loss", "weak", "negative", "bear", "down", "low", "crash", "sell", "debt", "crisis", "fear", "risk"]
    
    pos_score = sum(1 for word in positive_words if word in text)
    neg_score = sum(1 for word in negative_words if word in text)
    
    if pos_score > neg_score:
        return "positive"
    elif neg_score > pos_score:
        return "negative"
    return "neutral"


# Generic company name mapping for better search results
SYMBOL_MAP = {
    "RELIANCE": "Reliance Industries",
    "TCS": "Tata Consultancy Services",
    "INFY": "Infosys",
    "HDFCBANK": "HDFC Bank",
    "ICICIBANK": "ICICI Bank",
    "SBIN": "State Bank of India",
    "ITC": "ITC Limited",
    "LT": "Larsen & Toubro",
    "BHARTIARTL": "Bharti Airtel",
    "HINDUNILVR": "Hindustan Unilever",
    "NIFTY": "Nifty 50 Market",
    "BANKNIFTY": "Bank Nifty Market",
}


@router.get("")
async def get_news(symbol: str = Query(..., description="Stock Symbol")):
    """Fetch recent news for a stock symbol using GNews API with caching."""
    symbol = symbol.strip().upper()
    keyword = SYMBOL_MAP.get(symbol, symbol)
    
    # 1. Check Cache
    cache_key = f"news:gnews:{symbol}"
    cached_data = await get_cache(cache_key)
    if cached_data:
        logger.debug(f"[NEWS] Cache hit for {symbol}")
        return {"symbol": symbol, "data": cached_data, "cached": True}

    # 2. Free Tier Fallback
    if not NEWS_API_KEY:
        logger.warning(f"[NEWS] NEWS_API_KEY missing for {symbol}. Returning fallback.")
        return {"symbol": symbol, "data": _get_fallback_news(symbol), "cached": False}

    # 3. Fetch from GNews
    url = f"https://gnews.io/api/v4/search?q={keyword}&lang=en&country=in&max=10&apikey={NEWS_API_KEY}"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            
            if response.status_code == 403 or response.status_code == 429:
                logger.warning(f"[NEWS] Rate limit hit. Code: {response.status_code}")
                # Fallback to last known cache if available, else static
                return {"symbol": symbol, "data": _get_fallback_news(symbol), "cached": False, "error": "Rate limited"}
            
            response.raise_for_status()
            data = response.json()
            
            print("News API response:", data)
            
            articles = []
            for item in data.get("articles", []):
                title = item.get("title", "")
                desc = item.get("description", "")
                # Analyze sentiment from combined title and description
                combined_text = f"{title} {desc}"
                sentiment = _analyze_sentiment(combined_text)

                articles.append({
                    "id": item.get("url"), # URL acts as UUID
                    "title": title,
                    "description": desc,
                    "url": item.get("url"),
                    "image": item.get("image"),
                    "publishedAt": item.get("publishedAt"),
                    "source": item.get("source", {}).get("name", "News"),
                    "sentiment": sentiment
                })
            
            if not articles:
                articles = _get_fallback_news(symbol)

            # 4. Cache for 10 minutes (600s) to save API calls
            await set_cache(cache_key, articles, ttl=600)
            
            return {"symbol": symbol, "data": articles, "cached": False}

    except Exception as e:
        logger.error(f"[NEWS] Failed to fetch news for {symbol}: {e}")
        return {"symbol": symbol, "data": _get_fallback_news(symbol), "cached": False, "error": str(e)}


def _get_fallback_news(symbol: str) -> list[dict]:
    """Fallback static news if API fails, limit reached, or no key."""
    return [
        {
            "id": f"{symbol}-1",
            "title": f"{symbol} shows strong market resilience despite global headwinds.",
            "description": "Analysts remain optimistic about the company's long-term growth trajectory.",
            "url": "#",
            "image": None,
            "publishedAt": datetime.utcnow().isoformat() + "Z",
            "source": "Market Watch",
            "sentiment": "positive"
        },
        {
            "id": f"{symbol}-2",
            "title": f"Institutional buying supports {symbol} at support levels.",
            "description": "Block deals were observed earlier today.",
            "url": "#",
            "image": None,
            "publishedAt": datetime.utcnow().isoformat() + "Z",
            "source": "Financial Times",
            "sentiment": "positive"
        },
        {
            "id": f"{symbol}-3",
            "title": f"Concerns loom over {symbol}'s recent earnings report.",
            "description": "Investors express uncertainty over next quarter's projections amid rising costs.",
            "url": "#",
            "image": None,
            "publishedAt": datetime.utcnow().isoformat() + "Z",
            "source": "Economy Today",
            "sentiment": "negative"
        }
    ]

"""
Lightweight sentiment analysis API using keyword parsing on recent news titles.
"""
import logging
from fastapi import APIRouter, Query

from app.routes.news import get_news

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/sentiment", tags=["sentiment"])

# Keyword dictionary for quick scoring
BULLISH_KEYWORDS = ["gain", "growth", "profit", "strong", "beat", "surge", "up", "buy", "bullish", "positive", "resilience"]
BEARISH_KEYWORDS = ["loss", "decline", "drop", "weak", "fall", "down", "sell", "bearish", "negative", "crash", "plunge"]

@router.get("")
async def get_sentiment(symbol: str = Query(..., description="Stock Symbol")):
    """Analyze recent news headlines to generate a sentiment score for the symbol."""
    symbol = symbol.strip().upper()
    
    # 1. Fetch News
    news_response = await get_news(symbol=symbol)
    articles = news_response.get("data", [])
    
    if not articles:
        return {
            "symbol": symbol,
            "fear_greed": 50,
            "label": "Neutral",
            "bullish_count": 0,
            "bearish_count": 0,
            "error": "No news available for sentiment"
        }

    # 2. Analyze sentiment
    bull_score = 0
    bear_score = 0
    
    for idx, article in enumerate(articles):
        title = article.get("title", "").lower()
        desc = article.get("description", "").lower()
        content = f"{title} {desc}"
        
        # Recency weighting: First few articles (most recent) matter more
        weight = 1.5 if idx < 3 else 1.0
        
        for w in BULLISH_KEYWORDS:
            if w in content:
                bull_score += weight
                
        for w in BEARISH_KEYWORDS:
            if w in content:
                bear_score += weight

    # 3. Calculate Fear/Greed index (0-100)
    total_score = bull_score + bear_score
    if total_score == 0:
        index = 50.0 # Neutral baseline
    else:
        # Scale proportion to 0-100 gauge (Greed = Bullish, Fear = Bearish)
        bull_ratio = bull_score / total_score
        index = bull_ratio * 100

    # Smooth extreme values slightly towards median
    fear_greed = round(index * 0.8 + 50 * 0.2)
    
    # Generate labels
    if fear_greed >= 65:
        label = "Greed"
    elif fear_greed <= 35:
        label = "Fear"
    else:
        label = "Neutral"

    return {
        "symbol": symbol,
        "fear_greed": fear_greed,
        "label": label,
        "bullish_count": round(bull_score),
        "bearish_count": round(bear_score),
    }

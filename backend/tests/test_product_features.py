import pytest
from httpx import AsyncClient, ASGITransport
from app.server import app

@pytest.mark.anyio
async def test_news_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/news?symbol=RELIANCE")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "RELIANCE"
    assert "data" in data
    assert isinstance(data["data"], list)

@pytest.mark.anyio
async def test_sentiment_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/sentiment?symbol=TCS")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "TCS"
    assert "fear_greed" in data
    assert "label" in data
    assert "bullish_count" in data
    assert "bearish_count" in data

# Backtest is heavily mocked here as it relies on specific CSV files.
@pytest.mark.anyio
async def test_backtest_unauthorized():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/backtest", json={
            "symbol": "RELIANCE",
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
            "capital": 100000
        })
    # Since we are not passing auth token
    assert response.status_code == 401

# StockAI Production Debug & Fix TODO
Current: Backend APIs/WS working (mock data). Fix real-time + config.

## ✅ Step 1: Add /api/v1/signal alias (1min)
- backend/app/routes/predict.py: Add GET /signal → get_predict()

## ✅ Step 2: Update CORS for Railway domain (1min)  
- backend/app/server.py: Add https://stockai-pro-production.up.railway.app

## 🔄 Step 3: Copy models/ to Railway (5min)
- Add models/*.pkl to repo/Dockerfile COPY
- `git add models/ && git commit -m "Add ML models"`

## 🔄 Step 4: Fix SmartAPI WS (10min)
- Verify Railway SMARTAPI_TOTP_SECRET valid
- backend/app/server.py: Add startup log _smartapi_ws_started status

## 🔄 Step 5: Fix Redis (5min)
- Railway REDIS_URL=redis://redis.railway.internal:6379

## 🔄 Step 6: Frontend Env Vars (5min)
- VITE_API_URL=https://stockai-pro-production.up.railway.app
- VITE_WS_URL=wss://stockai-pro-production.up.railway.app/live

## 🔄 Step 7: Fix system date (2min)
- Railway shell: `date` → Check timezone

## 🔄 Step 8: Test & Verify (10min)
```
curl https://stockai-pro-production.up.railway.app/health | jq .smartapi_connected
ws = new WebSocket('wss://.../live'); ws.onmessage=console.log
```
Expected: real ticks, models loaded, graphs live.

**Progress: 4/8**  
✅ Step 4: SmartAPI WS startup log added.

**Next deploy → test /health**

Remaining:
- Step 5 Redis (Railway var)
- Step 6 Frontend env
- Step 7 Date
- Step 8 Test


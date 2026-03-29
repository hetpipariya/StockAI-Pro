# API Configuration Fix - Verification Checklist

## Problem Summary
- Frontend was calling relative API paths (`/api/...`) instead of absolute backend URLs
- WebSocket was connecting to frontend domain instead of backend
- This caused 522 errors and API calls returning frontend HTML instead of JSON

## Root Causes Fixed
1. **Environment variable mismatch**: `.env.local` used `VITE_API_URL` but config expected `VITE_API_BASE_URL`
2. **Relative WebSocket URL**: `VITE_WS_URL=/ws` connected to frontend instead of backend
3. **Missing absolute URL enforcement**: Config didn't validate that URLs were absolute

## Files Modified

### Configuration Files
- `frontend/src/config/api.js` - Centralized API configuration with absolute URL enforcement
- `frontend/.env` - Default development environment
- `frontend/.env.local` - Local development overrides
- `frontend/.env.production` - Production environment
- `frontend/.env.example` - Example configuration

### WebSocket Files
- `frontend/src/hooks/useWebsocket.js` - WebSocket hook with improved reconnection
- `frontend/src/utils/socket.js` - WebSocket manager with exponential backoff

### Utility Files
- `frontend/src/utils/env.js` - Re-exports from centralized config

---

## Verification Steps

### Step 1: Backend Health Check
Open in browser:
```
https://api.stockai-pro.in/api/health
```
**Expected**: JSON response like `{"status": "ok"}` or similar
**If you see HTML/login page**: DNS or backend issue, not frontend

### Step 2: Frontend Loads
Open in browser:
```
https://stockai-pro.in
```
**Expected**: Login page or dashboard loads correctly
**If 522 error**: Check Cloudflare DNS settings

### Step 3: Check Console Logs
1. Open DevTools (F12)
2. Go to Console tab
3. Look for `[API Config]` logs

**Expected logs in production**:
```
[API Config] Resolved URLs: {
  API_BASE: "https://api.stockai-pro.in",
  API_V1_BASE: "https://api.stockai-pro.in/api/v1",
  WS_URL: "wss://api.stockai-pro.in/live"
}
```

**Red flags**:
- `API_BASE` showing `http://localhost:8000` in production
- `WS_URL` showing relative path like `/ws` or `/live`
- `WS_URL` showing `wss://stockai-pro.in/live` (frontend domain)

### Step 4: Network Tab Verification
1. Open DevTools (F12)
2. Go to Network tab
3. Filter by "Fetch/XHR"
4. Perform actions (login, view stocks, etc.)

**Expected**:
- All API calls go to `api.stockai-pro.in`
- No calls to `stockai-pro.in/api/...`

**Check each request**:
- URL should start with `https://api.stockai-pro.in/api/v1/`
- Response should be JSON, not HTML

### Step 5: WebSocket Verification
1. Open DevTools (F12)
2. Go to Network tab
3. Filter by "WS" (WebSocket)
4. Login and navigate to a stock page

**Expected**:
- WebSocket connects to `wss://api.stockai-pro.in/live?token=...`
- Status shows "101 Switching Protocols"
- Messages flow (tick data)

**Red flags**:
- WebSocket connecting to `wss://stockai-pro.in/live` (wrong domain)
- Connection failing with 404 or 502

### Step 6: Mobile Device Test
1. Open `https://stockai-pro.in` on mobile
2. Login and use the app
3. Check for 522 errors

**Expected**: App works without errors

---

## Deployment Checklist

### Before Deploying
- [ ] Verify `.env.production` has correct values:
  ```
  VITE_API_BASE_URL=https://api.stockai-pro.in
  VITE_WS_URL=wss://api.stockai-pro.in/live
  ```
- [ ] Run `npm run build` locally to test production build
- [ ] Check build output for any warnings

### After Deploying
- [ ] Clear browser cache or use incognito
- [ ] Run through all verification steps above
- [ ] Test on multiple devices (desktop, mobile)
- [ ] Check Cloudflare Analytics for 522 errors

---

## Troubleshooting

### Issue: API calls still going to frontend
**Cause**: Old build cached, or environment variables not loaded
**Fix**: 
1. Clear Cloudflare cache
2. Clear browser cache
3. Verify `.env.production` is in the build

### Issue: WebSocket not connecting
**Cause**: Wrong WebSocket URL or CORS issue
**Fix**:
1. Check console for WebSocket URL being used
2. Verify backend allows WebSocket connections from frontend domain
3. Check backend CORS settings

### Issue: 522 errors on mobile
**Cause**: Backend not responding in time, or DNS issue
**Fix**:
1. Check Render backend logs
2. Verify `api.stockai-pro.in` DNS is "DNS only" (not proxied)
3. Check backend health endpoint directly

### Issue: CORS errors
**Cause**: Backend not allowing frontend origin
**Fix**: Ensure backend CORS allows:
- `https://stockai-pro.in`
- `https://www.stockai-pro.in` (if applicable)

---

## Quick Commands

### Local Development
```bash
cd frontend
npm run dev
# Opens http://localhost:5173
# API calls proxied to backend
```

### Production Build Test
```bash
cd frontend
npm run build
npm run preview
# Opens http://localhost:4173
# Uses production environment variables
```

### Check Environment Variables
```bash
# In browser console after loading the app:
console.log(window.__VITE_ENV__ || 'Check [API Config] logs above')
```

---

## Contact
If issues persist after following this checklist, check:
1. Cloudflare dashboard for DNS settings
2. Render dashboard for backend logs
3. Browser DevTools for specific error messages

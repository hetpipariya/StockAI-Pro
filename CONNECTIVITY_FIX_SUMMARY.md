# StockAI-Pro Connectivity Fix Summary

## 🔥 Issues Fixed

### 1. ✅ Frontend API Configuration (ALREADY CORRECT)
- **File**: [`frontend/src/api/api.js`](frontend/src/api/api.js:23) and [`frontend/src/utils/env.js`](frontend/src/utils/env.js:3)
- **Status**: Already correctly configured
- **API Base**: `https://api.stockai-pro.in/api/v1`
- **Login Endpoint**: `/auth/login`

### 2. ✅ Backend CORS Configuration (FIXED)
- **File**: [`backend/app/middleware.py`](backend/app/middleware.py:154)
- **Changes**:
  - Added `"*"` wildcard to allowed origins for debugging
  - Added `expose_headers=["*"]` for better CORS compatibility
  - Origins now include: `https://stockai-pro.in`, `https://www.stockai-pro.in`, `*`

### 3. ✅ Frontend Error Handling (FIXED)
- **Files**: [`frontend/src/utils/api.js`](frontend/src/utils/api.js:81) and [`frontend/src/api/api.js`](frontend/src/api/api.js:324)
- **Changes**:
  - Improved abort error detection with additional regex patterns
  - Better error messages for timeouts and network failures
  - Added detailed debug logging for API calls
  - Replaced "signal aborted without reason" with actionable messages

### 4. ✅ WebSocket Retry Logic (FIXED)
- **File**: [`backend/app/websocket/handler.py`](backend/app/websocket/handler.py:56)
- **Changes**:
  - Added `_WS_MAX_RETRY_ATTEMPTS = 3` constant
  - Limited infinite retry loop to prevent SmartAPI 429 errors
  - Improved logging with attempt counter

---

## 📋 Cloudflare DNS Configuration

### DNS Settings for `api.stockai-pro.in`

| Type | Name | Value | Proxy Status |
|------|------|-------|--------------|
| CNAME | api | `your-render-service.onrender.com` | 🟠 ON (Orange Cloud) |

### Important Testing Steps

#### Step 1: Test Without Proxy (Grey Cloud)
1. Go to Cloudflare Dashboard → DNS
2. Find `api.stockai-pro.in` record
3. Click the orange cloud to turn it **grey** (DNS only)
4. Wait 2-3 minutes for propagation
5. Test from mobile: `https://api.stockai-pro.in`

#### Step 2: If Direct Works, Re-enable Proxy
1. Turn cloud back to **orange** (Proxied)
2. Go to SSL/TLS → Overview
3. Set encryption mode to **Full (strict)**
4. Go to SSL/TLS → Edge Certificates
5. Ensure "Always Use HTTPS" is **ON**

### Cloudflare SSL/TLS Settings
```
SSL/TLS Encryption: Full (strict)
Always Use HTTPS: ON
Automatic HTTPS Rewrites: ON
HTTP Strict Transport Security (HSTS): ON
Minimum TLS Version: 1.2
```

---

## 🔧 Render Configuration

### Service Settings

```yaml
Service Type: Web Service (NOT Background Worker)
Build Command: pip install -r requirements.txt
Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### Critical Environment Variables

```bash
# Required for CORS
FRONTEND_URL=https://stockai-pro.in

# Required for JWT
JWT_SECRET=your-strong-secret-here-min-32-chars

# Required for database (PostgreSQL recommended for production)
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Optional: Additional CORS origins
CORS_ORIGINS=https://www.stockai-pro.in,https://stockai-pro.pages.dev

# Required for SmartAPI
SMARTAPI_API_KEY=your_api_key
SMARTAPI_CLIENT_ID=your_client_id
SMARTAPI_CLIENT_PWD=your_password
SMARTAPI_TOTP_SECRET=your_totp_secret
```

### Render Health Check
Ensure your service has a health check path:
- Path: `/api/v1`
- Expected Response: `{"status":"ok",...}`

---

## 🧪 Testing Steps

### 1. Test Backend Directly
```bash
curl -v https://api.stockai-pro.in/api/v1
```
Expected: `{"status":"ok","endpoints":[...]}`

### 2. Test Login Endpoint
```bash
curl -X POST https://api.stockai-pro.in/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test"}'
```
Expected: `401 Unauthorized` (if credentials wrong) or `200 OK` with tokens

### 3. Test CORS Preflight
```bash
curl -X OPTIONS https://api.stockai-pro.in/api/v1/auth/login \
  -H "Origin: https://stockai-pro.in" \
  -H "Access-Control-Request-Method: POST" \
  -v
```
Expected: `200 OK` with `Access-Control-Allow-Origin: *`

### 4. Browser DevTools Testing
1. Open `https://stockai-pro.in` in browser
2. Open DevTools → Network tab
3. Try to login
4. Check:
   - Request URL: `https://api.stockai-pro.in/api/v1/auth/login`
   - Status: Should be `200` or `401` (not `0` or `CORS error`)
   - Response headers should include `access-control-allow-origin`

---

## 🔍 Root Cause Analysis

### Primary Issues

1. **Cloudflare Error 522 (Mobile)**
   - **Cause**: Cloudflare cannot establish TCP connection to Render backend
   - **Possible Reasons**:
     - Render service is down/sleeping
     - Wrong PORT binding (must use `$PORT` env var)
     - Render blocking Cloudflare IPs
   - **Fix**: Test with grey cloud first, check Render logs

2. **"Signal Aborted Without Reason" Error**
   - **Cause**: AbortController timing out before fetch completes
   - **Trigger**: Slow network, CORS preflight delays, or Render cold start
   - **Fix**: Improved error messaging to distinguish timeout vs network error

3. **WebSocket 429 Errors**
   - **Cause**: Infinite retry loop hitting SmartAPI rate limits
   - **Fix**: Added max retry limit (3 attempts) with exponential backoff

### CORS Configuration Issue
The backend CORS was correctly configured but:
- Default `FRONTEND_URL` in config was old Pages.dev URL
- Added `"*"` wildcard for debugging mobile issues
- Mobile browsers may have stricter CORS handling

---

## 📁 Files Modified

| File | Changes |
|------|---------|
| [`backend/app/middleware.py`](backend/app/middleware.py:154) | Added CORS wildcard, expose_headers |
| [`backend/app/websocket/handler.py`](backend/app/websocket/handler.py:56) | Added max retry limit |
| [`frontend/src/utils/api.js`](frontend/src/utils/api.js:81) | Improved error handling |
| [`frontend/src/api/api.js`](frontend/src/api/api.js:259) | Added debug logging, improved errors |

---

## 🚀 Deployment Checklist

- [ ] Deploy backend to Render
- [ ] Verify Render service is "Live" (not sleeping)
- [ ] Test API directly: `curl https://api.stockai-pro.in/api/v1`
- [ ] Deploy frontend
- [ ] Test login on desktop
- [ ] Test login on mobile
- [ ] If mobile fails with 522: Disable Cloudflare proxy, test direct
- [ ] Re-enable Cloudflare proxy after verification
- [ ] Monitor WebSocket connections for 429 errors

---

## 📞 Debug Commands

```bash
# Check if backend is reachable
curl -I https://api.stockai-pro.in/api/v1

# Check CORS headers
curl -H "Origin: https://stockai-pro.in" \
     -I https://api.stockai-pro.in/api/v1/auth/login

# Test with verbose output
curl -v https://api.stockai-pro.in/api/v1 2>&1 | grep -i "access-control"

# Check DNS resolution
nslookup api.stockai-pro.in

# Trace route (Windows)
tracert api.stockai-pro.in
```

---

## ⚠️ IMPORTANT NOTES

1. **The wildcard CORS (`*`) is for debugging only** - Remove after fixing connectivity
2. **Cloudflare 522** usually means Render service is down or misconfigured
3. **Always test direct connection first** (grey cloud) before troubleshooting CORS
4. **Render free tier sleeps** - First request may timeout (15-30s cold start)

# 🚀 StockAI Pro — AI Powered Trading System

> ⚡ Real-time AI Trading Engine with SmartAPI Integration, Live Charts, Signal Generation & Full-Stack Infrastructure

---

## 🧠 Overview

**StockAI Pro** is a production-grade AI-powered trading system that combines:

* 📊 Real-time market data
* 🤖 Machine Learning + Technical Indicators
* 📈 Interactive charting system
* ⚡ Live WebSocket streaming
* 💼 Risk-managed trade execution

Built with a full-stack architecture using **FastAPI + React + SmartAPI + Redis + PostgreSQL + Docker**

---

## 🔥 Key Features

### 📊 Trading & Analytics

* Real-time OHLCV data streaming
* Multi-timeframe charts (1m, 5m, etc.)
* Gap filling & spike detection
* Indicator overlays (RSI, EMA, ATR, etc.)

### 🤖 AI Signal Engine

* ML model (XGBoost) + Technical Strategy
* Confidence-based BUY / SELL / HOLD signals
* ATR-based Target & Stop Loss
* Risk-managed position sizing

### ⚡ Real-time System

* WebSocket live price updates
* SmartAPI integration
* Redis caching layer
* DB fallback system

### 📱 UI/UX

* Fully responsive (Mobile + Desktop)
* Interactive charts (zoom, pan, gestures)
* Signal notifications
* Error boundaries

### 🛡️ Safety & Risk Management

* Kill-switch (TRADING_ENABLED)
* Daily loss limit
* Paper trading mode
* Secure JWT authentication

---

## 🏗️ Tech Stack

### Frontend

* ⚛️ React 18
* 📊 Lightweight Charts
* 🎨 Tailwind CSS

### Backend

* 🚀 FastAPI
* 🔐 JWT Auth
* 🔄 WebSockets

### Data & Infra

* 🧠 SmartAPI (Angel One)
* 🗄️ PostgreSQL / SQLite
* ⚡ Redis
* 🐳 Docker + Nginx
* 📈 Prometheus Monitoring

---

## 📁 Project Structure

```
StockAI-Pro/
│
├── backend/          # FastAPI backend (API + Trading Engine)
├── frontend/         # React frontend UI
├── nginx/            # Reverse proxy config
├── infra/            # Deployment configs
├── prometheus/       # Monitoring setup
│
├── docker-compose.yml
├── .env.example
├── README.md
```

---

## ⚙️ Setup Guide (Step-by-Step)

---

### 🔹 1. Clone Repository

```bash
git clone https://github.com/hetpipariya/StockAI-Pro.git
cd StockAI-Pro
```

---

### 🔹 2. Setup Environment Variables

Create `.env` file:

```env
JWT_SECRET=your_secret_key
SMARTAPI_API_KEY=your_api_key
SMARTAPI_CLIENT_ID=your_client_id
SMARTAPI_PASSWORD=your_password
SMARTAPI_TOTP_SECRET=your_totp_secret
DATABASE_URL=sqlite:///./test.db
REDIS_URL=redis://localhost:6379
```

⚠️ Never push `.env` to GitHub

---

### 🔹 3. Backend Setup

```bash
cd backend
pip install -r requirements.txt
uvicorn app.server:app --reload
```

👉 Runs on: `http://localhost:8000`

---

### 🔹 4. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

👉 Runs on: `http://localhost:5173`

---

### 🔹 5. Docker Setup (Recommended)

```bash
docker-compose up --build
```

---

## 🔌 SmartAPI Integration (Important 🔥)

This system uses **Angel One SmartAPI** for real-time trading data.

### 📡 How it works:

1. Login using SmartAPI credentials
2. Generate session token
3. Fetch historical OHLCV data
4. Subscribe to WebSocket for live ticks
5. Aggregate ticks → candles
6. Pass data → AI model
7. Generate signals

---

### ⚡ Flow Diagram (Simplified)

```
SmartAPI → WebSocket → Backend → Signal Engine → Frontend
                         ↓
                     Database + Redis
```

---

## 🤖 AI Signal Logic

* ML Model: XGBoost
* Indicators: RSI, EMA, ATR
* Ensemble Decision:

```
Final Signal = ML Prediction + Technical Confirmation
```

* Output:

  * BUY 📈
  * SELL 📉
  * HOLD ⏸️

---

## 📊 Performance & Optimization

* Redis caching (30s TTL)
* WebSocket throttling
* 500 candle limit buffer
* Async API handling

---

## 🛡️ Security Notes

* 🔐 JWT Authentication
* 🚫 No `.env` exposure
* ⚠️ Restrict CORS in production
* 🔒 Use HTTPS (Nginx + SSL)

---

## 🚀 Deployment Guide

### Backend

```bash
docker-compose up -d --build
```

### SSL Setup

```bash
certbot --nginx -d yourdomain.com
```

---

## 📌 Future Improvements

* 🔄 Backtesting engine
* 📊 Advanced indicators
* 🤖 GenAI integration
* 📱 Mobile app

---

## 🙌 Author

👤 Het Pipariya
💡 AI + Trading System Developer

---

## ⭐ Support

If you like this project:

👉 Star the repo ⭐
👉 Share with others 🚀

---

## ⚠️ Disclaimer

This project is for **educational purposes only**.
Trading involves financial risk.

---

# 🚀 Built with Passion, Logic & AI

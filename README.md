# StockAI Pro

<div align="center">

### AI-Powered Real-Time Trading Intelligence Platform for Indian Markets (NSE/BSE)

[![GitHub License](https://img.shields.io/github/license/hetpipariya/StockAI-Pro?style=for-the-badge&color=blue)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![React Version](https://img.shields.io/badge/react-18-blue?style=for-the-badge&logo=react&logoColor=white)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100.0%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)

</div>

---

> [!WARNING]
> ### ⚠️ DEVELOPMENT PAUSED
> **Development is currently paused.** The original creator is focusing on algorithmic trading research and development. The repository is now open-source, and community contributions are highly welcome. Feel free to fork, improve, fix issues, add features, and continue development.

---

## 📋 Project Overview

**StockAI Pro** is a high-performance, AI-driven real-time trading intelligence platform designed specifically for the Indian Stock Markets (NSE/BSE). Built to bridge the gap between institutional-grade trading infrastructure and retail traders, StockAI Pro processes real-time feeds, generates predictive trade signals using machine learning, evaluates risk metrics in real-time, and offers a paper-trading sandbox to test strategies without financial exposure.

### Why it was built
The platform was built to demonstrate how modern, distributed web architectures (FastAPI, React, Redis, WebSockets, PostgreSQL) can be combined with Machine Learning models (like XGBoost) to construct an end-to-end, low-latency trading dashboard.

### Main Goal
To empower researchers, developers, and algorithmic traders with a robust, modular framework for real-time signal generation, market data ingestion, and portfolio analytics in the Indian equities space.

---

## ✨ Features

- **⚡ Real-Time Data Architecture**: Ingestion and processing of live market feeds for NSE/BSE stocks with tick-by-tick updates.
- **🤖 AI Signal Generation**: Machine learning engine utilizing XGBoost and technical indicators to identify short-term momentum and trend reversals.
- **🛡️ Risk Management System**: Automated validation checking for maximum daily loss, max drawdown, and position sizing.
- **📈 Paper Trading Engine**: Realistic matching engine simulating orders against real-time market data to track virtual PnL.
- **🔐 JWT Authentication**: Secure user login, session management, and verification.
- **📋 Watchlists**: Create and manage custom watchlists with live price monitoring.
- **🖥️ Dashboard**: Modern frontend showing live chart feeds, active positions, performance charts, and signal logs.
- **🔄 WebSocket Streaming**: Duplex communication channel for low-latency streaming of market ticks and system alerts.
- **🗄️ PostgreSQL Storage**: Relational storage for users, order book history, and indicators.
- **🚀 Redis Caching**: Fast cache layer for real-time tick buffer, rate limiting, and session caching.

---

## 🛠️ Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Frontend** | React 18, Vite, Tailwind CSS, Lucide Icons, Recharts |
| **Backend** | FastAPI, Python 3.10+, Uvicorn, SQLAlchemy |
| **Database** | PostgreSQL |
| **Cache & Message Broker** | Redis |
| **AI / Machine Learning** | XGBoost, Scikit-learn, Pandas, NumPy |
| **Containerization** | Docker, Docker Compose |

---

## 📐 Architecture

```mermaid
graph TD
    subgraph Market Data Ingestion
        MD[Market Data Feed <br/> NSE/BSE APIs/WebSockets]
    end

    subgraph Backend Engine [FastAPI Backend]
        BE[Data Ingestion Controller]
        AI[AI Signal Engine <br/> XGBoost Predictor]
        RM[Risk Manager <br/> Validation & Limits]
        PE[Paper Trading Engine]
        DB[(PostgreSQL Database)]
        RC[(Redis Cache / Pub-Sub)]
    end

    subgraph Client Layer [React Frontend]
        FE[Dashboard UI]
        WS[WebSocket Client]
    end

    MD -->|Real-time Ticks| BE
    BE -->|Process Ticks| RC
    RC -->|Historical Ticks| AI
    AI -->|Buy/Sell Signals| RM
    RM -->|Validated Orders| PE
    PE -->|Persist Trades| DB
    PE -->|Cached Positions| RC
    RC -->|Pub/Sub Alerts| WS
    WS -->|Live Tick Streaming| FE
```

---

## 🚦 Project Status

- **Status**: ⚠️ Paused
- **Reason**: The original creator is currently focusing on algorithmic trading research and development. Future development may continue later.
- **Community Contributions**: Welcome! The code has been open-sourced to allow the community to build upon, fix, and enhance the framework.

---

## 🤝 Open Source Contributions

We welcome contributions from the community! To contribute to StockAI Pro, please follow these steps:

1. **Fork the Repository** on GitHub.
2. **Create a Branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes** and commit them with descriptive commit messages.
4. **Push your changes** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
5. **Open a Pull Request** to the main repository. Please describe the changes, fix issues, and specify what features were added.

---

## 💻 Local Setup Guide

Follow these instructions to set up StockAI Pro on your local machine.

### Prerequisites
- Python 3.10+ installed
- Node.js 18+ and npm installed
- PostgreSQL and Redis installed and running (or Docker installed)

### 1. Clone the Repository
```bash
git clone https://github.com/hetpipariya/StockAI-Pro.git
cd StockAI-Pro
```

### 2. Backend Setup
1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Create a Python virtual environment:
   ```bash
   python -m venv venv
   ```
3. Activate the virtual environment:
   - **Windows (PowerShell)**:
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```
   - **macOS/Linux**:
     ```bash
     source venv/bin/activate
     ```
4. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
5. Set up your environment variables (see [Environment Variables](#-environment-variables)).
6. Run database migrations:
   ```bash
   alembic upgrade head
   ```

### 3. Frontend Setup
1. Navigate to the frontend directory:
   ```bash
   cd ../frontend
   ```
2. Install dependencies:
   ```bash
   npm install
   ```

### 4. Running the Application Locally
Make sure PostgreSQL and Redis are running on your system.

1. **Start the Backend**:
   From the `backend` directory (with your virtual environment active):
   ```bash
   uvicorn main:app --reload --host 127.0.0.1 --port 8000
   ```
2. **Start the Frontend**:
   From the `frontend` directory:
   ```bash
   npm run dev
   ```
   Open your browser and navigate to `http://localhost:5173`.

### 5. Running with Docker (Recommended)
You can run the entire stack (PostgreSQL, Redis, Backend, Frontend) with Docker Compose:
```bash
# In the root project directory
docker-compose up -d --build
```
This will automatically launch all containers and run migrations.

---

## 🔑 Environment Variables

Create a `.env` file in the root directory. Below is an example `.env.example` file that you can use as a template:

```env
# Application Environment
APP_ENV=production
DEBUG=false

# PostgreSQL Database Configuration
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=stockai
DB_PORT=5432
DATABASE_URL=postgresql+asyncpg://postgres:your_secure_password@localhost:5432/stockai

# Redis Cache Configuration
REDIS_URL=redis://localhost:6379/0

# Backend Security
JWT_SECRET=your_super_secret_jwt_key_at_least_64_characters_long

# Broker API Credentials (Required for Live Trading/Market Data Ingestion)
SMARTAPI_API_KEY=your_smartapi_key
SMARTAPI_CLIENT_ID=your_client_id
SMARTAPI_PASSWORD=your_password
SMARTAPI_TOTP_SECRET=your_totp_secret

UPSTOX_API_KEY=your_upstox_key
UPSTOX_API_SECRET=your_upstox_secret
UPSTOX_REDIRECT_URI=http://localhost:8000/callback

# API Keys (Optional)
NEWS_API_KEY=your_news_api_key_for_sentiment
OPENROUTER_API_KEY=your_openrouter_key

# Trading Settings
TRADING_MODE=PAPER  # PAPER or LIVE
TRADING_ENABLED=true
```

---

## 🗺️ Roadmap

- [ ] **Multi-user support**: Separate dashboards and API key configurations per user.
- [ ] **Better AI models**: Implement LSTM/Transformer models to complement XGBoost.
- [ ] **Broker integrations**: Add native connectors for Zerodha, Groww, and Dhan.
- [ ] **Backtesting engine**: Historic simulation engine to backtest strategies on ticks.
- [ ] **Mobile App**: Responsive companion mobile view or React Native app.
- [ ] **Portfolio Analytics**: Deep insights into trade history, win-rates, Sharpe Ratio, and drawdown stats.
- [ ] **Multi-broker support**: Trade splitting and concurrent execution across multiple broker accounts.

---

## ⚠️ Known Limitations

- **Development Status**: The repository is currently not actively maintained by the original creator.
- **Multi-user Capability**: Currently optimized for single-tenant setup. Improving multi-user isolation is recommended before any SaaS deployments.
- **Production Readiness**: Security reviews and stress testing should be conducted before running live trading strategies.
- **AI Engine Validation**: The default XGBoost models are pre-configured examples and should be fully backtested and validated with clean data before real capital allocation.

---

## ⚖️ Disclaimer

> [!CAUTION]
> ### 🚨 FINANCIAL DISCLAIMER
> This repository is released strictly for **learning, research, and educational purposes**, as well as open-source collaboration. **It does NOT constitute financial advice.**
>
> Algorithmic trading involves substantial risk of loss. There is no guarantee of profitability, and past performance is not indicative of future results. The authors and contributors assume no responsibility or liability for any financial losses incurred through the use of this software. **Use at your own risk.**

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🌟 Support

If you find this project useful or plan to build upon it, please consider giving it a ⭐ on GitHub!

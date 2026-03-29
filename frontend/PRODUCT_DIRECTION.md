# StockAI-Pro: V1 Product Direction & UX Architecture

## 1. Core Product Definition
**Mission Statement:**  
> "Delivering instant, unambiguous AI trading signals for fast, high-conviction decision making."

The product is built on radical simplicity. It eliminates noise and analysis paralysis, acting purely as an ultra-fast conduit between real-time data, AI computation, and trader execution. 

---

## 2. User Flow (Strict Simplification)
The V1 user flow is entirely frictionless, dropping the user immediately into the actionable environment.

1. **Launch App:** Instantly load the default trading pair (e.g., AAPL).
2. **Scan Watchlist:** Quick access to predefined, highly liquid test symbols.
3. **Select Symbol:** Immediate UI update to highlight the specific asset.
4. **View Chart & Price:** Verify the current market state on a clean OHLCV chart.
5. **Read Signal & Decide:** Interpret the unambiguous AI directive (Buy/Sell/Hold) and finalize the trading decision.

*(Total Steps: 5. No login. No onboarding. No settings menus.)*

---

## 3. V1 Feature Scope (Only Essential)
This is exactly what is required for the internal testing phase to validate the AI accuracy and app speed.

* **Minimal Watchlist:** A hardcoded, predefined list of symbols allowing instantaneous toggling.
* **Live Price Header:** Real-time (or near real-time) ticker showing the current active price of the selected asset.
* **The Signal Card (Core):** A massive, unmissable UI card detailing the current AI stance, target, and stop loss.
* **Candlestick Chart (Basic):** A clean, simple OHLCV chart focusing strictly on price action without a clutter of technical indicators.
* **Basic Navbar:** A minimal header containing only the product name and system/connection status.

---

## 4. Out of Scope (Strict Removal List)
To maintain focus and zero-latency decision making, the following features are actively removed or disabled from the current iteration:

* 🚫 **Auth/Login System** (No user accounts for internal V1 testing)
* 🚫 **News Panel** (Distraction from pure price-action/AI signals)
* 🚫 **Sentiment Panel** (Noise)
* 🚫 **Correlation / Heatmaps** (Too macro, detracts from the active symbol)
* 🚫 **Backtesting UI** (Historical performance is a separate workflow)
* 🚫 **Duplicate / Experimental Panels** (Clean slate only)
* 🚫 **Secondary Signal Sources** (Only ONE single source of truth for the AI signal is allowed)

---

## 5. Signal System Definition (Critical)
The data contract connecting the backend AI to the frontend UI. This is the single source of truth and must be strictly adhered to:

```typescript
export interface TradingSignal {
  symbol: string;
  signal: "BUY" | "SELL" | "HOLD";
  confidence: number;  // Range: 0–100
  target: number;      // Take Profit level
  stopLoss: number;    // Invalidation level
  price: number;       // Execution/Entry price
  timestamp: string;   // ISO 8601 Timestamp
}
```

---

## 6. UX Principles (Strict Rules)
The UI MUST abide by the following design constraints:

1. **One Screen = One Decision:** The entire view must be strictly dedicated to evaluating the currently selected symbol. No split-screen macro analysis.
2. **Zero Duplicate Data:** A single, unified source of truth for the current price and selected asset. Do not repeat the symbol name or price across 4 different panels.
3. **Always-Visible Signal:** The core Signal Card must be placed "above the fold." The user must never have to scroll to see the AI's recommendation.
4. **Absolute Synchronization:** The Chart timeline, the Current Price ticker, and the AI Signal timestamp must be perfectly synced. A stale chart alongside a fresh signal is a critical failure.
5. **No Clutter:** Every pixel, border, and shadow must justify its existence. Omit purely decorative components that distract from the signal data.

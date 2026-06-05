#pragma once

namespace stockai::cpp_engine {

// ────────────────────────────────────────────────────────────────────────────
// FEATURE COMPUTATION CONSTANTS
// ────────────────────────────────────────────────────────────────────────────

// Minimum candles required before computing features
constexpr int MIN_CANDLES_FOR_FEATURES = 50;

// Indicator periods
constexpr int EMA_9_PERIOD = 9;
constexpr int EMA_21_PERIOD = 21;
constexpr int EMA_50_PERIOD = 50;
constexpr int RSI_PERIOD = 14;
constexpr int MACD_FAST_PERIOD = 12;
constexpr int MACD_SLOW_PERIOD = 26;
constexpr int MACD_SIGNAL_PERIOD = 9;
constexpr int ROC_PERIOD = 10;
constexpr int CCI_PERIOD = 20;
constexpr int ATR_PERIOD = 14;
constexpr int ADX_PERIOD = 14;
constexpr int MFI_PERIOD = 14;
constexpr int VOLUME_PERIOD = 20;
constexpr int LINREG_PERIOD = 20;

// ATR Bollinger Bands
constexpr int BB_PERIOD = 20;
constexpr double BB_STDDEV_MULTIPLIER = 2.0;

// Feature version
constexpr const char* FEATURE_VERSION = "v3.0_cpp";

// Default NaN fill values
constexpr double DEFAULT_RSI = 50.0;
constexpr double DEFAULT_MACD = 0.0;
constexpr double DEFAULT_ROC = 0.0;
constexpr double DEFAULT_CCI = 0.0;
constexpr double DEFAULT_EMA_RATIO = 1.0;
constexpr double DEFAULT_VOLUME_RATIO = 1.0;
constexpr double DEFAULT_MFI = 50.0;
constexpr double DEFAULT_BB_PERCENT_B = 0.5;
constexpr double DEFAULT_ATR = 0.0;
constexpr double DEFAULT_ADX = 0.0;
constexpr double DEFAULT_SLOPE = 0.0;

// Market hours (IST: UTC+5:30)
constexpr int MARKET_OPEN_HOUR = 9;
constexpr int MARKET_OPEN_MINUTE = 15;
constexpr int MARKET_CLOSE_HOUR = 15;
constexpr int MARKET_CLOSE_MINUTE = 30;

// Signal thresholds
constexpr double MIN_CONFIDENCE_FOR_TRADE = 0.60;
constexpr double CONFIDENCE_FOR_HOLD = 0.40;
constexpr double MIN_RISK_REWARD_RATIO = 1.5;
constexpr double MIN_VOLUME_RATIO = 0.5;
constexpr double LOW_ATR_THRESHOLD = 0.001;  // 0.1% of close
constexpr double HIGH_ATR_THRESHOLD = 0.10;  // 10% of close
constexpr double ATR_MULTIPLIER_FOR_SL = 1.5;
constexpr double ATR_MULTIPLIER_FOR_TARGET = 3.0;

// Position sizing
constexpr double MAX_POSITION_SIZE_PCT = 0.20;
constexpr double BASE_POSITION_SIZE_PCT = 0.10;

// Trend thresholds
constexpr double TREND_BULL_THRESHOLD = 0.55;
constexpr double TREND_BEAR_THRESHOLD = 0.45;

// Number of features
constexpr int TOTAL_FEATURE_COUNT = 20;

// Feature names (for logging/debugging)
constexpr const char* FEATURE_NAMES[] = {
    // TREND (5)
    "ema_9",
    "ema_21",
    "ema_50",
    "ema_9_21_ratio",
    "linreg_slope_20",
    
    // MOMENTUM (4)
    "rsi_14",
    "macd_histogram",
    "roc_10",
    "cci_20",
    
    // VOLUME (3)
    "vwap_distance_pct",
    "volume_ratio_20",
    "mfi_14",
    
    // VOLATILITY (3)
    "atr_14",
    "bb_width_pct",
    "bb_pct_b",
    
    // STRUCTURE (2)
    "adx_14",
    "candle_body_ratio",
    
    // MULTI-TIMEFRAME (2)
    "ema_direction_15m",
    "ema50_alignment_daily",
    
    // CONTEXT (1)
    "nifty_direction"
};

} // namespace stockai::cpp_engine

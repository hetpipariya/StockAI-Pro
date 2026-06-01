#pragma once

#include <cstdint>
#include <vector>
#include <array>
#include <cmath>

namespace stockai::cpp_engine {

// ────────────────────────────────────────────────────────────────────────────
// FUNDAMENTAL TYPES
// ────────────────────────────────────────────────────────────────────────────

using Price = double;
using Volume = double;
using Timestamp = int64_t;
using FeatureValue = double;

// OHLCV candle
struct Candle {
    Timestamp timestamp;
    Price open;
    Price high;
    Price low;
    Price close;
    Volume volume;
    
    Candle() : timestamp(0), open(0.0), high(0.0), low(0.0), close(0.0), volume(0.0) {}
    
    Candle(Timestamp ts, Price o, Price h, Price l, Price c, Volume v)
        : timestamp(ts), open(o), high(h), low(l), close(c), volume(v) {}
    
    // Validation
    bool is_valid() const {
        return std::isfinite(open) && std::isfinite(high) && std::isfinite(low) 
            && std::isfinite(close) && std::isfinite(volume)
            && high >= open && high >= close && low <= open && low <= close
            && volume >= 0.0;
    }
    
    // Get typical price
    Price typical() const {
        return (high + low + close) / 3.0;
    }
    
    // Get HL range
    Price range() const {
        return high - low;
    }
    
    // Get body
    Price body() const {
        return std::abs(close - open);
    }
};

using CandleBuffer = std::vector<Candle>;

// ────────────────────────────────────────────────────────────────────────────
// FEATURE VECTOR (20 FEATURES)
// ────────────────────────────────────────────────────────────────────────────

struct alignas(64) FeatureVector {
    // TREND (4)
    FeatureValue ema_9_21_ratio;
    FeatureValue close_to_ema50_pct;
    FeatureValue linreg_slope_20;
    FeatureValue adx_14;
    
    // MOMENTUM (4)
    FeatureValue rsi_14;
    FeatureValue macd_hist_pct;
    FeatureValue stoch_rsi_k;
    FeatureValue cci_20_clamped;
    
    // VOLUME (3)
    FeatureValue volume_ratio_20;
    FeatureValue mfi_14;
    FeatureValue relative_volume_intraday;
    
    // VOLATILITY (3)
    FeatureValue atr_pct;
    FeatureValue bb_width_pct;
    FeatureValue bb_pct_b;
    
    // INSTITUTIONAL (3)
    FeatureValue vwap_distance_pct;
    FeatureValue vwap_zscore_20;
    FeatureValue cpr_width_pct;
    
    // MARKET STRUCTURE (3)
    FeatureValue bos_strength_pct;
    FeatureValue fvg_gap_pct;
    FeatureValue candle_body_ratio;
    
    // CONTEXT (3)
    FeatureValue nifty_direction;
    FeatureValue sector_strength_pct;
    FeatureValue daily_distance_ema50_pct;
    
    // SESSION (1)
    FeatureValue session_progress_pct;
    
    FeatureVector()
        : ema_9_21_ratio(1.0), close_to_ema50_pct(0.0), linreg_slope_20(0.0), adx_14(0.0),
          rsi_14(50.0), macd_hist_pct(0.0), stoch_rsi_k(0.5), cci_20_clamped(0.0),
          volume_ratio_20(1.0), mfi_14(50.0), relative_volume_intraday(1.0),
          atr_pct(0.0), bb_width_pct(0.0), bb_pct_b(0.5),
          vwap_distance_pct(0.0), vwap_zscore_20(0.0), cpr_width_pct(0.0),
          bos_strength_pct(0.0), fvg_gap_pct(0.0), candle_body_ratio(0.5),
          nifty_direction(0.0), sector_strength_pct(0.0), daily_distance_ema50_pct(0.0),
          session_progress_pct(0.0) {}
    
    // Get as array for model inference
    std::array<FeatureValue, 24> to_array() const {
        return {{
            ema_9_21_ratio, close_to_ema50_pct, linreg_slope_20, adx_14,
            rsi_14, macd_hist_pct, stoch_rsi_k, cci_20_clamped,
            volume_ratio_20, mfi_14, relative_volume_intraday,
            atr_pct, bb_width_pct, bb_pct_b,
            vwap_distance_pct, vwap_zscore_20, cpr_width_pct,
            bos_strength_pct, fvg_gap_pct, candle_body_ratio,
            nifty_direction, sector_strength_pct, daily_distance_ema50_pct,
            session_progress_pct
        }};
    }
    
    // Get feature by index
    FeatureValue get_feature(int index) const {
        if (index < 0 || index >= 24) return 0.0;
        auto arr = to_array();
        return arr[index];
    }
    
    // Validate all features are finite
    bool is_valid() const {
        auto arr = to_array();
        for (const auto& f : arr) {
            if (!std::isfinite(f)) return false;
        }
        return true;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// ROLLING WINDOW STATE (EFFICIENT INDICATOR COMPUTATION)
// ────────────────────────────────────────────────────────────────────────────

template<typename T, size_t Size>
class RollingWindow {
private:
    std::array<T, Size> buffer;
    size_t count = 0;
    size_t head = 0;
    
public:
    void push(T value) {
        assert(head < Size);
        assert(count <= Size);
        buffer[head] = value;
        head = (head + 1) % Size;
        if (count < Size) count++;
    }
    
    T get(int index) const {
        assert(index >= 0);
        assert(index < static_cast<int>(count));
        if (index < 0 || index >= static_cast<int>(count)) return T();
        int pos = (head - count + index + Size) % Size;
        assert(pos >= 0 && pos < static_cast<int>(Size));
        return buffer[pos];
    }
    
    T latest() const {
        assert(count <= Size);
        return count > 0 ? buffer[(head - 1 + Size) % Size] : T();
    }
    
    size_t size() const { return count; }
    bool is_full() const { return count == Size; }
    void clear() { count = 0; head = 0; }
};

// ────────────────────────────────────────────────────────────────────────────
// INDICATOR STATE (MAINTAIN ROLLING STATE FOR EFFICIENCY)
// ────────────────────────────────────────────────────────────────────────────

struct IndicatorState {
    // EMA state
    std::vector<double> ema_values;  // EMA history for different spans
    
    // RSI state
    double rsi_avg_gain = 0.0;
    double rsi_avg_loss = 0.0;
    
    // MACD state
    double macd_ema_12 = 0.0;
    double macd_ema_26 = 0.0;
    double macd_signal = 0.0;
    
    // ATR state
    double atr_value = 0.0;
    
    // ADX state
    std::vector<double> plus_dm, minus_dm, tr_values;
    double plus_di = 0.0;
    double minus_di = 0.0;
    double adx_value = 0.0;
    
    // Candle history
    RollingWindow<Candle, 50> candle_history;
};

// ────────────────────────────────────────────────────────────────────────────
// MULTI-TIMEFRAME DATA
// ────────────────────────────────────────────────────────────────────────────

struct MultiTimeframeData {
    CandleBuffer candles_5m;
    CandleBuffer candles_15m;
    CandleBuffer candles_daily;
    CandleBuffer nifty_candles;
    CandleBuffer sector_candles;
};

// ────────────────────────────────────────────────────────────────────────────
// COMPUTATION RESULT
// ────────────────────────────────────────────────────────────────────────────

enum class ComputationStatus {
    OK,
    INSUFFICIENT_DATA,
    INVALID_DATA,
    NAN_VALUES,
    COMPUTATION_ERROR
};

struct ComputationResult {
    FeatureVector features;
    ComputationStatus status;
    const char* error_message;
    
    bool is_ok() const { return status == ComputationStatus::OK; }
    
    ComputationResult() 
        : status(ComputationStatus::OK), error_message(nullptr) {}
    
    ComputationResult(const FeatureVector& f, ComputationStatus s, const char* msg = nullptr)
        : features(f), status(s), error_message(msg) {}
};

} // namespace stockai::cpp_engine

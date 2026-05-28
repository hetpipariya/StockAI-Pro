#pragma once

#include "../core/types.hpp"
#include "../core/math_utils.hpp"
#include "../core/constants.hpp"
#include <vector>
#include <cmath>

namespace stockai::cpp_engine {

// ────────────────────────────────────────────────────────────────────────────
// RSI (RELATIVE STRENGTH INDEX)
// ────────────────────────────────────────────────────────────────────────────

class RSIIndicator {
public:
    static double compute(const std::vector<double>& closes, int period = 14) {
        if (closes.size() < static_cast<size_t>(period + 1)) {
            return 50.0;  // Default neutral RSI
        }
        
        double avg_gain = 0.0;
        double avg_loss = 0.0;
        
        // First pass: calculate initial average gain/loss
        for (size_t i = 1; i <= static_cast<size_t>(period); ++i) {
            double change = closes[i] - closes[i - 1];
            if (change > 0) {
                avg_gain += change;
            } else {
                avg_loss += -change;
            }
        }
        avg_gain /= period;
        avg_loss /= period;
        
        // Smoothed RSI (Wilder's method)
        for (size_t i = period + 1; i < closes.size(); ++i) {
            double change = closes[i] - closes[i - 1];
            if (change > 0) {
                avg_gain = (avg_gain * (period - 1) + change) / period;
                avg_loss = (avg_loss * (period - 1)) / period;
            } else {
                avg_gain = (avg_gain * (period - 1)) / period;
                avg_loss = (avg_loss * (period - 1) + (-change)) / period;
            }
        }
        
        if (avg_loss < EPSILON) {
            return 100.0;  // All gains, no losses
        }
        
        double rs = safe_divide(avg_gain, avg_loss, 1.0);
        double rsi = 100.0 - (100.0 / (1.0 + rs));
        
        return clamp(rsi, 0.0, 100.0);
    }
};

// ────────────────────────────────────────────────────────────────────────────
// MACD (MOVING AVERAGE CONVERGENCE DIVERGENCE)
// ────────────────────────────────────────────────────────────────────────────

class MACDIndicator {
public:
    struct Result {
        double macd_line;
        double signal_line;
        double histogram;
    };
    
    static Result compute(const std::vector<double>& closes) {
        Result res{0.0, 0.0, 0.0};
        
        if (closes.size() < 26) {
            return res;
        }
        
        // Compute EMAs
        auto ema_12 = EMAIndicator::compute(closes, 12);
        auto ema_26 = EMAIndicator::compute(closes, 26);
        
        if (ema_12.empty() || ema_26.empty()) {
            return res;
        }
        
        // MACD line = EMA12 - EMA26
        res.macd_line = ema_12.back() - ema_26.back();
        
        // Build MACD history for signal line
        std::vector<double> macd_history;
        size_t len12 = ema_12.size();
        size_t len26 = ema_26.size();
        size_t offset = len12 > len26 ? len12 - len26 : 0;
        assert(len12 >= len26);
        for (size_t i = offset; i < len12; ++i) {
            size_t j = i - offset;
            if (j >= len26) {
                break;
            }
            macd_history.push_back(ema_12[i] - ema_26[j]);
        }
        
        // Signal line = EMA9 of MACD
        if (macd_history.size() >= 9) {
            auto signal = EMAIndicator::compute(macd_history, 9);
            res.signal_line = signal.back();
        } else {
            res.signal_line = res.macd_line;
        }
        
        res.histogram = res.macd_line - res.signal_line;
        
        return res;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// ROC (RATE OF CHANGE)
// ────────────────────────────────────────────────────────────────────────────

class ROCIndicator {
public:
    static double compute(const std::vector<double>& closes, int period = 10) {
        if (closes.size() < static_cast<size_t>(period + 1)) {
            return 0.0;
        }
        
        double current = closes.back();
        double previous = closes[closes.size() - period - 1];
        
        return compute_roc(current, previous);
    }
};

// ────────────────────────────────────────────────────────────────────────────
// CCI (COMMODITY CHANNEL INDEX)
// ────────────────────────────────────────────────────────────────────────────

class CCIIndicator {
public:
    static double compute(const CandleBuffer& candles, int period = 20) {
        if (candles.size() < static_cast<size_t>(period)) {
            return 0.0;
        }
        
        // Get typical prices
        std::vector<double> typical_prices;
        for (const auto& candle : candles) {
            typical_prices.push_back(candle.typical());
        }
        
        // SMA of typical prices
        double sma = 0.0;
        for (size_t i = typical_prices.size() - period; i < typical_prices.size(); ++i) {
            sma += typical_prices[i];
        }
        sma /= period;
        
        // Mean Absolute Deviation
        double mad = 0.0;
        for (size_t i = typical_prices.size() - period; i < typical_prices.size(); ++i) {
            mad += std::abs(typical_prices[i] - sma);
        }
        mad /= period;
        
        double current_tp = typical_prices.back();
        double cci = safe_divide(current_tp - sma, 0.015 * (mad + EPSILON), 0.0);
        
        return clamp(cci, -200.0, 200.0);
    }
};

// ────────────────────────────────────────────────────────────────────────────
// MOMENTUM FEATURES COMPUTER
// ────────────────────────────────────────────────────────────────────────────

class MomentumFeatures {
public:
    struct Result {
        double rsi_14;
        double macd_histogram;
        double roc_10;
        double cci_20;
    };
    
    static Result compute(const CandleBuffer& candles) {
        Result res{50.0, 0.0, 0.0, 0.0};
        
        if (candles.size() < 50) {
            return res;
        }
        
        // Extract closes
        std::vector<double> closes;
        for (const auto& candle : candles) {
            closes.push_back(candle.close);
        }
        
        // Compute RSI
        res.rsi_14 = RSIIndicator::compute(closes, 14);
        
        // Compute MACD
        auto macd = MACDIndicator::compute(closes);
        res.macd_histogram = macd.histogram;
        
        // Compute ROC
        res.roc_10 = ROCIndicator::compute(closes, 10);
        
        // Compute CCI
        res.cci_20 = CCIIndicator::compute(candles, 20);
        
        return res;
    }
};

} // namespace stockai::cpp_engine

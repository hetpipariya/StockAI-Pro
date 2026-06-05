#pragma once

#include "../core/types.hpp"
#include "../core/math_utils.hpp"
#include "../core/constants.hpp"
#include <vector>

namespace stockai::cpp_engine {

// ────────────────────────────────────────────────────────────────────────────
// EMA (EXPONENTIAL MOVING AVERAGE)
// ────────────────────────────────────────────────────────────────────────────

class EMAIndicator {
private:
    std::vector<double> values;
    int period;
    double multiplier;
    
public:
    EMAIndicator(int p = 9) : period(p) {
        multiplier = ema_multiplier(period);
    }
    
    // Add a single value (online computation)
    double add_value(double price) {
        if (values.empty()) {
            values.push_back(price);
            return price;
        }
        
        double new_ema = price * multiplier + values.back() * (1.0 - multiplier);
        values.push_back(new_ema);
        return new_ema;
    }
    
    // Compute from buffer
    static std::vector<double> compute(const std::vector<double>& prices, int period) {
        return compute_ema_series(prices, period);
    }
    
    // Compute single value given history
    static double compute_single(const std::vector<double>& prices, int period) {
        if (prices.empty()) {
            return 0.0;
        }
        auto ema_vals = compute(prices, period);
        return ema_vals.empty() ? prices.back() : ema_vals.back();
    }
    
    // Get latest
    double latest() const {
        return values.empty() ? 0.0 : values.back();
    }
    
    // Get history
    const std::vector<double>& get_values() const {
        return values;
    }
    
    // Clear history
    void reset() {
        values.clear();
    }
};

// ────────────────────────────────────────────────────────────────────────────
// LINEAR REGRESSION
// ────────────────────────────────────────────────────────────────────────────

class LinearRegressionIndicator {
public:
    // Compute slope for last 'period' bars
    static double compute_slope(const std::vector<double>& prices, int period) {
        if (prices.size() < static_cast<size_t>(period)) {
            return 0.0;
        }
        
        // Get last 'period' values
        std::vector<double> window(
            prices.end() - period,
            prices.end()
        );
        
        return linear_regression_slope(window);
    }
    
    // Normalize slope by current price (price-relative)
    static double compute_normalized_slope(const std::vector<double>& prices, int period) {
        if (prices.empty()) return 0.0;
        
        double slope = compute_slope(prices, period);
        double current_price = prices.back();
        
        return safe_divide(slope, current_price, 0.0);
    }
};

// ────────────────────────────────────────────────────────────────────────────
// TREND FEATURES COMPUTER
// ────────────────────────────────────────────────────────────────────────────

class TrendFeatures {
public:
    // Compute all 5 trend features from close prices
    struct Result {
        double ema_9;
        double ema_21;
        double ema_50;
        double ema_9_21_ratio;
        double linreg_slope_20;
    };
    
    static Result compute(const std::vector<double>& closes) {
        Result res{};
        
        if (closes.empty()) {
            res.ema_9 = 0.0;
            res.ema_21 = 0.0;
            res.ema_50 = 0.0;
            res.ema_9_21_ratio = 1.0;
            res.linreg_slope_20 = 0.0;
            return res;
        }

        if (closes.size() < 50) {
            // Not enough data
            double last_close = closes.back();
            res.ema_9 = last_close;
            res.ema_21 = last_close;
            res.ema_50 = last_close;
            res.ema_9_21_ratio = 1.0;
            res.linreg_slope_20 = 0.0;
            return res;
        }
        
        // Compute EMAs
        auto ema_9_vals = EMAIndicator::compute(closes, 9);
        auto ema_21_vals = EMAIndicator::compute(closes, 21);
        auto ema_50_vals = EMAIndicator::compute(closes, 50);
        
        res.ema_9 = ema_9_vals.back();
        res.ema_21 = ema_21_vals.back();
        res.ema_50 = ema_50_vals.back();
        
        // EMA ratio (trend alignment indicator)
        res.ema_9_21_ratio = safe_divide(res.ema_9, res.ema_21, 1.0);
        
        // Linear regression slope (normalized)
        res.linreg_slope_20 = LinearRegressionIndicator::compute_normalized_slope(closes, 20);
        
        return res;
    }
    
    // Fast version: use pre-computed EMAs from buffer
    static Result compute_fast(double ema9, double ema21, double ema50, const std::vector<double>& closes) {
        Result res{};
        res.ema_9 = ema9;
        res.ema_21 = ema21;
        res.ema_50 = ema50;
        res.ema_9_21_ratio = safe_divide(ema9, ema21, 1.0);
        res.linreg_slope_20 = LinearRegressionIndicator::compute_normalized_slope(closes, 20);
        return res;
    }
};

} // namespace stockai::cpp_engine

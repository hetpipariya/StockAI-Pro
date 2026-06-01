#pragma once

#include <cmath>
#include <algorithm>
#include <vector>
#include <numeric>

namespace stockai::cpp_engine {

// ────────────────────────────────────────────────────────────────────────────
// MATHEMATICAL CONSTANTS
// ────────────────────────────────────────────────────────────────────────────

constexpr double EPSILON = 1e-10;
constexpr double PI = 3.14159265358979323846;
constexpr double HALF_PI = 1.57079632679489661923;

// ────────────────────────────────────────────────────────────────────────────
// SAFE ARITHMETIC
// ────────────────────────────────────────────────────────────────────────────

inline double safe_divide(double numerator, double denominator, double fallback = 0.0) {
    if (std::abs(denominator) < EPSILON) {
        return fallback;
    }
    double result = numerator / denominator;
    if (!std::isfinite(result)) {
        return fallback;
    }
    return result;
}

inline double safe_log(double value, double fallback = 0.0) {
    if (value <= 0.0) return fallback;
    double result = std::log(value);
    return std::isfinite(result) ? result : fallback;
}

inline double safe_sqrt(double value, double fallback = 0.0) {
    if (value < 0.0) return fallback;
    double result = std::sqrt(value);
    return std::isfinite(result) ? result : fallback;
}

// ────────────────────────────────────────────────────────────────────────────
// CLAMPING & NORMALIZATION
// ────────────────────────────────────────────────────────────────────────────

inline double clamp(double value, double min_val, double max_val) {
    if (!std::isfinite(value)) return (min_val + max_val) / 2.0;
    return std::max(min_val, std::min(max_val, value));
}

inline double normalize_to_range(double value, double min_val, double max_val) {
    if (std::abs(max_val - min_val) < EPSILON) {
        return 0.5 * (min_val + max_val);
    }
    return (value - min_val) / (max_val - min_val);
}

inline double normalize_01(double value, double min_val, double max_val) {
    return normalize_to_range(value, min_val, max_val);
}

inline double denormalize(double normalized, double min_val, double max_val) {
    return min_val + normalized * (max_val - min_val);
}

// ────────────────────────────────────────────────────────────────────────────
// VECTORIZED OPERATIONS
// ────────────────────────────────────────────────────────────────────────────

template<typename T>
inline double sum(const std::vector<T>& values) {
    return std::accumulate(values.begin(), values.end(), 0.0);
}

template<typename T>
inline double mean(const std::vector<T>& values) {
    if (values.empty()) return 0.0;
    return sum(values) / static_cast<double>(values.size());
}

template<typename T>
inline double variance(const std::vector<T>& values) {
    if (values.size() < 2) return 0.0;
    double m = mean(values);
    double sum_sq_diff = 0.0;
    for (const auto& v : values) {
        double diff = v - m;
        sum_sq_diff += diff * diff;
    }
    return sum_sq_diff / static_cast<double>(values.size() - 1);
}

template<typename T>
inline double stddev(const std::vector<T>& values) {
    return safe_sqrt(variance(values));
}

template<typename T>
inline T min_element(const std::vector<T>& values) {
    if (values.empty()) return T();
    return *std::min_element(values.begin(), values.end());
}

template<typename T>
inline T max_element(const std::vector<T>& values) {
    if (values.empty()) return T();
    return *std::max_element(values.begin(), values.end());
}

// ────────────────────────────────────────────────────────────────────────────
// EMA (EXPONENTIAL MOVING AVERAGE)
// ────────────────────────────────────────────────────────────────────────────

inline double ema_multiplier(int period) {
    return 2.0 / (period + 1.0);
}

inline double compute_ema_single(double price, double prev_ema, int period) {
    double mult = ema_multiplier(period);
    return price * mult + prev_ema * (1.0 - mult);
}

inline std::vector<double> compute_ema_series(const std::vector<double>& prices, int period) {
    std::vector<double> ema;
    if (prices.empty()) return ema;
    
    double mult = ema_multiplier(period);
    
    // Initialize with SMA if enough data
    if (prices.size() >= static_cast<size_t>(period)) {
        double sma = sum(std::vector<double>(prices.begin(), prices.begin() + period)) / period;
        ema.push_back(sma);
        
        for (size_t i = period; i < prices.size(); ++i) {
            double new_ema = prices[i] * mult + ema.back() * (1.0 - mult);
            ema.push_back(new_ema);
        }
    } else {
        // Not enough data, use simple initialization
        double current_ema = prices[0];
        ema.push_back(current_ema);
        
        for (size_t i = 1; i < prices.size(); ++i) {
            current_ema = compute_ema_single(prices[i], current_ema, period);
            ema.push_back(current_ema);
        }
    }
    
    return ema;
}

// ────────────────────────────────────────────────────────────────────────────
// SMA (SIMPLE MOVING AVERAGE)
// ────────────────────────────────────────────────────────────────────────────

inline std::vector<double> compute_sma_series(const std::vector<double>& prices, int period) {
    std::vector<double> sma;
    if (prices.size() < static_cast<size_t>(period)) return sma;
    
    for (size_t i = period - 1; i < prices.size(); ++i) {
        double sum = 0.0;
        for (int j = 0; j < period; ++j) {
            sum += prices[i - j];
        }
        sma.push_back(sum / period);
    }
    
    return sma;
}

// ────────────────────────────────────────────────────────────────────────────
// ROC (RATE OF CHANGE)
// ────────────────────────────────────────────────────────────────────────────

inline double compute_roc(double current, double previous) {
    return safe_divide(current - previous, previous);
}

// ────────────────────────────────────────────────────────────────────────────
// LINEAR REGRESSION SLOPE
// ────────────────────────────────────────────────────────────────────────────

inline double linear_regression_slope(const std::vector<double>& y_values) {
    if (y_values.size() < 2) return 0.0;
    
    int n = y_values.size();
    double n_d = static_cast<double>(n);
    
    // x is [0, 1, 2, ..., n-1]
    // sum_x = 0 + 1 + ... + (n-1) = n*(n-1)/2
    double sum_x = n_d * (n_d - 1.0) / 2.0;
    double sum_x_sq = n_d * (n_d - 1.0) * (2.0 * n_d - 1.0) / 6.0;
    
    double sum_y = sum(y_values);
    double sum_xy = 0.0;
    
    for (int i = 0; i < n; ++i) {
        sum_xy += i * y_values[i];
    }
    
    double denominator = n_d * sum_x_sq - sum_x * sum_x;
    if (std::abs(denominator) < EPSILON) return 0.0;
    
    double slope = (n_d * sum_xy - sum_x * sum_y) / denominator;
    
    return std::isfinite(slope) ? slope : 0.0;
}

// ────────────────────────────────────────────────────────────────────────────
// TRUE RANGE (FOR ATR)
// ────────────────────────────────────────────────────────────────────────────

inline double compute_true_range(double high, double low, double prev_close) {
    double tr1 = high - low;
    double tr2 = std::abs(high - prev_close);
    double tr3 = std::abs(low - prev_close);
    return std::max({tr1, tr2, tr3});
}

// ────────────────────────────────────────────────────────────────────────────
// DIRECTIONAL MOVEMENT (FOR ADX)
// ────────────────────────────────────────────────────────────────────────────

inline void compute_directional_movement(double high, double low, double prev_high, double prev_low,
                                        double& plus_dm, double& minus_dm) {
    double up_move = high - prev_high;
    double down_move = prev_low - low;
    
    plus_dm = (up_move > down_move && up_move > 0) ? up_move : 0.0;
    minus_dm = (down_move > up_move && down_move > 0) ? down_move : 0.0;
}

// ────────────────────────────────────────────────────────────────────────────
// HIGHEST & LOWEST
// ────────────────────────────────────────────────────────────────────────────

inline double highest_high(const std::vector<double>& highs, int period) {
    if (highs.empty() || period <= 0) return 0.0;
    
    int start = std::max(0, static_cast<int>(highs.size()) - period);
    return *std::max_element(highs.begin() + start, highs.end());
}

inline double lowest_low(const std::vector<double>& lows, int period) {
    if (lows.empty() || period <= 0) return 0.0;
    
    int start = std::max(0, static_cast<int>(lows.size()) - period);
    return *std::min_element(lows.begin() + start, lows.end());
}

// ────────────────────────────────────────────────────────────────────────────
// CROSSOVER DETECTION
// ────────────────────────────────────────────────────────────────────────────

inline bool is_bullish_crossover(double prev_a, double prev_b, double curr_a, double curr_b) {
    return prev_a <= prev_b && curr_a > curr_b;
}

inline bool is_bearish_crossover(double prev_a, double prev_b, double curr_a, double curr_b) {
    return prev_a >= prev_b && curr_a < curr_b;
}

// ────────────────────────────────────────────────────────────────────────────
// VALIDATION
// ────────────────────────────────────────────────────────────────────────────

inline bool is_valid_price(double price) {
    return std::isfinite(price) && price > 0.0;
}

inline bool is_valid_value(double value) {
    return std::isfinite(value);
}

} // namespace stockai::cpp_engine

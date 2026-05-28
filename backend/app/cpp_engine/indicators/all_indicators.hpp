#pragma once

#include "../core/types.hpp"
#include "../core/math_utils.hpp"
#include "../core/constants.hpp"
#include "ema.hpp"
#include "momentum.hpp"
#include <vector>
#include <cmath>

namespace stockai::cpp_engine {

// ────────────────────────────────────────────────────────────────────────────
// VOLATILITY INDICATORS
// ────────────────────────────────────────────────────────────────────────────

class VolatilityFeatures {
public:
    struct Result {
        double atr_14;
        double bb_width_pct;
        double bb_pct_b;
    };
    
    static Result compute(const CandleBuffer& candles) {
        Result res{0.0, 0.0, 0.5};
        
        if (candles.size() < 20) {
            return res;
        }
        
        // ATR computation
        std::vector<double> tr_values;
        for (size_t i = 1; i < candles.size(); ++i) {
            double tr = compute_true_range(
                candles[i].high,
                candles[i].low,
                candles[i - 1].close
            );
            tr_values.push_back(tr);
        }
        
        // ATR = EMA of TR
        if (!tr_values.empty()) {
            auto atr_vals = EMAIndicator::compute(tr_values, 14);
            res.atr_14 = atr_vals.back();
        }
        
        // Bollinger Bands
        std::vector<double> closes;
        for (const auto& c : candles) {
            closes.push_back(c.close);
        }
        
        if (closes.size() >= 20) {
            std::vector<double> last_20_closes(
                closes.end() - 20,
                closes.end()
            );
            
            double sma_20 = mean(last_20_closes);
            double std_20 = stddev(last_20_closes);
            
            double bb_upper = sma_20 + BB_STDDEV_MULTIPLIER * std_20;
            double bb_lower = sma_20 - BB_STDDEV_MULTIPLIER * std_20;
            
            double current_close = closes.back();
            
            // BB Width %
            res.bb_width_pct = safe_divide(bb_upper - bb_lower, sma_20, 0.0);
            
            // BB %B (position in bands)
            double bb_range = bb_upper - bb_lower;
            if (std::abs(bb_range) > EPSILON) {
                res.bb_pct_b = (current_close - bb_lower) / bb_range;
                res.bb_pct_b = clamp(res.bb_pct_b, 0.0, 1.0);
            }
        }
        
        return res;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// VOLUME INDICATORS
// ────────────────────────────────────────────────────────────────────────────

class VolumeFeatures {
public:
    struct Result {
        double vwap_distance_pct;
        double volume_ratio_20;
        double mfi_14;
    };
    
    static Result compute(const CandleBuffer& candles) {
        Result res{0.0, 1.0, 50.0};
        
        if (candles.size() < 20) {
            return res;
        }
        
        // VWAP computation
        double cum_tp_vol = 0.0;
        double cum_vol = 0.0;
        for (const auto& c : candles) {
            double tp = c.typical();
            cum_tp_vol += tp * c.volume;
            cum_vol += c.volume;
        }
        
        double vwap = safe_divide(cum_tp_vol, cum_vol, candles.back().close);
        double current_close = candles.back().close;
        res.vwap_distance_pct = safe_divide(current_close - vwap, vwap, 0.0);
        
        // Volume ratio (current vs 20-bar average)
        double vol_sum = 0.0;
        for (size_t i = std::max(0, static_cast<int>(candles.size()) - 20);
             i < candles.size(); ++i) {
            vol_sum += candles[i].volume;
        }
        double avg_vol = vol_sum / 20.0;
        res.volume_ratio_20 = safe_divide(candles.back().volume, avg_vol, 1.0);
        
        // MFI (Money Flow Index) - simplified
        if (candles.size() >= 14) {
            double pos_mf = 0.0, neg_mf = 0.0;
            size_t start_idx = candles.size() - 14;
            if (start_idx == 0) {
                start_idx = 1;
            }
            for (size_t i = start_idx; i < candles.size(); ++i) {
                double tp = candles[i].typical();
                double prev_tp = candles[i - 1].typical();
                double mf = tp * candles[i].volume;
                
                if (tp > prev_tp) {
                    pos_mf += mf;
                } else {
                    neg_mf += mf;
                }
            }
            
            double mfi_ratio = safe_divide(pos_mf, neg_mf, 1.0);
            res.mfi_14 = 100.0 - (100.0 / (1.0 + mfi_ratio));
            res.mfi_14 = clamp(res.mfi_14, 0.0, 100.0);
        }
        
        return res;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// STRUCTURE INDICATORS
// ────────────────────────────────────────────────────────────────────────────

class StructureFeatures {
public:
    struct Result {
        double adx_14;
        double candle_body_ratio;
    };
    
    static Result compute(const CandleBuffer& candles) {
        Result res{0.0, 0.5};
        
        if (candles.size() < 14) {
            return res;
        }
        
        // ADX (Average Directional Index) - simplified
        std::vector<double> plus_dm_vals, minus_dm_vals, tr_vals;
        
        for (size_t i = 1; i < candles.size(); ++i) {
            double plus_dm, minus_dm;
            compute_directional_movement(
                candles[i].high, candles[i].low,
                candles[i - 1].high, candles[i - 1].low,
                plus_dm, minus_dm
            );
            
            plus_dm_vals.push_back(plus_dm);
            minus_dm_vals.push_back(minus_dm);
            
            double tr = compute_true_range(
                candles[i].high, candles[i].low,
                candles[i - 1].close
            );
            tr_vals.push_back(tr);
        }
        
        if (!tr_vals.empty() && tr_vals.size() >= 14) {
            // Compute DI+ and DI-
            double tr_sum = 0.0;
            double plus_sum = 0.0;
            double minus_sum = 0.0;
            
            for (size_t i = tr_vals.size() - 14; i < tr_vals.size(); ++i) {
                tr_sum += tr_vals[i];
                plus_sum += plus_dm_vals[i];
                minus_sum += minus_dm_vals[i];
            }
            
            double plus_di = safe_divide(plus_sum, tr_sum, 0.0) * 100.0;
            double minus_di = safe_divide(minus_sum, tr_sum, 0.0) * 100.0;
            
            double di_sum = plus_di + minus_di;
            double di_diff = std::abs(plus_di - minus_di);
            
            res.adx_14 = safe_divide(di_diff, di_sum, 0.0) * 100.0;
            res.adx_14 = clamp(res.adx_14, 0.0, 100.0);
        }
        
        // Candle body ratio (body / total range)
        if (candles.size() > 0) {
            const auto& c = candles.back();
            double body = c.body();
            double range = c.range();
            res.candle_body_ratio = safe_divide(body, range, 0.5);
            res.candle_body_ratio = clamp(res.candle_body_ratio, 0.0, 1.0);
        }
        
        return res;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// MULTI-TIMEFRAME FEATURES
// ────────────────────────────────────────────────────────────────────────────

class MultiTimeframeFeatures {
public:
    struct Result {
        double ema_direction_15m;
        double ema50_alignment_daily;
    };
    
    static Result compute(const MultiTimeframeData& mtf_data) {
        Result res{0.0, 0.0};
        
        // 15m EMA direction
        if (mtf_data.candles_15m.size() >= 50) {
            std::vector<double> closes_15m;
            for (const auto& c : mtf_data.candles_15m) {
                closes_15m.push_back(c.close);
            }
            
            auto ema9 = EMAIndicator::compute(closes_15m, 9);
            auto ema21 = EMAIndicator::compute(closes_15m, 21);
            
            if (!ema9.empty() && !ema21.empty()) {
                double last_close = closes_15m.back();
                // Direction: 1 if EMA9 > EMA21 (bull), -1 if below
                res.ema_direction_15m = (ema9.back() > ema21.back()) ? 1.0 : -1.0;
            }
        }
        
        // Daily EMA50 alignment
        if (mtf_data.candles_daily.size() >= 50) {
            std::vector<double> closes_daily;
            for (const auto& c : mtf_data.candles_daily) {
                closes_daily.push_back(c.close);
            }
            
            auto ema50_daily = EMAIndicator::compute(closes_daily, 50);
            
            if (!ema50_daily.empty()) {
                double last_close = closes_daily.back();
                // Alignment: 1 if above EMA50, -1 if below
                res.ema50_alignment_daily = (last_close > ema50_daily.back()) ? 1.0 : -1.0;
            }
        }
        
        return res;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// MARKET CONTEXT
// ────────────────────────────────────────────────────────────────────────────

class MarketContext {
public:
    static double compute_nifty_direction(const CandleBuffer& nifty_candles) {
        if (nifty_candles.size() < 50) {
            return 0.0;
        }
        
        std::vector<double> closes;
        for (const auto& c : nifty_candles) {
            closes.push_back(c.close);
        }
        
        auto ema_9 = EMAIndicator::compute(closes, 9);
        auto ema_21 = EMAIndicator::compute(closes, 21);
        
        if (ema_9.empty() || ema_21.empty()) {
            return 0.0;
        }
        
        // Direction: 1 if bullish, -1 if bearish
        return (ema_9.back() > ema_21.back()) ? 1.0 : -1.0;
    }
};

} // namespace stockai::cpp_engine

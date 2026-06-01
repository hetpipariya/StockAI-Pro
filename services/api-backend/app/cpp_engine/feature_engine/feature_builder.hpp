#pragma once

#include "../core/types.hpp"
#include "../core/math_utils.hpp"
#include "../core/constants.hpp"
#include "../indicators/all_indicators.hpp"
#include <vector>

namespace stockai::cpp_engine {

static bool validate_candle_buffer(const CandleBuffer& candles) {
    for (const auto& candle : candles) {
        if (!candle.is_valid()) {
            return false;
        }
    }
    return true;
}

static ComputationResult invalid_data_result(const FeatureVector& features, const char* message) {
    return ComputationResult(features, ComputationStatus::INVALID_DATA, message);
}

// ────────────────────────────────────────────────────────────────────────────
// FEATURE BUILDER - MAIN ORCHESTRATOR
// ────────────────────────────────────────────────────────────────────────────

class FeatureBuilder {
public:
    // Main entry point: compute all 20 features
    static ComputationResult compute_features(const MultiTimeframeData& mtf_data) {
        FeatureVector features;
        
        // Validate input
        if (mtf_data.candles_5m.empty()) {
            return ComputationResult(features, ComputationStatus::INSUFFICIENT_DATA, 
                                    "No 5m candles provided");
        }
        
        if (mtf_data.candles_5m.size() < MIN_CANDLES_FOR_FEATURES) {
            return ComputationResult(features, ComputationStatus::INSUFFICIENT_DATA,
                                    "Insufficient 5m candles for feature computation");
        }
        
        try {
            // Validate all input candle buffers
            if (!validate_candle_buffer(mtf_data.candles_5m)) {
                return invalid_data_result(features, "Invalid 5m candle data");
            }
            if (!mtf_data.candles_15m.empty() && !validate_candle_buffer(mtf_data.candles_15m)) {
                return invalid_data_result(features, "Invalid 15m candle data");
            }
            if (!mtf_data.candles_daily.empty() && !validate_candle_buffer(mtf_data.candles_daily)) {
                return invalid_data_result(features, "Invalid daily candle data");
            }
            if (!mtf_data.nifty_candles.empty() && !validate_candle_buffer(mtf_data.nifty_candles)) {
                return invalid_data_result(features, "Invalid nifty candle data");
            }
            
            // Extract closes from 5m candles
            std::vector<double> closes_5m;
            closes_5m.reserve(mtf_data.candles_5m.size());
            for (const auto& c : mtf_data.candles_5m) {
                closes_5m.push_back(c.close);
            }
            
            // ─── TREND FEATURES (5) ───
            auto trend_res = TrendFeatures::compute(closes_5m);
            features.ema_9 = trend_res.ema_9;
            features.ema_21 = trend_res.ema_21;
            features.ema_50 = trend_res.ema_50;
            features.ema_9_21_ratio = trend_res.ema_9_21_ratio;
            features.linreg_slope_20 = trend_res.linreg_slope_20;
            
            // ─── MOMENTUM FEATURES (4) ───
            auto mom_res = MomentumFeatures::compute(mtf_data.candles_5m);
            features.rsi_14 = mom_res.rsi_14;
            features.macd_histogram = mom_res.macd_histogram;
            features.roc_10 = mom_res.roc_10;
            features.cci_20 = mom_res.cci_20;
            
            // ─── VOLUME FEATURES (3) ───
            auto vol_res = VolumeFeatures::compute(mtf_data.candles_5m);
            features.vwap_distance_pct = vol_res.vwap_distance_pct;
            features.volume_ratio_20 = vol_res.volume_ratio_20;
            features.mfi_14 = vol_res.mfi_14;
            
            // ─── VOLATILITY FEATURES (3) ───
            auto vol_features = VolatilityFeatures::compute(mtf_data.candles_5m);
            features.atr_14 = vol_features.atr_14;
            features.bb_width_pct = vol_features.bb_width_pct;
            features.bb_pct_b = vol_features.bb_pct_b;
            
            // ─── STRUCTURE FEATURES (2) ───
            auto struct_res = StructureFeatures::compute(mtf_data.candles_5m);
            features.adx_14 = struct_res.adx_14;
            features.candle_body_ratio = struct_res.candle_body_ratio;
            
            // ─── MULTI-TIMEFRAME FEATURES (2) ───
            auto mtf_res = MultiTimeframeFeatures::compute(mtf_data);
            features.ema_direction_15m = mtf_res.ema_direction_15m;
            features.ema50_alignment_daily = mtf_res.ema50_alignment_daily;
            
            // ─── MARKET CONTEXT (1) ───
            if (!mtf_data.nifty_candles.empty()) {
                features.nifty_direction = MarketContext::compute_nifty_direction(mtf_data.nifty_candles);
            } else {
                features.nifty_direction = 0.0;
            }
            
            // Validate final feature vector
            if (!features.is_valid()) {
                auto validated = features.to_array();
                for (int idx = 0; idx < static_cast<int>(validated.size()); ++idx) {
                    if (!std::isfinite(validated[idx])) {
                        return ComputationResult(features, ComputationStatus::NAN_VALUES,
                            FEATURE_NAMES[idx]);
                    }
                }
                return ComputationResult(features, ComputationStatus::NAN_VALUES,
                                        "Feature computation resulted in NaN values");
            }
            
            return ComputationResult(features, ComputationStatus::OK);
            
        } catch (const std::exception& e) {
            return ComputationResult(features, ComputationStatus::COMPUTATION_ERROR,
                                    e.what());
        }
    }
    
    // Fast batch compute for multiple symbols
    static std::vector<ComputationResult> compute_batch_features(
        const std::vector<MultiTimeframeData>& batch_data) {
        std::vector<ComputationResult> results;
        
        for (const auto& mtf_data : batch_data) {
            results.push_back(compute_features(mtf_data));
        }
        
        return results;
    }
    
    // Validate a feature vector
    static bool validate_feature_vector(const FeatureVector& features) {
        if (!features.is_valid()) {
            return false;
        }
        
        // Check for reasonable ranges
        if (std::abs(features.ema_9_21_ratio - 1.0) > 0.5) {
            return false;  // EMA ratio should be close to 1.0
        }
        
        if (features.rsi_14 < 0.0 || features.rsi_14 > 100.0) {
            return false;
        }
        
        if (features.adx_14 < 0.0 || features.adx_14 > 100.0) {
            return false;
        }
        
        if (features.mfi_14 < 0.0 || features.mfi_14 > 100.0) {
            return false;
        }
        
        if (features.bb_pct_b < 0.0 || features.bb_pct_b > 1.0) {
            return false;
        }
        
        return true;
    }
};

} // namespace stockai::cpp_engine

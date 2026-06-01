#pragma once

#include "../core/types.hpp"
#include "../core/math_utils.hpp"
#include "../core/constants.hpp"
#include "../indicators/all_indicators.hpp"
#include <vector>
#include <exception>

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
    // Main entry point: compute all 24 features
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
            if (!mtf_data.sector_candles.empty() && !validate_candle_buffer(mtf_data.sector_candles)) {
                return invalid_data_result(features, "Invalid sector candle data");
            }
            
            // ─── TREND FEATURES (4) ───
            auto trend_res = TrendFeatures::compute(mtf_data.candles_5m);
            features.ema_9_21_ratio = trend_res.ema_9_21_ratio;
            features.close_to_ema50_pct = trend_res.close_to_ema50_pct;
            features.linreg_slope_20 = trend_res.linreg_slope_20;
            features.adx_14 = trend_res.adx_14;
            
            // ─── MOMENTUM FEATURES (4) ───
            auto mom_res = MomentumFeatures::compute(mtf_data.candles_5m);
            features.rsi_14 = mom_res.rsi_14;
            features.macd_hist_pct = mom_res.macd_hist_pct;
            features.stoch_rsi_k = mom_res.stoch_rsi_k;
            features.cci_20_clamped = mom_res.cci_20_clamped;
            
            // ─── VOLUME FEATURES (3) ───
            auto vol_res = VolumeFeatures::compute(mtf_data.candles_5m);
            features.volume_ratio_20 = vol_res.volume_ratio_20;
            features.mfi_14 = vol_res.mfi_14;
            features.relative_volume_intraday = vol_res.relative_volume_intraday;
            
            // ─── VOLATILITY FEATURES (3) ───
            auto volat_res = VolatilityFeatures::compute(mtf_data.candles_5m);
            features.atr_pct = volat_res.atr_pct;
            features.bb_width_pct = volat_res.bb_width_pct;
            features.bb_pct_b = volat_res.bb_pct_b;
            
            // ─── INSTITUTIONAL FEATURES (3) ───
            auto inst_res = InstitutionalFeatures::compute(mtf_data.candles_5m, mtf_data.candles_daily);
            features.vwap_distance_pct = inst_res.vwap_distance_pct;
            features.vwap_zscore_20 = inst_res.vwap_zscore_20;
            features.cpr_width_pct = inst_res.cpr_width_pct;
            
            // ─── MARKET STRUCTURE (3) ───
            auto struct_res = MarketStructureFeatures::compute(mtf_data.candles_5m);
            features.bos_strength_pct = struct_res.bos_strength_pct;
            features.fvg_gap_pct = struct_res.fvg_gap_pct;
            features.candle_body_ratio = struct_res.candle_body_ratio;
            
            // ─── CONTEXT FEATURES (3) ───
            auto context_res = ContextFeatures::compute(mtf_data);
            features.nifty_direction = context_res.nifty_direction;
            features.sector_strength_pct = context_res.sector_strength_pct;
            features.daily_distance_ema50_pct = context_res.daily_distance_ema50_pct;
            
            // ─── SESSION (1) ───
            features.session_progress_pct = SessionFeatures::compute_progress(mtf_data.candles_5m);
            
            // Validate final feature vector for NaNs or infinites
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
        results.reserve(batch_data.size());
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
        
        if (features.stoch_rsi_k < 0.0 || features.stoch_rsi_k > 1.0) {
            return false;
        }
        
        if (features.cci_20_clamped < -250.0 || features.cci_20_clamped > 250.0) {
            return false;
        }
        
        if (features.candle_body_ratio < 0.0 || features.candle_body_ratio > 1.0) {
            return false;
        }
        
        if (features.session_progress_pct < 0.0 || features.session_progress_pct > 1.0) {
            return false;
        }
        
        return true;
    }
};

} // namespace stockai::cpp_engine

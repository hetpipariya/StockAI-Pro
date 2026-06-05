#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>
#include <vector>
#include <cassert>
#include <pybind11/numpy.h>
#include <numpy/arrayobject.h>

#include "../core/types.hpp"
#include "../core/constants.hpp"
#include "../feature_engine/feature_builder.hpp"

namespace py = pybind11;
using namespace stockai::cpp_engine;

static void ensure_buffer_1d(const py::buffer_info& buf, const char* name) {
    if (buf.ndim != 1) {
        throw std::runtime_error(std::string(name) + " must be a 1D array");
    }
    if (buf.ptr == nullptr) {
        throw std::runtime_error(std::string(name) + " contains no data");
    }
}

static void ensure_same_length(const py::buffer_info& a, const py::buffer_info& b,
                               const char* a_name, const char* b_name) {
    if (a.size != b.size) {
        throw std::runtime_error(std::string(a_name) + " and " + b_name + " must have the same length");
    }
}

static bool validate_double_buffer(const double* ptr, size_t len) {
    for (size_t i = 0; i < len; ++i) {
        if (!std::isfinite(ptr[i])) {
            return false;
        }
    }
    return true;
}

static CandleBuffer build_close_only_candles(const py::array_t<double>& close_array, const char* label) {
    CandleBuffer candles;
    if (close_array.size() == 0) {
        return candles;
    }

    auto buf = close_array.request();
    ensure_buffer_1d(buf, label);
    if (!validate_double_buffer(static_cast<double*>(buf.ptr), buf.size)) {
        throw std::runtime_error(std::string(label) + " contains invalid numeric values");
    }

    auto ptr = static_cast<double*>(buf.ptr);
    candles.reserve(buf.size);
    for (size_t i = 0; i < buf.size; ++i) {
        candles.emplace_back(static_cast<int64_t>(i), ptr[i], ptr[i], ptr[i], ptr[i], 0.0);
    }
    return candles;
}

static CandleBuffer build_ohlc_candles(
    const py::array_t<double>& open_arr,
    const py::array_t<double>& high_arr,
    const py::array_t<double>& low_arr,
    const py::array_t<double>& close_arr,
    const char* label) {
    
    CandleBuffer candles;
    if (close_arr.size() == 0) {
        return candles;
    }
    
    auto buf_open = open_arr.request();
    auto buf_high = high_arr.request();
    auto buf_low = low_arr.request();
    auto buf_close = close_arr.request();
    
    ensure_buffer_1d(buf_open, "open_daily");
    ensure_buffer_1d(buf_high, "high_daily");
    ensure_buffer_1d(buf_low, "low_daily");
    ensure_buffer_1d(buf_close, "close_daily");
    
    ensure_same_length(buf_open, buf_high, "open_daily", "high_daily");
    ensure_same_length(buf_open, buf_low, "open_daily", "low_daily");
    ensure_same_length(buf_open, buf_close, "open_daily", "close_daily");
    
    auto ptr_open = static_cast<double*>(buf_open.ptr);
    auto ptr_high = static_cast<double*>(buf_high.ptr);
    auto ptr_low = static_cast<double*>(buf_low.ptr);
    auto ptr_close = static_cast<double*>(buf_close.ptr);
    
    size_t size = buf_close.size;
    candles.reserve(size);
    for (size_t i = 0; i < size; ++i) {
        candles.emplace_back(static_cast<int64_t>(i), ptr_open[i], ptr_high[i], ptr_low[i], ptr_close[i], 0.0);
    }
    return candles;
}

// ────────────────────────────────────────────────────────────────────────────
// PYTHON WRAPPER FOR FEATURE COMPUTATION
// ────────────────────────────────────────────────────────────────────────────

class PythonFeatureWrapper {
public:
    // Compute features from Python arrays
    static py::dict compute_all_features(
        py::array_t<double> open_5m,
        py::array_t<double> high_5m,
        py::array_t<double> low_5m,
        py::array_t<double> close_5m,
        py::array_t<double> volume_5m,
        py::array_t<double> close_15m = py::array_t<double>(),
        py::array_t<double> open_daily = py::array_t<double>(),
        py::array_t<double> high_daily = py::array_t<double>(),
        py::array_t<double> low_daily = py::array_t<double>(),
        py::array_t<double> close_daily = py::array_t<double>(),
        py::array_t<double> close_nifty = py::array_t<double>(),
        py::array_t<double> close_sector = py::array_t<double>()) {
        
        try {
            // Get buffer info
            auto buf_open = open_5m.request();
            auto buf_high = high_5m.request();
            auto buf_low = low_5m.request();
            auto buf_close = close_5m.request();
            auto buf_volume = volume_5m.request();

            ensure_buffer_1d(buf_open, "open_5m");
            ensure_buffer_1d(buf_high, "high_5m");
            ensure_buffer_1d(buf_low, "low_5m");
            ensure_buffer_1d(buf_close, "close_5m");
            ensure_buffer_1d(buf_volume, "volume_5m");

            ensure_same_length(buf_open, buf_high, "open_5m", "high_5m");
            ensure_same_length(buf_open, buf_low, "open_5m", "low_5m");
            ensure_same_length(buf_open, buf_close, "open_5m", "close_5m");
            ensure_same_length(buf_open, buf_volume, "open_5m", "volume_5m");
            
            if (!validate_double_buffer(static_cast<double*>(buf_open.ptr), buf_open.size)
                || !validate_double_buffer(static_cast<double*>(buf_high.ptr), buf_high.size)
                || !validate_double_buffer(static_cast<double*>(buf_low.ptr), buf_low.size)
                || !validate_double_buffer(static_cast<double*>(buf_close.ptr), buf_close.size)
                || !validate_double_buffer(static_cast<double*>(buf_volume.ptr), buf_volume.size)) {
                throw std::runtime_error("5m OHLCV data contains invalid values");
            }

            auto ptr_open = static_cast<double*>(buf_open.ptr);
            auto ptr_high = static_cast<double*>(buf_high.ptr);
            auto ptr_low = static_cast<double*>(buf_low.ptr);
            auto ptr_close = static_cast<double*>(buf_close.ptr);
            auto ptr_volume = static_cast<double*>(buf_volume.ptr);
            
            size_t len_5m = buf_close.size;
            
            // Build candle buffer for 5m
            CandleBuffer candles_5m;
            candles_5m.reserve(len_5m);
            for (size_t i = 0; i < len_5m; ++i) {
                Candle c(
                    static_cast<int64_t>(i),  // timestamp placeholder
                    ptr_open[i],
                    ptr_high[i],
                    ptr_low[i],
                    ptr_close[i],
                    ptr_volume[i]
                );
                candles_5m.push_back(c);
            }
            
            // Build other candles if provided
            CandleBuffer candles_15m = build_close_only_candles(close_15m, "close_15m");
            CandleBuffer candles_daily;
            if (open_daily.size() > 0 && high_daily.size() > 0 && low_daily.size() > 0 && close_daily.size() > 0) {
                candles_daily = build_ohlc_candles(open_daily, high_daily, low_daily, close_daily, "daily");
            } else if (close_daily.size() > 0) {
                candles_daily = build_close_only_candles(close_daily, "close_daily");
            }
            CandleBuffer nifty_candles = build_close_only_candles(close_nifty, "close_nifty");
            CandleBuffer sector_candles = build_close_only_candles(close_sector, "close_sector");
            
            // Prepare multi-timeframe data
            MultiTimeframeData mtf_data;
            mtf_data.candles_5m = candles_5m;
            mtf_data.candles_15m = candles_15m;
            mtf_data.candles_daily = candles_daily;
            mtf_data.nifty_candles = nifty_candles;
            mtf_data.sector_candles = sector_candles;
            
            // Compute features
            auto result = FeatureBuilder::compute_features(mtf_data);
            
            // Return as dictionary
            py::dict output;
            output["status"] = static_cast<int>(result.status);
            output["error_message"] = result.error_message ? std::string(result.error_message) : "";
            
            if (result.is_ok()) {
                py::dict features;
                auto fv = result.features;
                
                // TREND (4)
                features["ema_9_21_ratio"] = fv.ema_9_21_ratio;
                features["close_to_ema50_pct"] = fv.close_to_ema50_pct;
                features["linreg_slope_20"] = fv.linreg_slope_20;
                features["adx_14"] = fv.adx_14;
                
                // MOMENTUM (4)
                features["rsi_14"] = fv.rsi_14;
                features["macd_hist_pct"] = fv.macd_hist_pct;
                features["stoch_rsi_k"] = fv.stoch_rsi_k;
                features["cci_20_clamped"] = fv.cci_20_clamped;
                
                // VOLUME (3)
                features["volume_ratio_20"] = fv.volume_ratio_20;
                features["mfi_14"] = fv.mfi_14;
                features["relative_volume_intraday"] = fv.relative_volume_intraday;
                
                // VOLATILITY (3)
                features["atr_pct"] = fv.atr_pct;
                features["bb_width_pct"] = fv.bb_width_pct;
                features["bb_pct_b"] = fv.bb_pct_b;
                
                // INSTITUTIONAL (3)
                features["vwap_distance_pct"] = fv.vwap_distance_pct;
                features["vwap_zscore_20"] = fv.vwap_zscore_20;
                features["cpr_width_pct"] = fv.cpr_width_pct;
                
                // MARKET STRUCTURE (3)
                features["bos_strength_pct"] = fv.bos_strength_pct;
                features["fvg_gap_pct"] = fv.fvg_gap_pct;
                features["candle_body_ratio"] = fv.candle_body_ratio;
                
                // CONTEXT (3)
                features["nifty_direction"] = fv.nifty_direction;
                features["sector_strength_pct"] = fv.sector_strength_pct;
                features["daily_distance_ema50_pct"] = fv.daily_distance_ema50_pct;
                
                // SESSION (1)
                features["session_progress_pct"] = fv.session_progress_pct;
                
                output["features"] = features;
            }
            
            return output;
            
        } catch (const std::exception& e) {
            py::dict error;
            error["status"] = static_cast<int>(ComputationStatus::COMPUTATION_ERROR);
            error["error_message"] = std::string(e.what());
            return error;
        }
    }
    
    // Get feature names
    static py::list get_feature_names() {
        py::list names;
        for (int i = 0; i < TOTAL_FEATURE_COUNT; ++i) {
            names.append(py::str(FEATURE_NAMES[i]));
        }
        return names;
    }
    
    // Get feature count
    static int get_feature_count() {
        return TOTAL_FEATURE_COUNT;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// MODULE DEFINITION
// ────────────────────────────────────────────────────────────────────────────

PYBIND11_MODULE(stockai_cpp_engine, m) {
    m.doc() = "StockAI Pro C++ Feature Engineering Engine";
    
    // Main feature computation function
    m.def("compute_all_features", &PythonFeatureWrapper::compute_all_features,
          py::arg("open_5m"),
          py::arg("high_5m"),
          py::arg("low_5m"),
          py::arg("close_5m"),
          py::arg("volume_5m"),
          py::arg("close_15m") = py::array_t<double>(),
          py::arg("open_daily") = py::array_t<double>(),
          py::arg("high_daily") = py::array_t<double>(),
          py::arg("low_daily") = py::array_t<double>(),
          py::arg("close_daily") = py::array_t<double>(),
          py::arg("close_nifty") = py::array_t<double>(),
          py::arg("close_sector") = py::array_t<double>(),
          "Compute all 24 production features from OHLCV and context data");
    
    m.def("get_feature_names", &PythonFeatureWrapper::get_feature_names,
          "Get list of 24 feature names");
    
    m.def("get_feature_count", &PythonFeatureWrapper::get_feature_count,
          "Get total feature count (24)");
    
    // Constants
    m.attr("MIN_CANDLES_FOR_FEATURES") = MIN_CANDLES_FOR_FEATURES;
    m.attr("FEATURE_VERSION") = FEATURE_VERSION;
    m.attr("TOTAL_FEATURE_COUNT") = TOTAL_FEATURE_COUNT;
    
    // Enums
    py::enum_<ComputationStatus>(m, "ComputationStatus")
        .value("OK", ComputationStatus::OK)
        .value("INSUFFICIENT_DATA", ComputationStatus::INSUFFICIENT_DATA)
        .value("INVALID_DATA", ComputationStatus::INVALID_DATA)
        .value("NAN_VALUES", ComputationStatus::NAN_VALUES)
        .value("COMPUTATION_ERROR", ComputationStatus::COMPUTATION_ERROR);
}

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
        py::array_t<double> close_daily = py::array_t<double>(),
        py::array_t<double> close_nifty = py::array_t<double>()) {
        
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
            
            // Build 15m candles if provided
            CandleBuffer candles_15m = build_close_only_candles(close_15m, "close_15m");
            
            // Build daily candles if provided
            CandleBuffer candles_daily = build_close_only_candles(close_daily, "close_daily");
            
            // Build NIFTY candles if provided
            CandleBuffer nifty_candles = build_close_only_candles(close_nifty, "close_nifty");
            
            // Prepare multi-timeframe data
            MultiTimeframeData mtf_data;
            mtf_data.candles_5m = candles_5m;
            mtf_data.candles_15m = candles_15m;
            mtf_data.candles_daily = candles_daily;
            mtf_data.nifty_candles = nifty_candles;
            
            // Compute features
            auto result = FeatureBuilder::compute_features(mtf_data);
            
            // Return as dictionary
            py::dict output;
            output["status"] = static_cast<int>(result.status);
            output["error_message"] = result.error_message ? std::string(result.error_message) : "";
            
            if (result.is_ok()) {
                py::dict features;
                auto fv = result.features;
                
                // TREND (5)
                features["ema_9"] = fv.ema_9;
                features["ema_21"] = fv.ema_21;
                features["ema_50"] = fv.ema_50;
                features["ema_9_21_ratio"] = fv.ema_9_21_ratio;
                features["linreg_slope_20"] = fv.linreg_slope_20;
                
                // MOMENTUM (4)
                features["rsi_14"] = fv.rsi_14;
                features["macd_histogram"] = fv.macd_histogram;
                features["roc_10"] = fv.roc_10;
                features["cci_20"] = fv.cci_20;
                
                // VOLUME (3)
                features["vwap_distance_pct"] = fv.vwap_distance_pct;
                features["volume_ratio_20"] = fv.volume_ratio_20;
                features["mfi_14"] = fv.mfi_14;
                
                // VOLATILITY (3)
                features["atr_14"] = fv.atr_14;
                features["bb_width_pct"] = fv.bb_width_pct;
                features["bb_pct_b"] = fv.bb_pct_b;
                
                // STRUCTURE (2)
                features["adx_14"] = fv.adx_14;
                features["candle_body_ratio"] = fv.candle_body_ratio;
                
                // MULTI-TIMEFRAME (2)
                features["ema_direction_15m"] = fv.ema_direction_15m;
                features["ema50_alignment_daily"] = fv.ema50_alignment_daily;
                
                // CONTEXT (1)
                features["nifty_direction"] = fv.nifty_direction;
                
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
          py::arg("close_daily") = py::array_t<double>(),
          py::arg("close_nifty") = py::array_t<double>(),
          "Compute all 20 production features from OHLCV data");
    
    m.def("get_feature_names", &PythonFeatureWrapper::get_feature_names,
          "Get list of 20 feature names");
    
    m.def("get_feature_count", &PythonFeatureWrapper::get_feature_count,
          "Get total feature count (20)");
    
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

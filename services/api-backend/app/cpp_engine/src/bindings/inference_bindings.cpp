#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include "../core/feature_pipeline.hpp"
#include "../core/feature_vector.hpp"

namespace py = pybind11;

using namespace stockai::core;
using namespace stockai::features;

// Helper to convert numpy arrays to vector of Candles
std::vector<Candle> numpy_to_candles(
    py::array_t<double> open,
    py::array_t<double> high,
    py::array_t<double> low,
    py::array_t<double> close,
    py::array_t<double> volume
) {
    auto buf_open = open.request();
    auto buf_high = high.request();
    auto buf_low = low.request();
    auto buf_close = close.request();
    auto buf_volume = volume.request();
    
    // Assume all have same length
    size_t len = buf_close.size;
    std::vector<Candle> candles(len);
    
    double* ptr_open = static_cast<double*>(buf_open.ptr);
    double* ptr_high = static_cast<double*>(buf_high.ptr);
    double* ptr_low = static_cast<double*>(buf_low.ptr);
    double* ptr_close = static_cast<double*>(buf_close.ptr);
    double* ptr_volume = static_cast<double*>(buf_volume.ptr);
    
    for (size_t i = 0; i < len; ++i) {
        candles[i].open = ptr_open[i];
        candles[i].high = ptr_high[i];
        candles[i].low = ptr_low[i];
        candles[i].close = ptr_close[i];
        candles[i].volume = ptr_volume[i];
        candles[i].vwap = 0.0; // Needs to be calculated or passed
    }
    return candles;
}

std::vector<double> compute_features_bridge(
    py::array_t<double> open_5m,
    py::array_t<double> high_5m,
    py::array_t<double> low_5m,
    py::array_t<double> close_5m,
    py::array_t<double> volume_5m,
    py::array_t<double> open_15m, // placeholders for MTF
    py::array_t<double> close_15m,
    py::array_t<double> close_daily,
    py::array_t<double> close_nifty
) {
    std::vector<Candle> c_5m = numpy_to_candles(open_5m, high_5m, low_5m, close_5m, volume_5m);
    
    // In actual implementation, we'd also convert 15m, daily, nifty arrays
    std::vector<Candle> c_15m; 
    std::vector<Candle> c_daily;
    std::vector<Candle> c_nifty;

    FeaturePipeline pipeline;
    FeatureVector vec = pipeline.compute(c_5m, c_15m, c_daily, c_nifty);
    
    return vec.values;
}

PYBIND11_MODULE(stockai_cpp_engine, m) {
    m.doc() = "Ultra-high-performance C++ feature engineering engine";
    
    m.def("compute_features", &compute_features_bridge, "Compute finalized 20 feature vector in C++",
          py::arg("open_5m"), py::arg("high_5m"), py::arg("low_5m"), py::arg("close_5m"), py::arg("volume_5m"),
          py::arg("open_15m") = py::array_t<double>(), py::arg("close_15m") = py::array_t<double>(),
          py::arg("close_daily") = py::array_t<double>(), py::arg("close_nifty") = py::array_t<double>());
          
    m.def("get_feature_names", &FeatureVector::get_feature_names, "Get finalized fixed-order feature names");
}

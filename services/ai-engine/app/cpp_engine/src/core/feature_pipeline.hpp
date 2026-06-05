#pragma once

#include <vector>
#include <cmath>
#include <stdexcept>
#include "feature_vector.hpp"

namespace stockai {
namespace core {

struct Candle {
    double open;
    double high;
    double low;
    double close;
    double volume;
    double vwap; // pre-computed or passed
    bool is_valid() const {
        return !std::isnan(close) && !std::isinf(close);
    }
};

class FeaturePipeline {
public:
    FeaturePipeline() = default;

    // The single entry point required by the new architecture
    // Output should be safe, no NaNs
    features::FeatureVector compute(
        const std::vector<Candle>& candles_5m,
        const std::vector<Candle>& candles_15m,
        const std::vector<Candle>& candles_daily,
        const std::vector<Candle>& nifty_daily) 
    {
        features::FeatureVector vec;
        
        // Rolling Window Safety check (e.g., minimum 50 candles required for EMA50)
        if (candles_5m.size() < 50) {
            // Return safe HOLD-ready vector
            return vec; // Default is all 0.0
        }

        // Implementation of features will go here
        // E.g.
        // vec.values[(int)features::FeatureIndex::EMA_9] = compute_ema(candles_5m, 9);
        // vec.values[(int)features::FeatureIndex::EMA_RATIO] = vec.values[0] / vec.values[1];
        
        // ... (all 20 features)

        // Sanitize output (Zero NaN policy)
        for (double& val : vec.values) {
            if (std::isnan(val) || std::isinf(val)) {
                val = 0.0; // Fail-safe
            }
        }

        return vec;
    }

private:
    // Helper compute functions (Delegated to /features implementors)
    double compute_ema(const std::vector<Candle>& candles, int period) { return 0.0; }
    // ...
};

} // namespace core
} // namespace stockai

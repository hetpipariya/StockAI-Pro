#pragma once

#include <vector>
#include <string>

namespace stockai {
namespace features {

// Fixed order of features as defined by the system architecture
enum class FeatureIndex {
    EMA_9 = 0,
    EMA_21,
    EMA_50,
    EMA_RATIO,
    LINREG_SLOPE,
    RSI_14,
    MACD_HIST,
    ROC_10,
    CCI_20,
    VWAP_DISTANCE,
    VOLUME_RATIO,
    MFI_14,
    ATR_14,
    BB_WIDTH,
    BB_PERCENT_B,
    ADX_14,
    CANDLE_BODY_RATIO,
    MTF_15M_DIRECTION,
    DAILY_ALIGNMENT,
    NIFTY_DIRECTION,
    NUM_FEATURES // Must be 20
};

struct FeatureVector {
    std::vector<double> values;

    FeatureVector() : values(static_cast<size_t>(FeatureIndex::NUM_FEATURES), 0.0) {}

    static std::vector<std::string> get_feature_names() {
        return {
            "ema9",
            "ema21",
            "ema50",
            "ema_ratio",
            "linreg_slope",
            "rsi14",
            "macd_hist",
            "roc10",
            "cci20",
            "vwap_distance",
            "volume_ratio",
            "mfi14",
            "atr14",
            "bb_width",
            "bb_percent_b",
            "adx14",
            "candle_body_ratio",
            "mtf_15m_direction",
            "daily_alignment",
            "nifty_direction"
        };
    }
};

} // namespace features
} // namespace stockai

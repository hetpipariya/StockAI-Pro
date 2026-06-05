#pragma once

#include "../core/types.hpp"
#include "../core/math_utils.hpp"
#include "../core/constants.hpp"
#include <vector>
#include <cmath>
#include <algorithm>
#include <numeric>
#include <array>

namespace stockai::cpp_engine {

// ────────────────────────────────────────────────────────────────────────────
// GENERAL UTILS
// ────────────────────────────────────────────────────────────────────────────

inline std::vector<double> extract_closes(const CandleBuffer& candles) {
    std::vector<double> closes;
    closes.reserve(candles.size());
    for (const auto& c : candles) {
        closes.push_back(c.close);
    }
    return closes;
}

inline std::vector<double> extract_volumes(const CandleBuffer& candles) {
    std::vector<double> vols;
    vols.reserve(candles.size());
    for (const auto& c : candles) {
        vols.push_back(c.volume);
    }
    return vols;
}

// ────────────────────────────────────────────────────────────────────────────
// TREND FEATURES (4)
// ────────────────────────────────────────────────────────────────────────────

class TrendFeatures {
public:
    struct Result {
        double ema_9_21_ratio;
        double close_to_ema50_pct;
        double linreg_slope_20;
        double adx_14;
    };

    static Result compute(const CandleBuffer& candles) {
        Result res{1.0, 0.0, 0.0, 0.0};
        if (candles.size() < 50) {
            return res;
        }

        std::vector<double> closes = extract_closes(candles);
        
        // EMA computations
        auto ema9 = compute_ema_series(closes, 9);
        auto ema21 = compute_ema_series(closes, 21);
        auto ema50 = compute_ema_series(closes, 50);

        if (!ema9.empty() && !ema21.empty()) {
            res.ema_9_21_ratio = safe_divide(ema9.back(), ema21.back(), 1.0);
        }
        if (!ema50.empty()) {
            res.close_to_ema50_pct = safe_divide(closes.back() - ema50.back(), ema50.back(), 0.0) * 100.0;
        }

        // Linear regression slope over 20 bars
        if (closes.size() >= 20) {
            std::vector<double> last_20_closes(closes.end() - 20, closes.end());
            double slope = linear_regression_slope(last_20_closes);
            res.linreg_slope_20 = safe_divide(slope, closes.back(), 0.0) * 100.0;
        }

        // ADX(14) computation
        if (candles.size() >= 28) {
            size_t n = candles.size();
            std::vector<double> tr(n, 0.0);
            std::vector<double> plus_dm(n, 0.0);
            std::vector<double> minus_dm(n, 0.0);

            for (size_t i = 1; i < n; ++i) {
                tr[i] = compute_true_range(candles[i].high, candles[i].low, candles[i - 1].close);
                double plus_dm_val = 0.0;
                double minus_dm_val = 0.0;
                compute_directional_movement(
                    candles[i].high, candles[i].low,
                    candles[i - 1].high, candles[i - 1].low,
                    plus_dm_val, minus_dm_val
                );
                plus_dm[i] = plus_dm_val;
                minus_dm[i] = minus_dm_val;
            }

            // Smoothed series using Wilder's EMA (span 14)
            auto smoothed_tr = compute_ema_series(tr, 14);
            auto smoothed_plus_dm = compute_ema_series(plus_dm, 14);
            auto smoothed_minus_dm = compute_ema_series(minus_dm, 14);

            size_t smoothed_size = smoothed_tr.size();
            std::vector<double> dx(smoothed_size, 0.0);
            for (size_t i = 0; i < smoothed_size; ++i) {
                double plus_di = 100.0 * safe_divide(smoothed_plus_dm[i], smoothed_tr[i], 0.0);
                double minus_di = 100.0 * safe_divide(smoothed_minus_dm[i], smoothed_tr[i], 0.0);
                double di_sum = plus_di + minus_di;
                double di_diff = std::abs(plus_di - minus_di);
                dx[i] = 100.0 * safe_divide(di_diff, di_sum, 0.0);
            }

            auto adx_series = compute_ema_series(dx, 14);
            if (!adx_series.empty()) {
                res.adx_14 = clamp(adx_series.back(), 0.0, 100.0);
            }
        }

        return res;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// MOMENTUM FEATURES (4)
// ────────────────────────────────────────────────────────────────────────────

class MomentumFeatures {
public:
    struct Result {
        double rsi_14;
        double macd_hist_pct;
        double stoch_rsi_k;
        double cci_20_clamped;
    };

    static Result compute(const CandleBuffer& candles) {
        Result res{50.0, 0.0, 0.5, 0.0};
        if (candles.size() < 50) {
            return res;
        }

        std::vector<double> closes = extract_closes(candles);

        // RSI(14)
        double avg_gain = 0.0;
        double avg_loss = 0.0;
        for (size_t i = 1; i <= 14; ++i) {
            double change = closes[i] - closes[i - 1];
            if (change > 0) avg_gain += change;
            else avg_loss += -change;
        }
        avg_gain /= 14.0;
        avg_loss /= 14.0;

        std::vector<double> rsi_values(closes.size(), 50.0);
        for (size_t i = 15; i < closes.size(); ++i) {
            double change = closes[i] - closes[i - 1];
            double gain = change > 0 ? change : 0.0;
            double loss = change < 0 ? -change : 0.0;
            avg_gain = (avg_gain * 13.0 + gain) / 14.0;
            avg_loss = (avg_loss * 13.0 + loss) / 14.0;
            
            double rs = safe_divide(avg_gain, avg_loss, 1.0);
            rsi_values[i] = clamp(100.0 - (100.0 / (1.0 + rs)), 0.0, 100.0);
        }
        res.rsi_14 = rsi_values.back();

        // MACD Hist %
        auto ema12 = compute_ema_series(closes, 12);
        auto ema26 = compute_ema_series(closes, 26);
        if (ema12.size() >= ema26.size() && !ema26.empty()) {
            size_t offset = ema12.size() - ema26.size();
            std::vector<double> macd_line;
            macd_line.reserve(ema26.size());
            for (size_t i = 0; i < ema26.size(); ++i) {
                macd_line.push_back(ema12[i + offset] - ema26[i]);
            }
            auto signal_line = compute_ema_series(macd_line, 9);
            if (!signal_line.empty()) {
                double raw_hist = macd_line.back() - signal_line.back();
                res.macd_hist_pct = safe_divide(raw_hist, closes.back(), 0.0) * 100.0;
            }
        }

        // Stochastic RSI %K (smoothed over 3 periods)
        if (rsi_values.size() >= 17) {
            std::vector<double> stoch_rsi;
            stoch_rsi.reserve(17);
            for (size_t i = rsi_values.size() - 17; i < rsi_values.size(); ++i) {
                double min_rsi = rsi_values[i];
                double max_rsi = rsi_values[i];
                for (size_t j = i - 13; j <= i; ++j) {
                    if (rsi_values[j] < min_rsi) min_rsi = rsi_values[j];
                    if (rsi_values[j] > max_rsi) max_rsi = rsi_values[j];
                }
                double diff = max_rsi - min_rsi;
                double val = safe_divide(rsi_values[i] - min_rsi, diff, 0.5);
                stoch_rsi.push_back(clamp(val, 0.0, 1.0));
            }
            res.stoch_rsi_k = mean(std::vector<double>(stoch_rsi.end() - 3, stoch_rsi.end()));
        }

        // CCI(20) clamped to [-250, +250]
        std::vector<double> typical_prices;
        typical_prices.reserve(candles.size());
        for (const auto& c : candles) {
            typical_prices.push_back(c.typical());
        }

        if (typical_prices.size() >= 20) {
            std::vector<double> last_20_tp(typical_prices.end() - 20, typical_prices.end());
            double tp_sma = mean(last_20_tp);
            double mad = 0.0;
            for (double tp : last_20_tp) {
                mad += std::abs(tp - tp_sma);
            }
            mad /= 20.0;
            
            double current_tp = typical_prices.back();
            double cci = safe_divide(current_tp - tp_sma, 0.015 * mad, 0.0);
            res.cci_20_clamped = clamp(cci, -250.0, +250.0);
        }

        return res;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// VOLUME FEATURES (3)
// ────────────────────────────────────────────────────────────────────────────

class VolumeFeatures {
public:
    struct Result {
        double volume_ratio_20;
        double mfi_14;
        double relative_volume_intraday;
    };

    static Result compute(const CandleBuffer& candles) {
        Result res{1.0, 50.0, 1.0};
        if (candles.size() < 20) {
            return res;
        }

        std::vector<double> volumes = extract_volumes(candles);
        
        // Volume Ratio 20
        std::vector<double> last_20_vols(volumes.end() - 20, volumes.end());
        double avg_vol_20 = mean(last_20_vols);
        res.volume_ratio_20 = safe_divide(volumes.back(), avg_vol_20, 1.0);

        // Relative Volume Intraday (normalized over last 50 bars)
        if (volumes.size() >= 50) {
            std::vector<double> last_50_vols(volumes.end() - 50, volumes.end());
            double avg_vol_50 = mean(last_50_vols);
            res.relative_volume_intraday = safe_divide(volumes.back(), avg_vol_50, 1.0);
        }

        // MFI 14
        if (candles.size() >= 14) {
            double pos_mf = 0.0;
            double neg_mf = 0.0;
            for (size_t i = candles.size() - 14; i < candles.size(); ++i) {
                double tp = candles[i].typical();
                double prev_tp = candles[i - 1].typical();
                double mf = tp * candles[i].volume;
                if (tp > prev_tp) pos_mf += mf;
                else neg_mf += mf;
            }
            double mfi_ratio = safe_divide(pos_mf, neg_mf, 1.0);
            res.mfi_14 = clamp(100.0 - (100.0 / (1.0 + mfi_ratio)), 0.0, 100.0);
        }

        return res;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// VOLATILITY FEATURES (3)
// ────────────────────────────────────────────────────────────────────────────

class VolatilityFeatures {
public:
    struct Result {
        double atr_pct;
        double bb_width_pct;
        double bb_pct_b;
    };

    static Result compute(const CandleBuffer& candles) {
        Result res{0.0, 0.0, 0.5};
        if (candles.size() < 20) {
            return res;
        }

        std::vector<double> closes = extract_closes(candles);

        // ATR percentage (ATR 14 / Close * 100)
        if (candles.size() >= 14) {
            std::vector<double> tr_values;
            tr_values.reserve(candles.size());
            tr_values.push_back(candles[0].high - candles[0].low);
            for (size_t i = 1; i < candles.size(); ++i) {
                tr_values.push_back(compute_true_range(candles[i].high, candles[i].low, candles[i - 1].close));
            }
            auto atr_series = compute_ema_series(tr_values, 14);
            if (!atr_series.empty()) {
                res.atr_pct = safe_divide(atr_series.back(), closes.back(), 0.0) * 100.0;
            }
        }

        // Bollinger Bands (20, 2.0)
        std::vector<double> last_20_closes(closes.end() - 20, closes.end());
        double bb_mid = mean(last_20_closes);
        double bb_std = stddev(last_20_closes);
        double bb_up = bb_mid + 2.0 * bb_std;
        double bb_lo = bb_mid - 2.0 * bb_std;

        res.bb_width_pct = safe_divide(bb_up - bb_lo, bb_mid, 0.0) * 100.0;
        res.bb_pct_b = clamp(safe_divide(closes.back() - bb_lo, bb_up - bb_lo, 0.5), 0.0, 1.0);

        return res;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// INSTITUTIONAL FEATURES (3)
// ────────────────────────────────────────────────────────────────────────────

class InstitutionalFeatures {
public:
    struct Result {
        double vwap_distance_pct;
        double vwap_zscore_20;
        double cpr_width_pct;
    };

    static Result compute(const CandleBuffer& candles, const CandleBuffer& daily_candles) {
        Result res{0.0, 0.0, 0.0};
        if (candles.empty()) {
            return res;
        }

        double close_t = candles.back().close;

        // Session reset VWAP (India intraday resubmits session limits modulo 75 bars)
        size_t current_idx = candles.size() - 1;
        size_t session_start = current_idx - (current_idx % 75);
        
        double cum_tp_vol = 0.0;
        double cum_vol = 0.0;
        for (size_t i = session_start; i <= current_idx; ++i) {
            double tp = candles[i].typical();
            cum_tp_vol += tp * candles[i].volume;
            cum_vol += candles[i].volume;
        }
        double session_vwap = safe_divide(cum_tp_vol, cum_vol, close_t);
        res.vwap_distance_pct = safe_divide(close_t - session_vwap, session_vwap, 0.0) * 100.0;

        // Rolling 20-bar VWAP & Standard Deviation Z-Score
        if (candles.size() >= 20) {
            double roll_tpv = 0.0;
            double roll_vol = 0.0;
            for (size_t i = candles.size() - 20; i < candles.size(); ++i) {
                roll_tpv += candles[i].typical() * candles[i].volume;
                roll_vol += candles[i].volume;
            }
            double roll_vwap = safe_divide(roll_tpv, roll_vol, close_t);

            double weighted_variance = 0.0;
            for (size_t i = candles.size() - 20; i < candles.size(); ++i) {
                double diff = candles[i].typical() - roll_vwap;
                weighted_variance += candles[i].volume * diff * diff;
            }
            double weighted_std = safe_sqrt(safe_divide(weighted_variance, roll_vol, 0.0), 0.0);
            
            double raw_z = safe_divide(close_t - roll_vwap, weighted_std, 0.0);
            res.vwap_zscore_20 = clamp(raw_z, -3.0, +3.0);
        }

        // Daily CPR width percentage (computed from previous completed daily candle)
        if (daily_candles.size() >= 2) {
            const auto& prev_day = daily_candles[daily_candles.size() - 2];
            double pivot = (prev_day.high + prev_day.low + prev_day.close) / 3.0;
            double bc = (prev_day.high + prev_day.low) / 2.0;
            double tc = (pivot - bc) + pivot;
            res.cpr_width_pct = safe_divide(std::abs(tc - bc), close_t, 0.0) * 100.0;
        }

        return res;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// MARKET STRUCTURE FEATURES (3)
// ────────────────────────────────────────────────────────────────────────────

class MarketStructureFeatures {
public:
    struct Result {
        double bos_strength_pct;
        double fvg_gap_pct;
        double candle_body_ratio;
    };

    static Result compute(const CandleBuffer& candles) {
        Result res{0.0, 0.0, 0.5};
        if (candles.empty()) {
            return res;
        }

        const auto& current = candles.back();
        res.candle_body_ratio = clamp(safe_divide(current.body(), current.range(), 0.5), 0.0, 1.0);

        // FVG detection (3-candle rolling imbalance)
        if (candles.size() >= 3) {
            size_t t = candles.size() - 1;
            const auto& c1 = candles[t - 2];
            const auto& c2 = candles[t - 1];
            const auto& c3 = candles[t];
            
            double bullish_fvg = 0.0;
            double bearish_fvg = 0.0;
            
            if (c3.low > c1.high && c2.close > c1.high) {
                bullish_fvg = c3.low - c1.high;
            }
            if (c3.high < c1.low && c2.close < c1.low) {
                bearish_fvg = c1.low - c3.high;
            }
            
            double net_fvg = bullish_fvg - bearish_fvg;
            res.fvg_gap_pct = safe_divide(net_fvg, c3.close, 0.0) * 100.0;
        }

        // BOS strength detection (continuous swing breakouts, lagged by 2 bars to prevent leakage)
        if (candles.size() >= 6) {
            double latest_swing_high = 0.0;
            double latest_swing_low = 0.0;
            
            // Loop backwards up to t-2 to locate latest completed swing pivots
            size_t t = candles.size() - 1;
            for (size_t i = t - 2; i >= 2; --i) {
                // Swing High check
                if (latest_swing_high == 0.0) {
                    if (candles[i].high > candles[i - 1].high && candles[i].high > candles[i - 2].high &&
                        candles[i].high > candles[i + 1].high && candles[i].high > candles[i + 2].high) {
                        latest_swing_high = candles[i].high;
                    }
                }
                // Swing Low check
                if (latest_swing_low == 0.0) {
                    if (candles[i].low < candles[i - 1].low && candles[i].low < candles[i - 2].low &&
                        candles[i].low < candles[i + 1].low && candles[i].low < candles[i + 2].low) {
                        latest_swing_low = candles[i].low;
                    }
                }
                if (latest_swing_high != 0.0 && latest_swing_low != 0.0) {
                    break;
                }
            }

            double close_t = current.close;
            if (latest_swing_high > 0.0 && close_t > latest_swing_high) {
                res.bos_strength_pct = safe_divide(close_t - latest_swing_high, latest_swing_high, 0.0) * 100.0;
            } else if (latest_swing_low > 0.0 && close_t < latest_swing_low) {
                res.bos_strength_pct = safe_divide(close_t - latest_swing_low, latest_swing_low, 0.0) * 100.0;
            }
        }

        return res;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// CONTEXT FEATURES (3)
// ────────────────────────────────────────────────────────────────────────────

class ContextFeatures {
public:
    struct Result {
        double nifty_direction;
        double sector_strength_pct;
        double daily_distance_ema50_pct;
    };

    static Result compute(const MultiTimeframeData& mtf_data) {
        Result res{0.0, 0.0, 0.0};
        
        // Stock current close
        if (mtf_data.candles_5m.empty()) {
            return res;
        }
        double close_5m = mtf_data.candles_5m.back().close;

        // Nifty direction index
        if (mtf_data.nifty_candles.size() >= 21) {
            std::vector<double> nifty_closes = extract_closes(mtf_data.nifty_candles);
            auto nifty_ema9 = compute_ema_series(nifty_closes, 9);
            auto nifty_ema21 = compute_ema_series(nifty_closes, 21);
            if (!nifty_ema9.empty() && !nifty_ema21.empty()) {
                res.nifty_direction = (nifty_ema9.back() > nifty_ema21.back()) ? 1.0 : -1.0;
            }
        }

        // Daily distance from EMA 50
        if (mtf_data.candles_daily.size() >= 50) {
            std::vector<double> daily_closes = extract_closes(mtf_data.candles_daily);
            auto daily_ema50 = compute_ema_series(daily_closes, 50);
            if (!daily_ema50.empty()) {
                double last_daily_close = daily_closes.back();
                res.daily_distance_ema50_pct = safe_divide(last_daily_close - daily_ema50.back(), daily_ema50.back(), 0.0) * 100.0;
            }
        }

        // Sector strength %
        if (mtf_data.candles_5m.size() >= 20 && mtf_data.sector_candles.size() >= 20) {
            double stock_perf = safe_divide(close_5m - mtf_data.candles_5m[mtf_data.candles_5m.size() - 20].close,
                                            mtf_data.candles_5m[mtf_data.candles_5m.size() - 20].close, 0.0) * 100.0;
            
            double sec_prev = mtf_data.sector_candles[mtf_data.sector_candles.size() - 20].close;
            double sec_curr = mtf_data.sector_candles.back().close;
            double sector_perf = safe_divide(sec_curr - sec_prev, sec_prev, 0.0) * 100.0;
            
            res.sector_strength_pct = stock_perf - sector_perf;
        }

        return res;
    }
};

// ────────────────────────────────────────────────────────────────────────────
// SESSION FEATURES (1)
// ────────────────────────────────────────────────────────────────────────────

class SessionFeatures {
public:
    static double compute_progress(const CandleBuffer& candles) {
        if (candles.empty()) {
            return 0.0;
        }
        // In the Indian market session (9:15 - 3:30), there are exactly 75 five-minute bars
        size_t idx = candles.size() - 1;
        double progress = static_cast<double>(idx % 75) / 75.0;
        return clamp(progress, 0.0, 1.0);
    }
};

} // namespace stockai::cpp_engine

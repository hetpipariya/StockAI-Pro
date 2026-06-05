from typing import Any, Dict, List
import math
import numpy as np
import pandas as pd
from scipy.signal import lfilter

from app.inference.native_accelerators import compute_indicator_frame


class IndicatorEngine:
    """Calculates technical indicators in batch and real-time.
    
    Optimized for high-frequency low-latency execution. Dead indicators pruned.
    """

    @staticmethod
    def compute_all(ohlcv: List[Dict[str, Any]]) -> pd.DataFrame:
        """Batch compute all indicators given OHLCV list."""
        if not ohlcv:
            return pd.DataFrame()

        df = pd.DataFrame(ohlcv)
        if "time" in df.columns:
            df.set_index("time", inplace=True)

        # Ensure correct types
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        native_df = compute_indicator_frame(df)
        if native_df is not None and not native_df.empty:
            df = native_df.copy()

        df = IndicatorEngine._calc_moving_averages(df)
        df = IndicatorEngine._calc_oscillators(df)
        df = IndicatorEngine._calc_volatility(df)
        df = IndicatorEngine._calc_trend(df)
        df = IndicatorEngine._calc_volume(df)
        df = IndicatorEngine._calc_advanced(df)
        df = IndicatorEngine._calc_scalp_pro(df)

        return df.replace([np.inf, -np.inf], 0).fillna(0)

    @staticmethod
    def _calc_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
        if "ema9" not in df.columns:
            df["ema9"] = df["close"].ewm(span=9, adjust=False).mean()
        if "sma20" not in df.columns:
            df["sma20"] = df["close"].rolling(window=20).mean()

        # VWAP — guard against zero cumulative volume
        if "vwap" not in df.columns:
            q = df["volume"]
            p = (df["high"] + df["low"] + df["close"]) / 3
            cum_vol = q.cumsum()
            cum_vol = cum_vol.replace(0, np.nan)  # avoid divide-by-zero
            df["vwap"] = (p * q).cumsum() / cum_vol
        return df

    @staticmethod
    def _calc_oscillators(df: pd.DataFrame) -> pd.DataFrame:
        # MACD
        if "macd" not in df.columns:
            exp1 = df["close"].ewm(span=12, adjust=False).mean()
            exp2 = df["close"].ewm(span=26, adjust=False).mean()
            df["macd"] = exp1 - exp2
        if "macd_signal" not in df.columns:
            df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        if "macd_hist" not in df.columns:
            df["macd_hist"] = df["macd"] - df["macd_signal"]

        # CCI 20
        if "cci20" not in df.columns:
            tp = (df["high"] + df["low"] + df["close"]) / 3
            sma = tp.rolling(20).mean()
            mad = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
            mad = mad.replace(0, np.nan)  # avoid divide-by-zero
            df["cci20"] = (tp - sma) / (0.015 * mad)

        return df

    @staticmethod
    def _calc_volatility(df: pd.DataFrame) -> pd.DataFrame:
        # Bollinger Bands 20
        if "bb_upper" not in df.columns or "bb_lower" not in df.columns:
            sma = df["close"].rolling(20).mean()
            std = df["close"].rolling(20).std()
            df["bb_upper"] = sma + 2 * std
            df["bb_lower"] = sma - 2 * std

        # ATR 14
        if "atr14" not in df.columns:
            tr1 = df["high"] - df["low"]
            tr2 = abs(df["high"] - df["close"].shift())
            tr3 = abs(df["low"] - df["close"].shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            df["atr14"] = tr.rolling(14).mean()
        return df

    @staticmethod
    def _calc_trend(df: pd.DataFrame) -> pd.DataFrame:
        # ADX 14 — Directional Movement
        if "adx14" not in df.columns:
            up_move = df["high"].diff()  # current high - previous high
            down_move = df["low"].shift() - df["low"]  # previous low - current low

            plus_dm = up_move.copy()
            minus_dm = down_move.copy()

            # +DM: up_move > down_move and up_move > 0, else 0
            plus_dm[(up_move <= down_move) | (up_move < 0)] = 0
            # -DM: down_move > up_move and down_move > 0, else 0
            minus_dm[(down_move <= up_move) | (down_move < 0)] = 0

            tr1 = df["high"] - df["low"]
            tr2 = abs(df["high"] - df["close"].shift())
            tr3 = abs(df["low"] - df["close"].shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()

            plus_di = 100 * (plus_dm.rolling(14).mean() / atr)
            minus_di = 100 * (minus_dm.rolling(14).mean() / atr)
            di_sum = plus_di + minus_di
            di_sum = di_sum.replace(0, np.nan)  # avoid divide-by-zero
            dx = 100 * abs(plus_di - minus_di) / di_sum
            df["adx14"] = dx.rolling(14).mean()
        return df

    @staticmethod
    def _calc_volume(df: pd.DataFrame) -> pd.DataFrame:
        # OBV
        if "obv" not in df.columns:
            df["obv"] = (np.sign(df["close"].diff()) * df["volume"]).fillna(0).cumsum()
        return df

    @staticmethod
    def _calc_advanced(df: pd.DataFrame) -> pd.DataFrame:
        # Money Flow Index 14
        if "mfi14" not in df.columns:
            typical_price = (df["high"] + df["low"] + df["close"]) / 3
            money_flow = typical_price * df["volume"]
            positive_flow = np.where(typical_price > typical_price.shift(), money_flow, 0)
            negative_flow = np.where(typical_price < typical_price.shift(), money_flow, 0)
            pos_flow_sum = pd.Series(positive_flow, index=df.index).rolling(14).sum()
            neg_flow_sum = pd.Series(negative_flow, index=df.index).rolling(14).sum()
            neg_flow_sum = neg_flow_sum.replace(0, np.nan)  # avoid divide-by-zero
            mfi_ratio = pos_flow_sum / neg_flow_sum
            df["mfi14"] = 100 - (100 / (1 + mfi_ratio))

        return df

    @staticmethod
    def _calc_scalp_pro(df: pd.DataFrame) -> pd.DataFrame:
        """
        Scalp Pro v2 indicator — ported from TradingView Pine Script by Velly.
        Highly optimized using vectorized SciPy recursive IIR filtering to bypass Python event-loop blocks.
        """
        p = df["close"].values
        n = len(p)
        if n == 0:
            return df

        def ehlers_super_smoother(prices, period):
            f = (1.414 * math.pi) / period
            a = math.exp(-f)
            c2 = 2 * a * math.cos(f)
            c3 = -(a * a)
            c1 = 1 - c2 - c3
            
            x = np.zeros(n)
            x[0] = c1 * prices[0]
            if n > 1:
                x[1:] = c1 * (prices[1:] + prices[:-1]) * 0.5
                
            b_coeff = [1.0]
            a_coeff = [1.0, -c2, -c3]
            return lfilter(b_coeff, a_coeff, x)

        # Fast Super Smoother (period 8)
        ssmooth = ehlers_super_smoother(p, 8)

        # Slow Super Smoother (period 10)
        ssmooth2 = ehlers_super_smoother(p, 10)

        # MACD (difference * 10M)
        macd_vals = (ssmooth - ssmooth2) * 10_000_000

        # Signal Super Smoother (period 8)
        signal_vals = ehlers_super_smoother(macd_vals, 8)

        df["scalp_macd"] = macd_vals
        df["scalp_signal"] = signal_vals

        # Vectorized Crossover detection
        scalp_buy = np.zeros(n, dtype=int)
        scalp_sell = np.zeros(n, dtype=int)

        cond_buy = (macd_vals > signal_vals)
        cond_buy_prev = np.zeros(n, dtype=bool)
        cond_buy_prev[1:] = (macd_vals[:-1] <= signal_vals[:-1])
        scalp_buy[cond_buy & cond_buy_prev] = 1

        cond_sell = (macd_vals < signal_vals)
        cond_sell_prev = np.zeros(n, dtype=bool)
        cond_sell_prev[1:] = (macd_vals[:-1] >= signal_vals[:-1])
        scalp_sell[cond_sell & cond_sell_prev] = 1

        df["scalp_buy"] = scalp_buy
        df["scalp_sell"] = scalp_sell

        return df

    @staticmethod
    def compute_incremental(
        candles: List[Dict[str, Any]], new_candle: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compute indicators for a new tick incrementally by appending to history."""
        recent = candles[-50:] + [new_candle]
        df = IndicatorEngine.compute_all(recent)
        latest = df.iloc[-1].to_dict()
        return latest

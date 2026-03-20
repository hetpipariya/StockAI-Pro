import numpy as np
import pandas as pd
from typing import List, Dict, Any

class IndicatorEngine:
    """Calculates 20+ technical indicators in batch and real-time."""

    @staticmethod
    def compute_all(ohlcv: List[Dict[str, Any]]) -> pd.DataFrame:
        """Batch compute all indicators given OHLCV list."""
        if not ohlcv:
            return pd.DataFrame()

        df = pd.DataFrame(ohlcv)
        if 'time' in df.columns:
            df.set_index('time', inplace=True)
            
        # Ensure correct types
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

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
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema15'] = df['close'].ewm(span=15, adjust=False).mean()
        df['sma20'] = df['close'].rolling(window=20).mean()
        
        # VWAP — guard against zero cumulative volume
        q = df['volume']
        p = (df['high'] + df['low'] + df['close']) / 3
        cum_vol = q.cumsum()
        cum_vol = cum_vol.replace(0, np.nan)  # avoid divide-by-zero
        df['vwap'] = (p * q).cumsum() / cum_vol
        return df

    @staticmethod
    def _calc_oscillators(df: pd.DataFrame) -> pd.DataFrame:
        # RSI 9
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=9).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=9).mean()
        loss = loss.replace(0, np.nan)  # avoid divide-by-zero
        rs = gain / loss
        df['rsi9'] = 100 - (100 / (1 + rs))

        # MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # Stochastic Oscillator (14, 3)
        low14 = df['low'].rolling(14).min()
        high14 = df['high'].rolling(14).max()
        stoch_range = high14 - low14
        stoch_range = stoch_range.replace(0, np.nan)  # avoid divide-by-zero
        df['stoch_k'] = 100 * ((df['close'] - low14) / stoch_range)
        df['stoch_d'] = df['stoch_k'].rolling(3).mean()

        # CCI 20
        tp = (df['high'] + df['low'] + df['close']) / 3
        sma = tp.rolling(20).mean()
        mad = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
        mad = mad.replace(0, np.nan)  # avoid divide-by-zero
        df['cci20'] = (tp - sma) / (0.015 * mad)
        
        # ROC 9
        df['roc9'] = df['close'].pct_change(periods=9) * 100

        return df

    @staticmethod
    def _calc_volatility(df: pd.DataFrame) -> pd.DataFrame:
        # Bollinger Bands 20
        sma = df['close'].rolling(20).mean()
        std = df['close'].rolling(20).std()
        df['bb_upper'] = sma + 2 * std
        df['bb_lower'] = sma - 2 * std

        # ATR 14
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift())
        tr3 = abs(df['low'] - df['close'].shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr14'] = tr.rolling(14).mean()
        return df

    @staticmethod
    def _calc_trend(df: pd.DataFrame) -> pd.DataFrame:
        # ADX 14 — Directional Movement
        up_move = df['high'].diff()  # current high - previous high
        down_move = df['low'].shift() - df['low']  # previous low - current low
        
        plus_dm = up_move.copy()
        minus_dm = down_move.copy()
        
        # +DM: up_move > down_move and up_move > 0, else 0
        plus_dm[(up_move <= down_move) | (up_move < 0)] = 0
        # -DM: down_move > up_move and down_move > 0, else 0  
        minus_dm[(down_move <= up_move) | (down_move < 0)] = 0
        
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift())
        tr3 = abs(df['low'] - df['close'].shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        
        plus_di = 100 * (plus_dm.rolling(14).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(14).mean() / atr)
        di_sum = plus_di + minus_di
        di_sum = di_sum.replace(0, np.nan)  # avoid divide-by-zero
        dx = 100 * abs(plus_di - minus_di) / di_sum
        df['adx14'] = dx.rolling(14).mean()

        # SuperTrend (ATR multiplier = 3)
        hl2 = (df['high'] + df['low']) / 2
        df['supertrend'] = hl2 - (3 * df['atr14'])  # Simplified logic
        
        # ZigZag (simplified proxy)
        def _zigzag(x):
            vals = np.asarray(x)
            last = vals[-1]
            return last if (last == vals.max() or last == vals.min()) else np.nan
        df['zigzag'] = df['close'].rolling(5).apply(_zigzag, raw=True).interpolate()
        return df

    @staticmethod
    def _calc_volume(df: pd.DataFrame) -> pd.DataFrame:
        # OBV
        df['obv'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        return df

    @staticmethod
    def _calc_advanced(df: pd.DataFrame) -> pd.DataFrame:
        # Ichimoku Cloud
        nine_period_high = df['high'].rolling(9).max()
        nine_period_low = df['low'].rolling(9).min()
        df['tenkan_sen'] = (nine_period_high + nine_period_low) / 2
        
        # Parabolic SAR (simplified static proxy)
        df['psar'] = df['close'].rolling(2).min()
        
        # Keltner Channels
        ema20 = df['close'].ewm(span=20, adjust=False).mean()
        df['kc_upper'] = ema20 + 2 * df['atr14']
        df['kc_lower'] = ema20 - 2 * df['atr14']
        
        # Williams %R 14
        highest_14 = df['high'].rolling(14).max()
        lowest_14 = df['low'].rolling(14).min()
        wr_range = (highest_14 - lowest_14).replace(0, np.nan)  # avoid divide-by-zero
        df['williams_r'] = -100 * ((highest_14 - df['close']) / wr_range)
        
        # Money Flow Index 14
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        money_flow = typical_price * df['volume']
        positive_flow = np.where(typical_price > typical_price.shift(), money_flow, 0)
        negative_flow = np.where(typical_price < typical_price.shift(), money_flow, 0)
        pos_flow_sum = pd.Series(positive_flow, index=df.index).rolling(14).sum()
        neg_flow_sum = pd.Series(negative_flow, index=df.index).rolling(14).sum()
        neg_flow_sum = neg_flow_sum.replace(0, np.nan)  # avoid divide-by-zero
        mfi_ratio = pos_flow_sum / neg_flow_sum
        df['mfi14'] = 100 - (100 / (1 + mfi_ratio))
        
        return df

    @staticmethod
    def _calc_scalp_pro(df: pd.DataFrame) -> pd.DataFrame:
        """
        Scalp Pro v2 indicator — ported from TradingView Pine Script by Velly.
        Uses Ehlers Super Smoother filter for fast/slow lines, computes crossover signals.
        """
        import math
        
        p = df['close'].values
        n = len(p)
        
        # --- Fast Super Smoother (period 8) ---
        fast_len = 8
        f1 = (1.414 * math.pi) / fast_len
        a1 = math.exp(-f1)
        c2_1 = 2 * a1 * math.cos(f1)
        c3_1 = -(a1 * a1)
        c1_1 = 1 - c2_1 - c3_1
        
        ssmooth = np.zeros(n)
        for i in range(n):
            src = p[i]
            src_prev = p[i - 1] if i >= 1 else src
            ss1 = ssmooth[i - 1] if i >= 1 else 0
            ss2 = ssmooth[i - 2] if i >= 2 else 0
            ssmooth[i] = c1_1 * (src + src_prev) * 0.5 + c2_1 * ss1 + c3_1 * ss2
        
        # --- Slow Super Smoother (period 10) ---
        slow_len = 10
        f2 = (1.414 * math.pi) / slow_len
        a2 = math.exp(-f2)
        c2_2 = 2 * a2 * math.cos(f2)
        c3_2 = -(a2 * a2)
        c1_2 = 1 - c2_2 - c3_2
        
        ssmooth2 = np.zeros(n)
        for i in range(n):
            src = p[i]
            src_prev = p[i - 1] if i >= 1 else src
            ss1 = ssmooth2[i - 1] if i >= 1 else 0
            ss2 = ssmooth2[i - 2] if i >= 2 else 0
            ssmooth2[i] = c1_2 * (src + src_prev) * 0.5 + c2_2 * ss1 + c3_2 * ss2
        
        # --- MACD (difference * 10M) ---
        macd_vals = (ssmooth - ssmooth2) * 10_000_000
        
        # --- Signal Super Smoother (period 8) ---
        signal_len = 8
        f3 = (1.414 * math.pi) / signal_len
        a3 = math.exp(-f3)
        c2_3 = 2 * a3 * math.cos(f3)
        c3_3 = -(a3 * a3)
        c1_3 = 1 - c2_3 - c3_3
        
        signal_vals = np.zeros(n)
        for i in range(n):
            src = macd_vals[i]
            src_prev = macd_vals[i - 1] if i >= 1 else src
            ss1 = signal_vals[i - 1] if i >= 1 else 0
            ss2 = signal_vals[i - 2] if i >= 2 else 0
            signal_vals[i] = c1_3 * (src + src_prev) * 0.5 + c2_3 * ss1 + c3_3 * ss2
        
        df['scalp_macd'] = macd_vals
        df['scalp_signal'] = signal_vals
        
        # Crossover detection
        scalp_buy = np.zeros(n, dtype=int)
        scalp_sell = np.zeros(n, dtype=int)
        for i in range(1, n):
            if macd_vals[i] > signal_vals[i] and macd_vals[i - 1] <= signal_vals[i - 1]:
                scalp_buy[i] = 1
            if macd_vals[i] < signal_vals[i] and macd_vals[i - 1] >= signal_vals[i - 1]:
                scalp_sell[i] = 1
        
        df['scalp_buy'] = scalp_buy
        df['scalp_sell'] = scalp_sell
        
        return df

    @staticmethod
    def compute_incremental(candles: List[Dict[str, Any]], new_candle: Dict[str, Any]) -> Dict[str, Any]:
        """Compute indicators for a new tick incrementally by appending to history."""
        # For simplicity, we reuse batch compute on the last 50 candles which is fast enough
        recent = candles[-50:] + [new_candle]
        df = IndicatorEngine.compute_all(recent)
        latest = df.iloc[-1].to_dict()
        return latest

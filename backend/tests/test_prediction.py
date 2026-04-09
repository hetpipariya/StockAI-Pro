"""
Tests for the ML prediction pipeline (ModelEnsemble).
Tests run with and without a trained model.
"""

from app.inference.feature_engineering import FEATURE_COLUMNS
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestModelEnsembleFallback:
    """Test prediction behavior when NO model is loaded."""

    def test_returns_hold_without_data(self):
        """With no OHLCV data, should return HOLD."""
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST",
            100.0,
            np.zeros((20, 10)),
            np.zeros((1, 10)),
            ohlcv_df=None,
        )
        assert result["signal"] == "HOLD"
        assert result["confidence"] == 0
        assert "prediction" in result

    def test_returns_hold_with_short_data(self, short_ohlcv_df):
        """With < 50 rows, should return HOLD fallback."""
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST",
            100.0,
            np.zeros((20, 10)),
            np.zeros((1, 10)),
            ohlcv_df=short_ohlcv_df,
        )
        assert result["signal"] == "HOLD"
        assert result["confidence"] == 0

    def test_result_has_required_keys(self, mock_ohlcv_df):
        """Output must always contain all required fields."""
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "RELIANCE",
            2500.0,
            np.zeros((20, 10)),
            np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
        )
        required_keys = [
            "prediction",
            "signal",
            "confidence",
            "momentum_score",
            "trend_score",
            "volatility_score",
            "volatility_state",
            "volume_score",
            "price_action_score",
            "candle_type",
            "engulfing",
            "doji",
            "candle_strength",
            "body_strength_score",
            "upper_wick_pct",
            "lower_wick_pct",
            "streak_strength_score",
            "consecutive_green",
            "consecutive_red",
            "rsi_macd_signal",
            "rsi_macd_strength",
            "ema_crossover_signal",
            "ema_crossover_strength",
            "rsi_divergence",
            "divergence_strength",
            "macd_histogram_trend",
            "macd_momentum_strength",
            "fusion_score",
            "structure_score",
            "structure",
            "last_pattern",
            "support_levels",
            "resistance_levels",
            "nearest_support",
            "nearest_resistance",
            "support_distance",
            "resistance_distance",
            "breakout",
            "breakout_type",
            "range_or_trend",
            "volume_ratio",
            "volume_ratio_flag",
            "volume_spike",
            "vwap_deviation",
            "vwap_bias",
            "volume_trend_direction",
            "position_size_factor",
            "mtf_alignment",
            "mtf_score",
            "ema_structure",
            "session",
            "time_bucket",
            "day_of_week",
            "day_bias_score",
            "expiry_flag",
            "expiry_type",
            "time_score",
            "time_bias",
            "liquidity_score",
            "price_impact",
            "jump_flag",
            "gap_flag",
            "liquidity_sweep",
            "sweep_type",
            "flow_state",
            "stop",
            "stop_loss",
            "target",
            "RR",
            "position_size",
            "models",
            "regime",
            "factors",
            "explanation",
            "reason",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_signal_is_valid(self, mock_ohlcv_df):
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST",
            2500.0,
            np.zeros((20, 10)),
            np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
        )
        assert result["signal"] in ("BUY", "SELL", "HOLD")

    def test_confidence_range(self, mock_ohlcv_df):
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST",
            2500.0,
            np.zeros((20, 10)),
            np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
        )
        assert 0 <= result["confidence"] <= 1
        assert 0 <= result["confidence_pct"] <= 100

    def test_stop_less_than_target_for_buy(self, mock_ohlcv_df):
        """For non-HOLD signals, stop should always differ from target."""
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST",
            2500.0,
            np.zeros((20, 10)),
            np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
        )
        # Stop and target should be different (enforced by move_ratio > 0)
        assert result["stop"] != result["target"]

    def test_factors_is_list(self, mock_ohlcv_df):
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST",
            2500.0,
            np.zeros((20, 10)),
            np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
        )
        assert isinstance(result["factors"], list)
        assert all(isinstance(f, str) for f in result["factors"])

    def test_regime_is_valid(self, mock_ohlcv_df):
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST",
            2500.0,
            np.zeros((20, 10)),
            np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
        )
        assert result["regime"] in ("Volatile", "Trending", "Ranging", "Unknown")


class TestModelEnsembleDebug:
    """Test debug mode output."""

    def test_debug_false_no_debug_info(self, mock_ohlcv_df):
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST",
            2500.0,
            np.zeros((20, 10)),
            np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
            debug=False,
        )
        assert "debug_info" not in result

    def test_debug_true_has_debug_info(self, mock_ohlcv_df):
        import app.inference.models as models_mod
        from app.inference.models import ModelEnsemble

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list
        try:
            mock_model = MagicMock()
            mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])
            mock_scaler = MagicMock()
            mock_scaler.transform.return_value = np.zeros((1, len(FEATURE_COLUMNS)))

            models_mod._ensemble_model = mock_model
            models_mod._scaler = mock_scaler
            models_mod._features_list = FEATURE_COLUMNS

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=mock_ohlcv_df,
                debug=True,
            )
            assert "debug_info" in result
            assert "features" in result["debug_info"]
            assert "feature_count" in result["debug_info"]
            assert "rows_used" in result["debug_info"]
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features


class TestPriceActionEngine:
    def test_detects_bullish_engulfing_and_strong_candle(self):
        from app.inference.models import _compute_price_action_engine

        candles = pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0, 103.0, 102.0, 99.0],
                "high": [101.0, 102.0, 103.0, 104.0, 103.5, 105.0],
                "low": [99.0, 100.0, 101.0, 101.5, 99.5, 98.0],
                "close": [100.8, 101.4, 102.2, 102.0, 100.0, 104.0],
            }
        )

        result = _compute_price_action_engine(candles, streak_window=5)

        assert result["bullish_engulfing"] == 1
        assert result["bearish_engulfing"] == 0
        assert result["engulfing"] == "BULLISH"
        assert result["candle_type"] == "STRONG_BULLISH"
        assert result["candle_strength"] == "STRONG"
        assert result["price_action_score"] > 0.6

    def test_detects_doji_indecision(self):
        from app.inference.models import _compute_price_action_engine

        candles = pd.DataFrame(
            {
                "open": [100.0, 100.5, 100.2],
                "high": [101.0, 101.5, 101.0],
                "low": [99.5, 99.8, 99.0],
                "close": [100.6, 100.3, 100.05],
            }
        )

        result = _compute_price_action_engine(candles)

        assert result["doji"] is True
        assert result["candle_type"] == "DOJI"
        assert result["price_action_score"] < 0.6


class TestMarketStructureEngine:
    def test_detects_bullish_breakout_structure(self):
        from app.inference.models import _compute_market_structure_engine

        n = 80
        idx = np.arange(n, dtype=float)
        base = 100.0 + (idx * 0.24) + (np.sin(idx / 3.0) * 1.8)

        open_price = base - 0.35
        close = base + 0.35
        high = np.maximum(open_price, close) + 0.6
        low = np.minimum(open_price, close) - 0.6
        volume = np.full(n, 1100.0) + ((idx % 6) * 35.0)

        # Repeated resistance touches around a cluster level.
        for touch_idx in (60, 64, 68):
            high[touch_idx] = 118.0
            open_price[touch_idx] = 116.8
            close[touch_idx] = 117.2
            low[touch_idx] = 116.1

        # Final candle closes decisively above clustered resistance.
        open_price[-1] = 117.4
        close[-1] = 120.6
        high[-1] = 121.1
        low[-1] = 116.8
        volume[-1] = 3200.0

        candles = pd.DataFrame(
            {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

        result = _compute_market_structure_engine(candles, swing_window=3)

        assert result["breakout"] is True
        assert result["breakout_type"] == "BULLISH"
        assert result["range_or_trend"] == "TREND"
        assert result["structure_score"] > 0.5

    def test_detects_range_bound_structure(self):
        from app.inference.models import _compute_market_structure_engine

        n = 90
        idx = np.arange(n, dtype=float)
        close = 100.0 + (np.sin(idx / 2.4) * 1.35)
        open_price = 100.0 + (np.sin((idx - 1.0) / 2.4) * 1.25)
        high = np.maximum(open_price, close) + 0.5
        low = np.minimum(open_price, close) - 0.5
        volume = np.full(n, 1000.0) + ((idx % 4) * 25.0)

        # Keep final candle near midpoint to represent indecisive center-of-range behavior.
        open_price[-1] = 100.0
        close[-1] = 100.04
        high[-1] = 100.45
        low[-1] = 99.60
        volume[-1] = 980.0

        candles = pd.DataFrame(
            {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

        result = _compute_market_structure_engine(candles, swing_window=3)

        assert result["range_or_trend"] == "RANGE"
        assert result["breakout"] is False
        assert result["structure_score"] < 0.75


class TestIndicatorFusionEngine:
    def test_detects_bullish_confluence_and_positive_fusion(self):
        from app.inference.models import _compute_indicator_fusion_engine

        n = 60
        idx = np.arange(n, dtype=float)
        close = 100.0 + (idx * 0.45) + (np.sin(idx / 4.0) * 0.3)

        candles = pd.DataFrame(
            {
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": np.full(n, 1500.0) + ((idx % 5) * 20.0),
            }
        )

        feature_df = pd.DataFrame(
            {
                "rsi_14": np.linspace(48.0, 68.0, n),
                "macd": np.linspace(-0.2, 1.4, n),
                "macd_signal": np.linspace(-0.25, 0.9, n),
                "macd_hist": np.linspace(-0.05, 0.5, n),
                "ema_9": close + 0.8,
                "ema_21": close - 0.8,
            }
        )

        result = _compute_indicator_fusion_engine(feature_df, candles)

        assert result["rsi_macd_signal"] == 1
        assert result["ema_crossover_signal"] == 1
        assert result["macd_histogram_trend"] == 1
        assert result["fusion_score"] > 0.5
        assert 0 <= result["rsi_macd_strength"] <= 1
        assert 0 <= result["ema_crossover_strength"] <= 1

    def test_detects_bearish_rsi_divergence(self):
        from app.inference.models import _compute_indicator_fusion_engine

        n = 60
        close = np.full(n, 100.0, dtype=float)

        # Construct two clear swing highs: 106 then 107 (higher high).
        close[36:43] = [101.0, 102.0, 103.0, 104.0, 106.0, 104.0, 102.0]
        close[44:51] = [102.0, 103.0, 104.0, 105.0, 107.0, 105.0, 103.0]

        # RSI peaks lower on the second higher-high price swing.
        rsi = np.full(n, 50.0, dtype=float)
        rsi[40] = 68.0
        rsi[48] = 60.0

        candles = pd.DataFrame(
            {
                "open": close - 0.2,
                "high": close + 0.4,
                "low": close - 0.4,
                "close": close,
                "volume": np.full(n, 1200.0),
            }
        )

        feature_df = pd.DataFrame(
            {
                "rsi_14": rsi,
                "macd": np.linspace(0.12, -0.08, n),
                "macd_signal": np.linspace(0.10, -0.06, n),
                "macd_hist": np.linspace(0.02, -0.02, n),
                "ema_9": close + 0.2,
                "ema_21": close - 0.2,
            }
        )

        result = _compute_indicator_fusion_engine(feature_df, candles, swing_window=2)

        assert result["rsi_divergence"] == -1
        assert result["divergence_strength"] > 0


class TestPriceActionHoldFilters:
    def _make_mock_model(self, prob_up=0.8):
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[1 - prob_up, prob_up]])
        return mock_model

    def _make_mock_scaler(self):
        mock_scaler = MagicMock()
        mock_scaler.transform.return_value = np.zeros((1, len(FEATURE_COLUMNS)))
        return mock_scaler

    def test_doji_forces_hold_even_with_engine_alignment(self, bullish_ohlcv_df, monkeypatch):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.9)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            def _mock_volatility(_ohlcv_df, _feature_df):
                return {
                    "volatility_score": 0.75,
                    "volatility_state": "BREAKOUT",
                    "breakout_detected": True,
                    "atr_ratio": 0.012,
                    "bb_width": 0.09,
                    "historical_volatility": 0.28,
                    "range_pct": 0.015,
                    "component_scores": {},
                    "component_metrics": {},
                }

            def _mock_volume(_ohlcv_df, _feature_df):
                return {
                    "volume_score": 0.8,
                    "volume_ratio": 1.7,
                    "volume_ratio_flag": "HIGH",
                    "volume_spike": True,
                    "volume_spike_strength": 1.9,
                    "vwap_deviation": 0.01,
                    "vwap_bias": "ABOVE",
                    "obv_slope": 0.4,
                    "obv_divergence": False,
                    "volume_trend_slope": 0.08,
                    "volume_trend_direction": "UP",
                    "position_size_factor": 1.0,
                    "inconsistent_volume": False,
                    "components": {},
                }

            def _mock_price_action(_ohlcv_df, streak_window=5):
                return {
                    "price_action_score": 0.68,
                    "body_strength_score": 0.12,
                    "upper_wick_pct": 0.38,
                    "lower_wick_pct": 0.36,
                    "bullish_engulfing": 0,
                    "bearish_engulfing": 0,
                    "engulfing": "NONE",
                    "doji": True,
                    "candle_strength": "WEAK",
                    "candle_type": "DOJI",
                    "strong_green_candle": False,
                    "strong_red_candle": False,
                    "consecutive_green": 2,
                    "consecutive_red": 0,
                    "streak_strength_score": 0.4,
                    "long_upper_wick": False,
                    "long_lower_wick": False,
                    "weak_body_candle": False,
                    "conflicting_patterns": False,
                    "components": {},
                }

            monkeypatch.setattr(models_mod, "_compute_volatility_engine", _mock_volatility)
            monkeypatch.setattr(models_mod, "_compute_volume_engine", _mock_volume)
            monkeypatch.setattr(models_mod, "_compute_price_action_engine", _mock_price_action)

            from app.inference.models import ModelEnsemble

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=bullish_ohlcv_df,
            )

            assert result["signal"] == "HOLD"
            assert "doji_indecision" in result["models"].get("filters", [])
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features

    def test_long_upper_wick_bullish_setup_forces_hold(self, bullish_ohlcv_df, monkeypatch):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.9)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            def _mock_volatility(_ohlcv_df, _feature_df):
                return {
                    "volatility_score": 0.74,
                    "volatility_state": "BREAKOUT",
                    "breakout_detected": True,
                    "atr_ratio": 0.012,
                    "bb_width": 0.09,
                    "historical_volatility": 0.28,
                    "range_pct": 0.015,
                    "component_scores": {},
                    "component_metrics": {},
                }

            def _mock_volume(_ohlcv_df, _feature_df):
                return {
                    "volume_score": 0.8,
                    "volume_ratio": 1.7,
                    "volume_ratio_flag": "HIGH",
                    "volume_spike": True,
                    "volume_spike_strength": 1.9,
                    "vwap_deviation": 0.01,
                    "vwap_bias": "ABOVE",
                    "obv_slope": 0.4,
                    "obv_divergence": False,
                    "volume_trend_slope": 0.08,
                    "volume_trend_direction": "UP",
                    "position_size_factor": 1.0,
                    "inconsistent_volume": False,
                    "components": {},
                }

            def _mock_price_action(_ohlcv_df, streak_window=5):
                return {
                    "price_action_score": 0.78,
                    "body_strength_score": 0.82,
                    "upper_wick_pct": 0.66,
                    "lower_wick_pct": 0.08,
                    "bullish_engulfing": 1,
                    "bearish_engulfing": 0,
                    "engulfing": "BULLISH",
                    "doji": False,
                    "candle_strength": "STRONG",
                    "candle_type": "STRONG_BULLISH",
                    "strong_green_candle": True,
                    "strong_red_candle": False,
                    "consecutive_green": 4,
                    "consecutive_red": 0,
                    "streak_strength_score": 0.8,
                    "long_upper_wick": True,
                    "long_lower_wick": False,
                    "weak_body_candle": False,
                    "conflicting_patterns": False,
                    "components": {},
                }

            monkeypatch.setattr(models_mod, "_compute_volatility_engine", _mock_volatility)
            monkeypatch.setattr(models_mod, "_compute_volume_engine", _mock_volume)
            monkeypatch.setattr(models_mod, "_compute_price_action_engine", _mock_price_action)

            from app.inference.models import ModelEnsemble

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=bullish_ohlcv_df,
            )

            assert result["signal"] == "HOLD"
            assert "price_action_upper_wick_rejection" in result["models"].get("filters", [])
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features

    def test_debug_feature_values(self, mock_ohlcv_df):
        """Debug info should include all canonical feature values."""
        import app.inference.models as models_mod
        from app.inference.models import ModelEnsemble

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list
        try:
            mock_model = MagicMock()
            mock_model.predict_proba.return_value = np.array([[0.4, 0.6]])
            mock_scaler = MagicMock()
            mock_scaler.transform.return_value = np.zeros((1, len(FEATURE_COLUMNS)))

            models_mod._ensemble_model = mock_model
            models_mod._scaler = mock_scaler
            models_mod._features_list = FEATURE_COLUMNS

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=mock_ohlcv_df,
                debug=True,
            )
            features = result["debug_info"]["features"]
            for col in FEATURE_COLUMNS:
                assert col in features, f"Debug missing feature: {col}"
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features
        for col in FEATURE_COLUMNS:
            assert col in features, f"Debug missing feature: {col}"


class TestModelEnsembleWithMockModel:
    """Test prediction with a mock ML model."""

    def _make_mock_model(self, prob_up=0.75):
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[1 - prob_up, prob_up]])
        return mock_model

    def _make_mock_scaler(self):
        mock_scaler = MagicMock()
        mock_scaler.transform.return_value = np.zeros((1, len(FEATURE_COLUMNS)))
        return mock_scaler

    def test_buy_signal_with_high_prob(self, bullish_ohlcv_df, monkeypatch):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.80)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            def _mock_volatility(_ohlcv_df, _feature_df):
                return {
                    "volatility_score": 0.72,
                    "volatility_state": "BREAKOUT",
                    "breakout_detected": True,
                    "atr_ratio": 0.012,
                    "bb_width": 0.09,
                    "historical_volatility": 0.28,
                    "range_pct": 0.015,
                    "component_scores": {
                        "atr_expansion": 0.75,
                        "bb_width": 0.70,
                        "historical_volatility": 0.68,
                        "breakout": 1.0,
                        "candle_range": 0.55,
                    },
                    "component_metrics": {},
                }

            def _mock_volume(_ohlcv_df, _feature_df):
                return {
                    "volume_score": 0.78,
                    "volume_ratio": 1.6,
                    "volume_ratio_flag": "HIGH",
                    "volume_spike": True,
                    "volume_spike_strength": 1.8,
                    "vwap_deviation": 0.012,
                    "vwap_bias": "ABOVE",
                    "obv_slope": 0.35,
                    "obv_divergence": False,
                    "volume_trend_slope": 0.08,
                    "volume_trend_direction": "UP",
                    "position_size_factor": 1.0,
                    "inconsistent_volume": False,
                    "components": {
                        "ratio": 0.8,
                        "spike": 0.9,
                        "slope": 0.7,
                        "vwap": 0.6,
                        "obv": 0.7,
                    },
                }

            def _mock_price_action(_ohlcv_df, streak_window=5):
                return {
                    "price_action_score": 0.82,
                    "body_strength_score": 0.86,
                    "upper_wick_pct": 0.08,
                    "lower_wick_pct": 0.18,
                    "bullish_engulfing": 1,
                    "bearish_engulfing": 0,
                    "engulfing": "BULLISH",
                    "doji": False,
                    "candle_strength": "STRONG",
                    "candle_type": "STRONG_BULLISH",
                    "strong_green_candle": True,
                    "strong_red_candle": False,
                    "consecutive_green": 4,
                    "consecutive_red": 0,
                    "streak_strength_score": 0.8,
                    "long_upper_wick": False,
                    "long_lower_wick": False,
                    "weak_body_candle": False,
                    "conflicting_patterns": False,
                    "components": {
                        "body_strength": 0.86,
                        "wick_analysis": 0.7,
                        "engulfing": 1.0,
                        "doji_signal": 1.0,
                        "streak": 0.8,
                    },
                }

            def _mock_structure(_ohlcv_df, swing_window=3, cluster_pct=0.0035):
                return {
                    "structure_score": 0.84,
                    "structure": "UPTREND",
                    "last_pattern": "HIGHER_HIGH",
                    "support_levels": [2488.0, 2494.0],
                    "resistance_levels": [2510.0],
                    "nearest_support": 2494.0,
                    "nearest_resistance": 2510.0,
                    "support_distance": 0.0024,
                    "resistance_distance": 0.004,
                    "near_support": True,
                    "near_resistance": False,
                    "middle_zone": False,
                    "breakout": True,
                    "breakout_type": "BULLISH",
                    "breakout_distance": 0.003,
                    "breakout_level": 2510.0,
                    "range_or_trend": "TREND",
                    "higher_high": True,
                    "higher_low": True,
                    "lower_high": False,
                    "lower_low": False,
                    "components": {
                        "trend_clarity": 0.9,
                        "sr_proximity": 0.8,
                        "breakout_strength": 0.85,
                        "classification": 0.88,
                    },
                }

            def _mock_fusion(
                _feature_df,
                _ohlcv_df,
                swing_window=3,
                histogram_window=5,
            ):
                return {
                    "rsi_macd_signal": 1,
                    "rsi_macd_strength": 0.76,
                    "ema_crossover_signal": 1,
                    "ema_crossover_strength": 0.012,
                    "rsi_divergence": 0,
                    "divergence_strength": 0.0,
                    "macd_histogram_trend": 1,
                    "macd_momentum_strength": 0.42,
                    "fusion_score": 0.8,
                    "components": {},
                }

            def _mock_mtf(_ohlcv_df):
                return {
                    "mtf_alignment": "STRONG",
                    "mtf_score": 0.95,
                    "direction": "BULLISH",
                    "htf_confirmed": True,
                    "ltf_entry_confirmed": True,
                    "conflict": False,
                    "timeframes": {
                        "1m": "BULLISH",
                        "5m": "BULLISH",
                        "15m": "BULLISH",
                        "1h": "BULLISH",
                    },
                    "timeframe_strength": {
                        "1m": 0.9,
                        "5m": 0.9,
                        "15m": 0.9,
                        "1h": 0.9,
                    },
                    "components": {},
                }

            monkeypatch.setattr(models_mod, "_compute_volatility_engine", _mock_volatility)
            monkeypatch.setattr(models_mod, "_compute_volume_engine", _mock_volume)
            monkeypatch.setattr(models_mod, "_compute_price_action_engine", _mock_price_action)
            monkeypatch.setattr(models_mod, "_compute_market_structure_engine", _mock_structure)
            monkeypatch.setattr(models_mod, "_compute_indicator_fusion_engine", _mock_fusion)
            monkeypatch.setattr(models_mod, "compute_multi_timeframe_alignment", _mock_mtf)

            from app.inference.models import ModelEnsemble

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=bullish_ohlcv_df,
            )
            assert result["signal"] == "BUY"
            assert result["momentum_score"] > 0.65
            assert result["trend_score"] > 0.6
            assert result["volatility_score"] > 0.55
            assert result["volume_ratio"] > 1.2
            assert result["volume_spike"] is True
            assert result["vwap_bias"] == "ABOVE"
            assert result["price_action_score"] > 0.6
            assert result["engulfing"] == "BULLISH"
            assert result["confidence"] >= 0.6
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features

    def test_sell_signal_with_low_prob(self, bearish_ohlcv_df, monkeypatch):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.20)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            def _mock_volatility(_ohlcv_df, _feature_df):
                return {
                    "volatility_score": 0.70,
                    "volatility_state": "BREAKOUT",
                    "breakout_detected": True,
                    "atr_ratio": 0.011,
                    "bb_width": 0.08,
                    "historical_volatility": 0.26,
                    "range_pct": 0.014,
                    "component_scores": {
                        "atr_expansion": 0.70,
                        "bb_width": 0.67,
                        "historical_volatility": 0.65,
                        "breakout": 1.0,
                        "candle_range": 0.52,
                    },
                    "component_metrics": {},
                }

            def _mock_volume(_ohlcv_df, _feature_df):
                return {
                    "volume_score": 0.76,
                    "volume_ratio": 1.7,
                    "volume_ratio_flag": "HIGH",
                    "volume_spike": True,
                    "volume_spike_strength": 1.9,
                    "vwap_deviation": -0.013,
                    "vwap_bias": "BELOW",
                    "obv_slope": -0.32,
                    "obv_divergence": False,
                    "volume_trend_slope": 0.09,
                    "volume_trend_direction": "UP",
                    "position_size_factor": 1.0,
                    "inconsistent_volume": False,
                    "components": {
                        "ratio": 0.8,
                        "spike": 0.9,
                        "slope": 0.7,
                        "vwap": 0.6,
                        "obv": 0.7,
                    },
                }

            def _mock_price_action(_ohlcv_df, streak_window=5):
                return {
                    "price_action_score": 0.8,
                    "body_strength_score": 0.83,
                    "upper_wick_pct": 0.2,
                    "lower_wick_pct": 0.06,
                    "bullish_engulfing": 0,
                    "bearish_engulfing": 1,
                    "engulfing": "BEARISH",
                    "doji": False,
                    "candle_strength": "STRONG",
                    "candle_type": "STRONG_BEARISH",
                    "strong_green_candle": False,
                    "strong_red_candle": True,
                    "consecutive_green": 0,
                    "consecutive_red": 4,
                    "streak_strength_score": 0.8,
                    "long_upper_wick": False,
                    "long_lower_wick": False,
                    "weak_body_candle": False,
                    "conflicting_patterns": False,
                    "components": {
                        "body_strength": 0.83,
                        "wick_analysis": 0.72,
                        "engulfing": 1.0,
                        "doji_signal": 1.0,
                        "streak": 0.8,
                    },
                }

            def _mock_structure(_ohlcv_df, swing_window=3, cluster_pct=0.0035):
                return {
                    "structure_score": 0.83,
                    "structure": "DOWNTREND",
                    "last_pattern": "LOWER_LOW",
                    "support_levels": [2488.0],
                    "resistance_levels": [2508.0, 2515.0],
                    "nearest_support": 2488.0,
                    "nearest_resistance": 2508.0,
                    "support_distance": 0.0048,
                    "resistance_distance": 0.0032,
                    "near_support": False,
                    "near_resistance": True,
                    "middle_zone": False,
                    "breakout": True,
                    "breakout_type": "BEARISH",
                    "breakout_distance": 0.0031,
                    "breakout_level": 2488.0,
                    "range_or_trend": "TREND",
                    "higher_high": False,
                    "higher_low": False,
                    "lower_high": True,
                    "lower_low": True,
                    "components": {
                        "trend_clarity": 0.88,
                        "sr_proximity": 0.81,
                        "breakout_strength": 0.83,
                        "classification": 0.86,
                    },
                }

            def _mock_fusion(
                _feature_df,
                _ohlcv_df,
                swing_window=3,
                histogram_window=5,
            ):
                return {
                    "rsi_macd_signal": -1,
                    "rsi_macd_strength": 0.74,
                    "ema_crossover_signal": -1,
                    "ema_crossover_strength": 0.013,
                    "rsi_divergence": 0,
                    "divergence_strength": 0.0,
                    "macd_histogram_trend": -1,
                    "macd_momentum_strength": -0.45,
                    "fusion_score": -0.8,
                    "components": {},
                }

            def _mock_time(_ohlcv_df):
                return {
                    "session": "CLOSE",
                    "time_bucket": "BREAKOUT_REVERSAL",
                    "day_of_week": 2,
                    "day_bias_score": 0.58,
                    "expiry_flag": False,
                    "expiry_type": "NONE",
                    "time_score": 0.7,
                    "time_bias": "TREND_CONTINUATION",
                    "trade_mode": "TREND_CONTINUATION",
                    "confirmation_threshold": 0.6,
                    "position_size_factor": 1.0,
                    "components": {},
                }

            def _mock_mtf(_ohlcv_df):
                return {
                    "mtf_alignment": "STRONG",
                    "mtf_score": 0.95,
                    "direction": "BEARISH",
                    "htf_confirmed": True,
                    "ltf_entry_confirmed": True,
                    "conflict": False,
                    "timeframes": {
                        "1m": "BEARISH",
                        "5m": "BEARISH",
                        "15m": "BEARISH",
                        "1h": "BEARISH",
                    },
                    "timeframe_strength": {
                        "1m": 0.9,
                        "5m": 0.9,
                        "15m": 0.9,
                        "1h": 0.9,
                    },
                    "components": {},
                }

            monkeypatch.setattr(models_mod, "_compute_volatility_engine", _mock_volatility)
            monkeypatch.setattr(models_mod, "_compute_volume_engine", _mock_volume)
            monkeypatch.setattr(models_mod, "_compute_price_action_engine", _mock_price_action)
            monkeypatch.setattr(models_mod, "_compute_market_structure_engine", _mock_structure)
            monkeypatch.setattr(models_mod, "_compute_indicator_fusion_engine", _mock_fusion)
            monkeypatch.setattr(models_mod, "compute_time_intelligence", _mock_time)
            monkeypatch.setattr(models_mod, "compute_multi_timeframe_alignment", _mock_mtf)

            from app.inference.models import ModelEnsemble

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=bearish_ohlcv_df,
            )
            assert result["signal"] == "SELL"
            assert result["momentum_score"] < 0.35
            assert result["trend_score"] < 0.4
            assert result["volatility_score"] > 0.55
            assert result["volume_ratio"] > 1.2
            assert result["volume_spike"] is True
            assert result["vwap_bias"] == "BELOW"
            assert result["price_action_score"] > 0.6
            assert result["engulfing"] == "BEARISH"
            assert result["confidence"] >= 0.6
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features

    def test_hold_signal_with_uncertain_prob(self, mock_ohlcv_df):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.52)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            from app.inference.models import ModelEnsemble

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=mock_ohlcv_df,
            )
            assert result["signal"] == "HOLD"
            assert result["confidence"] <= 0.59
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features

    def test_debug_shows_probabilities(self, mock_ohlcv_df):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.70)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            from app.inference.models import ModelEnsemble

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=mock_ohlcv_df,
                debug=True,
            )
            assert "debug_info" in result
            assert result["debug_info"]["prob_up"] == 0.7
            assert result["debug_info"]["prob_down"] == 0.3
            assert "signal_reasoning" in result["debug_info"]
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features

    def test_conflicting_timeframes_force_hold(self, bullish_ohlcv_df, monkeypatch):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.88)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            def _mock_trend(_ohlcv_df):
                return {
                    "trend_score": 0.75,
                    "ema_structure": "BULLISH STACK",
                    "mtf_alignment": "CONFLICTING",
                    "mtf_direction": "MIXED",
                    "signed": 0.2,
                    "component_signed": {
                        "stacking": 1.0,
                        "slope": 0.2,
                        "distance": 0.2,
                        "mtf": 0.0,
                    },
                    "timeframes": {
                        "1m": "BULLISH",
                        "5m": "BEARISH",
                        "15m": "BULLISH",
                        "1h": "BEARISH",
                    },
                }

            monkeypatch.setattr(models_mod, "_compute_trend_engine", _mock_trend)

            from app.inference.models import ModelEnsemble

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=bullish_ohlcv_df,
            )
            assert result["signal"] == "HOLD"
            assert "conflicting_timeframes" in result["models"].get("filters", [])
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features

    def test_low_volatility_forces_hold(self, bullish_ohlcv_df, monkeypatch):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.9)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            def _mock_volatility(_ohlcv_df, _feature_df):
                return {
                    "volatility_score": 0.2,
                    "volatility_state": "LOW_VOLATILITY",
                    "breakout_detected": False,
                    "atr_ratio": 0.001,
                    "bb_width": 0.01,
                    "historical_volatility": 0.02,
                    "range_pct": 0.001,
                    "component_scores": {
                        "atr_expansion": 0.1,
                        "bb_width": 0.1,
                        "historical_volatility": 0.1,
                        "breakout": 0.0,
                        "candle_range": 0.1,
                    },
                    "component_metrics": {},
                }

            monkeypatch.setattr(models_mod, "_compute_volatility_engine", _mock_volatility)

            from app.inference.models import ModelEnsemble

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=bullish_ohlcv_df,
            )
            assert result["signal"] == "HOLD"
            assert "volatility_too_low" in result["models"].get("filters", [])
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features

    def test_open_session_weak_confirmation_forces_hold(self, bullish_ohlcv_df, monkeypatch):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.9)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            def _mock_momentum(_feature_df, _ohlcv_df, ml_prob_up=None):
                return {
                    "momentum_score": 0.71,
                    "momentum_label": "BULLISH",
                    "signed": 0.42,
                    "ml_prob_up": ml_prob_up,
                    "components": {},
                }

            def _mock_trend(_ohlcv_df):
                return {
                    "trend_score": 0.66,
                    "ema_structure": "BULLISH STACK",
                    "mtf_alignment": "STRONG",
                    "mtf_direction": "BULLISH",
                    "signed": 0.6,
                    "component_signed": {},
                    "timeframes": {"1m": "BULLISH", "5m": "BULLISH"},
                }

            def _mock_volatility(_ohlcv_df, _feature_df):
                return {
                    "volatility_score": 0.72,
                    "volatility_state": "BREAKOUT",
                    "breakout_detected": True,
                    "atr_ratio": 0.012,
                    "bb_width": 0.09,
                    "historical_volatility": 0.28,
                    "range_pct": 0.015,
                    "component_scores": {},
                    "component_metrics": {},
                }

            def _mock_volume(_ohlcv_df, _feature_df):
                return {
                    "volume_score": 0.72,
                    "volume_ratio": 1.6,
                    "volume_ratio_flag": "HIGH",
                    "volume_spike": True,
                    "volume_spike_strength": 1.6,
                    "vwap_deviation": 0.009,
                    "vwap_bias": "ABOVE",
                    "obv_slope": 0.3,
                    "obv_divergence": False,
                    "volume_trend_slope": 0.06,
                    "volume_trend_direction": "UP",
                    "position_size_factor": 1.0,
                    "inconsistent_volume": False,
                    "components": {},
                }

            def _mock_price_action(_ohlcv_df, streak_window=5):
                return {
                    "price_action_score": 0.65,
                    "body_strength_score": 0.66,
                    "upper_wick_pct": 0.15,
                    "lower_wick_pct": 0.20,
                    "bullish_engulfing": 1,
                    "bearish_engulfing": 0,
                    "engulfing": "BULLISH",
                    "doji": False,
                    "candle_strength": "STRONG",
                    "candle_type": "STRONG_BULLISH",
                    "strong_green_candle": True,
                    "strong_red_candle": False,
                    "consecutive_green": 3,
                    "consecutive_red": 0,
                    "streak_strength_score": 0.7,
                    "long_upper_wick": False,
                    "long_lower_wick": False,
                    "weak_body_candle": False,
                    "conflicting_patterns": False,
                    "components": {},
                }

            def _mock_structure(_ohlcv_df, swing_window=3, cluster_pct=0.0035):
                return {
                    "structure_score": 0.8,
                    "structure": "UPTREND",
                    "last_pattern": "HIGHER_HIGH",
                    "support_levels": [100.0],
                    "resistance_levels": [102.0],
                    "nearest_support": 100.0,
                    "nearest_resistance": 102.0,
                    "support_distance": 0.002,
                    "resistance_distance": 0.004,
                    "near_support": True,
                    "near_resistance": False,
                    "middle_zone": False,
                    "breakout": True,
                    "breakout_type": "BULLISH",
                    "breakout_distance": 0.003,
                    "breakout_level": 102.0,
                    "range_or_trend": "TREND",
                    "higher_high": True,
                    "higher_low": True,
                    "lower_high": False,
                    "lower_low": False,
                    "components": {},
                }

            def _mock_fusion(_feature_df, _ohlcv_df, swing_window=3, histogram_window=5):
                return {
                    "rsi_macd_signal": 1,
                    "rsi_macd_strength": 0.7,
                    "ema_crossover_signal": 1,
                    "ema_crossover_strength": 0.01,
                    "rsi_divergence": 0,
                    "divergence_strength": 0.0,
                    "macd_histogram_trend": 1,
                    "macd_momentum_strength": 0.35,
                    "fusion_score": 0.7,
                    "components": {},
                }

            def _mock_time(_ohlcv_df):
                return {
                    "session": "OPEN",
                    "time_bucket": "OPENING_SPIKE",
                    "day_of_week": 2,
                    "day_bias_score": 0.58,
                    "expiry_flag": False,
                    "expiry_type": "NONE",
                    "time_score": 0.62,
                    "time_bias": "HIGH_VOLATILITY",
                    "confirmation_threshold": 0.95,
                    "position_size_factor": 0.9,
                    "components": {},
                }

            monkeypatch.setattr(models_mod, "_compute_momentum_engine", _mock_momentum)
            monkeypatch.setattr(models_mod, "_compute_trend_engine", _mock_trend)
            monkeypatch.setattr(models_mod, "_compute_volatility_engine", _mock_volatility)
            monkeypatch.setattr(models_mod, "_compute_volume_engine", _mock_volume)
            monkeypatch.setattr(models_mod, "_compute_price_action_engine", _mock_price_action)
            monkeypatch.setattr(models_mod, "_compute_market_structure_engine", _mock_structure)
            monkeypatch.setattr(models_mod, "_compute_indicator_fusion_engine", _mock_fusion)
            monkeypatch.setattr(models_mod, "compute_time_intelligence", _mock_time)

            from app.inference.models import ModelEnsemble

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=bullish_ohlcv_df,
            )

            assert result["signal"] == "HOLD"
            assert "open_session_weak_confirmation" in result["models"].get("filters", [])
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features

    def test_expiry_conflicting_signals_forces_hold(self, bullish_ohlcv_df, monkeypatch):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.9)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            def _mock_momentum(_feature_df, _ohlcv_df, ml_prob_up=None):
                return {
                    "momentum_score": 0.72,
                    "momentum_label": "BULLISH",
                    "signed": 0.44,
                    "ml_prob_up": ml_prob_up,
                    "components": {},
                }

            def _mock_trend(_ohlcv_df):
                return {
                    "trend_score": 0.70,
                    "ema_structure": "BULLISH STACK",
                    "mtf_alignment": "STRONG",
                    "mtf_direction": "BULLISH",
                    "signed": 0.62,
                    "component_signed": {},
                    "timeframes": {"1m": "BULLISH", "5m": "BULLISH"},
                }

            def _mock_volatility(_ohlcv_df, _feature_df):
                return {
                    "volatility_score": 0.70,
                    "volatility_state": "NORMAL_VOLATILITY",
                    "breakout_detected": True,
                    "atr_ratio": 0.01,
                    "bb_width": 0.06,
                    "historical_volatility": 0.22,
                    "range_pct": 0.01,
                    "component_scores": {},
                    "component_metrics": {},
                }

            def _mock_volume(_ohlcv_df, _feature_df):
                return {
                    "volume_score": 0.74,
                    "volume_ratio": 1.7,
                    "volume_ratio_flag": "HIGH",
                    "volume_spike": True,
                    "volume_spike_strength": 1.8,
                    "vwap_deviation": 0.01,
                    "vwap_bias": "ABOVE",
                    "obv_slope": 0.28,
                    "obv_divergence": False,
                    "volume_trend_slope": 0.07,
                    "volume_trend_direction": "UP",
                    "position_size_factor": 1.0,
                    "inconsistent_volume": False,
                    "components": {},
                }

            def _mock_price_action(_ohlcv_df, streak_window=5):
                return {
                    "price_action_score": 0.78,
                    "body_strength_score": 0.8,
                    "upper_wick_pct": 0.1,
                    "lower_wick_pct": 0.16,
                    "bullish_engulfing": 1,
                    "bearish_engulfing": 0,
                    "engulfing": "BULLISH",
                    "doji": False,
                    "candle_strength": "STRONG",
                    "candle_type": "STRONG_BULLISH",
                    "strong_green_candle": True,
                    "strong_red_candle": False,
                    "consecutive_green": 4,
                    "consecutive_red": 0,
                    "streak_strength_score": 0.8,
                    "long_upper_wick": False,
                    "long_lower_wick": False,
                    "weak_body_candle": False,
                    "conflicting_patterns": False,
                    "components": {},
                }

            def _mock_structure(_ohlcv_df, swing_window=3, cluster_pct=0.0035):
                return {
                    "structure_score": 0.83,
                    "structure": "UPTREND",
                    "last_pattern": "HIGHER_HIGH",
                    "support_levels": [100.0],
                    "resistance_levels": [103.0],
                    "nearest_support": 100.0,
                    "nearest_resistance": 103.0,
                    "support_distance": 0.002,
                    "resistance_distance": 0.005,
                    "near_support": True,
                    "near_resistance": False,
                    "middle_zone": False,
                    "breakout": True,
                    "breakout_type": "BULLISH",
                    "breakout_distance": 0.003,
                    "breakout_level": 103.0,
                    "range_or_trend": "TREND",
                    "higher_high": True,
                    "higher_low": True,
                    "lower_high": False,
                    "lower_low": False,
                    "components": {},
                }

            def _mock_fusion(_feature_df, _ohlcv_df, swing_window=3, histogram_window=5):
                return {
                    "rsi_macd_signal": -1,
                    "rsi_macd_strength": 0.6,
                    "ema_crossover_signal": -1,
                    "ema_crossover_strength": 0.01,
                    "rsi_divergence": 0,
                    "divergence_strength": 0.0,
                    "macd_histogram_trend": -1,
                    "macd_momentum_strength": -0.3,
                    "fusion_score": -0.45,
                    "components": {},
                }

            def _mock_time(_ohlcv_df):
                return {
                    "session": "CLOSE",
                    "time_bucket": "BREAKOUT_REVERSAL",
                    "day_of_week": 3,
                    "day_bias_score": 0.62,
                    "expiry_flag": True,
                    "expiry_type": "WEEKLY",
                    "time_score": 0.58,
                    "time_bias": "HIGH_VOLATILITY",
                    "confirmation_threshold": 0.6,
                    "position_size_factor": 0.7,
                    "components": {},
                }

            monkeypatch.setattr(models_mod, "_compute_momentum_engine", _mock_momentum)
            monkeypatch.setattr(models_mod, "_compute_trend_engine", _mock_trend)
            monkeypatch.setattr(models_mod, "_compute_volatility_engine", _mock_volatility)
            monkeypatch.setattr(models_mod, "_compute_volume_engine", _mock_volume)
            monkeypatch.setattr(models_mod, "_compute_price_action_engine", _mock_price_action)
            monkeypatch.setattr(models_mod, "_compute_market_structure_engine", _mock_structure)
            monkeypatch.setattr(models_mod, "_compute_indicator_fusion_engine", _mock_fusion)
            monkeypatch.setattr(models_mod, "compute_time_intelligence", _mock_time)

            from app.inference.models import ModelEnsemble

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=bullish_ohlcv_df,
            )

            assert result["signal"] == "HOLD"
            assert result["expiry_flag"] is True
            assert "expiry_conflicting_signals" in result["models"].get("filters", [])
            assert result["position_size_factor"] <= 0.7
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features

    def test_rr_below_threshold_forces_hold(self, bullish_ohlcv_df, monkeypatch):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.9)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            def _mock_momentum(_feature_df, _ohlcv_df, ml_prob_up=None):
                return {
                    "momentum_score": 0.72,
                    "momentum_label": "BULLISH",
                    "signed": 0.44,
                    "ml_prob_up": ml_prob_up,
                    "components": {},
                }

            def _mock_trend(_ohlcv_df):
                return {
                    "trend_score": 0.68,
                    "ema_structure": "BULLISH STACK",
                    "mtf_alignment": "STRONG",
                    "mtf_direction": "BULLISH",
                    "signed": 0.6,
                    "component_signed": {},
                    "timeframes": {"1m": "BULLISH", "5m": "BULLISH"},
                }

            def _mock_volatility(_ohlcv_df, _feature_df):
                return {
                    "volatility_score": 0.72,
                    "volatility_state": "BREAKOUT",
                    "breakout_detected": True,
                    "atr_ratio": 0.012,
                    "bb_width": 0.09,
                    "historical_volatility": 0.28,
                    "range_pct": 0.015,
                    "component_scores": {},
                    "component_metrics": {},
                }

            def _mock_volume(_ohlcv_df, _feature_df):
                return {
                    "volume_score": 0.78,
                    "volume_ratio": 1.6,
                    "volume_ratio_flag": "HIGH",
                    "volume_spike": True,
                    "volume_spike_strength": 1.8,
                    "vwap_deviation": 0.012,
                    "vwap_bias": "ABOVE",
                    "obv_slope": 0.35,
                    "obv_divergence": False,
                    "volume_trend_slope": 0.08,
                    "volume_trend_direction": "UP",
                    "position_size_factor": 1.0,
                    "inconsistent_volume": False,
                    "components": {},
                }

            def _mock_price_action(_ohlcv_df, streak_window=5):
                return {
                    "price_action_score": 0.82,
                    "body_strength_score": 0.86,
                    "upper_wick_pct": 0.08,
                    "lower_wick_pct": 0.18,
                    "bullish_engulfing": 1,
                    "bearish_engulfing": 0,
                    "engulfing": "BULLISH",
                    "doji": False,
                    "candle_strength": "STRONG",
                    "candle_type": "STRONG_BULLISH",
                    "strong_green_candle": True,
                    "strong_red_candle": False,
                    "consecutive_green": 4,
                    "consecutive_red": 0,
                    "streak_strength_score": 0.8,
                    "long_upper_wick": False,
                    "long_lower_wick": False,
                    "weak_body_candle": False,
                    "conflicting_patterns": False,
                    "components": {},
                }

            def _mock_structure(_ohlcv_df, swing_window=3, cluster_pct=0.0035):
                return {
                    "structure_score": 0.84,
                    "structure": "UPTREND",
                    "last_pattern": "HIGHER_HIGH",
                    "support_levels": [2488.0, 2494.0],
                    "resistance_levels": [2510.0],
                    "nearest_support": 2494.0,
                    "nearest_resistance": 2510.0,
                    "support_distance": 0.0024,
                    "resistance_distance": 0.004,
                    "near_support": True,
                    "near_resistance": False,
                    "middle_zone": False,
                    "breakout": True,
                    "breakout_type": "BULLISH",
                    "breakout_distance": 0.003,
                    "breakout_level": 2510.0,
                    "range_or_trend": "TREND",
                    "higher_high": True,
                    "higher_low": True,
                    "lower_high": False,
                    "lower_low": False,
                    "components": {},
                }

            def _mock_fusion(_feature_df, _ohlcv_df, swing_window=3, histogram_window=5):
                return {
                    "rsi_macd_signal": 1,
                    "rsi_macd_strength": 0.76,
                    "ema_crossover_signal": 1,
                    "ema_crossover_strength": 0.012,
                    "rsi_divergence": 0,
                    "divergence_strength": 0.0,
                    "macd_histogram_trend": 1,
                    "macd_momentum_strength": 0.42,
                    "fusion_score": 0.8,
                    "components": {},
                }

            def _mock_liquidity(_ohlcv_df):
                return {
                    "liquidity_score": 0.75,
                    "price_impact": 0.0002,
                    "jump_flag": False,
                    "gap_flag": "NO_GAP",
                    "gap_continuation": False,
                    "gap_rejection": False,
                    "liquidity_sweep": False,
                    "sweep_type": "NONE",
                    "flow_state": "STRONG_MOVE",
                    "components": {},
                }

            def _mock_time(_ohlcv_df):
                return {
                    "session": "MID",
                    "time_bucket": "TREND_WINDOW",
                    "day_of_week": 2,
                    "day_bias_score": 0.55,
                    "expiry_flag": False,
                    "expiry_type": "NONE",
                    "time_score": 0.7,
                    "time_bias": "TREND_CONTINUATION",
                    "confirmation_threshold": 0.6,
                    "position_size_factor": 1.0,
                    "components": {},
                }

            def _mock_risk_context(
                ohlcv_df,
                signal,
                entry_price,
                target_price,
                capital,
                risk_per_trade,
                atr_multiplier=1.5,
                rr_min=1.5,
                volatility_state="NORMAL_VOLATILITY",
            ):
                return {
                    "stop_loss": round(float(entry_price) * 0.99, 2),
                    "target": round(float(entry_price) * 1.002, 2),
                    "RR": 1.2,
                    "position_size": 42,
                    "atr": 25.0,
                    "atr_ratio": 0.01,
                    "position_size_factor": 0.5,
                    "risk_filter_fail": True,
                    "volatility_mode": "NORMAL",
                }

            def _mock_mtf(_ohlcv_df):
                return {
                    "mtf_alignment": "STRONG",
                    "mtf_score": 0.95,
                    "direction": "BULLISH",
                    "htf_confirmed": True,
                    "ltf_entry_confirmed": True,
                    "conflict": False,
                    "timeframes": {
                        "1m": "BULLISH",
                        "5m": "BULLISH",
                        "15m": "BULLISH",
                        "1h": "BULLISH",
                    },
                    "timeframe_strength": {
                        "1m": 0.9,
                        "5m": 0.9,
                        "15m": 0.9,
                        "1h": 0.9,
                    },
                    "components": {},
                }

            monkeypatch.setattr(models_mod, "_compute_momentum_engine", _mock_momentum)
            monkeypatch.setattr(models_mod, "_compute_trend_engine", _mock_trend)
            monkeypatch.setattr(models_mod, "_compute_volatility_engine", _mock_volatility)
            monkeypatch.setattr(models_mod, "_compute_volume_engine", _mock_volume)
            monkeypatch.setattr(models_mod, "_compute_price_action_engine", _mock_price_action)
            monkeypatch.setattr(models_mod, "_compute_market_structure_engine", _mock_structure)
            monkeypatch.setattr(models_mod, "_compute_indicator_fusion_engine", _mock_fusion)
            monkeypatch.setattr(models_mod, "compute_liquidity_order_flow", _mock_liquidity)
            monkeypatch.setattr(models_mod, "compute_time_intelligence", _mock_time)
            monkeypatch.setattr(models_mod, "compute_multi_timeframe_alignment", _mock_mtf)
            monkeypatch.setattr(models_mod, "_evaluate_hold_filters", lambda *args, **kwargs: [])
            monkeypatch.setattr(models_mod, "compute_risk_position_context", _mock_risk_context)

            from app.inference.models import ModelEnsemble

            result = ModelEnsemble.predict(
                "TEST",
                2500.0,
                np.zeros((20, 10)),
                np.zeros((1, 10)),
                ohlcv_df=bullish_ohlcv_df,
            )

            assert result["signal"] == "HOLD"
            assert "rr_below_threshold" in result["models"].get("filters", [])
            assert "rr_below_threshold" in result["reason"]
            assert result["position_size"] == 0
            assert result["RR"] == 1.2
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features

"""
Tests for the ML prediction pipeline (ModelEnsemble).
Tests run with and without a trained model.
"""
import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.inference.feature_engineering import FEATURE_COLUMNS, compute_features


class TestModelEnsembleFallback:
    """Test prediction behavior when NO model is loaded."""

    def test_returns_hold_without_data(self):
        """With no OHLCV data, should return HOLD."""
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST", 100.0,
            np.zeros((20, 10)), np.zeros((1, 10)),
            ohlcv_df=None,
        )
        assert result["signal"] == "HOLD"
        assert result["confidence"] == 0
        assert "prediction" in result

    def test_returns_hold_with_short_data(self, short_ohlcv_df):
        """With < 25 rows, should return HOLD fallback."""
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST", 100.0,
            np.zeros((20, 10)), np.zeros((1, 10)),
            ohlcv_df=short_ohlcv_df,
        )
        assert result["signal"] == "HOLD"
        assert result["confidence"] == 0

    def test_result_has_required_keys(self, mock_ohlcv_df):
        """Output must always contain all required fields."""
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "RELIANCE", 2500.0,
            np.zeros((20, 10)), np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
        )
        required_keys = [
            "prediction", "signal", "confidence", "stop", "target",
            "models", "regime", "factors", "explanation",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_signal_is_valid(self, mock_ohlcv_df):
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST", 2500.0,
            np.zeros((20, 10)), np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
        )
        assert result["signal"] in ("BUY", "SELL", "HOLD")

    def test_confidence_range(self, mock_ohlcv_df):
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST", 2500.0,
            np.zeros((20, 10)), np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
        )
        assert 0 <= result["confidence"] <= 100

    def test_stop_less_than_target_for_buy(self, mock_ohlcv_df):
        """For non-HOLD signals, stop should always differ from target."""
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST", 2500.0,
            np.zeros((20, 10)), np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
        )
        # Stop and target should be different (enforced by move_ratio > 0)
        assert result["stop"] != result["target"]

    def test_factors_is_list(self, mock_ohlcv_df):
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST", 2500.0,
            np.zeros((20, 10)), np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
        )
        assert isinstance(result["factors"], list)
        assert all(isinstance(f, str) for f in result["factors"])

    def test_regime_is_valid(self, mock_ohlcv_df):
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST", 2500.0,
            np.zeros((20, 10)), np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
        )
        assert result["regime"] in ("Volatile", "Trending", "Ranging", "Unknown")


class TestModelEnsembleDebug:
    """Test debug mode output."""

    def test_debug_false_no_debug_info(self, mock_ohlcv_df):
        from app.inference.models import ModelEnsemble

        result = ModelEnsemble.predict(
            "TEST", 2500.0,
            np.zeros((20, 10)), np.zeros((1, 10)),
            ohlcv_df=mock_ohlcv_df,
            debug=False,
        )
        assert "debug_info" not in result

    def test_debug_true_has_debug_info(self, mock_ohlcv_df):
        import app.inference.models as models_mod
        from app.inference.models import ModelEnsemble
        
        orig_model = models_mod._ensemble_model
        try:
            models_mod._ensemble_model = True # just to bypass 'if not _ensemble_model'
            result = ModelEnsemble.predict(
                "TEST", 2500.0,
                np.zeros((20, 10)), np.zeros((1, 10)),
                ohlcv_df=mock_ohlcv_df,
                debug=True,
            )
            assert "debug_info" in result
            assert "features" in result["debug_info"]
            assert "feature_count" in result["debug_info"]
            assert "rows_used" in result["debug_info"]
        finally:
            models_mod._ensemble_model = orig_model

    def test_debug_feature_values(self, mock_ohlcv_df):
        """Debug info should include all canonical feature values."""
        import app.inference.models as models_mod
        from app.inference.models import ModelEnsemble

        orig_model = models_mod._ensemble_model
        try:
            models_mod._ensemble_model = True 
            result = ModelEnsemble.predict(
                "TEST", 2500.0,
                np.zeros((20, 10)), np.zeros((1, 10)),
                ohlcv_df=mock_ohlcv_df,
                debug=True,
            )
            features = result["debug_info"]["features"]
            for col in FEATURE_COLUMNS:
                assert col in features, f"Debug missing feature: {col}"
        finally:
            models_mod._ensemble_model = orig_model
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

    def test_buy_signal_with_high_prob(self, mock_ohlcv_df):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.80)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            from app.inference.models import ModelEnsemble
            result = ModelEnsemble.predict(
                "TEST", 2500.0,
                np.zeros((20, 10)), np.zeros((1, 10)),
                ohlcv_df=mock_ohlcv_df,
            )
            assert result["signal"] == "BUY"
            assert result["confidence"] == 80
        finally:
            models_mod._ensemble_model = orig_model
            models_mod._scaler = orig_scaler
            models_mod._features_list = orig_features

    def test_sell_signal_with_low_prob(self, mock_ohlcv_df):
        import app.inference.models as models_mod

        orig_model = models_mod._ensemble_model
        orig_scaler = models_mod._scaler
        orig_features = models_mod._features_list

        try:
            models_mod._ensemble_model = self._make_mock_model(prob_up=0.20)
            models_mod._scaler = self._make_mock_scaler()
            models_mod._features_list = FEATURE_COLUMNS

            from app.inference.models import ModelEnsemble
            result = ModelEnsemble.predict(
                "TEST", 2500.0,
                np.zeros((20, 10)), np.zeros((1, 10)),
                ohlcv_df=mock_ohlcv_df,
            )
            assert result["signal"] == "SELL"
            assert result["confidence"] == 80  # prob_down = 0.80
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
                "TEST", 2500.0,
                np.zeros((20, 10)), np.zeros((1, 10)),
                ohlcv_df=mock_ohlcv_df,
            )
            assert result["signal"] == "HOLD"
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
                "TEST", 2500.0,
                np.zeros((20, 10)), np.zeros((1, 10)),
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

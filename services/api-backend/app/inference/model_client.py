"""Wrapper for model inference; used by routes and WS relay."""

from .runner import PredictionResult, predict_symbol

__all__ = ["predict_symbol", "PredictionResult"]

"""Wrapper for model inference; used by routes and WS relay."""
from .runner import predict_symbol, PredictionResult

__all__ = ["predict_symbol", "PredictionResult"]

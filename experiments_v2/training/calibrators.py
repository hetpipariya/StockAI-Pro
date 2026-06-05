"""
experiments_v2/training/calibrators.py
=======================================
Shared calibrator classes.
Import this module wherever joblib.load() needs to deserialize
PlattCalibrator or SoftmaxCalibrator objects.

These must be importable from a STABLE path so joblib can
reconstruct them from pickle — never define them only inside
a training script.
"""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier


class PlattCalibrator:
    """
    Manual Platt scaling for binary XGBoost.
    Fits LogisticRegression on top of XGBoost P(class=1) on a held-out set.
    Base model is frozen — no re-training, no calibration leakage.
    """
    def __init__(self, base_model: XGBClassifier):
        self.base_model = base_model
        self.lr         = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
        self.classes_   = np.array([0, 1])

    def fit(self, X: np.ndarray, y: np.ndarray) -> "PlattCalibrator":
        raw = self.base_model.predict_proba(X)[:, 1].reshape(-1, 1)
        self.lr.fit(raw, y)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        raw = self.base_model.predict_proba(X)[:, 1].reshape(-1, 1)
        return self.lr.predict_proba(raw)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.predict_proba(X).argmax(axis=1)


class SoftmaxCalibrator:
    """
    Manual calibration for 3-class XGBoost.
    Fits multinomial LogisticRegression on raw softmax probabilities.
    Base model is frozen — no re-training.
    """
    def __init__(self, base_model: XGBClassifier):
        self.base_model = base_model
        self.lr         = LogisticRegression(
            C=1.0, solver="lbfgs", max_iter=1000, random_state=42
        )
        self.classes_   = np.array([0, 1, 2])

    def fit(self, X: np.ndarray, y: np.ndarray) -> "SoftmaxCalibrator":
        raw = self.base_model.predict_proba(X)
        self.lr.fit(raw, y)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        raw = self.base_model.predict_proba(X)
        return self.lr.predict_proba(raw)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.predict_proba(X).argmax(axis=1)

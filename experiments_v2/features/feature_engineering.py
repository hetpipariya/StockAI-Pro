"""Canonical experiments_v2 feature-engineering API.

This module is a thin adapter over the backend-native feature stack so
training and runtime share one strict 20-feature contract.
"""

from app.inference.feature_engineering import *  # noqa: F401,F403

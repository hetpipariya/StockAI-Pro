"""
experiments_v2/features/__init__.py
Exposes the leakage-free feature engineering API at the package level.

Usage:
    from experiments_v2.features.feature_engineering import (
        compute_base_features,
        build_1h_context,
        merge_5m_with_1h_context,
        validate_feature_contract,
        finalize_feature_matrix,
        load_timeframe_csv_folder,
        TREND_FEATURE_COLUMNS,
        ENTRY_FEATURE_COLUMNS,
        BASE_5M_FEATURE_COLUMNS,
        CONTEXT_1H_FEATURE_COLUMNS,
        DataConfig,
    )
"""
from experiments_v2.features.feature_engineering import (  # noqa: F401
    BASE_5M_FEATURE_COLUMNS,
    CONTEXT_1H_FEATURE_COLUMNS,
    ENTRY_FEATURE_COLUMNS,
    TREND_FEATURE_COLUMNS,
    DataConfig,
    build_1h_context,
    check_inference_compatibility,
    compute_base_features,
    finalize_feature_matrix,
    load_timeframe_csv_folder,
    merge_5m_with_1h_context,
    validate_feature_contract,
)

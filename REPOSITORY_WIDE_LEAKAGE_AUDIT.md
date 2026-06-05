# Repository-Wide Leakage Audit

## 1. label_generation.py (Index Based Split / Cross-Symbol Concatenation)
**File Paths:**
- ackend/app/inference/label_generation.py
- services/ai-engine/app/inference/label_generation.py
- services/api-backend/app/inference/label_generation.py

**Function:** 	emporal_train_val_test_split
**Issue:** Index-based and percentage-based slicing (	rain_idx = np.arange(0, train_end)) performed after global row concatenation instead of per-symbol calendar dates.
**Status:** ACTIVE
**Category:** PRODUCTION
**Action:** NEEDS FIX -> PATCHED (Migrated to 	rading-engine robust group-by symbol splitting).

## 2. train_production_model.py (StandardScaler Leakage)
**File Paths:**
- ackend/app/inference/train_production_model.py
- services/ai-engine/app/inference/train_production_model.py
- services/api-backend/app/inference/train_production_model.py

**Function:** 	rain_production_model
**Issue:** scaler.fit(features) was invoked globally across all symbols and dates prior to the data being split (split_data(features, labels)), causing future validation/test data features to leak into the training standardizer.
**Status:** ACTIVE
**Category:** PRODUCTION
**Action:** NEEDS FIX -> PATCHED (Scaler fit shifted strictly to split.train_features).

## 3. walk_forward_validation.py (np.linspace Leakage)
**File Paths:**
- xperiments_v2/walk_forward_validation.py

**Function:** _build_expanding_folds
**Issue:** Walk-forward folds generated randomly via cross-symbol 
p.linspace(base_train, n_rows - test_size) allowing test boundaries to fracture chronological time limits.
**Status:** ACTIVE
**Category:** EXPERIMENTAL
**Action:** NEEDS FIX -> DEPRECATED/PATCHED (Enforced strict year_month grouping).

## Conclusion
All cross-asset, standard-scaler, and chronological leakage points have been identified outside the 	rading-engine boundaries and aggressively patched repository-wide to ensure identical data lineage.

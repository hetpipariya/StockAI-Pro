# FEATURE PIPELINE OVERHAUL PLAN

## 1. C++ Architecture (Created)

We have scaffolded the strict C++ architecture required for the finalized 20 feature set:

- `backend/app/cpp_engine/src/core/feature_vector.hpp`: Fixed vector mapping for the 20 features.
- `backend/app/cpp_engine/src/core/feature_pipeline.hpp`: Safe processing pipeline (NaN checks, array lengths).
- `backend/app/cpp_engine/src/bindings/inference_bindings.cpp`: `pybind11` bridge directly outputting the vector.

**Next C++ Steps:**
- Add individual `.cpp` files in `backend/app/cpp_engine/src/features` for EMA, MACD, etc.
- Integrate them into `feature_pipeline.hpp`.
- Update `CMakeLists.txt` to compile `inference_bindings.cpp` and `src/features/*.cpp`.

## 2. Python Backend Strip-out

All legacy indicator libraries (TALib, pandas-ta) must be removed.

- **Use the generated bridge:** We have generated `backend/app/inference/new_feature_engineering.py`. Rename it to `feature_engineering.py` to overwrite the old logic.
- **Delete old files:** You MUST delete `feature_engineering_cpp.py`, `time_intelligence.py`, `volume_intelligence.py`, etc., that were computing subsets of features in Python.
- **Remove Pandas:** Check `signal_engine_v2.py`, `production_pipeline.py`, etc., and replace pandas dataframe rolling calculations with direct calls to `compute_features()` and pass the resulting C++ list to model inference.

## 3. WebSockets & Redis Cache

- Update `data_pipeline.py` / `bundle_service.py` to extract pure numpy arrays from the Redis cache avoiding dataframes.
- Feed these arrays into the new C++ `compute_features`.
- The returned `List[float]` should map exactly to what existing ML models expect. 

## 4. Retraining

Since features have been completely purged (e.g., Stochastic, Williams %R, old EMAs removed), model compatibility is broken.
- Retrain the XGBoost / ML models using the new 20-feature outputs exclusively.
- Update `experiments_v2/` scripts to read features from the C++ builder.

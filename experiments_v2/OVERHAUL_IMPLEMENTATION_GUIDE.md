# experiments_v2 E2E Overhaul Guide

## What was implemented

1. Data sanitization is now market-aware:
- IST-normalized timestamps.
- Weekday and NSE/BSE session filtering (`09:15` to `15:30`).
- Raw zero-volume rows removed.
- Missing intraday bars are reindexed and forward-filled from prior close only (no look-ahead).

2. Feature engineering expanded to 103 features:
- Canonical backend base features.
- Statistical tensors (z-score, VWAP distance, return distribution).
- Institutional flow (RVOL, CMF, OBV, money-flow vectors).
- Volatility regimes (ATR normalization, BB squeeze, realized volatility).
- Price geometry (wick/body ratios, streak exhaustion).
- Cyclic time intelligence (sin/cos session encodings for Indian market hours).
- Interaction tensors and context signals.

3. Labeling switched to Triple Barrier Method:
- Profit barrier: `+2 x ATR`.
- Stop barrier: `-1 x ATR`.
- Time barrier:
  - `4` bars for `1h`.
  - `12` bars for `5m` (1 hour).

4. Multi-timeframe synchronization:
- `1h` features are merged onto `5m` rows via backward `merge_asof`.
- Context columns use `_1h_ctx` suffix and additional context flags.

5. Training stack upgraded:
- Walk-forward split:
  - Train: `<= 2024`.
  - Holdout Test: `>= 2025`.
- Walk-forward folds built from temporal years.
- Optuna Bayesian tuning over `xgboost` / `lightgbm` candidates.
- Final artifacts exported both as:
  - backend-compatible `model.pkl/scaler.pkl/features.pkl` bundle.
  - direct `.joblib` in `backend/app/inference/`.

## Updated modules

- `pipeline/cleaner.py`
- `features/feature_engineering.py`
- `fusion/fusion_labeling.py`
- `pipeline/label_generator.py`
- `pipeline/dataset_builder.py`
- `models/train.py`
- `models/evaluate.py`
- `train_5m.ipynb`
- `train_1h.ipynb`

## Install dependencies

```bash
pip install -r experiments_v2/requirements.txt
```

## Build datasets (5m + 1h)

```bash
python -m experiments_v2.pipeline.dataset_builder \
  --raw-dir experiments_v2/data/raw \
  --processed-dir experiments_v2/data/processed \
  --timeframes 5m,1h
```

Outputs:
- `experiments_v2/data/processed/training_dataset_5m.csv`
- `experiments_v2/data/processed/training_dataset_1h.csv`
- `experiments_v2/data/processed/training_dataset.csv`

### Memory-safe chunked build (optional)

If your machine cannot ingest the full corpus in one pass, use symbol allowlists and/or file caps:

```bash
python -m experiments_v2.pipeline.dataset_builder \
  --raw-dir experiments_v2/data/raw \
  --processed-dir experiments_v2/data/processed \
  --timeframes 5m,1h \
  --symbols ABFRL,ABSLAMC,ACC \
  --max-files-per-timeframe 50
```

## Train 5m model (with 1h context)

```bash
python -m experiments_v2.models.train \
  --dataset experiments_v2/data/processed/training_dataset_5m.csv \
  --target-timeframe 5m \
  --optuna-trials 40 \
  --model-candidates xgboost,lightgbm \
  --model-out experiments_v2/outputs/models/model_5m.joblib \
  --report-out experiments_v2/outputs/reports/train_report_5m.json \
  --backend-model-dir backend/models/timeframe_5m \
  --backend-inference-artifact backend/app/inference/model_5m.joblib
```

## Train 1h model

```bash
python -m experiments_v2.models.train \
  --dataset experiments_v2/data/processed/training_dataset_1h.csv \
  --target-timeframe 1h \
  --optuna-trials 40 \
  --model-candidates xgboost,lightgbm \
  --model-out experiments_v2/outputs/models/model_1h.joblib \
  --report-out experiments_v2/outputs/reports/train_report_1h.json \
  --backend-model-dir backend/models/timeframe_1h \
  --backend-inference-artifact backend/app/inference/model_1h.joblib
```

## Notebook runbooks

- `experiments_v2/train_5m.ipynb`
- `experiments_v2/train_1h.ipynb`

Both notebooks now call the same production modules above (no duplicated inline training logic).

import sys
from pathlib import Path

sys.path.append(str((Path(__file__).parent / "backend").resolve()))
from app.inference.models import ModelEnsemble
import pandas as pd
import numpy as np

# Create a dummy bullish OHLCV structure
bull_data = []
close_price = 100.0
for i in range(50):
    close_price += np.random.uniform(0.1, 0.5)
    bull_data.append({
        "time": f"2023-01-01T10:{i:02d}:00Z",
        "open": close_price - 0.2,
        "high": close_price + 0.3,
        "low": close_price - 0.3,
        "close": close_price,
        "volume": 100 + i * 10
    })

# Add a huge volume spike at the end to confirm
bull_data[-1]["volume"] = 5000
bull_data[-1]["close"] += 1.0

# Run prediction
print("--- BULLISH TEST ---")
res_bull = ModelEnsemble.predict("TEST", bull_data[-1]["close"], np.zeros((20,10)), np.zeros((1,10)), pd.DataFrame(bull_data))
import json
print(json.dumps(res_bull, indent=2))

# Create a mixed OHLCV structure
mixed_data = []
close_price = 100.0
for i in range(50):
    close_price += np.random.uniform(-0.5, 0.5)
    mixed_data.append({
        "time": f"2023-01-01T10:{i:02d}:00Z",
        "open": close_price - 0.2,
        "high": close_price + 0.3,
        "low": close_price - 0.3,
        "close": close_price,
        "volume": 100 + np.random.uniform(0, 50)
    })

print("\n--- MIXED TEST ---")
res_mixed = ModelEnsemble.predict("TEST", mixed_data[-1]["close"], np.zeros((20,10)), np.zeros((1,10)), pd.DataFrame(mixed_data))
print(json.dumps(res_mixed, indent=2))


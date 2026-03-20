import os
import pandas as pd
import numpy as np
from xgboost import XGBClassifier
from sklearn.preprocessing import RobustScaler
import warnings

warnings.filterwarnings('ignore')

# --- CONFIGURATION ---
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "train_data.csv")
SLIPPAGE_BPS = 0.02 / 100 
BROKERAGE_BPS = 0.03 / 100 
TOTAL_COST = SLIPPAGE_BPS + BROKERAGE_BPS

RISK_PER_TRADE = 0.01  
REWARD_RISK_RATIO = 1.5
ATR_STOP_MULTIPLIER = 1.5

print("========================================")
print("   DYNAMIC INTRADAY AI BACKTEST ENGINE  ")
print("========================================")

if not os.path.exists(DATA_FILE):
    raise FileNotFoundError("Run build_dataset.py first!")

# 1. LOAD DATA
df = pd.read_csv(DATA_FILE)
df['date'] = pd.to_datetime(df['date'])
df.sort_values(by=['ticker', 'date'], inplace=True)
df.reset_index(drop=True, inplace=True)

# 2. FEATURE ENGINEERING
def engineer_features(g):
    g = g.copy()
    c = g['close']
    h = g['high']
    l = g['low']
    
    g['ema_9'] = c.ewm(span=9, adjust=False).mean()
    g['ema_21'] = c.ewm(span=21, adjust=False).mean()
    g['ema_50'] = c.ewm(span=50, adjust=False).mean()
    
    delta = c.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    g['rsi_14'] = 100 - (100 / (1 + rs))
    
    vol_ma = g['volume'].rolling(20, min_periods=1).mean()
    g['volume_spike'] = (g['volume'] > (vol_ma * 2.0)).astype(int)
    
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    g['true_range'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    g['atr_14'] = g['true_range'].rolling(14).mean()
    
    g['price_change'] = c - g['open']
    safe_c = c.clip(lower=1e-5)
    g['volatility'] = (h - l) / safe_c
    g['momentum'] = c - c.shift(3)
    g['rolling_mean_5'] = c.rolling(5, min_periods=1).mean()
    g['rolling_std_5'] = c.rolling(5, min_periods=2).std()
    
    return g

new_dfs = []
for t, group in df.groupby('ticker'):
    new_dfs.append(engineer_features(group))
df = pd.concat(new_dfs).reset_index(drop=True)

df.replace([np.inf, -np.inf], np.nan, inplace=True)
df.fillna(0, inplace=True)
df.sort_values(by='date', inplace=True)
df.reset_index(drop=True, inplace=True)

# 3. TRAIN / TEST SPLIT
exclude_cols = ['ticker', 'date', 'target', 'true_range']
feature_cols = [c for c in df.columns if c not in exclude_cols and np.issubdtype(df[c].dtype, np.number)]

X = df[feature_cols].values
y = df['target'].values
split_idx = int(len(df) * 0.8)

X_train, X_test = X[:split_idx], X[split_idx:]
y_train, y_test = y[:split_idx], y[split_idx:]
df_test = df.iloc[split_idx:].copy()

print(f"Training XGBoost on {len(X_train)} samples...")

scaler = RobustScaler()
X_train_sc = np.nan_to_num(scaler.fit_transform(X_train))
X_test_sc = np.nan_to_num(scaler.transform(X_test))

model = XGBClassifier(n_estimators=100, max_depth=5, learning_rate=0.05, eval_metric='logloss')
model.fit(X_train_sc, y_train)

# 4. PREDICTIONS & SIGNALS
df_test['ml_pred'] = model.predict(X_test_sc)

# ENTRY CONDITION: High-Confirmation Breakout 
df_test['signal_buy'] = (
    (df_test['ml_pred'] == 1) & 
    (df_test['close'] > df_test['ema_50']) &
    (df_test['ema_9'] > df_test['ema_21']) &
    (df_test['volume_spike'] == 1) &
    (df_test['rsi_14'] > 55) & (df_test['rsi_14'] < 75) &
    (df_test['atr_14'] > df_test['close'] * 0.003) 
)

df_test['signal_sell'] = (
    (df_test['ml_pred'] == 0) & 
    (df_test['close'] < df_test['ema_50']) &
    (df_test['ema_9'] < df_test['ema_21']) &
    (df_test['volume_spike'] == 1) &
    (df_test['rsi_14'] < 45) & (df_test['rsi_14'] > 25) &
    (df_test['atr_14'] > df_test['close'] * 0.003)
)

# 5. RISK PARAMETER SIMULATOR
capital = 100000.0
peak_capital = capital
drawdown = 0.0

trades = []
winning_trades = 0

print("Generating Simulated High-Frequency Execution paths...")
for ticker, group in df_test.groupby('ticker'):
    in_pos = False
    trade_type = ""
    entry_price = 0.0
    stop_price = 0.0
    target_price = 0.0
    pos_size = 0.0  
    locked_stop_dist = 0.0
    
    for idx, row in group.iterrows():
        c = row['close']
        h = row['high']
        l = row['low']
        atr = row['atr_14']
        
        if in_pos:
            exit_flag = False
            exit_price = 0.0
            
            if trade_type == "BUY":
                if c > entry_price + locked_stop_dist:
                    new_stop = c - locked_stop_dist
                    if new_stop > stop_price: stop_price = new_stop
                    
                if h >= target_price: 
                    exit_price = target_price
                    exit_flag = True
                elif l <= stop_price:
                    exit_price = stop_price
                    exit_flag = True
                    
            elif trade_type == "SELL":
                if c < entry_price - locked_stop_dist:
                    new_stop = c + locked_stop_dist
                    if new_stop < stop_price: stop_price = new_stop
                    
                if l <= target_price:
                    exit_price = target_price
                    exit_flag = True
                elif h >= stop_price:
                    exit_price = stop_price
                    exit_flag = True
                    
            if exit_flag:
                if trade_type == "BUY": raw_pnl = (exit_price - entry_price) / entry_price
                else: raw_pnl = (entry_price - exit_price) / entry_price
                
                net_move = raw_pnl - (2 * TOTAL_COST)
                capital_pnl = capital * pos_size * net_move
                capital += capital_pnl
                
                if net_move > 0: winning_trades += 1
                if capital > peak_capital: peak_capital = capital
                
                current_dd = (peak_capital - capital) / peak_capital
                if current_dd > drawdown: drawdown = current_dd
                    
                trades.append(capital_pnl)
                in_pos = False
                
        if not in_pos and atr > 0:
            if row['signal_buy']:
                in_pos = True
                trade_type = "BUY"
                entry_price = c
                
                locked_stop_dist = ATR_STOP_MULTIPLIER * atr
                stop_price = c - locked_stop_dist
                target_price = c + (locked_stop_dist * REWARD_RISK_RATIO)
                
                max_shares = (capital * RISK_PER_TRADE) / locked_stop_dist
                pos_size = min(1.0, (max_shares * entry_price) / capital)
                
            elif row['signal_sell']:
                in_pos = True
                trade_type = "SELL"
                entry_price = c
                
                locked_stop_dist = ATR_STOP_MULTIPLIER * atr
                stop_price = c + locked_stop_dist
                target_price = c - (locked_stop_dist * REWARD_RISK_RATIO)
                
                max_shares = (capital * RISK_PER_TRADE) / locked_stop_dist
                pos_size = min(1.0, (max_shares * entry_price) / capital)

# 6. OUTPUT METRICS
win_rate = (winning_trades / len(trades) * 100) if trades else 0
roi = ((capital - 100000.0) / 100000.0) * 100

print("\\n========================================")
print(f"Total Trades: {len(trades)}")
print(f"Win Rate:     {win_rate:.2f}%")
print(f"Net ROI %:    {roi:.2f}%")
print(f"Max Drawdown: {drawdown * 100:.2f}%")
print("========================================")

if roi > 0: print("SUCCESS: Dynamic System PROFITABLE under real-world ATR Trailing!")
else: print("WARNING: Strategy is mathematically bleeding.")

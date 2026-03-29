import os
import yfinance as yf
import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ==========================================
# CONFIGURATION
# ==========================================
# Set TEST_MODE = True to run exactly 10 stocks total for a fast sandbox test
# Set TEST_MODE = False for the full 20 x 8 pipeline (160 stocks approx)
TEST_MODE = False 

# Extended pool (~120 stocks) covering Nifty 50, Gainers, Losers, and specifically <₹40, <₹70, <₹100
STOCK_UNIVERSE = [
    # Nifty 50 Large Caps & Benchmarks
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "ITC.NS", "SBIN.NS", 
    "BHARTIARTL.NS", "BAJFINANCE.NS", "LT.NS", "KOTAKBANK.NS", "AXISBANK.NS", "HINDUNILVR.NS",
    "ASIANPAINT.NS", "MARUTI.NS", "SUNPHARMA.NS", "TITAN.NS", "TATASTEEL.NS", "ULTRACEMCO.NS", "TATAMOTORS.NS",
    "NTPC.NS", "POWERGRID.NS", "HCLTECH.NS", "WIPRO.NS", "BAJAJFINSV.NS", "ADANIENT.NS", "ADANIPORTS.NS",
    "ONGC.NS", "COALINDIA.NS", "JSWSTEEL.NS", "GRASIM.NS", "M&M.NS", "INDUSINDBK.NS", "BAJAJ-AUTO.NS",
    # Mix for volume, volatility, and prices (<40, <70, <100)
    "SUZLON.NS", "YESBANK.NS", "IDEA.NS", "IRFC.NS", "PNB.NS", "NHPC.NS", "RPOWER.NS", "JPPOWER.NS",
    "SOUTHBANK.NS", "TRIDENT.NS", "UCOBANK.NS", "RENUKA.NS", "VAKRANGEE.NS", "NBCC.NS", "BHEL.NS",
    "NATIONALUM.NS", "HUDCO.NS", "BANKBARODA.NS", "BANKINDIA.NS", "CENTRALBK.NS", "PUNJLLOYD.NS",
    "GMRINFRA.NS", "ZOMATO.NS", "PAYTM.NS", "NYKAA.NS", "LODHA.NS", "RVNL.NS", "IRCTC.NS", "IREDA.NS",
    "IDFCFIRSTB.NS", "IOB.NS", "MAHABANK.NS", "MRPL.NS", "TATACOMM.NS", "SAIL.NS", "NMDC.NS", 
    "BEL.NS", "HAL.NS", "SJVN.NS", "HCC.NS", "DISHTV.NS", "RCOM.NS", "GTLINFRA.NS", "PCJEWELLER.NS",
    "IFCI.NS", "JAICORPLTD.NS", "RECLTD.NS", "PFC.NS", "ABFRL.NS", "ZEEL.NS",
    "ASHOKLEY.NS", "CUMMINSIND.NS", "MRF.NS", "PAGEIND.NS", "BOSCHLTD.NS", "INDIGO.NS", "PIDILITIND.NS",
    "HDFCAMC.NS", "MUTHOOTFIN.NS", "CHOLAFIN.NS", "AUBANK.NS", "ABCAPITAL.NS", "ICICIPRULI.NS", "HDFCLIFE.NS",
    "SBILIFE.NS", "MOTHERSUMI.NS", "BATAINDIA.NS", "VOLTAS.NS", "HAVELLS.NS", "CROMPTON.NS"
]

NIFTY_50_POOL = STOCK_UNIVERSE[:50]  # The first chunk explicitly for large cap

if TEST_MODE:
    STOCK_UNIVERSE = STOCK_UNIVERSE[:10]
    LIMIT_PER_CATEGORY = 2  # Scaled down to ensure logic runs
else:
    LIMIT_PER_CATEGORY = 20

# ==========================================
# 1. DIRECTORY CREATION LOGIC
# ==========================================
def ensure_folders():
    """Create strict experiments/data/category folders safely."""
    base_dir = os.path.join(os.path.dirname(__file__), "data")
    folders = [
        "1_large_cap",
        "2_gainers",
        "3_losers",
        "4_under_70",
        "5_under_40",
        "6_under_100",
        "7_high_volume",
        "8_low_volume"
    ]
    for folder in folders:
        os.makedirs(os.path.join(base_dir, folder), exist_ok=True)
    return base_dir

# ==========================================
# 2. FEATURE ENGINEERING & LABELING
# ==========================================
def process_data(df):
    """Clean data, add technicals (EMA, RSI, MACD, VWAP), and label."""
    df = df.copy()
    if len(df) < 50:
        return None  # Needs enough history

    # Standardize columns
    df.columns = [c.lower() for c in df.columns]

    # EMA 20, 50
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()

    # RSI 14
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi_14'] = 100 - (100 / (1 + rs))

    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

    # VWAP (Formula: Cumulative (Price * Volume) / Cumulative Volume)
    q = df['volume']
    p = (df['high'] + df['low'] + df['close']) / 3
    df['vwap'] = (p * q).cumsum() / q.cumsum()

    df.dropna(inplace=True)

    # LABELING: 1 if next day close > current close else 0
    df['target'] = np.where(df['close'].shift(-1) > df['close'], 1, 0)
    df.drop(df.tail(1).index, inplace=True) # Drop last row since it has no "tomorrow"

    return df

# ==========================================
# 3. PIPELINE
# ==========================================
def run_pipeline():
    base_dir = ensure_folders()
    master_frames = []
    
    # STEP 1 & 2: Download 60 Days Intraday data (15m candles)
    logging.info(f"Fetching 60 days of 15m intraday data for {len(STOCK_UNIVERSE)} stocks ...")
    bulk_data = yf.download(STOCK_UNIVERSE, period="60d", interval="15m", group_by='ticker', threads=True, progress=False)
    
    # STEP 3: Calculate Metrics (Return, Avg Volume, Last Price)
    metrics = []
    processed_dfs = {}

    for ticker in STOCK_UNIVERSE:
        try:
            if len(STOCK_UNIVERSE) == 1:
                df = bulk_data.copy()
            else:
                if ticker not in bulk_data.columns.levels[0]:
                    continue
                df = bulk_data[ticker].copy()
            
            df.dropna(subset=['Close'], inplace=True)
            if len(df) < 50:
                continue

            last_price = df['Close'].iloc[-1]
            first_price = df['Close'].iloc[0]
            ret_60d = ((last_price - first_price) / first_price) * 100
            avg_vol = df['Volume'].mean()

            # Process features immediately to save time
            feat_df = process_data(df)
            if feat_df is None or len(feat_df) == 0:
                continue

            # Keep for Master saving
            feat_df.reset_index(inplace=True)
            for c in feat_df.columns:
                if str(c).lower() in ['date', 'datetime', 'index']:
                    feat_df.rename(columns={c: 'date'}, inplace=True)
                    break
            
            # Keep Intraday Timestamp precision 
            feat_df['date'] = pd.to_datetime(feat_df['date'], utc=True).dt.strftime('%Y-%m-%d %H:%M:%S')
            feat_df.insert(0, 'ticker', ticker.replace('.NS', ''))
            
            processed_dfs[ticker] = feat_df
            
            metrics.append({
                'ticker': ticker,
                'last_price': last_price,
                'ret_60d': ret_60d,
                'avg_volume': avg_vol
            })
        except Exception as e:
            logging.warning(f"Skipping {ticker} due to error: {e}")
            continue

    metrics_df = pd.DataFrame(metrics)
    if metrics_df.empty:
        logging.error("No data fetched. Aborting.")
        return

    # Helper function matching requirements
    def get_category_tickers(name):
        if name == '1_large_cap':
            return metrics_df[metrics_df['ticker'].isin(NIFTY_50_POOL)]['ticker'].tolist()
        elif name == '2_gainers':
            return metrics_df.sort_values('ret_60d', ascending=False)['ticker'].tolist()
        elif name == '3_losers':
            return metrics_df.sort_values('ret_60d', ascending=True)['ticker'].tolist()
        elif name == '4_under_70':
            return metrics_df[metrics_df['last_price'] < 70].sort_values('ret_60d', ascending=False)['ticker'].tolist()
        elif name == '5_under_40':
            return metrics_df[metrics_df['last_price'] < 40].sort_values('ret_60d', ascending=False)['ticker'].tolist()
        elif name == '6_under_100':
            return metrics_df[metrics_df['last_price'] < 100].sort_values('ret_60d', ascending=False)['ticker'].tolist()
        elif name == '7_high_volume':
            return metrics_df.sort_values('avg_volume', ascending=False)['ticker'].tolist()
        elif name == '8_low_volume':
            return metrics_df.sort_values('avg_volume', ascending=True)['ticker'].tolist()
        return []

    # STEP 4: Filter Categories and Save exactly LIMIT_PER_CATEGORY (20)
    for category in ["1_large_cap", "2_gainers", "3_losers", "4_under_70", "5_under_40", "6_under_100", "7_high_volume", "8_low_volume"]:
        tickers_list = get_category_tickers(category)
        
        # Take exactly X stocks
        selected_tickers = tickers_list[:LIMIT_PER_CATEGORY]
        
        cat_dir = os.path.join(base_dir, category)
        saved_count = 0
        
        for t in selected_tickers:
            if t not in processed_dfs:
                continue
            
            # Save file
            df_to_save = processed_dfs[t]
            clean_ticker = t.replace('.NS', '')
            save_path = os.path.join(cat_dir, f"{clean_ticker}.csv")
            
            cols = ['date', 'open', 'high', 'low', 'close', 'volume', 
                    'ema_20', 'ema_50', 'rsi_14', 'macd', 'vwap', 'target']
            valid_cols = [c for c in cols if c in df_to_save.columns]
            
            df_to_save.to_csv(save_path, columns=valid_cols, index=False)
            master_frames.append(df_to_save)
            saved_count += 1
            
        logging.info(f"Saved {saved_count} stocks to '{category}/'")

    # Save Master File
    if master_frames:
        master_df = pd.concat(master_frames, ignore_index=True)
        # We drop duplicate entries since 1 stock might be in "Gainers" and "High Volume"
        master_df.drop_duplicates(subset=['ticker', 'date'], keep='first', inplace=True)
        
        master_csv = os.path.join(base_dir, "train_data.csv")
        master_df.to_csv(master_csv, index=False)
        logging.info("=" * 40)
        logging.info(f"PIPELINE COMPLETE - {len(master_df)} training rows across {master_df['ticker'].nunique()} unique stocks")
        logging.info(f"Master file saved at: {master_csv}")

if __name__ == "__main__":
    if TEST_MODE:
        logging.info("Running in TEST MODE (10 stock limit). To run full pipeline, set TEST_MODE = False in code.")
    run_pipeline()

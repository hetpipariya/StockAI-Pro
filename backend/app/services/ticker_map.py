"""
ticker_map.py
=============
100-stock NSE universe for StockAI Pro.
All tickers use the .NS suffix required by yfinance.
"""
from __future__ import annotations

# ── 100-Stock Universe (grouped by sector) ────────────────────────────────────

WATCHLIST: dict[str, str] = {
    # ── Banking & Finance (10) ────────────────────────────────────────────────
    "HDFC Bank":              "HDFCBANK.NS",
    "ICICI Bank":             "ICICIBANK.NS",
    "State Bank of India":    "SBIN.NS",
    "Kotak Mahindra Bank":    "KOTAKBANK.NS",
    "Axis Bank":              "AXISBANK.NS",
    "IndusInd Bank":          "INDUSINDBK.NS",
    "Bank of Baroda":         "BANKBARODA.NS",
    "Federal Bank":           "FEDERALBNK.NS",
    "IDFC First Bank":        "IDFCFIRSTB.NS",
    "Punjab National Bank":   "PNB.NS",

    # ── IT & Technology (9) ───────────────────────────────────────────────────
    "TCS":                    "TCS.NS",
    "Infosys":                "INFY.NS",
    "HCL Tech":               "HCLTECH.NS",
    "Wipro":                  "WIPRO.NS",
    "Tech Mahindra":          "TECHM.NS",
    "LTIMindtree":            "LTIM.NS",
    "Persistent Systems":     "PERSISTENT.NS",
    "Coforge":                "COFORGE.NS",
    "Mphasis":                "MPHASIS.NS",

    # ── Energy & Power (10) ───────────────────────────────────────────────────
    "Reliance Industries":    "RELIANCE.NS",
    "ONGC":                   "ONGC.NS",
    "Indian Oil Corporation": "IOC.NS",
    "BPCL":                   "BPCL.NS",
    "HPCL":                   "HPCL.NS",
    "GAIL":                   "GAIL.NS",
    "Oil India":              "OIL.NS",
    "Adani Green Energy":     "ADANIGREEN.NS",
    "NTPC":                   "NTPC.NS",
    "Power Grid":             "POWERGRID.NS",

    # ── Automobile (10) ───────────────────────────────────────────────────────
    "Maruti Suzuki":          "MARUTI.NS",
    "Tata Motors":            "TATAMOTORS.NS",
    "M&M":                    "M&M.NS",
    "Bajaj Auto":             "BAJAJ-AUTO.NS",
    "Eicher Motors":          "EICHERMOT.NS",
    "Hero MotoCorp":          "HEROMOTOCO.NS",
    "TVS Motor":              "TVSMOTOR.NS",
    "Ashok Leyland":          "ASHOKLEY.NS",
    "Bosch":                  "BOSCHLTD.NS",
    "Exide Industries":       "EXIDEIND.NS",

    # ── Infrastructure & Defence (10) ─────────────────────────────────────────
    "L&T":                    "LT.NS",
    "Adani Ports":            "ADANIPORTS.NS",
    "Siemens":                "SIEMENS.NS",
    "ABB India":              "ABB.NS",
    "BHEL":                   "BHEL.NS",
    "Bharat Electronics":     "BEL.NS",
    "HAL":                    "HAL.NS",
    "RITES":                  "RITES.NS",
    "IRCTC":                  "IRCTC.NS",
    "NBCC":                   "NBCC.NS",

    # ── Pharma & Healthcare (10) ──────────────────────────────────────────────
    "Sun Pharma":             "SUNPHARMA.NS",
    "Dr Reddys":              "DRREDDY.NS",
    "Cipla":                  "CIPLA.NS",
    "Divis Labs":             "DIVISLAB.NS",
    "Lupin":                  "LUPIN.NS",
    "Torrent Pharma":         "TORNTPHARM.NS",
    "Aurobindo Pharma":       "AUROPHARMA.NS",
    "Glenmark Pharma":        "GLENMARK.NS",
    "Alkem Labs":             "ALKEM.NS",
    "Biocon":                 "BIOCON.NS",

    # ── FMCG & Consumer (10) ──────────────────────────────────────────────────
    "Hindustan Unilever":     "HINDUNILVR.NS",
    "ITC":                    "ITC.NS",
    "Nestle India":           "NESTLEIND.NS",
    "Britannia":              "BRITANNIA.NS",
    "Dabur":                  "DABUR.NS",
    "Godrej Consumer":        "GODREJCP.NS",
    "Marico":                 "MARICO.NS",
    "Colgate-Palmolive":      "COLPAL.NS",
    "Tata Consumer":          "TATACONSUM.NS",
    "P&G Hygiene":            "PGHH.NS",

    # ── Metals & Cement (10) ──────────────────────────────────────────────────
    "Tata Steel":             "TATASTEEL.NS",
    "JSW Steel":              "JSWSTEEL.NS",
    "Hindalco":               "HINDALCO.NS",
    "Vedanta":                "VEDL.NS",
    "SAIL":                   "SAIL.NS",
    "NMDC":                   "NMDC.NS",
    "Jindal Steel":           "JINDALSTEL.NS",
    "Ambuja Cements":         "AMBUJACEM.NS",
    "UltraTech Cement":       "ULTRACEMCO.NS",
    "Shree Cement":           "SHREECEM.NS",

    # ── New-Age & Specialty (10) ──────────────────────────────────────────────
    "Zomato":                 "ZOMATO.NS",
    "Paytm":                  "PAYTM.NS",
    "PB Fintech":             "POLICYBZR.NS",
    "Nykaa":                  "NYKAA.NS",
    "Delhivery":              "DELHIVERY.NS",
    "Dixon Tech":             "DIXON.NS",
    "Astral":                 "ASTRAL.NS",
    "Pidilite":               "PIDILITIND.NS",
    "Havells":                "HAVELLS.NS",
    "Voltas":                 "VOLTAS.NS",
}

# Convenience lists
TICKERS: list[str] = list(WATCHLIST.values())
TICKER_NAMES: dict[str, str] = {v: k for k, v in WATCHLIST.items()}

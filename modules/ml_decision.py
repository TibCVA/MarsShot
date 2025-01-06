#!/usr/bin/env python3
# coding: utf-8

"""
ml_decision.py
--------------
But : lire daily_inference_data.csv, charger model.pkl, calculer proba.
+ get_probability_for_symbol(...) => usage live dans main.py.
"""

import os
import logging
import numpy as np
import pandas as pd
import joblib

MODEL_FILE = "model.pkl"
INPUT_CSV  = "daily_inference_data.csv"
LOG_FILE   = "ml_decision.log"

COLUMNS_ORDER = [
    "close","volume","market_cap","galaxy_score","alt_rank","sentiment",
    "rsi","macd","atr",
    "btc_daily_change","eth_daily_change","sol_daily_change"
]

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START ml_decision ===")

def main():
    # 1) Check model
    if not os.path.exists(MODEL_FILE):
        msg = f"[ERROR] {MODEL_FILE} introuvable => impossible de prédire."
        logging.error(msg)
        print(msg)
        return

    # 2) Check CSV
    if not os.path.exists(INPUT_CSV):
        msg = f"[ERROR] {INPUT_CSV} introuvable => impossible de prédire."
        logging.error(msg)
        print(msg)
        return

    # 3) Load model
    model = joblib.load(MODEL_FILE)
    logging.info(f"[INFO] Model {MODEL_FILE} chargé.")

    # 4) Read CSV
    df = pd.read_csv(INPUT_CSV)
    if df.empty:
        msg = "[WARN] daily_inference_data.csv est vide => aucune prédiction."
        logging.warning(msg)
        print(msg)
        return

    # 5) Check columns
    needed_cols = COLUMNS_ORDER + ["symbol"]
    for col in needed_cols:
        if col not in df.columns:
            msg = f"[ERROR] Colonne manquante => {col}"
            logging.error(msg)
            print(msg)
            return

    # 6) Drop NaN
    df_before = len(df)
    df.dropna(subset=COLUMNS_ORDER, inplace=True)
    df_after = len(df)
    if df_after<df_before:
        logging.warning(f"[WARN] Drop {df_before-df_after} tokens => NaN.")

    if df.empty:
        msg = "[WARN] All lines dropped => no predict."
        logging.warning(msg)
        print(msg)
        return

    # 7) Build X => (N,12)
    X = df[COLUMNS_ORDER].values.astype(float)
    # 8) predict_proba
    probs = model.predict_proba(X)
    prob_1 = probs[:,1]

    # 9) log results
    print("=== Probabilités de hausse (classe=1) ===")
    for i, row in df.iterrows():
        sym = row["symbol"]
        p = prob_1[i]
        print(f"{sym} => {p:.4f}")
        logging.info(f"[RESULT] {sym} => {p:.4f}")

    logging.info("=== END ml_decision ===")


##########################################################
# Restauration get_probability_for_symbol(...) usage live
##########################################################

import requests
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional
from indicators import compute_rsi_macd_atr

# Config + key LunarCrush
import yaml
if not os.path.exists("config.yaml"):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open("config.yaml","r") as f:
    CFG_LC = yaml.safe_load(f)

LUNAR_API_KEY = CFG_LC["lunarcrush"]["api_key"]

def get_probability_for_symbol(symbol: str) -> Optional[float]:
    """
    Récupère 1 an data symbol, calcule indicateurs, merges BTC/ETH/SOL, 
    renvoie prob classe=1 via model.pkl
    """
    logging.info(f"[LIVE fetch] get_probability_for_symbol({symbol})")

    df_token = _fetch_lc_raw(symbol, "1y")
    if df_token is None or df_token.empty:
        logging.warning(f"[{symbol}] => No data => None")
        return None

    df_indic = compute_rsi_macd_atr(df_token)
    if df_indic.empty:
        logging.warning(f"[{symbol}] => empty after indic => None")
        return None

    df_btc = _fetch_lc_raw("BTC", "1y")
    df_btc = _compute_daily_change(df_btc, "btc_daily_change") if (df_btc is not None and not df_btc.empty) else pd.DataFrame(columns=["date","btc_daily_change"])

    df_eth = _fetch_lc_raw("ETH", "1y")
    df_eth = _compute_daily_change(df_eth, "eth_daily_change") if (df_eth is not None and not df_eth.empty) else pd.DataFrame(columns=["date","eth_daily_change"])

    df_sol = _fetch_lc_raw("SOL", "1y")
    df_sol = _compute_daily_change(df_sol, "sol_daily_change") if (df_sol is not None and not df_sol.empty) else pd.DataFrame(columns=["date","sol_daily_change"])

    merged = df_indic.merge(df_btc, on="date", how="left")
    merged = merged.merge(df_eth, on="date", how="left")
    merged = merged.merge(df_sol, on="date", how="left")
    merged.sort_values("date", inplace=True)
    if merged.empty:
        return None

    row = merged.iloc[-1]
    needed_cols = COLUMNS_ORDER
    if row[needed_cols].isnull().any():
        logging.warning(f"[{symbol}] => missing col => None")
        return None

    arr = np.array([
        row["close"],
        row["volume"],
        row["market_cap"],
        row["galaxy_score"],
        row["alt_rank"],
        row["sentiment"],
        row["rsi"],
        row["macd"],
        row["atr"],
        row["btc_daily_change"],
        row["eth_daily_change"],
        row["sol_daily_change"]
    ]).reshape(1, -1)

    if not os.path.exists(MODEL_FILE):
        logging.error(f"[get_probability_for_symbol] no model.pkl => None")
        return None

    mdl = joblib.load(MODEL_FILE)
    prob = mdl.predict_proba(arr)[0][1]
    logging.info(f"[LIVE ML] {symbol} => prob={prob:.4f}")
    return prob

def _fetch_lc_raw(sym: str, interval="1y") -> Optional[pd.DataFrame]:
    url = f"https://lunarcrush.com/api4/public/coins/{sym}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "interval": interval
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code!=200:
            return None
        j = r.json()
        if "data" not in j or not j["data"]:
            return None
        rows=[]
        for point in j["data"]:
            ts = point.get("time")
            if not ts: continue
            dt_utc = datetime.utcfromtimestamp(ts)
            o  = point.get("open")
            c  = point.get("close")
            hi = point.get("high")
            lo = point.get("low")
            vol= point.get("volume_24h")
            mc = point.get("market_cap")
            gal= point.get("galaxy_score")
            alt_=point.get("alt_rank")
            senti= point.get("sentiment")
            rows.append([
                dt_utc, o, hi, lo, c, vol, mc, gal, alt_, senti
            ])
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=[
            "date","open","high","low","close","volume","market_cap",
            "galaxy_score","alt_rank","sentiment"
        ])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True,inplace=True)
        return df
    except:
        return None

def _compute_daily_change(df: pd.DataFrame, col_name:str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["date",col_name])
    df = df.sort_values("date").reset_index(drop=True)
    if "close" not in df.columns:
        df[col_name]=None
        return df
    df["prev_close"] = df["close"].shift(1)
    df[col_name] = (df["close"]/df["prev_close"] -1).replace([float("inf"),-float("inf")], None)
    df.drop(columns=["prev_close"],inplace=True)
    return df

if __name__=="__main__":
    main()

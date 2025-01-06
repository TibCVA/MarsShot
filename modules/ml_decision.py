#!/usr/bin/env python3
# coding: utf-8

"""
ml_decision.py
--------------
But : lire le CSV daily_inference_data.csv (issu de data_fetcher.py),
      charger model.pkl (issu de build_csv.py + train_model.py),
      calculer la proba de hausse (classe=1) pour chaque token,
      et afficher + logger le résultat.

Configuration :
 - On suppose que daily_inference_data.csv contient 1 ligne par token,
   avec les colonnes EXACTEMENT comme build_csv.py :
     ["date","open","high","low","close","volume","market_cap",
      "galaxy_score","alt_rank","sentiment",
      "rsi","macd","atr",
      "label","symbol",
      "btc_daily_change","eth_daily_change","sol_daily_change"]

 - On utilise model.pkl (RandomForest ou autre) 
   qui attend en entrée (train_model.py) => un vecteur :
     [close, volume, market_cap, galaxy_score, alt_rank, sentiment,
      rsi, macd, atr, btc_daily_change, eth_daily_change, sol_daily_change]

Exécution "live" :
1) data_fetcher.py => produit daily_inference_data.csv
2) python ml_decision.py => lit ce CSV, charge model.pkl => proba => logs.

+ en plus : get_probability_for_symbol(...) => fetch "live" LunarCrush

Pas de redondance côté batch, 
mais on rétablit la fonction live pour main.py.
"""

import os
import logging
import numpy as np
import pandas as pd
import joblib

########################################
# FICHIERS
########################################
MODEL_FILE = "model.pkl"
INPUT_CSV  = "daily_inference_data.csv"
LOG_FILE   = "ml_decision.log"

########################################
# COLONNES attendues
########################################
COLUMNS_ORDER = [
    "close","volume","market_cap","galaxy_score","alt_rank","sentiment",
    "rsi","macd","atr",
    "btc_daily_change","eth_daily_change","sol_daily_change"
]

########################################
# LOGGING
########################################
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START ml_decision ===")

def main():
    # 1) Vérifier la présence du modèle
    if not os.path.exists(MODEL_FILE):
        msg = f"[ERROR] {MODEL_FILE} introuvable => impossible de prédire."
        logging.error(msg)
        print(msg)
        return

    # 2) Vérifier le CSV
    if not os.path.exists(INPUT_CSV):
        msg = f"[ERROR] {INPUT_CSV} introuvable => impossible de prédire."
        logging.error(msg)
        print(msg)
        return

    # 3) Charger le modèle
    model = joblib.load(MODEL_FILE)
    logging.info(f"[INFO] Modèle {MODEL_FILE} chargé.")

    # 4) Lire le CSV
    df = pd.read_csv(INPUT_CSV)
    if df.empty:
        msg = "[WARN] daily_inference_data.csv est vide => aucune prédiction."
        logging.warning(msg)
        print(msg)
        return

    # 5) Vérifier qu'on a bien toutes les colonnes
    needed_cols = COLUMNS_ORDER + ["symbol"]
    for col in needed_cols:
        if col not in df.columns:
            msg = f"[ERROR] Colonne manquante dans {INPUT_CSV} => {col}"
            logging.error(msg)
            print(msg)
            return

    # 6) Drop les lignes qui ont un NaN dans l'une des colonnes d'entrée
    df_before = len(df)
    df.dropna(subset=COLUMNS_ORDER, inplace=True)
    df_after = len(df)
    if df_after < df_before:
        logging.warning(f"[WARN] On drop {df_before - df_after} tokens pour cause de NaN dans colonnes d'entrée.")

    if df.empty:
        msg = "[WARN] Toutes les lignes ont été drop => plus rien à prédire."
        logging.warning(msg)
        print(msg)
        return

    # 7) Construire la matrice d'entrée (N,12)
    X = df[COLUMNS_ORDER].values.astype(float)
    # 8) Prédiction
    probs = model.predict_proba(X)  # shape (N,2)
    # index 1 = prob classe=1
    prob_1 = probs[:,1]

    # 9) On logge le résultat + on print
    print("=== Probabilités de hausse (classe=1) ===")
    for i, row in df.iterrows():
        sym = row["symbol"]
        p   = prob_1[i]
        print(f"{sym} => {p:.4f}")
        logging.info(f"[RESULT] {sym} => {p:.4f}")

    logging.info("=== END ml_decision ===")

##########################################################
# AJOUT MINIMAL => get_probability_for_symbol(...) "live"
##########################################################

import requests
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional
from indicators import compute_rsi_macd_atr

# Si besoin, on lit la config + clé LunarCrush
import yaml
if not os.path.exists("config.yaml"):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open("config.yaml","r") as f:
    CFG_LC = yaml.safe_load(f)

LUNAR_API_KEY = CFG_LC["lunarcrush"]["api_key"]

def get_probability_for_symbol(symbol: str) -> Optional[float]:
    """
    Restauration de la fonction live pour 'main.py'
    => Récupère 1 an data sur symbol (LunarCrush),
       calcule RSI/macd/atr, merges BTC/ETH/SOL daily change,
       prend la dernière ligne => vecteur => model.predict_proba => prob classe=1.
    """
    logging.info(f"[LIVE fetch] get_probability_for_symbol({symbol})")

    # 1) fetch data 1y
    df_token = _fetch_lc_raw(symbol, "1y")
    if df_token is None or df_token.empty:
        logging.warning(f"[{symbol}] => No data => None")
        return None

    # 2) compute indicators
    df_indic = compute_rsi_macd_atr(df_token)
    if df_indic.empty:
        return None

    # 3) merges BTC/ETH/SOL daily
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
    # 4) needed cols
    needed_cols = [
        "close","volume","market_cap","galaxy_score","alt_rank","sentiment",
        "rsi","macd","atr",
        "btc_daily_change","eth_daily_change","sol_daily_change"
    ]
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

    mdl = joblib.load(MODEL_FILE)  # On recharge le modèle
    prob = mdl.predict_proba(arr)[0][1]
    return prob

############################
# FONCTIONS interne _fetch_lc_raw, _compute_daily_change
# (mêmes que data_fetcher, version minimal)
############################

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
            rows.append([dt_utc, o, hi, lo, c, vol, mc, gal, alt_, senti])
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

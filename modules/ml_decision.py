#!/usr/bin/env python3
# coding: utf-8

"""
ml_decision.py
--------------
But : 
  1) Lire daily_inference_data.csv, charger model.pkl, calculer la proba => mode "batch".
  2) Fournir get_probability_for_symbol(...) pour usage "live" dans main.py 
     (récup 1 an de data sur LunarCrush, calcule RSI/MACD/ATR, merges 
      btc_daily_change, eth_daily_change, sol_daily_change, 
      renvoie proba de hausse (classe=1)).

NB: Ce code suppose que votre train_model.py inclut désormais 'sol_daily_change'
comme douzième feature, et que le model.pkl reflète bien ces 12 colonnes.
"""

import os
import logging
import numpy as np
import pandas as pd
import joblib

# --------------------------------
# Fichiers / colonnes pour le mode "batch"
# --------------------------------
MODEL_FILE = "model.pkl"
INPUT_CSV  = "daily_inference_data.csv"
LOG_FILE   = "ml_decision.log"

# L'ordre exact des features pour le modèle (12 colonnes)
COLUMNS_ORDER = [
    "close","volume","market_cap","galaxy_score","alt_rank","sentiment",
    "rsi","macd","atr",
    "btc_daily_change","eth_daily_change","sol_daily_change"
]

# --------------------------------
# Logging global pour ce module
# --------------------------------
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START ml_decision ===")

def main():
    """
    Mode batch : on lit daily_inference_data.csv => on applique model.pkl => 
    on logge les probabilités de hausse (classe=1) pour chaque token.
    """
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
            msg = f"[ERROR] Colonne manquante => {col}"
            logging.error(msg)
            print(msg)
            return

    # 6) Drop les lignes NaN
    df_before = len(df)
    df.dropna(subset=COLUMNS_ORDER, inplace=True)
    df_after = len(df)
    if df_after < df_before:
        logging.warning(f"[WARN] Drop {df_before - df_after} tokens => NaN.")

    if df.empty:
        msg = "[WARN] Toutes les lignes ont été drop => plus rien à prédire."
        logging.warning(msg)
        print(msg)
        return

    # 7) Construire la matrice d'entrée (N,12)
    X = df[COLUMNS_ORDER].values.astype(float)

    # 8) predict_proba
    probs = model.predict_proba(X)  # shape (N,2)
    prob_1 = probs[:,1]            # prob de la classe=1

    # 9) On log/affiche
    print("=== Probabilités de hausse (classe=1) ===")
    for i, row in df.iterrows():
        sym = row["symbol"]
        p   = prob_1[i]
        print(f"{sym} => {p:.4f}")
        logging.info(f"[RESULT] {sym} => {p:.4f}")

    logging.info("=== END ml_decision ===")

# ---------------------------------------------------
# Partie LIVE => get_probability_for_symbol(symbol)
# ---------------------------------------------------
import requests
from datetime import datetime
from typing import Optional
from indicators import compute_rsi_macd_atr

# On lit la config + clé LunarCrush
import yaml
if not os.path.exists("config.yaml"):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open("config.yaml", "r") as f:
    CFG_LC = yaml.safe_load(f)

LUNAR_API_KEY = CFG_LC["lunarcrush"]["api_key"]
TOKENS_DAILY  = CFG_LC["tokens_daily"]  # Liste des 21 tokens autorisés

def get_probability_for_symbol(symbol: str) -> Optional[float]:
    """
    Récupère 1 an de data daily sur 'symbol' (LunarCrush).
    Calcule RSI,MACD,ATR => df_indic.
    Merge df_btc/df_eth/df_sol => date, daily_change...
    => Construit le vecteur => model.predict_proba => prob classe=1.

    Ne calcule la prob que si 'symbol' est dans config["tokens_daily"].
    Sinon => None.
    """
    # 1) Vérifier si le token est suivi
    if symbol not in TOKENS_DAILY:
        logging.info(f"[LIVE fetch] {symbol} => pas dans tokens_daily => skip prob => None.")
        return None

    logging.info(f"[LIVE fetch] get_probability_for_symbol({symbol})")

    df_token = _fetch_lc_raw(symbol, "1y")
    if df_token is None or df_token.empty:
        logging.warning(f"[{symbol}] => No data => None")
        return None

    # Calcul RSI, MACD, ATR
    df_indic = compute_rsi_macd_atr(df_token)
    if df_indic.empty:
        logging.warning(f"[{symbol}] => empty after compute_rsi_macd_atr => None")
        return None

    # Récup BTC daily change
    df_btc = _fetch_lc_raw("BTC", "1y")
    df_btc = _compute_daily_change(df_btc, "btc_daily_change") if (df_btc is not None and not df_btc.empty) else None
    if df_btc is not None and not df_btc.empty:
        df_btc = df_btc[["date","btc_daily_change"]]

    # Récup ETH
    df_eth = _fetch_lc_raw("ETH", "1y")
    df_eth = _compute_daily_change(df_eth, "eth_daily_change") if (df_eth is not None and not df_eth.empty) else None
    if df_eth is not None and not df_eth.empty:
        df_eth = df_eth[["date","eth_daily_change"]]

    # Récup SOL
    df_sol = _fetch_lc_raw("SOL", "1y")
    df_sol = _compute_daily_change(df_sol, "sol_daily_change") if (df_sol is not None and not df_sol.empty) else None
    if df_sol is not None and not df_sol.empty:
        df_sol = df_sol[["date","sol_daily_change"]]

    # Merge final
    merged = df_indic.copy()
    if df_btc is not None:
        merged = merged.merge(df_btc, on="date", how="left")
    if df_eth is not None:
        merged = merged.merge(df_eth, on="date", how="left")
    if df_sol is not None:
        merged = merged.merge(df_sol, on="date", how="left")

    merged.sort_values("date", inplace=True)
    merged.reset_index(drop=True, inplace=True)

    if merged.empty:
        logging.warning(f"[{symbol}] => merged empty => None")
        return None

    # On prend la dernière ligne
    row = merged.iloc[-1]

    # Vérifier la présence de toutes les colonnes du modèle
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
        logging.error("[LIVE fetch] model.pkl absent => None")
        return None

    # Charger le modèle
    model = joblib.load(MODEL_FILE)

    # predict_proba => prob classe=1
    prob = model.predict_proba(arr)[0][1]
    logging.info(f"[LIVE ML] {symbol} => prob={prob:.4f}")
    return prob

# -------------------------------------------
# Fonctions internes : _fetch_lc_raw, _compute_daily_change
# -------------------------------------------
import requests
def _fetch_lc_raw(sym: str, interval="1y") -> Optional[pd.DataFrame]:
    """
    Récupère la data daily sur LunarCrush => [date,open,high,low,close,volume,market_cap,galaxy_score,alt_rank,sentiment]
    Tri par date => DF ou None
    """
    url = f"https://lunarcrush.com/api4/public/coins/{sym}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "interval": interval
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            logging.warning(f"[_fetch_lc_raw] {sym} => HTTP {r.status_code}")
            return None
        j = r.json()
        if "data" not in j or not j["data"]:
            return None

        rows = []
        for point in j["data"]:
            ts = point.get("time")
            if not ts:
                continue
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
    except Exception as e:
        logging.error(f"[ERROR _fetch_lc_raw] {sym} => {e}")
        return None

def _compute_daily_change(df: pd.DataFrame, col_name: str) -> pd.DataFrame:
    """
    Identique à build_csv => daily_change(t)= close(t)/close(t-1) -1
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", col_name])
    dff = df.copy().sort_values("date").reset_index(drop=True)
    if "close" not in dff.columns:
        dff[col_name] = None
        return dff
    dff["prev_close"] = dff["close"].shift(1)
    dff[col_name] = (dff["close"] / dff["prev_close"] - 1).replace([float("inf"), -float("inf")], None)
    dff.drop(columns=["prev_close"], inplace=True)
    return dff

# -------------------------------------------
if __name__=="__main__":
    main()
#!/usr/bin/env python3
# coding: utf-8

"""
Ce module gère la prédiction de la probabilité (prob>=0.70, etc.)
en s'appuyant sur le même pipeline que build_csv.py :
- On récupère 1 an de data sur le token (LunarCrush)
- On applique EXACTEMENT la même logique de "cleaning" (0 => NaN, dropna, etc.)
- On calcule RSI, MACD, ATR (indicators.py)
- On merge BTC, ETH daily_change (comme build_csv)
- On prend la dernière ligne
- On construit le vecteur complet :
  [close, volume, market_cap, galaxy_score, alt_rank, sentiment,
   rsi, macd, atr, btc_daily_change, eth_daily_change]
- On renvoie la proba d'être label=1 (RandomForest ou autre)

Remarque : on ne gère pas "future_close" ni la colonne "label" en inference, évidemment.
"""

import os
import logging
import requests
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

import joblib

# On importe la même fonction "compute_rsi_macd_atr" que build_csv.py utilise
from indicators import compute_rsi_macd_atr

MODEL_PATH = "model.pkl"
_model = None

# Même clé / param que build_csv.py
LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"
INTERVAL = "1y"  # On récupère 1 an daily

########################################
# Chargement du modèle
########################################

def load_model():
    global _model
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"[ERREUR] {MODEL_PATH} introuvable.")
        _model = joblib.load(MODEL_PATH)
    return _model


########################################
# API Prediction Principale
########################################

def get_probability_for_symbol(symbol: str) -> Optional[float]:
    """
    Récupère 1 an de data daily sur 'symbol' (LunarCrush) avec les champs
     [galaxy_score, alt_rank, sentiment, ...].
    Calcule RSI, MACD, ATR avec la même "logique" (0 => NaN => dropna).
    Merge BTC/ETH daily_change (même code).
    Prend la DERNIERE ligne => [close, volume, market_cap, galaxy_score, alt_rank, sentiment,
                                rsi, macd, atr, btc_daily_change, eth_daily_change].
    Applique le modèle => renvoie prob (classe=1).
    Retourne None si data insuffisante.
    """

    # 1) Récup data du token
    df_token = fetch_lunar_data(symbol)
    if df_token is None or df_token.empty:
        logging.warning(f"[{symbol}] => No data from LC => prob=None")
        return None

    # 2) Calcul indicateurs + cleaning
    df_indic = compute_rsi_macd_atr(df_token)
    if df_indic.empty:
        logging.warning(f"[{symbol}] => after cleaning => empty => prob=None")
        return None

    # 3) On merge BTC / ETH daily_change
    df_btc = fetch_lunar_data("BTC")
    df_btc = compute_daily_change(df_btc, "btc_daily_change") if (df_btc is not None and not df_btc.empty) else pd.DataFrame(columns=["date","btc_daily_change"])

    df_eth = fetch_lunar_data("ETH")
    df_eth = compute_daily_change(df_eth, "eth_daily_change") if (df_eth is not None and not df_eth.empty) else pd.DataFrame(columns=["date","eth_daily_change"])

    merged = pd.merge(df_indic, df_btc, on="date", how="left")
    merged = pd.merge(merged, df_eth, on="date", how="left")

    # 4) Dernière ligne
    merged.sort_values("date", inplace=True)
    merged.reset_index(drop=True, inplace=True)
    if merged.empty:
        return None
    last_row = merged.iloc[-1]

    # 5) Vérif qu'on a tous les champs => [close, volume, market_cap, galaxy_score, alt_rank, sentiment, rsi, macd, atr, btc_daily_change, eth_daily_change]
    needed_cols = [
        "close", "volume", "market_cap",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr",
        "btc_daily_change", "eth_daily_change"
    ]
    if last_row[needed_cols].isnull().any():
        # Si l'une est NaN => prob=None
        logging.warning(f"[{symbol}] => missing col => prob=None")
        return None

    # 6) Construction du vecteur EXACTEMENT comme train_model.py
    arr = np.array([
        last_row["close"],
        last_row["volume"],
        last_row["market_cap"],
        last_row["galaxy_score"],
        last_row["alt_rank"],
        last_row["sentiment"],
        last_row["rsi"],
        last_row["macd"],
        last_row["atr"],
        last_row["btc_daily_change"],
        last_row["eth_daily_change"]
    ]).reshape(1, -1)

    # 7) predict_proba
    model = load_model()
    prob = model.predict_proba(arr)[0][1]
    return prob


########################################
# Fonctions utilitaires (copiées de build_csv.py)
########################################

def fetch_lunar_data(symbol: str) -> Optional[pd.DataFrame]:
    """
    Reprise stricte de build_csv.py => on récupère daily 1y + columns 
     [galaxy_score, alt_rank, sentiment].
    """
    if not symbol:
        return None

    url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "interval": INTERVAL
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            logging.warning(f"[WARN] fetch_lunar_data({symbol}) => {r.status_code}")
            return None

        j = r.json()
        if "data" not in j or not j["data"]:
            logging.warning(f"[WARN] {symbol} => no 'data'")
            return None

        rows = []
        for point in j["data"]:
            unix_ts = point.get("time")
            if not unix_ts:
                continue

            dt_utc = datetime.utcfromtimestamp(unix_ts)
            o = point.get("open", None)
            c = point.get("close", None)
            h = point.get("high", None)
            lo= point.get("low", None)
            vol24 = point.get("volume_24h", None)
            mc = point.get("market_cap", None)
            gal = point.get("galaxy_score", None)
            alt_ = point.get("alt_rank", None)
            senti = point.get("sentiment", None)

            rows.append([
                dt_utc, o, c, h, lo, vol24, mc, gal, alt_, senti
            ])

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=[
            "date","open","close","high","low","volume","market_cap",
            "galaxy_score","alt_rank","sentiment"
        ])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    except Exception as e:
        logging.error(f"[ERROR] fetch_lunar_data({symbol}) => {e}")
        return None


def compute_daily_change(df: pd.DataFrame, col_name: str) -> pd.DataFrame:
    """
    Identique à build_csv => daily_change(t) = close(t)/close(t-1) -1
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", col_name])
    df = df.sort_values("date").reset_index(drop=True)
    if "close" not in df.columns:
        df[col_name] = None
        return df

    df["prev_close"] = df["close"].shift(1)
    df[col_name] = (df["close"] / df["prev_close"] -1).replace([float("inf"), -float("inf")], None)
    df.drop(columns=["prev_close"], inplace=True)
    return df


########################################
# Petit test
########################################

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sym_test = "FET"
    p = get_probability_for_symbol(sym_test)
    if p is not None:
        print(f"[TEST] Probability for {sym_test} => {p:.4f}")
    else:
        print(f"[TEST] Probability for {sym_test} => None")
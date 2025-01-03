#!/usr/bin/env python3
# coding: utf-8

import os
import requests
import time
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

# On réutilise EXACTEMENT l'indicateur existant, pour le même "cleaning"
from indicators import compute_rsi_macd_atr

# On charge ton modèle déjà entraîné
import joblib

MODEL_PATH = "model.pkl"
_model = None

########################################
# CONFIGURATION "SIMILAIRE" A BUILD_CSV
########################################
# Même clé, même endpoint, même paramétrage
LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"
SLEEP_BETWEEN_TOKENS = 6  # comme dans build_csv
INTERVAL = "1y"           # on récupère 1 an de data, comme build_csv

def load_model():
    global _model
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"[ERREUR] {MODEL_PATH} introuvable.")
        _model = joblib.load(MODEL_PATH)
    return _model


def get_probability_for_symbol(symbol: str) -> Optional[float]:
    """
    Réplique la logique de build_csv pour un SEUL symbol :
      1) fetch_lunar_data(symbol) => on récupère 1 an daily
      2) compute_rsi_macd_atr => même "cleaning"
      3) merge BTC daily_change, ETH daily_change => comme build_csv
      4) on prend la DERNIÈRE LIGNE => on construit l'array EXACTEMENT dans le même ordre
         [close, volume, market_cap, galaxy_score, alt_rank, sentiment,
          rsi, macd, atr, btc_daily_change, eth_daily_change]
      5) on calcule model.predict_proba(...) et on renvoie prob classe=1
    Retourne None si data vide ou line vide.
    """

    # 1) Récup data du token
    df_alt = fetch_lunar_data(symbol)
    if df_alt is None or df_alt.empty:
        return None

    # 2) On calcule RSI, MACD, ATR (même "cleaning" que build_csv)
    df_alt_ind = compute_rsi_macd_atr(df_alt)
    if df_alt_ind.empty:
        return None

    # 3) Merge BTC/ETH daily change (comme build_csv)
    df_btc = fetch_lunar_data("BTC")
    if df_btc is not None and not df_btc.empty:
        df_btc = compute_daily_change(df_btc, "btc_daily_change")
        df_btc = df_btc[["date","btc_daily_change"]]
    else:
        df_btc = pd.DataFrame(columns=["date","btc_daily_change"])

    df_eth = fetch_lunar_data("ETH")
    if df_eth is not None and not df_eth.empty:
        df_eth = compute_daily_change(df_eth, "eth_daily_change")
        df_eth = df_eth[["date","eth_daily_change"]]
    else:
        df_eth = pd.DataFrame(columns=["date","eth_daily_change"])

    # On merge successivement
    merged = pd.merge(df_alt_ind, df_btc, on="date", how="left")
    merged = pd.merge(merged, df_eth, on="date", how="left")

    # 4) On prend la dernière date
    merged.sort_values("date", inplace=True)
    merged.reset_index(drop=True, inplace=True)
    if merged.empty:
        return None

    last_row = merged.iloc[-1].copy()  # la plus récente

    # Contrôle final : s'il y a un champ manquant => on force à None
    # Mais on va continuer, c'est à toi de voir si tu préfères "return None" ou 0
    # On suit la même optique que dans build_csv : si "close" manquant => plus exploitable.
    needed_cols = [
        "close", "volume", "market_cap",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr",
        "btc_daily_change", "eth_daily_change"
    ]
    if last_row[needed_cols].isnull().any():
        # s'il y a un NaN => en production, ça va poser souci
        # A toi de voir si tu renvoies None, ou tu forces 0
        return None

    # 5) On construit l'array EXACTEMENT dans le même ordre que dans train_model.py
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

    model = load_model()
    prob = model.predict_proba(arr)[0][1]
    return prob


########################################
# Fonctions utilitaires (copiées de build_csv)
########################################

def fetch_lunar_data(symbol: str) -> Optional[pd.DataFrame]:
    """
    Identique à la version build_csv : on récupère 1 an daily 
    + on a les colonnes galaxy_score, alt_rank, sentiment en plus.
    """
    url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "interval": INTERVAL  # "1y"
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        logging.info(f"[LUNAR] {symbol} => HTTP {r.status_code}")

        if r.status_code != 200:
            logging.warning(f"[WARN] {symbol} => code={r.status_code}, skip.")
            return None

        j = r.json()
        if "data" not in j or not j["data"]:
            logging.warning(f"[WARN] {symbol} => data vide => skip.")
            return None

        rows = []
        for point in j["data"]:
            unix_ts = point.get("time")
            if not unix_ts:
                continue

            dt_utc = datetime.utcfromtimestamp(unix_ts)
            o      = point.get("open", None)
            c      = point.get("close", None)
            h      = point.get("high", None)
            lo     = point.get("low", None)
            vol_24 = point.get("volume_24h", None)
            mc     = point.get("market_cap", None)
            gal    = point.get("galaxy_score", None)
            alt_   = point.get("alt_rank", None)
            senti  = point.get("sentiment", None)

            rows.append([
                dt_utc, o, c, h, lo, vol_24, mc, gal, alt_, senti
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
        logging.error(f"[ERROR] {symbol} => {e}")
        return None


def compute_daily_change(df: pd.DataFrame, col_name: str) -> pd.DataFrame:
    """
    Même code que build_csv => daily_change(t) = close(t)/close(t-1) - 1
    """
    df = df.sort_values("date").reset_index(drop=True)
    if "close" not in df.columns:
        df[col_name] = None
        return df

    df["prev_close"] = df["close"].shift(1)
    df[col_name] = (df["close"] / df["prev_close"] - 1).replace([float("inf"), -float("inf")], None)
    df.drop(columns=["prev_close"], inplace=True)
    return df


########################################
# Test Rapide
########################################
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_sym = "FET"  # par exemple
    prob = get_probability_for_symbol(test_sym)
    if prob is not None:
        print(f"[INFO] Probability for {test_sym} => {prob:.3f}")
    else:
        print(f"[WARN] No data / invalid for {test_sym}")
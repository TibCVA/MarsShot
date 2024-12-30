#!/usr/bin/env python3
# coding: utf-8

import requests
import pandas as pd
import time
import logging
import os
from datetime import datetime
from typing import Optional

#####################################
# PARAMÈTRES GLOBAUX
#####################################

LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"

# Nombre de jours d’horizon pour récupérer l’historique sur 1 an
# (LunarCrush gérera interval=1y, qui ~ 365 jours)
DAYS_HISTORY = 365

# Paramètres pour le label
SHIFT_DAYS = 2
THRESHOLD = 0.30

# Fichier CSV de sortie
OUTPUT_CSV = "training_data.csv"

# Fichier de logs
LOG_FILE = "build_csv.log"

# Temps d'attente pour éviter le rate-limit (10 requêtes/minute)
SLEEP_BETWEEN_TOKENS = 6  # en secondes

# Configuration du logger
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START build_csv_lunar_only ===")


#####################################
# LISTE DES TOKENS À TRAITER
#####################################
# Exemple simplifié avec 4 tokens "ETH", "LINK", "SOLVEX", "MOEW".
# Vous pouvez en ajouter autant que vous voulez, tant que vous respectez
# le rate-limit imposé par l’API LunarCrush.
TOKENS = [
    {"symbol": "GOAT"},
    {"symbol": "FARTCOIN"},
    {"symbol": "ZEREBRO"},
    {"symbol": "STNK"},
    {"symbol": "BONK"},
    {"symbol": "FET"},
    {"symbol": "AGIX"},
    {"symbol": "NMR"},
    {"symbol": "CTXC"},
    {"symbol": "VLX"},
    {"symbol": "VET"},
    {"symbol": "CHZ"},
    {"symbol": "ENJ"},
    {"symbol": "MANA"},
    {"symbol": "SAND"},
    {"symbol": "INJ"},
    {"symbol": "WOO"},
    {"symbol": "OP"},
    {"symbol": "ARB"},
    {"symbol": "SNX"},
    {"symbol": "LDO"},
    {"symbol": "RUNE"},
    {"symbol": "RVF"},
    {"symbol": "ROSE"},
    {"symbol": "ALGO"},
    {"symbol": "GALA"},
    {"symbol": "SUI"},
    {"symbol": "QNT"},
    {"symbol": "LINK"}
]



#####################################
# FONCTIONS
#####################################

def fetch_lunar_data(symbol: str) -> Optional[pd.DataFrame]:
    """
    Récupère les données journalières (bucket=day) sur 1 an (interval=1y)
    depuis l’endpoint v2 de LunarCrush :
      GET /api4/public/coins/<symbol>/time-series/v2
    On extrait :
      time, open, close, high, low, volume_24h, market_cap, market_dominance,
      circulating_supply, sentiment, spam, galaxy_score, volatility, alt_rank,
      contributors_active, contributors_created, posts_active, posts_created,
      interactions, social_dominance
    Retourne un DataFrame ou None si échec.
    """

    url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"

    # Paramètres : bucket=day, interval=1y => ~ 365 jours
    # On ne précise pas "start" ou "end", c’est l’API qui gère l’interval=1y
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "interval": "1y"
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        logging.info(f"[LUNAR] symbol={symbol}, status_code={r.status_code}")

        if r.status_code != 200:
            logging.warning(f"[LUNAR WARNING] symbol={symbol} => HTTP={r.status_code}, skip.")
            return None

        j = r.json()
        if "data" not in j or not j["data"]:
            logging.warning(f"[LUNAR WARNING] symbol={symbol} => pas de data => skip.")
            return None

        rows = []
        for point in j["data"]:
            # point est un dict, ex.:
            # {
            #   "time": 1734912000,
            #   "open": 3252.28,
            #   "close": 3252.28,
            #   "high": 3252.28,
            #   "low": 3248.85,
            #   "volume_24h": 24854088734.3,
            #   "market_cap": 391793759443.76,
            #   "market_dominance": 11.954,
            #   "circulating_supply": 120455304.54,
            #   "sentiment": 82,
            #   "spam": 234,
            #   "galaxy_score": 64,
            #   "volatility": 0.02,
            #   "alt_rank": 701,
            #   "contributors_active": 12054,
            #   "contributors_created": 407,
            #   "posts_active": 22115,
            #   "posts_created": 571,
            #   "interactions": 2644033,
            #   "social_dominance": 8.348
            # }
            unix_ts = point.get("time")
            if not unix_ts:
                continue
            dt_utc = datetime.utcfromtimestamp(unix_ts)

            # On lit toutes les métriques
            o = point.get("open", None)
            c = point.get("close", None)
            h = point.get("high", None)
            lo = point.get("low", None)
            vol_24 = point.get("volume_24h", None)
            mc = point.get("market_cap", None)
            md = point.get("market_dominance", None)
            cs = point.get("circulating_supply", None)
            senti = point.get("sentiment", None)
            spam_ = point.get("spam", None)
            gs = point.get("galaxy_score", None)
            volat = point.get("volatility", None)
            alt_r = point.get("alt_rank", None)
            contrib_act = point.get("contributors_active", None)
            contrib_creat = point.get("contributors_created", None)
            posts_act = point.get("posts_active", None)
            posts_creat = point.get("posts_created", None)
            inter = point.get("interactions", None)
            soc_dom = point.get("social_dominance", None)

            rows.append([
                dt_utc, o, c, h, lo, vol_24, mc, md, cs,
                senti, spam_, gs, volat, alt_r,
                contrib_act, contrib_creat, posts_act, posts_creat, inter, soc_dom
            ])

        if not rows:
            logging.warning(f"[LUNAR WARNING] symbol={symbol} => rows empty after parse.")
            return None

        df = pd.DataFrame(rows, columns=[
            "date", "open", "close", "high", "low", "volume_24h", "market_cap",
            "market_dominance", "circulating_supply", "sentiment", "spam",
            "galaxy_score", "volatility", "alt_rank",
            "contributors_active", "contributors_created",
            "posts_active", "posts_created", "interactions", "social_dominance"
        ])

        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    except Exception as e:
        logging.error(f"[LUNAR ERROR] symbol={symbol} => {e}")
        return None


def compute_label(df: pd.DataFrame, shift_days=2, threshold=0.30) -> pd.DataFrame:
    """
    Calcule un label binaire : label=1 si la hausse (close D+shift_days - close D)/close D >= threshold
    Sinon 0. Si le close D+2 n’existe pas, la valeur label reste NaN (puis on pourra drop ou laisser).
    """
    df = df.sort_values("date").reset_index(drop=True)
    # On vérifie qu’on a bien la colonne 'close'
    if "close" not in df.columns:
        df["label"] = None
        return df

    df["future_close"] = df["close"].shift(-shift_days)
    df["variation"] = (df["future_close"] - df["close"]) / df["close"]
    df["label"] = (df["variation"] >= threshold).astype(float)

    return df


def main():
    logging.info("=== build_csv_lunar_only => collecting data for tokens (lunar only) ===")

    all_dfs = []
    nb_tokens = len(TOKENS)

    for i, tk in enumerate(TOKENS, start=1):
        sym = tk["symbol"]
        logging.info(f"[{i}/{nb_tokens}] Fetching LunarCrush data for {sym} ...")

        df_lunar = fetch_lunar_data(sym)
        if df_lunar is None or df_lunar.empty:
            logging.warning(f"No valid data for {sym} => skip.")
            continue

        # Calcul du label
        df_lunar = compute_label(df_lunar, SHIFT_DAYS, THRESHOLD)
        df_lunar["symbol"] = sym

        # On enlève les lignes dont label est NaN (pas de data +2 jours) si on veut un CSV “final”
        # => On laisse quand même la possibilité de conserver : à votre choix
        df_lunar.dropna(subset=["label"], inplace=True)

        all_dfs.append(df_lunar)
        # Pour éviter l’erreur 429 de LunarCrush si on a beaucoup de tokens
        time.sleep(SLEEP_BETWEEN_TOKENS)

    if not all_dfs:
        logging.warning("No data => no CSV.")
        print("No data => no CSV. Check logs.")
        return

    # Concatène tout
    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["symbol","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    # Exporte
    df_final.to_csv(OUTPUT_CSV, index=False)
    logging.info(f"Export => {OUTPUT_CSV} => {len(df_final)} lignes.")
    print(f"Export => {OUTPUT_CSV} ({len(df_final)} lignes)")

    logging.info("=== DONE build_csv ===")


if __name__ == "__main__":
    main()

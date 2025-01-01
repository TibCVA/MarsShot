#!/usr/bin/env python3
# coding: utf-8

import requests
import pandas as pd
import time
import logging
import os
from datetime import datetime
from typing import Optional

# On importe notre module indicators.py
from indicators import compute_rsi_macd_atr

#####################################
# PARAMÈTRES GLOBAUX
#####################################

LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"

# SHIFT_DAYS => label (variat° 2 jours)
SHIFT_DAYS = 2
# THRESHOLD => 30% de hausse => label=1
THRESHOLD = 0.30

OUTPUT_CSV = "training_data.csv"
LOG_FILE = "build_csv.log"

# On se limite à ~10 appels/min => 6s
SLEEP_BETWEEN_TOKENS = 6

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START build_csv_lunar_with_indicators ===")


#####################################
# LISTE TOKENS
#####################################
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
    {"symbol": "LINK"},
    {"symbol": "SOLVEX"},
    {"symbol": "COOKIE"},
    {"symbol": "A8"},
    {"symbol": "PRQ"},
    {"symbol": "PHA"},
    {"symbol": "XYO"},
    {"symbol": "MCADE"},
    {"symbol": "COW"},
    {"symbol": "AVA"},
    {"symbol": "DF"},
    {"symbol": "XVG"},
    {"symbol": "AGLD"},
    {"symbol": "WILD"},
    {"symbol": "CPOOL"},
    {"symbol": "ZEN"},
    {"symbol": "UTK"},
    {"symbol": "WHBAR"},
    {"symbol": "SHIBTC"},
    {"symbol": "NCT"},
    {"symbol": "SRX"},
    {"symbol": "OMI"},
    {"symbol": "ACX"},
    {"symbol": "ARTY"},
    {"symbol": "FIRO"},
    {"symbol": "SHDW"},
    {"symbol": "VELO"},
    {"symbol": "SWFTC"},
    {"symbol": "CXT"},
    {"symbol": "ZENT"},
    {"symbol": "IDEX"}
]
# Ajoutez autant de tokens que voulu (tout en restant dans la limite d'appels)

#####################################
# FONCTIONS
#####################################

def fetch_lunar_data(symbol: str) -> Optional[pd.DataFrame]:
    """
    Récupère l'historique daily (ou potentiellement + d'un point par jour)
    via l'endpoint v2 de LunarCrush:
      GET /api4/public/coins/<symbol>/time-series/v2
    Retourne un DataFrame (date, open, close, high, low, volume, market_cap, galaxy_score, alt_rank, sentiment)
    ou None si échec.
    """
    url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",   # param 'bucket=day'
        "interval": "1y"   # interval sur 2 ans, par ex.
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        logging.info(f"[LUNAR] symbol={symbol}, status={r.status_code}")

        if r.status_code != 200:
            logging.warning(f"[LUNAR WARNING] symbol={symbol}, HTTP={r.status_code}, skip.")
            return None

        j = r.json()
        if "data" not in j or not j["data"]:
            logging.warning(f"[LUNAR WARNING] symbol={symbol}, no data => skip.")
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
            lo = point.get("low", None)
            vol_24 = point.get("volume_24h", None)
            mc = point.get("market_cap", None)
            # Ajout des 3 indicateurs : galaxy_score, alt_rank, sentiment
            galaxy = point.get("galaxy_score", None)
            alt_r = point.get("alt_rank", None)
            senti = point.get("sentiment", None)

            rows.append([
                dt_utc, o, c, h, lo, vol_24, mc,
                galaxy, alt_r, senti
            ])

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=[
            "date","open","close","high","low","volume","market_cap",
            "galaxy_score","alt_rank","sentiment"
        ])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)

        # -------------------------------------------------------------------
        # AJOUT MINIMAL : on ne garde qu'une (ou plusieurs) heure(s) par jour
        # Ex. SI ON NE VEUT QU'UNE LIGNE PAR JOUR => hour=12
        #
        #   df["hour"] = df["date"].dt.hour
        #   df = df[df["hour"] == 12]
        #
        # Ex. POUR TROIS LIGNES PAR JOUR => 0h, 12h, 23h
        #   df["hour"] = df["date"].dt.hour
        #   df = df[df["hour"].isin([0,12,23])]
        #
        # Choisissez la variante souhaitée, en décommentant l'une ou l'autre:
        # -------------------------------------------------------------------
        df["hour"] = df["date"].dt.hour

        # => 1 relevé par jour, sur l'heure 12 :
        df = df[df["hour"].isin([0,12,23])]

        # Ou => 3 relevés par jour, ex. 0h, 12h, 23h
        #df = df[df["hour"].isin([0,12,23])]

        df.drop(columns=["hour"], inplace=True, errors="ignore")
        # FIN AJOUT MINIMAL
        # -------------------------------------------------------------------

        return df

    except Exception as e:
        logging.error(f"[LUNAR ERROR] symbol={symbol} => {e}")
        return None


def compute_label(df: pd.DataFrame, shift_days=2, threshold=0.30) -> pd.DataFrame:
    """
    Calcule un label binaire => label=1 si +30% sur 2j
    """
    df = df.sort_values("date").reset_index(drop=True)
    if "close" not in df.columns:
        df["label"] = None
        return df

    df["future_close"] = df["close"].shift(-shift_days)
    df["variation"] = (df["future_close"] - df["close"]) / df["close"]
    df["label"] = (df["variation"] >= threshold).astype(float)
    return df


def main():
    logging.info("=== build_csv => collecting data + indicators ===")

    all_dfs = []
    nb_tokens = len(TOKENS)

    for i, tk in enumerate(TOKENS, start=1):
        sym = tk["symbol"]
        logging.info(f"[{i}/{nb_tokens}] => symbol={sym}")
        df_lunar = fetch_lunar_data(sym)
        if df_lunar is None or df_lunar.empty:
            logging.warning(f"No data for {sym}, skipping.")
            continue

        # Calcul du label
        df_lunar = compute_label(df_lunar, SHIFT_DAYS, THRESHOLD)

        # Calcul RSI, MACD, ATR
        df_indic = compute_rsi_macd_atr(df_lunar)

        # On fusionne pour conserver le label
        df_indic["label"] = df_lunar["label"]

        # Ajout du symbole
        df_indic["symbol"] = sym

        # On drop les lignes sans label
        df_indic.dropna(subset=["label"], inplace=True)

        all_dfs.append(df_indic)

        # Pour limiter le rate-limit
        time.sleep(SLEEP_BETWEEN_TOKENS)

    if not all_dfs:
        logging.warning("No data => no CSV.")
        print("No data => no CSV. Check logs.")
        return

    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["symbol","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    # Export
    df_final.to_csv(OUTPUT_CSV, index=False)
    logging.info(f"Export => {OUTPUT_CSV} => {len(df_final)} rows")
    print(f"Export => {OUTPUT_CSV} ({len(df_final)} rows)")

    logging.info("=== DONE build_csv with RSI/MACD/ATR ===")


if __name__ == "__main__":
    main()
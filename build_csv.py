#!/usr/bin/env python3
# coding: utf-8

import requests
import pandas as pd
import time
import logging
import os
from datetime import datetime, timedelta

#####################################
# PARAMÈTRES GLOBAUX ET CLÉS API
#####################################
CMC_API_KEY = "0a602f8f-2a68-4992-89f2-7e7416a4d8e8"
LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"

DAYS = 30                  # Nombre de jours d’historique
SHIFT_DAYS = 2             # Décalage pour calcul du label
THRESHOLD = 0.30           # Seuil de hausse => label=1
OUTPUT_CSV = "training_data.csv"
LOG_FILE = "build_csv.log"

# Logger
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START build_csv ===")

#####################################
# LISTE DES TOKENS
#####################################
TOKENS = [
    # Exemple: juste 4 tokens pour la démonstration,
    # Remplacez par votre liste des 102 tokens
    {
        "symbol": "SOLVEX",
        "cmc_id": 9604,
        "lunar_symbol": "SOLVEX"
    },
    {
        "symbol": "ETH",
        "cmc_id": 1027,
        "lunar_symbol": "ETH"
    },
    {
        "symbol": "LINK",
        "cmc_id": 1975,
        "lunar_symbol": "LINK"
    },
    {
        "symbol": "MOEW",
        "cmc_id": 28839,
        "lunar_symbol": "MOEW"
    },
    # ... ajoutez ici les 102 tokens ...
]

#####################################
# FONCTIONS
#####################################

# Compteur global d'appels CMC => on fait une pause après 30 calls
CMC_CALL_COUNT = 0

def build_daily_date_range(days=30):
    """
    Construit une liste de dates (datetime) du jour J-29 jusqu'à J (inclus).
    Ex: [2024-01-01, 2024-01-02, ... 2024-01-30]
    Triée chronologiquement.
    """
    end_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=days-1)
    # On génère du start_date au end_date inclus
    date_list = [start_date + timedelta(days=i) for i in range(days)]
    return date_list

def fetch_cmc_history(cmc_id, days=30):
    """
    Récupère l'historique daily sur 'days' jours pour le token (id=cmc_id).
    Retourne un dict { date_str: (close, volume, market_cap) } OU dict vide si échec.
    Les dates_str seront au format "YYYY-MM-DD".
    """
    global CMC_CALL_COUNT

    # On détermine time_start / time_end
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accept": "application/json"
    }
    params = {
        "id": str(cmc_id),
        "time_start": start_date.isoformat(),
        "time_end": end_date.isoformat(),
        "interval": "1d",
        "count": days,
        "convert": "USD"
    }

    # Pause si on a déjà fait 30 appels
    CMC_CALL_COUNT += 1
    if CMC_CALL_COUNT % 30 == 0:
        logging.info("[CMC DEBUG] Reached 30 calls => sleeping 60s to avoid 429")
        time.sleep(60)

    out = {}  # date_str -> (close, volume, mcap)
    try:
        r = requests.get(url, headers=headers, params=params, timeout=25)
        logging.info(f"[CMC DEBUG] cmc_id={cmc_id} status={r.status_code}")
        if r.status_code != 200:
            logging.warning(f"[CMC WARNING] cmc_id={cmc_id}, HTTP={r.status_code} => No data.")
            return out

        j = r.json()
        if "data" not in j or not j["data"]:
            logging.warning(f"[CMC WARNING] cmc_id={cmc_id} => JSON sans 'data'.")
            return out

        quotes = j["data"].get("quotes", [])
        for q in quotes:
            t = q.get("timestamp")
            if not t:
                continue
            # parse la date
            dd = datetime.fromisoformat(t.replace("Z",""))
            date_str = dd.strftime("%Y-%m-%d")

            usd = q["quote"].get("USD", {})
            c = usd.get("close")
            vol = usd.get("volume")
            mc = usd.get("market_cap")
            # On stocke
            out[date_str] = (c, vol, mc)

        return out

    except Exception as e:
        logging.error(f"[CMC ERROR] {cmc_id} => {e}")
        return {}

def fetch_lunar_history(symbol):
    """
    Récupère ~30 jours en daily depuis LunarCrush (time-series/v2).
    Retourne un dict date_str -> (galaxy_score, alt_rank, sentiment).
    date_str = "YYYY-MM-DD"
    """
    base_url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "interval": "1m"  # ~30 jours
    }

    out = {}
    try:
        r = requests.get(base_url, params=params, timeout=25)
        logging.info(f"[LUNAR DEBUG] symbol={symbol} status={r.status_code}")
        if r.status_code != 200:
            logging.warning(f"[LUNAR WARNING] {symbol} => HTTP={r.status_code}, no data.")
            return out

        data_json = r.json()
        if "data" not in data_json or not data_json["data"]:
            logging.warning(f"[LUNAR WARNING] {symbol} => no data in JSON.")
            return out

        for row in data_json["data"]:
            # row["time"] = epoch
            epoch_ts = row.get("time")
            if not epoch_ts:
                continue
            dt_utc = datetime.utcfromtimestamp(epoch_ts)
            date_str = dt_utc.strftime("%Y-%m-%d")

            gal = row.get("galaxy_score", None)
            alt_r = row.get("alt_rank", None)
            senti = row.get("sentiment", None)

            out[date_str] = (gal, alt_r, senti)
        return out

    except Exception as e:
        logging.error(f"[LUNAR ERROR] {symbol} => {e}")
        return {}

def compute_label_column(df):
    """
    df contient : date, close, etc.
    On crée label = 1 si variation >= 30% dans SHIFT_DAYS=2 jours, sinon 0, sinon None si data manquante.
    """
    # index par date => on peut itérer
    df = df.sort_values("date").reset_index(drop=True)
    close_list = df["close"].tolist()

    labels = []
    for i in range(len(df)):
        if i + SHIFT_DAYS >= len(df):
            labels.append(None)
            continue
        c0 = close_list[i]
        c2 = close_list[i + SHIFT_DAYS]
        if c0 is None or c2 is None:
            labels.append(None)
            continue
        # variation
        var_2d = (c2 - c0) / c0
        lab = 1 if var_2d >= THRESHOLD else 0
        labels.append(lab)

    df["label"] = labels
    return df

def main():
    logging.info("=== build_csv => collecting data for tokens ===")
    all_dfs = []

    # On crée un "template" date range = 30 jours [J-29..J]
    date_range = build_daily_date_range(days=DAYS)
    date_strs = [dt.strftime("%Y-%m-%d") for dt in date_range]

    for token_info in TOKENS:
        sym = token_info["symbol"]
        cmc_id = token_info["cmc_id"]
        lunar_sym = token_info["lunar_symbol"]

        logging.info(f"=== TOKEN {sym} (cmc_id={cmc_id}, lunar={lunar_sym}) ===")

        # 1) Récup Data CMC
        cmc_data = fetch_cmc_history(cmc_id, DAYS)
        logging.info(f"[{sym}] CMC data => {len(cmc_data)} entries")

        # 2) Récup Data Lunar
        lunar_data = fetch_lunar_history(lunar_sym)
        logging.info(f"[{sym}] Lunar data => {len(lunar_data)} entries")

        # 3) Construire un DataFrame "jour par jour" sur 30 jours
        rows = []
        for d_str in date_strs:
            # par défaut None
            close, vol, mc = (None, None, None)
            gal, alt_r, senti = (None, None, None)

            if d_str in cmc_data:
                close, vol, mc = cmc_data[d_str]

            if d_str in lunar_data:
                gal, alt_r, senti = lunar_data[d_str]

            rows.append({
                "date_str": d_str,
                "close": close,
                "volume": vol,
                "market_cap": mc,
                "galaxy_score": gal,
                "alt_rank": alt_r,
                "sentiment": senti
            })

        df = pd.DataFrame(rows)
        # On transforme la date_str en datetime
        df["date"] = pd.to_datetime(df["date_str"], format="%Y-%m-%d")
        df.drop(columns=["date_str"], inplace=True)
        df = df.sort_values("date").reset_index(drop=True)

        # 4) Calcul du label
        df = compute_label_column(df)

        # 5) On ajoute la colonne token
        df["token"] = sym

        # Ordre colonnes
        col_order = [
            "token",
            "date",
            "close",
            "volume",
            "market_cap",
            "galaxy_score",
            "alt_rank",
            "sentiment",
            "label"
        ]
        df = df[col_order]

        # Ajout dans all_dfs
        all_dfs.append(df)

        # Pause 2s pour éviter trop de hits Lunar
        time.sleep(2)

    # Fin de la boucle
    if not all_dfs:
        logging.warning("No data => no CSV => nothing to export.")
        print("No data => no CSV.")
        return

    final_df = pd.concat(all_dfs, ignore_index=True)
    final_df.sort_values(["token","date"], inplace=True)
    final_df.reset_index(drop=True, inplace=True)

    final_df.to_csv(OUTPUT_CSV, index=False)
    nb_rows = len(final_df)
    logging.info(f"Export => {OUTPUT_CSV} => {nb_rows} lignes.")
    print(f"Export => {OUTPUT_CSV} => {nb_rows} lignes.")

if __name__=="__main__":
    main()

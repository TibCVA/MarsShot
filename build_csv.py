#!/usr/bin/env python3
# coding: utf-8

import requests
import pandas as pd
import time
import logging
import os
from datetime import datetime, timedelta

#####################################
# PARAMÈTRES GLOBAUX
#####################################
CMC_API_KEY = "0a602f8f-2a68-4992-89f2-7e7416a4d8e8"
LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"

DAYS = 30
SHIFT_DAYS = 2
THRESHOLD = 0.30

OUTPUT_CSV = "training_data.csv"
LOG_FILE = "build_csv.log"

# Pause entre chaque token pour éviter 429 (10 req/min max sur LunarCrush)
PAUSE_SECONDS = 6

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START build_csv ===")

#####################################
# LISTE DES 4 TOKENS (exemple)
#####################################
TOKENS = [
    {
        "symbol": "ETH",
        "cmc_id": 1027,      # CoinMarketCap ID pour Ethereum
        "lunar_symbol": "ETH"
    },
    {
        "symbol": "LINK",
        "cmc_id": 1975,      # CoinMarketCap ID pour Chainlink
        "lunar_symbol": "LINK"
    },
    {
        "symbol": "SOLVEX",
        "cmc_id": 9604,      # CoinMarketCap ID pour Solvex
        "lunar_symbol": "SOLVEX"
    },
    {
        "symbol": "MOEW",
        "cmc_id": 28839,     # CoinMarketCap ID pour Moew
        "lunar_symbol": "MOEW"
    }
]

#####################################
# FONCTIONS
#####################################


def build_date_range(days=30):
    """
    Construit une liste de datetime pour les 'days' derniers jours
    (chaque date à minuit UTC).
    """
    end_utc = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = end_utc - timedelta(days=days-1)
    return [start_utc + timedelta(days=i) for i in range(days)]


def fetch_cmc_history(cmc_id, days=30):
    """
    Récupère un historique daily de 'days' jours via l'endpoint
    /v2/cryptocurrency/ohlcv/historical (CoinMarketCap).
    Retourne un dict date_str => (close, volume, market_cap).
    """
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/ohlcv/historical"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accepts": "application/json"
    }
    params = {
        "id": str(cmc_id),
        "time_start": start_date.isoformat(),
        "time_end": end_date.isoformat(),
        "interval": "1d",
        "count": days,
        "convert": "USD"
    }

    d_result = {}  # date_str -> (close, volume, mcap)

    try:
        r = requests.get(url, headers=headers, params=params, timeout=25)
        logging.info(f"[CMC] GET {url} => status={r.status_code} (id={cmc_id})")
        if r.status_code != 200:
            logging.warning(f"[CMC WARNING] id={cmc_id}, HTTP={r.status_code}")
            return d_result

        j = r.json()
        if "data" not in j or not j["data"]:
            logging.warning(f"[CMC WARNING] id={cmc_id}, no data.")
            return d_result

        quotes = j["data"].get("quotes", [])
        if not quotes:
            return d_result

        for item in quotes:
            # item["time_close"] ex: "2024-12-01T23:59:59.999Z"
            t_close = item.get("time_close")
            if not t_close:
                continue

            dt_ = datetime.fromisoformat(t_close.replace("Z",""))
            date_str = dt_.strftime("%Y-%m-%d")

            usd = item["quote"].get("USD", {})
            c = usd.get("close")
            vol = usd.get("volume")
            mc = usd.get("market_cap")

            if c is None:
                # On laisse possiblement volume, mc ?
                # Mais si close=None => on met un tri ? On met tout None
                c = None
            # On stocke
            d_result[date_str] = (c, vol, mc)

        return d_result

    except Exception as e:
        logging.error(f"[CMC ERROR] {cmc_id} => {e}")
        return d_result


def fetch_lunar_history(symbol):
    """
    Récupère l'historique ~30 jours (bucket=day, interval=1m) sur LunarCrush
    => dict date_str => (galaxy_score, alt_rank, sentiment).
    """
    base_url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "interval": "1m"
    }

    out = {}
    try:
        r = requests.get(base_url, params=params, timeout=25)
        logging.info(f"[LUNAR] symbol={symbol}, status={r.status_code}")
        if r.status_code != 200:
            logging.warning(f"[LUNAR WARN] {symbol} => HTTP {r.status_code}")
            return out

        data_j = r.json()
        if ("data" not in data_j) or (not data_j["data"]):
            logging.warning(f"[LUNAR WARN] {symbol} => data vide.")
            return out

        for row in data_j["data"]:
            epoch = row.get("time")
            if not epoch:
                continue
            dt_utc = datetime.utcfromtimestamp(epoch)
            date_str = dt_utc.strftime("%Y-%m-%d")

            gal = row.get("galaxy_score")    # ex. 75
            alt = row.get("alt_rank")        # ex. 200
            senti = row.get("sentiment")     # ex. 60

            out[date_str] = (gal, alt, senti)
        return out
    except Exception as e:
        logging.error(f"[LUNAR ERROR] {symbol} => {e}")
        return out


def compute_label_column(df):
    """
    SHIFT_DAYS=2 => on regarde la variation (close J+2 - close J)/close J
    label=1 si >= THRESHOLD, 0 sinon, ou None si close manquant.
    """
    df = df.sort_values("date").reset_index(drop=True)
    prices = df["close"].tolist()
    labels = []

    for i in range(len(prices)):
        if i + SHIFT_DAYS >= len(prices):
            labels.append(None)
            continue
        c0 = prices[i]
        c2 = prices[i + SHIFT_DAYS]
        if (c0 is None) or (c2 is None):
            labels.append(None)
            continue
        var_2d = (c2 - c0) / c0
        lab = 1 if var_2d >= THRESHOLD else 0
        labels.append(lab)

    df["label"] = labels
    return df


def main():
    logging.info("=== build_csv => Start for 4 tokens ===")

    # On construit une liste de 30 dates (J-29..J)
    date_list = build_date_range(DAYS)
    date_strs = [dt.strftime("%Y-%m-%d") for dt in date_list]

    all_dfs = []

    for idx, tk in enumerate(TOKENS, start=1):
        sym = tk["symbol"]
        cmc_id = tk["cmc_id"]
        lunar_sym = tk["lunar_symbol"]
        logging.info(f"Token {idx}/{len(TOKENS)} => {sym}, cmc_id={cmc_id}, lunar={lunar_sym}")

        # 1) Récup CMC
        cmc_map = fetch_cmc_history(cmc_id, DAYS)  # dict date_str->(c, vol, mc)
        logging.info(f"[{sym}] cmc_map => {len(cmc_map)} data points")

        # 2) Récup LunarCrush
        lunar_map = fetch_lunar_history(lunar_sym)  # dict date_str->(gal, alt, senti)
        logging.info(f"[{sym}] lunar_map => {len(lunar_map)} data points")

        # 3) Construire un DataFrame day par day
        rows = []
        for d_str in date_strs:
            c = None
            v = None
            mc = None
            gal = None
            alt_r = None
            senti = None

            if d_str in cmc_map:
                c, v, mc = cmc_map[d_str]

            if d_str in lunar_map:
                gal, alt_r, senti = lunar_map[d_str]

            rows.append({
                "date_str": d_str,
                "close": c,
                "volume": v,
                "market_cap": mc,
                "galaxy_score": gal,
                "alt_rank": alt_r,
                "sentiment": senti
            })

        df_token = pd.DataFrame(rows)
        df_token["date"] = pd.to_datetime(df_token["date_str"], format="%Y-%m-%d")
        df_token.drop(columns=["date_str"], inplace=True)

        df_token.sort_values("date", inplace=True)
        df_token.reset_index(drop=True, inplace=True)

        # 4) label
        df_token = compute_label_column(df_token)

        # 5) Ajoute la colonne token
        df_token["token"] = sym

        # 6) On réordonne
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
        df_token = df_token[col_order]

        all_dfs.append(df_token)

        # On attend 6s pour éviter trop de hits (~10 req/min sur LunarCrush)
        time.sleep(PAUSE_SECONDS)

    # Concat final
    if not all_dfs:
        logging.warning("No data => no CSV")
        print("No data => no CSV.")
        return

    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["token","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    # Export
    df_final.to_csv(OUTPUT_CSV, index=False)
    nb_lines = len(df_final)
    print(f"Export => {OUTPUT_CSV} ({nb_lines} lignes)")
    logging.info(f"Export => {OUTPUT_CSV} => {nb_lines} lignes")


if __name__=="__main__":
    main()

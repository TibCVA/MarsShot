#!/usr/bin/env python3
# coding: utf-8

import requests
import logging
import json
from datetime import datetime, timedelta

"""
check_solvex_endpoints.py
-------------------------
Ce script interroge DEUX endpoints CoinMarketCap (pour un token spécifique)
afin de vérifier exactement quelles données daily sont renvoyées, et si
"open/high/low/close" sont présents ou non.

1) /v2/cryptocurrency/quotes/historical
2) /v2/cryptocurrency/ohlcv/historical

OBJECTIF:
- Repérer si l'un ou l'autre endpoint fournit un "open"/"high"/"low"/"close".
- Voir si le token est réellement couvert sur 30 jours, etc.

LOGS:
- Fichier: check_solvex_endpoints.log
- Dump JSON partiels (extraits) => check les champs disponibles.

UTILISATION:
1) python check_solvex_endpoints.py
2) Consultez check_solvex_endpoints.log
"""

CMC_API_KEY = "0a602f8f-2a68-4992-89f2-7e7416a4d8e8"  # votre clé
LOG_FILE = "check_solvex_endpoints.log"

# On prend l'ID "Solvex" = 9604 (d'après vos retours)
SOLVEX_ID = 9604
DAYS = 30

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

def main():
    logging.info("=== START check_solvex_endpoints ===")

    # 1) "quotes/historical"
    #    => https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical
    #    On teste sur 30j
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=DAYS)

    url_quotes_historical = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accepts": "application/json"
    }
    params_q = {
        "id": str(SOLVEX_ID),
        "time_start": start_date.isoformat(),
        "time_end": end_date.isoformat(),
        "interval": "1d",
        "count": DAYS,   
        "convert": "USD"
    }

    logging.info(f"[REQUEST quotes_historical] ID={SOLVEX_ID} => {url_quotes_historical}, params={params_q}")

    try:
        r1 = requests.get(url_quotes_historical, headers=headers, params=params_q)
        sc1 = r1.status_code
        txt1 = r1.text[:700].replace("\n"," ")
        logging.info(f"[RESPONSE quotes_historical] status={sc1}, excerpt={txt1}")

        if sc1 == 200:
            j1 = r1.json()
            # On va logguer la structure "quotes" si elle existe
            quotes_data = j1.get("data", {}).get("quotes", [])
            logging.info(f"[quotes_historical] nb_quotes={len(quotes_data)}")
            if quotes_data:
                # On log 1-2 exemples
                snippet = json.dumps(quotes_data[:2], indent=2)  # 2 premiers quotes
                logging.info(f"[quotes_historical] first_2_quotes => {snippet}")
        else:
            logging.warning(f"[quotes_historical] HTTP {sc1} => no data ?")

    except Exception as e:
        logging.error(f"[quotes_historical] error => {e}")

    # 2) "ohlcv/historical"
    #    => https://pro-api.coinmarketcap.com/v2/cryptocurrency/ohlcv/historical
    #    On teste sur la même période 30j, daily
    url_ohlcv_historical = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/ohlcv/historical"
    params_o = {
        "id": str(SOLVEX_ID),
        "time_start": start_date.isoformat(),
        "time_end": end_date.isoformat(),
        "interval": "1d",      # daily
        "count": DAYS,
        "convert": "USD"
    }

    logging.info(f"[REQUEST ohlcv_historical] ID={SOLVEX_ID} => {url_ohlcv_historical}, params={params_o}")

    try:
        r2 = requests.get(url_ohlcv_historical, headers=headers, params=params_o)
        sc2 = r2.status_code
        txt2 = r2.text[:700].replace("\n"," ")
        logging.info(f"[RESPONSE ohlcv_historical] status={sc2}, excerpt={txt2}")

        if sc2 == 200:
            j2 = r2.json()
            # On va logguer "quotes" aussi
            data2 = j2.get("data", {})
            # Sur /ohlcv/historical, on a data: { "id":..., "name":..., "symbol":..., "quotes": [...] }
            quotes2 = data2.get("quotes", [])
            logging.info(f"[ohlcv_historical] nb_quotes={len(quotes2)}")
            if quotes2:
                snippet2 = json.dumps(quotes2[:2], indent=2)
                logging.info(f"[ohlcv_historical] first_2_quotes => {snippet2}")
        else:
            logging.warning(f"[ohlcv_historical] HTTP {sc2} => no data ?")

    except Exception as e:
        logging.error(f"[ohlcv_historical] error => {e}")

    logging.info("=== END check_solvex_endpoints ===")


if __name__=="__main__":
    main()
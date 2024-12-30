#!/usr/bin/env python3
# coding: utf-8

"""
Script de test LunarCrush v4 /public/coins/:coin/time-series/v2
pour 3 tokens: SOLVEX, ETH, LINK
Récupération sur ~30 jours (daily) => galaxy_score, alt_rank, sentiment
Log file => check_solvex_test.log
"""

import requests
import logging
import time
import sys
from datetime import datetime

#####################################
# 1) Clé API
#####################################
LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"

#####################################
# 2) Nom du fichier de log
#####################################
LOG_FILE = "check_solvex_test.log"

#####################################
# 3) Configuration du logging
#####################################
with open(LOG_FILE, "w", encoding="utf-8") as ff:
    ff.write("Initialisation du log.\n")

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

#####################################
# 4) Liste des tokens à tester
#####################################
TOKENS = [
    { "name": "Solvex",   "symbol": "SOLVEX" },
    { "name": "Ethereum", "symbol": "ETH"    },
    { "name": "Chainlink","symbol": "LINK"   }
]

#####################################
# 5) Fonction de récupération
#####################################
def fetch_lunar_timeseries(symbol):
    """
    Tente de récupérer l'historique sur 30 jours (daily) pour 'symbol'
    via /public/coins/:coin/time-series/v2
    bucket=day, interval=1m
    On renvoie la liste extraite (ou None si introuvable).
    """

    base_url = "https://lunarcrush.com/api4/public/coins"
    # Endpoint v2: /:coin/time-series/v2
    # Ex: /public/coins/ETH/time-series/v2?bucket=day&interval=1m&key=API_KEY

    url = f"{base_url}/{symbol}/time-series/v2"
    params = {
        "bucket": "day",
        "interval": "1m",
        "key": LUNAR_API_KEY
    }
    logging.info(f"[LUNAR] GET {url}, params={params}")
    try:
        r = requests.get(url, params=params, timeout=10)
        sc = r.status_code
        logging.info(f"[LUNAR] status_code={sc}")
        if sc != 200:
            logging.warning(f"[LUNAR] HTTP {sc} => return None")
            return None

        j = r.json()
        # structure attendue: { "data": [{...}, {...}, ...] }
        if ("data" not in j) or (not j["data"]):
            logging.warning("[LUNAR] data vide => None")
            return None
        
        # j["data"] est censé être un tableau d'objets pour chaque jour
        return j["data"]

    except Exception as e:
        logging.error(f"[LUNAR] Exception => {e}")
        return None

#####################################
# 6) main
#####################################
def main():
    logging.info("=== START check_solvex_test ===")

    for tk in TOKENS:
        name = tk["name"]
        sym  = tk["symbol"]

        logging.info(f"--- TOKEN {name} ({sym}) ---")
        print(f"\n=== {name} ({sym}) ===")

        data = fetch_lunar_timeseries(sym)
        if not data:
            msg = f"{sym} => introuvable ou data vide."
            logging.info(msg)
            print(msg)
            time.sleep(1)
            continue

        # data => liste de daily points
        # On affiche galaxy_score, alt_rank, sentiment s'ils existent
        for day_obj in data:
            # ex: day_obj.get("time") => timestamp
            ts = day_obj.get("time")  # ex: 1696003200
            dt = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else "???"
            gal   = day_obj.get("galaxy_score")
            alt   = day_obj.get("alt_rank")
            senti = day_obj.get("sentiment", None)  # pas sûr qu'il existe
            # On log et on print
            line = f"{dt} => galaxy_score={gal}, alt_rank={alt}, sentiment={senti}"
            logging.info(line)
            print(line)

        time.sleep(1)

    logging.info("=== END check_solvex_test ===")


if __name__=="__main__":
    main()
    sys.exit(0)
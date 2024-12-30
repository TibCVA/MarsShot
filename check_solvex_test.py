#!/usr/bin/env python3
# coding: utf-8

"""
Exemple de script LunarCrush avec timeout=20s et retry (pause 40s) en cas de time-out
Log file => check_solvex_test.log
"""

import requests
import logging
import time
import sys
import os

#####################################
# 1) Clés API
#####################################
LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"

#####################################
# 2) Nom du fichier de log
#####################################
LOG_FILE = "check_solvex_test.log"

#####################################
# 3) Configuration du logging
#####################################
# On force la création du fichier en l’ouvrant en mode "w" une première fois.
with open(LOG_FILE, "w", encoding="utf-8") as ff:
    ff.write("Initialisation du log.\n")

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",  # on append après avoir créé le fichier
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

#####################################
# 4) Liste des tokens
#####################################
TOKENS = [
    {
        "name": "Solvex",
        "symbol": "SOLVEX"
    },
    {
        "name": "Ethereum",
        "symbol": "ETH"
    },
    {
        "name": "Chainlink",
        "symbol": "LINK"
    }
]

#####################################
# 5) Fonction de récupération time-series
#####################################
def fetch_lunar_timeseries(symbol, bucket="day", interval="1m", max_retries=3):
    """
    Récupère la time-series (v2) sur ~30 jours, renvoie (success, data) ou (False, None)
    On ajoute un retry en cas de time-out ou de code d'erreur.
    """
    base_url = "https://lunarcrush.com/api4/public/coins"
    url = f"{base_url}/{symbol}/time-series/v2"

    params = {
        "key": LUNAR_API_KEY,
        "bucket": bucket,       # "day"
        "interval": interval    # ex: "1m" => correspond ~30 jours
    }

    for attempt in range(1, max_retries+1):
        logging.info(f"[LUNAR] GET {url}, params={params}, attempt={attempt}/{max_retries}")
        try:
            r = requests.get(url, params=params, timeout=20)  # <-- timeout=20s
            sc = r.status_code
            logging.info(f"[LUNAR] status_code={sc}")
            if sc == 200:
                j = r.json()
                if j and "data" in j and j["data"]:
                    return (True, j["data"])
                else:
                    logging.info(f"[LUNAR] data vide pour {symbol}.")
                    return (False, None)
            else:
                logging.warning(f"[LUNAR] HTTP {sc} => on retente si possible...")
        except requests.exceptions.Timeout:
            logging.error(f"[LUNAR] Time-out sur {symbol}.")
        except Exception as e:
            logging.error(f"[LUNAR] Exception => {e}")

        if attempt < max_retries:
            logging.info(f"... wait 40s before retry ...")
            time.sleep(40)

    # Si on arrive ici => échec final
    return (False, None)

#####################################
# 6) main
#####################################
def main():
    logging.info("=== START check_solvex_test ===")

    for t in TOKENS:
        name = t["name"]
        symbol = t["symbol"]
        logging.info(f"--- TOKEN {name} ({symbol}) ---")

        success, data = fetch_lunar_timeseries(symbol)
        if not success or not data:
            logging.info(f"{symbol} => introuvable ou data vide.")
            continue

        # On suppose qu'on boucle sur data => each item => on récupère galaxy_score, alt_rank, sentiment
        # data est typiquement un tableau d'objets
        for dline in data:
            dt = dline.get("time")  # la date en timestamp ?
            # Dans la doc v4, la structure "time" est un UNIX timestamp, il faut parfois le convertir
            # On imagine un champ "galaxy_score", "alt_rank" et "sentiment"
            gs = dline.get("galaxy_score", None)
            ar = dline.get("alt_rank", None)
            st = dline.get("sentiment", None)

            # On log
            logging.info(f"ts={dt} => galaxy_score={gs}, alt_rank={ar}, sentiment={st}")

        time.sleep(2)

    logging.info("=== END check_solvex_test ===")

if __name__=="__main__":
    main()
    sys.exit(0)
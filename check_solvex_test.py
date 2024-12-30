#!/usr/bin/env python3
# coding: utf-8

"""
Script de test pour 3 tokens: SOLVEX, ETH, LINK
Uniquement via LunarCrush
Log file => check_solvex_test.log
"""

import requests
import logging
import time
import sys
import os

#####################################
# 1) Clé API LunarCrush
#####################################
LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"

#####################################
# 2) Nom du fichier de log
#####################################
LOG_FILE = "check_solvex_test.log"

#####################################
# 3) Configuration du logging
#####################################
# On force la création (ou la réinitialisation) du fichier de log en le vidant d'abord.
with open(LOG_FILE, "w", encoding="utf-8") as ff:
    ff.write("Initialisation du log.\n")

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",  # append
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

#####################################
# 4) Liste des tokens
#####################################
TOKENS = [
    {
        "name": "Solvex",
        "symbol": "SOLVEX",
    },
    {
        "name": "Ethereum",
        "symbol": "ETH",
    },
    {
        "name": "Chainlink",
        "symbol": "LINK",
    }
]

#####################################
# 5) Fonction pour récupérer sentiment
#####################################
def test_lunar_sentiment(symbol):
    """
    Récupère un 'sentiment' approximatif via l'API LunarCrush V4.
    URL: https://api.lunarcrush.com/v4/assets?symbol=SYMBOL&data=market
    On normalise 'social_score' sur [0..1].
    Retourne (status_code, sentiment, excerpt).
    """
    url = "https://api.lunarcrush.com/v4/assets"
    headers = {
        "Authorization": f"Bearer {LUNAR_API_KEY}"
    }
    params = {
        "symbol": symbol,
        "data": "market"
    }

    logging.info(f"[LUNAR] GET {url}?symbol={symbol}&data=market")
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        sc = r.status_code
        excerpt = r.text[:300].replace("\n", " ")
        logging.info(f"[LUNAR] status_code={sc}, excerpt={excerpt}")

        if sc != 200:
            logging.warning(f"[LUNAR] HTTP {sc} => sentiment=0.5")
            return (sc, 0.5, excerpt)

        j = r.json()
        arr = j.get("data", [])
        if not arr:
            logging.warning("[LUNAR] data vide => sentiment=0.5")
            return (sc, 0.5, excerpt)

        first_item = arr[0]
        sc_val = first_item.get("social_score", 50)  # fallback 50
        maxi = max(sc_val, 100)
        val = sc_val / maxi
        if val > 1:
            val = 1
        return (sc, val, excerpt)

    except Exception as e:
        logging.error(f"[LUNAR] Exception => {e}")
        return (None, 0.5, f"Exception: {e}")

#####################################
# 6) main
#####################################
def main():
    logging.info("=== START check_solvex_test ===")

    for t in TOKENS:
        name = t["name"]
        symbol = t["symbol"]

        logging.info(f"--- TOKEN {name} ({symbol}) ---")

        # Récupération sentiment
        st_l, sentiment, excerpt = test_lunar_sentiment(symbol)

        # On logge en console pour voir
        print(f"{name} [{symbol}] => sentiment={sentiment:.3f}")
        time.sleep(2)

    logging.info("=== END check_solvex_test ===")


if __name__ == "__main__":
    main()
    sys.exit(0)
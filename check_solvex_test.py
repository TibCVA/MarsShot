#!/usr/bin/env python3
# coding: utf-8

"""
Script de test pour 3 tokens: SOLVEX, ETH, LINK
Uniquement via LunarCrush, sans fallback IP.
On désactive la vérification SSL (verify=False) en dernier recours.
Log file => check_solvex_test.log
"""

import requests
import logging
import time
import sys

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
with open(LOG_FILE, "w", encoding="utf-8") as ff:
    ff.write("Initialisation du log.\n")

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",  
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
# 5) Requête LunarCrush
#####################################
def do_lunarcrush_request(symbol):
    """
    Effectue la requête sur "api.lunarcrush.com/v4/assets".
    On force verify=False pour éviter les soucis de certificat,
    mais la résolution DNS doit marcher.
    """
    url = "https://api.lunarcrush.com/v4/assets"
    headers = {
        "Authorization": f"Bearer {LUNAR_API_KEY}"
    }
    params = {
        "symbol": symbol,
        "data": "market"
    }

    logging.info(f"[LUNAR] GET {url} (verify=False), symbol={symbol}")
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10, verify=False)
        sc = r.status_code
        excerpt = r.text[:300].replace("\n", " ")
        logging.info(f"[LUNAR] status_code={sc}, excerpt={excerpt}")

        if sc != 200:
            logging.warning(f"[LUNAR] HTTP {sc} => sentiment=0.5")
            return 0.5
        j = r.json()
        return parse_sentiment(j)

    except Exception as e:
        logging.error(f"[LUNAR] Exception => {e}")
        return 0.5

def parse_sentiment(jsondata):
    """
    Extrait un éventuel social_score normalisé [0..1].
    Sinon renvoie 0.5
    """
    arr = jsondata.get("data", [])
    if not arr:
        return 0.5
    first = arr[0]
    sc_val = first.get("social_score", 50)
    maxi = max(sc_val, 100)
    val = sc_val/maxi
    if val>1:
        val=1
    return val

#####################################
# 6) main
#####################################
def main():
    logging.info("=== START check_solvex_test ===")
    for t in TOKENS:
        name = t["name"]
        sym = t["symbol"]
        logging.info(f"--- TOKEN {name} ({sym}) ---")
        senti = do_lunarcrush_request(sym)
        print(f"{name} [{sym}] => sentiment={senti:.3f}")
        time.sleep(2)
    logging.info("=== END check_solvex_test ===")

if __name__ == "__main__":
    main()
    sys.exit(0)
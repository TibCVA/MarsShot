#!/usr/bin/env python3
# coding: utf-8

"""
Script de test Nansen & LunarCrush pour 3 tokens: SOLVEX, ETH, LINK
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
NANSEN_API_KEY = "QOkxEu97HMywRodE4747YpwVsivO690Fl6arVXoe"
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
        "symbol": "SOLVEX",
        "chain": "eth",
        "contract": "0x2d7a47908d817dd359b9595c19f6d9e1c994472a",
        "lunar_symbol": "SOLVEX"
    },
    {
        "name": "Ethereum",
        "symbol": "ETH",
        "chain": None,  # natif => pas de contract
        "contract": None,
        "lunar_symbol": "ETH"
    },
    {
        "name": "Chainlink",
        "symbol": "LINK",
        "chain": "eth",
        "contract": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
        "lunar_symbol": "LINK"
    }
]

#####################################
# 5) Fonctions
#####################################
def test_nansen_holders(chain, contract):
    """
    Récupère le nombre de holders depuis Nansen.
    Retourne (status_code, holders_count, excerpt).
    """
    if not chain or not contract:
        logging.info("[NANSEN] chain/contract manquants => 0 holders")
        return (None, 0, "no chain/contract => skip")

    url = f"https://api.nansen.ai/tokens/{chain}/{contract}/holders"
    headers = {"X-API-KEY": NANSEN_API_KEY}

    logging.info(f"[NANSEN] GET {url}")
    try:
        r = requests.get(url, headers=headers)
        sc = r.status_code
        excerpt = r.text[:300].replace("\n"," ")
        logging.info(f"[NANSEN] status_code={sc}, excerpt={excerpt}")
        if sc != 200:
            logging.warning(f"[NANSEN] HTTP {sc} => holders=0")
            return (sc, 0, excerpt)

        j = r.json()
        holders = j.get("data", {}).get("holders", 0)
        return (sc, holders, excerpt)

    except Exception as e:
        logging.error(f"[NANSEN] Exception => {e}")
        return (None, 0, f"Exception: {e}")

def test_lunar_sentiment(symbol):
    """
    Récupère le social_score sur [0..1], ou 0.5 si pb.
    Retourne (status_code, score, excerpt).
    """
    url = f"https://lunarcrush.com/api2?symbol={symbol}&data=market"
    headers = {"Authorization": f"Bearer {LUNAR_API_KEY}"}

    logging.info(f"[LUNAR] GET {url}")
    try:
        r = requests.get(url, headers=headers)
        sc = r.status_code
        excerpt = r.text[:300].replace("\n"," ")
        logging.info(f"[LUNAR] status_code={sc}, excerpt={excerpt}")

        if sc != 200:
            logging.warning(f"[LUNAR] HTTP {sc} => sentiment=0.5")
            return (sc, 0.5, excerpt)

        j = r.json()
        if ("data" not in j) or (not j["data"]):
            logging.warning("[LUNAR] data vide => sentiment=0.5")
            return (sc, 0.5, excerpt)

        dd = j["data"][0]
        sc_val = dd.get("social_score", 50)
        maxi = max(sc_val, 100)
        val = sc_val/maxi
        if val>1:
            val=1
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
        chain = t["chain"]
        contract = t["contract"]
        lun_sym = t["lunar_symbol"]

        logging.info(f"--- TOKEN {name} ({symbol}) ---")
        # Nansen
        st_n, holders, exc_n = test_nansen_holders(chain, contract)
        # Lunar
        st_l, sentiment, exc_l = test_lunar_sentiment(lun_sym)

        # print en console
        print(f"{name} [{symbol}] => holders={holders}, sentiment={sentiment:.4f}")
        time.sleep(2)

    logging.info("=== END check_solvex_test ===")

if __name__=="__main__":
    main()
    sys.exit(0)
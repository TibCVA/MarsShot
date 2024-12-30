#!/usr/bin/env python3
# coding: utf-8

"""
Script de test Nansen & LunarCrush pour 3 tokens: SOLVEX, ETH, LINK
Objectif:
  - Vérifier holders (Nansen) et social_score (LunarCrush)
  - Loguer toutes les infos utiles pour debugger
"""

import requests
import logging
import time
import sys

#####################################
# 1) Clés API
#####################################
NANSEN_API_KEY = "QOkxEu97HMywRodE4747YpwVsivO690Fl6arVXoe"
LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"

#####################################
# 2) Configuration du logging
#####################################
LOG_FILE = "check_solvex_eth_link.log"
logging.basicConfig(
    filename=LOG_FILE,
    filemode="w",  # on écrase à chaque run
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

#####################################
# 3) Liste des tokens
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
        "chain": None,  # pas de holders tracké sur Nansen pour le token natif
        "contract": None,
        "lunar_symbol": "ETH"
    },
    {
        "name": "Chainlink",
        "symbol": "LINK",
        "chain": "eth",
        "contract": "0x514910771AF9Ca656af840dff83E8264EcF986CA",  # Contrat ERC-20 officiel
        "lunar_symbol": "LINK"
    }
]

#####################################
# 4) Fonctions de test
#####################################
def test_nansen_holders(chain, contract):
    """
    Récupère le nombre de holders depuis Nansen.
    Si chain=None ou contract=None => renvoie 0 directement.
    Logue:
      - URL
      - status_code
      - excerpt
    Retourne (status_code, holders_count, excerpt)
    """
    if not chain or not contract:
        logging.info("[NANSEN] chain/contract manquants => return 0 holders")
        return (None, 0, "no chain/contract => no call")

    url = f"https://api.nansen.ai/tokens/{chain}/{contract}/holders"
    headers = {"X-API-KEY": NANSEN_API_KEY}

    logging.info(f"[NANSEN] GET {url}")
    try:
        r = requests.get(url, headers=headers)
        sc = r.status_code
        excerpt = r.text[:300].replace("\n"," ")
        logging.info(f"[NANSEN] status_code={sc}, excerpt={excerpt}")
        if sc != 200:
            logging.warning(f"[NANSEN] HTTP {sc}, pas de holders.")
            return (sc, 0, excerpt)

        j = r.json()
        holders = j.get("data", {}).get("holders", 0)
        return (sc, holders, excerpt)

    except Exception as e:
        logging.error(f"[NANSEN] Exception => {e}")
        return (None, 0, f"Exception: {e}")

def test_lunar_sentiment(symbol):
    """
    Récupère le social_score pour 'symbol' via LunarCrush.
    Logue:
      - url
      - status_code
      - excerpt
    Retourne (status_code, social_score, excerpt)
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
            logging.warning(f"[LUNAR] HTTP {sc}, on renvoie 0.5 par défaut")
            return (sc, 0.5, excerpt)

        j = r.json()
        if ("data" not in j) or (not j["data"]):
            logging.warning("[LUNAR] 'data' vide => return 0.5")
            return (sc, 0.5, excerpt)

        dd = j["data"][0]
        sc_val = dd.get("social_score", 50)
        # on normalise en [0..1]
        maxi = max(sc_val, 100)
        val = sc_val / maxi
        if val>1:
            val=1
        return (sc, val, excerpt)

    except Exception as e:
        logging.error(f"[LUNAR] Exception => {e}")
        return (None, 0.5, f"Exception: {e}")

#####################################
# 5) main
#####################################
def main():
    logging.info("=== START check_solvex_eth_link ===")

    for t in TOKENS:
        name = t["name"]
        symbol = t["symbol"]
        chain = t["chain"]
        contract = t["contract"]
        lunar_sym = t["lunar_symbol"]

        logging.info(f"--- TOKEN {name} ({symbol}) ---")

        # 1) Nansen
        st_n, holders, exc_n = test_nansen_holders(chain, contract)
        # 2) LunarCrush
        st_l, sentiment, exc_l = test_lunar_sentiment(lunar_sym)

        # On print aussi en console pour un retour direct
        print(f"{name} ({symbol}) => holders={holders}, sentiment_score={sentiment:.4f}")

        # Petit sleep de 2s pour éviter 429
        time.sleep(2)

    logging.info("=== END check_solvex_eth_link ===")

if __name__=="__main__":
    main()
    sys.exit(0)
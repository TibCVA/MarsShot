#!/usr/bin/env python3
# coding: utf-8

import requests
import logging
import json
import sys

#####################################
# CONFIGS / CLES D'API
#####################################
NANSEN_API_KEY = "QOkxEu97HMywRodE4747YpwVsivO690Fl6arVXoe"  # mettre votre clé user si c'est nécessaire
LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"

LOG_FILE = "check_solvex_test.log"
logging.basicConfig(
    filename=LOG_FILE,
    filemode="w",  # pour écraser à chaque run
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logging.info("=== START check_solvex_test ===")

#####################################
# DONNEES SOLVEX
#####################################
SOLVEX = {
    "symbol": "SOLVEX",
    "chain": "eth",
    "contract": "0x2d7a47908d817dd359b9595c19f6d9e1c994472a",
    "lunar_symbol": "SOLVEX"
}

#####################################
# FONCTIONS DE TEST
#####################################
def test_nansen_holders(chain, contract):
    """
    Test Nansen => GET /tokens/{chain}/{contract}/holders
    Retourne un tuple (status_code, holders_val ou None, excerpt)
    """
    if not chain or not contract:
        return (None, None, "No chain or contract => skip")

    url = f"https://api.nansen.ai/tokens/{chain}/{contract}/holders"
    headers = {"X-API-KEY": NANSEN_API_KEY}
    logging.info(f"[NANSEN] GET {url} (chain={chain} contract={contract})")

    try:
        r = requests.get(url, headers=headers)
        sc = r.status_code
        excerpt = r.text[:300].replace("\n"," ")
        logging.info(f"[NANSEN] status_code={sc}, excerpt={excerpt}")
        if sc != 200:
            logging.warning(f"[NANSEN] HTTP {sc} => {r.text}")
            return (sc, None, excerpt)

        j = r.json()
        # j => { "data": { "holders": <val> } }
        holders_val = None
        if "data" in j and isinstance(j["data"], dict):
            holders_val = j["data"].get("holders", None)

        return (sc, holders_val, excerpt)

    except Exception as e:
        logging.error(f"[NANSEN ERROR] {e}")
        return (None, None, f"Exception => {e}")

def test_lunar_sentiment(symbol):
    """
    Test LunarCrush => GET https://lunarcrush.com/api2?symbol={symbol}&data=market
    Retourne (status_code, social_score or None, excerpt)
    """
    if not symbol:
        return (None, None, "No symbol => skip")

    url = f"https://lunarcrush.com/api2?symbol={symbol}&data=market"
    headers = {"Authorization": f"Bearer {LUNAR_API_KEY}"}
    logging.info(f"[LUNAR] GET {url} (symbol={symbol})")

    try:
        r = requests.get(url, headers=headers)
        sc = r.status_code
        excerpt = r.text[:300].replace("\n"," ")
        logging.info(f"[LUNAR] status_code={sc}, excerpt={excerpt}")
        if sc != 200:
            logging.warning(f"[LUNAR] HTTP {sc} => {r.text}")
            return (sc, None, excerpt)

        j = r.json()
        # structure: { "data": [ { "symbol":..., "social_score": ...}, ... ] }
        if "data" not in j or not j["data"]:
            return (sc, None, excerpt)

        # on prend le premier
        dd = j["data"][0]
        social_score = dd.get("social_score", None)
        return (sc, social_score, excerpt)

    except Exception as e:
        logging.error(f"[LUNAR ERROR] {e}")
        return (None, None, f"Exception => {e}")

#####################################
# MAIN
#####################################
if __name__ == "__main__":
    logging.info("[TEST] Checking Nansen & LunarCrush for SOLVEX...")

    # 1) Nansen
    sc_n, h_n, exc_n = test_nansen_holders(SOLVEX["chain"], SOLVEX["contract"])
    logging.info(f"[RESULT NANSEN] status_code={sc_n}, holders={h_n}, excerpt='{exc_n}'")

    # 2) LunarCrush
    sc_l, score_l, exc_l = test_lunar_sentiment(SOLVEX["lunar_symbol"])
    logging.info(f"[RESULT LUNAR] status_code={sc_l}, social_score={score_l}, excerpt='{exc_l}'")

    # Impression console + log
    print("==== NANSEN RESULT ====")
    print(f"Status code  : {sc_n}")
    print(f"Holders val  : {h_n}")
    print(f"Excerpt resp : {exc_n}\n")

    print("==== LUNARCRUSH RESULT ====")
    print(f"Status code   : {sc_l}")
    print(f"Social Score  : {score_l}")
    print(f"Excerpt resp  : {exc_l}\n")

    logging.info("=== END check_solvex_test ===")
    sys.exit(0)
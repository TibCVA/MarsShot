#!/usr/bin/env python3
# coding: utf-8

"""
Script de test pour 3 tokens: SOLVEX, ETH, LINK
Uniquement via LunarCrush.
On ajoute un fallback IP + Host header si la résolution DNS échoue.

Log file => check_solvex_test.log
"""

import requests
import logging
import time
import sys
import os
import socket
from urllib3.exceptions import NewConnectionError
from requests.exceptions import ConnectionError

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
# 5) Fonction de requête standard
#####################################
def do_lunarcrush_request(symbol):
    """
    Requête standard sur l'endpoint https://api.lunarcrush.com/v4/assets
    params: symbol=SYM, data=market
    Retourne (status_code, json, excerpt) ou (None, None, str) en cas d'erreur
    """
    url = "https://api.lunarcrush.com/v4/assets"
    headers = {
        "Authorization": f"Bearer {LUNAR_API_KEY}"
    }
    params = {
        "symbol": symbol,
        "data": "market"
    }

    logging.info(f"[LUNAR] GET {url} + symbol={symbol}, data=market")

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        sc = r.status_code
        excerpt = r.text[:300].replace("\n", " ")
        logging.info(f"[LUNAR] status_code={sc}, excerpt={excerpt[:100]}")

        if sc != 200:
            return (sc, None, excerpt)
        return (sc, r.json(), excerpt)

    except Exception as e:
        logging.error(f"[LUNAR] Exception => {e}")
        return (None, None, str(e))

#####################################
# 6) Fonction fallback si DNS échoue
#####################################
def do_lunarcrush_fallback(symbol):
    """
    En cas de NameResolutionError ou DNS fail, on tente la requête
    via IP direct + Host header. On disable SSL verify (mismatch).
    """
    # IP "api.lunarcrush.com"
    # NOTE: L'IP peut changer => c'est un hack de secours.
    fallback_ip = None
    try:
        fallback_ip = socket.gethostbyname("api.lunarcrush.com")
    except Exception as ee:
        # si on ne peut même pas résoudre via python => on force une IP statique (peu fiable)
        # Cf. "dig api.lunarcrush.com" => ex: 104.22.17.167 (ex. Cloudflare)
        fallback_ip = "104.22.17.167"  # Valeur indicative

    fallback_url = f"https://{fallback_ip}/v4/assets"
    headers = {
        "Authorization": f"Bearer {LUNAR_API_KEY}",
        "Host": "api.lunarcrush.com"
    }
    params = {
        "symbol": symbol,
        "data": "market"
    }

    logging.info(f"[LUNAR-FALLBACK] GET {fallback_url} (Host=api.lunarcrush.com), symbol={symbol}")

    try:
        r = requests.get(
            fallback_url,
            headers=headers,
            params=params,
            timeout=10,
            verify=False  # SSL mismatch => on skip la vérif
        )
        sc = r.status_code
        excerpt = r.text[:300].replace("\n", " ")
        logging.info(f"[LUNAR-FALLBACK] status_code={sc}, excerpt={excerpt[:100]}")

        if sc != 200:
            return (sc, None, excerpt)
        return (sc, r.json(), excerpt)

    except Exception as e:
        logging.error(f"[LUNAR-FALLBACK] Exception => {e}")
        return (None, None, str(e))

#####################################
# 7) Récupération du sentiment
#####################################
def get_lunar_sentiment(symbol):
    """
    Tente do_lunarcrush_request.
    Si NameResolutionError => do_lunarcrush_fallback.
    => Retourne un score [0..1], ou 0.5 si tout échoue.
    """
    sc, jdata, exc = do_lunarcrush_request(symbol)
    # si sc is None => c'est possiblement un DNS fail, on check l'exception
    if sc is None and ("NameResolutionError" in exc or "Failed to resolve" in exc):
        # => fallback
        logging.warning("[LUNAR] DNS fail => fallback IP approach")
        sc2, jdata2, exc2 = do_lunarcrush_fallback(symbol)
        if (sc2 == 200) and jdata2:
            return parse_sentiment(jdata2)
        else:
            return 0.5
    # sinon si sc=200 => parse
    if (sc == 200) and jdata:
        return parse_sentiment(jdata)
    # sinon => 0.5
    return 0.5

def parse_sentiment(jsondata):
    """
    Extrait social_score => normalisé sur [0..1].
    """
    arr = jsondata.get("data", [])
    if not arr:
        return 0.5
    first = arr[0]
    sc_val = first.get("social_score", 50)
    maxi = max(sc_val, 100)
    val = sc_val / maxi
    if val > 1:
        val = 1
    return val

#####################################
# 8) main
#####################################
def main():
    logging.info("=== START check_solvex_test ===")

    for t in TOKENS:
        name = t["name"]
        sym = t["symbol"]
        logging.info(f"--- TOKEN {name} ({sym}) ---")
        senti = get_lunar_sentiment(sym)
        print(f"{name} [{sym}] => sentiment={senti:.3f}")
        time.sleep(2)

    logging.info("=== END check_solvex_test ===")


if __name__ == "__main__":
    main()
    sys.exit(0)
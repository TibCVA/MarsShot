#!/usr/bin/env python3
# coding: utf-8

"""
Test LunarCrush v4 - base URL https://lunarcrush.com/api4
Nous allons juste appeler l'endpoint /public/coins/list/v2
pour vérifier l'accessibilité, puis on affichera quelques stats
pour 3 coins : SOLVEX, ETH, LINK si disponibles dans la liste.
Log => check_solvex_test.log
"""

import requests
import logging
import time
import sys

#####################################
# Clé API LunarCrush
#####################################
LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"

#####################################
# Fichier log
#####################################
LOG_FILE = "check_solvex_test.log"

#####################################
# Création fichier log
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
# La liste symboles qu'on veut inspecter
#####################################
TARGETS = ["SOLVEX", "ETH", "LINK"]

#####################################
# POINT D'ENTREE
#####################################
def main():
    logging.info("=== START check_solvex_test ===")

    # 1) On appelle l'endpoint "coins/list/v2" pour récupérer la liste
    #    Paramètres possibles : limit=..., page=..., etc.
    #    Documentation : https://lunarcrush.com/api4/public/coins/list/v2
    url = "https://lunarcrush.com/api4/public/coins/list/v2"
    params = {
        "key": LUNAR_API_KEY,
        "limit": 500  # on récupère jusqu'à 500 coins
    }

    logging.info(f"[LUNAR] GET {url}, params={params}")
    try:
        r = requests.get(url, params=params, timeout=10)
        sc = r.status_code
        logging.info(f"[LUNAR] status_code={sc}")
        if sc != 200:
            excerpt = r.text[:300].replace("\n"," ")
            logging.warning(f"[LUNAR] HTTP {sc}, excerpt={excerpt}")
            print(f"Erreur HTTP {sc}, voir log.")
            return

        # On parse le JSON
        data = r.json()
        # data devrait contenir "data": [ { ... coin info ... } , ... ]

        if "data" not in data:
            logging.warning("[LUNAR] 'data' not in JSON => abort")
            print("Réponse JSON inattendue => voir log.")
            return

        big_list = data["data"]
        logging.info(f"[LUNAR] nb_coins={len(big_list)}")

        # On va faire un dict par symbol, ex: d["ETH"] => objet
        found_map = {}
        for coin_obj in big_list:
            sym = coin_obj.get("symbol","").upper()
            found_map[sym] = coin_obj

        # 2) On affiche les infos pour nos TARGETS
        for sym in TARGETS:
            logging.info(f"--- Checking {sym}")
            cdata = found_map.get(sym)
            if not cdata:
                print(f"{sym} introuvable dans la liste.")
                logging.info(f"{sym} => introuvable.")
                continue

            # On récupère par ex price, market_cap, alt_rank, etc.
            price = cdata.get("price","?")
            mc = cdata.get("market_cap","?")
            gal_score = cdata.get("galaxy_score","?")
            print(f"{sym} => price={price}, market_cap={mc}, galaxy_score={gal_score}")
            logging.info(f"{sym} => price={price}, mc={mc}, gal_score={gal_score}")

    except Exception as e:
        logging.error(f"[LUNAR] Exception => {e}")
        print(f"Erreur => {e}")
    finally:
        logging.info("=== END check_solvex_test ===")

if __name__=="__main__":
    main()
    sys.exit(0)
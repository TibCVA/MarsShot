#!/usr/bin/env python3
# coding: utf-8

import requests
import logging
import csv

"""
check_tokens_validity.py
------------------------
Ce script interroge l'endpoint CoinMarketCap /v1/cryptocurrency/map
pour vérifier la validité (existence / is_active / etc.) de chaque token 
sur la base de son symbol.

Il génère :
- un fichier de logs: check_tokens_validity.log
- un fichier CSV: result_tokens.csv

UTILISATION:
    1) Placez ce fichier dans votre repo GitHub.
    2) Ajoutez un workflow (.yml) pour exécuter 'python check_tokens_validity.py'
       et consulter les logs en sortie.

Notes:
    - Ajoutez vos 102 tokens + BTC, ETH, LINK ci-dessous.
    - Les retours 'first_historical_data' / 'last_historical_data' 
      vous indiqueront la plage d'historique disponible.
    - S'il n'y a pas de correspondance, 'found' = "No".
    - S'il y a une erreur HTTP 429 ou 400, on l'indique.
"""

# ====================================================
# 1) VOS INFORMATIONS / CONFIG
# ====================================================

CMC_API_KEY = "0a602f8f-2a68-4992-89f2-7e7416a4d8e8"  # <-- Votre clé CoinMarketCap
LOG_FILE = "check_tokens_validity.log"
CSV_FILE = "result_tokens.csv"

# ====================================================
# 2) LISTE DE TOKENS
#    Ajoutez ici vos 102 tokens exacts (symbol), + BTC, ETH, LINK
# ====================================================
TOKENS = [
    # Exemples => vous compléterez le reste
    "SOLVEX",
    "FAI",
    "PATRIOT",
    # ...
    # Ajoutez ici tous vos symboles (total 102).
    # ...
    "BTC",   # certain
    "ETH",   # certain
    "LINK",  # certain, UCID=1975
]


# ====================================================
# 3) INITIALISATION DU LOGGING
# ====================================================
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


def main():
    logging.info("=== START check_tokens_validity ===")

    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/map"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accepts": "application/json"
    }

    # On stockera les résultats dans une liste de dict
    results = []

    for symbol in TOKENS:
        # On appelle l'endpoint /map avec ?symbol=<symbol>
        params = {
            "symbol": symbol,
            "listing_status": "active,untracked"  
            # "untracked" inclut les projets qui n'ont pas (encore) de marché
        }

        logging.info(f"[CHECK] symbol={symbol}, GET {url} params={params}")
        try:
            r = requests.get(url, headers=headers, params=params)
            sc = r.status_code
            logging.info(f"[CHECK] symbol={symbol} => status_code={sc}")

            if sc != 200:
                # On log un warning et on range un enregistrement minimal
                logging.warning(f"{symbol}: HTTP {sc}")
                results.append({
                    "symbol": symbol,
                    "found": f"No (HTTP {sc})",
                    "id": None,
                    "is_active": None,
                    "first_historical_data": None,
                    "last_historical_data": None
                })
                continue

            # On parse la réponse JSON
            j = r.json()
            data = j.get("data", [])

            if not data:
                # => token inconnu
                logging.info(f"{symbol}: Pas de correspondance (data=vide).")
                results.append({
                    "symbol": symbol,
                    "found": "No",
                    "id": None,
                    "is_active": None,
                    "first_historical_data": None,
                    "last_historical_data": None
                })
                continue

            # data est un tableau => on prend la première correspondance
            first_item = data[0]
            coin_id = first_item.get("id")
            is_active = first_item.get("is_active")
            fhd = first_item.get("first_historical_data")
            lhd = first_item.get("last_historical_data")

            logging.info(f"{symbol}: found => id={coin_id}, is_active={is_active},"
                         f" fhd={fhd}, lhd={lhd}")

            results.append({
                "symbol": symbol,
                "found": "Yes",
                "id": coin_id,
                "is_active": is_active,
                "first_historical_data": fhd,
                "last_historical_data": lhd
            })

        except Exception as e:
            logging.error(f"[ERROR] symbol={symbol} => {e}")
            results.append({
                "symbol": symbol,
                "found": f"Error: {e}",
                "id": None,
                "is_active": None,
                "first_historical_data": None,
                "last_historical_data": None
            })

    # ====================================================
    # 4) Génération d'un CSV
    # ====================================================
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "symbol",
                "found",
                "id",
                "is_active",
                "first_historical_data",
                "last_historical_data"
            ]
        )
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    logging.info(f"CSV generated: {CSV_FILE} with {len(results)} tokens.")
    logging.info("=== END check_tokens_validity ===")


if __name__ == "__main__":
    main()
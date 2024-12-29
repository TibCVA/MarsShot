#!/usr/bin/env python3
# coding: utf-8

import requests
import logging
import os
import csv

"""
Ce script interroge l'endpoint CoinMarketCap /v1/cryptocurrency/map
pour chaque token symbol, afin de vérifier s'il est reconnu, et récupère
'first_historical_data', 'last_historical_data', 'is_active', etc.

Usage:
  python check_tokens_validity.py
  --> Génère un fichier check_tokens_validity.log + un CSV result_tokens.csv
"""

CMC_API_KEY = "VOTRE_CLE_CMC_ICI"  # Mettez ici votre clé (ex: "0a602f8f-xxx")

# Liste de tokens : 102 de votre choix + BTC, ETH, LINK
# (Exemple minimal, à adapter: ci-dessous "SOLVEX", "FAI" etc.)
TOKENS = [
    "SOLVEX", "FAI", "PATRIOT",  # 3 "exotiques"
    # ... (ajoutez vos 99 autres symboles) ...
    "BTC",   # un token certain
    "ETH",   # un token certain
    "LINK"   # un token certain
]

LOG_FILE = "check_tokens_validity.log"
CSV_FILE = "result_tokens.csv"

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

    # On va stocker les résultats (liste de dict)
    results = []

    for symbol in TOKENS:
        # On appelle /map?symbol=...
        params = {
            "symbol": symbol,               # On recherche la correspondance par symbole
            "listing_status": "active,untracked"  # pour être large
        }

        logging.info(f"[CHECK] symbol={symbol}, url={url}, params={params}")
        try:
            r = requests.get(url, headers=headers, params=params)
            status_code = r.status_code
            logging.info(f"[CHECK] symbol={symbol} => status_code={status_code}")

            if status_code != 200:
                logging.warning(f"{symbol}: HTTP {status_code}")
                # On met un enregistrement "KO" direct
                results.append({
                    "symbol": symbol,
                    "found": "No (HTTP error)",
                    "id": None,
                    "is_active": None,
                    "first_historical_data": None,
                    "last_historical_data": None
                })
                continue

            j = r.json()
            data = j.get("data", [])
            if not data:
                # => pas trouvé
                logging.info(f"{symbol}: data vide => token introuvable ou inactif")
                results.append({
                    "symbol": symbol,
                    "found": "No",
                    "id": None,
                    "is_active": None,
                    "first_historical_data": None,
                    "last_historical_data": None
                })
                continue

            # data est une liste d'objets. ex:
            # [
            #   {
            #     "id": 28301,
            #     "name": "SolvexNetwork",
            #     "symbol": "SOLVEX",
            #     "slug": "solvex-network",
            #     "is_active": 1,
            #     "first_historical_data": "2023-01-02T00:00:00Z",
            #     "last_historical_data": "2023-12-29T00:00:00Z",
            #     ...
            #   }
            # ]
            # Il peut y avoir plusieurs correspondances. On va prendre la 1re:
            first_match = data[0]
            coin_id = first_match.get("id", None)
            is_active = first_match.get("is_active", None)
            fhd = first_match.get("first_historical_data", None)
            lhd = first_match.get("last_historical_data", None)

            # On log
            logging.info(f"{symbol}: found ID={coin_id}, is_active={is_active}, "
                         f"fhd={fhd}, lhd={lhd}")

            results.append({
                "symbol": symbol,
                "found": "Yes",
                "id": coin_id,
                "is_active": is_active,
                "first_historical_data": fhd,
                "last_historical_data": lhd
            })

        except Exception as e:
            logging.error(f"[ERROR] {symbol} => {e}")
            results.append({
                "symbol": symbol,
                "found": f"Error: {e}",
                "id": None,
                "is_active": None,
                "first_historical_data": None,
                "last_historical_data": None
            })

    # Ecriture CSV
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["symbol","found","id","is_active","first_historical_data","last_historical_data"]
        )
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    logging.info(f"==> CSV generated: {CSV_FILE} with {len(results)} entries")
    logging.info("=== END check_tokens_validity ===")

if __name__ == "__main__":
    main()
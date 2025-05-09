#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
auto_select_tokens.py
---------------------
Sélectionne automatiquement les 60 meilleurs tokens "moonshot"
basés sur leur performance intraday et momentum,
**uniquement** pour les paires Spot en USDC tradables sur Binance.
"""

import os
import yaml
import logging
import time

from binance.client import Client
from binance.exceptions import BinanceAPIException

def fetch_USDC_spot_pairs(client):
    """
    Récupère toutes les paires SPOT en USDC sur Binance :
      - quoteAsset == 'USDC'
      - status == 'TRADING'
      - market SPOT (permissions inclut 'SPOT')
    Exclut les tokens à effet de levier et les stablecoins.
    Retourne la liste de symboles 'XXXUSDC'.
    """
    try:
        info = client.get_exchange_info()
    except BinanceAPIException as e:
        logging.error(f"[fetch_USDC_spot_pairs] Erreur get_exchange_info: {e}")
        return []

    usdc_pairs = []
    for s in info.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        if s.get("quoteAsset") != "USDC":
            continue
        # Vérifier que c'est bien du SPOT
        if "SPOT" not in s.get("permissions", []):
            continue

        base = s.get("baseAsset", "")
        # Exclure les tokens à effet de levier
        if any(tag in base for tag in ["UP", "DOWN", "BULL", "BEAR"]):
            continue
        # Exclure les stablecoins
        if base in {"USDC", "BUSD", "TUSD", "USDT"}:
            continue

        symbol = s.get("symbol", "")
        if symbol.endswith("USDC"):
            usdc_pairs.append(symbol)

    # On retire les doublons et on trie
    return sorted(set(usdc_pairs))


def get_24h_change(client, symbol):
    """
    Variation 24h en % (ex: '5.00' -> 0.05), ou 0.0 en cas d'erreur.
    """
    try:
        tick = client.get_ticker(symbol=symbol)
        return float(tick.get("priceChangePercent", 0)) / 100.0
    except Exception as e:
        logging.warning(f"[get_24h_change] {symbol} => {e}")
        return 0.0


def get_kline_change(client, symbol, days=7):
    """
    Variation sur 'days' derniers jours (ex: +0.10 pour +10%),
    basée sur les clôtures journalières. 0.0 si insuffisance de données.
    """
    limit = days + 1
    try:
        klines = client.get_klines(
            symbol=symbol,
            interval=Client.KLINE_INTERVAL_1DAY,
            limit=limit
        )
        if len(klines) < limit:
            return 0.0
        last_close = float(klines[-1][4])
        old_close  = float(klines[-limit][4])
        if old_close <= 0:
            return 0.0
        return (last_close - old_close) / old_close
    except Exception as e:
        logging.warning(f"[get_kline_change] {symbol}, days={days} => {e}")
        return 0.0


def compute_token_score(p24, p7, p30):
    """
    Scoring "moonshot" :
      - 80% sur la perf 7 jours (momentum)
      -  0% sur la perf 30 jours
      - 20% sur la perf 24h (volatilité court terme)
    """
    return 0.8 * p7 + 0.0 * p30 + 0.2 * p24


def select_top_tokens(client, top_n=60):
    """
    Récupère les paires USDC spot, calcule p24/p7/p30, score et
    retourne les top_n baseAssets (sans le suffixe 'USDC').
    """
    usdc_pairs = fetch_USDC_spot_pairs(client)
    logging.info(f"[AUTO] {len(usdc_pairs)} paires USDC spot détectées")

    scored = []
    for idx, sym in enumerate(usdc_pairs, start=1):
        # Pause pour respecter les rate limits
        if idx % 20 == 0:
            time.sleep(1)

        p24  = get_24h_change(client, sym)
        p7   = get_kline_change(client, sym, days=7)
        p30  = get_kline_change(client, sym, days=30)
        score= compute_token_score(p24, p7, p30)
        scored.append((sym, score))

    # Tri descendant par score
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:top_n]

    # On enlève le suffixe 'USDC'
    return [sym[:-4] for sym, _ in top]


def update_config_tokens_daily(new_tokens):
    """
    Met à jour la clé 'extended_tokens_daily' de config.yaml.
    """
    cfg_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.isfile(cfg_path):
        logging.error(f"[update_config] config.yaml introuvable ({cfg_path})")
        return

    with open(cfg_path, "r") as f:
        cfg = yaml.safe_load(f)

    cfg["extended_tokens_daily"] = new_tokens
    with open(cfg_path, "w") as f:
        yaml.dump(cfg, f, sort_keys=False)

    logging.info(f"[update_config] Mis à jour {len(new_tokens)} tokens")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    cfg_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.isfile(cfg_path):
        logging.error(f"Config non trouvée : {cfg_path}")
        return

    with open(cfg_path, "r") as f:
        cfg = yaml.safe_load(f)

    client = Client(
        cfg["binance_api"]["api_key"],
        cfg["binance_api"]["api_secret"]
    )

    best60 = select_top_tokens(client, top_n=60)
    logging.info(f"[AUTO] Sélection des 60 meilleurs tokens : {best60}")

    update_config_tokens_daily(best60)
    print("[OK] config.yaml mise à jour avec extended_tokens_daily")


if __name__ == "__main__":
    main()

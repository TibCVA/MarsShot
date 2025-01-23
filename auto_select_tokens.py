#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
auto_select_tokens.py
---------------------
Sélectionne automatiquement les 60 meilleurs tokens "moonshot" basés sur
leur performance 24h, 7j et 30j, avec des pondérations plus fortes sur
le 7 jours et le 30 jours, pour un effet momentum + tendance.
"""

import os
import yaml
import logging
import time
from datetime import datetime, timedelta

from binance.client import Client

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_YML = os.path.join(BASE_DIR, "config.yaml")
LOG_FILE   = "auto_select_tokens.log"

def fetch_usdt_spot_pairs(client):
    """
    Récupère toutes les paires Spot en USDT sur Binance,
    en filtrant les tokens indésirables (UP,DOWN,BULL,BEAR, stablecoins).
    """
    info = client.get_exchange_info()
    all_symbols = info.get("symbols", [])
    pairs = []
    for s in all_symbols:
        if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
            base = s.get("baseAsset","")
            # Exclusion: LEVERAGED tokens
            if any(x in base for x in ["UP","DOWN","BULL","BEAR"]):
                continue
            # Exclusion: stablecoins
            if base in ["USDC","BUSD","TUSD","USDT"]:
                continue
            pairs.append(s["symbol"])
    return pairs

def get_24h_change(client, symbol):
    """
    Retourne la variation sur 24h en % (ex: +5% => 0.05), ou 0.0 si problème.
    """
    try:
        tick = client.get_ticker(symbol=symbol)
        pc_str = tick.get("priceChangePercent","0")
        return float(pc_str)/100.0
    except:
        return 0.0

def get_kline_change(client, symbol, days=7):
    """
    Retourne la variation sur 'days' jours (ex: +10% => 0.10)
    en se basant sur des klines journalières. 0.0 si problème ou data insuffisante.
    """
    limit = days+5
    try:
        klines = client.get_klines(
            symbol=symbol,
            interval=Client.KLINE_INTERVAL_1DAY,
            limit=limit
        )
        if len(klines) <= days:
            return 0.0
        last_close = float(klines[-1][4])
        old_close  = float(klines[-days-1][4])
        if old_close <= 0:
            return 0.0
        return (last_close - old_close)/old_close
    except:
        return 0.0

def compute_token_score(p24, p7, p30):
    """
    Nouveau scoring "moonshot" :
      - 50% sur la perf 7 jours (momentum hebdo)
      - 30% sur la perf 30 jours (tendance plus durable)
      - 20% sur la perf 24h (volatilité court terme)
    """
    return 0.5*p7 + 0.3*p30 + 0.2*p24

def select_top_tokens(client, top_n=60):
    """
    Récupère la liste de toutes les paires USDT, calcule la perf 24h, 7j, 30j,
    et applique compute_token_score pour ranker. On renvoie les top_n.
    """
    all_pairs = fetch_usdt_spot_pairs(client)
    logging.info(f"[AUTO] fetch_usdt_spot_pairs => {len(all_pairs)} pairs")

    results = []
    count=0
    for sym in all_pairs:
        count += 1
        if (count % 20) == 0:
            time.sleep(1)

        p24  = get_24h_change(client, sym)
        p7   = get_kline_change(client, sym, 7)
        p30  = get_kline_change(client, sym, 30)
        score= compute_token_score(p24, p7, p30)
        results.append((sym, score))

    # On trie du plus grand score au plus faible
    results.sort(key=lambda x: x[1], reverse=True)
    top = results[:top_n]

    # On renvoie la baseAsset (ex. BNB si BNBUSDT)
    bases = []
    for sym, sc in top:
        if sym.endswith("USDT"):
            base = sym.replace("USDT","")
            bases.append(base)
    return bases

def update_config_tokens_daily(new_tokens):
    """
    Met à jour la clé 'tokens_daily' dans config.yaml en y mettant new_tokens.
    """
    if not os.path.exists(CONFIG_YML):
        logging.warning(f"[update_config_tokens_daily] {CONFIG_YML} introuvable")
        return
    with open(CONFIG_YML,"r") as f:
        cfg = yaml.safe_load(f)
    cfg["tokens_daily"] = new_tokens

    with open(CONFIG_YML,"w") as f:
        yaml.dump(cfg, f, sort_keys=False)
    logging.info(f"[update_config_tokens_daily] => {len(new_tokens)} tokens => {new_tokens}")

def main():
    logging.basicConfig(
        filename=LOG_FILE,
        filemode="a",
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("=== START auto_select_tokens ===")

    if not os.path.exists(CONFIG_YML):
        logging.error(f"[ERROR] {CONFIG_YML} introuvable")
        print(f"[ERROR] {CONFIG_YML} introuvable")
        return

    with open(CONFIG_YML,"r") as f:
        config = yaml.safe_load(f)
    key = config["binance_api"]["api_key"]
    sec = config["binance_api"]["api_secret"]
    if not key or not sec:
        logging.error("[ERROR] Clé/secret binance manquante.")
        print("[ERROR] Clé/secret binance manquante.")
        return

    client = Client(key, sec)

    # On veut désormais top 60 => fix l'appel
    best60 = select_top_tokens(client, top_n=60)
    logging.info(f"[AUTO] best60 => {best60}")

    update_config_tokens_daily(best60)

    logging.info("=== DONE auto_select_tokens ===")
    print("[OK] auto_select_tokens => config.yaml updated")


if __name__=="__main__":
    main()
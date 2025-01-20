#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import yaml
import logging
import time
from datetime import datetime, timedelta

# Binance
from binance.client import Client

CONFIG_FILE = "config.yaml"
LOG_FILE    = "auto_select_tokens.log"

# --------------------------------------------------------------------
# FONCTION 1 : Récupère toutes les paires USDT en mode SPOT/trading
# --------------------------------------------------------------------
def fetch_usdt_spot_pairs(binance_client):
    """
    Récupère toutes les paires spot sur binance se terminant par USDT,
    status=TRADING, non margin/ETF, etc.
    Retourne une liste de symbol ex: ["BTCUSDT", "ETHUSDT", ...].
    """
    exchange_info = binance_client.get_exchange_info()
    all_symbols = exchange_info.get("symbols", [])
    pairs = []
    for s in all_symbols:
        # Filtrage : status=TRADING, quoteAsset=USDT
        if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
            # Évite UP/DOWN, etc.
            base = s.get("baseAsset","")
            if "UP" in base or "DOWN" in base or "BULL" in base or "BEAR" in base:
                continue
            # Évite stables BUSD, TUSD => si vous voulez
            if base in ["USDC","BUSD","TUSD","USDT"]:
                continue
            # OK
            pairs.append(s["symbol"])
    return pairs

# --------------------------------------------------------------------
# FONCTION 2 : Variation sur 24h
# --------------------------------------------------------------------
def get_24h_change(binance_client, symbol):
    """
    Variation 24h (ex: +0.12 = +12%) via l'endpoint 24hr ticker.
    Si aucune donnée, on retourne 0.0
    """
    try:
        tick = binance_client.get_ticker(symbol=symbol)
        pc_str = tick.get("priceChangePercent","0")
        pc = float(pc_str)/100.0  # ex "12.45" => 0.1245
        return pc
    except Exception as e:
        logging.warning(f"[24h ERR] {symbol} => {e}")
        return 0.0

# --------------------------------------------------------------------
# FONCTION 3 : Variation sur X jours (7 ou 30) via Klines 1d
# --------------------------------------------------------------------
def get_kline_change(binance_client, symbol, days=7):
    """
    Variation sur `days` jours : close_{today} / close_{today - days} - 1
    On récupère ~days+5 klines daily. 
    """
    limit = days + 5
    try:
        klines = binance_client.get_klines(
            symbol=symbol,
            interval=Client.KLINE_INTERVAL_1DAY,
            limit=limit
        )
        if len(klines) < (days+1):
            return 0.0
        last_close = float(klines[-1][4])   # close
        old_close  = float(klines[-days-1][4])
        if old_close<=0:
            return 0.0
        change = (last_close - old_close)/old_close
        return change
    except Exception as e:
        logging.warning(f"[kline ERR] {symbol}, days={days} => {e}")
        return 0.0

# --------------------------------------------------------------------
# FONCTION 4 : Score pondéré type "moonshot"
# --------------------------------------------------------------------
def compute_token_score(perf_24h, perf_7d, perf_30d):
    """
    Formule pondérée, favorisant le 30j, 
    plus agressif => +0.6 * 30j + 0.25 * 7j + 0.15 * 24h
    => on cherche des potentiels "moonshots" sur la durée.
    """
    return 0.6*perf_30d + 0.25*perf_7d + 0.15*perf_24h

# --------------------------------------------------------------------
# FONCTION 5 : select_top_tokens
# --------------------------------------------------------------------
def select_top_tokens(binance_client, top_n=30):
    """
    1) Récupère liste usdt_spot pairs
    2) calcule perf 24h, 7d, 30d
    3) calcule score => tri => top_n
    4) renvoie liste des *base assets* (ex: BTC, ETH)
    """
    all_pairs = fetch_usdt_spot_pairs(binance_client)
    logging.info(f"[AUTO] fetch_usdt_spot_pairs => {len(all_pairs)} pairs")

    results = []
    count=0

    for sym in all_pairs:
        count+=1
        # latence => pause chaque 20 paires
        if (count%20)==0:
            time.sleep(1)

        p24  = get_24h_change(binance_client, sym)
        p7   = get_kline_change(binance_client, sym, days=7)
        p30  = get_kline_change(binance_client, sym, days=30)
        score= compute_token_score(p24, p7, p30)
        results.append((sym, p24, p7, p30, score))
    
    # on trie => descending sur score
    results.sort(key=lambda x: x[4], reverse=True)

    top = results[:top_n]
    # On retire la base => ex. "BTC" si "BTCUSDT"
    selected_bases = []
    for (s, p24, p7, p30, sc) in top:
        if s.endswith("USDT"):
            base = s.replace("USDT","")
            selected_bases.append(base)
    return selected_bases

# --------------------------------------------------------------------
# FONCTION 6 : update_config_tokens_daily
# --------------------------------------------------------------------
def update_config_tokens_daily(new_tokens):
    """
    Ouvre config.yaml, 
    modifie tokens_daily => new_tokens, 
    réécrit config.yaml
    """
    if not os.path.exists(CONFIG_FILE):
        logging.warning(f"[update_config_tokens_daily] {CONFIG_FILE} introuvable.")
        return
    
    with open(CONFIG_FILE, "r") as f:
        config = yaml.safe_load(f)
    
    config["tokens_daily"] = new_tokens
    
    with open(CONFIG_FILE, "w") as f:
        # on évite sort_keys pour garder la structure
        yaml.dump(config, f, sort_keys=False)
    logging.info(f"[update_config_tokens_daily] => {len(new_tokens)} tokens => {new_tokens}")

# --------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------
def main():
    logging.basicConfig(
        filename=LOG_FILE,
        filemode='a',
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("=== START auto_select_tokens ===")

    if not os.path.exists(CONFIG_FILE):
        msg = f"[ERROR] {CONFIG_FILE} introuvable."
        logging.error(msg)
        print(msg)
        return

    with open(CONFIG_FILE,"r") as f:
        cfg = yaml.safe_load(f)

    # Clés API Binance
    key = cfg.get("binance_api",{}).get("api_key","")
    sec = cfg.get("binance_api",{}).get("api_secret","")
    if not key or not sec:
        logging.error("[ERROR] Clé/secret binance manquante.")
        print("[ERROR] Clé/secret binance manquante.")
        return

    # init client
    client = Client(key, sec)
    # exemple : pas besoin de param microseconds => defaults millisecond

    # 1) Sélectionne top30
    best30 = select_top_tokens(client, top_n=30)
    logging.info(f"[AUTO] top30 => {best30}")

    # 2) update config
    update_config_tokens_daily(best30)

    logging.info("=== DONE auto_select_tokens ===")
    print("[OK] auto_select_tokens => config.yaml updated with 30 tokens")

if __name__=="__main__":
    main()

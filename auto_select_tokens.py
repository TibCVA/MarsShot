#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import yaml
import logging
import time
from datetime import datetime, timedelta

from binance.client import Client

# Construction du chemin absolu vers config.yaml
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(CURRENT_DIR, "config.yaml")
LOG_FILE    = "auto_select_tokens.log"

def fetch_usdt_spot_pairs(binance_client):
    exchange_info = binance_client.get_exchange_info()
    all_symbols = exchange_info.get("symbols", [])
    pairs = []
    for s in all_symbols:
        if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
            base = s.get("baseAsset", "")
            # Exclusions => tokens à effet de levier
            if any(x in base for x in ["UP","DOWN","BULL","BEAR"]):
                continue
            # Exclusion de stablecoins
            if base in ["USDC","BUSD","TUSD","USDT"]:
                continue
            pairs.append(s["symbol"])
    return pairs

def get_24h_change(binance_client, symbol):
    try:
        tick = binance_client.get_ticker(symbol=symbol)
        pc_str = tick.get("priceChangePercent", "0")
        pc = float(pc_str)/100.0
        return pc
    except Exception as e:
        logging.warning(f"[24h ERR] {symbol} => {e}")
        return 0.0

def get_kline_change(binance_client, symbol, days=7):
    limit = days + 5
    try:
        klines = binance_client.get_klines(
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
    except Exception as e:
        logging.warning(f"[kline ERR] {symbol}, days={days} => {e}")
        return 0.0

def compute_token_score(perf_24h, perf_7d, perf_30d):
    return 0.6*perf_30d + 0.25*perf_7d + 0.15*perf_24h

def select_top_tokens(binance_client, top_n=30):
    all_pairs = fetch_usdt_spot_pairs(binance_client)
    logging.info(f"[AUTO] fetch_usdt_spot_pairs => {len(all_pairs)} pairs")

    results = []
    count=0
    for sym in all_pairs:
        count += 1
        if (count % 20) == 0:
            time.sleep(1)
        p24 = get_24h_change(binance_client, sym)
        p7  = get_kline_change(binance_client, sym, days=7)
        p30 = get_kline_change(binance_client, sym, days=30)
        score = compute_token_score(p24, p7, p30)
        results.append((sym, p24, p7, p30, score))

    results.sort(key=lambda x: x[4], reverse=True)
    top = results[:top_n]

    selected_bases = []
    for (s,p24,p7,p30,sc) in top:
        if s.endswith("USDT"):
            base = s.replace("USDT","")
            selected_bases.append(base)
    return selected_bases

def update_config_tokens_daily(new_tokens):
    if not os.path.exists(CONFIG_FILE):
        logging.warning(f"[update_config_tokens_daily] {CONFIG_FILE} introuvable.")
        return
    with open(CONFIG_FILE, "r") as f:
        config = yaml.safe_load(f)

    config["tokens_daily"] = new_tokens

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, sort_keys=False)
    logging.info(f"[update_config_tokens_daily] => {len(new_tokens)} tokens => {new_tokens}")

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

    with open(CONFIG_FILE, "r") as f:
        cfg = yaml.safe_load(f)

    key = cfg.get("binance_api",{}).get("api_key","")
    sec = cfg.get("binance_api",{}).get("api_secret","")
    if not key or not sec:
        logging.error("[ERROR] Clé/secret binance manquante.")
        print("[ERROR] Clé/secret binance manquante.")
        return

    client = Client(key, sec)

    best30 = select_top_tokens(client, top_n=30)
    logging.info(f"[AUTO] top30 => {best30}")

    update_config_tokens_daily(best30)

    logging.info("=== DONE auto_select_tokens ===")
    print("[OK] auto_select_tokens => config.yaml updated with 30 tokens")


if __name__=="__main__":
    main()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import yaml
import logging
import time
from datetime import datetime, timedelta

from binance.client import Client

# On suppose que ce fichier est dans /app/auto_select_tokens.py
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_YML = os.path.join(BASE_DIR, "config.yaml")
LOG_FILE   = "auto_select_tokens.log"

def fetch_usdt_spot_pairs(client):
    info = client.get_exchange_info()
    all_symbols = info.get("symbols", [])
    pairs = []
    for s in all_symbols:
        if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
            base = s.get("baseAsset","")
            if any(x in base for x in ["UP","DOWN","BULL","BEAR"]):
                continue
            if base in ["USDC","BUSD","TUSD","USDT"]:
                continue
            pairs.append(s["symbol"])
    return pairs

def get_24h_change(client, symbol):
    try:
        tick = client.get_ticker(symbol=symbol)
        pc_str = tick.get("priceChangePercent","0")
        return float(pc_str)/100
    except:
        return 0.0

def get_kline_change(client, symbol, days=7):
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
    return 0.6*p30 + 0.25*p7 + 0.15*p24

def select_top_tokens(client, top_n=30):
    all_pairs = fetch_usdt_spot_pairs(client)
    logging.info(f"[AUTO] fetch_usdt_spot_pairs => {len(all_pairs)} pairs")

    results = []
    count=0
    for sym in all_pairs:
        count+=1
        if (count%20)==0:
            time.sleep(1)
        p24  = get_24h_change(client, sym)
        p7   = get_kline_change(client, sym, 7)
        p30  = get_kline_change(client, sym, 30)
        score= compute_token_score(p24, p7, p30)
        results.append((sym, score))

    results.sort(key=lambda x: x[1], reverse=True)
    top = results[:top_n]

    bases = []
    for sym, sc in top:
        if sym.endswith("USDT"):
            bases.append(sym.replace("USDT",""))
    return bases

def update_config_tokens_daily(new_tokens):
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
    best30 = select_top_tokens(client, top_n=30)
    logging.info(f"[AUTO] best30 => {best30}")

    update_config_tokens_daily(best30)

    logging.info("=== DONE auto_select_tokens ===")
    print("[OK] auto_select_tokens => config.yaml updated")


if __name__=="__main__":
    main()
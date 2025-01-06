#!/usr/bin/env python3
# coding: utf-8

"""
data_fetcher.py
---------------
Ce script conserve TOUTE la logique précédente, y compris :
 - Intraday => Binance (fetch_current_price_from_binance, fetch_prices_for_symbols)
 - Daily => LunarCrush
MAIS on ajoute une étape "inférence daily" qui produit daily_inference_data.csv, 
en reprenant la logique exact de build_csv.py pour la partie "daily" (1 an => RSI/MACD/ATR, merges BTC/ETH/SOL),
et on ne garde que la DERNIERE ligne par token, label=NaN, 
tout en gardant la structure identique à build_csv.

Le but : 
- Les 21 tokens sont lus dans config["tokens_daily"] => plus de liste en dur.
- On export daily_inference_data.csv => 21 lignes (1 par token), 
  colonnes EXACTEMENT = [
    "date","open","high","low","close","volume","market_cap",
    "galaxy_score","alt_rank","sentiment",
    "rsi","macd","atr",
    "label","symbol",
    "btc_daily_change","eth_daily_change","sol_daily_change"
  ]
"""

import requests
import logging
import time
import pandas as pd
import os
import yaml
from datetime import datetime
import numpy as np
from typing import Optional

from indicators import compute_rsi_macd_atr  # identique à build_csv
from binance.client import Client

########################################
# CHARGEMENT CONFIG
########################################

CONFIG_FILE = "config.yaml"
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

BINANCE_KEY = CONFIG["binance_api"]["api_key"]
BINANCE_SECRET = CONFIG["binance_api"]["api_secret"]
symbol_map = CONFIG["exchanges"]["binance"]["symbol_mapping"]

# => On récupère la liste de tokens
TOKENS_DAILY = CONFIG["tokens_daily"]  # 21 tokens

LOG_FILE = "data_fetcher.log"
OUTPUT_INFERENCE_CSV = "daily_inference_data.csv"

# On garde la partie intraday => Binance
binance_client = Client(BINANCE_KEY, BINANCE_SECRET)

#########################
# Intraday => Binance
#########################
def fetch_current_price_from_binance(symbol: str):
    """
    Retourne le dernier prix pour symbol (ex: "FET"),
    en utilisant le mapping config => binance_symbol + "USDT".
    """
    if symbol not in symbol_map:
        logging.error(f"[BINANCE PRICE] {symbol} absent de symbol_mapping => skip")
        return None

    bsymbol = symbol_map[symbol]  # ex: "FET"
    pair = f"{bsymbol}USDT"
    try:
        tick = binance_client.get_symbol_ticker(symbol=pair)
        return float(tick["price"])
    except Exception as e:
        logging.error(f"[BINANCE PRICE] Error {pair} => {e}")
        return None

def fetch_prices_for_symbols(symbols):
    """
    Récupère un dict { 'FET': 0.12, 'AGIX': 0.98, ... } via binance
    """
    out = {}
    for sym in symbols:
        px = fetch_current_price_from_binance(sym)
        if px is not None:
            out[sym] = px
        time.sleep(0.1)  # petite pause pour éviter un spam
    return out

#########################
# Daily => LunarCrush
#########################

LUNAR_API_KEY = CONFIG["lunarcrush"]["api_key"]
INTERVAL = "1y"  # On veut 1 an daily => comme build_csv
SLEEP_BETWEEN_TOKENS = 6

def fetch_lc_raw(symbol: str, days_interval="1y") -> Optional[pd.DataFrame]:
    """
    Récupère 1 an de daily data sur LunarCrush, 
    identique à build_csv => renvoie DataFrame
     columns=[date, open, close, high, low, volume, market_cap, 
              galaxy_score, alt_rank, sentiment]
    triées par date
    """
    base_url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "interval": days_interval
    }
    try:
        r = requests.get(base_url, params=params, timeout=30)
        if r.status_code != 200:
            logging.warning(f"[LC Raw] {symbol} => HTTP {r.status_code}")
            return None
        j = r.json()
        if "data" not in j or not j["data"]:
            return None
        rows = []
        for point in j["data"]:
            ts = point.get("time")
            if not ts:
                continue
            dt_utc = datetime.utcfromtimestamp(ts)
            o = point.get("open")
            c = point.get("close")
            hi= point.get("high")
            lo= point.get("low")
            vol= point.get("volume_24h")
            mc = point.get("market_cap")
            gal = point.get("galaxy_score")
            alt_ = point.get("alt_rank")
            senti= point.get("sentiment")
            rows.append([
                dt_utc, o, hi, lo, c, vol, mc, gal, alt_, senti
            ])
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=[
            "date","open","high","low","close","volume","market_cap",
            "galaxy_score","alt_rank","sentiment"
        ])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df
    except Exception as e:
        logging.error(f"[LC RAW] {symbol} => {e}")
        return None

def compute_daily_change(df: pd.DataFrame, col_name: str) -> pd.DataFrame:
    """
    Identique build_csv => daily_change(t)=close(t)/close(t-1)-1
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", col_name])
    dff = df.copy().sort_values("date").reset_index(drop=True)
    if "close" not in dff.columns:
        dff[col_name] = None
        return dff
    dff["prev_close"] = dff["close"].shift(1)
    dff[col_name] = (dff["close"] / dff["prev_close"] - 1).replace([float("inf"), -float("inf")], None)
    dff.drop(columns=["prev_close"], inplace=True)
    return dff

#########################
# MAIN => Production d'un CSV daily_inference_data.csv 
#         (1 ligne par token, colonnes identiques à build_csv)
#########################

def main():
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("=== START data_fetcher => daily_inference_data.csv ===")

    # 1) Récup data BTC => daily_change
    df_btc = fetch_lc_raw("BTC", INTERVAL)
    if df_btc is not None and not df_btc.empty:
        df_btc = compute_daily_change(df_btc, "btc_daily_change")
        df_btc = df_btc[["date","btc_daily_change"]]
    else:
        df_btc = pd.DataFrame(columns=["date","btc_daily_change"])

    # 2) Récup data ETH => daily_change
    df_eth = fetch_lc_raw("ETH", INTERVAL)
    if df_eth is not None and not df_eth.empty:
        df_eth = compute_daily_change(df_eth, "eth_daily_change")
        df_eth = df_eth[["date","eth_daily_change"]]
    else:
        df_eth = pd.DataFrame(columns=["date","eth_daily_change"])

    # 3) Récup data SOL => daily_change
    df_sol = fetch_lc_raw("SOL", INTERVAL)
    if df_sol is not None and not df_sol.empty:
        df_sol = compute_daily_change(df_sol, "sol_daily_change")
        df_sol = df_sol[["date","sol_daily_change"]]
    else:
        df_sol = pd.DataFrame(columns=["date","sol_daily_change"])

    all_dfs = []
    nb_tokens = len(TOKENS_DAILY)

    logging.info(f"[INFO] We have {nb_tokens} tokens_daily from config.yaml")

    for i, sym in enumerate(TOKENS_DAILY, start=1):
        logging.info(f"[TOKEN {i}/{nb_tokens}] => {sym}")

        df_alt = fetch_lc_raw(sym, INTERVAL)
        if df_alt is None or df_alt.empty:
            logging.warning(f"[SKIP] {sym} => no data from LC.")
            continue

        # On calcule RSI,MACD,ATR
        df_ind = compute_rsi_macd_atr(df_alt)
        if df_ind.empty:
            logging.warning(f"[SKIP] {sym} => empty after indicators.")
            continue

        # Merge BTC/ETH/SOL daily change
        merged = df_ind.merge(df_btc, on="date", how="left")
        merged = merged.merge(df_eth, on="date", how="left")
        merged = merged.merge(df_sol, on="date", how="left")

        # Tri par date
        merged.sort_values("date", inplace=True)
        merged.reset_index(drop=True, inplace=True)
        if merged.empty:
            continue

        # On ne garde que la dernière ligne
        last = merged.iloc[[-1]].copy()  # 1-ligne DataFrame
        # On ajoute 'symbol'
        last["symbol"] = sym
        # On ajoute 'label' = np.nan => pour conserver la structure
        last["label"] = np.nan

        # build_csv => ordre final :
        # ["date","open","high","low","close","volume","market_cap",
        #  "galaxy_score","alt_rank","sentiment",
        #  "rsi","macd","atr",
        #  "label","symbol",
        #  "btc_daily_change","eth_daily_change","sol_daily_change"]
        needed_cols = [
            "date","open","high","low","close","volume","market_cap",
            "galaxy_score","alt_rank","sentiment",
            "rsi","macd","atr",
            "label","symbol",
            "btc_daily_change","eth_daily_change","sol_daily_change"
        ]
        for col in needed_cols:
            if col not in last.columns:
                last[col] = np.nan
        last = last[needed_cols]

        all_dfs.append(last)

        time.sleep(SLEEP_BETWEEN_TOKENS)  # respect rate-limit

    if not all_dfs:
        logging.warning("[data_fetcher] => No tokens => produce empty CSV.")
        columns = [
            "date","open","high","low","close","volume","market_cap",
            "galaxy_score","alt_rank","sentiment",
            "rsi","macd","atr",
            "label","symbol",
            "btc_daily_change","eth_daily_change","sol_daily_change"
        ]
        df_empty = pd.DataFrame(columns=columns)
        df_empty.to_csv(OUTPUT_INFERENCE_CSV, index=False)
        print(f"[WARN] daily_inference_data.csv => empty")
        return

    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["symbol","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    df_final.to_csv(OUTPUT_INFERENCE_CSV, index=False)
    logging.info(f"[data_fetcher] => Export => {OUTPUT_INFERENCE_CSV} => {len(df_final)} rows")
    print(f"[OK] daily_inference_data.csv => {len(df_final)} rows created.")


if __name__=="__main__":
    main()

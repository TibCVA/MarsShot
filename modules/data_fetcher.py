#!/usr/bin/env python3
# coding: utf-8

"""
data_fetcher.py
---------------
- Intraday => Binance (prix spot pour risk_manager).
- Daily => LunarCrush => on re-produit daily_inference_data.csv 
  (1 ligne par token : colonnes identiques build_csv).
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

from indicators import compute_rsi_macd_atr
from binance.client import Client

########################################
# CONFIG
########################################
CONFIG_FILE = "config.yaml"
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

BINANCE_KEY    = CONFIG["binance_api"]["api_key"]
BINANCE_SECRET = CONFIG["binance_api"]["api_secret"]
symbol_map     = CONFIG["exchanges"]["binance"]["symbol_mapping"]

TOKENS_DAILY   = CONFIG["tokens_daily"]  # par ex. 21 tokens
LOG_FILE       = "data_fetcher.log"
OUTPUT_INFERENCE_CSV = "daily_inference_data.csv"

binance_client = Client(BINANCE_KEY, BINANCE_SECRET)

# Pour la partie daily => LunarCrush
LUNAR_API_KEY = CONFIG["lunarcrush"]["api_key"]
INTERVAL      = "1y"
SLEEP_BETWEEN_TOKENS = 6

# --------------------------------------------------------
# Intraday => Binance
# --------------------------------------------------------
def fetch_current_price_from_binance(symbol: str):
    """
    Retourne le dernier prix spot de symbol via binance => symbol_map[symbol] + "USDT".
    """
    if symbol not in symbol_map:
        logging.error(f"[BINANCE PRICE] {symbol} absent du symbol_mapping => skip")
        return None

    bsymbol = symbol_map[symbol]
    pair = f"{bsymbol}USDT"
    try:
        tick = binance_client.get_symbol_ticker(symbol=pair)
        px = float(tick["price"])
        logging.info(f"[BINANCE PRICE] {pair} => {px:.6f}")
        return px
    except Exception as e:
        logging.error(f"[BINANCE PRICE] Error {pair} => {e}")
        return None

def fetch_prices_for_symbols(symbols):
    """
    Récupère un dict { 'FET': 0.123, 'AGIX': 0.987, ... } 
    """
    out = {}
    for sym in symbols:
        px = fetch_current_price_from_binance(sym)
        if px is not None:
            out[sym] = px
        time.sleep(0.1)
    return out

# --------------------------------------------------------
# Daily => LunarCrush
# --------------------------------------------------------
def fetch_lc_raw(symbol: str, interval="1y") -> Optional[pd.DataFrame]:
    """
    Récupère 1 an daily data => colonnes [date,open,high,low,close,volume,market_cap,galaxy_score,alt_rank,sentiment].
    """
    base_url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "interval": interval
    }
    try:
        r = requests.get(base_url, params=params, timeout=30)
        if r.status_code != 200:
            logging.warning(f"[LC Raw] {symbol} => HTTP {r.status_code}")
            return None

        j = r.json()
        if "data" not in j or not j["data"]:
            logging.warning(f"[LC Raw] {symbol} => data vide.")
            return None

        rows = []
        for point in j["data"]:
            ts = point.get("time")
            if not ts: 
                continue
            dt_utc = datetime.utcfromtimestamp(ts)
            o   = point.get("open")
            c   = point.get("close")
            hi  = point.get("high")
            lo  = point.get("low")
            vol = point.get("volume_24h")
            mc  = point.get("market_cap")
            gal = point.get("galaxy_score")
            alt = point.get("alt_rank")
            st  = point.get("sentiment")
            rows.append([dt_utc, o, hi, lo, c, vol, mc, gal, alt, st])

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=[
            "date","open","high","low","close","volume","market_cap",
            "galaxy_score","alt_rank","sentiment"
        ])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        logging.info(f"[LC RAW] {symbol} => {len(df)} lignes")
        return df
    except Exception as e:
        logging.error(f"[LC RAW] {symbol} => {e}")
        return None

def compute_daily_change(df: pd.DataFrame, col_name: str) -> pd.DataFrame:
    """
    daily_change(t) = close(t)/close(t-1)-1
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

def main():
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("=== START data_fetcher => daily_inference_data.csv ===")

    # 1) fetch BTC => daily
    df_btc = fetch_lc_raw("BTC", INTERVAL)
    if df_btc is not None and not df_btc.empty:
        df_btc = compute_daily_change(df_btc, "btc_daily_change")
        df_btc = df_btc[["date","btc_daily_change"]]
    else:
        df_btc = pd.DataFrame(columns=["date","btc_daily_change"])

    # 2) fetch ETH => daily
    df_eth = fetch_lc_raw("ETH", INTERVAL)
    if df_eth is not None and not df_eth.empty:
        df_eth = compute_daily_change(df_eth, "eth_daily_change")
        df_eth = df_eth[["date","eth_daily_change"]]
    else:
        df_eth = pd.DataFrame(columns=["date","eth_daily_change"])

    # 3) fetch SOL => daily
    df_sol = fetch_lc_raw("SOL", INTERVAL)
    if df_sol is not None and not df_sol.empty:
        df_sol = compute_daily_change(df_sol, "sol_daily_change")
        df_sol = df_sol[["date","sol_daily_change"]]
    else:
        df_sol = pd.DataFrame(columns=["date","sol_daily_change"])

    all_dfs = []
    nb_tokens = len(TOKENS_DAILY)
    logging.info(f"[INFO] TOKENS_DAILY => {nb_tokens} tokens => {TOKENS_DAILY}")

    for i, sym in enumerate(TOKENS_DAILY, start=1):
        logging.info(f"[TOKEN {i}/{nb_tokens}] => {sym}")
        df_alt = fetch_lc_raw(sym, INTERVAL)
        if df_alt is None or df_alt.empty:
            logging.warning(f"[SKIP] {sym} => no data from LC => continue.")
            continue

        # RSI, MACD, ATR
        df_ind = compute_rsi_macd_atr(df_alt)
        if df_ind.empty:
            logging.warning(f"[SKIP] {sym} => empty after indicators => continue.")
            continue

        # merges
        merged = df_ind.merge(df_btc, on="date", how="left")
        merged = merged.merge(df_eth, on="date", how="left")
        merged = merged.merge(df_sol, on="date", how="left")
        merged.sort_values("date", inplace=True)
        merged.reset_index(drop=True, inplace=True)

        if merged.empty:
            logging.warning(f"[SKIP] {sym} => merged empty => continue.")
            continue

        # On ne garde que la dernière ligne
        last = merged.iloc[[-1]].copy()
        last["symbol"] = sym
        last["label"]  = np.nan

        needed_cols = [
            "date","open","high","low","close","volume","market_cap",
            "galaxy_score","alt_rank","sentiment",
            "rsi","macd","atr",
            "label","symbol",
            "btc_daily_change","eth_daily_change","sol_daily_change"
        ]
        # On remplit les colonnes manquantes par NaN
        for col in needed_cols:
            if col not in last.columns:
                last[col] = np.nan

        last = last[needed_cols]
        all_dfs.append(last)

        time.sleep(SLEEP_BETWEEN_TOKENS)

    if not all_dfs:
        logging.warning("[data_fetcher] => No final data => produce empty CSV.")
        columns = [
            "date","open","high","low","close","volume","market_cap",
            "galaxy_score","alt_rank","sentiment",
            "rsi","macd","atr",
            "label","symbol",
            "btc_daily_change","eth_daily_change","sol_daily_change"
        ]
        df_empty = pd.DataFrame(columns=columns)
        df_empty.to_csv(OUTPUT_INFERENCE_CSV, index=False)
        print(f"[WARN] daily_inference_data.csv => empty => 0 row")
        return

    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["symbol","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    df_final.to_csv(OUTPUT_INFERENCE_CSV, index=False)
    nb_rows = len(df_final)
    logging.info(f"[data_fetcher] Export => {OUTPUT_INFERENCE_CSV} => {nb_rows} rows")
    print(f"[OK] daily_inference_data.csv => {nb_rows} rows created.")


if __name__ == "__main__":
    main()
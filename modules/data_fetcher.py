#!/usr/bin/env python3
# coding: utf-8

import requests
import logging
import time
import pandas as pd
import os
import yaml
from datetime import datetime

from indicators import compute_rsi_macd_atr
from binance.client import Client

# Lecture config
CONFIG_FILE = "config.yaml"
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

BINANCE_KEY = CONFIG["binance_api"]["api_key"]
BINANCE_SECRET = CONFIG["binance_api"]["api_secret"]
symbol_map = CONFIG["exchanges"]["binance"]["symbol_mapping"]

# Init client Binance
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
# LunarCrush => daily
#########################
def fetch_last_day_from_lunarcrush(symbol, api_key):
    """
    Récupère ~2 jours sur LunarCrush (bucket=day, interval=2d).
    Calcule RSI/MACD/ATR, renvoie la dernière ligne (dict) => features pour l'IA
    {
      'close', 'volume', 'market_cap', 'rsi', 'macd', 'atr',
      'btc_daily_change', 'eth_daily_change', 'sol_daily_change'
    }
    """
    df_token = fetch_lc_raw(symbol, api_key)
    if df_token is None or df_token.empty:
        return None

    df_ind = compute_rsi_macd_atr(df_token)
    if df_ind.empty:
        return None

    last_date = df_ind["date"].max()

    # Récup btc / eth / sol sur 2 jours
    df_btc = fetch_lc_raw("BTC", api_key, days=2)
    df_eth = fetch_lc_raw("ETH", api_key, days=2)
    df_sol = fetch_lc_raw("SOL", api_key, days=2)
    if df_btc is not None and not df_btc.empty:
        df_btc = compute_daily_change(df_btc, "btc_daily_change")
    if df_eth is not None and not df_eth.empty:
        df_eth = compute_daily_change(df_eth, "eth_daily_change")
    if df_sol is not None and not df_sol.empty:
        df_sol = compute_daily_change(df_sol, "sol_daily_change")

    df_merged = df_ind
    if df_btc is not None:
        df_merged = df_merged.merge(df_btc[["date","btc_daily_change"]], on="date", how="left")
    if df_eth is not None:
        df_merged = df_merged.merge(df_eth[["date","eth_daily_change"]], on="date", how="left")
    if df_sol is not None:
        df_merged = df_merged.merge(df_sol[["date","sol_daily_change"]], on="date", how="left")

    row = df_merged[df_merged["date"]==last_date].copy()
    if row.empty:
        return None

    r = row.iloc[0]
    feats = {
        "close": r.get("close", 0.0),
        "volume": r.get("volume", 0.0),
        "market_cap": r.get("market_cap", 0.0),
        "rsi": r.get("rsi", 50.0),
        "macd": r.get("macd", 0.0),
        "atr": r.get("atr", 0.0),
        "btc_daily_change": r.get("btc_daily_change", 0.0),
        "eth_daily_change": r.get("eth_daily_change", 0.0),
        "sol_daily_change": r.get("sol_daily_change", 0.0)
    }
    return feats

def fetch_lc_raw(symbol, api_key, days=2):
    base_url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": api_key,
        "bucket": "day",
        "interval": f"{days}d"
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
            rows.append([dt_utc,o,hi,lo,c,vol,mc])
        df = pd.DataFrame(rows, columns=["date","open","high","low","close","volume","market_cap"])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df
    except Exception as e:
        logging.error(f"[LC RAW] {symbol} => {e}")
        return None

def compute_daily_change(df, col_name):
    dff = df.copy().sort_values("date").reset_index(drop=True)
    dff["prev_close"] = dff["close"].shift(1)
    dff[col_name] = (dff["close"] / dff["prev_close"] - 1).replace([float("inf"), -float("inf")], None)
    dff.drop(columns=["prev_close"], inplace=True)
    return dff
import requests
import logging
import time
import pandas as pd
from datetime import datetime, timedelta
import os

from indicators import compute_rsi_macd_atr

# ==========================
# Coinbase (intraday prices)
# ==========================
COINBASE_SPOT_URL = "https://api.coinbase.com/v2/prices/XXX-USD/spot"

def fetch_current_price_from_coinbase(symbol:str):
    """
    Récupère le prix spot en USD depuis l'endpoint public Coinbase.
    symbol = "BTC", "ETH", ...
    """
    url = COINBASE_SPOT_URL.replace("XXX", symbol)
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            logging.warning(f"[Coinbase Error] {symbol} => HTTP {r.status_code}")
            return None
        j = r.json()
        return float(j["data"]["amount"])
    except Exception as e:
        logging.error(f"[Coinbase Exception] {symbol} => {e}")
        return None

def fetch_prices_for_symbols(symbols):
    """
    Récupère un dict { 'BTC': 12345.6, 'ETH': 234.5, ... }
    """
    out = {}
    for sym in symbols:
        px = fetch_current_price_from_coinbase(sym)
        if px is not None:
            out[sym] = px
        time.sleep(1)
    return out

# ==========================
# LunarCrush (daily fetch)
# ==========================

def fetch_last_day_from_lunarcrush(symbol, api_key):
    """
    Récupère ~2 jours sur LunarCrush (bucket=day, interval=2d).
    Calcule RSI/MACD/ATR, renvoie la dernière ligne (dict) => features pour l'IA
    {
      'close':..., 'volume':..., 'market_cap':...,
      'rsi':..., 'macd':..., 'atr':...,
      'btc_daily_change':..., 'eth_daily_change':...
    }
    Retourne None si échec ou si aucune ligne exploitable.
    """
    df_token = fetch_lc_raw(symbol, api_key)
    if df_token is None or df_token.empty:
        return None

    # On calcule RSI/MACD/ATR
    df_ind = compute_rsi_macd_atr(df_token)
    if df_ind is None or df_ind.empty:
        return None

    # On merge btc, eth daily change sur la date la + récente
    # => On récupère la plus récente date
    last_date = df_ind["date"].max()

    # Récup data BTC / ETH sur 2 jours, on calcule le daily change
    df_btc = fetch_lc_raw("BTC", api_key, days=2)
    df_eth = fetch_lc_raw("ETH", api_key, days=2)
    if df_btc is not None and not df_btc.empty:
        df_btc = compute_daily_change(df_btc, "btc_daily_change")
    if df_eth is not None and not df_eth.empty:
        df_eth = compute_daily_change(df_eth, "eth_daily_change")

    # Merge
    # On ne merge qu'une date => on fait un "left join" sur la date
    df_merged = df_ind.merge(df_btc[["date","btc_daily_change"]], on="date", how="left") if df_btc is not None else df_ind
    df_merged = df_merged.merge(df_eth[["date","eth_daily_change"]], on="date", how="left") if df_eth is not None else df_merged

    row = df_merged[df_merged["date"]==last_date].copy()
    if row.empty:
        # Pas de ligne
        return None

    # On fabrique un dict de features
    # Ordre identique à train_model => [close, volume, market_cap, rsi, macd, atr, btc_daily_change, eth_daily_change]
    r = row.iloc[0]  # on prend la première (et unique) ligne
    feats = {
        "close": r.get("close", 0.0),
        "volume": r.get("volume", 0.0),
        "market_cap": r.get("market_cap", 0.0),
        "rsi": r.get("rsi", 50.0),
        "macd": r.get("macd", 0.0),
        "atr": r.get("atr", 0.0),
        "btc_daily_change": r.get("btc_daily_change", 0.0),
        "eth_daily_change": r.get("eth_daily_change", 0.0)
    }
    return feats

def fetch_lc_raw(symbol, api_key, days=2):
    """
    Récupère 'days' jours max (bucket=day, interval=?).
    Pour être sûr d'avoir la dernière bougie daily, on set interval=7d ou 2d c'est suffisant.
    """
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
            o  = point.get("open")
            c  = point.get("close")
            hi = point.get("high")
            lo = point.get("low")
            vol = point.get("volume_24h")
            mc  = point.get("market_cap")
            rows.append([dt_utc,o,hi,lo,c,vol,mc])
        df = pd.DataFrame(rows, columns=["date","open","high","low","close","volume","market_cap"])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df
    except Exception as e:
        logging.error(f"[fetch_lc_raw Error] {symbol} => {e}")
        return None

def compute_daily_change(df, col_name):
    df = df.copy()
    df = df.sort_values("date").reset_index(drop=True)
    df["prev_close"] = df["close"].shift(1)
    df[col_name] = (df["close"] / df["prev_close"] - 1).replace([float("inf"), -float("inf")], None)
    df.drop(columns=["prev_close"], inplace=True)
    return df
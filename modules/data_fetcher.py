#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import logging
import time
import pandas as pd
import os
import yaml
import numpy as np
from datetime import datetime, timedelta
from typing import Optional

from binance.client import Client
from indicators import compute_indicators_extended

######################################
# Ajuster les chemins
######################################
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# On part du principe que "config.yaml" est à la racine de MarsShot
CONFIG_FILE = os.path.join(CURRENT_DIR, "..", "config.yaml")
# On écrit le CSV au même niveau que config.yaml
OUTPUT_INFERENCE_CSV = os.path.join(CURRENT_DIR, "..", "daily_inference_data.csv")

LOG_FILE = "data_fetcher.log"

if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError(f"[ERREUR] {CONFIG_FILE} introuvable.")

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

BINANCE_KEY    = CONFIG["binance_api"]["api_key"]
BINANCE_SECRET = CONFIG["binance_api"]["api_secret"]
TOKENS_DAILY   = CONFIG["tokens_daily"]

LUNAR_API_KEY  = CONFIG["lunarcrush"]["api_key"]
LOOKBACK_DAYS  = 365
SLEEP_BETWEEN_TOKENS = 12

logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START data_fetcher => daily_inference_data.csv ===")

def fetch_lunar_data_inference(symbol: str, lookback_days=LOOKBACK_DAYS) -> Optional[pd.DataFrame]:
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=lookback_days)
    start_ts = int(start_date.timestamp())
    end_ts   = int(end_date.timestamp())

    url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "start": start_ts,
        "end":   end_ts
    }
    logging.info(f"[LUNAR INF] => symbol={symbol}, lookback_days={lookback_days}")

    max_retries = 3
    df_out = None

    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            code = r.status_code
            logging.info(f"[LUNAR INF] {symbol} => code={code}, attempt={attempt+1}/{max_retries}")
            if code == 200:
                j = r.json()
                data_pts = j.get("data", [])
                if data_pts:
                    rows = []
                    for pt in data_pts:
                        unix_ts = pt.get("time")
                        if not unix_ts:
                            continue
                        dt_utc = datetime.utcfromtimestamp(unix_ts)
                        o   = pt.get("open", 0)
                        c   = pt.get("close", 0)
                        hi  = pt.get("high", 0)
                        lo  = pt.get("low", 0)
                        vol = pt.get("volume_24h", 0)
                        mc  = pt.get("market_cap", 0)
                        gal = pt.get("galaxy_score", 0)
                        alt_= pt.get("alt_rank", 0)
                        senti= pt.get("sentiment", 0)
                        soc_dom= pt.get("social_dominance", 0)
                        mkt_dom= pt.get("market_dominance", 0)
                        rows.append([
                            dt_utc,o,c,hi,lo,vol,mc,gal,alt_,senti,soc_dom,mkt_dom
                        ])
                    if rows:
                        df_out = pd.DataFrame(rows, columns=[
                            "date","open","close","high","low","volume","market_cap",
                            "galaxy_score","alt_rank","sentiment",
                            "social_dominance","market_dominance"
                        ])
                break
            elif code in (429, 502, 530):
                wait_s = 30*(attempt+1)
                logging.warning(f"[WARN INF] {symbol} => code={code}, wait {wait_s}s => retry")
                time.sleep(wait_s)
            else:
                logging.warning(f"[WARN INF] => {symbol}, code={code}, skip.")
                break
        except Exception as e:
            logging.error(f"[ERROR INF] => {symbol} => {e}", exc_info=True)
            wait_s = 30*(attempt+1)
            time.sleep(wait_s)

    if df_out is None or df_out.empty:
        logging.warning(f"[LUNAR INF] {symbol} => df_out is None/empty => None")
        return None

    df_out.sort_values("date", inplace=True)
    df_out.drop_duplicates(subset=["date"], keep="first", inplace=True)
    df_out.reset_index(drop=True, inplace=True)
    return df_out

def main():
    logging.info("=== START data_fetcher => daily_inference_data.csv ===")
    logging.info(f"[DATA_FETCHER] config.yaml => {CONFIG_FILE}")
    logging.info(f"[DATA_FETCHER] TOKENS_DAILY => {TOKENS_DAILY}")

    # Merge BTC/ETH
    df_btc = fetch_lunar_data_inference("BTC", LOOKBACK_DAYS) or pd.DataFrame(columns=["date","close"])
    df_eth = fetch_lunar_data_inference("ETH", LOOKBACK_DAYS) or pd.DataFrame(columns=["date","close"])

    all_dfs = []
    nb = len(TOKENS_DAILY)
    logging.info(f"[DATA_FETCHER] Number of tokens => {nb}")

    for i, sym in enumerate(TOKENS_DAILY, start=1):
        logging.info(f"[INF TOKEN {i}/{nb}] => {sym}")
        df_ = fetch_lunar_data_inference(sym, LOOKBACK_DAYS)
        if df_ is None or df_.empty:
            logging.warning(f"[SKIP INF] => {sym}")
            continue

        # Convert to numeric
        for c_ in [
            "open","close","high","low","volume","market_cap",
            "galaxy_score","alt_rank","sentiment",
            "social_dominance","market_dominance"
        ]:
            if c_ in df_.columns:
                df_[c_] = pd.to_numeric(df_[c_], errors="coerce")
            else:
                df_[c_] = 0.0

        # Indicators
        dfi = compute_indicators_extended(df_)
        dfi.sort_values("date", inplace=True)
        dfi.reset_index(drop=True, inplace=True)

        # Fillna
        for cc in ["galaxy_score","alt_rank","sentiment","market_cap",
                   "social_dominance","market_dominance"]:
            dfi[cc] = dfi[cc].fillna(0)

        # Deltas
        dfi["delta_close_1d"] = dfi["close"].pct_change(1)
        dfi["delta_close_3d"] = dfi["close"].pct_change(3)
        dfi["delta_vol_1d"]   = dfi["volume"].pct_change(1)
        dfi["delta_vol_3d"]   = dfi["volume"].pct_change(3)
        dfi["delta_mcap_1d"]  = dfi["market_cap"].pct_change(1)
        dfi["delta_mcap_3d"]  = dfi["market_cap"].pct_change(3)
        dfi["delta_galaxy_score_3d"] = dfi["galaxy_score"].diff(3)
        dfi["delta_alt_rank_3d"]     = dfi["alt_rank"].diff(3)
        dfi["delta_social_dom_3d"]   = dfi["social_dominance"].diff(3)
        dfi["delta_market_dom_3d"]   = dfi["market_dominance"].diff(3)

        # Merge BTC
        df_btc2 = df_btc[["date","close"]].rename(columns={"close":"btc_close"})
        merged  = pd.merge(dfi, df_btc2, on="date", how="left")
        merged["btc_close"] = merged["btc_close"].fillna(0)
        merged["btc_daily_change"] = merged["btc_close"].pct_change(1)
        merged["btc_3d_change"]    = merged["btc_close"].pct_change(3)

        # Merge ETH
        df_eth2 = df_eth[["date","close"]].rename(columns={"close":"eth_close"})
        merged = pd.merge(merged, df_eth2, on="date", how="left")
        merged["eth_close"] = merged["eth_close"].fillna(0)
        merged["eth_daily_change"] = merged["eth_close"].pct_change(1)
        merged["eth_3d_change"]    = merged["eth_close"].pct_change(3)

        merged.replace([np.inf, -np.inf], np.nan, inplace=True)
        merged["symbol"] = sym

        needed_cols = [
            "date","symbol",
            "delta_close_1d","delta_close_3d","delta_vol_1d","delta_vol_3d",
            "rsi14","rsi30","ma_close_7d","ma_close_14d","atr14","macd_std",
            "stoch_rsi_k","stoch_rsi_d","mfi14","boll_percent_b","obv",
            "adx","adx_pos","adx_neg",
            "btc_daily_change","btc_3d_change","eth_daily_change","eth_3d_change",
            "delta_mcap_1d","delta_mcap_3d",
            "galaxy_score","delta_galaxy_score_3d",
            "alt_rank","delta_alt_rank_3d","sentiment",
            "social_dominance","market_dominance",
            "delta_social_dom_3d","delta_market_dom_3d"
        ]
        merged.dropna(subset=needed_cols, inplace=True)

        if not merged.empty:
            all_dfs.append(merged)
            logging.info(f"[TOKEN OK] {sym} => final shape={merged.shape}")
        else:
            logging.warning(f"[TOKEN EMPTY] {sym} => after dropna => empty")

        time.sleep(SLEEP_BETWEEN_TOKENS)

    if not all_dfs:
        logging.warning("[WARN] => no data => empty daily_inference_data.csv")
        df_empty = pd.DataFrame(columns=needed_cols)
        df_empty.to_csv(OUTPUT_INFERENCE_CSV, index=False)
        print(f"[WARN] => empty {OUTPUT_INFERENCE_CSV}")
        return

    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["symbol","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    df_final.to_csv(OUTPUT_INFERENCE_CSV, index=False)
    nb_ = len(df_final)
    logging.info(f"[DATA_FETCHER] => {OUTPUT_INFERENCE_CSV} with {nb_} lines")
    print(f"[OK] => {OUTPUT_INFERENCE_CSV} with {nb_} lines")


if __name__=="__main__":
    main()
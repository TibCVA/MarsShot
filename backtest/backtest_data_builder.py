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

from indicators import compute_indicators_extended

########################################
# CONFIG
########################################

CONFIG_FILE = "config.yaml"
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

LUNAR_API_KEY   = CONFIG["lunarcrush"]["api_key"]
TOKENS_DAILY    = CONFIG["tokens_daily"]  # ~ 40 tokens
LOG_FILE        = "backtest_data_builder.log"
OUTPUT_CSV      = "backtest_data.csv"

# On choisit 12 mois
LOOKBACK_DAYS   = 365
SLEEP_BETWEEN_TOKENS = 10

logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START backtest_data_builder (3 mois) ===")

def fetch_lunar_data_3m(symbol: str, lookback_days=LOOKBACK_DAYS) -> Optional[pd.DataFrame]:
    """
    Récupère ~12 mois (lookback_days=365) de données journalières
    sur LunarCrush, sans volatility_24h, social_volume_24h...
    Gère 429, 502, 530 => retries exponentiels.
    """
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
    max_retries=3
    df_out=None

    for attempt in range(max_retries):
        try:
            r= requests.get(url, params=params, timeout=30)
            code= r.status_code
            logging.info(f"[LUNAR BACKTEST] {symbol} => code={code}, attempt={attempt+1}")
            if code==200:
                j= r.json()
                data_pts= j.get("data",[])
                if data_pts:
                    rows=[]
                    for pt in data_pts:
                        unix_ts= pt.get("time")
                        if not unix_ts:
                            continue
                        dt_utc= datetime.utcfromtimestamp(unix_ts)

                        o   = pt.get("open",0)
                        c   = pt.get("close",0)
                        hi  = pt.get("high",0)
                        lo  = pt.get("low",0)
                        vol = pt.get("volume_24h",0)
                        mc  = pt.get("market_cap",0)
                        gal = pt.get("galaxy_score",0)
                        alt_= pt.get("alt_rank",0)
                        senti= pt.get("sentiment",0)
                        soc_dom= pt.get("social_dominance",0)
                        mkt_dom= pt.get("market_dominance",0)
                        # pas de volatility_24h
                        rows.append([
                            dt_utc, o, c, hi, lo, vol, mc,
                            gal, alt_, senti, soc_dom, mkt_dom
                        ])
                    if rows:
                        df_out= pd.DataFrame(rows, columns=[
                            "date","open","close","high","low","volume",
                            "market_cap","galaxy_score","alt_rank","sentiment",
                            "social_dominance","market_dominance"
                        ])
                break
            elif code in (429,502,530):
                wait_s= 20*(attempt+1)
                logging.warning(f"[WARN BACKTEST] => {symbol}, code={code}, wait={wait_s}s => retry")
                time.sleep(wait_s)
            else:
                logging.warning(f"[WARN BACKTEST] => {symbol}, code={code}, skip.")
                break
        except Exception as e:
            logging.error(f"[ERROR BACKTEST] {symbol} => {e}")
            time.sleep(20*(attempt+1))

    if df_out is None or df_out.empty:
        return None
    df_out.sort_values("date", inplace=True)
    df_out.drop_duplicates(subset=["date"], keep="first", inplace=True)
    df_out.reset_index(drop=True, inplace=True)
    return df_out


def main():
    logging.info("[BACKTEST BUILDER] => start main()")

    # Récupère BTC et ETH (mêmes raisons que data_fetcher)
    df_btc = fetch_lunar_data_3m("BTC", LOOKBACK_DAYS)
    if df_btc is None:
        df_btc = pd.DataFrame(columns=["date","close"])
    df_eth = fetch_lunar_data_3m("ETH", LOOKBACK_DAYS)
    if df_eth is None:
        df_eth = pd.DataFrame(columns=["date","close"])

    all_dfs=[]
    nb= len(TOKENS_DAILY)

    from indicators import compute_indicators_extended

    for i, sym in enumerate(TOKENS_DAILY, start=1):
        logging.info(f"[BACKTEST {i}/{nb}] => {sym}")
        df_ = fetch_lunar_data_3m(sym, LOOKBACK_DAYS)
        if df_ is None or df_.empty:
            logging.warning(f"[SKIP] => {sym}")
            continue

        # Convertir float
        for cc in [
            "open","close","high","low","volume","market_cap",
            "galaxy_score","alt_rank","sentiment",
            "social_dominance","market_dominance"
        ]:
            df_[cc] = pd.to_numeric(df_[cc], errors="coerce")

        # On calcule les indicateurs identiques
        dfi= compute_indicators_extended(df_)
        dfi["symbol"]= sym
        dfi.sort_values("date", inplace=True)
        dfi.reset_index(drop=True, inplace=True)

        # fillna(0) sur alt_rank, sentiment,...
        for col_ in [
            "galaxy_score","alt_rank","sentiment","market_cap",
            "social_dominance","market_dominance"
        ]:
            dfi[col_] = dfi[col_].fillna(0)

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

        # Merge BTC, ETH => daily_change
        if not df_btc.empty:
            df_btc2= df_btc[["date","close"]].rename(columns={"close":"btc_close"})
            dfi= pd.merge(dfi, df_btc2, on="date", how="left")
            dfi["btc_close"]= dfi["btc_close"].fillna(0)
            dfi["btc_daily_change"]= dfi["btc_close"].pct_change(1)
            dfi["btc_3d_change"]= dfi["btc_close"].pct_change(3)
        else:
            dfi["btc_daily_change"]=0
            dfi["btc_3d_change"]=0

        if not df_eth.empty:
            df_eth2= df_eth[["date","close"]].rename(columns={"close":"eth_close"})
            dfi= pd.merge(dfi, df_eth2, on="date", how="left")
            dfi["eth_close"]= dfi["eth_close"].fillna(0)
            dfi["eth_daily_change"]= dfi["eth_close"].pct_change(1)
            dfi["eth_3d_change"]= dfi["eth_close"].pct_change(3)
        else:
            dfi["eth_daily_change"]=0
            dfi["eth_3d_change"]=0

        dfi.replace([np.inf, -np.inf], np.nan, inplace=True)

        # On dropna sur les colonnes features
        needed_cols = [
            "date","symbol",
            "delta_close_1d","delta_close_3d","delta_vol_1d","delta_vol_3d",
            "rsi14","rsi30","ma_close_7d","ma_close_14d","atr14","macd_std",
            "stoch_rsi_k","stoch_rsi_d","mfi14","boll_percent_b","obv","adx","adx_pos","adx_neg",
            "btc_daily_change","btc_3d_change","eth_daily_change","eth_3d_change",
            "delta_mcap_1d","delta_mcap_3d",
            "galaxy_score","delta_galaxy_score_3d",
            "alt_rank","delta_alt_rank_3d",
            "sentiment",
            "social_dominance","market_dominance",
            "delta_social_dom_3d","delta_market_dom_3d"
        ]
        dfi.dropna(subset=needed_cols, inplace=True)
        if not dfi.empty:
            all_dfs.append(dfi)

        time.sleep(SLEEP_BETWEEN_TOKENS)

    if not all_dfs:
        logging.warning("[WARN] => No data => empty backtest_data.csv")
        pd.DataFrame().to_csv(OUTPUT_CSV, index=False)
        print("[WARN] => empty backtest_data.csv")
        return

    df_final= pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["symbol","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)
    df_final.to_csv(OUTPUT_CSV, index=False)

    nb_= len(df_final)
    print(f"[OK] => {OUTPUT_CSV} => {nb_} lines (3 mois)")

    logging.info(f"[OK] => {OUTPUT_CSV} => {nb_} lines")
    logging.info("=== DONE backtest_data_builder ===")


if __name__=="__main__":
    main()

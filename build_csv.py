#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import pandas as pd
import time
import logging
import os
from datetime import datetime, timedelta
from typing import Optional
import numpy as np

from indicators import compute_indicators_extended

########################################
# CONFIG
########################################

LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"
SHIFT_DAYS = 2         # Label => +5% sur 2 jours
THRESHOLD = 0.05       # +5%
OUTPUT_CSV = "training_data.csv"
LOG_FILE   = "build_csv.log"
SLEEP_BETWEEN_TOKENS = 12

logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START build_csv ===")

########################################
# LISTE TOKENS
########################################

TOKENS = [
  {"symbol": "BTG"},
  {"symbol": "SBD"},
  {"symbol": "NCT"},
  {"symbol": "HIVE"},
  {"symbol": "PRIME"},
  {"symbol": "STG"},
  {"symbol": "NOS"},
  {"symbol": "ACS"},
  {"symbol": "SFUND"},
  {"symbol": "CETUS"},
  {"symbol": "MAGIC"},
  {"symbol": "ALU"},
  {"symbol": "CTXC"},
  {"symbol": "AI"},
  {"symbol": "BLUE"},
  {"symbol": "SUSHI"},
  {"symbol": "DAR"},
  {"symbol": "TOSHI"},
  {"symbol": "WMTX"},
  {"symbol": "STEEM"},
  {"symbol": "AKT"},
  {"symbol": "XNO"},
  {"symbol": "CGPT"},
  {"symbol": "XCN"},
  {"symbol": "HUNT"},
  {"symbol": "KAVA"},
  {"symbol": "WAVES"},
  {"symbol": "LUNA"},
  {"symbol": "VANRY"},
  {"symbol": "WOO"},
  {"symbol": "NFP"},
  {"symbol": "SPELL"},
  {"symbol": "ARK"},
  {"symbol": "UMA"},
  {"symbol": "RSR"},
  {"symbol": "ASM"},
  {"symbol": "VRA"},
  {"symbol": "BANANA"},
  {"symbol": "OSMO"},
  {"symbol": "POPCAT"},
  {"symbol": "STRAX"},
  {"symbol": "PEAQ"},
  {"symbol": "sAVAX"},
  {"symbol": "BOBO"},
  {"symbol": "STPT"},
  {"symbol": "WAVAX"},
  {"symbol": "ZRX"},
  {"symbol": "DEXE"},
  {"symbol": "XEM"},
  {"symbol": "KNC"},
  {"symbol": "DGB"},
  {"symbol": "CTK"},
  {"symbol": "ARKM"},
  {"symbol": "ENJ"},
  {"symbol": "MOC"},
  {"symbol": "MAV"},
  {"symbol": "DENT"},
  {"symbol": "NTRN"},
  {"symbol": "ELF"},
  {"symbol": "ROSE"},
  {"symbol": "SUPER"},
  {"symbol": "HIFI"},
  {"symbol": "HIGH"},
  {"symbol": "SXP"},
  {"symbol": "RLC"},
  {"symbol": "ICX"},
  {"symbol": "BAT"},
  {"symbol": "VOXEL"},
  {"symbol": "ANKR"},
  {"symbol": "GAS"},
  {"symbol": "SKL"},
  {"symbol": "ONE"},
  {"symbol": "ALICE"},
  {"symbol": "SYN"},
  {"symbol": "GLM"},
  {"symbol": "AIDOGE"},
  {"symbol": "RVN"},
  {"symbol": "POLYX"},
  {"symbol": "SLP"},
  {"symbol": "QKC"},
  {"symbol": "SNT"},
  {"symbol": "CTSI"},
  {"symbol": "METIS"},
  {"symbol": "TRU"},
  {"symbol": "DASH"},
  {"symbol": "POWR"},
  {"symbol": "REI"},
  {"symbol": "AXL"},
  {"symbol": "RSS3"},
  {"symbol": "QTUM"},
  {"symbol": "BAND"},
  {"symbol": "BEL"},
  {"symbol": "ALCX"},
  {"symbol": "MTL"},
  {"symbol": "SOL"},
  {"symbol": "LINA"},
  {"symbol": "MOVR"},
  {"symbol": "MBOX"},
  {"symbol": "CHR"},
  {"symbol": "BAKE"},
  {"symbol": "1INCH"},
  {"symbol": "GRS"},
  {"symbol": "IOST"},
  {"symbol": "BNT"},
  {"symbol": "MVL"},
  {"symbol": "CFX"},
  {"symbol": "MOBILE"},
  {"symbol": "ELON"},
  {"symbol": "CYBER"},
  {"symbol": "ILV"},
  {"symbol": "ARDR"},
  {"symbol": "HFT"},
  {"symbol": "BONE"},
  {"symbol": "VELO"},
  {"symbol": "WAXP"},
  {"symbol": "ONT"},
  {"symbol": "DAO"},
  {"symbol": "BAL"},
  {"symbol": "LSK"},
  {"symbol": "XVS"},
  {"symbol": "ZIL"},
  {"symbol": "RIF"},
  {"symbol": "CBK"},
  {"symbol": "PHB"},
  {"symbol": "XYO"},
  {"symbol": "AL"},
  {"symbol": "BNX"},
  {"symbol": "DIA"},
  {"symbol": "WMATIC"},
  {"symbol": "RDNT"},
  {"symbol": "MATIC"},
  {"symbol": "XEC"},
  {"symbol": "DUSK"},
  {"symbol": "STORJ"},
  {"symbol": "NKN"},
  {"symbol": "COMP"},
  {"symbol": "GROK"},
  {"symbol": "AGI"},
  {"symbol": "AMP"},
  {"symbol": "ETHX"},
  {"symbol": "CELO"},
  {"symbol": "FLUX"},
  {"symbol": "BLUR"},
  {"symbol": "CVX"},
  {"symbol": "ETHDYDX"},
  {"symbol": "VIC"},
  {"symbol": "IQ"},
  {"symbol": "SNX"},
  {"symbol": "MINA"},
  {"symbol": "TURBO"},
  {"symbol": "LEVER"},
  {"symbol": "DEGO"},
  {"symbol": "UTK"},
  {"symbol": "ASTR"},
  {"symbol": "CXT"},
  {"symbol": "API3"},
  {"symbol": "ATLAS"},
  {"symbol": "LOOM"},
  {"symbol": "JOE"},
  {"symbol": "ACX"},
  {"symbol": "ORBS"},
  {"symbol": "HOT"},
  {"symbol": "CAKE"},
  {"symbol": "GMX"},
  {"symbol": "cbETH"},
  {"symbol": "CHESS"},
  {"symbol": "MLK"},
  {"symbol": "LUNC"},
  {"symbol": "LQTY"},
  {"symbol": "COTI"},
  {"symbol": "TKO"},
  {"symbol": "QI"},
  {"symbol": "vETH"},
  {"symbol": "FORTH"},
  {"symbol": "T"},
  {"symbol": "ALPHA"},
  {"symbol": "MBL"},
  {"symbol": "FIDA"},
  {"symbol": "CKB"},
  {"symbol": "TLM"},
  {"symbol": "PEPECOIN"},
  {"symbol": "YGG"},
  {"symbol": "APEX"},
  {"symbol": "AGLD"},
  {"symbol": "YFI"},
  {"symbol": "C98"},
  {"symbol": "CHZ"},
  {"symbol": "DKA"},
  {"symbol": "OMG"},
  {"symbol": "COS"},
  {"symbol": "ONG"},
  {"symbol": "SC"},
  {"symbol": "BIGTIME"},
  {"symbol": "ID"},
  {"symbol": "TROY"},
  {"symbol": "CHEX"},
  {"symbol": "CPOOL"},
  {"symbol": "ZEN"},
  {"symbol": "BSW"},
  {"symbol": "MPLX"},
  {"symbol": "STMX"},
  {"symbol": "NAKA"},
  {"symbol": "PRQ"},
  {"symbol": "PHA"},
  {"symbol": "JTO"},
  {"symbol": "VR"},
  {"symbol": "SD"},
  {"symbol": "TAI"},
  {"symbol": "REQ"},
  {"symbol": "AERGO"},
  {"symbol": "GOMINING"},
  {"symbol": "BDX"},
  {"symbol": "EURC"},
  {"symbol": "USDD"},
  {"symbol": "CHEEL"},
  {"symbol": "PYUSD"},
  {"symbol": "USDC.E"},
  {"symbol": "THE"},
  {"symbol": "CRVUSD"},
  {"symbol": "BUSD"},
  {"symbol": "FRAX"},
  {"symbol": "TUSD"},
  {"symbol": "CVC"},
  {"symbol": "ACA"},
  {"symbol": "BFC"},
  {"symbol": "vBNB"},
  {"symbol": "AA"},
  {"symbol": "BRISE"},
  {"symbol": "FIS"},
  {"symbol": "XAUt"},
  {"symbol": "BMX"},
  {"symbol": "ZEC"},
  {"symbol": "PAXG"},
  {"symbol": "FUN"},
  {"symbol": "MDT"},
  {"symbol": "AITECH"},
  {"symbol": "NMR"},
  {"symbol": "SSV"},
  {"symbol": "WPLS"},
  {"symbol": "BADGER"},
  {"symbol": "WHBAR"},
  {"symbol": "BETA"},
  {"symbol": "TLOS"},
  {"symbol": "JST"},
  {"symbol": "CSPR"},
  {"symbol": "BICO"},
  {"symbol": "NFT"},
  {"symbol": "COQ"},
  {"symbol": "POND"},
  {"symbol": "CELR"},
  {"symbol": "CLV"},
  {"symbol": "LIT"},
  {"symbol": "XCH"},
  {"symbol": "SAFE"},
  {"symbol": "HOOK"},
  {"symbol": "STRK"},
  {"symbol": "SFP"},
  {"symbol": "ORCA"},
  {"symbol": "RACA"},
  {"symbol": "ACH"},
  {"symbol": "TWT"},
  {"symbol": "LOOKS"},
  {"symbol": "ERN"},
  {"symbol": "SUN"},
  {"symbol": "TRAC"},
  {"symbol": "AVA"},
  {"symbol": "TRB"},
  {"symbol": "DATA"},
  {"symbol": "RIO"},
  {"symbol": "STRX"},
  {"symbol": "BTC.b"},
  {"symbol": "MX"},
  {"symbol": "IDEX"},
  {"symbol": "MEME"},
  {"symbol": "RARE"},
  {"symbol": "DF"},
  {"symbol": "RAD"},
  {"symbol": "IOTX"},
  {"symbol": "MED"},
  {"symbol": "KMD"},
  {"symbol": "OXT"},
  {"symbol": "TOKEN"},
  {"symbol": "CTC"},
  {"symbol": "GNO"},
  {"symbol": "EL"},
  {"symbol": "COW"},
  {"symbol": "PERP"},
  {"symbol": "VTHO"},
  {"symbol": "ACE"},
  {"symbol": "GHST"},
  {"symbol": "AUCTION"},
  {"symbol": "LOKA"},
  {"symbol": "TFUEL"},
  {"symbol": "XVG"},
  {"symbol": "SCRT"},
  {"symbol": "ATA"},
  {"symbol": "KSM"},
  {"symbol": "KDA"},
  {"symbol": "FXS"},
  {"symbol": "LRC"},
  {"symbol": "DIONE"},
  {"symbol": "PEOPLE"},
  {"symbol": "SATS"},
  {"symbol": "NPC"},
  {"symbol": "MYRO"},
  {"symbol": "ORDI"},
  {"symbol": "USTC"},
  {"symbol": "GNS"},
  {"symbol": "LADYS"},
  {"symbol": "ZETA"},
  {"symbol": "HPO"}
]

########################################
# fetch_lunar_data_2y AVEC RETRY
########################################

def fetch_lunar_data_2y(symbol: str) -> Optional[pd.DataFrame]:
    """
    Récupère 2 ans de données journalières via LunarCrush.
    Gère les codes 429, 502, 530 avec retry exponentiel.
    """
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=730)
    start_ts = int(start_date.timestamp())
    end_ts   = int(end_date.timestamp())

    url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "start": start_ts,
        "end":   end_ts
    }
    max_retries = 3
    df_out = None

    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            code = r.status_code
            logging.info(f"[LUNAR] {symbol} => HTTP {code} (attempt {attempt+1}/{max_retries})")

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
                        h   = pt.get("high", 0)
                        lo  = pt.get("low", 0)
                        vol = pt.get("volume_24h", 0)
                        mc  = pt.get("market_cap", 0)
                        gal = pt.get("galaxy_score", 0)
                        alt_ = pt.get("alt_rank", 0)
                        senti = pt.get("sentiment", 0)

                        # On n'utilise plus volatility_24h => on laisse, 
                        # ou on la retire si on veut la capter, c'est possible.
                        soc_dom = pt.get("social_dominance", 0)
                        mkt_dom = pt.get("market_dominance", 0)
                        # On ne garde PAS volatility_24h => on ignore
                        # On retire "volatility_24h" si vous le souhaitez

                        rows.append([
                            dt_utc, o, c, h, lo, vol,
                            mc, gal, alt_, senti,
                            soc_dom, mkt_dom
                        ])
                    if rows:
                        df_out = pd.DataFrame(rows, columns=[
                            "date","open","close","high","low","volume",
                            "market_cap","galaxy_score","alt_rank","sentiment",
                            "social_dominance","market_dominance"
                        ])
                break

            elif code in (429, 502, 530):
                wait_s = 30*(attempt+1)
                logging.warning(f"[WARN] {symbol} => code={code}, wait {wait_s}s => retry")
                time.sleep(wait_s)

            else:
                logging.warning(f"[WARN] {symbol} => code={code}, skip.")
                break

        except Exception as e:
            logging.error(f"[ERROR] {symbol} => {e}")
            wait_s = 30*(attempt+1)
            time.sleep(wait_s)

    if df_out is None or df_out.empty:
        return None

    df_out.sort_values("date", inplace=True)
    df_out.drop_duplicates(subset=["date"], keep="first", inplace=True)
    df_out.reset_index(drop=True, inplace=True)
    return df_out

########################################
# compute_label => +5%
########################################

def compute_label(df_in):
    dff = df_in.sort_values("date").copy()
    if "close" not in dff.columns:
        dff["label"] = None
        return dff
    dff["future_close"] = dff["close"].shift(-SHIFT_DAYS)
    dff["variation"] = (dff["future_close"] - dff["close"]) / dff["close"]
    dff["label"] = (dff["variation"] >= THRESHOLD).astype(int)
    return dff

########################################
# MAIN
########################################

def main():
    logging.info("=== build_csv => start ===")

    # Récup 2 ans BTC, ETH
    df_btc = fetch_lunar_data_2y("BTC")
    if df_btc is None or df_btc.empty:
        df_btc = pd.DataFrame(columns=["date","close"])

    df_eth = fetch_lunar_data_2y("ETH")
    if df_eth is None or df_eth.empty:
        df_eth = pd.DataFrame(columns=["date","close"])

    all_dfs = []
    nb = len(TOKENS)

    for i, tk in enumerate(TOKENS, start=1):
        sym = tk["symbol"]
        logging.info(f"[TOK {i}/{nb}] => {sym}")

        df_ = fetch_lunar_data_2y(sym)
        if df_ is None or df_.empty:
            logging.warning(f"[SKIP] => {sym}")
            continue

        # 1) label
        df_ = compute_label(df_)

        # 2) Convert to float
        for c_ in [
            "open","high","low","close","volume","market_cap",
            "galaxy_score","alt_rank","sentiment",
            "social_dominance","market_dominance"
        ]:
            if c_ in df_.columns:
                df_[c_] = pd.to_numeric(df_[c_], errors="coerce")
            else:
                df_[c_] = 0.0

        # 3) compute_indicators_extended
        df_ind = compute_indicators_extended(df_)

        df_ind["label"] = df_["label"]
        df_ind.dropna(subset=["label"], inplace=True)

        df_ind["symbol"] = sym
        df_ind.sort_values("date", inplace=True)
        df_ind.reset_index(drop=True, inplace=True)

        # fillna(0)
        for col_ in [
            "galaxy_score","alt_rank","sentiment","market_cap",
            "social_dominance","market_dominance"
        ]:
            df_ind[col_] = df_ind[col_].fillna(0)

        # Deltas
        df_ind["delta_close_1d"] = df_ind["close"].pct_change(1)
        df_ind["delta_close_3d"] = df_ind["close"].pct_change(3)
        df_ind["delta_vol_1d"]   = df_ind["volume"].pct_change(1)
        df_ind["delta_vol_3d"]   = df_ind["volume"].pct_change(3)

        df_ind["delta_mcap_1d"]  = df_ind["market_cap"].pct_change(1)
        df_ind["delta_mcap_3d"]  = df_ind["market_cap"].pct_change(3)

        df_ind["delta_galaxy_score_3d"] = df_ind["galaxy_score"].diff(3)
        df_ind["delta_alt_rank_3d"]     = df_ind["alt_rank"].diff(3)

        df_ind["delta_social_dom_3d"]   = df_ind["social_dominance"].diff(3)
        df_ind["delta_market_dom_3d"]   = df_ind["market_dominance"].diff(3)
        # On n'utilise plus volatility_24h => on n'en fait pas delta_volatility_3d

        # Merge BTC, ETH => (close)
        df_btc2 = df_btc[["date","close"]].rename(columns={"close":"btc_close"})
        df_eth2 = df_eth[["date","close"]].rename(columns={"close":"eth_close"})
        merged = pd.merge(df_ind, df_btc2, on="date", how="left")
        merged = pd.merge(merged, df_eth2, on="date", how="left")
        merged["btc_close"] = merged["btc_close"].fillna(0)
        merged["eth_close"] = merged["eth_close"].fillna(0)

        merged["btc_daily_change"] = merged["btc_close"].pct_change(1)
        merged["btc_3d_change"]    = merged["btc_close"].pct_change(3)
        merged["eth_daily_change"] = merged["eth_close"].pct_change(1)
        merged["eth_3d_change"]    = merged["eth_close"].pct_change(3)

        # remove inf
        merged.replace([np.inf, -np.inf], np.nan, inplace=True)

        needed_cols = [
            "delta_close_1d","delta_close_3d","delta_vol_1d","delta_vol_3d",
            "rsi14","rsi30","ma_close_7d","ma_close_14d","atr14","macd_std",
            "stoch_rsi_k","stoch_rsi_d","mfi14","boll_percent_b","obv","adx","adx_pos","adx_neg",
            "btc_daily_change","btc_3d_change","eth_daily_change","eth_3d_change",
            "delta_mcap_1d","delta_mcap_3d","galaxy_score","delta_galaxy_score_3d",
            "alt_rank","delta_alt_rank_3d","sentiment",
            "social_dominance","market_dominance",
            "delta_social_dom_3d","delta_market_dom_3d",
            # Retiré: volatility_24h et delta_volatility_3d
            "label"
        ]
        merged.dropna(subset=needed_cols, inplace=True)

        all_dfs.append(merged)
        time.sleep(SLEEP_BETWEEN_TOKENS)

    # Check final
    if not all_dfs:
        logging.warning("[WARN] => No data => minimal CSV.")
        empty_cols = ["date","symbol"] + needed_cols
        df_empty = pd.DataFrame(columns=empty_cols)
        df_empty.to_csv(OUTPUT_CSV, index=False)
        print(f"[WARN] empty => {OUTPUT_CSV}")
        return

    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["symbol","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    final_cols = ["date","symbol"] + needed_cols
    df_final = df_final[final_cols].copy()

    df_final.to_csv(OUTPUT_CSV, index=False)
    nb_rows = len(df_final)
    print(f"[OK] => {OUTPUT_CSV} with {nb_rows} lines")
    logging.info(f"[OK] => {OUTPUT_CSV} => {nb_rows} lines")
    logging.info("=== DONE build_csv ===")

if __name__=="__main__":
    main()
 

#!/usr/bin/env python3
# coding: utf-8

import requests
import pandas as pd
import time
import logging
import os
from datetime import datetime, timedelta
from typing import Optional
import numpy as np

from indicators import compute_indicators

########################################
# CONFIG
########################################

LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"
SHIFT_DAYS = 2      # Label => +5% sur 2 jours
THRESHOLD = 0.05    # +5%
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
# TOKENS (321)
########################################

TOKENS = [
  {"symbol": "BTG"},
  {"symbol": "TRUMP"},
  {"symbol": "SBD"},
  {"symbol": "NCT"},
  {"symbol": "HIVE"},
  {"symbol": "PAAL"},
  {"symbol": "PRIME"},
  {"symbol": "STG"},
  {"symbol": "NOS"},
  {"symbol": "ACS"},
  {"symbol": "SFUND"},
  {"symbol": "CETUS"},
  {"symbol": "MAGIC"},
  {"symbol": "MCADE"},
  {"symbol": "ALU"},
  {"symbol": "CTXC"},
  {"symbol": "AI"},
  {"symbol": "BITCOIN"},
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
  {"symbol": "TEL"},
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
# fetch_lunar_data_2y
########################################

def fetch_lunar_data_2y(symbol: str) -> Optional[pd.DataFrame]:
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
    max_retries = 2
    attempt = 0
    df_out = None

    while attempt < max_retries:
        attempt += 1
        try:
            r = requests.get(url, params=params, timeout=30)
            logging.info(f"[LUNAR] {symbol} => HTTP {r.status_code}")
            if r.status_code == 200:
                j = r.json()
                data_pts = j.get("data", [])
                if data_pts:
                    rows = []
                    for pt in data_pts:
                        ts_ = pt.get("time")
                        if not ts_:
                            continue
                        dt_utc = datetime.utcfromtimestamp(ts_)
                        o   = pt.get("open", None)
                        c   = pt.get("close", None)
                        h   = pt.get("high", None)
                        lo  = pt.get("low", None)
                        vol = pt.get("volume_24h", None)
                        mc  = pt.get("market_cap", None)
                        gal = pt.get("galaxy_score", None)
                        alt_ = pt.get("alt_rank", None)
                        senti = pt.get("sentiment", None)

                        rows.append([
                            dt_utc, o, c, h, lo, vol, mc, gal, alt_, senti
                        ])
                    if rows:
                        df_out = pd.DataFrame(rows, columns=[
                            "date","open","close","high","low","volume","market_cap",
                            "galaxy_score","alt_rank","sentiment"
                        ])
                break
            elif r.status_code == 429:
                logging.warning(f"[429] => {symbol}, wait 60s")
                time.sleep(60)
            else:
                logging.warning(f"[WARN] => {symbol}, code={r.status_code}, skip.")
                break
        except Exception as e:
            logging.error(f"[ERROR] => {symbol} => {e}")
            break

    if df_out is None or df_out.empty:
        return None

    df_out.sort_values("date", inplace=True)
    df_out.drop_duplicates(subset=["date"], keep="first", inplace=True)
    df_out.reset_index(drop=True, inplace=True)
    return df_out

########################################
# compute_label => +5% sur SHIFT_DAYS=2
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

        # 1) label => +5% /2j
        df_ = compute_label(df_)

        # 2) Convert to float
        for c_ in ["open","high","low","close","volume","market_cap","galaxy_score","alt_rank","sentiment"]:
            df_[c_] = pd.to_numeric(df_[c_], errors="coerce")

        # 3) compute_indicators => rsi14,rsi30,macd_std,atr14, ma_close_7d, ma_close_14d
        from indicators import compute_indicators
        df_ind = compute_indicators(df_)

        df_ind["label"] = df_["label"]
        df_ind.dropna(subset=["label"], inplace=True)

        df_ind["symbol"] = sym
        df_ind.sort_values("date", inplace=True)
        df_ind.reset_index(drop=True, inplace=True)

        # 4) Remplacer NaN par 0 => galaxy_score, alt_rank, sentiment, market_cap
        for col_ in ["galaxy_score","alt_rank","sentiment","market_cap"]:
            df_ind[col_] = df_ind[col_].fillna(0)

        # 5) Calcul delta_close_1d,3d
        df_ind["delta_close_1d"] = df_ind["close"].pct_change(periods=1, fill_method=None)
        df_ind["delta_close_3d"] = df_ind["close"].pct_change(periods=3, fill_method=None)

        # delta_vol_1d,3d
        df_ind["delta_vol_1d"] = df_ind["volume"].pct_change(1, fill_method=None)
        df_ind["delta_vol_3d"] = df_ind["volume"].pct_change(3, fill_method=None)

        # delta_mcap_1d,3d
        df_ind["delta_mcap_1d"] = df_ind["market_cap"].pct_change(1, fill_method=None)
        df_ind["delta_mcap_3d"] = df_ind["market_cap"].pct_change(3, fill_method=None)

        # delta_galaxy_score_3d
        df_ind["delta_galaxy_score_3d"] = df_ind["galaxy_score"].diff(3)

        # delta_alt_rank_3d
        df_ind["delta_alt_rank_3d"] = df_ind["alt_rank"].diff(3)

        # Merge BTC, ETH => rename
        df_btc2 = df_btc[["date","close"]].rename(columns={"close":"btc_close"})
        df_eth2 = df_eth[["date","close"]].rename(columns={"close":"eth_close"})
        merged = pd.merge(df_ind, df_btc2, on="date", how="left")
        merged = pd.merge(merged, df_eth2, on="date", how="left")

        merged["btc_close"] = merged["btc_close"].fillna(0)
        merged["eth_close"] = merged["eth_close"].fillna(0)

        merged["btc_daily_change"] = merged["btc_close"].pct_change(1, fill_method=None)
        merged["btc_3d_change"]    = merged["btc_close"].pct_change(3, fill_method=None)
        merged["eth_daily_change"] = merged["eth_close"].pct_change(1, fill_method=None)
        merged["eth_3d_change"]    = merged["eth_close"].pct_change(3, fill_method=None)

        # On remplace inf par NaN
        merged.replace([np.inf, -np.inf], np.nan, inplace=True)

        # dropna final
        # => On NE VEUT PLUS delta_sentiment_3d => on retire de la liste
        merged.dropna(subset=[
            "delta_close_1d","delta_close_3d",
            "delta_vol_1d","delta_vol_3d",
            "rsi14","rsi30","ma_close_7d","ma_close_14d","atr14","macd_std",
            "btc_daily_change","btc_3d_change","eth_daily_change","eth_3d_change",
            "delta_mcap_1d","delta_mcap_3d",
            "galaxy_score","delta_galaxy_score_3d",
            "alt_rank","delta_alt_rank_3d",
            "sentiment",
            "label"  # plus delta_sentiment_3d !
        ], inplace=True)

        all_dfs.append(merged)
        time.sleep(SLEEP_BETWEEN_TOKENS)

    if not all_dfs:
        logging.warning("[WARN] => No data => minimal CSV")
        final_cols = [
            "date","symbol","label",
            "delta_close_1d","delta_close_3d",
            "delta_vol_1d","delta_vol_3d",
            "rsi14","rsi30","ma_close_7d","ma_close_14d","atr14","macd_std",
            "btc_daily_change","btc_3d_change","eth_daily_change","eth_3d_change",
            "delta_mcap_1d","delta_mcap_3d",
            "galaxy_score","delta_galaxy_score_3d",
            "alt_rank","delta_alt_rank_3d",
            "sentiment"
        ]
        df_empty = pd.DataFrame(columns=final_cols)
        df_empty.to_csv(OUTPUT_CSV, index=False)
        print(f"[WARN] empty => {OUTPUT_CSV}")
        return

    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["symbol","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    # On ne garde QUE (21 features + date,symbol,label),
    # => enlevé delta_sentiment_3d
    final_cols = [
        "date","symbol","label",
        "delta_close_1d","delta_close_3d",
        "delta_vol_1d","delta_vol_3d",
        "rsi14","rsi30","ma_close_7d","ma_close_14d","atr14","macd_std",
        "btc_daily_change","btc_3d_change","eth_daily_change","eth_3d_change",
        "delta_mcap_1d","delta_mcap_3d",
        "galaxy_score","delta_galaxy_score_3d",
        "alt_rank","delta_alt_rank_3d",
        "sentiment"
    ]
    df_final = df_final[final_cols].copy()

    df_final.to_csv(OUTPUT_CSV, index=False)
    rows_ = len(df_final)
    print(f"[OK] => {OUTPUT_CSV} with {rows_} lines")
    logging.info(f"[OK] => {OUTPUT_CSV} => {rows_} lines")
    logging.info("=== DONE build_csv ===")

if __name__=="__main__":
    main()

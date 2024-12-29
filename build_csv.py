#!/usr/bin/env python3
# coding: utf-8

import requests
import pandas as pd
import time
import logging
import os
from datetime import datetime, timedelta

#####################################
# CLES D'API
#####################################
CMC_API_KEY = "0a602f8f-2a68-4992-89f2-7e7416a4d8e8"
NANSEN_API_KEY = "QOkxEu97HMywRodE4747YpwVsivO690Fl6arVXoe"
LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"

#####################################
# PARAMS
#####################################
DAYS = 30
SHIFT_DAYS = 2
THRESHOLD = 0.30
OUTPUT_CSV = "training_data.csv"
LOG_FILE = "build_csv.log"

logging.basicConfig(filename=LOG_FILE,
                    level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logging.info("=== START build_csv ===")

#####################################
# LISTE 102 TOKENS
#####################################
TOKENS = [
    # 25 tokens manquants
    {
        "symbol": "SOLVEX",
        "cmc_id": 28301,
        "chain": "eth",
        "contract": "0x2d7a47908d817dd359b9595c19f6d9e1c994472a",
        "lunar_symbol": "SOLVEX"
    },
    {
        "symbol": "PATRIOT",
        "cmc_id": 27669,
        "chain": "bsc",
        "contract": "0x6d48b2d0de4d2e6c5f0a3b0b2824b99b42ed56d1",
        "lunar_symbol": "PATRIOT"
    },
    {
        "symbol": "FAI",
        "cmc_id": 28885,
        "chain": "eth",
        "contract": "0x4d5f47fa6a74757f35c14fd3a6ef8e3c9bc514e8",
        "lunar_symbol": "FAI"
    },
    {
        "symbol": "MOEW",
        "cmc_id": 28839,
        "chain": None,  # solana => pas couverte par nansen
        "contract": None,
        "lunar_symbol": "MOEW"
    },
    {
        "symbol": "A8",
        "cmc_id": 28136,
        "chain": "bsc",
        "contract": "0x7d70642b5fec0adc79d6cd5cad7d73c7ce2dd61d",
        "lunar_symbol": "A8"
    },
    {
        "symbol": "GNON",
        "cmc_id": 28477,
        "chain": "eth",
        "contract": "0x364d2ebf28b9b9cf077bb78a1ea91f859f307f85",
        "lunar_symbol": "GNON"
    },
    {
        "symbol": "COOKIE",
        "cmc_id": 28991,
        "chain": "eth",
        "contract": "0x52f4d5417d219fe71f81cbf5c45c1e19522a5359",
        "lunar_symbol": "COOKIE"
    },
    {
        "symbol": "LOFI",
        "cmc_id": 27987,
        "chain": "eth",
        "contract": "0x17d8519f57450e2b7e6ae1163e0e448322a8af17",
        "lunar_symbol": "LOFI"
    },
    {
        "symbol": "PRQ",
        "cmc_id": 7208,
        "chain": "eth",
        "contract": "0x362bc847A3a9637d3af6624EeC853618a43ed7D2",
        "lunar_symbol": "PRQ"
    },
    {
        "symbol": "CHAMP",
        "cmc_id": 28344,
        "chain": "bsc",
        "contract": "0x7d70642b5fec0adc79d6cd5cad7d73c7ce2dd61d",
        "lunar_symbol": "CHAMP"
    },
    {
        "symbol": "PHA",
        "cmc_id": 6841,
        "chain": None, # multiple => on skip
        "contract": None,
        "lunar_symbol": "PHA"
    },
    {
        "symbol": "UXLINK",
        "cmc_id": 28810,
        "chain": "bsc",
        "contract": "0xb1f0c25dd5deb285c9714ebf7c0ad8f1c471d0d5",
        "lunar_symbol": "UXLINK"
    },
    {
        "symbol": "KOMA",
        "cmc_id": 28356,
        "chain": "eth",
        "contract": "0x42d1b21e0ca6086c757ab33c76f0cc6ad5ceeae7",
        "lunar_symbol": "KOMA"
    },
    {
        "symbol": "COW",
        "cmc_id": 11042,
        "chain": "eth",
        "contract": "0xdef1ca1fb7fbcdc777520aa7f396b4e015f497ab",
        "lunar_symbol": "COW"
    },
    {
        "symbol": "MORPHO",
        "cmc_id": 27950,
        "chain": "eth",
        "contract": "0x9994E35Db50125E0DF82e4c2dde62496CE330999",
        "lunar_symbol": "MORPHO"
    },
    {
        "symbol": "WILD",
        "cmc_id": 9674,
        "chain": "eth",
        "contract": "0x2a3bff78b79a009976eea096a51a948a3dc00e34",
        "lunar_symbol": "WILD"
    },
    {
        "symbol": "MCADE",
        "cmc_id": 24660,
        "chain": "eth",
        "contract": "0x957d1ad5214468332c5e6c00305a25116f53c934",
        "lunar_symbol": "MCADE"
    },
    {
        "symbol": "AIXBT",
        "cmc_id": 28743,
        "chain": "eth",
        "contract": "0x2d7a47908d817dd359b9595c19f6d9e1c994472a",
        "lunar_symbol": "AIXBT"
    },
    {
        "symbol": "NETVR",
        "cmc_id": 28770,
        "chain": "eth",
        "contract": "0x2d7a47908d817dd359b9595c19f6d9e1c994472a",
        "lunar_symbol": "NETVR"
    },
    {
        "symbol": "XVG",
        "cmc_id": 693,
        "chain": None,
        "contract": None,
        "lunar_symbol": "XVG"
    },
    {
        "symbol": "AVA",
        "cmc_id": 4646,
        "chain": "bsc",
        "contract": "0x78f5d389f5cdccfc41594abab4b0ed02f31398b3",
        "lunar_symbol": "AVA"
    },
    {
        "symbol": "XYO",
        "cmc_id": 2765,
        "chain": "eth",
        "contract": "0x55296f69f40ea6d20e478533c15a6b08b654e758",
        "lunar_symbol": "XYO"
    },
    {
        "symbol": "WHBAR",
        "cmc_id": 28571,
        "chain": None,
        "contract": None,
        "lunar_symbol": "WHBAR"
    },
    {
        "symbol": "PAAL",
        "cmc_id": 28729,
        "chain": "eth",
        "contract": "0x14fee680690900ba0cccf3f12a35028b53369787",
        "lunar_symbol": "PAAL"
    },
    {
        "symbol": "OL",
        "cmc_id": 28897,
        "chain": None,
        "contract": None,
        "lunar_symbol": "OL"
    },

    # ... on enchaîne avec les 77 tokens restants ...
    # EXACTEMENT comme dans la config.yaml (mêmes cmc_id, chain, contract)
    # ...
    {
        "symbol": "ALICE",
        "cmc_id": 8766,
        "chain": "eth",
        "contract": "0xAC51066d7bEC65Dc4589368da368b212745d63E8",
        "lunar_symbol": "ALICE"
    }
]

#####################################
# FONCTIONS
#####################################
def fetch_cmc_history(cmc_id, days=30):
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accepts": "application/json"
    }
    params = {
        "id": str(cmc_id),
        "time_start": start_date.isoformat(),
        "time_end": end_date.isoformat(),
        "interval": "1d",
        "count": days,
        "convert": "USD"
    }
    try:
        r = requests.get(url, headers=headers, params=params)
        j = r.json()
        if "data" not in j or not j["data"]:
            return None
        quotes = j["data"]["quotes"]
        if not quotes:
            return None
        rows = []
        for q in quotes:
            t = q["timestamp"]
            dd = datetime.fromisoformat(t.replace("Z",""))
            usd = q["quote"].get("USD",{})
            o = usd.get("open", None)
            h = usd.get("high", None)
            lo = usd.get("low", None)
            c = usd.get("close", None)
            vol = usd.get("volume", None)
            mc = usd.get("market_cap", None)
            if (o is None) or (h is None) or (lo is None) or (c is None):
                continue
            rows.append([dd,o,h,lo,c,vol,mc])
        df = pd.DataFrame(rows, columns=["date","open","high","low","close","volume","market_cap"])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df
    except Exception as e:
        logging.error(f"[CMC ERROR] {cmc_id} => {e}")
        return None

def fetch_nansen_holders(chain, contract):
    if not chain or not contract:
        return 0
    url = f"https://api.nansen.ai/tokens/{chain}/{contract}/holders"
    headers = {"X-API-KEY": NANSEN_API_KEY}
    try:
        r = requests.get(url, headers=headers)
        j = r.json()
        if "data" in j and "holders" in j["data"]:
            return j["data"]["holders"]
        return 0
    except:
        return 0

def fetch_lunar_sentiment(symbol):
    if not symbol:
        return 0.5
    url = f"https://lunarcrush.com/api2?symbol={symbol}&data=market"
    headers = {"Authorization": f"Bearer {LUNAR_API_KEY}"}
    try:
        r = requests.get(url, headers=headers)
        j = r.json()
        if "data" not in j or not j["data"]:
            return 0.5
        dd = j["data"][0]
        sc = dd.get("social_score", 50)
        maxi = max(sc,100)
        val = sc/maxi
        if val>1:
            val=1
        return val
    except:
        return 0.5

def build_token_df(token):
    sym = token["symbol"]
    cmc_id = token["cmc_id"]
    chain = token["chain"]
    contract = token["contract"]
    lunar = token["lunar_symbol"]

    df_cmc = fetch_cmc_history(cmc_id, DAYS)
    if df_cmc is None or df_cmc.empty:
        logging.warning(f"No data for {sym}")
        return None

    df_cmc["token"] = sym

    h = fetch_nansen_holders(chain, contract)
    s = fetch_lunar_sentiment(lunar)

    df_cmc["holders"] = h
    df_cmc["sentiment_score"] = s
    return df_cmc

def compute_label(df):
    df = df.sort_values("date").reset_index(drop=True)
    df["price_future"] = df["close"].shift(-SHIFT_DAYS)
    df["variation_2d"] = (df["price_future"] - df["close"]) / df["close"]
    df["label"] = (df["variation_2d"]>=THRESHOLD).astype(int)
    return df

def main():
    logging.info("=== build_csv => collecting data for 102 tokens ===")
    all_dfs = []
    for t in TOKENS:
        sym = t["symbol"]
        logging.info(f"... fetching {sym}")
        df_ = build_token_df(t)
        if df_ is None or df_.empty:
            continue
        df_ = compute_label(df_)
        all_dfs.append(df_)
        time.sleep(2)

    if not all_dfs:
        logging.warning("No data => no CSV.")
        return
    df_all = pd.concat(all_dfs, ignore_index=True)
    df_all = df_all.sort_values(["token","date"]).reset_index(drop=True)

    df_all.dropna(subset=["label"], inplace=True)

    final = df_all[["token","date","close","volume","market_cap","holders","sentiment_score","label"]].copy()
    final.rename(columns={"close":"price"}, inplace=True)

    final.to_csv(OUTPUT_CSV, index=False)
    print(f"Export => {OUTPUT_CSV} ({len(final)} lignes)")
    logging.info(f"Export => {OUTPUT_CSV} => {len(final)} lignes")

if __name__=="__main__":
    main()


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

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START build_csv ===")

#####################################
# LISTE 102 TOKENS
#####################################
TOKENS = [
    {
        "symbol": "SOLVEX",
        "cmc_id": 9604,  # Corrigé
        "chain": "eth",
        "contract": "0x2d7a47908d817dd359b9595c19f6d9e1c994472a",
        "lunar_symbol": "SOLVEX"
    },
    {
        "symbol": "PATRIOT",
        "cmc_id": 2988,  # Corrigé
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
        "chain": None,
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
        "chain": None,
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
    {
        "symbol": "LKI",
        "cmc_id": 28634,
        "chain": "eth",
        "contract": "0x4b3a0c6d668b43f3f07904e124328659b90bb4ca",
        "lunar_symbol": "LKI"
    },
    {
        "symbol": "APX",
        "cmc_id": 21792,
        "chain": "bsc",
        "contract": "0x78f5d389f5cdccfc41594abab4b0ed02f31398b3",
        "lunar_symbol": "APX"
    },
    {
        "symbol": "DF",
        "cmc_id": 5777,
        "chain": "eth",
        "contract": "0x431ad2ff6a9C365805eBaD47Ee021148d6f7DBe0",
        "lunar_symbol": "DF"
    },
    {
        "symbol": "EL",
        "cmc_id": 7505,
        "chain": "eth",
        "contract": "0x2781246fe707bb15cee3e5ea354e2154a2877b16",
        "lunar_symbol": "EL"
    },
    {
        "symbol": "VELO",
        "cmc_id": 20461,
        "chain": None,
        "contract": None,
        "lunar_symbol": "VELO"
    },
    {
        "symbol": "SRX",
        "cmc_id": 10798,
        "chain": None,
        "contract": None,
        "lunar_symbol": "SRX"
    },
    {
        "symbol": "ACX",
        "cmc_id": 19163,
        "chain": "eth",
        "contract": "0x44108f0223a3c3028f5fe7177f8964c072d90904",
        "lunar_symbol": "ACX"
    },
    {
        "symbol": "COMAI",
        "cmc_id": 28649,
        "chain": "eth",
        "contract": "0x4d5f47fa6a74757f35c14fd3a6ef8e3c9bc514e8",
        "lunar_symbol": "COMAI"
    },
    {
        "symbol": "ZENT",
        "cmc_id": 28552,
        "chain": "bsc",
        "contract": "0x5874c7195d3f959668f883a34c82391a4b188f7a",
        "lunar_symbol": "ZENT"
    },
    {
        "symbol": "WOLF",
        "cmc_id": 28901,
        "chain": "eth",
        "contract": "0x79b1f5e682368ea3786a1518f0f5a0613224f8fa",
        "lunar_symbol": "WOLF"
    },
    {
        "symbol": "ZEN",
        "cmc_id": 1698,
        "chain": None,
        "contract": None,
        "lunar_symbol": "ZEN"
    },
    {
        "symbol": "GEAR",
        "cmc_id": 28352,
        "chain": "eth",
        "contract": "0xba3335588d9403515223f109edc4eb7269a9ab5d",
        "lunar_symbol": "GEAR"
    },
    {
        "symbol": "TOMI",
        "cmc_id": 16834,
        "chain": None,
        "contract": None,
        "lunar_symbol": "TOMI"
    },
    {
        "symbol": "ARTY",
        "cmc_id": 28789,
        "chain": "eth",
        "contract": "0x9b91ef0d78488c5ef4c509b5fac2911b2d67b1af",
        "lunar_symbol": "ARTY"
    },
    {
        "symbol": "URO",
        "cmc_id": 28899,
        "chain": "eth",
        "contract": "0x7b4328c127b85369d9f82ca0503b000d96997463",
        "lunar_symbol": "URO"
    },
    {
        "symbol": "AXOL",
        "cmc_id": 28547,
        "chain": None,
        "contract": None,
        "lunar_symbol": "AXOL"
    },
    {
        "symbol": "AAAHHM",
        "cmc_id": 28876,
        "chain": None,
        "contract": None,
        "lunar_symbol": "AAAHHM"
    },
    {
        "symbol": "ATA",
        "cmc_id": 10188,
        "chain": "eth",
        "contract": "0xa2120b9e674d3fc3875f415a7df52e382f141225",
        "lunar_symbol": "ATA"
    },
    {
        "symbol": "UTK",
        "cmc_id": 28816,
        "chain": "eth",
        "contract": "0xdc9ac3c20d1ed0b540df9b1fedc10039df13f99c",
        "lunar_symbol": "UTK"
    },
    {
        "symbol": "PEAQ",
        "cmc_id": 22766,
        "chain": None,
        "contract": None,
        "lunar_symbol": "PEAQ"
    },
    {
        "symbol": "CELL",
        "cmc_id": 8993,
        "chain": None,
        "contract": None,
        "lunar_symbol": "CELL"
    },
    {
        "symbol": "IDEX",
        "cmc_id": 3928,
        "chain": "eth",
        "contract": "0xB705268213D593B8FD88d3FDEFF93AFF5CbDcfAE",
        "lunar_symbol": "IDEX"
    },
    {
        "symbol": "PUFFER",
        "cmc_id": 28522,
        "chain": "eth",
        "contract": "0xd9A442856C234a39a81a089C06451EBAa4306a72",
        "lunar_symbol": "PUFFER"
    },
    {
        "symbol": "CA",
        "cmc_id": 28713,
        "chain": "eth",
        "contract": "0x9c25E6d3aEf2786a5D0CE8835D71839f7E388889",
        "lunar_symbol": "CA"
    },
    {
        "symbol": "ORDER",
        "cmc_id": 27682,
        "chain": None,
        "contract": None,
        "lunar_symbol": "ORDER"
    },
    {
        "symbol": "CXT",
        "cmc_id": 28635,
        "chain": "eth",
        "contract": "0xE98A72656287275Ab9F82E0B8F4b29E233C3E632",
        "lunar_symbol": "CXT"
    },
    {
        "symbol": "TERMINUS",
        "cmc_id": 28874,
        "chain": "eth",
        "contract": "0x20393be0d2643ed542394E31eF0909cF1437B6ef",
        "lunar_symbol": "TERMINUS"
    },
    {
        "symbol": "SYNT",
        "cmc_id": 28453,
        "chain": "eth",
        "contract": "0x11a068Ea42F9454E591C94eB0f2Ea0c5bC7aAfd7",
        "lunar_symbol": "SYNT"
    },
    {
        "symbol": "ZKJ",
        "cmc_id": 28237,
        "chain": None,
        "contract": None,
        "lunar_symbol": "ZKJ"
    },
    {
        "symbol": "DBR",
        "cmc_id": 28246,
        "chain": "eth",
        "contract": "0xE987c5D2Cfa092Ad9E730055bF8DF81F4842E3c9",
        "lunar_symbol": "DBR"
    },
    {
        "symbol": "FORTH",
        "cmc_id": 9421,
        "chain": "eth",
        "contract": "0x77FbA179C79De5B7653F68b5039Af940AdA60ce0",
        "lunar_symbol": "FORTH"
    },
    {
        "symbol": "FIRO",
        "cmc_id": 1414,
        "chain": None,
        "contract": None,
        "lunar_symbol": "FIRO"
    },
    {
        "symbol": "RNDR",
        "cmc_id": 5690,
        "chain": "eth",
        "contract": "0x6de037ef9ad2725eb40118bb1702ebb27e4aeb24",
        "lunar_symbol": "RNDR"
    },
    {
        "symbol": "INJ",
        "cmc_id": 7226,
        "chain": None,
        "contract": None,
        "lunar_symbol": "INJ"
    },
    {
        "symbol": "GRT",
        "cmc_id": 6719,
        "chain": "eth",
        "contract": "0xc944e90c64b2c07662a292be6244bdf05cda44a7",
        "lunar_symbol": "GRT"
    },
    {
        "symbol": "RLC",
        "cmc_id": 1637,
        "chain": "eth",
        "contract": "0x607F4C5BB672230e8672085532f7e901544a7375",
        "lunar_symbol": "RLC"
    },
    {
        "symbol": "OCEAN",
        "cmc_id": 3911,
        "chain": "eth",
        "contract": "0x967da4048cD07aB37855c090aAF366e4ce1b9F48",
        "lunar_symbol": "OCEAN"
    },
    {
        "symbol": "AGIX",
        "cmc_id": 2424,
        "chain": "eth",
        "contract": "0x5B7533812759B45C2B44C19e320ba2cD2681b542",
        "lunar_symbol": "AGIX"
    },
    {
        "symbol": "FET",
        "cmc_id": 3773,
        "chain": None,
        "contract": None,
        "lunar_symbol": "FET"
    },
    {
        "symbol": "ROSE",
        "cmc_id": 7653,
        "chain": None,
        "contract": None,
        "lunar_symbol": "ROSE"
    },
    {
        "symbol": "CTSI",
        "cmc_id": 5444,
        "chain": "eth",
        "contract": "0x491604c0FDF08347Dd1fa4Ee062a822A5DD06B5D",
        "lunar_symbol": "CTSI"
    },
    {
        "symbol": "CQT",
        "cmc_id": 9467,
        "chain": "eth",
        "contract": "0xD417144312DbF50465b1C641d016962017Ef6240",
        "lunar_symbol": "CQT"
    },
    {
        "symbol": "DAG",
        "cmc_id": 3843,
        "chain": None,
        "contract": None,
        "lunar_symbol": "DAG"
    },
    {
        "symbol": "UOS",
        "cmc_id": 4184,
        "chain": "eth",
        "contract": "0xd13c7342e1ef687c5ad21b27c2b65d772cab5c8c",
        "lunar_symbol": "UOS"
    },
    {
        "symbol": "PYR",
        "cmc_id": 8750,
        "chain": "eth",
        "contract": "0x430EF9263E76DAE63c84292C3409D61c598E9682",
        "lunar_symbol": "PYR"
    },
    {
        "symbol": "ILV",
        "cmc_id": 9399,
        "chain": "eth",
        "contract": "0x767FE9EDC9E0dF98E07454847909b5E959D7ca0E",
        "lunar_symbol": "ILV"
    },
    {
        "symbol": "AXS",
        "cmc_id": 6783,
        "chain": "eth",
        "contract": "0xBB0E17EF65F82Ab018d8EDd776e8DD940327B28b",
        "lunar_symbol": "AXS"
    },
    {
        "symbol": "SAND",
        "cmc_id": 6210,
        "chain": "eth",
        "contract": "0x3845badAde8e6dFF049820680d1F14bD3903a5d0",
        "lunar_symbol": "SAND"
    },
    {
        "symbol": "MANA",
        "cmc_id": 1966,
        "chain": "eth",
        "contract": "0x0F5D2fB29fb7d3CFeE444a200298f468908cC942",
        "lunar_symbol": "MANA"
    },
    {
        "symbol": "ENJ",
        "cmc_id": 2130,
        "chain": "eth",
        "contract": "0xF629cBd94d3791C9250152BD8dfBDF380E2a3B9c",
        "lunar_symbol": "ENJ"
    },
    {
        "symbol": "GALA",
        "cmc_id": 7080,
        "chain": "eth",
        "contract": "0x15D4c048F83bd7e37d49eA4C83a07267Ec4203dA",
        "lunar_symbol": "GALA"
    },
    {
        "symbol": "ALICE",
        "cmc_id": 8766,
        "chain": "eth",
        "contract": "0xAC51066d7bEC65Dc4589368da368b212745d63E8",
        "lunar_symbol": "ALICE"
    },

    # On ajoute ici les 78→102
    {
        "symbol": "APT",
        "cmc_id": 21794,
        "chain": None,
        "contract": None,
        "lunar_symbol": "APT"
    },
    {
        "symbol": "OP",
        "cmc_id": 11840,
        "chain": None,
        "contract": None,
        "lunar_symbol": "OP"
    },
    {
        "symbol": "ARB",
        "cmc_id": 11841,
        "chain": None,
        "contract": None,
        "lunar_symbol": "ARB"
    },
    {
        "symbol": "FTM",
        "cmc_id": 3513,
        "chain": None,
        "contract": None,
        "lunar_symbol": "FTM"
    },
    {
        "symbol": "NEAR",
        "cmc_id": 6535,
        "chain": None,
        "contract": None,
        "lunar_symbol": "NEAR"
    },
    {
        "symbol": "AAVE",
        "cmc_id": 7278,
        "chain": None,
        "contract": None,
        "lunar_symbol": "AAVE"
    },
    {
        "symbol": "XTZ",
        "cmc_id": 2011,
        "chain": None,
        "contract": None,
        "lunar_symbol": "XTZ"
    },
    {
        "symbol": "THETA",
        "cmc_id": 2416,
        "chain": None,
        "contract": None,
        "lunar_symbol": "THETA"
    },
    {
        "symbol": "FLOW",
        "cmc_id": 4558,
        "chain": None,
        "contract": None,
        "lunar_symbol": "FLOW"
    },
    {
        "symbol": "EGLD",  # MultiversX
        "cmc_id": 6892,
        "chain": None,
        "contract": None,
        "lunar_symbol": "EGLD"
    },
    {
        "symbol": "ICP",
        "cmc_id": 8916,
        "chain": None,
        "contract": None,
        "lunar_symbol": "ICP"
    },
    {
        "symbol": "VET",
        "cmc_id": 3077,
        "chain": None,
        "contract": None,
        "lunar_symbol": "VET"
    },
    {
        "symbol": "HBAR",
        "cmc_id": 4642,
        "chain": None,
        "contract": None,
        "lunar_symbol": "HBAR"
    },
    {
        "symbol": "ALGO",
        "cmc_id": 4030,
        "chain": None,
        "contract": None,
        "lunar_symbol": "ALGO"
    },
    {
        "symbol": "STX",
        "cmc_id": 4847,
        "chain": None,
        "contract": None,
        "lunar_symbol": "STX"
    },
    {
        "symbol": "EOS",
        "cmc_id": 1765,
        "chain": None,
        "contract": None,
        "lunar_symbol": "EOS"
    },
    {
        "symbol": "KAVA",
        "cmc_id": 4846,
        "chain": None,
        "contract": None,
        "lunar_symbol": "KAVA"
    },
    {
        "symbol": "ZIL",
        "cmc_id": 2469,
        "chain": None,
        "contract": None,
        "lunar_symbol": "ZIL"
    },
    {
        "symbol": "1INCH",
        "cmc_id": 8104,
        "chain": None,
        "contract": None,
        "lunar_symbol": "1INCH"
    },
    {
        "symbol": "GNO",
        "cmc_id": 1659,
        "chain": None,
        "contract": None,
        "lunar_symbol": "GNO"
    },
    {
        "symbol": "LRC",
        "cmc_id": 1934,
        "chain": None,
        "contract": None,
        "lunar_symbol": "LRC"
    },
    {
        "symbol": "SUSHI",
        "cmc_id": 6758,
        "chain": None,
        "contract": None,
        "lunar_symbol": "SUSHI"
    },
    {
        "symbol": "BAL",
        "cmc_id": 6538,
        "chain": None,
        "contract": None,
        "lunar_symbol": "BAL"
    },
    {
        "symbol": "YFI",
        "cmc_id": 5864,
        "chain": None,
        "contract": None,
        "lunar_symbol": "YFI"
    },
    {
        "symbol": "SRM",
        "cmc_id": 6187,
        "chain": None,
        "contract": None,
        "lunar_symbol": "SRM"
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
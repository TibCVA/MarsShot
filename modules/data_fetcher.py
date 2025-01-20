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

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(CURRENT_DIR, "..", "config.yaml")
OUTPUT_INFERENCE_CSV = os.path.join(CURRENT_DIR, "..", "daily_inference_data.csv")

LOG_FILE = "data_fetcher.log"

if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable (data_fetcher).")

with open(CONFIG_FILE,"r") as f:
    CONFIG = yaml.safe_load(f)

BINANCE_KEY  = CONFIG["binance_api"]["api_key"]
BINANCE_SEC  = CONFIG["binance_api"]["api_secret"]
TOKENS_DAILY = CONFIG["tokens_daily"]
LUNAR_KEY    = CONFIG["lunarcrush"]["api_key"]

LOOKBACK_DAYS= 365
SLEEP_BETWEEN_TOKENS= 2  # plus rapide, ajustez comme vous voulez

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START data_fetcher => daily_inference_data.csv ===")

def fetch_lunar_data_inference(symbol: str, lookback_days=365) -> Optional[pd.DataFrame]:
    # ...
    # => si code !=200 => skip
    # => si error => skip
    # ...
    pass  # voir versions précédentes, on skip ici pour la concision

def main():
    logging.info("=== START data_fetcher => daily_inference_data.csv ===")
    logging.info(f"[DATA_FETCHER] config.yaml => {CONFIG_FILE}")
    logging.info(f"[DATA_FETCHER] TOKENS_DAILY => {TOKENS_DAILY}")

    # Si vous voulez, vous pouvez skip s'il n'y a pas de tokens
    if not TOKENS_DAILY:
        logging.warning("[DATA_FETCHER] tokens_daily est vide => no CSV")
        with open(OUTPUT_INFERENCE_CSV,"w") as fw:
            fw.write("")  # CSV vide
        return

    # fetch BTC, ETH
    # skip si code!=200, on renvoie un df vide => c'est ok
    # ...
    
    all_dfs = []
    for sym in TOKENS_DAILY:
        logging.info(f"[TOKEN] => {sym}")
        df_ = fetch_lunar_data_inference(sym, LOOKBACK_DAYS)
        if df_ is None or df_.empty:
            logging.warning(f"[SKIP {sym}] => data empty or None => partial continue")
            continue
        # calculer indicateurs => skip si error => partial
        # ...
        # Si on a un df final, on l'ajoute à all_dfs
        all_dfs.append(merged_df)

        time.sleep(SLEEP_BETWEEN_TOKENS)

    if not all_dfs:
        logging.warning("[WARN] no data => empty daily_inference_data.csv")
        pd.DataFrame().to_csv(OUTPUT_INFERENCE_CSV, index=False)
        print(f"[WARN] empty => {OUTPUT_INFERENCE_CSV}")
        return

    final_df = pd.concat(all_dfs, ignore_index=True)
    final_df.to_csv(OUTPUT_INFERENCE_CSV, index=False)
    logging.info(f"[DATA_FETCHER] => {OUTPUT_INFERENCE_CSV} with {len(final_df)} lines")
    print(f"[OK] => {OUTPUT_INFERENCE_CSV} with {len(final_df)} lines")

if __name__=="__main__":
    main()

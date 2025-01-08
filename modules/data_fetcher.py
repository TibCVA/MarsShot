#!/usr/bin/env python3
# coding: utf-8

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

CONFIG_FILE = "config.yaml"
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

BINANCE_KEY    = CONFIG["binance_api"]["api_key"]
BINANCE_SECRET = CONFIG["binance_api"]["api_secret"]
symbol_map     = CONFIG["exchanges"]["binance"]["symbol_mapping"]
TOKENS_DAILY   = CONFIG["tokens_daily"]
LOG_FILE       = "data_fetcher.log"
OUTPUT_INFERENCE_CSV = "daily_inference_data.csv"

binance_client = Client(BINANCE_KEY, BINANCE_SECRET)

LUNAR_API_KEY = CONFIG["lunarcrush"]["api_key"]
INTERVAL      = "1y"
SLEEP_BETWEEN_TOKENS = 60

# => Append mode
logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START data_fetcher => daily_inference_data.csv ===")

def fetch_current_price_from_binance(symbol: str):
    # Code inchangé ...
    if symbol not in symbol_map:
        logging.error(f"[BINANCE PRICE] {symbol} absent du symbol_mapping => skip")
        return None
    # etc.

# ... (reste inchangé) ...

def main():
    logging.info("=== START data_fetcher => daily_inference_data.csv ===")
    # Contenu inchangé...
    # Fin main()

if __name__ == "__main__":
    main()
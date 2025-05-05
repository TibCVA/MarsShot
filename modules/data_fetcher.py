#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import logging
import time
import requests
import yaml
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
from indicators import compute_indicators_extended

# Configuration du logging
LOG_FILE = "data_fetcher.log"
logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logging.info("=== START data_fetcher => daily_inference_data.csv ===")

# ----------------------------------------------------------------
# PARSE DES ARGUMENTS
# ----------------------------------------------------------------
parser = argparse.ArgumentParser(description="Data Fetcher for daily_inference_data.csv")
parser.add_argument("--config", help="Path to config YAML", default="")
args = parser.parse_args()

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

if args.config:
    CONFIG_FILE = args.config
    logging.info(f"[DATA_FETCHER] Using custom config => {CONFIG_FILE}")
else:
    CONFIG_FILE = os.path.join(CURRENT_DIR, "..", "config.yaml")
    logging.info(f"[DATA_FETCHER] Using default config => {CONFIG_FILE}")

OUTPUT_INFERENCE_CSV = os.path.join(CURRENT_DIR, "..", "daily_inference_data.csv")

# ----------------------------------------------------------------
# CHARGEMENT DU CONFIG
# ----------------------------------------------------------------
if not os.path.exists(CONFIG_FILE):
    msg = f"[ERREUR] {CONFIG_FILE} introuvable."
    logging.error(msg)
    print(msg)
    sys.exit(1)

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

# ----------------------------------------------------------------
# Détermination de la liste des tokens
# ----------------------------------------------------------------
if "extended_tokens_daily" in CONFIG and CONFIG["extended_tokens_daily"]:
    TOKENS_DAILY = CONFIG["extended_tokens_daily"]
    logging.info(f"[DATA_FETCHER] Found extended_tokens_daily => {TOKENS_DAILY}")
else:
    TOKENS_DAILY = CONFIG.get("tokens_daily", [])
    logging.info(f"[DATA_FETCHER] Using tokens_daily => {TOKENS_DAILY}")

# ----------------------------------------------------------------
# Récupération des clés API et autres constantes
# ----------------------------------------------------------------
LUNAR_API_KEY = CONFIG.get("lunarcrush", {}).get("api_key", "")
BINANCE_KEY   = CONFIG.get("binance_api", {}).get("api_key", "")
BINANCE_SEC   = CONFIG.get("binance_api", {}).get("api_secret", "")

LOOKBACK_DAYS = 365
SLEEP_BETWEEN_TOKENS = 2

# ----------------------------------------------------------------
# Initialisation du client Binance
# ----------------------------------------------------------------
from binance.client import Client as BinanceClient
# Importation des exceptions spécifiques du client Binance
from binance.exceptions import BinanceAPIException, BinanceRequestException
binance_client = BinanceClient(BINANCE_KEY, BINANCE_SEC)

# ----------------------------------------------------------------
# Fonction de récupération des données LunarCrush
# ----------------------------------------------------------------
def fetch_lunar_data_inference(symbol: str, lookback_days: int = 365) -> Optional[pd.DataFrame]:
    """
    Récupère environ lookback_days de données journalières sur LunarCrush pour 'symbol'.
    """
    if not LUNAR_API_KEY:
        logging.warning(f"[{symbol}] No LUNAR_API_KEY => skip.")
        return None

    now_utc = datetime.utcnow()
    end_date = datetime(now_utc.year, now_utc.month, now_utc.day)  # minuit UTC
    start_date = end_date - timedelta(days=lookback_days)
    start_ts = int(start_date.timestamp())
    end_ts = int(end_date.timestamp())

    url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "start": start_ts,
        "end": end_ts
    }
    max_retries = 3
    df_out = None

    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            code = r.status_code
            logging.info(f"[LUNAR INF] {symbol} => code={code}, attempt={attempt+1}/{max_retries}, url={r.url}")

            if code == 200:
                j = r.json()
                data_pts = j.get("data", [])
                if not data_pts:
                    logging.warning(f"[{symbol}] => code=200, data_pts empty => skip token.")
                    return None

                logging.info(f"[{symbol}] => code=200, data_pts.len={len(data_pts)}")

                rows = []
                for pt in data_pts:
                    unix_ts = pt.get("time")
                    if not unix_ts:
                        continue
                    dt_utc = datetime.utcfromtimestamp(unix_ts)
                    o = pt.get("open", 0)
                    c = pt.get("close", 0)
                    hi = pt.get("high", 0)
                    lo = pt.get("low", 0)
                    vol = pt.get("volume_24h", 0)
                    mc = pt.get("market_cap", 0)
                    gal = pt.get("galaxy_score", 0)
                    alt = pt.get("alt_rank", 0)
                    sent = pt.get("sentiment", 0)
                    soc = pt.get("social_dominance", 0)
                    dom = pt.get("market_dominance", 0)
                    rows.append([dt_utc, o, c, hi, lo, vol, mc, gal, alt, sent, soc, dom])

                if not rows:
                    logging.warning(f"[{symbol}] => code=200, but no valid rows => skip.")
                    return None

                df_tmp = pd.DataFrame(rows, columns=[
                    "date", "open", "close", "high", "low", "volume", "market_cap",
                    "galaxy_score", "alt_rank", "sentiment", "social_dominance", "market_dominance"
                ])
                df_out = df_tmp
                break  # Sortie de la boucle de retries

            elif code in [429, 502, 530]:
                wait_s = 30 * (attempt + 1)
                logging.warning(f"[{symbol}] => code={code}, wait {wait_s}s => retry")
                time.sleep(wait_s)

            else:
                logging.warning(f"[{symbol}] => code={code}, skip token.")
                return None

        except Exception as e:
            logging.error(f"[ERROR] fetch {symbol} => {e}", exc_info=True)
            wait_s = 30 * (attempt + 1)
            logging.warning(f"[{symbol}] => exception => wait {wait_s}s => retry")
            time.sleep(wait_s)

    if df_out is None or df_out.empty:
        logging.warning(f"[{symbol}] => final df_out empty => skip.")
        return None

    df_out.sort_values("date", inplace=True)
    df_out.drop_duplicates(subset=["date"], keep="first", inplace=True)
    df_out.reset_index(drop=True, inplace=True)
    return df_out

# ----------------------------------------------------------------
# Nouvelle fonction de vérification d'identité du token
# ----------------------------------------------------------------
def verify_token_identity(symbol: str, binance_client: BinanceClient, lunar_df: pd.DataFrame, tolerance: float = 0.2) -> bool:
    """
    Vérifie que le token identifié par 'symbol' sur Binance correspond aux données de LunarCrush.
    La vérification se fait par la comparaison du prix actuel sur Binance et du dernier prix de clôture dans lunar_df.
    
    Parameters:
      symbol: le symbole du token sur Binance (ex: "BANANA")
      binance_client: instance du client Binance
      lunar_df: DataFrame récupérée depuis LunarCrush pour ce token
      tolerance: tolérance relative acceptée (ex: 0.2 pour 20%)
      
    Returns:
      True si les prix sont cohérents, False sinon.
    """
    try:
        # Construction du ticker Binance en ajoutant "USDC" (ex: "BANANAUSDC")
        binance_symbol = symbol.upper() + "USDC"
        ticker = binance_client.get_symbol_ticker(symbol=binance_symbol)
        binance_price = float(ticker.get("price", 0))
        if binance_price == 0:
            logging.warning(f"[VERIFY] Prix Binance pour {binance_symbol} est 0.")
            return False
    except (BinanceAPIException, BinanceRequestException, ValueError, Exception) as e:
        logging.warning(f"[VERIFY] Erreur pour récupérer le prix Binance de {symbol}: {e}")
        return False

    try:
        lunar_price = float(lunar_df['close'].iloc[-1])
    except Exception as e:
        logging.warning(f"[VERIFY] Erreur pour extraire le prix LunarCrush pour {symbol}: {e}")
        return False

    if abs(binance_price - lunar_price) / binance_price > tolerance:
        logging.warning(f"[VERIFY] Incohérence pour {symbol} : Binance={binance_price} vs LunarCrush={lunar_price}")
        return False

    return True

# ----------------------------------------------------------------
# Traitement principal des tokens
# ----------------------------------------------------------------
all_dfs = []
nb = len(TOKENS_DAILY)
logging.info(f"[DATA_FETCHER] We'll fetch {nb} tokens from the final list now.")

try:
    for i, sym in enumerate(TOKENS_DAILY, start=1):
        logging.info(f"[TOKEN {i}/{nb}] => {sym} => fetch_lunar_data_inference")
        df_ = fetch_lunar_data_inference(sym, lookback_days=LOOKBACK_DAYS)
        if df_ is None or df_.empty:
            logging.warning(f"[SKIP] => {sym}, got None/empty => partial continue.")
            continue

        # Vérification d'identité par comparaison des prix
        if not verify_token_identity(sym, binance_client, df_, tolerance=0.2):
            logging.warning(f"[SKIP] => {sym} ignoré car les données Binance et LunarCrush ne correspondent pas.")
            continue

        logging.info(f"[DEBUG] {sym} => building indicators ... len(df_)={len(df_)}")
        # Conversion en valeurs numériques
        for c_ in [
            "open", "close", "high", "low", "volume", "market_cap",
            "galaxy_score", "alt_rank", "sentiment", "social_dominance", "market_dominance"
        ]:
            if c_ in df_.columns:
                df_[c_] = pd.to_numeric(df_[c_], errors="coerce")
            else:
                df_[c_] = 0.0

        # Calcul des indicateurs techniques
        df_i = compute_indicators_extended(df_)
        df_i.sort_values("date", inplace=True)
        df_i.reset_index(drop=True, inplace=True)

        for cc in ["galaxy_score", "alt_rank", "sentiment", "market_cap", "social_dominance", "market_dominance"]:
            df_i[cc] = df_i[cc].fillna(0)

        df_i["delta_close_1d"] = df_i["close"].pct_change(1)
        df_i["delta_close_3d"] = df_i["close"].pct_change(3)
        df_i["delta_vol_1d"]   = df_i["volume"].pct_change(1)
        df_i["delta_vol_3d"]   = df_i["volume"].pct_change(3)
        df_i["delta_mcap_1d"]  = df_i["market_cap"].pct_change(1)
        df_i["delta_mcap_3d"]  = df_i["market_cap"].pct_change(3)
        df_i["delta_galaxy_score_3d"] = df_i["galaxy_score"].diff(3)
        df_i["delta_alt_rank_3d"] = df_i["alt_rank"].diff(3)
        df_i["delta_social_dom_3d"] = df_i["social_dominance"].diff(3)
        df_i["delta_market_dom_3d"] = df_i["market_dominance"].diff(3)

        merged = df_i.copy()

        # Fusion avec les données BTC
        try:
            df_btc_raw = fetch_lunar_data_inference("BTC", lookback_days=LOOKBACK_DAYS)
            if df_btc_raw is None or df_btc_raw.empty:
                logging.info("[DEBUG] BTC => None/empty => use empty df.")
                df_btc = pd.DataFrame(columns=["date", "close"])
            else:
                df_btc = df_btc_raw
        except Exception as e:
            logging.error(f"[DEBUG] Erreur lors de la récupération de BTC: {e}")
            df_btc = pd.DataFrame(columns=["date", "close"])

        if not df_btc.empty:
            df_btc2 = df_btc[["date", "close"]].rename(columns={"close": "btc_close"})
            merged = pd.merge(merged, df_btc2, on="date", how="left")
            merged["btc_close"] = merged["btc_close"].fillna(0)
            merged["btc_daily_change"] = merged["btc_close"].pct_change(1)
            merged["btc_3d_change"] = merged["btc_close"].pct_change(3)
        else:
            merged["btc_daily_change"] = 0
            merged["btc_3d_change"] = 0

        # Fusion avec les données ETH
        try:
            df_eth_raw = fetch_lunar_data_inference("ETH", lookback_days=LOOKBACK_DAYS)
            if df_eth_raw is None or df_eth_raw.empty:
                logging.info("[DEBUG] ETH => None/empty => use empty df.")
                df_eth = pd.DataFrame(columns=["date", "close"])
            else:
                df_eth = df_eth_raw
        except Exception as e:
            logging.error(f"[DEBUG] Erreur lors de la récupération de ETH: {e}")
            df_eth = pd.DataFrame(columns=["date", "close"])

        if not df_eth.empty:
            df_eth2 = df_eth[["date", "close"]].rename(columns={"close": "eth_close"})
            merged = pd.merge(merged, df_eth2, on="date", how="left")
            merged["eth_close"] = merged["eth_close"].fillna(0)
            merged["eth_daily_change"] = merged["eth_close"].pct_change(1)
            merged["eth_3d_change"] = merged["eth_close"].pct_change(3)
        else:
            merged["eth_daily_change"] = 0
            merged["eth_3d_change"] = 0

        merged.replace([np.inf, -np.inf], np.nan, inplace=True)
        merged["symbol"] = sym

        needed_cols = [
            "date", "symbol",
            "delta_close_1d", "delta_close_3d", "delta_vol_1d", "delta_vol_3d",
            "rsi14", "rsi30", "ma_close_7d", "ma_close_14d", "atr14", "macd_std",
            "stoch_rsi_k", "stoch_rsi_d", "mfi14", "boll_percent_b", "obv",
            "adx", "adx_pos", "adx_neg",
            "btc_daily_change", "btc_3d_change", "eth_daily_change", "eth_3d_change",
            "delta_mcap_1d", "delta_mcap_3d", "galaxy_score", "delta_galaxy_score_3d",
            "alt_rank", "delta_alt_rank_3d", "sentiment",
            "social_dominance", "market_dominance",
            "delta_social_dom_3d", "delta_market_dom_3d"
        ]
        before_len = len(merged)
        merged.dropna(subset=needed_cols, inplace=True)
        after_len = len(merged)
        if after_len <= 0:
            logging.warning(f"[DROPNA] => {sym}, from {before_len} to {after_len} => skip token.")
            continue

        logging.info(f"[TOKEN OK] => {sym}, final shape={merged.shape}")
        all_dfs.append(merged)
        time.sleep(SLEEP_BETWEEN_TOKENS)
except Exception as e:
    logging.error("[FATAL] Exception in main token loop", exc_info=True)
    print(f"[ERROR] data_fetcher fatal exception => {e}")
    sys.exit(1)

if not all_dfs:
    logging.warning("[WARN] no data => empty daily_inference_data.csv")
    pd.DataFrame().to_csv(OUTPUT_INFERENCE_CSV, index=False)
    print(f"[WARN] empty => {OUTPUT_INFERENCE_CSV}")
    sys.exit(0)

df_final = pd.concat(all_dfs, ignore_index=True)
df_final.sort_values(["symbol", "date"], inplace=True)
df_final.reset_index(drop=True, inplace=True)

nb_rows = len(df_final)
logging.info(f"[DATA_FETCHER] => final df_final.shape={df_final.shape}")
df_final.to_csv(OUTPUT_INFERENCE_CSV, index=False)
print(f"[OK] => {OUTPUT_INFERENCE_CSV} with {nb_rows} lines")

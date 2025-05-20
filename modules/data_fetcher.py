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
from typing import Optional, List # AJOUT List pour la fonction calculate_slope

# Assurez-vous que indicators.py est accessible et que compute_indicators_extended est correct
from indicators import compute_indicators_extended 
import ta # AJOUT: Nécessaire pour ta.volatility.BollingerBands et autres indicateurs spécifiques

# Configuration du logging
LOG_FILE = "data_fetcher.log"
logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logging.info("=== START data_fetcher => daily_inference_data.csv (pour model_deuxpointcinq.pkl) ===")

# ----------------------------------------------------------------
# PARSE DES ARGUMENTS (inchangé)
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
# CHARGEMENT DU CONFIG (inchangé)
# ----------------------------------------------------------------
if not os.path.exists(CONFIG_FILE):
    msg = f"[ERREUR] {CONFIG_FILE} introuvable."
    logging.error(msg)
    print(msg)
    sys.exit(1)

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

# ----------------------------------------------------------------
# Détermination de la liste des tokens (inchangé)
# ----------------------------------------------------------------
if "extended_tokens_daily" in CONFIG and CONFIG["extended_tokens_daily"]:
    TOKENS_DAILY = CONFIG["extended_tokens_daily"]
    logging.info(f"[DATA_FETCHER] Found extended_tokens_daily => {len(TOKENS_DAILY)} tokens")
else:
    TOKENS_DAILY = CONFIG.get("tokens_daily", [])
    logging.info(f"[DATA_FETCHER] Using tokens_daily => {len(TOKENS_DAILY)} tokens")

if not TOKENS_DAILY:
    logging.warning("[DATA_FETCHER] La liste des tokens à traiter est vide. Arrêt.")
    # Créer un CSV vide pour éviter des erreurs en aval si c'est le comportement attendu
    pd.DataFrame().to_csv(OUTPUT_INFERENCE_CSV, index=False)
    print("[WARN] Token list is empty. Exiting data_fetcher.")
    sys.exit(0)
    
# ----------------------------------------------------------------
# Récupération des clés API et autres constantes (inchangé)
# ----------------------------------------------------------------
LUNAR_API_KEY = CONFIG.get("lunarcrush", {}).get("api_key", "")
BINANCE_KEY   = CONFIG.get("binance_api", {}).get("api_key", "")
BINANCE_SEC   = CONFIG.get("binance_api", {}).get("api_secret", "")

LOOKBACK_DAYS = 365 # Peut être ajusté si le modèle a besoin de plus/moins d'historique pour les rolling windows
SLEEP_BETWEEN_TOKENS = 2 # Conserver pour la gestion des rate limits

# ----------------------------------------------------------------
# Initialisation du client Binance (inchangé)
# ----------------------------------------------------------------
from binance.client import Client as BinanceClient
from binance.exceptions import BinanceAPIException, BinanceRequestException
binance_client = BinanceClient(BINANCE_KEY, BINANCE_SEC)

# ----------------------------------------------------------------
# Fonction de récupération des données LunarCrush (inchangée)
# ----------------------------------------------------------------
def fetch_lunar_data_inference(symbol: str, lookback_days: int = 365) -> Optional[pd.DataFrame]:
    if not LUNAR_API_KEY:
        logging.warning(f"[{symbol}] No LUNAR_API_KEY => skip.")
        return None
    now_utc = datetime.utcnow()
    end_date = datetime(now_utc.year, now_utc.month, now_utc.day)
    start_date = end_date - timedelta(days=lookback_days)
    start_ts = int(start_date.timestamp())
    end_ts = int(end_date.timestamp())
    url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {"key": LUNAR_API_KEY, "bucket": "day", "start": start_ts, "end": end_ts}
    max_retries = 3; df_out = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            code = r.status_code
            logging.debug(f"[LUNAR INF] {symbol} => code={code}, attempt={attempt+1}/{max_retries}, url={r.url}")
            if code == 200:
                j = r.json(); data_pts = j.get("data", [])
                if not data_pts: logging.warning(f"[{symbol}] => code=200, data_pts empty => skip token."); return None
                rows = []
                for pt in data_pts:
                    unix_ts = pt.get("time");
                    if not unix_ts: continue
                    # Assurer que la date est à minuit UTC pour la cohérence
                    dt_utc = datetime.utcfromtimestamp(unix_ts).replace(hour=0, minute=0, second=0, microsecond=0)
                    rows.append([
                        dt_utc, pt.get("open", np.nan), pt.get("close", np.nan), pt.get("high", np.nan), pt.get("low", np.nan),
                        pt.get("volume_24h", np.nan), pt.get("market_cap", np.nan), pt.get("galaxy_score", np.nan),
                        pt.get("alt_rank", np.nan), pt.get("sentiment", np.nan), pt.get("social_dominance", np.nan),
                        pt.get("market_dominance", np.nan)
                    ])
                if not rows: logging.warning(f"[{symbol}] => code=200, but no valid rows => skip."); return None
                df_tmp = pd.DataFrame(rows, columns=[
                    "date", "open", "close", "high", "low", "volume", "market_cap", "galaxy_score",
                    "alt_rank", "sentiment", "social_dominance", "market_dominance"
                ])
                df_out = df_tmp; break
            elif code in [429, 502, 503, 530]: # AJOUT 503 comme dans build_csv
                wait_s = 20 * (attempt + 1); logging.warning(f"[{symbol}] => code={code}, wait {wait_s}s => retry"); time.sleep(wait_s)
            else: logging.warning(f"[{symbol}] => code={code}, skip token. Response: {r.text[:200]}"); return None
        except requests.exceptions.Timeout: logging.warning(f"[{symbol}] Timeout attempt {attempt+1}, wait {10*(attempt+1)}s"); time.sleep(10*(attempt+1))
        except requests.exceptions.RequestException as e: logging.error(f"[ERROR] fetch {symbol} request exception: {e}", exc_info=False); time.sleep(10*(attempt+1))
        except Exception as e: logging.error(f"[ERROR] fetch {symbol} generic exception: {e}", exc_info=True); time.sleep(10)
    if df_out is None or df_out.empty: logging.warning(f"[{symbol}] => final df_out empty => skip."); return None
    df_out.sort_values("date", inplace=True); df_out.drop_duplicates(subset=["date"], keep="first", inplace=True); df_out.reset_index(drop=True, inplace=True)
    return df_out

# ----------------------------------------------------------------
# Fonction de vérification d'identité du token (inchangée)
# ----------------------------------------------------------------
def verify_token_identity(symbol: str, binance_client: BinanceClient, lunar_df: pd.DataFrame, tolerance: float = 0.2) -> bool:
    if lunar_df is None or lunar_df.empty or 'close' not in lunar_df.columns:
        logging.warning(f"[VERIFY] {symbol}: lunar_df invalide ou 'close' manquante.")
        return False
    lunar_latest_close_series = lunar_df["close"].dropna()
    if lunar_latest_close_series.empty:
        logging.warning(f"[VERIFY] {symbol}: Pas de dernier prix de clôture valide dans lunar_df.")
        return False
    lunar_price = lunar_latest_close_series.iloc[-1]
    try:
        binance_symbol = symbol.upper() + "USDC"
        ticker = binance_client.get_symbol_ticker(symbol=binance_symbol)
        binance_price = float(ticker.get("price", 0))
        if binance_price == 0: logging.warning(f"[VERIFY] Prix Binance pour {binance_symbol} est 0."); return False
    except (BinanceAPIException, BinanceRequestException, ValueError, Exception) as e:
        logging.warning(f"[VERIFY] Erreur pour récupérer le prix Binance de {symbol}: {e}"); return False
    
    price_diff_ratio = abs(binance_price - lunar_price) / binance_price if binance_price != 0 else float('inf')
    is_consistent = price_diff_ratio <= tolerance
    if not is_consistent:
        logging.warning(f"[VERIFY] Incohérence pour {symbol}: Binance={binance_price:.4f} vs LunarCrush={lunar_price:.4f} (Ratio: {price_diff_ratio:.4f})")
    return is_consistent

# AJOUT: Fonction calculate_slope (nécessaire pour obv_slope_5d, ma_slope_7d, ma_slope_14d)
def calculate_slope(series: pd.Series, window: int = 5) -> pd.Series:
    if not isinstance(series, pd.Series):
        logging.debug(f"calculate_slope attend une pd.Series, a reçu {type(series)}")
        return pd.Series(np.nan, index=getattr(series, 'index', None))
    if series.empty or len(series) < window:
        return pd.Series(np.nan, index=series.index)
    
    # Remplacer les infinis par NaN avant le calcul de la pente
    series_cleaned = series.replace([np.inf, -np.inf], np.nan)

    slopes = np.full(len(series_cleaned), np.nan)
    x_coords = np.arange(window, dtype=float) # x pour la régression
    
    # Utiliser rolling apply pour une approche plus vectorisée si possible,
    # mais polyfit sur des fenêtres est souvent fait avec une boucle.
    # La boucle est conservée pour correspondre à build_csv_v4.py
    for i in range(len(series_cleaned) - window + 1):
        y_window_raw = series_cleaned.iloc[i : i + window].values
        try:
            y_window = y_window_raw.astype(float)
        except ValueError:
            logging.debug(f"calculate_slope: Impossible de convertir y_window en float pour la fenêtre commençant à {i}.")
            continue # Passer à la fenêtre suivante
        
        finite_mask = np.isfinite(y_window) # Masque pour les valeurs non-NaN, non-inf
        
        if finite_mask.sum() < 2:  # Besoin d'au moins 2 points valides pour une pente
            continue
            
        try:
            # Appliquer polyfit uniquement sur les points valides
            slope_val, _ = np.polyfit(x_coords[finite_mask], y_window[finite_mask], 1)
            slopes[i + window - 1] = slope_val # Assigner à la fin de la fenêtre
        except (np.linalg.LinAlgError, ValueError) as e_poly:
            logging.debug(f"calculate_slope: Erreur polyfit pour la fenêtre commençant à {i} pour la series: {e_poly}")
            continue
    return pd.Series(slopes, index=series.index)

# ----------------------------------------------------------------
# Traitement principal des tokens
# ----------------------------------------------------------------
all_dfs = []
nb_tokens_total = len(TOKENS_DAILY)
logging.info(f"[DATA_FETCHER] Début du traitement de {nb_tokens_total} tokens.")

# Récupération des données BTC et ETH en premier (inchangé dans la structure)
df_btc_full = fetch_lunar_data_inference("BTC", lookback_days=LOOKBACK_DAYS + 60) # +60 pour les rolling windows
df_eth_full = fetch_lunar_data_inference("ETH", lookback_days=LOOKBACK_DAYS + 60)

# Prétraitement des données BTC
df_btc_processed = pd.DataFrame()
if df_btc_full is not None and not df_btc_full.empty:
    df_btc_temp = df_btc_full.copy()
    for col in ["open", "high", "low", "close", "volume"]: # S'assurer que les colonnes OHLCV sont numériques
        df_btc_temp[col] = pd.to_numeric(df_btc_temp[col], errors='coerce')
    df_btc_temp.dropna(subset=["close"], inplace=True) # Au moins 'close' doit être valide

    df_btc_processed['date'] = df_btc_temp['date']
    df_btc_processed['btc_close'] = df_btc_temp['close']
    df_btc_processed['btc_daily_change'] = df_btc_temp['close'].pct_change(1)
    df_btc_processed['btc_3d_change'] = df_btc_temp['close'].pct_change(3)
    if all(c in df_btc_temp.columns for c in ["high", "low", "close"]):
        btc_atr_indicator = ta.volatility.AverageTrueRange(high=df_btc_temp["high"], low=df_btc_temp["low"], close=df_btc_temp["close"], window=14, fillna=False)
        df_btc_processed["btc_atr_raw"] = btc_atr_indicator.average_true_range()
        df_btc_processed["btc_atr_norm"] = df_btc_processed["btc_atr_raw"] / df_btc_temp["close"].replace(0, np.nan)
        btc_rsi_indicator = ta.momentum.RSIIndicator(close=df_btc_temp["close"], window=14, fillna=False)
        df_btc_processed["btc_rsi"] = btc_rsi_indicator.rsi()
    else:
        df_btc_processed["btc_atr_norm"] = np.nan
        df_btc_processed["btc_rsi"] = np.nan
else:
    logging.warning("[DATA_FETCHER] Données BTC non disponibles ou vides.")

# Prétraitement des données ETH
df_eth_processed = pd.DataFrame()
if df_eth_full is not None and not df_eth_full.empty:
    df_eth_temp = df_eth_full.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df_eth_temp[col] = pd.to_numeric(df_eth_temp[col], errors='coerce')
    df_eth_temp.dropna(subset=["close"], inplace=True)

    df_eth_processed['date'] = df_eth_temp['date']
    df_eth_processed['eth_close'] = df_eth_temp['close']
    df_eth_processed['eth_daily_change'] = df_eth_temp['close'].pct_change(1)
    df_eth_processed['eth_3d_change'] = df_eth_temp['close'].pct_change(3)
    if all(c in df_eth_temp.columns for c in ["high", "low", "close"]):
        eth_atr_indicator = ta.volatility.AverageTrueRange(high=df_eth_temp["high"], low=df_eth_temp["low"], close=df_eth_temp["close"], window=14, fillna=False)
        df_eth_processed["eth_atr_raw"] = eth_atr_indicator.average_true_range()
        df_eth_processed["eth_atr_norm"] = df_eth_processed["eth_atr_raw"] / df_eth_temp["close"].replace(0, np.nan)
        eth_rsi_indicator = ta.momentum.RSIIndicator(close=df_eth_temp["close"], window=14, fillna=False)
        df_eth_processed["eth_rsi"] = eth_rsi_indicator.rsi()
    else:
        df_eth_processed["eth_atr_norm"] = np.nan
        df_eth_processed["eth_rsi"] = np.nan
else:
    logging.warning("[DATA_FETCHER] Données ETH non disponibles ou vides.")


try:
    for i, sym in enumerate(TOKENS_DAILY, start=1):
        logging.info(f"[TOKEN {i}/{nb_tokens_total}] => {sym} => fetch_lunar_data_inference")
        df_raw_token = fetch_lunar_data_inference(sym, lookback_days=LOOKBACK_DAYS)
        if df_raw_token is None or df_raw_token.empty or len(df_raw_token) < 60: # Seuil de 60 jours comme dans build_csv
            logging.warning(f"[SKIP] => {sym}, données LunarCrush insuffisantes ou vides (lignes: {len(df_raw_token) if df_raw_token is not None else 0}).")
            time.sleep(0.2)
            continue

        if not verify_token_identity(sym, binance_client, df_raw_token, tolerance=0.2):
            logging.warning(f"[SKIP] => {sym} ignoré, vérification d'identité Binance/LunarCrush échouée.")
            time.sleep(0.2)
            continue

        # Conversion en valeurs numériques et remplissage initial (similaire à build_csv)
        df_token_processed = df_raw_token.copy()
        numeric_cols_lunar = ["open","high","low","close","volume","market_cap","galaxy_score","alt_rank","sentiment","social_dominance","market_dominance"]
        for col in numeric_cols_lunar:
            if col in df_token_processed.columns:
                df_token_processed[col] = pd.to_numeric(df_token_processed[col], errors='coerce')
            else: # Si une colonne Lunar manque, l'ajouter avec NaN pour la cohérence
                df_token_processed[col] = np.nan
                logging.warning(f"Colonne Lunar '{col}' manquante pour {sym}, initialisée à NaN.")

        # Remplissage des prix OHLC (ffill puis bfill pour minimiser les NaN)
        price_cols = ["open", "high", "low", "close"]
        for pcol in price_cols:
            df_token_processed[pcol] = df_token_processed[pcol].replace(0, np.nan).ffill().bfill()
        
        # Remplissage volume et autres scores Lunar (ffill puis bfill)
        df_token_processed["volume"] = df_token_processed["volume"].fillna(0) # Volume à 0 si NaN
        lunar_score_cols = ["market_cap", "galaxy_score", "alt_rank", "sentiment", "social_dominance", "market_dominance"]
        for lcol in lunar_score_cols:
            df_token_processed[lcol] = df_token_processed[lcol].ffill().bfill()

        # Si après remplissage, des colonnes de prix essentielles sont toujours NaN, skipper
        if df_token_processed[price_cols].isnull().any().any():
            logging.warning(f"[SKIP] => {sym}, données OHLCV manquantes persistantes après remplissage.")
            continue
        
        # Calcul des indicateurs techniques via compute_indicators_extended
        # compute_indicators_extended attend un df avec 'date' en colonne, pas en index.
        df_with_indicators = compute_indicators_extended(df_token_processed.copy()) # .copy() pour éviter SettingWithCopyWarning

        # --- Calcul des features spécifiques à model_deuxpointcinq.pkl ---
        # Les features de compute_indicators_extended sont déjà dans df_with_indicators:
        # rsi14, rsi30, atr14, macd_std, stoch_rsi_k, stoch_rsi_d, mfi14, boll_percent_b, obv, adx, adx_pos, adx_neg, ma_close_7d, ma_close_14d

        # Deltas (certains étaient déjà dans votre version originale de data_fetcher)
        df_with_indicators["delta_close_1d"] = df_with_indicators["close"].pct_change(1)
        df_with_indicators["delta_close_3d"] = df_with_indicators["close"].pct_change(3)
        df_with_indicators["delta_vol_1d"]   = df_with_indicators["volume"].pct_change(1)
        df_with_indicators["delta_vol_3d"]   = df_with_indicators["volume"].pct_change(3)
        df_with_indicators["delta_mcap_1d"]  = df_with_indicators["market_cap"].pct_change(1)
        df_with_indicators["delta_mcap_3d"]  = df_with_indicators["market_cap"].pct_change(3)
        
        df_with_indicators["delta_galaxy_score_1d"] = df_with_indicators["galaxy_score"].diff(1)
        # delta_galaxy_score_3d est retiré du modèle final
        
        df_with_indicators["delta_alt_rank_3d"] = df_with_indicators["alt_rank"].diff(3)
        df_with_indicators["delta_social_dom_1d"] = df_with_indicators["social_dominance"].diff(1)
        df_with_indicators["delta_social_dom_3d"] = df_with_indicators["social_dominance"].diff(3)
        df_with_indicators["delta_market_dom_1d"] = df_with_indicators["market_dominance"].diff(1)
        df_with_indicators["delta_market_dom_3d"] = df_with_indicators["market_dominance"].diff(3)

        # Transformations
        df_with_indicators["atr14_norm"] = df_with_indicators["atr14"] / df_with_indicators["close"].replace(0, np.nan)
        df_with_indicators["price_change_norm_atr1d"] = df_with_indicators["close"].diff(1) / df_with_indicators["atr14"].shift(1).replace(0, np.nan)
        df_with_indicators["rsi14_roc3d"] = df_with_indicators["rsi14"].diff(3)
        
        df_with_indicators["ma_slope_7d"] = calculate_slope(df_with_indicators["ma_close_7d"], window=5)
        df_with_indicators["ma_slope_14d"] = calculate_slope(df_with_indicators["ma_close_14d"], window=5)

        if 'close' in df_with_indicators.columns and not df_with_indicators['close'].empty:
            boll_obj_token = ta.volatility.BollingerBands(close=df_with_indicators["close"], window=20, window_dev=2, fillna=False)
            mavg_safe = boll_obj_token.bollinger_mavg().replace(0, np.nan)
            df_with_indicators["boll_width_norm"] = (boll_obj_token.bollinger_hband() - boll_obj_token.bollinger_lband()) / mavg_safe
        else:
            df_with_indicators["boll_width_norm"] = np.nan

        df_with_indicators["volume_norm_ma20"] = df_with_indicators["volume"] / df_with_indicators["volume"].rolling(window=20, min_periods=1).mean().replace(0, np.nan)
        df_with_indicators["galaxy_score_norm_ma7"] = df_with_indicators["galaxy_score"] / df_with_indicators["galaxy_score"].rolling(window=7, min_periods=1).mean().replace(0, np.nan)
        df_with_indicators["sentiment_ma_diff7"] = df_with_indicators["sentiment"] - df_with_indicators["sentiment"].rolling(window=7, min_periods=1).mean()
        
        df_with_indicators["alt_rank_roc1d"] = df_with_indicators["alt_rank"].diff(1)
        df_with_indicators["alt_rank_roc7d"] = df_with_indicators["alt_rank"].diff(7)

        # Nouvelle feature v4
        df_with_indicators["obv_slope_5d"] = calculate_slope(df_with_indicators["obv"], window=5)
        
        # --- Fin des calculs spécifiques ---

        # Merge avec les données BTC et ETH
        merged_df = df_with_indicators.copy()
        if not df_btc_processed.empty:
            merged_df = pd.merge(merged_df, df_btc_processed.drop(columns=['btc_close'], errors='ignore'), on="date", how="left")
        else: # Initialiser les colonnes BTC si df_btc_processed est vide
            for col in ["btc_daily_change", "btc_3d_change", "btc_atr_norm", "btc_rsi"]: merged_df[col] = 0.0

        if not df_eth_processed.empty:
            merged_df = pd.merge(merged_df, df_eth_processed.drop(columns=['eth_close'], errors='ignore'), on="date", how="left")
        else: # Initialiser les colonnes ETH si df_eth_processed est vide
            for col in ["eth_daily_change", "eth_3d_change", "eth_atr_norm", "eth_rsi"]: merged_df[col] = 0.0
        
        # Remplir les NaN pour les colonnes BTC/ETH qui pourraient apparaître après le merge si les dates ne correspondent pas parfaitement
        # ou si les données BTC/ETH étaient incomplètes.
        btc_eth_cols_to_fill = ["btc_daily_change", "btc_3d_change", "btc_atr_norm", "btc_rsi",
                                "eth_daily_change", "eth_3d_change", "eth_atr_norm", "eth_rsi"]
        for col in btc_eth_cols_to_fill:
            if col in merged_df.columns:
                merged_df[col] = merged_df[col].fillna(0) # Remplir avec 0 comme dans votre version originale
            else: # Si la colonne n'a pas été créée (ex: df_btc_processed vide)
                merged_df[col] = 0.0


        # Calcul des features relatives au marché (après merge BTC/ETH)
        if "rsi14" in merged_df.columns and "btc_rsi" in merged_df.columns:
            merged_df["rsi_vs_btc"] = merged_df["rsi14"] - merged_df["btc_rsi"]
        else:
            merged_df["rsi_vs_btc"] = np.nan 

        if "atr14_norm" in merged_df.columns and "btc_atr_norm" in merged_df.columns:
            merged_df["atr_norm_vs_btc"] = merged_df["atr14_norm"] - merged_df["btc_atr_norm"]
        else:
            merged_df["atr_norm_vs_btc"] = np.nan

        if all(x in merged_df.columns for x in ["atr14_norm", "btc_atr_norm", "eth_atr_norm"]):
            avg_market_atr_norm = (merged_df["btc_atr_norm"].fillna(0) + merged_df["eth_atr_norm"].fillna(0)) / 2
            merged_df["volatility_ratio_vs_market"] = merged_df["atr14_norm"] / avg_market_atr_norm.replace(0, np.nan)
        else:
            merged_df["volatility_ratio_vs_market"] = np.nan
            logging.debug(f"Colonnes manquantes pour 'volatility_ratio_vs_market' pour {sym}.")

        merged_df.replace([np.inf, -np.inf], np.nan, inplace=True) # Remplacer infinis par NaN
        merged_df["symbol"] = sym # Ajouter la colonne symbol

        # Définition de la liste des features finales attendues par le modèle pour le dropna
        # Cette liste doit correspondre à COLUMNS_ORDER de ml_decision.py
        final_model_features = sorted([
            "rsi14", "rsi30", "atr14", "macd_std", "stoch_rsi_k", "stoch_rsi_d", "mfi14", "boll_percent_b", "obv", "adx", "adx_pos", "adx_neg", "ma_close_7d", "ma_close_14d",
            "galaxy_score", "alt_rank", "sentiment", "social_dominance", "market_dominance",
            "delta_close_1d", "delta_close_3d", "delta_vol_1d", "delta_vol_3d", "delta_mcap_1d", "delta_mcap_3d",
            "delta_galaxy_score_1d", "delta_alt_rank_3d", "delta_social_dom_1d", "delta_social_dom_3d",
            "delta_market_dom_1d", "delta_market_dom_3d",
            "atr14_norm", "price_change_norm_atr1d", "rsi14_roc3d",
            "ma_slope_7d", "ma_slope_14d", "boll_width_norm", "volume_norm_ma20",
            "galaxy_score_norm_ma7", "sentiment_ma_diff7", "alt_rank_roc1d", "alt_rank_roc7d",
            "btc_daily_change", "btc_3d_change", "eth_daily_change", "eth_3d_change",
            "btc_atr_norm", "btc_rsi", "eth_atr_norm", "eth_rsi",
            "rsi_vs_btc", "atr_norm_vs_btc", "volatility_ratio_vs_market", "obv_slope_5d"
        ])
        
        # S'assurer que toutes les features nécessaires sont présentes avant dropna
        missing_features_for_dropna = [f for f in final_model_features if f not in merged_df.columns]
        if missing_features_for_dropna:
            logging.warning(f"[SKIP] => {sym}, features manquantes avant dropna: {missing_features_for_dropna}")
            continue # Ne pas ajouter ce token si des features essentielles manquent

        # Dropna basé sur les features du modèle uniquement
        rows_before_dropna = len(merged_df)
        merged_df.dropna(subset=final_model_features, inplace=True)
        rows_after_dropna = len(merged_df)
        
        if rows_after_dropna < rows_before_dropna:
            logging.debug(f"Pour {sym}, {rows_before_dropna - rows_after_dropna} lignes supprimées par dropna sur les features du modèle.")

        if merged_df.empty:
            logging.warning(f"[SKIP] => {sym}, dataframe vide après dropna sur les features du modèle.")
            continue

        logging.info(f"[TOKEN OK] => {sym}, final shape={merged_df.shape}")
        all_dfs.append(merged_df)
        time.sleep(SLEEP_BETWEEN_TOKENS) # Respecter les rate limits

except KeyboardInterrupt:
    logging.warning("[DATA_FETCHER] Processus interrompu par l'utilisateur (KeyboardInterrupt).")
    print("\n[WARN] Data fetching interrompu.")
    # Sauvegarder ce qui a été collecté jusqu'à présent si nécessaire
    if all_dfs:
        logging.info("Sauvegarde des données collectées avant interruption...")
    # Le sys.exit sera géré dans le bloc finally global
    raise # Propage l'exception pour que le bloc finally global puisse la gérer

except Exception as e:
    logging.error(f"[FATAL] Exception in main token loop: {e}", exc_info=True)
    print(f"[ERROR] data_fetcher fatal exception => {e}")
    # Pas de sys.exit ici, laisser le bloc finally global gérer

finally:
    if not all_dfs:
        logging.warning("[WARN] Aucune donnée collectée pour aucun token. Export d'un CSV vide.")
        # S'assurer que le CSV est créé même s'il est vide pour éviter des erreurs en aval
        # Définir les colonnes attendues pour un CSV vide basé sur les features + 'date' + 'symbol'
        empty_csv_cols = ["date", "symbol"] + sorted([
            "rsi14", "rsi30", "atr14", "macd_std", "stoch_rsi_k", "stoch_rsi_d", "mfi14", "boll_percent_b", "obv", "adx", "adx_pos", "adx_neg", "ma_close_7d", "ma_close_14d",
            "galaxy_score", "alt_rank", "sentiment", "social_dominance", "market_dominance", "market_cap", "volume", "close", "high", "low", "open",
            "delta_close_1d", "delta_close_3d", "delta_vol_1d", "delta_vol_3d", "delta_mcap_1d", "delta_mcap_3d",
            "delta_galaxy_score_1d", "delta_alt_rank_3d", "delta_social_dom_1d", "delta_social_dom_3d",
            "delta_market_dom_1d", "delta_market_dom_3d",
            "atr14_norm", "price_change_norm_atr1d", "rsi14_roc3d",
            "ma_slope_7d", "ma_slope_14d", "boll_width_norm", "volume_norm_ma20",
            "galaxy_score_norm_ma7", "sentiment_ma_diff7", "alt_rank_roc1d", "alt_rank_roc7d",
            "btc_daily_change", "btc_3d_change", "eth_daily_change", "eth_3d_change",
            "btc_atr_norm", "btc_rsi", "eth_atr_norm", "eth_rsi",
            "rsi_vs_btc", "atr_norm_vs_btc", "volatility_ratio_vs_market", "obv_slope_5d"
        ])
        pd.DataFrame(columns=empty_csv_cols).to_csv(OUTPUT_INFERENCE_CSV, index=False)
        print(f"[WARN] empty daily_inference_data.csv created at {OUTPUT_INFERENCE_CSV}")
        if 'e' in locals() and isinstance(e, Exception) and not isinstance(e, KeyboardInterrupt): # Si une exception autre que KeyboardInterrupt a causé la sortie
             sys.exit(1) # Sortir avec un code d'erreur
        elif 'e' in locals() and isinstance(e, KeyboardInterrupt):
             sys.exit(130) # Code de sortie standard pour Ctrl+C
        else: # Si la boucle s'est terminée normalement mais all_dfs est vide
             sys.exit(0)


    df_final = pd.concat(all_dfs, ignore_index=True)
    
    # S'assurer que toutes les colonnes attendues par ml_decision sont présentes,
    # même si certaines sont entièrement NaN pour certains tokens (le dropna de ml_decision s'en chargera).
    # Colonnes de base + features du modèle
    expected_output_columns = ["date", "symbol"] + sorted([
        "rsi14", "rsi30", "atr14", "macd_std", "stoch_rsi_k", "stoch_rsi_d", "mfi14", "boll_percent_b", "obv", "adx", "adx_pos", "adx_neg", "ma_close_7d", "ma_close_14d",
        # Inclure les colonnes brutes utilisées pour calculer les features si elles ne sont pas déjà dans la liste des features
        "open", "high", "low", "close", "volume", "market_cap", 
        "galaxy_score", "alt_rank", "sentiment", "social_dominance", "market_dominance",
        "delta_close_1d", "delta_close_3d", "delta_vol_1d", "delta_vol_3d", "delta_mcap_1d", "delta_mcap_3d",
        "delta_galaxy_score_1d", "delta_alt_rank_3d", "delta_social_dom_1d", "delta_social_dom_3d",
        "delta_market_dom_1d", "delta_market_dom_3d",
        "atr14_norm", "price_change_norm_atr1d", "rsi14_roc3d",
        "ma_slope_7d", "ma_slope_14d", "boll_width_norm", "volume_norm_ma20",
        "galaxy_score_norm_ma7", "sentiment_ma_diff7", "alt_rank_roc1d", "alt_rank_roc7d",
        "btc_daily_change", "btc_3d_change", "eth_daily_change", "eth_3d_change",
        "btc_atr_norm", "btc_rsi", "eth_atr_norm", "eth_rsi",
        "rsi_vs_btc", "atr_norm_vs_btc", "volatility_ratio_vs_market", "obv_slope_5d"
    ])
    expected_output_columns = pd.Series(expected_output_columns).drop_duplicates().tolist()


    for col in expected_output_columns:
        if col not in df_final.columns:
            logging.warning(f"La colonne attendue '{col}' n'est pas dans df_final. Ajout avec NaN.")
            df_final[col] = np.nan # Ajouter les colonnes manquantes avec NaN

    # Réorganiser les colonnes pour la lisibilité du CSV (optionnel, mais bon pour le débogage)
    # Mettre 'date' et 'symbol' en premier, puis les features triées.
    cols_for_export = ["date", "symbol"] + [col for col in expected_output_columns if col not in ["date", "symbol"]]
    df_final = df_final[cols_for_export] # S'assurer que seules ces colonnes sont exportées et dans cet ordre

    df_final.sort_values(["symbol", "date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    nb_rows = len(df_final)
    logging.info(f"[DATA_FETCHER] => final df_final.shape={df_final.shape}")
    try:
        df_final.to_csv(OUTPUT_INFERENCE_CSV, index=False)
        print(f"[OK] => {OUTPUT_INFERENCE_CSV} with {nb_rows} lines and {len(df_final.columns)} columns.")
    except Exception as e_csv:
        logging.error(f"[ERROR] Failed to write final CSV to {OUTPUT_INFERENCE_CSV}: {e_csv}", exc_info=True)
        print(f"[ERROR] Failed to write final CSV: {e_csv}")
        sys.exit(1)
    
    # Gérer la sortie en cas d'interruption clavier après la sauvegarde
    if 'e' in locals() and isinstance(e, KeyboardInterrupt):
        sys.exit(130)
    sys.exit(0)

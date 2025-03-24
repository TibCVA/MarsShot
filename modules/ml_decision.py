#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import numpy as np
import pandas as pd
import joblib
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_FILE        = os.path.join(CURRENT_DIR, "..", "model.pkl")
INPUT_CSV         = os.path.join(CURRENT_DIR, "..", "daily_inference_data.csv")
OUTPUT_PROBA_CSV  = os.path.join(CURRENT_DIR, "..", "daily_probabilities.csv")
LOG_FILE          = "ml_decision.log"

COLUMNS_ORDER = [
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

logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START ml_decision (BATCH) ===")

def main():
    logging.info("[ML_DECISION] Checking model file => %s", MODEL_FILE)
    if not os.path.exists(MODEL_FILE):
        logging.error(f"[ERROR] {MODEL_FILE} introuvable => impossible de prédire.")
        print(f"[ERROR] {MODEL_FILE} introuvable => skip.")
        return

    logging.info("[ML_DECISION] Checking input CSV => %s", INPUT_CSV)
    if not os.path.exists(INPUT_CSV):
        logging.error(f"[ERROR] {INPUT_CSV} introuvable => impossible de prédire.")
        print(f"[ERROR] {INPUT_CSV} introuvable => skip.")
        return

    df = pd.read_csv(INPUT_CSV)
    if df.empty:
        logging.warning("[WARN] daily_inference_data.csv est vide => aucune prédiction possible.")
        print("[WARN] empty daily_inference_data.csv => skip.")
        return

    needed_cols = COLUMNS_ORDER + ["symbol", "date"]
    missing = [col for col in needed_cols if col not in df.columns]
    if missing:
        logging.error(f"[ERROR] Colonnes manquantes => {missing}")
        print(f"[ERROR] missing cols => {missing}")
        return

    # Conversion de "date" en datetime et filtrage sur les données complètes (bucket J-1)
    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    today = datetime.utcnow().date()
    df = df[df["date_dt"].dt.date < today]
    if df.empty:
        logging.error("[ERROR] Aucune donnée complète (J-1 ou antérieure) disponible.")
        print("[ERROR] Pas de données pour J-1 ou antérieures.")
        return

    # Suppression des lignes où les features sont NaN
    before = len(df)
    df.dropna(subset=COLUMNS_ORDER, inplace=True)
    after = len(df)
    if after < before:
        logging.warning(f"[WARN] Drop {before - after} lignes => NaN dans features")
    if df.empty:
        logging.warning("[WARN] plus aucune ligne => skip.")
        print("[WARN] no data => skip.")
        return

    # Chargement du modèle
    try:
        loaded = joblib.load(MODEL_FILE)
        logging.info(f"[ML_DECISION] Modèle chargé. Type: {type(loaded)}")
        
        # Cas 1: Modèle Original (tuple)
        if isinstance(loaded, tuple) and len(loaded) == 2:
            model, custom_threshold = loaded
            logging.info(f"[ML_DECISION] Modèle détecté comme tuple (original) + threshold={custom_threshold}")
        
        # Cas 2: Modèle Business/Business3 (dictionnaire avec pipeline)
        elif isinstance(loaded, dict) and "pipeline" in loaded:
            model = loaded["pipeline"]
            # Récupération des seuils (pour information)
            buy_threshold = loaded.get("thresholds", {}).get("high_precision", None)
            sell_threshold = loaded.get("thresholds", {}).get("profit_taking", None)
            logging.info(f"[ML_DECISION] Modèle détecté comme dictionnaire (business) avec seuils: achat={buy_threshold}, vente={sell_threshold}")
            custom_threshold = buy_threshold
        
        # Cas 3: Pipeline direct
        elif hasattr(loaded, 'predict_proba') or hasattr(loaded, 'named_steps'):
            model = loaded
            custom_threshold = None
            logging.info(f"[ML_DECISION] Modèle détecté comme pipeline direct")
        
        # Cas non géré
        else:
            logging.error(f"[ML_DECISION] Structure de modèle non reconnue: {type(loaded)}")
            if isinstance(loaded, dict):
                logging.error(f"[ML_DECISION] Clés disponibles: {list(loaded.keys())}")
            print("[ERROR] Structure de modèle non reconnue")
            return
        
        # Vérification du pipeline
        if not hasattr(model, 'predict_proba'):
            logging.error("[ML_DECISION] Le modèle n'a pas de méthode predict_proba")
            print("[ERROR] Le modèle ne peut pas faire de prédictions")
            return
            
    except Exception as e:
        logging.error(f"[ERROR] Erreur lors du chargement du modèle: {str(e)}")
        print(f"[ERROR] Erreur lors du chargement du modèle: {str(e)}")
        return

    # Prédiction
    try:
        X = df[COLUMNS_ORDER].values.astype(float)
        probs = model.predict_proba(X)[:, 1]
        df["prob"] = probs  # On ajoute la probabilité à chaque ligne
        
        # Groupement par token pour obtenir uniquement la dernière ligne (la plus récente) par token
        df_last_per_token = df.sort_values("date_dt").groupby("symbol", as_index=False).tail(1)
        df_out = df_last_per_token[["symbol", "prob"]].copy()
        df_out.sort_values("symbol", inplace=True)
        df_out.reset_index(drop=True, inplace=True)
        
        df_out.to_csv(OUTPUT_PROBA_CSV, index=False)
        logging.info(f"[OK] => daily_probabilities.csv => {len(df_out)} tokens.")
        print(f"[OK] => daily_probabilities.csv => {len(df_out)} tokens.")
        
        # Enregistrement dans le log uniquement de la dernière probabilité (du bucket J-1) pour chaque token
        logging.info("Probabilités utilisées (bucket J-1) par token:")
        for idx, row in df_out.iterrows():
            logging.info(f"Token: {row['symbol']} - Probabilité (J-1): {row['prob']:.4f}")
            
    except Exception as e:
        logging.error(f"[ERROR] Erreur lors des prédictions: {str(e)}")
        print(f"[ERROR] Erreur lors des prédictions: {str(e)}")
        return

    logging.info("=== END ml_decision (BATCH) ===")

if __name__=="__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import numpy as np
import pandas as pd
import joblib
from datetime import datetime
import sys 

logger = logging.getLogger("ml_decision_logic")
if not logger.hasHandlers():
    _handler_ml = logging.StreamHandler(sys.stderr)
    _formatter_ml = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s")
    _handler_ml.setFormatter(_formatter_ml)
    logger.addHandler(_handler_ml)
    logger.setLevel(logging.INFO)
    logger.propagate = False

CURRENT_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT_ML = os.path.join(CURRENT_MODULE_DIR, "..")

MODEL_FILE        = os.path.join(PROJECT_ROOT_ML, "model_deuxpointcinq.pkl")
INPUT_CSV         = os.path.join(PROJECT_ROOT_ML, "daily_inference_data.csv")
OUTPUT_PROBA_CSV  = os.path.join(PROJECT_ROOT_ML, "daily_probabilities.csv")

COLUMNS_ORDER = sorted([
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

def main_ml_decision():
    logger.info(f"=== START ml_decision (BATCH) using {os.path.basename(MODEL_FILE)} ===")
    logger.info(f"Vérification du fichier modèle => {MODEL_FILE}")
    if not os.path.exists(MODEL_FILE):
        logger.error(f"Fichier modèle {MODEL_FILE} introuvable."); print(f"[ERREUR_ML] {MODEL_FILE} introuvable."); return 1
    logger.info(f"Vérification du fichier CSV d'entrée => {INPUT_CSV}")
    if not os.path.exists(INPUT_CSV):
        logger.error(f"Fichier d'entrée {INPUT_CSV} introuvable."); print(f"[ERREUR_ML] {INPUT_CSV} introuvable."); return 1
    try:
        df = pd.read_csv(INPUT_CSV)
    except Exception as e:
        logger.error(f"Échec lecture {INPUT_CSV}: {e}", exc_info=True); print(f"[ERREUR_ML] Échec lecture {INPUT_CSV}: {e}"); return 1
    if df.empty:
        logger.warning(f"{os.path.basename(INPUT_CSV)} est vide. Aucune prédiction.");
        try:
            pd.DataFrame(columns=["symbol", "prob"]).to_csv(OUTPUT_PROBA_CSV, index=False)
            logger.info(f"Fichier probabilités vide créé: {OUTPUT_PROBA_CSV}"); print(f"[OK_ML] {os.path.basename(INPUT_CSV)} vide, {os.path.basename(OUTPUT_PROBA_CSV)} vide créé.")
        except Exception as e_csv: logger.error(f"Erreur création fichier prob vide: {e_csv}"); print(f"[ERREUR_ML] Erreur création fichier prob vide: {e_csv}"); return 1
        return 0
    base_needed_cols = ["symbol", "date"]
    for base_col in base_needed_cols:
        if base_col not in df.columns: logger.error(f"Colonne '{base_col}' manquante dans {INPUT_CSV}"); print(f"[ERREUR_ML] Colonne '{base_col}' manquante."); return 1
    missing_in_csv = [col for col in COLUMNS_ORDER if col not in df.columns]
    if missing_in_csv: logger.error(f"Colonnes features manquantes dans {INPUT_CSV} pour {os.path.basename(MODEL_FILE)}: {missing_in_csv}"); print(f"[ERREUR_ML] Colonnes features manquantes: {missing_in_csv}"); return 1
    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    if df["date_dt"].isnull().any(): logger.warning(f"{df['date_dt'].isnull().sum()} lignes dates invalides supprimées."); df.dropna(subset=["date_dt"], inplace=True)
    if df.empty: logger.error(f"Aucune donnée date valide."); print(f"[ERREUR_ML] Pas de données date valide."); return 1
    today = datetime.utcnow().date(); df = df[df["date_dt"].dt.date < today]
    if df.empty: logger.error(f"Aucune donnée J-1 ou antérieure."); print(f"[ERREUR_ML] Pas de données J-1."); return 1
    for col in COLUMNS_ORDER:
        if df[col].dtype == 'object':
            try: df[col] = pd.to_numeric(df[col], errors='raise')
            except ValueError as e_conv: logger.error(f"Erreur conversion numérique '{col}': {e_conv}. Ex: {df[col].unique()[:5]}"); print(f"[ERREUR_ML] Erreur conversion '{col}'."); return 1
        df[col] = df[col].astype(float)
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    rows_before_dropna = len(df); df.dropna(subset=COLUMNS_ORDER, inplace=True); rows_after_dropna = len(df)
    if rows_after_dropna < rows_before_dropna: logger.warning(f"Suppression {rows_before_dropna - rows_after_dropna} lignes (NaN features).")
    if df.empty: logger.warning(f"Plus aucune ligne après dropna features. Skip."); print(f"[WARN_ML] Pas de données après dropna."); return 0
    try:
        loaded_model_artifact = joblib.load(MODEL_FILE); logger.info(f"Modèle {os.path.basename(MODEL_FILE)} chargé. Type: {type(loaded_model_artifact)}")
        model_to_predict = None
        if hasattr(loaded_model_artifact, 'predict_proba'): model_to_predict = loaded_model_artifact; logger.info("Modèle détecté comme pipeline direct.")
        elif isinstance(loaded_model_artifact, tuple) and len(loaded_model_artifact) == 2: model_to_predict, _ = loaded_model_artifact; logger.info("Modèle détecté comme tuple.")
        elif isinstance(loaded_model_artifact, dict) and "pipeline" in loaded_model_artifact: model_to_predict = loaded_model_artifact["pipeline"]; logger.info("Modèle détecté comme dict avec 'pipeline'.")
        else: logger.error(f"Structure modèle non reconnue: {type(loaded_model_artifact)}"); print(f"[ERREUR_ML] Structure modèle non reconnue"); return 1
        if not hasattr(model_to_predict, 'predict_proba'): logger.error(f"Modèle/pipeline n'a pas predict_proba."); print(f"[ERREUR_ML] Modèle ne peut prédire probas."); return 1
    except Exception as e: logger.error(f"Erreur chargement modèle {MODEL_FILE}: {e}", exc_info=True); print(f"[ERREUR_ML] Erreur chargement modèle: {e}"); return 1
    try:
        X_for_predict = df[COLUMNS_ORDER]
        non_numeric_final = X_for_predict.select_dtypes(exclude=[np.number]).columns
        if not non_numeric_final.empty: logger.error(f"Colonnes non numériques DANS X_for_predict: {non_numeric_final.tolist()}."); print(f"[ERREUR_ML] Colonnes non numériques DANS X_for_predict."); return 1
        logger.info(f"Prédiction sur {len(X_for_predict)} lignes, {len(X_for_predict.columns)} features.")
        probs = model_to_predict.predict_proba(X_for_predict)[:, 1]; df["prob"] = probs
        df_last_per_token = df.sort_values("date_dt").groupby("symbol", as_index=False).tail(1)
        df_out = df_last_per_token[["symbol", "prob"]].copy(); df_out.sort_values("symbol", inplace=True); df_out.reset_index(drop=True, inplace=True)
        df_out.to_csv(OUTPUT_PROBA_CSV, index=False)
        msg_ok = f"{os.path.basename(OUTPUT_PROBA_CSV)} généré ({len(df_out)} tokens) pour {os.path.basename(MODEL_FILE)}."
        logger.info(msg_ok); print(f"[OK_ML] {msg_ok}")
        logger.info(f"Probabilités (J-1) pour {os.path.basename(MODEL_FILE)}:")
        for _, row in df_out.iterrows(): logger.info(f"  {row['symbol']}: {row['prob']:.4f}")
    except Exception as e: logger.error(f"Erreur prédiction avec {MODEL_FILE}: {e}", exc_info=True); print(f"[ERREUR_ML] Erreur prédictions: {e}"); return 1
    logger.info(f"=== END ml_decision (BATCH) pour {os.path.basename(MODEL_FILE)} ==="); return 0

if __name__=="__main__":
    if not logging.getLogger("ml_decision_logic").hasHandlers() and not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s", handlers=[logging.StreamHandler(sys.stderr)])
        logger.info("Logging de base configuré pour exécution directe de ml_decision.py.")
    exit_code = main_ml_decision()
    sys.exit(exit_code)

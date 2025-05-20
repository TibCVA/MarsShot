#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import numpy as np
import pandas as pd
import joblib
from datetime import datetime
import sys # Assurez-vous que sys est importé si vous utilisez sys.executable ailleurs

# Récupérer le logger configuré par main.py ou configurer un logger de base
logger = logging.getLogger("ml_decision_logic") # Nom spécifique
if not logger.hasHandlers():
    # Configuration de base si le script est exécuté seul ou si le logger n'est pas propagé
    _handler_ml = logging.StreamHandler(sys.stderr) # Log sur stderr pour être capturé
    _formatter_ml = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s")
    _handler_ml.setFormatter(_formatter_ml)
    logger.addHandler(_handler_ml)
    logger.setLevel(logging.INFO)
    logger.propagate = False


# Chemins basés sur l'hypothèse que ce script est dans modules/
# et que les données/modèles sont dans le répertoire parent (racine du projet)
CURRENT_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT_ML = os.path.join(CURRENT_MODULE_DIR, "..")

MODEL_FILE        = os.path.join(PROJECT_ROOT_ML, "model_deuxpointcinq.pkl")
INPUT_CSV         = os.path.join(PROJECT_ROOT_ML, "daily_inference_data.csv")
OUTPUT_PROBA_CSV  = os.path.join(PROJECT_ROOT_ML, "daily_probabilities.csv")
# LOG_FILE est géré par le logger, pas besoin de filename= ici si configuré par main

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

def main_ml_decision(): # Renommer pour éviter conflit si importé
    logger.info(f"=== START ml_decision (BATCH) using {os.path.basename(MODEL_FILE)} ===")

    logger.info(f"Vérification du fichier modèle => {MODEL_FILE}")
    if not os.path.exists(MODEL_FILE):
        logger.error(f"Fichier modèle {MODEL_FILE} introuvable. Impossible de prédire.")
        print(f"[ERREUR_ML_DECISION] {MODEL_FILE} introuvable.") # Pour stdout si capturé
        return 1 # Code d'erreur

    logger.info(f"Vérification du fichier CSV d'entrée => {INPUT_CSV}")
    if not os.path.exists(INPUT_CSV):
        logger.error(f"Fichier d'entrée {INPUT_CSV} introuvable. Impossible de prédire.")
        print(f"[ERREUR_ML_DECISION] {INPUT_CSV} introuvable.")
        return 1

    try:
        df = pd.read_csv(INPUT_CSV)
    except Exception as e:
        logger.error(f"Échec de la lecture de {INPUT_CSV}: {e}", exc_info=True)
        print(f"[ERREUR_ML_DECISION] Échec lecture {INPUT_CSV}: {e}")
        return 1
        
    if df.empty:
        logger.warning(f"{os.path.basename(INPUT_CSV)} est vide. Aucune prédiction possible.")
        # Créer un fichier de probabilités vide pour éviter des erreurs en aval
        try:
            pd.DataFrame(columns=["symbol", "prob"]).to_csv(OUTPUT_PROBA_CSV, index=False)
            logger.info(f"Fichier de probabilités vide créé: {OUTPUT_PROBA_CSV}")
            print(f"[OK_ML_DECISION] {os.path.basename(INPUT_CSV)} vide, {os.path.basename(OUTPUT_PROBA_CSV)} vide créé.")
        except Exception as e_csv:
            logger.error(f"Erreur création fichier probabilités vide: {e_csv}")
            print(f"[ERREUR_ML_DECISION] Erreur création fichier probabilités vide: {e_csv}")
            return 1
        return 0 # Succès, mais pas de données à traiter

    base_needed_cols = ["symbol", "date"]
    for base_col in base_needed_cols:
        if base_col not in df.columns:
            logger.error(f"Colonne essentielle '{base_col}' manquante dans {INPUT_CSV}")
            print(f"[ERREUR_ML_DECISION] Colonne essentielle '{base_col}' manquante.")
            return 1
            
    needed_cols_for_check = COLUMNS_ORDER + base_needed_cols
    missing_in_csv = [col for col in COLUMNS_ORDER if col not in df.columns] # Seulement les features pour le modèle
    if missing_in_csv:
        logger.error(f"Colonnes de features manquantes dans {INPUT_CSV} pour {os.path.basename(MODEL_FILE)}: {missing_in_csv}")
        print(f"[ERREUR_ML_DECISION] Colonnes features manquantes: {missing_in_csv}")
        return 1

    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    if df["date_dt"].isnull().any():
        logger.warning(f"{df['date_dt'].isnull().sum()} lignes avec dates invalides supprimées de {os.path.basename(INPUT_CSV)}.")
        df.dropna(subset=["date_dt"], inplace=True)
    if df.empty:
        logger.error(f"Aucune donnée avec date valide disponible dans {os.path.basename(INPUT_CSV)}.");
        print(f"[ERREUR_ML_DECISION] Pas de données avec date valide."); return 1

    today = datetime.utcnow().date()
    df = df[df["date_dt"].dt.date < today]
    if df.empty:
        logger.error(f"Aucune donnée complète (J-1 ou antérieure) disponible après filtrage par date dans {os.path.basename(INPUT_CSV)}.")
        print(f"[ERREUR_ML_DECISION] Pas de données pour J-1 ou antérieures."); return 1 # Peut-être retourner 0 si c'est un cas normal

    # S'assurer que toutes les colonnes de features sont numériques
    for col in COLUMNS_ORDER:
        if df[col].dtype == 'object': # Si une colonne est de type object, tenter une conversion
            try:
                df[col] = pd.to_numeric(df[col], errors='raise') # 'raise' pour attraper les problèmes
            except ValueError as e_conv:
                logger.error(f"Erreur de conversion en numérique pour la colonne '{col}': {e_conv}. Exemples: {df[col].unique()[:5]}")
                print(f"[ERREUR_ML_DECISION] Erreur conversion numérique colonne '{col}'.")
                return 1
        df[col] = df[col].astype(float) # Assurer float pour toutes les features

    # Remplacer infinis par NaN avant dropna
    df.replace([np.inf, -np.inf], np.nan, inplace=True)

    rows_before_dropna = len(df)
    df.dropna(subset=COLUMNS_ORDER, inplace=True)
    rows_after_dropna = len(df)
    if rows_after_dropna < rows_before_dropna:
        logger.warning(f"Suppression de {rows_before_dropna - rows_after_dropna} lignes en raison de NaN dans les features (colonnes vérifiées: {len(COLUMNS_ORDER)}).")
    if df.empty:
        logger.warning(f"Plus aucune ligne après suppression des NaN dans les features de {os.path.basename(INPUT_CSV)}. Skip.")
        print(f"[WARN_ML_DECISION] Pas de données après dropna features."); return 0 # Succès, mais pas de données

    try:
        loaded_model_artifact = joblib.load(MODEL_FILE)
        logger.info(f"Modèle {os.path.basename(MODEL_FILE)} chargé. Type: {type(loaded_model_artifact)}")
        model_to_predict = None
        if hasattr(loaded_model_artifact, 'predict_proba'):
            model_to_predict = loaded_model_artifact
            logger.info("Modèle détecté comme pipeline scikit-learn direct (ou objet avec predict_proba).")
        elif isinstance(loaded_model_artifact, tuple) and len(loaded_model_artifact) == 2:
            model_to_predict, _ = loaded_model_artifact
            logger.info("Modèle détecté comme tuple (ancien format).")
        elif isinstance(loaded_model_artifact, dict) and "pipeline" in loaded_model_artifact:
            model_to_predict = loaded_model_artifact["pipeline"]
            logger.info("Modèle détecté comme dictionnaire avec clé 'pipeline'.")
        else:
            logger.error(f"Structure de modèle non reconnue pour {MODEL_FILE}: {type(loaded_model_artifact)}")
            print(f"[ERREUR_ML_DECISION] Structure de modèle non reconnue pour {MODEL_FILE}"); return 1
        
        if not hasattr(model_to_predict, 'predict_proba'):
            logger.error(f"Le modèle/pipeline de {MODEL_FILE} n'a pas de méthode predict_proba.")
            print(f"[ERREUR_ML_DECISION] Modèle/pipeline de {MODEL_FILE} ne peut pas prédire probas."); return 1
            
    except Exception as e:
        logger.error(f"Erreur lors du chargement du modèle {MODEL_FILE}: {e}", exc_info=True)
        print(f"[ERREUR_ML_DECISION] Erreur chargement modèle {MODEL_FILE}: {e}"); return 1

    try:
        # MODIFICATION ICI: Passer le DataFrame avec les noms de colonnes
        X_for_predict = df[COLUMNS_ORDER] 
        
        # Vérification supplémentaire des types avant prédiction
        non_numeric_final = X_for_predict.select_dtypes(exclude=[np.number]).columns
        if not non_numeric_final.empty:
            logger.error(f"Colonnes non numériques DANS X_for_predict avant prédiction: {non_numeric_final.tolist()}.")
            print(f"[ERREUR_ML_DECISION] Colonnes non numériques DANS X_for_predict."); return 1

        logger.info(f"Prédiction sur {len(X_for_predict)} lignes avec {len(X_for_predict.columns)} features.")
        probs = model_to_predict.predict_proba(X_for_predict)[:, 1]
        df["prob"] = probs
        
        df_last_per_token = df.sort_values("date_dt").groupby("symbol", as_index=False).tail(1)
        df_out = df_last_per_token[["symbol", "prob"]].copy()
        df_out.sort_values("symbol", inplace=True); df_out.reset_index(drop=True, inplace=True)
        
        df_out.to_csv(OUTPUT_PROBA_CSV, index=False)
        msg_ok = f"{os.path.basename(OUTPUT_PROBA_CSV)} généré avec {len(df_out)} tokens pour {os.path.basename(MODEL_FILE)}."
        logger.info(msg_ok)
        print(f"[OK_ML_DECISION] {msg_ok}") # Pour stdout
        
        logger.info(f"Probabilités (J-1) utilisées par token (modèle {os.path.basename(MODEL_FILE)}):")
        for _, row in df_out.iterrows(): logger.info(f"Token: {row['symbol']}, Prob (J-1): {row['prob']:.4f}")
            
    except Exception as e:
        logger.error(f"Erreur lors de la phase de prédiction avec {MODEL_FILE}: {e}", exc_info=True)
        print(f"[ERREUR_ML_DECISION] Erreur prédictions avec {MODEL_FILE}: {e}"); return 1

    logger.info(f"=== END ml_decision (BATCH) pour {os.path.basename(MODEL_FILE)} ===")
    return 0 # Succès

if __name__=="__main__":
    # Si exécuté directement, configurer un logging de base pour ce script
    # Le logger 'ml_decision_logic' est déjà défini au niveau du module.
    # Si main.py l'appelle, le logger de main.py (ou root) devrait déjà être configuré.
    # Cette config est un fallback.
    if not logging.getLogger("ml_decision_logic").hasHandlers() and not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, 
                            format="%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s",
                            handlers=[logging.StreamHandler(sys.stderr)]) # Écrit sur stderr pour subprocess
        logger.info("Logging de base configuré pour exécution directe de ml_decision.py.")

    exit_code = main_ml_decision()
    sys.exit(exit_code)

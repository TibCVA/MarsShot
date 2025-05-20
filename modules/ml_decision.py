#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import numpy as np
import pandas as pd
import joblib
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# MODIFICATION: Nom du fichier modèle mis à jour
MODEL_FILE        = os.path.join(CURRENT_DIR, "..", "model_deuxpointcinq.pkl")
INPUT_CSV         = os.path.join(CURRENT_DIR, "..", "daily_inference_data.csv")
OUTPUT_PROBA_CSV  = os.path.join(CURRENT_DIR, "..", "daily_probabilities.csv")
LOG_FILE          = "ml_decision.log" # Le nom du fichier log peut rester le même ou être versionné

# MODIFICATION: COLUMNS_ORDER mise à jour pour model_deuxpointcinq.pkl
# Correspond à la liste 'expected_features' de train_model_v4.py, triée.
COLUMNS_ORDER = sorted([
    "rsi14", "rsi30", "atr14", "macd_std", "stoch_rsi_k", "stoch_rsi_d", "mfi14", "boll_percent_b", "obv", "adx", "adx_pos", "adx_neg", "ma_close_7d", "ma_close_14d",
    "galaxy_score", "alt_rank", "sentiment", "social_dominance", "market_dominance", # Les brutes sont utilisées par le modèle
    "delta_close_1d", "delta_close_3d",
    "delta_vol_1d", "delta_vol_3d",
    "delta_mcap_1d", "delta_mcap_3d",
    "delta_galaxy_score_1d", # delta_galaxy_score_3d est retiré
    "delta_alt_rank_3d",
    "delta_social_dom_1d", "delta_social_dom_3d",
    "delta_market_dom_1d", "delta_market_dom_3d",
    "atr14_norm", "price_change_norm_atr1d", "rsi14_roc3d",
    "ma_slope_7d", "ma_slope_14d", "boll_width_norm",
    "volume_norm_ma20", # Pour le token lui-même
    "galaxy_score_norm_ma7", "sentiment_ma_diff7",
    "alt_rank_roc1d", "alt_rank_roc7d",
    "btc_daily_change", "btc_3d_change", "eth_daily_change", "eth_3d_change",
    "btc_atr_norm", "btc_rsi", "eth_atr_norm", "eth_rsi", # btc/eth_volume_norm_ma20 ne sont PAS dans expected_features du modèle final
    "rsi_vs_btc", "atr_norm_vs_btc",
    "volatility_ratio_vs_market",
    "obv_slope_5d"
])

logging.basicConfig(
    filename=LOG_FILE,
    filemode='a', # Conserver 'a' pour ajouter aux logs existants
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START ml_decision (BATCH) using model_deuxpointcinq.pkl ===") # Log mis à jour

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

    try:
        df = pd.read_csv(INPUT_CSV)
    except Exception as e:
        logging.error(f"[ERROR] Failed to read {INPUT_CSV}: {e}")
        print(f"[ERROR] Failed to read {INPUT_CSV}: {e}")
        return
        
    if df.empty:
        logging.warning("[WARN] daily_inference_data.csv est vide => aucune prédiction possible.")
        print("[WARN] empty daily_inference_data.csv => skip.")
        return

    # S'assurer que 'date' et 'symbol' sont présentes avant de les ajouter à needed_cols
    # pour éviter une erreur si elles manquaient pour une raison imprévue.
    base_needed_cols = ["symbol", "date"]
    for base_col in base_needed_cols:
        if base_col not in df.columns:
            logging.error(f"[ERROR] Colonne essentielle '{base_col}' manquante dans {INPUT_CSV}")
            print(f"[ERROR] Colonne essentielle '{base_col}' manquante dans {INPUT_CSV}")
            return
            
    needed_cols_for_check = COLUMNS_ORDER + base_needed_cols
    missing = [col for col in needed_cols_for_check if col not in df.columns]
    if missing:
        logging.error(f"[ERROR] Colonnes manquantes dans {INPUT_CSV} pour le modèle {os.path.basename(MODEL_FILE)}: {missing}")
        print(f"[ERROR] Colonnes manquantes: {missing}")
        return

    # Conversion de "date" en datetime et filtrage sur les données complètes (bucket J-1)
    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    # Gérer les NaT qui pourraient résulter de 'coerce'
    if df["date_dt"].isnull().any():
        logging.warning(f"[WARN] {df['date_dt'].isnull().sum()} lignes avec dates invalides ont été supprimées.")
        df.dropna(subset=["date_dt"], inplace=True)

    if df.empty: # Vérifier à nouveau après suppression des NaT
        logging.error("[ERROR] Aucune donnée avec date valide disponible.")
        print("[ERROR] Pas de données avec date valide.")
        return

    today = datetime.utcnow().date()
    df = df[df["date_dt"].dt.date < today] # Utilise uniquement les données jusqu'à la veille (J-1)
    
    if df.empty:
        logging.error("[ERROR] Aucune donnée complète (J-1 ou antérieure) disponible après filtrage par date.")
        print("[ERROR] Pas de données pour J-1 ou antérieures.")
        return

    # Suppression des lignes où les features sont NaN (uniquement pour les colonnes de features)
    before = len(df)
    df.dropna(subset=COLUMNS_ORDER, inplace=True) # COLUMNS_ORDER contient uniquement les features
    after = len(df)
    if after < before:
        logging.warning(f"[WARN] Drop {before - after} lignes en raison de NaN dans les features: {COLUMNS_ORDER}")
    if df.empty:
        logging.warning("[WARN] Plus aucune ligne après suppression des NaN dans les features => skip.")
        print("[WARN] no data after NaN drop in features => skip.")
        return

    # Chargement du modèle
    try:
        loaded_model_artifact = joblib.load(MODEL_FILE)
        logging.info(f"[ML_DECISION] Modèle {os.path.basename(MODEL_FILE)} chargé. Type: {type(loaded_model_artifact)}")
        
        # La logique de détection du type de modèle (tuple, dict, pipeline direct) est conservée.
        # S'assurer qu'elle est toujours pertinente pour model_deuxpointcinq.pkl.
        # D'après train_model_v4.py, le modèle sauvegardé est un Pipeline scikit-learn.
        
        model_to_predict = None
        if isinstance(loaded_model_artifact, tuple) and len(loaded_model_artifact) == 2: # Cas ancien modèle
            model_to_predict, _ = loaded_model_artifact # custom_threshold non utilisé ici pour la proba brute
            logging.info(f"[ML_DECISION] Modèle détecté comme tuple (ancien format).")
        
        elif isinstance(loaded_model_artifact, dict) and "pipeline" in loaded_model_artifact: # Cas ancien modèle "business"
            model_to_predict = loaded_model_artifact["pipeline"]
            logging.info(f"[ML_DECISION] Modèle détecté comme dictionnaire avec clé 'pipeline'.")
        
        elif hasattr(loaded_model_artifact, 'predict_proba'): # Cas pipeline scikit-learn direct (attendu pour model_deuxpointcinq.pkl)
            model_to_predict = loaded_model_artifact
            logging.info(f"[ML_DECISION] Modèle détecté comme pipeline scikit-learn direct.")
        
        else:
            logging.error(f"[ML_DECISION] Structure de modèle non reconnue pour {MODEL_FILE}: {type(loaded_model_artifact)}")
            if isinstance(loaded_model_artifact, dict):
                logging.error(f"[ML_DECISION] Clés disponibles dans le dictionnaire: {list(loaded_model_artifact.keys())}")
            print(f"[ERROR] Structure de modèle non reconnue pour {MODEL_FILE}")
            return
        
        if not hasattr(model_to_predict, 'predict_proba'):
            logging.error(f"[ML_DECISION] Le modèle/pipeline chargé depuis {MODEL_FILE} n'a pas de méthode predict_proba.")
            print(f"[ERROR] Le modèle/pipeline de {MODEL_FILE} ne peut pas faire de prédictions de probabilité.")
            return
            
    except Exception as e:
        logging.error(f"[ERROR] Erreur lors du chargement du modèle {MODEL_FILE}: {e}", exc_info=True)
        print(f"[ERROR] Erreur lors du chargement du modèle {MODEL_FILE}: {e}")
        return

    # Prédiction
    try:
        # S'assurer que df[COLUMNS_ORDER] ne contient que des types numériques et pas d'objets/strings
        X_features = df[COLUMNS_ORDER]
        non_numeric_cols = X_features.select_dtypes(exclude=[np.number]).columns
        if not non_numeric_cols.empty:
            logging.error(f"[ERROR] Colonnes non numériques trouvées dans les features avant la prédiction: {non_numeric_cols.tolist()}. Vérifiez {INPUT_CSV}.")
            for col in non_numeric_cols:
                logging.error(f"Exemple de valeurs pour la colonne non numérique '{col}': {X_features[col].unique()[:5]}")
            print(f"[ERROR] Colonnes non numériques dans les features: {non_numeric_cols.tolist()}")
            return

        X = X_features.values.astype(float) # Conversion explicite en float
        probs = model_to_predict.predict_proba(X)[:, 1] # Probabilité de la classe positive (1)
        df["prob"] = probs
        
        # Groupement par token pour obtenir uniquement la dernière ligne (la plus récente) par token
        # Assurer que 'date_dt' et 'symbol' sont bien dans df
        df_last_per_token = df.sort_values("date_dt").groupby("symbol", as_index=False).tail(1)
        
        # Sélectionner uniquement 'symbol' et 'prob' pour la sortie
        df_out = df_last_per_token[["symbol", "prob"]].copy()
        df_out.sort_values("symbol", inplace=True)
        df_out.reset_index(drop=True, inplace=True)
        
        df_out.to_csv(OUTPUT_PROBA_CSV, index=False)
        logging.info(f"[OK] => {OUTPUT_PROBA_CSV} généré avec {len(df_out)} tokens pour le modèle {os.path.basename(MODEL_FILE)}.")
        print(f"[OK] => {OUTPUT_PROBA_CSV} ({len(df_out)} tokens) for {os.path.basename(MODEL_FILE)}.")
        
        logging.info("Probabilités (J-1) utilisées par token (modèle %s):", os.path.basename(MODEL_FILE))
        for _, row in df_out.iterrows():
            logging.info(f"Token: {row['symbol']}, Prob (J-1): {row['prob']:.4f}")
            
    except Exception as e:
        logging.error(f"[ERROR] Erreur lors de la phase de prédiction avec {MODEL_FILE}: {e}", exc_info=True)
        print(f"[ERROR] Erreur lors des prédictions avec {MODEL_FILE}: {e}")
        return

    logging.info("=== END ml_decision (BATCH) ===")

if __name__=="__main__":
    main()

#!/usr/bin/env python3
# coding: utf-8

"""
ml_decision.py
--------------
But:
  - Lire daily_inference_data.csv (fourni par data_fetcher.py)
  - Charger model.pkl (entraîne avec 12 features => [close, volume, ... sol_daily_change])
  - Calculer la prob. de hausse (classe=1) pour CHAQUE token => 1 ligne par token
  - Écrire daily_probabilities.csv, ex:
       symbol,prob
       HIVE,0.8321
       ACT,0.4249
       ...
  - Aucune récupération en "live" (plus de get_probability_for_symbol).
    => Tout se fait sur daily_inference_data.csv
"""

import os
import logging
import numpy as np
import pandas as pd
import joblib

# Nom du modèle
MODEL_FILE = "model.pkl"
# CSV d'entrée (issu de data_fetcher.py)
INPUT_CSV  = "daily_inference_data.csv"
# CSV de sortie => probas
OUTPUT_PROBA_CSV = "daily_probabilities.csv"
# Log
LOG_FILE   = "ml_decision.log"

# Les 12 features EXACTES
COLUMNS_ORDER = [
    "close","volume","market_cap","galaxy_score","alt_rank","sentiment",
    "rsi","macd","atr",
    "btc_daily_change","eth_daily_change","sol_daily_change"
]

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START ml_decision (BATCH) ===")

def main():
    # 1) Check model
    if not os.path.exists(MODEL_FILE):
        msg = f"[ERROR] {MODEL_FILE} introuvable => impossible de prédire."
        logging.error(msg)
        print(msg)
        return

    # 2) Check CSV
    if not os.path.exists(INPUT_CSV):
        msg = f"[ERROR] {INPUT_CSV} introuvable => impossible de prédire."
        logging.error(msg)
        print(msg)
        return

    # 3) Charger le modèle
    model = joblib.load(MODEL_FILE)
    logging.info(f"[INFO] Modèle {MODEL_FILE} chargé.")

    # 4) Lire daily_inference_data.csv
    df = pd.read_csv(INPUT_CSV)
    if df.empty:
        msg = "[WARN] daily_inference_data.csv est vide => aucune prédiction possible."
        logging.warning(msg)
        print(msg)
        return

    # 5) Vérifier colonnes
    needed_cols = COLUMNS_ORDER + ["symbol"]
    for col in needed_cols:
        if col not in df.columns:
            msg = f"[ERROR] Colonne manquante => {col}"
            logging.error(msg)
            print(msg)
            return

    # 6) Drop NaN dans nos features
    before = len(df)
    df.dropna(subset=COLUMNS_ORDER, inplace=True)
    after = len(df)
    if after < before:
        logging.warning(f"[WARN] Drop {before - after} tokens => NaN dans features.")

    if df.empty:
        msg = "[WARN] Plus aucune ligne => impossible de prédire."
        logging.warning(msg)
        print(msg)
        return

    # 7) X => (N,12)
    X = df[COLUMNS_ORDER].values.astype(float)

    # 8) predict_proba => prob_1
    probs = model.predict_proba(X)
    prob_1 = probs[:,1]

    # 9) On stocke dans daily_probabilities.csv
    out_rows = []
    for i, row in df.iterrows():
        sym = row["symbol"]
        p   = prob_1[i]
        out_rows.append([sym, p])

    df_out = pd.DataFrame(out_rows, columns=["symbol","prob"])
    df_out.sort_values("symbol", inplace=True)
    df_out.reset_index(drop=True, inplace=True)
    df_out.to_csv(OUTPUT_PROBA_CSV, index=False)

    logging.info(f"[INFO] Probabilités sauvegardées => {OUTPUT_PROBA_CSV}")
    print(f"[OK] daily_probabilities.csv => {len(df_out)} tokens.")

    logging.info("=== END ml_decision (BATCH) ===")


if __name__=="__main__":
    main()
#!/usr/bin/env python3
# coding: utf-8

"""
ml_decision.py
--------------
But : lire le CSV daily_inference_data.csv (issu de data_fetcher.py),
      charger model.pkl (issu de build_csv.py + train_model.py),
      calculer la proba de hausse (classe=1) pour chaque token,
      et afficher + logger le résultat.

Configuration :
 - On suppose que daily_inference_data.csv contient 1 ligne par token,
   avec les colonnes EXACTEMENT comme build_csv.py :
     ["date","open","high","low","close","volume","market_cap",
      "galaxy_score","alt_rank","sentiment",
      "rsi","macd","atr",
      "label","symbol",
      "btc_daily_change","eth_daily_change","sol_daily_change"]

 - On utilise model.pkl (RandomForest ou autre) 
   qui attend en entrée (train_model.py) => un vecteur :
     [close, volume, market_cap, galaxy_score, alt_rank, sentiment,
      rsi, macd, atr, btc_daily_change, eth_daily_change, sol_daily_change]

Exécution "live" :
1) data_fetcher.py => produit daily_inference_data.csv
2) python ml_decision.py => lit ce CSV, charge model.pkl => proba => logs.

Pas de redondance : on NE refait pas le fetch lunarcrush (contrairement à l'ancienne version).
"""

import os
import logging
import numpy as np
import pandas as pd
import joblib

########################################
# FICHIERS
########################################
MODEL_FILE = "model.pkl"
INPUT_CSV  = "daily_inference_data.csv"
LOG_FILE   = "ml_decision.log"

########################################
# COLONNES attendues
########################################
COLUMNS_ORDER = [
    "close","volume","market_cap","galaxy_score","alt_rank","sentiment",
    "rsi","macd","atr",
    "btc_daily_change","eth_daily_change","sol_daily_change"
]

########################################
# LOGGING
########################################
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START ml_decision ===")

def main():
    # 1) Vérifier la présence du modèle
    if not os.path.exists(MODEL_FILE):
        msg = f"[ERROR] {MODEL_FILE} introuvable => impossible de prédire."
        logging.error(msg)
        print(msg)
        return

    # 2) Vérifier le CSV
    if not os.path.exists(INPUT_CSV):
        msg = f"[ERROR] {INPUT_CSV} introuvable => impossible de prédire."
        logging.error(msg)
        print(msg)
        return

    # 3) Charger le modèle
    model = joblib.load(MODEL_FILE)
    logging.info(f"[INFO] Modèle {MODEL_FILE} chargé.")

    # 4) Lire le CSV
    df = pd.read_csv(INPUT_CSV)
    if df.empty:
        msg = "[WARN] daily_inference_data.csv est vide => aucune prédiction."
        logging.warning(msg)
        print(msg)
        return

    # 5) Vérifier qu'on a bien toutes les colonnes
    needed_cols = COLUMNS_ORDER + ["symbol"]
    for col in needed_cols:
        if col not in df.columns:
            msg = f"[ERROR] Colonne manquante dans {INPUT_CSV} => {col}"
            logging.error(msg)
            print(msg)
            return

    # 6) Drop les lignes qui ont un NaN dans l'une des colonnes d'entrée
    df_before = len(df)
    df.dropna(subset=COLUMNS_ORDER, inplace=True)
    df_after = len(df)
    if df_after < df_before:
        logging.warning(f"[WARN] On drop {df_before - df_after} tokens pour cause de NaN dans colonnes d'entrée.")

    if df.empty:
        msg = "[WARN] Toutes les lignes ont été drop => plus rien à prédire."
        logging.warning(msg)
        print(msg)
        return

    # 7) Construire la matrice d'entrée (N,12)
    X = df[COLUMNS_ORDER].values.astype(float)
    # 8) Prédiction
    probs = model.predict_proba(X)  # shape (N,2)
    # index 1 = prob classe=1
    prob_1 = probs[:,1]

    # 9) On logge le résultat + on print
    print("=== Probabilités de hausse (classe=1) ===")
    for i, row in df.iterrows():
        sym = row["symbol"]
        p   = prob_1[i]
        print(f"{sym} => {p:.4f}")
        logging.info(f"[RESULT] {sym} => {p:.4f}")

    logging.info("=== END ml_decision ===")


if __name__=="__main__":
    main()

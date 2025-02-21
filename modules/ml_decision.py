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

    needed_cols = COLUMNS_ORDER + ["symbol","date"]
    missing = [col for col in needed_cols if col not in df.columns]
    if missing:
        logging.error(f"[ERROR] Colonnes manquantes => {missing}")
        print(f"[ERROR] missing cols => {missing}")
        return

    # dropna
    before = len(df)
    df.dropna(subset=COLUMNS_ORDER, inplace=True)
    after = len(df)
    if after < before:
        logging.warning(f"[WARN] Drop {before - after} lignes => NaN dans features")

    if df.empty:
        logging.warning("[WARN] plus aucune ligne => skip.")
        print("[WARN] no data => skip.")
        return

    # Charger le modèle
    loaded = joblib.load(MODEL_FILE)
    if isinstance(loaded, tuple):
        model, custom_threshold = loaded
        logging.info(f"[ML_DECISION] pipeline + threshold={custom_threshold}")
    else:
        model = loaded
        custom_threshold = None

    X = df[COLUMNS_ORDER].values.astype(float)
    probs = model.predict_proba(X)[:,1]

    out_rows = []
    for i, row in df.iterrows():
        sym = row["symbol"]
        p   = probs[i]
        out_rows.append([sym, p])

    df_out = pd.DataFrame(out_rows, columns=["symbol","prob"])
    df_out.sort_values("symbol", inplace=True)
    df_out.reset_index(drop=True, inplace=True)

    df_out.to_csv(OUTPUT_PROBA_CSV, index=False)
    logging.info(f"[OK] => daily_probabilities.csv => {len(df_out)} tokens.")
    print(f"[OK] => daily_probabilities.csv => {len(df_out)} tokens.")

    # --- AJOUT : Enregistrement des probabilités par token dans le log ---
    logging.info("Résultats des probabilités par token:")
    for idx, row in df_out.iterrows():
        logging.info(f"Token: {row['symbol']} - Probabilité: {row['prob']:.4f}")

    logging.info("=== END ml_decision (BATCH) ===")

if __name__=="__main__":
    main()

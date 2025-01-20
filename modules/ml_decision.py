#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import numpy as np
import pandas as pd
import joblib

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# model.pkl dans la racine => ../model.pkl
MODEL_FILE       = os.path.join(CURRENT_DIR, "..", "model.pkl")
INPUT_CSV        = os.path.join(CURRENT_DIR, "..", "daily_inference_data.csv")
OUTPUT_PROBA_CSV = os.path.join(CURRENT_DIR, "..", "daily_probabilities.csv")
LOG_FILE         = "ml_decision.log"

COLUMNS_ORDER = [
    "delta_close_1d","delta_close_3d","delta_vol_1d","delta_vol_3d",
    "rsi14","rsi30","ma_close_7d","ma_close_14d","atr14","macd_std",
    "stoch_rsi_k","stoch_rsi_d","mfi14","boll_percent_b","obv",
    "adx","adx_pos","adx_neg",
    "btc_daily_change","btc_3d_change","eth_daily_change","eth_3d_change",
    "delta_mcap_1d","delta_mcap_3d","galaxy_score","delta_galaxy_score_3d",
    "alt_rank","delta_alt_rank_3d","sentiment","social_dominance","market_dominance",
    "delta_social_dom_3d","delta_market_dom_3d"
]

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START ml_decision (BATCH) ===")

def main():
    logging.info(f"[ML_DECISION] Checking model file => {MODEL_FILE}")
    if not os.path.exists(MODEL_FILE):
        msg = f"[ERROR] {MODEL_FILE} introuvable => impossible de prédire."
        logging.error(msg)
        print(msg)
        return

    logging.info(f"[ML_DECISION] Checking input CSV => {INPUT_CSV}")
    if not os.path.exists(INPUT_CSV):
        msg = f"[ERROR] {INPUT_CSV} introuvable => impossible de prédire."
        logging.error(msg)
        print(msg)
        return

    loaded = joblib.load(MODEL_FILE)
    if isinstance(loaded, tuple):
        model, custom_threshold = loaded
        logging.info(f"[INFO] Modèle + threshold={custom_threshold}")
    else:
        model = loaded
        custom_threshold = None

    df = pd.read_csv(INPUT_CSV)
    if df.empty:
        msg = "[WARN] daily_inference_data.csv est vide => aucune prédiction possible."
        logging.warning(msg)
        print(msg)
        return

    needed = COLUMNS_ORDER + ["symbol","date"]
    for col in needed:
        if col not in df.columns:
            msg = f"[ERROR] Colonne manquante => {col}"
            logging.error(msg)
            print(msg)
            return

    before = len(df)
    df.dropna(subset=COLUMNS_ORDER, inplace=True)
    after = len(df)
    if after<before:
        logging.warning(f"[WARN] drop {before-after} lignes => NaN dans features.")

    if df.empty:
        msg = "[WARN] plus aucune ligne => impossible de prédire."
        logging.warning(msg)
        print(msg)
        return

    X = df[COLUMNS_ORDER].values.astype(float)
    probs = model.predict_proba(X)
    prob_1= probs[:,1]

    out_rows=[]
    for i, row in df.iterrows():
        sym = row["symbol"]
        p   = prob_1[i]
        out_rows.append([sym,p])

    df_out = pd.DataFrame(out_rows, columns=["symbol","prob"])
    df_out.sort_values("symbol", inplace=True)
    df_out.reset_index(drop=True, inplace=True)

    df_out.to_csv(OUTPUT_PROBA_CSV, index=False)
    logging.info(f"[INFO] Probabilités => {OUTPUT_PROBA_CSV}, rows={len(df_out)}")
    print(f"[OK] daily_probabilities.csv => {len(df_out)} tokens.")
    logging.info("=== END ml_decision (BATCH) ===")

if __name__=="__main__":
    main()
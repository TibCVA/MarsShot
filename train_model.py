#!/usr/bin/env python3
# coding: utf-8

"""
train_model.py
Inclut désormais 'sol_daily_change' dans les features, en plus de BTC et ETH.
"""

import os
import logging
import pandas as pd
import numpy as np
import joblib

from sklearn.model_selection import TimeSeriesSplit, RandomizedSearchCV
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report

# Imblearn
try:
    from imblearn.over_sampling import SMOTE
    from imblearn.pipeline import Pipeline as ImbPipeline
    IMBLEARN_OK = True
except ImportError:
    from sklearn.pipeline import Pipeline as SkPipeline
    IMBLEARN_OK = False
    print("[WARNING] imbalanced-learn non installé => SMOTE indisponible.")

LOG_FILE   = "train_model.log"
CSV_FILE   = "training_data.csv"
MODEL_FILE = "model.pkl"

FINAL_TEST_RATIO = 0.1
N_ITER          = 50    # Paramètre pour la RandomizedSearch
TSCV_SPLITS     = 15    # Nombre de splits en TimeSeriesSplit

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START train_model ===")

def main():
    if not os.path.exists(CSV_FILE):
        print("[ERREUR] CSV introuvable.")
        return

    df = pd.read_csv(CSV_FILE)
    if "label" not in df.columns:
        print("[ERREUR] label manquant.")
        return

    # Ajout de 'sol_daily_change' dans la liste des features
    features = [
        "close", "volume", "market_cap",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr",
        "btc_daily_change", "eth_daily_change",
        "sol_daily_change"  # <-- NOUVEAU
    ]

    missing = [c for c in features if c not in df.columns]
    if missing:
        print("[ERREUR] Missing columns:", missing)
        return

    # On retire toutes les lignes où l'une des features ou 'label' est NaN
    sub = df.dropna(subset=features + ["label"]).copy()
    sub.sort_values("date", inplace=True)  # S'assurer du tri chronologique

    # Découpe en train/val vs. final_test
    cutoff = int((1.0 - FINAL_TEST_RATIO) * len(sub))
    train_val_df = sub.iloc[:cutoff].copy()
    final_test_df = sub.iloc[cutoff:].copy()

    logging.info(f"Train_val => {len(train_val_df)}, Final_test => {len(final_test_df)}.")

    X_tv = train_val_df[features]
    y_tv = train_val_df["label"].astype(int)

    X_test = final_test_df[features]
    y_test = final_test_df["label"].astype(int)

    # Choix du pipeline selon la disponibilité de SMOTE
    if IMBLEARN_OK:
        steps = [
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=42)),
            ("clf", RandomForestClassifier(random_state=42))
        ]
        pipe_class = ImbPipeline
        logging.info("[build_model] => SMOTE activé")
    else:
        steps = [
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                class_weight="balanced_subsample",
                random_state=42
            ))
        ]
        pipe_class = SkPipeline
        logging.info("[build_model] => SMOTE indisponible => fallback")

    pipe = pipe_class(steps)

    # Grille de recherche hyperparamètres
    param_dist = {
       "clf__n_estimators":      [100, 200, 300, 500, 800, 1200],
        "clf__max_depth":         [10, 15, 20, 30, None],
        "clf__min_samples_split": [2, 5, 10, 20],
        "clf__min_samples_leaf":  [1, 2, 5, 10],
        "clf__max_features":      ["sqrt", "log2", None],
        "clf__bootstrap":         [True, False],
        "clf__class_weight":      [None, "balanced_subsample", {0:1,1:2}, {0:1,1:3}, {0:1,1:4}]
    }

    tscv = TimeSeriesSplit(n_splits=TSCV_SPLITS)

    search = RandomizedSearchCV(
        estimator=pipe,
        param_distributions=param_dist,
        n_iter=N_ITER,
        scoring="f1",  # f1 pour classification binaire (pos_label=1)
        cv=tscv,
        verbose=1,
        random_state=42,
        n_jobs=-1
    )

    logging.info(f"RandomizedSearch => scoring='f1', TSCV={TSCV_SPLITS}, n_iter={N_ITER}")
    search.fit(X_tv, y_tv)

    best_params = search.best_params_
    logging.info(f"Best Params => {best_params}")
    print("\n[RESULT] Hyperparams =>", best_params)

    final_model = search.best_estimator_

    # Évaluation finale sur la portion "final_test"
    y_pred_test = final_model.predict(X_test)
    rep_test = classification_report(y_test, y_pred_test, digits=3)
    print("\n=== [Hold-out final test] ===")
    print(rep_test)
    logging.info("\n[Hold-out final test]\n" + rep_test)

    # Re-fit sur tout train+val
    final_model.fit(X_tv, y_tv)
    y_pred_in = final_model.predict(X_tv)
    rep_in = classification_report(y_tv, y_pred_in, digits=3)
    print("\n=== [In-sample 100%] ===")
    print(rep_in)
    logging.info("\n[In-sample 100%]\n" + rep_in)

    # Sauvegarde du modèle
    joblib.dump(final_model, MODEL_FILE)
    logging.info(f"Modèle final sauvegardé => {MODEL_FILE}")
    print(f"[OK] Modèle final sauvegardé => {MODEL_FILE}")

if __name__ == "__main__":
    main()

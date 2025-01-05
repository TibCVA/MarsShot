#!/usr/bin/env python3
# coding: utf-8

"""
Entraînement ML avec TimeSeriesSplit et hold-out final (20%):
 1) Tri par date
 2) Sépare 80% (train_val) vs 20% (final_test)
 3) Sur train_val => RandomizedSearchCV (TimeSeriesSplit=10, n_iter=60)
 4) best_model évalué sur final_test (vrai hold-out)
 5) Re-train final_model sur 100% (mêmes hyperparams)
 6) classification_report sur tout X,y (in-sample)
 7) Sauvegarde final_model => model.pkl
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
import joblib

from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit, RandomizedSearchCV
from sklearn.metrics import classification_report
from sklearn.pipeline import Pipeline

try:
    from imblearn.over_sampling import SMOTE
    from imblearn.pipeline import Pipeline as ImbPipeline
    IMBLEARN_OK = True
except ImportError:
    IMBLEARN_OK = False
    print("[WARNING] 'imbalanced-learn' non installé => SMOTE indisponible.")

########################################
# CONFIG
########################################
LOG_FILE   = "train_model.log"
CSV_FILE   = "training_data.csv"
MODEL_FILE = "model.pkl"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START train_model ===")

def main():
    """
    1) Lecture CSV => df
    2) Tri par date
    3) Sépare train_val (80%) / final_test (20%)   (méthode chronologique)
    4) Sur train_val => TSCV => RandomizedSearchCV => best_model
    5) Evaluate best_model sur final_test => classification_report
    6) Re-train (final_model) sur 100% (mêmes best_params)
    7) classification_report(in-sample) sur 100%
    8) joblib.dump(final_model, model.pkl)
    """

    # Récup param --n_iter (sinon 30)
    n_iter = 30
    for i, arg in enumerate(sys.argv):
        if arg == "--n_iter" and i+1 < len(sys.argv):
            try:
                n_iter = int(sys.argv[i+1])
            except ValueError:
                pass

    # 1) Lecture CSV
    if not os.path.exists(CSV_FILE):
        msg = f"[ERREUR] Fichier CSV introuvable : {CSV_FILE}"
        print(msg)
        logging.error(msg)
        return

    df = pd.read_csv(CSV_FILE)
    logging.info(f"CSV => {df.shape[0]} lignes, {df.shape[1]} colonnes.")

    if "label" not in df.columns:
        msg = "[ERREUR] Colonne 'label' manquante."
        print(msg)
        logging.error(msg)
        return

    if "date" not in df.columns:
        msg = "[ERREUR] Pas de colonne 'date' => hold-out final impossible."
        print(msg)
        logging.error(msg)
        return

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df.dropna(subset=["date"], inplace=True)
    df.sort_values("date", inplace=True)

    features = [
        "close","volume","market_cap",
        "galaxy_score","alt_rank","sentiment",
        "rsi","macd","atr",
        "btc_daily_change","eth_daily_change","sol_daily_change"
    ]
    target = "label"

    sub = df.dropna(subset=features + [target]).copy()
    if sub.empty:
        msg = "[ERREUR] Aucune ligne exploitable après dropna."
        print(msg)
        logging.error(msg)
        return

    # Indices
    cut_index = int(0.8 * len(sub))
    train_val_df = sub.iloc[:cut_index].reset_index(drop=True)
    final_test_df = sub.iloc[cut_index:].reset_index(drop=True)

    X_tv = train_val_df[features]
    y_tv = train_val_df[target].astype(int)

    X_ft = final_test_df[features]
    y_ft = final_test_df[target].astype(int)

    logging.info(f"Train_val => {len(X_tv)} lignes, Final_test => {len(X_ft)} lignes.")

    # Pipeline "vierge" pour RandomizedSearch
    if IMBLEARN_OK:
        steps = [
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=42)),
            ("clf", RandomForestClassifier(random_state=42))
        ]
        from imblearn.pipeline import Pipeline as PipelineClass
        logging.info("Pipeline: StandardScaler + SMOTE + RandomForest (pour RandomizedSearch)")
    else:
        steps = [
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                class_weight="balanced_subsample",
                random_state=42
            ))
        ]
        from sklearn.pipeline import Pipeline as PipelineClass
        logging.info("Pipeline fallback: StandardScaler + RF(class_weight=balanced_subsample)")

    pipe = PipelineClass(steps)

    param_distributions = {
        "clf__n_estimators":      [100, 200, 300, 500],
        "clf__max_depth":         [10, 15, 20, None],
        "clf__min_samples_split": [2, 5, 10],
        "clf__min_samples_leaf":  [1, 2, 5],
        "clf__max_features":      ["sqrt", "log2", None],
        "clf__bootstrap":         [True, False]
    }

    # TimeSeriesSplit sur train_val
    tscv = TimeSeriesSplit(n_splits=10)
    search = RandomizedSearchCV(
        estimator=pipe,
        param_distributions=param_distributions,
        n_iter=n_iter,
        scoring="f1",
        n_jobs=-1,
        cv=tscv,
        verbose=1,
        random_state=42
    )

    logging.info(f"Lancement RandomizedSearchCV => TSCV(10), n_iter={n_iter} sur train_val.")
    print(f"[INFO] RandomizedSearch => TSCV(10), n_iter={n_iter} sur {len(X_tv)} lignes. Patience ...")

    search.fit(X_tv, y_tv)
    best_model_cv = search.best_estimator_
    best_params = search.best_params_
    logging.info(f"Best Params => {best_params}")
    print("\n[RESULT] Hyperparamètres retenus =>", best_params)

    # Evaluation hold-out final (modèle entraîné sur train_val)
    y_pred_ft = best_model_cv.predict(X_ft)
    rep_ft = classification_report(y_ft, y_pred_ft, digits=3)
    logging.info("\n[Hold-out final test] " + rep_ft)
    print("\n=== Rapport hold-out final test (jamais vu) ===")
    print(rep_ft)

    # Re-train sur 100% des données (train_val + final_test)
    # => final_model
    if IMBLEARN_OK:
        final_steps = [
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=42)),
            ("clf", RandomForestClassifier(random_state=42, **_extract_rf_params(best_params)))
        ]
        from imblearn.pipeline import Pipeline as PipelineClass2
    else:
        final_steps = [
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                class_weight="balanced_subsample",
                random_state=42,
                **_extract_rf_params(best_params)
            ))
        ]
        from sklearn.pipeline import Pipeline as PipelineClass2

    final_model = PipelineClass2(final_steps)

    # X,y sur *toute* la data
    X_all = sub[features].reset_index(drop=True)
    y_all = sub[target].astype(int).reset_index(drop=True)

    final_model.fit(X_all, y_all)

    # Classification rapport sur 100%
    y_pred_all = final_model.predict(X_all)
    rep_all = classification_report(y_all, y_pred_all, digits=3)
    logging.info("\n[In-sample ALL data] " + rep_all)
    print("\n=== Rapport final_model sur 100% in-sample ===")
    print(rep_all)

    # Sauvegarde final_model
    joblib.dump(final_model, MODEL_FILE)
    logging.info(f"Final model sauvegardé => {MODEL_FILE}")
    print(f"[OK] Final model sauvegardé => {MODEL_FILE}")


def _extract_rf_params(params_dict):
    """
    Extrait seulement les paramètres liés à RandomForestClassifier
    depuis le best_params du pipeline (ex: clf__max_depth, etc.)
    pour re-construire un random forest identique.
    """
    rf_params = {}
    for k,v in params_dict.items():
        if k.startswith("clf__"):
            real_key = k.replace("clf__","")
            rf_params[real_key] = v
    return rf_params


if __name__ == "__main__":
    main()
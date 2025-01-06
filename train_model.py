#!/usr/bin/env python3
# coding: utf-8

"""
Entraînement ML "bull run friendly" (V8), focalisé sur le critère F1 de la classe 1
pour évaluer si on obtient un meilleur équilibre précision/rappel que la version axée sur le recall.
Logique: TimeSeriesSplit + hold-out final (20%) + réentraînement final sur 100%.
(Le reste du code est identique à la version précédente V6, sauf que le scoring passe à 'f1'.)
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

# Tentative d'import SMOTE
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
LOG_FILE   = "train_model.log"           # Fichier de logs
CSV_FILE   = "training_data.csv"         # Fichier CSV d'entrée
MODEL_FILE = "model.pkl"                 # Fichier de sortie (modèle final)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START train_model ===")


def main():
    """
    1) Charge CSV, check 'date', 'label'.
    2) Tri par date, split 80% (train_val) / 20% (final_test).
    3) Sur train_val => TSCV(10) + RandomizedSearchCV(n_iter=50, scoring='f1').
    4) hold-out final => évalue best_model (F1 prioritaire sur la classe 1).
    5) Re-train sur 100% => final_model, rapport in-sample global.
    6) Sauvegarde final_model => model.pkl
    """

    # --n_iter <int> (optionnel) => par défaut 30
    n_iter = 30
    for i, arg in enumerate(sys.argv):
        if arg == "--n_iter" and (i+1 < len(sys.argv)):
            try:
                n_iter = int(sys.argv[i+1])
            except ValueError:
                pass

    if not os.path.exists(CSV_FILE):
        msg = f"[ERREUR] Fichier CSV introuvable : {CSV_FILE}"
        print(msg)
        logging.error(msg)
        return

    df = pd.read_csv(CSV_FILE)
    logging.info(f"CSV => {df.shape[0]} lignes, {df.shape[1]} colonnes.")
    print(f"[INFO] CSV chargé: {len(df)} lignes, {len(df.columns)} colonnes.")

    if "label" not in df.columns:
        msg = "[ERREUR] Colonne 'label' absente => classification impossible."
        print(msg)
        logging.error(msg)
        return

    if "date" not in df.columns:
        msg = "[ERREUR] Colonne 'date' absente => pas de split chronologique."
        print(msg)
        logging.error(msg)
        return

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df.dropna(subset=["date"], inplace=True)
    df.sort_values("date", inplace=True)

    # Features susceptibles d'être présentes dans le CSV
    features = [
        "close", "volume", "market_cap",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr",
        "btc_daily_change", "eth_daily_change", "sol_daily_change"
    ]
    target = "label"

    # Drop lignes NaN
    sub = df.dropna(subset=features + [target]).copy()
    if sub.empty:
        msg = "[ERREUR] Aucune ligne exploitable => dataset vide après dropna."
        print(msg)
        logging.error(msg)
        return

    # Split 80% / 20% chrono
    cut_index = int(0.8 * len(sub))
    train_val_df = sub.iloc[:cut_index].reset_index(drop=True)
    final_test_df = sub.iloc[cut_index:].reset_index(drop=True)

    X_tv = train_val_df[features]
    y_tv = train_val_df[target].astype(int)

    X_ft = final_test_df[features]
    y_ft = final_test_df[target].astype(int)

    logging.info(f"Train_val => {len(X_tv)} lignes, Final_test => {len(X_ft)}.")
    print(f"[INFO] train_val = {len(X_tv)}, final_test = {len(X_ft)}")

    # Pipeline initial
    if IMBLEARN_OK:
        steps = [
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=42)),
            ("clf", RandomForestClassifier(random_state=42))
        ]
        PipelineClass = ImbPipeline
        logging.info("Pipeline: StandardScaler + SMOTE + RandomForest")
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

    # Grille d'hyperparams
    param_distributions = {
        "clf__n_estimators": [100, 200, 300, 500],
        "clf__max_depth": [10, 15, 20, None],
        "clf__min_samples_split": [2, 5, 10],
        "clf__min_samples_leaf": [1, 2, 5],
        "clf__max_features": ["sqrt", "log2", None],
        "clf__bootstrap": [True, False],
        "clf__class_weight": [None, "balanced", "balanced_subsample",
                              {0:1,1:2}, {0:1,1:3}]
    }

    tscv = TimeSeriesSplit(n_splits=10)

    # SCORING = 'f1' => On vise le f1 (classe 1) plus équilibré
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

    logging.info(f"RandomizedSearchCV => TSCV(10), n_iter={n_iter}, scoring='f1'")
    print("[INFO] RandomizedSearch => scoring='f1'. Patience ...")

    search.fit(X_tv, y_tv)
    best_model_cv = search.best_estimator_
    best_params = search.best_params_
    logging.info(f"Best Params => {best_params}")
    print("\n[RESULT] Hyperparamètres retenus =>", best_params)

    # Éval sur hold-out final
    y_pred_ft = best_model_cv.predict(X_ft)
    rep_ft = classification_report(y_ft, y_pred_ft, digits=3)
    logging.info("\n[Hold-out final test] " + rep_ft)
    print("\n=== Rapport hold-out final test (f1 classe 1 prioritaire) ===")
    print(rep_ft)

    # Re-train sur 100%
    final_model = build_final_model(best_params, sub, features, target)

    # Rapports sur 100%
    X_all = sub[features].reset_index(drop=True)
    y_all = sub[target].astype(int).reset_index(drop=True)

    y_pred_all = final_model.predict(X_all)
    rep_all = classification_report(y_all, y_pred_all, digits=3)
    logging.info("\n[In-sample 100%] " + rep_all)
    print("\n=== Rapport final_model sur 100% in-sample ===")
    print(rep_all)

    joblib.dump(final_model, MODEL_FILE)
    logging.info(f"Final model sauvegardé => {MODEL_FILE}")
    print(f"[OK] Final model sauvegardé => {MODEL_FILE}")


def build_final_model(best_params, full_df, features, target):
    """
    Construit un pipeline final (scaler + SMOTE + RF)
    avec EXACTEMENT les hyperparams best_params.
    Entraîne sur 100% du dataset pour usage en production.
    """
    if IMBLEARN_OK:
        final_steps = [
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=42)),
            ("clf", RandomForestClassifier(
                random_state=42,
                **extract_rf_params(best_params)
            ))
        ]
        from imblearn.pipeline import Pipeline as PipelineClass2
        logging.info("[build_final_model] => SMOTE activé")
    else:
        final_steps = [
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                random_state=42,
                **extract_rf_params(best_params)
            ))
        ]
        from sklearn.pipeline import Pipeline as PipelineClass2
        logging.info("[build_final_model] => Fallback RF")

    final_model = PipelineClass2(final_steps)
    X_all = full_df[features].reset_index(drop=True)
    y_all = full_df[target].astype(int).reset_index(drop=True)

    final_model.fit(X_all, y_all)
    return final_model


def extract_rf_params(params_dict):
    """
    Convertit { 'clf__xxx': ... } en { 'xxx': ... } 
    pour initialiser RandomForestClassifier.
    """
    rf_params = {}
    for k, v in params_dict.items():
        if k.startswith("clf__"):
            real_key = k.replace("clf__", "")
            rf_params[real_key] = v
    return rf_params


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
# coding: utf-8

"""
Script d'entraînement d'un modèle pour détecter des hausses >= 5% en 2 jours (label=1).
- Chargement du CSV (généré par build_csv.py, SHIFT_DAYS=2 et THRESHOLD=0.05).
- Ajout possible de nouvelles features (btc_daily_change, eth_daily_change).
- Pipeline: StandardScaler + (SMOTE si imblearn dispo) + RandomForest.
- Recherche d'hyperparamètres via RandomizedSearchCV (50 itérations, 7 folds).
- Sauvegarde du meilleur modèle (model.pkl).
"""

import os
import logging
import pandas as pd
import numpy as np
import joblib

from sklearn.model_selection import (
    train_test_split,
    RandomizedSearchCV,
    StratifiedKFold
)
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report

# Tentative d'import d'imblearn (pour SMOTE)
try:
    from imblearn.over_sampling import SMOTE
    from imblearn.pipeline import Pipeline as ImbPipeline
    IMBLEARN_OK = True
except ImportError:
    IMBLEARN_OK = False
    print("[WARNING] 'imbalanced-learn' non installé => SMOTE indisponible.")

# Pipeline fallback scikit-learn
from sklearn.pipeline import Pipeline as SkPipeline

########################################
# CONFIG
########################################
LOG_FILE   = "train_model.log"
CSV_FILE   = "training_data.csv"  # Fichier CSV généré (avec colonnes btc_daily_change, eth_daily_change si code build_csv modifié)
MODEL_FILE = "model.pkl"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START train_model ===")


def main():
    """
    1) Vérifie la présence de 'training_data.csv'.
    2) Charge le dataset, vérifie 'label' + les features voulues.
    3) Split (80/20) stratifié.
    4) Pipeline: StandardScaler + (SMOTE) + RandomForest.
    5) RandomizedSearchCV => 50 itérations, 7 folds => scoring="f1".
    6) Évalue le meilleur modèle => classification_report
    7) Sauvegarde dans model.pkl
    """

    # 1) Check CSV
    if not os.path.exists(CSV_FILE):
        msg = f"[ERREUR] Fichier CSV introuvable : {CSV_FILE}"
        print(msg)
        logging.error(msg)
        return

    # 2) Lecture CSV
    df = pd.read_csv(CSV_FILE)
    logging.info(f"CSV => {df.shape[0]} lignes, {df.shape[1]} colonnes.")
    if "label" not in df.columns:
        msg = "[ERREUR] Colonne 'label' manquante."
        print(msg)
        logging.error(msg)
        return

    # Exemple de features (vous pouvez inclure btc_daily_change / eth_daily_change si vous le voulez)
    features = [
        "close", "volume", "market_cap",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr",
        # Ajout si vous le jugez pertinent :
        "btc_daily_change", 
        "eth_daily_change"
    ]
    target = "label"

    # Vérif colonnes
    missing = [col for col in features if col not in df.columns]
    if missing:
        msg = f"[ERREUR] Colonnes manquantes: {missing}"
        print(msg)
        logging.error(msg)
        return

    # Drop NaN
    sub = df.dropna(subset=features + [target]).copy()
    if sub.empty:
        msg = "[ERREUR] Aucune ligne exploitable après dropna."
        print(msg)
        logging.error(msg)
        return

    X = sub[features]
    y = sub[target].astype(int)

    # 3) Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    logging.info(f"Split => train={len(X_train)}, test={len(X_test)}")

    # 4) Choix du pipeline
    if IMBLEARN_OK:
        steps = [
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=42)),
            ("clf", RandomForestClassifier(random_state=42))
        ]
        pipeline_class = ImbPipeline
        logging.info("Pipeline: StandardScaler + SMOTE + RandomForest")
    else:
        steps = [
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                class_weight="balanced_subsample",
                random_state=42
            ))
        ]
        pipeline_class = SkPipeline
        logging.info("Pipeline fallback: StandardScaler + RF(class_weight=balanced_subsample)")

    pipe = pipeline_class(steps)

    # 5) Espace de recherche
    param_distributions = {
        "clf__n_estimators":      [100, 200, 300, 500],
        "clf__max_depth":         [10, 15, 20, None],
        "clf__min_samples_split": [2, 5, 10],
        "clf__min_samples_leaf":  [1, 2, 5],
        "clf__max_features":      ["sqrt", "log2", None],
        "clf__bootstrap":         [True, False]
    }

    from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold
    cv = StratifiedKFold(n_splits=7, shuffle=True, random_state=42)

    search = RandomizedSearchCV(
        estimator=pipe,
        param_distributions=param_distributions,
        n_iter=60,
        scoring="f1",
        n_jobs=-1,
        cv=cv,
        verbose=1,
        random_state=42
    )

    logging.info("Lancement RandomizedSearchCV (7 folds, 60 itérations).")
    print("[INFO] Recherche d'hyperparamètres => patience ...")
    search.fit(X_train, y_train)

    best_model = search.best_estimator_
    logging.info(f"Best Params => {search.best_params_}")
    print("\n[RESULT] Meilleurs hyperparamètres =>", search.best_params_)

    # 6) Evaluation
    y_pred = best_model.predict(X_test)
    rep = classification_report(y_test, y_pred, digits=3)
    logging.info("\n" + rep)
    print("\n=== Rapport final ===")
    print(rep)

    # 7) Sauvegarde
    joblib.dump(best_model, MODEL_FILE)
    logging.info(f"Modèle sauvegardé => {MODEL_FILE}")
    print(f"\n[OK] Modèle sauvegardé => {MODEL_FILE}")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
# coding: utf-8

"""
Script d'entraînement d'un modèle pour détecter des hausses >= 5% en 2 jours (label=1).
- Chargement du CSV (généré par build_csv.py, avec SHIFT_DAYS=2 et THRESHOLD=0.05).
- Sélection de features pertinents.
- Pipeline avec StandardScaler + (optionnel SMOTE si imblearn est dispo) + RandomForest.
- Recherche d'hyperparamètres via RandomizedSearchCV (50 itérations, 5 folds).
- Sauvegarde du meilleur modèle.
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
# CONFIG LOGGING / FICHIERS
########################################
LOG_FILE   = "train_model.log"
CSV_FILE   = "training_data.csv"  # Fichier CSV généré
MODEL_FILE = "model.pkl"          # Sauvegarde du modèle

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START train_model ===")


def main():
    """
    1. Vérifie la présence de 'training_data.csv'.
    2. Charge le dataset, vérifie la colonne 'label' et les features.
    3. Split stratifié (80% train, 20% test).
    4. Pipeline: StandardScaler + (SMOTE si possible) + RandomForest.
    5. RandomizedSearchCV (50 itérations, scoring=f1).
    6. Évalue sur le set de test.
    7. Sauvegarde le meilleur modèle dans model.pkl.
    """

    # 1) Vérification existence CSV
    if not os.path.exists(CSV_FILE):
        msg = f"[ERREUR] Fichier CSV introuvable: {CSV_FILE}"
        print(msg)
        logging.error(msg)
        return

    # 2) Chargement du CSV
    df = pd.read_csv(CSV_FILE)
    nrows, ncols = df.shape
    logging.info(f"CSV: {nrows} lignes, {ncols} colonnes.")
    if "label" not in df.columns:
        msg = "[ERREUR] Colonne 'label' manquante dans le CSV."
        print(msg)
        logging.error(msg)
        return

    # Exemple de features (adaptez selon vos colonnes effectives)
    features = [
        "close", "volume", "market_cap",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr"
    ]
    target = "label"

    # Vérification des colonnes
    missing = [col for col in features if col not in df.columns]
    if missing:
        msg = f"[ERREUR] Colonnes manquantes dans le CSV: {missing}"
        print(msg)
        logging.error(msg)
        return

    # Retrait des lignes NaN
    sub = df.dropna(subset=features + [target]).copy()
    if sub.empty:
        msg = "[ERREUR] Aucune donnée valide après dropna(subset=features+label)."
        print(msg)
        logging.error(msg)
        return

    X = sub[features]
    y = sub[target].astype(int)

    # 3) Split (stratifié pour conserver ratio des classes)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    logging.info(f"Split => train={len(X_train)}, test={len(X_test)}")

    # 4) Choix du pipeline (avec ou sans SMOTE)
    if IMBLEARN_OK:
        # Pipeline Imb avec SMOTE
        steps = [
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=42)),  # sur-échantillonne la classe 1
            ("clf", RandomForestClassifier(random_state=42))
        ]
        pipeline_class = ImbPipeline
        logging.info("Pipeline: StandardScaler + SMOTE + RandomForest")
    else:
        # Fallback scikit-learn
        steps = [
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                class_weight="balanced_subsample",
                random_state=42
            ))
        ]
        pipeline_class = SkPipeline
        logging.info("Pipeline fallback: StandardScaler + RF (class_weight=balanced_subsample)")

    pipe = pipeline_class(steps)

    # 5) Espace de recherche + RandomizedSearchCV
    param_distributions = {
        "clf__n_estimators":      [100, 200, 300, 500],
        "clf__max_depth":         [10, 15, 20, None],
        "clf__min_samples_split": [2, 5, 10],
        "clf__min_samples_leaf":  [1, 2, 5],
        "clf__max_features":      ["sqrt", "log2", None],
        "clf__bootstrap":         [True, False]
    }

    cv = StratifiedKFold(n_splits=7, shuffle=True, random_state=42)

    search = RandomizedSearchCV(
        estimator=pipe,
        param_distributions=param_distributions,
        n_iter=50,      # 50 itérations => compromis entre temps & perf
        scoring="f1",   # f1 = focus classe minoritaire
        n_jobs=-1,
        cv=cv,
        verbose=1,
        random_state=42
    )

    logging.info("Lancement RandomizedSearchCV (7 folds, 50 itérations).")
    print("\n[INFO] Recherche d'hyperparamètres (RandomizedSearchCV) ...")
    search.fit(X_train, y_train)

    best_model = search.best_estimator_
    logging.info(f"Best Params: {search.best_params_}")
    print("\n[RESULT] Meilleurs hyperparamètres =>", search.best_params_)

    # 6) Évaluation sur le set de test
    y_pred = best_model.predict(X_test)
    rep = classification_report(y_test, y_pred, digits=3)
    logging.info("\n" + rep)
    print("\n=== Rapport sur le set de test ===")
    print(rep)

    # 7) Sauvegarde
    joblib.dump(best_model, MODEL_FILE)
    logging.info(f"Modèle sauvegardé => {MODEL_FILE}")
    print(f"\n[OK] Modèle sauvegardé => {MODEL_FILE}")


if __name__ == "__main__":
    main()
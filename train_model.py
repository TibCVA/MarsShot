#!/usr/bin/env python3
# coding: utf-8

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

########################################
# TENTATIVE import d'imblearn (SMOTE + Pipeline)
########################################
try:
    from imblearn.over_sampling import SMOTE
    from imblearn.pipeline import Pipeline as ImbPipeline
    IMBLEARN_OK = True
except ImportError:
    IMBLEARN_OK = False
    print("[WARNING] 'imbalanced-learn' non disponible => pas de SMOTE.")

########################################
# ALTERNATIVE pipeline scikit-learn
########################################
from sklearn.pipeline import Pipeline as SkPipeline

########################################
# CONFIG
########################################
LOG_FILE   = "train_model.log"
CSV_FILE   = "training_data.csv"  # Fichier généré par build_csv
MODEL_FILE = "model.pkl"          # Nom sous lequel on sauvegarde le modèle

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START train_model ===")


def main():
    """ 
    Script d'entraînement:
      - Lecture CSV
      - Sélection features/label
      - Pipeline = [StandardScaler] + [SMOTE?] + [RandomForest]
      - RandomizedSearchCV (5 folds, 50 itérations)
      - Sauvegarde du meilleur modèle
    """

    # 1) Vérif CSV
    if not os.path.exists(CSV_FILE):
        print(f"[ERREUR] CSV '{CSV_FILE}' introuvable. Annulation.")
        logging.error("Fichier CSV manquant.")
        return

    # 2) Lecture CSV
    df = pd.read_csv(CSV_FILE)
    logging.info(f"CSV: {df.shape[0]} lignes, {df.shape[1]} colonnes.")
    if "label" not in df.columns:
        print("[ERREUR] Pas de colonne 'label'.")
        logging.error("Colonne 'label' manquante.")
        return

    # Ex. de features — adaptez selon votre CSV.
    features = [
        "close", "volume", "market_cap",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr"
    ]
    target = "label"

    # Vérif colonnes
    missing = [col for col in features if col not in df.columns]
    if missing:
        print("[ERREUR] Colonnes manquantes:", missing)
        logging.error(f"Colonnes manquantes: {missing}")
        return

    # Drop NaN
    sub = df.dropna(subset=features + [target]).copy()
    if sub.empty:
        print("[ERREUR] Aucune ligne exploitable (NaN).")
        logging.error("Données vides après dropna.")
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
        # => Pipeline avec SMOTE
        steps = [
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=42)),
            ("clf", RandomForestClassifier(random_state=42))
        ]
        pipeline_class = ImbPipeline
        logging.info("Pipeline IMB + SMOTE.")
    else:
        # => Pipeline scikit-learn
        #    On met class_weight="balanced_subsample" pour compenser
        #    partiellement l'absence de SMOTE
        steps = [
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                class_weight="balanced_subsample",
                random_state=42
            ))
        ]
        pipeline_class = SkPipeline
        logging.info("Pipeline SKLearn sans SMOTE (fallback).")

    pipe = pipeline_class(steps)

    # 5) Espace de recherche d'hyperparamètres
    param_distributions = {
        "clf__n_estimators":      [100, 200, 300, 500, 800, 1200],
        "clf__max_depth":         [5, 10, 15, 20, 30, None],
        "clf__min_samples_split": [2, 5, 10, 20],
        "clf__min_samples_leaf":  [1, 2, 5, 10],
        "clf__max_features":      ["sqrt", "log2", None],
        "clf__bootstrap":         [True, False]
    }

    # 6) RandomizedSearchCV
    from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    search = RandomizedSearchCV(
        estimator=pipe,
        param_distributions=param_distributions,
        n_iter=50,          # Nombre d'itérations
        scoring="f1",       # f1 => focus sur la classe minoritaire
        n_jobs=-1,
        cv=cv,
        verbose=1,
        random_state=42
    )

    print("\n[INFO] Recherche d'hyperparamètres (peut prendre du temps) ...")
    logging.info("Début RandomizedSearchCV avec 5 folds, 50 itérations.")
    search.fit(X_train, y_train)

    best_model = search.best_estimator_
    logging.info(f"Best Params: {search.best_params_}")
    print("[RESULT] Meilleurs hyperparamètres =>", search.best_params_)

    # 7) Évaluation
    y_pred = best_model.predict(X_test)
    rep = classification_report(y_test, y_pred, digits=3)
    logging.info("\n" + rep)
    print("\n=== Rapport final sur test ===")
    print(rep)

    # 8) Sauvegarde
    joblib.dump(best_model, MODEL_FILE)
    logging.info(f"Modèle sauvegardé => {MODEL_FILE}")
    print(f"\n[OK] Modèle sauvegardé => {MODEL_FILE}")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
# coding: utf-8

import os
import logging
import pandas as pd
import numpy as np

from sklearn.model_selection import (
    train_test_split,
    RandomizedSearchCV,
    StratifiedKFold
)
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report
import joblib

# --- Nouvelle importation du Pipeline d'imblearn ---
try:
    from imblearn.pipeline import Pipeline  # <-- pipeline compatible SMOTE
    from imblearn.over_sampling import SMOTE
    IMBLEARN_AVAILABLE = True
except ImportError:
    # On pourra fallback sur scikit pipeline + class_weight="balanced_subsample"
    IMBLEARN_AVAILABLE = False
    print("[WARN] 'imbalanced-learn' n'est pas installé => SMOTE désactivé.")

########################################
# CONFIG
########################################

LOG_FILE = "train_model.log"
CSV_FILE = "training_data.csv"   # Fichier généré par build_csv.py
MODEL_FILE = "model.pkl"         # Le modèle final sera sauvegardé ici

# Configuration du logger
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START train_model ===")

########################################
# SCRIPT PRINCIPAL
########################################
def main():
    """
    Script d'entraînement d'un RandomForest pour prédire la colonne 'label' (0/1).
    - 1 => token a pris +XX% (ex. 15% ou 30%) sur 2 jours, 0 => sinon.
    - On utilise un Pipeline imblearn si possible :
         [Scaler] -> [SMOTE] -> [RandomForest].
      Sinon on fallback :
         [Scaler] -> [RF avec class_weight='balanced_subsample'].
    - RandomizedSearchCV sur un espace de paramètres plus large => plus long,
      mais potentiellement plus performant.
    """

    # 1) Vérification de l'existence du CSV
    if not os.path.exists(CSV_FILE):
        print(f"[ERREUR] Fichier CSV '{CSV_FILE}' introuvable.")
        logging.error(f"CSV introuvable: {CSV_FILE}")
        return

    # 2) Chargement du CSV
    df = pd.read_csv(CSV_FILE)
    logging.info(f"CSV chargé => {df.shape[0]} lignes, {df.shape[1]} colonnes.")

    if "label" not in df.columns:
        print("[ERREUR] Pas de colonne 'label' => impossible d'entraîner.")
        logging.error("Colonne 'label' manquante.")
        return

    # Ex. de features => adaptez selon vos colonnes
    features = [
        "close", "volume", "market_cap",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr"
    ]
    target = "label"

    # Vérification
    missing_cols = [f for f in features if f not in df.columns]
    if missing_cols:
        print("[ERREUR] Colonnes manquantes:", missing_cols)
        logging.error(f"Colonnes manquantes: {missing_cols}")
        return

    # Filtre NaN
    sub = df.dropna(subset=features + [target]).copy()
    if sub.empty:
        print("[ERREUR] Toutes les données sont NaN => impossible d'entraîner.")
        logging.error("Données vides après dropna.")
        return

    X = sub[features]
    y = sub[target].astype(int)

    # 3) Split train/test (stratifié sur y)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )
    logging.info(f"Split => train={len(X_train)}, test={len(X_test)}")

    # 4) Construction du Pipeline
    if IMBLEARN_AVAILABLE:
        # Pipeline d'imblearn avec SMOTE
        steps = [
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=42)),
            ("clf", RandomForestClassifier(random_state=42))
        ]
    else:
        # Fallback : scikit pipeline, class_weight='balanced_subsample'
        from sklearn.pipeline import Pipeline as SKLPipeline
        steps = [
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                class_weight="balanced_subsample",
                random_state=42
            ))
        ]
        Pipeline = SKLPipeline  # on redéfinit Pipeline pour la suite

    pipe = Pipeline(steps)

    # 5) Espace de recherche d'hyperparamètres
    #    On inclut plus de possibilités => plus long.
    param_distributions = {
        "clf__n_estimators":      [100, 200, 300, 500, 800, 1200],
        "clf__max_depth":         [5, 10, 15, 20, 30, None],
        "clf__min_samples_split": [2, 5, 10, 20],
        "clf__min_samples_leaf":  [1, 2, 5, 10],
        "clf__max_features":      ["sqrt", "log2", None],
        "clf__bootstrap":         [True, False]
    }

    # 6) Setup du RandomizedSearchCV
    from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold
    cv = StratifiedKFold(n_splits=10, shuffle=True, random_state=42)  # 10 folds

    search = RandomizedSearchCV(
        estimator=pipe,
        param_distributions=param_distributions,
        n_iter=50,          # 50 tirages => plus long, potentiellement mieux
        scoring="f1",       # f1 => compromis entre precision et recall
        n_jobs=-1,          # parallélise
        cv=cv,
        verbose=1,
        random_state=42
    )

    print("\n[INFO] Lancement de la recherche d'hyperparamètres (long).")
    search.fit(X_train, y_train)

    best_model = search.best_estimator_
    logging.info(f"Best params: {search.best_params_}")
    print("[RESULT] Meilleurs hyperparamètres =>", search.best_params_)

    # 7) Évaluation finale
    y_pred = best_model.predict(X_test)
    rep = classification_report(y_test, y_pred, digits=3)
    logging.info("\n" + rep)
    print("\n=== Rapport final sur le set de test ===")
    print(rep)

    # 8) Sauvegarde du modèle
    joblib.dump(best_model, MODEL_FILE)
    logging.info(f"Modèle sauvegardé => {MODEL_FILE}")
    print(f"\n[OK] Modèle sauvegardé => {MODEL_FILE}")

if __name__ == "__main__":
    main()
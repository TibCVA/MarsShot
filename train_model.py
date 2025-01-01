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
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report
import joblib

# Tentative d'import de SMOTE (imbalanced-learn)
try:
    from imblearn.over_sampling import SMOTE
    IMBLEARN_AVAILABLE = True
except ImportError:
    IMBLEARN_AVAILABLE = False
    print("[WARN] imbalanced-learn n'est pas installé => SMOTE sera désactivé.")

########################################
# CONFIG
########################################
LOG_FILE = "train_model.log"
CSV_FILE = "training_data.csv"   # Doit contenir une colonne 'label' (0/1).
MODEL_FILE = "model.pkl"         # Le modèle final sera sauvegardé ici.

# Configuration du logger
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START train_model ===")

########################################
# FONCTION PRINCIPALE
########################################
def main():
    """
    Script d'entraînement d'un RandomForest pour prédire la colonne 'label':
      - 1 = token qui prend +XX% (ex. +30%) sur 2 jours,
      - 0 = sinon.
    
    Étapes :
      1) Vérifie la présence du CSV et de la colonne 'label'.
      2) Charge et nettoie (dropna).
      3) Split train/test (stratifié).
      4) Pipeline : (Scaler) + [SMOTE]* + RandomForest.
      5) RandomizedSearchCV => hyperparamètres + scoring="f1" (vous pouvez changer).
      6) Évaluation sur le set de test final.
      7) Sauvegarde du meilleur modèle (model.pkl).

    * SMOTE (suréchantillonnage) est appliqué si imblearn est dispo,
      utile pour la classe 1 rare (hausses).
    """
    # 1) Vérification du CSV
    if not os.path.exists(CSV_FILE):
        print(f"[ERREUR] Fichier CSV '{CSV_FILE}' introuvable.")
        logging.error(f"CSV introuvable: {CSV_FILE}")
        return

    # 2) Chargement du CSV
    df = pd.read_csv(CSV_FILE)
    logging.info(f"CSV chargé: {df.shape[0]} lignes, {df.shape[1]} colonnes.")
    
    if "label" not in df.columns:
        print("[ERREUR] Pas de colonne 'label' dans le CSV => impossible d'entraîner.")
        logging.error("Colonne 'label' manquante.")
        return

    # Exemple de features (à adapter selon vos colonnes).
    # On suppose que vous avez déjà enlevé 'variation' si vous ne voulez pas l'utiliser.
    features = [
        "close", "volume", "market_cap",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr"
    ]
    target = "label"

    # Vérifie la présence de ces features
    missing_features = [f for f in features if f not in df.columns]
    if missing_features:
        print("[ERREUR] Colonnes manquantes:", missing_features)
        logging.error(f"Colonnes manquantes: {missing_features}")
        return

    # Filtrage NaN
    sub = df.dropna(subset=features + [target]).copy()
    if sub.empty:
        print("[ERREUR] Toutes les données sont NaN => impossible d'entraîner.")
        logging.error("Données NaN => aucune ligne utilisable.")
        return
    
    X = sub[features]
    y = sub[target].astype(int)

    # 3) Split train/test
    # On prend, par exemple, 80-85% train, 15-20% test => ici 80/20 pour la démo
    # Vous pouvez aussi faire 70/30, selon la taille et la rareté de la classe 1.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )
    logging.info(f"Split: train={len(X_train)}, test={len(X_test)}")

    # 4) Construction du pipeline
    steps = []
    # Scaling
    steps.append(("scaler", StandardScaler()))

    # SMOTE si imblearn est dispo
    if IMBLEARN_AVAILABLE:
        steps.append(("smote", SMOTE(random_state=42)))
        # RandomForest sans class_weight => SMOTE gère déjà.
        forest = RandomForestClassifier(random_state=42)
    else:
        print("[INFO] SMOTE désactivé => on utilise class_weight='balanced_subsample'.")
        forest = RandomForestClassifier(
            class_weight="balanced_subsample",
            random_state=42
        )

    steps.append(("clf", forest))
    pipe = Pipeline(steps)

    # 5) RandomizedSearchCV
    #    On élargit l'espace de recherche => plus long, mais potentiellement meilleur.
    #    n_iter=50 => 50 configurations testées, scoring="f1".
    param_distributions = {
        "clf__n_estimators":      [100, 200, 300, 500, 800, 1200],
        "clf__max_depth":         [5, 10, 15, 20, 30, None],
        "clf__min_samples_split": [2, 5, 10, 20],
        "clf__min_samples_leaf":  [1, 2, 5, 10],
        "clf__max_features":      ["sqrt", "log2", None],   # None => toutes
        "clf__bootstrap":         [True, False]
    }

    cv = StratifiedKFold(n_splits=10, shuffle=True, random_state=42)

    search = RandomizedSearchCV(
        estimator=pipe,
        param_distributions=param_distributions,
        n_iter=50,           # augmentez si vous voulez encore plus
        scoring="f1",        # f1 => compromis précision/rappel
        n_jobs=-1,           # parallélise
        cv=cv,
        verbose=1,
        random_state=42
    )

    print("\n[INFO] Lancement de la recherche d'hyperparamètres (peut être long)...")
    search.fit(X_train, y_train)

    best_model = search.best_estimator_
    logging.info(f"Best params: {search.best_params_}")
    print("[RESULT] Meilleurs paramètres:", search.best_params_)

    # 6) Évaluation finale sur le test set
    y_pred = best_model.predict(X_test)
    report = classification_report(y_test, y_pred, digits=3)
    logging.info("\n" + report)
    print("\n=== Rapport sur le test set ===")
    print(report)

    # 7) Sauvegarde du modèle
    joblib.dump(best_model, MODEL_FILE)
    logging.info(f"Modèle sauvegardé => {MODEL_FILE}")
    print(f"\n[OK] Modèle final sauvegardé dans: {MODEL_FILE}")

if __name__ == "__main__":
    main()
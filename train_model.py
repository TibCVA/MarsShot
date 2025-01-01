#!/usr/bin/env python3
# coding: utf-8

import os
import logging
import pandas as pd
import numpy as np

from sklearn.model_selection import train_test_split, RandomizedSearchCV, StratifiedKFold
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report
import joblib

# Imbalanced-learn pour gérer le déséquilibre
from imblearn.over_sampling import RandomOverSampler
from imblearn.pipeline import Pipeline as ImbPipeline

#####################################
# CONFIGURATIONS
#####################################
LOG_FILE = "train_model.log"
CSV_FILE = "training_data.csv"   # Fichier CSV généré par build_csv.py
MODEL_FILE = "model.pkl"         # Nom du fichier de sortie pour le modèle

# Configuration du logger
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START train_model ===")


#####################################
# SCRIPT PRINCIPAL
#####################################
def main():
    """
    Entraîne un modèle ML (RandomForest) pour prédire la probabilité
    qu'un token prenne +30% sur 2 jours (colonne 'label'=1).
    
    Points clés pour améliorer la fiabilité vis-à-vis du déséquilibre :
      - Sur-échantillonnage (RandomOverSampler) des exemples positifs
        directement dans le pipeline.
      - Évaluation basée sur F1-score, pour mieux considérer la classe 1.
      - StratifiedKFold et train_test_split(stratify=y).
    """

    # 1) Vérifier l'existence du CSV
    if not os.path.exists(CSV_FILE):
        logging.error(f"Fichier CSV introuvable: {CSV_FILE}")
        print("Aucun CSV => entraînement impossible. Vérifiez build_csv.")
        return

    # 2) Charger les données
    df = pd.read_csv(CSV_FILE)
    logging.info(f"CSV chargé: {CSV_FILE} => {df.shape[0]} lignes, {df.shape[1]} colonnes")

    # 3) Vérifier la colonne 'label'
    if "label" not in df.columns:
        logging.error("Colonne 'label' manquante => entraînement impossible.")
        print("Pas de colonne 'label' => entraînement impossible.")
        return

    # 4) Spécifier les features souhaitées
    #    IMPORTANT: assurez-vous que ces colonnes existent réellement dans le CSV
    #    On prend un exemple : close, volume, market_cap, variation, galaxy_score,
    #    alt_rank, sentiment, rsi, macd, atr
    features = [
        "close", "volume", "market_cap", "variation",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr"
    ]
    target = "label"

    # Vérifier l'existence des colonnes
    missing_cols = [col for col in features if col not in df.columns]
    if missing_cols:
        logging.error(f"Colonnes manquantes dans le CSV: {missing_cols}")
        print(f"Colonnes manquantes dans le CSV: {missing_cols}\nImpossible d'entraîner.")
        return

    # 5) Retirer les lignes NaN
    sub = df.dropna(subset=features + [target]).copy()
    if sub.empty:
        logging.error("Toutes les données sont NaN => impossible d'entraîner.")
        print("Aucune donnée valide => entraînement impossible.")
        return

    X = sub[features]
    y = sub[target].astype(int)

    # 6) Split train/test (stratifié)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    logging.info(f"Split => train={len(X_train)}, test={len(X_test)}")

    # 7) Pipeline incluant :
    #    - OverSampling (RandomOverSampler) pour dupliquer la classe minoritaire
    #    - Scaler (StandardScaler) pour normaliser
    #    - RandomForestClassifier
    ros = RandomOverSampler(random_state=42)
    rf = RandomForestClassifier(
        class_weight=None,  # On laisse None car on sur-échantillonne déjà
        random_state=42
    )

    # Imbalanced-learn Pipeline
    pipe = ImbPipeline([
        ("oversample", ros),
        ("scaler", StandardScaler()),
        ("clf", rf)
    ])

    # 8) Définition de l'espace de recherche
    param_distributions = {
        "clf__n_estimators":    [50, 100, 200, 300, 500, 800],
        "clf__max_depth":       [5, 10, 15, 20, None],
        "clf__min_samples_split": [2, 5, 10],
        "clf__min_samples_leaf":  [1, 2, 5],
    }

    from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    search = RandomizedSearchCV(
        estimator=pipe,
        param_distributions=param_distributions,
        n_iter=20,
        scoring="f1",        # f1-score pour mieux prendre en compte la classe 1
        n_jobs=-1,           # utilise tous les cœurs
        cv=cv,
        random_state=42,
        verbose=1
    )

    # 9) Entraînement + recherche d'hyperparamètres
    search.fit(X_train, y_train)
    best_model = search.best_estimator_

    logging.info(f"Meilleurs paramètres: {search.best_params_}")
    print("Meilleurs hyperparamètres trouvés:", search.best_params_)

    # 10) Évaluation finale sur le set de test
    y_pred = best_model.predict(X_test)
    report = classification_report(y_test, y_pred, digits=3)
    logging.info("\n" + report)
    print("\n===== Évaluation finale sur le set de test =====")
    print(report)

    # 11) Sauvegarde du meilleur modèle
    joblib.dump(best_model, MODEL_FILE)
    logging.info(f"Modèle sauvegardé => {MODEL_FILE}")
    print(f"Modèle sauvegardé => {MODEL_FILE}")


if __name__ == "__main__":
    main()
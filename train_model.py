#!/usr/bin/env python3
# coding: utf-8

import os
import logging
import pandas as pd
import numpy as np

from sklearn.model_selection import train_test_split, RandomizedSearchCV, StratifiedKFold
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report
import joblib
import scipy.stats as st

#####################################
# CONFIGURATIONS
#####################################
LOG_FILE = "train_model.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START train_model ===")

CSV_FILE = "training_data.csv"  # Chemin vers votre dataset
MODEL_FILE = "model.pkl"        # Nom du fichier de sortie pour le modèle

#####################################
# SCRIPT PRINCIPAL
#####################################
def main():
    """
    Entraîne un modèle ML (RandomForest) pour prédire la probabilité
    qu'un token prenne +30% sur 2 jours (colonne 'label'=1).
    Utilise un pipeline (StandardScaler + RandomForest)
    et une recherche d'hyperparamètres par RandomizedSearchCV.
    """

    # 1) Vérification de l'existence du CSV
    if not os.path.exists(CSV_FILE):
        logging.error(f"Fichier CSV introuvable: {CSV_FILE}")
        print("Aucun CSV => entraînement impossible. Vérifiez build_csv.")
        return

    # 2) Chargement des données
    df = pd.read_csv(CSV_FILE)
    logging.info(f"CSV chargé: {CSV_FILE} => {df.shape[0]} lignes, {df.shape[1]} colonnes")

    # 3) Vérification de la colonne 'label'
    if "label" not in df.columns:
        logging.error("Colonne 'label' manquante => entraînement impossible.")
        print("Pas de colonne 'label' => entraînement impossible.")
        return

    # 4) Sélection des features + label
    #    IMPORTANT: assurez-vous que ces colonnes existent vraiment dans votre CSV.
    #    On inclut : close, volume, market_cap, variation, galaxy_score, alt_rank,
    #               sentiment, rsi, macd, atr
    features = [
        "close", "volume", "market_cap", "variation",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr"
    ]
    target = "label"

    # Vérification que toutes les colonnes de 'features' sont présentes
    missing_cols = [col for col in features if col not in df.columns]
    if missing_cols:
        logging.error(f"Colonnes manquantes: {missing_cols}")
        print(f"Colonnes manquantes dans le CSV: {missing_cols}\nImpossible d'entraîner.")
        return

    # Filtrage des lignes NaN
    sub = df.dropna(subset=features + [target]).copy()
    if sub.empty:
        logging.error("Toutes les données sont NaN => impossible d'entraîner.")
        print("Aucune donnée valide => entraînement impossible.")
        return

    # Définition de X, y
    X = sub[features]
    y = sub[target].astype(int)

    # 5) Séparation train/test
    #    80% pour le train, 20% pour le test => bonne pratique
    #    On stratifie selon y pour préserver le ratio de classes positives vs négatives.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    logging.info(f"Split => train={len(X_train)}, test={len(X_test)}")

    # 6) Création d'un Pipeline: scaling + RandomForest
    #    On met class_weight="balanced_subsample" pour gérer le déséquilibre.
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            class_weight="balanced_subsample",
            random_state=42
        ))
    ])

    # 7) Espace de recherche d'hyperparamètres
    #    On cherche de manière aléatoire ~20 combinaisons sur ces paramètres clés.
    param_distributions = {
        "clf__n_estimators": [50, 100, 200, 300, 500, 800],
        "clf__max_depth": [5, 10, 15, 20, None],
        "clf__min_samples_split": [2, 5, 10],
        "clf__min_samples_leaf": [1, 2, 5]
    }

    # 8) RandomizedSearchCV: on fait 20 itérations, 5 folds,
    #    on cherche à optimiser le F1-score (compromis précision/rappel).
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    search = RandomizedSearchCV(
        estimator=pipe,
        param_distributions=param_distributions,
        n_iter=20,                # Nombre d'échantillons dans l'espace de recherche
        scoring="f1",             # F1 pour mieux gérer la rareté des hausses 30%
        n_jobs=-1,                # Parallélise au max
        cv=cv,
        random_state=42,
        verbose=1
    )

    # 9) Entraînement (avec validation croisée interne pour chaque config)
    search.fit(X_train, y_train)
    logging.info(f"Meilleurs paramètres: {search.best_params_}")
    print("Meilleurs hyperparamètres trouvés:", search.best_params_)

    best_model = search.best_estimator_

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
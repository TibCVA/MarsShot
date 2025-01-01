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
    
    Étapes principales :
      1) Vérifie l'existence du CSV.
      2) Charge les données et vérifie la présence des colonnes requises.
      3) Filtre les lignes NaN.
      4) Split (train/test) stratifié.
      5) Crée un pipeline (scaling + random forest).
      6) Recherche d'hyperparamètres (RandomizedSearchCV).
      7) Évalue le meilleur modèle sur le set de test.
      8) Sauvegarde le modèle dans un fichier .pkl.
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
    #    IMPORTANT: assurez-vous que ces colonnes existent bien dans le CSV.
    #    On inclut par exemple :
    #       close, volume, market_cap, variation, galaxy_score, alt_rank,
    #       sentiment, rsi, macd, atr
    features = [
        "close", "volume", "market_cap", "variation",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr"
    ]
    target = "label"

    # Vérification que toutes les colonnes de 'features' sont présentes
    missing_cols = [col for col in features if col not in df.columns]
    if missing_cols:
        logging.error(f"Colonnes manquantes dans le CSV: {missing_cols}")
        print(f"Colonnes manquantes dans le CSV: {missing_cols}\nImpossible d'entraîner.")
        return

    # Retrait des lignes qui contiennent des NaN
    sub = df.dropna(subset=features + [target]).copy()
    if sub.empty:
        logging.error("Toutes les données sont NaN => impossible d'entraîner.")
        print("Aucune donnée valide => entraînement impossible.")
        return

    X = sub[features]
    y = sub[target].astype(int)

    # 5) Séparation train/test (stratifié)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    logging.info(f"Split => train={len(X_train)}, test={len(X_test)}")

    # 6) Création d'un Pipeline: StandardScaler + RandomForest
    #    On met class_weight="balanced_subsample" pour gérer le déséquilibre.
    from sklearn.pipeline import Pipeline
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            class_weight="balanced_subsample",
            random_state=42
        ))
    ])

    # 7) Définition de l'espace de recherche d'hyperparamètres
    #    On utilise RandomizedSearchCV pour gagner du temps (vs GridSearch).
    param_distributions = {
        "clf__n_estimators":    [50, 100, 200, 300, 500, 800],
        "clf__max_depth":       [5, 10, 15, 20, None],
        "clf__min_samples_split": [2, 5, 10],
        "clf__min_samples_leaf":  [1, 2, 5],
    }

    # On fait 20 itérations, scoring="f1" pour tenir compte du déséquilibre.
    from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    search = RandomizedSearchCV(
        estimator=pipe,
        param_distributions=param_distributions,
        n_iter=20,               # Nombre de combinaisons à tester
        scoring="f1",            # f1 pour gérer la rareté de la classe 1
        n_jobs=-1,               # utilise tous les CPU disponibles
        cv=cv,
        random_state=42,
        verbose=1
    )

    # 8) Lancement de la recherche + entraînement
    search.fit(X_train, y_train)
    logging.info(f"Meilleurs paramètres: {search.best_params_}")
    print("Meilleurs hyperparamètres trouvés:", search.best_params_)

    best_model = search.best_estimator_

    # 9) Évaluation finale sur le set de test
    y_pred = best_model.predict(X_test)
    report = classification_report(y_test, y_pred, digits=3)
    logging.info("\n" + report)
    print("\n===== Évaluation finale sur le set de test =====")
    print(report)

    # 10) Sauvegarde du meilleur modèle
    joblib.dump(best_model, MODEL_FILE)
    logging.info(f"Modèle sauvegardé => {MODEL_FILE}")
    print(f"Modèle sauvegardé => {MODEL_FILE}")

if __name__ == "__main__":
    main()
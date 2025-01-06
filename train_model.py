#!/usr/bin/env python3
# coding: utf-8

"""
train_model.py - Version V8 (focalisée sur le score F1 pour la classe 1)
---------------------------------------------------------------
 - Lecture d'un CSV (avec SHIFT_DAYS, THRESHOLD, etc. déjà appliqués).
 - Séparation temporelle: on réserve la portion la plus récente (~20%) en final_test.
 - Sur le reste (train_val), on effectue un TimeSeriesSplit (TSCV).
 - Pipeline: StandardScaler + SMOTE (si dispo) + RandomForest.
 - RandomizedSearchCV => scoring="f1" (pour viser un compromis précision/rappel).
 - Meilleur modèle ré-entraîné sur l'intégralité du jeu train_val => on évalue sur final_test.
 - Sauvegarde du modèle final.
"""

import os
import logging
import pandas as pd
import numpy as np
import joblib

# sklearn
from sklearn.model_selection import (
    TimeSeriesSplit, 
    RandomizedSearchCV,
    train_test_split
)
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report

# Imblearn (SMOTE + Pipeline) - fallback si non dispo
try:
    from imblearn.over_sampling import SMOTE
    from imblearn.pipeline import Pipeline as ImbPipeline
    IMBLEARN_OK = True
except ImportError:
    from sklearn.pipeline import Pipeline as SkPipeline
    IMBLEARN_OK = False
    print("[WARNING] imbalanced-learn non installé => pas de SMOTE possible.")

########################################
# CONFIG GLOBALE
########################################
LOG_FILE   = "train_model.log"
CSV_FILE   = "training_data.csv"   # CSV complet
MODEL_FILE = "model.pkl"

# On suppose que ~20% des données les + récentes serviront de final test
FINAL_TEST_RATIO = 0.2  
# Nombre d'itérations RandomizedSearch
N_ITER = 30
# Nombre de splits TimeSeries (sur la portion train_val)
TSCV_SPLITS = 10

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START train_model (V8 => focus F1) ===")

def main():
    # 1) Vérif CSV
    if not os.path.exists(CSV_FILE):
        msg = f"[ERREUR] Fichier CSV introuvable => {CSV_FILE}"
        print(msg)
        logging.error(msg)
        return

    # 2) Lecture CSV
    df = pd.read_csv(CSV_FILE)
    nrows, ncols = df.shape
    logging.info(f"CSV => {nrows} lignes, {ncols} colonnes.")

    # Vérif label
    if "label" not in df.columns:
        msg = "[ERREUR] Colonne 'label' manquante."
        print(msg)
        logging.error(msg)
        return

    # Choix de features => adapter selon tes colonnes dispo
    features = [
        "close", "volume", "market_cap",
        "galaxy_score", "alt_rank", "sentiment",
        "rsi", "macd", "atr",
        "btc_daily_change", "eth_daily_change"
    ]
    target = "label"

    # Vérif si features sont présentes
    missing_cols = [c for c in features if c not in df.columns]
    if missing_cols:
        msg = f"[ERREUR] Colonnes manquantes: {missing_cols}"
        print(msg)
        logging.error(msg)
        return

    # Retrait lignes NaN => crucial
    sub = df.dropna(subset=features+[target]).copy()
    if sub.empty:
        msg = "[ERREUR] Aucune data valide après dropna."
        print(msg)
        logging.error(msg)
        return

    # 3) Faire un tri par date ? => On suppose qu'on a "date" trié
    # On suppose que sub est déjà trié, sinon on fait:
    #   sub.sort_values("date", inplace=True)

    # On sépare le final_test
    cutoff = int((1.0 - FINAL_TEST_RATIO)*len(sub))
    train_val_df = sub.iloc[:cutoff].copy()
    final_test_df = sub.iloc[cutoff:].copy()

    logging.info(f"Train_val => {len(train_val_df)} lignes, Final_test => {len(final_test_df)}.")

    # X, y (train_val)
    X_tv = train_val_df[features]
    y_tv = train_val_df[target].astype(int)

    # X, y (final_test)
    X_test = final_test_df[features]
    y_test = final_test_df[target].astype(int)

    # 4) Création Pipeline
    if IMBLEARN_OK:
        steps = [
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=42)),
            ("clf", RandomForestClassifier(random_state=42))
        ]
        pipe_class = ImbPipeline
        logging.info("[build_model] => SMOTE activé.")
    else:
        steps = [
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                class_weight="balanced_subsample",
                random_state=42
            ))
        ]
        pipe_class = SkPipeline
        logging.info("[build_model] => Pas de SMOTE, fallback pipeline")

    pipe = pipe_class(steps)

    # 5) Espace d'hyperparamètres
    # On peut inclure un param 'clf__class_weight': [None, "balanced", {0:1,1:2}, {0:1,1:3}]
    # si on veut ajuster le ratio. 
    param_dist = {
        "clf__n_estimators": [100, 200, 300, 500],
        "clf__max_depth": [10, 15, 20, None],
        "clf__min_samples_split": [2, 5, 10],
        "clf__min_samples_leaf": [1, 2, 5],
        "clf__max_features": ["sqrt", "log2", None],
        "clf__bootstrap": [True, False],
        "clf__class_weight": [None, "balanced_subsample", {0:1, 1:2}, {0:1, 1:3}],
    }

    # 6) Construction du TimeSeriesSplit
    tscv = TimeSeriesSplit(
        n_splits=TSCV_SPLITS
    )

    # 7) RandomizedSearch => scoring="f1" 
    from sklearn.model_selection import RandomizedSearchCV
    rscv = RandomizedSearchCV(
        estimator=pipe,
        param_distributions=param_dist,
        n_iter=N_ITER,
        scoring="f1",   # <-- Changement crucial : on vise un F1 global (macro) 
        # Si tu veux forcer la F1 minoritaire => "f1_weighted" ou "f1_macro", 
        # ou un "make_scorer(f1_score, average='binary', pos_label=1)".
        # Pour rester simple, on laisse "f1" => par défaut c'est f1 w.r.t. 
        # la classe majoritaire => c'est "binary" en scikit-learn si y in {0,1} => pos_label=1
        cv=tscv,
        verbose=1,
        random_state=42,
        n_jobs=-1
    )

    logging.info(f"[RandomizedSearchCV] => TSCV({TSCV_SPLITS}), n_iter={N_ITER}, scoring='f1'")
    print("[INFO] Lancement RandomizedSearchCV => scoring='f1' sur train_val ...")
    rscv.fit(X_tv, y_tv)

    best_params = rscv.best_params_
    logging.info(f"Best Params => {best_params}")
    print("\n[RESULT] Meilleurs hyperparamètres =>", best_params)

    # 8) Bâtir un modèle final sur l'intégralité du train_val
    #    (re-fit pipeline sur X_tv, y_tv, mais en fixant les best_params).
    # On peut faire rscv.best_estimator_, qui est déjà fit, 
    # mais pour être formel, on reconstruit un pipeline.
    final_model = rscv.best_estimator_

    # 9) Évaluation sur final_test
    y_pred = final_model.predict(X_test)
    rep = classification_report(y_test, y_pred, digits=3)
    logging.info("\n[Hold-out final test] " + rep)
    print("\n===== [Hold-out final test] =====")
    print(rep)

    # 10) Si tu veux, on peut re-check in-sample
    final_model.fit(X_tv, y_tv)  # refit complet
    y_pred_in = final_model.predict(X_tv)
    rep_in = classification_report(y_tv, y_pred_in, digits=3)
    logging.info("\n[In-sample 100%] " + rep_in)
    print("\n===== [In-sample 100%] =====")
    print(rep_in)

    # 11) Sauvegarde
    joblib.dump(final_model, MODEL_FILE)
    logging.info(f"Final model sauvegardé => {MODEL_FILE}")
    print(f"\n[OK] Modèle final (V8 => f1) sauvegardé => {MODEL_FILE}")


if __name__ == "__main__":
    main()
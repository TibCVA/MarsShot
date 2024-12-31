#!/usr/bin/env python3
# coding: utf-8

import os
import logging
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
import joblib

LOG_FILE = "train_model.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START train_model ===")

CSV_FILE = "training_data.csv"
MODEL_FILE = "model.pkl"

def main():
    if not os.path.exists(CSV_FILE):
        logging.error(f"No CSV file found: {CSV_FILE}")
        print("No CSV => can't train. Check build_csv first.")
        return

    # 1) Charger le CSV
    df = pd.read_csv(CSV_FILE)

    # 2) On vérifie la colonne label
    if "label" not in df.columns:
        logging.error("No label column in CSV => can't train.")
        print("No label => can't train.")
        return

    # Exemples de features => vous pouvez adapter
    # On prend : close, volume, market_cap, rsi, macd, atr
    #  (assurez-vous qu'ils existent dans le CSV)
    features = ["close", "volume", "market_cap", "rsi", "macd", "atr"]
    # On retire les lignes qui ont NaN
    sub = df.dropna(subset=features + ["label"]).copy()

    if sub.empty:
        logging.error("All data are NaN => can't train.")
        print("No data => can't train.")
        return

    X = sub[features]
    y = sub["label"].astype(int)

    # 3) Split train/test
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # 4) Entraîner un modèle simple RandomForest
    clf = RandomForestClassifier(n_estimators=100, random_state=42)
    clf.fit(X_train, y_train)

    # 5) Évaluer
    y_pred = clf.predict(X_test)
    rep = classification_report(y_test, y_pred, digits=3)
    logging.info("\n"+rep)
    print(rep)

    # 6) Sauvegarde du modèle
    joblib.dump(clf, MODEL_FILE)
    logging.info(f"Model saved => {MODEL_FILE}")
    print(f"Model saved => {MODEL_FILE}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# coding: utf-8

"""
train_model_optuna.py
Entraîne un modèle LightGBM optimisé via Optuna,
pour prédire si un token fera +5% sur 2 jours (label=1 vs label=0).
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
import joblib

import optuna
from optuna.samplers import TPESampler
import lightgbm as lgb

from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score, classification_report

try:
    from imblearn.over_sampling import SMOTE
    IMBLEARN_OK = True
except ImportError:
    IMBLEARN_OK = False
    print("[WARNING] imblearn (SMOTE) non installé => fallback")

CSV_FILE       = "training_data.csv"
MODEL_FILE     = "model.pkl"
LOG_FILE       = "train_model_optuna.log"

FEATURES = [
    "close", "volume", "market_cap",
    "galaxy_score", "alt_rank", "sentiment",
    "rsi", "macd", "atr",
    "btc_daily_change", "eth_daily_change", "sol_daily_change"
]
LABEL_COL = "label"

FINAL_TEST_RATIO = 0.1
TSCV_SPLITS      = 5
N_TRIALS         = 100
USE_SMOTE        = True

logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(console_handler)

logging.info("=== START train_model_optuna (LightGBM) ===")

# 1) Lire le CSV
if not os.path.exists(CSV_FILE):
    msg = f"[ERREUR] {CSV_FILE} introuvable."
    logging.error(msg)
    print(msg)
    sys.exit(1)

df = pd.read_csv(CSV_FILE)
if LABEL_COL not in df.columns:
    msg = f"[ERREUR] Colonne '{LABEL_COL}' introuvable."
    logging.error(msg)
    print(msg)
    sys.exit(1)

missing_feats = [f for f in FEATURES if f not in df.columns]
if missing_feats:
    msg = f"[ERREUR] Features manquantes : {missing_feats}"
    logging.error(msg)
    print(msg)
    sys.exit(1)

df.dropna(subset=FEATURES + [LABEL_COL], inplace=True)
df.sort_values("date", inplace=True)
df.reset_index(drop=True, inplace=True)
df[LABEL_COL] = df[LABEL_COL].astype(int)

logging.info(f"[DATA] {len(df)} lignes après dropna")

# 2) Split
cut = int(len(df)*(1 - FINAL_TEST_RATIO))
train_val_df = df.iloc[:cut].copy()
test_df      = df.iloc[cut:].copy()

X_tv = train_val_df[FEATURES]
y_tv = train_val_df[LABEL_COL]
X_test = test_df[FEATURES]
y_test = test_df[LABEL_COL]

logging.info(f"[SPLIT] Train_val={len(train_val_df)}, Test={len(test_df)}")

# 3) Objective Optuna
def objective(trial):
    params_lgb = {
        "boosting_type": "gbdt",
        "n_estimators": trial.suggest_int("n_estimators", 100, 2000, step=100),
        "num_leaves": trial.suggest_int("num_leaves", 8, 512),
        "max_depth": trial.suggest_int("max_depth", 3, 16),
        "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 1, 200),
        "learning_rate": trial.suggest_float("learning_rate", 1e-4, 0.1, log=True),
        "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0, step=0.1),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0, step=0.1),
        "bagging_freq": trial.suggest_int("bagging_freq", 0, 10),
        "lambda_l1": trial.suggest_float("lambda_l1", 1e-8, 10.0, log=True),
        "lambda_l2": trial.suggest_float("lambda_l2", 1e-8, 10.0, log=True),
        "random_state": 42,
        "n_jobs": -1
    }

    lgb_clf = lgb.LGBMClassifier(**params_lgb)

    steps = []
    if USE_SMOTE and IMBLEARN_OK:
        steps.append(("smote", SMOTE(random_state=42)))
    steps.append(("scaler", StandardScaler()))
    steps.append(("lgb", lgb_clf))

    pipe = Pipeline(steps)

    tscv = TimeSeriesSplit(n_splits=TSCV_SPLITS)
    scores = []
    for train_idx, val_idx in tscv.split(X_tv):
        X_tr, X_val = X_tv.iloc[train_idx], X_tv.iloc[val_idx]
        y_tr, y_val = y_tv.iloc[train_idx], y_tv.iloc[val_idx]

        pipe.fit(X_tr, y_tr)
        y_pred = pipe.predict(X_val)
        f1_val = f1_score(y_val, y_pred, average="binary")
        scores.append(f1_val)

    mean_score = np.mean(scores)
    trial.set_user_attr("f1_cv", mean_score)
    return mean_score

logging.info("[OPTUNA] create_study => TPE, direction=maximize")
study = optuna.create_study(
    direction="maximize",
    sampler=TPESampler(seed=42)
)

logging.info(f"[OPTUNA] start => n_trials={N_TRIALS}")
study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)

best_trial = study.best_trial
logging.info(f"[OPTUNA] best trial => #{best_trial.number}, f1={best_trial.value:.4f}")
logging.info(f"[OPTUNA] best params => {best_trial.params}")

print("\n=== [Optuna BEST] ===")
print(f"Trial => #{best_trial.number}, f1={best_trial.value:.4f}")
print("Params =>", best_trial.params)

# 4) Retrain final
params_final = {
    "boosting_type": "gbdt",
    "n_estimators": best_trial.params["n_estimators"],
    "num_leaves": best_trial.params["num_leaves"],
    "max_depth": best_trial.params["max_depth"],
    "min_data_in_leaf": best_trial.params["min_data_in_leaf"],
    "learning_rate": best_trial.params["learning_rate"],
    "feature_fraction": best_trial.params["feature_fraction"],
    "bagging_fraction": best_trial.params["bagging_fraction"],
    "bagging_freq": best_trial.params["bagging_freq"],
    "lambda_l1": best_trial.params["lambda_l1"],
    "lambda_l2": best_trial.params["lambda_l2"],
    "random_state": 42,
    "n_jobs": -1
}

final_steps = []
if USE_SMOTE and IMBLEARN_OK:
    final_steps.append(("smote", SMOTE(random_state=42)))
final_steps.append(("scaler", StandardScaler()))
final_steps.append(("lgb", lgb.LGBMClassifier(**params_final)))

final_pipe = Pipeline(final_steps)
logging.info("[FINAL] Fit sur train_val complet")
final_pipe.fit(X_tv, y_tv)

# test final
y_pred_test = final_pipe.predict(X_test)
f1_t = f1_score(y_test, y_pred_test, average="binary")
rep = classification_report(y_test, y_pred_test, digits=3)

print("\n=== [Hold-out Test] ===")
print(f"F1 => {f1_t:.4f}")
print(rep)
logging.info(f"[TEST] F1={f1_t:.4f}\n{rep}")

joblib.dump(final_pipe, MODEL_FILE)
logging.info(f"[SAVE] => {MODEL_FILE}")
print(f"[OK] Modèle final sauvegardé => {MODEL_FILE}")

logging.info("=== DONE train_model_optuna (LightGBM) ===")


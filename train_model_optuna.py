#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
train_model_optuna_final.py

Objectif:
 - Lire 'training_data.csv' (21 features + label + date + symbol)
 - Supprimer NaN
 - TSCV=15 sur 90% du dataset, hold-out=10% final
 - Optuna => LightGBM => On optimise la F1 "macro" (moyenne F1(0) et F1(1))
 - On teste plusieurs samplers (none, SMOTE, BorderlineSMOTE, ADASYN,
   random undersampler, SMOTE+Under)
 - GPU => device="gpu"
 - On sauvegarde le pipeline final => model.pkl
"""

import os
import sys
import logging
import numpy as np
import pandas as pd
import joblib

import optuna
from optuna.samplers import TPESampler

import lightgbm as lgb

from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import f1_score, classification_report
from sklearn.preprocessing import StandardScaler

try:
    from imblearn.pipeline import Pipeline
    from imblearn.over_sampling import SMOTE, BorderlineSMOTE, ADASYN
    from imblearn.under_sampling import RandomUnderSampler
    IMBLEARN_OK = True
except ImportError:
    IMBLEARN_OK = False
    print("[WARNING] imbalanced-learn is not installed => pip install imbalanced-learn")

########################################
# CONFIG
########################################
CSV_FILE       = "training_data.csv"
MODEL_FILE     = "model.pkl"
LOG_FILE       = "train_model_optuna_final.log"

TSCV_SPLITS    = 15
N_TRIALS       = 700
USE_GPU        = True

logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(console_handler)

logging.info("=== START train_model_optuna_final (LightGBM + F1_macro) ===")

def main():
    # 1) Charger CSV
    if not os.path.exists(CSV_FILE):
        print(f"[ERROR] {CSV_FILE} not found.")
        logging.error(f"[ERROR] {CSV_FILE} not found.")
        return

    df = pd.read_csv(CSV_FILE)

    # 21 features EXACTES
    feats_21 = [
        "delta_close_1d","delta_close_3d",
        "delta_vol_1d","delta_vol_3d",
        "rsi14","rsi30","ma_close_7d","ma_close_14d","atr14","macd_std",
        "btc_daily_change","btc_3d_change","eth_daily_change","eth_3d_change",
        "delta_mcap_1d","delta_mcap_3d",
        "galaxy_score","delta_galaxy_score_3d",
        "alt_rank","delta_alt_rank_3d",
        "sentiment"
    ]
    needed_cols = ["date","symbol","label"] + feats_21
    missing = [c for c in needed_cols if c not in df.columns]
    if missing:
        msg = f"[ERROR] Missing columns: {missing}"
        print(msg)
        logging.error(msg)
        return

    # 2) dropna
    sub = df.dropna(subset=feats_21 + ["label"]).copy()
    sub.sort_values(["symbol","date"], inplace=True)
    sub.reset_index(drop=True, inplace=True)
    sub["label"] = sub["label"].astype(int)

    # 3) Hold-out final => 10%
    final_test_ratio=0.1
    cutoff=int((1-final_test_ratio)*len(sub))
    train_val_df= sub.iloc[:cutoff].copy()
    test_df= sub.iloc[cutoff:].copy()

    X_tv= train_val_df[feats_21]
    y_tv= train_val_df["label"]
    X_test= test_df[feats_21]
    y_test= test_df["label"]

    logging.info(f"[DATA] => train_val={len(train_val_df)}, test={len(test_df)}")

    # 4) L'objectif Optuna => F1_macro
    def objective(trial):

        if IMBLEARN_OK:
            sampler_name = trial.suggest_categorical(
                "sampler_name",
                ["none","SMOTE","BorderlineSMOTE","ADASYN","Under","SMOTE+Under"]
            )
            sampler_steps=[]
            if sampler_name=="none":
                pass
            elif sampler_name=="Under":
                sampler_steps.append(("under", RandomUnderSampler(random_state=42)))
            elif sampler_name=="SMOTE+Under":
                ratio = trial.suggest_float("smote_ratio", 0.5,1.0, step=0.1)
                sampler_steps.append(("smote", SMOTE(random_state=42, sampling_strategy=ratio)))
                sampler_steps.append(("under", RandomUnderSampler(random_state=42)))
            elif sampler_name=="SMOTE":
                ratio= trial.suggest_float("smote_ratio",0.5,1.0, step=0.1)
                sampler_steps.append(("smote", SMOTE(random_state=42, sampling_strategy=ratio)))
            elif sampler_name=="BorderlineSMOTE":
                sampler_steps.append(("smote", BorderlineSMOTE(random_state=42)))
            elif sampler_name=="ADASYN":
                sampler_steps.append(("smote", ADASYN(random_state=42)))
        else:
            sampler_steps=[]

        params_lgb = {
            "boosting_type":"gbdt",
            "n_estimators": trial.suggest_int("n_estimators",100,3000, step=100),
            "num_leaves": trial.suggest_int("num_leaves",8,512),
            "max_depth": trial.suggest_int("max_depth",3,20),
            "min_data_in_leaf": trial.suggest_int("min_data_in_leaf",1,400),
            "learning_rate": trial.suggest_float("learning_rate",1e-5,0.3, log=True),
            "feature_fraction": trial.suggest_float("feature_fraction",0.4,1.0, step=0.1),
            "bagging_fraction": trial.suggest_float("bagging_fraction",0.4,1.0, step=0.1),
            "bagging_freq": trial.suggest_int("bagging_freq",0,15),
            "lambda_l1": trial.suggest_float("lambda_l1",1e-9,10.0, log=True),
            "lambda_l2": trial.suggest_float("lambda_l2",1e-9,10.0, log=True),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight",0.5,5.0),
            "random_state":42,
            "n_jobs":-1
        }
        if USE_GPU:
            params_lgb["device"]="gpu"

        lgb_clf= lgb.LGBMClassifier(**params_lgb)

        steps=[]
        steps.extend(sampler_steps)
        steps.append(("scaler", StandardScaler()))
        steps.append(("lgb", lgb_clf))

        pipe= Pipeline(steps=steps)

        tscv= TimeSeriesSplit(n_splits=15)
        scores=[]
        for train_idx, val_idx in tscv.split(X_tv):
            X_tr, X_val= X_tv.iloc[train_idx], X_tv.iloc[val_idx]
            y_tr, y_val= y_tv.iloc[train_idx], y_tv.iloc[val_idx]
            pipe.fit(X_tr,y_tr)

            y_pred= pipe.predict(X_val)
            f1_mac= f1_score(y_val, y_pred, average="macro")
            scores.append(f1_mac)

        return np.mean(scores)

    logging.info(f"[OPTUNA] => TSCV=15, n_trials={N_TRIALS}")
    study= optuna.create_study(direction="maximize", sampler=TPESampler(seed=42))
    study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)

    best_trial= study.best_trial
    logging.info(f"[OPTUNA] best trial => {best_trial.number}, f1_macro={best_trial.value:.4f}")
    logging.info(f"[OPTUNA] best params => {best_trial.params}")

    print("\n=== [Optuna BEST] ===")
    print(f"Trial => #{best_trial.number}, f1_macro={best_trial.value:.4f}")
    print("Params =>", best_trial.params)

    bp= best_trial.params.copy()
    final_sampler_steps=[]
    if IMBLEARN_OK:
        sn= bp.get("sampler_name","none")
        if sn in ["SMOTE","SMOTE+Under"]:
            sr= bp.get("smote_ratio",1.0)
        else:
            sr= None

        if sn=="Under":
            final_sampler_steps.append(("under", RandomUnderSampler(random_state=42)))
        elif sn=="SMOTE+Under":
            final_sampler_steps.append(("smote", SMOTE(random_state=42, sampling_strategy=sr)))
            final_sampler_steps.append(("under", RandomUnderSampler(random_state=42)))
        elif sn=="SMOTE":
            final_sampler_steps.append(("smote", SMOTE(random_state=42, sampling_strategy=sr)))
        elif sn=="BorderlineSMOTE":
            final_sampler_steps.append(("smote", BorderlineSMOTE(random_state=42)))
        elif sn=="ADASYN":
            final_sampler_steps.append(("smote", ADASYN(random_state=42)))

    if "sampler_name" in bp: del bp["sampler_name"]
    if "smote_ratio" in bp: del bp["smote_ratio"]

    params_final={
        "boosting_type": "gbdt",
        "n_estimators": bp["n_estimators"],
        "num_leaves": bp["num_leaves"],
        "max_depth": bp["max_depth"],
        "min_data_in_leaf": bp["min_data_in_leaf"],
        "learning_rate": bp["learning_rate"],
        "feature_fraction": bp["feature_fraction"],
        "bagging_fraction": bp["bagging_fraction"],
        "bagging_freq": bp["bagging_freq"],
        "lambda_l1": bp["lambda_l1"],
        "lambda_l2": bp["lambda_l2"],
        "scale_pos_weight": bp["scale_pos_weight"],
        "random_state":42,
        "n_jobs":-1
    }
    if USE_GPU:
        params_final["device"]="gpu"

    lgb_final= lgb.LGBMClassifier(**params_final)

    steps_final=[]
    steps_final.extend(final_sampler_steps)
    steps_final.append(("scaler", StandardScaler()))
    steps_final.append(("lgb", lgb_final))

    final_pipe= Pipeline(steps=steps_final)

    logging.info("[FINAL] => Fit sur tout train_val")
    final_pipe.fit(X_tv, y_tv)

    y_pred_test= final_pipe.predict(X_test)
    f1_mac= f1_score(y_test, y_pred_test, average="macro")
    rep= classification_report(y_test, y_pred_test, digits=3)

    print("\n=== [Hold-out Test] ===")
    print(f"F1_macro => {f1_mac:.4f}")
    print(rep)
    logging.info(f"[TEST] => f1_macro={f1_mac:.4f}\n{rep}")

    joblib.dump(final_pipe, MODEL_FILE)
    logging.info(f"[SAVE] => {MODEL_FILE}")
    print(f"[OK] Model saved => {MODEL_FILE}")

if __name__=="__main__":
    main()

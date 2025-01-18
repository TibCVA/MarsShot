#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
from sklearn.pipeline import Pipeline as SkPipeline

########################################
# On prepare des variables globales SMOTE_, BSMOTE_, ADASYN_
# De base: None => si imblearn non installe
########################################
SMOTE_ = None
BSMOTE_ = None
ADASYN_ = None
IMBLEARN_OK = False

try:
    from imblearn.pipeline import Pipeline as ImbPipeline
    from imblearn.over_sampling import SMOTE, BorderlineSMOTE, ADASYN
    # On leur assigne un alias
    SMOTE_ = SMOTE
    BSMOTE_ = BorderlineSMOTE
    ADASYN_ = ADASYN
    IMBLEARN_OK = True
except ImportError:
    print("[WARNING] 'pip install imbalanced-learn' pour SMOTE/BLSMOTE/ADASYN")
    IMBLEARN_OK = False

########################################
# CONFIG
########################################
LOG_FILE   = "train_model_optuna.log"
CSV_FILE   = "training_data.csv"
MODEL_FILE = "model.pkl"

TSCV_SPLITS = 15
N_TRIALS    = 300
USE_GPU     = True

logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(console_handler)

logging.info("=== START train_model_optuna ===")

def main():
    # 1) Verif CSV
    if not os.path.exists(CSV_FILE):
        msg = f"[ERROR] {CSV_FILE} introuvable."
        logging.error(msg)
        print(msg)
        return

    df = pd.read_csv(CSV_FILE)
    if "label" not in df.columns:
        msg = "[ERROR] CSV sans colonne 'label'."
        logging.error(msg)
        print(msg)
        return

    # 2) Features (sans volatility_24h ni delta_volatility_3d)
    FEATURES = [
        "delta_close_1d","delta_close_3d","delta_vol_1d","delta_vol_3d",
        "rsi14","rsi30","ma_close_7d","ma_close_14d","atr14","macd_std",
        "stoch_rsi_k","stoch_rsi_d","mfi14","boll_percent_b","obv","adx","adx_pos","adx_neg",
        "btc_daily_change","btc_3d_change","eth_daily_change","eth_3d_change",
        "delta_mcap_1d","delta_mcap_3d","galaxy_score","delta_galaxy_score_3d",
        "alt_rank","delta_alt_rank_3d","sentiment",
        "social_dominance","market_dominance",
        "delta_social_dom_3d","delta_market_dom_3d",
        "label"
    ]

    missing = [c for c in FEATURES if c not in df.columns]
    if missing:
        msg = f"[ERROR] colonnes manquantes: {missing}"
        logging.error(msg)
        print(msg)
        return

    # 3) On drop na
    sub = df.dropna(subset=FEATURES, inplace=False).copy()
    sub.sort_values("date", inplace=True)
    sub.reset_index(drop=True, inplace=True)
    sub["label"] = sub["label"].astype(int)

    # 4) split 90/10
    cutoff = int(len(sub)*0.9)
    train_val_df = sub.iloc[:cutoff].copy()
    test_df      = sub.iloc[cutoff:].copy()

    X_tv = train_val_df[[col for col in FEATURES if col!="label"]]
    y_tv = train_val_df["label"]
    X_test = test_df[[col for col in FEATURES if col!="label"]]
    y_test = test_df["label"]

    logging.info(f"[DATA] => train_val={len(train_val_df)}, test={len(test_df)}")

    ##########################
    # 5) Fct objective
    ##########################
    def objective(trial):
        # a) Sampler
        if IMBLEARN_OK:
            sampler_name = trial.suggest_categorical(
                "sampler_name", ["none","SMOTE","BorderlineSMOTE","ADASYN"]
            )
            if sampler_name=="SMOTE":
                ratio = trial.suggest_float("smote_ratio", 0.5, 1.0, step=0.1)
                sampler = SMOTE_(random_state=42, sampling_strategy=ratio)
            elif sampler_name=="BorderlineSMOTE":
                sampler = BSMOTE_(random_state=42)
            elif sampler_name=="ADASYN":
                sampler = ADASYN_(random_state=42)
            else:
                sampler = None
        else:
            sampler = None

        # b) threshold
        threshold = trial.suggest_float("threshold", 0.40, 0.60, step=0.01)

        # c) LightGBM
        params_lgb = {
            "boosting_type": "gbdt",
            "n_estimators": trial.suggest_int("n_estimators", 200, 2500, step=100),
            "num_leaves":   trial.suggest_int("num_leaves", 8, 512),
            "max_depth":    trial.suggest_int("max_depth", 3, 20),
            "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 1, 400),
            "learning_rate":  trial.suggest_float("learning_rate", 1e-4, 0.2, log=True),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.4, 1.0, step=0.1),
            "bagging_fraction":  trial.suggest_float("bagging_fraction", 0.4, 1.0, step=0.1),
            "bagging_freq":   trial.suggest_int("bagging_freq", 0, 20),
            "lambda_l1":      trial.suggest_float("lambda_l1", 1e-9, 10.0, log=True),
            "lambda_l2":      trial.suggest_float("lambda_l2", 1e-9, 10.0, log=True),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", 0.5, 10.0),
            "random_state":   42,
            "n_jobs":         -1
        }
        if USE_GPU:
            params_lgb["device"] = "gpu"

        lgb_clf = lgb.LGBMClassifier(**params_lgb)

        # d) pipeline
        if sampler:
            from imblearn.pipeline import Pipeline
            pipe = Pipeline([
                ("sampler", sampler),
                ("scaler", StandardScaler()),
                ("lgb", lgb_clf)
            ])
        else:
            pipe = SkPipeline([
                ("scaler", StandardScaler()),
                ("lgb", lgb_clf)
            ])

        # e) tscv
        tscv = TimeSeriesSplit(n_splits=15)
        scores = []
        for train_idx, val_idx in tscv.split(X_tv):
            X_tr, X_val = X_tv.iloc[train_idx], X_tv.iloc[val_idx]
            y_tr, y_val = y_tv.iloc[train_idx], y_tv.iloc[val_idx]
            pipe.fit(X_tr, y_tr)
            y_prob = pipe.predict_proba(X_val)[:,1]
            y_pred = (y_prob >= threshold).astype(int)

            f1_m = f1_score(y_val, y_pred, average="macro")
            scores.append(f1_m)
        return np.mean(scores)

    # 6) Etude
    logging.info(f"[OPTUNA] => TSCV=15, n_trials={N_TRIALS}")
    study = optuna.create_study(direction="maximize", sampler=TPESampler(seed=42))
    study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)

    # 7) best
    best_trial = study.best_trial
    logging.info(f"[OPTUNA] best trial => #{best_trial.number}, val={best_trial.value:.4f}")
    logging.info(f"[OPTUNA] best params => {best_trial.params}")

    print("\n=== [Optuna BEST] ===")
    print(f"Trial => #{best_trial.number}, f1_macro={best_trial.value:.4f}")
    print("Params =>", best_trial.params)

    bp = best_trial.params.copy()
    final_threshold = bp.get("threshold", 0.5)

    # sampler final
    final_sampler = None
    if IMBLEARN_OK:
        from imblearn.pipeline import Pipeline
        sn = bp.get("sampler_name","none")
        if sn=="SMOTE":
            sr = bp.get("smote_ratio",1.0)
            final_sampler= SMOTE_(random_state=42, sampling_strategy=sr)
        elif sn=="BorderlineSMOTE":
            final_sampler= BSMOTE_(random_state=42)
        elif sn=="ADASYN":
            final_sampler= ADASYN_(random_state=42)

    # remove keys
    for k in ["sampler_name","smote_ratio","threshold"]:
        if k in bp:
            del bp[k]

    params_final = {
        "boosting_type":   "gbdt",
        "n_estimators":    bp["n_estimators"],
        "num_leaves":      bp["num_leaves"],
        "max_depth":       bp["max_depth"],
        "min_data_in_leaf":bp["min_data_in_leaf"],
        "learning_rate":   bp["learning_rate"],
        "feature_fraction":bp["feature_fraction"],
        "bagging_fraction":bp["bagging_fraction"],
        "bagging_freq":    bp["bagging_freq"],
        "lambda_l1":       bp["lambda_l1"],
        "lambda_l2":       bp["lambda_l2"],
        "scale_pos_weight":bp["scale_pos_weight"],
        "random_state":    42,
        "n_jobs":          -1
    }
    if USE_GPU:
        params_final["device"] = "gpu"

    lgb_final = lgb.LGBMClassifier(**params_final)

    if final_sampler:
        pipe_final = Pipeline([
            ("sampler", final_sampler),
            ("scaler", StandardScaler()),
            ("lgb", lgb_final)
        ])
    else:
        pipe_final = SkPipeline([
            ("scaler", StandardScaler()),
            ("lgb", lgb_final)
        ])

    logging.info("[FINAL] => fit sur train_val complet.")
    pipe_final.fit(X_tv, y_tv)

    y_prob_test= pipe_final.predict_proba(X_test)[:,1]
    y_pred_test= (y_prob_test >= final_threshold).astype(int)

    f1_m = f1_score(y_test, y_pred_test, average="macro")
    rep  = classification_report(y_test, y_pred_test, digits=3)

    print("\n=== [Hold-out Test] ===")
    print(f"Threshold = {final_threshold:.2f}")
    print(f"F1_macro => {f1_m:.4f}")
    print(rep)

    logging.info(f"[TEST] => threshold={final_threshold:.2f}, f1_macro={f1_m:.4f}\n{rep}")

    joblib.dump((pipe_final, final_threshold), MODEL_FILE)
    logging.info(f"[SAVE] => {MODEL_FILE}")
    print(f"[OK] Modele final sauvegarde => {MODEL_FILE}")

if __name__=="__main__":
    main()

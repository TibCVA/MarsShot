#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ml_decision.py –  LIVE inference pour ensemble_mixcalib.pkl (modèle v9)

• Lit daily_inference_data.csv produit par data_fetcher.py
• Récupère **dynamiquement** la liste des features depuis le booster
  LightGBM (pas de liste codée en dur → zéro décalage possible)
• Calcule la proba moyenne (sigmoid + isotonic) / 2, moyennée sur l’ensemble
• Écrit daily_probabilities.csv   (colonnes : symbol, prob)
"""

# ------------------------------------------------------------------ #
# Imports                                                            #
# ------------------------------------------------------------------ #
from __future__ import annotations
import os, sys, logging
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

# ------------------------------------------------------------------ #
# Constantes chemins                                                 #
# ------------------------------------------------------------------ #
CUR_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_FILE        = os.path.join(CUR_DIR, "..", "ensemble_mixcalib.pkl")
INPUT_CSV         = os.path.join(CUR_DIR, "..", "daily_inference_data.csv")
OUTPUT_CSV        = os.path.join(CUR_DIR, "..", "daily_probabilities.csv")
LOG_FILE          = "ml_decision.log"

# ------------------------------------------------------------------ #
# Logging                                                            #
# ------------------------------------------------------------------ #
logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logging.getLogger().addHandler(console)
log = logging.getLogger(__name__)
log.info("=== START ml_decision.py – modèle ensemble_mixcalib.pkl ===")

# ------------------------------------------------------------------ #
# Helpers                                                            #
# ------------------------------------------------------------------ #
def _find_booster(calibrator):
    """
    Récupère le LGBMClassifier (ou son booster_.booster_) encapsulé dans
    CalibratedClassifierCV (sigmoid / isotonic) qui est lui‑même dans un
    Pipeline scikit‑learn.
    """
    for attr in ("base_estimator_", "estimator_", "base_estimator", "estimator"):
        if hasattr(calibrator, attr):
            base = getattr(calibrator, attr)
            break
    else:
        raise AttributeError("Booster LightGBM introuvable dans calibrateur.")
    # Cas Pipeline -> .named_steps['clf'] ; cas direct -> LGBMClassifier
    return base.named_steps["clf"] if hasattr(base, "named_steps") else base


def get_feature_list(model_path: str) -> list[str]:
    """Extrait la feature list du premier seed de l'ensemble."""
    ensemble = joblib.load(model_path)
    booster = _find_booster(ensemble[0]["sig"])
    return booster.booster_.feature_name()  # ordre appris → ordre requis


def load_ensemble(model_path: str):
    """Charge l'ensemble et renvoie la fonction de prédiction agrégée."""
    ensemble = joblib.load(model_path)

    def _predict(df_feat: pd.DataFrame) -> np.ndarray:
        probs = [
            0.5 * (m["sig"].predict_proba(df_feat)[:, 1] +
                   m["iso"].predict_proba(df_feat)[:, 1])
            for m in ensemble
        ]
        return np.mean(probs, axis=0)

    return _predict


# ------------------------------------------------------------------ #
# MAIN                                                               #
# ------------------------------------------------------------------ #
def main():
    # -------------------- Vérifications préalables ---------------- #
    if not os.path.exists(MODEL_FILE):
        log.error("Modèle absent : %s", MODEL_FILE)
        print(f"[ERROR] {MODEL_FILE} introuvable"); sys.exit(1)
    if not os.path.exists(INPUT_CSV):
        log.error("CSV d'entrée absent : %s", INPUT_CSV)
        print(f"[ERROR] {INPUT_CSV} introuvable"); sys.exit(1)

    # -------------------- Extraction features --------------------- #
    try:
        FEATURES = get_feature_list(MODEL_FILE)
    except Exception as exc:
        log.critical("Extraction features impossible : %s", exc, exc_info=True)
        sys.exit(1)
    feat_set = set(FEATURES)

    # -------------------- Lecture CSV ----------------------------- #
    df = pd.read_csv(INPUT_CSV)
    if df.empty:
        log.warning("CSV inferences vide – fin.")
        sys.exit(0)

    # Standardise colonne date -> date_dt (timezone‑aware UTC)
    date_col = "date_dt" if "date_dt" in df.columns else "date"
    df["date_dt"] = pd.to_datetime(df[date_col], utc=True, errors="coerce")

    # On ne prédit que sur la dernière bougie *fermée* (J‑1)
    today_utc = datetime.now(timezone.utc).date()
    df = df[df["date_dt"].dt.date < today_utc]

    # -------------------- Sanity columns -------------------------- #
    if "symbol" not in df.columns:
        log.error("Colonne symbol manquante dans %s", INPUT_CSV); sys.exit(1)

    # Ajout éventuel des features manquantes (remplies NaN)
    missing_cols = [c for c in FEATURES if c not in df.columns]
    if missing_cols:
        log.warning("Ajout %d features manquantes remplies NaN : %s",
                    len(missing_cols), missing_cols)
        for c in missing_cols:
            df[c] = np.nan

    # -------------------- Filtrage « lignes complètes » ----------- #
    rows_before = len(df)
    df = df.dropna(subset=FEATURES)           # <-- PATCH parité back‑test
    rows_after = len(df)
    log.info("[FILTER] %d lignes écartées pour NaN ; %d restantes.",
             rows_before - rows_after, rows_after)
    if df.empty:
        log.warning("Aucune ligne complète après filtrage – fin.")
        sys.exit(0)

    # -------------------- Préparation X --------------------------- #
    X = df[FEATURES].astype(float)

    # -------------------- Prédiction ------------------------------ #
    predict_fn = load_ensemble(MODEL_FILE)
    probs = predict_fn(X)

    df["prob"] = probs

    # On conserve la dernière ligne disponible par token
    df_latest = (df.sort_values("date_dt")
                   .groupby("symbol", as_index=False)
                   .tail(1)[["symbol", "prob"]]
                   .sort_values("symbol")
                   .reset_index(drop=True))

    df_latest.to_csv(OUTPUT_CSV, index=False)
    log.info("✅ daily_probabilities.csv écrit – %d tokens", len(df_latest))
    print(f"[OK] => {OUTPUT_CSV} ({len(df_latest)} tokens)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.critical("Fatal error", exc_info=True)
        sys.exit(1)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import yaml
import json
import time
import datetime
import pandas as pd

from modules.trade_executor import TradeExecutor

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(CURRENT_DIR, "config.yaml")

if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable (dashboard).")

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

BINANCE_KEY    = CONFIG["binance_api"]["api_key"]
BINANCE_SECRET = CONFIG["binance_api"]["api_secret"]

logging.basicConfig(level=logging.INFO)

# Fichiers d'historique
TRADE_FILE = "trade_history.json"
PERF_FILE  = "performance_history.json"

########################
# 1) Portfolio actuel
########################

def get_portfolio_state():
    """
    Retourne un dict {"positions": [...], "total_value_usdt": ...}
    représentant la liste des tokens (symbol, qty, value_usdt) et la somme totale en USDT.
    """
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    info  = bexec.client.get_account()
    bals  = info["balances"]

    positions = []
    total_val = 0.0

    for b in bals:
        asset = b["asset"]
        free  = float(b["free"])
        locked = float(b["locked"])
        qty   = free + locked
        if qty <= 0:
            continue
        if asset.upper() == "USDT":
            val_usdt = qty
        else:
            px = bexec.get_symbol_price(asset)
            val_usdt = px * qty
        positions.append({
            "symbol": asset,
            "qty": round(qty, 4),
            "value_usdt": round(val_usdt, 2)
        })
        total_val += val_usdt

    # Optionnel : à chaque appel, on peut enregistrer la valeur du portefeuille (si assez de temps s'est écoulé)
    # Pour ne pas enregistrer trop souvent, on enregistre seulement si le dernier enregistrement date de plus de 5 minutes.
    try:
        if os.path.exists(PERF_FILE):
            with open(PERF_FILE, "r") as f:
                hist = json.load(f)
            if hist:
                last_ts = hist[-1]["timestamp"]
                if time.time() - last_ts > 300:  # plus de 5 minutes
                    record_portfolio_value(total_val)
            else:
                record_portfolio_value(total_val)
        else:
            record_portfolio_value(total_val)
    except Exception as e:
        logging.error(f"[PORTFOLIO] record_portfolio_value error: {e}")

    return {
        "positions": positions,
        "total_value_usdt": round(total_val, 2)
    }

def list_tokens_tracked():
    return CONFIG.get("tokens_daily", [])

########################
# 2) Historique de trades
########################

def get_trades_history():
    """
    Retourne l'historique des trades.
    D'abord, on tente de lire trade_history.json.
    Si ce fichier n'existe pas, on tente de lire closed_trades.csv.
    La liste est triée par timestamp décroissant.
    """
    trades = []
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, "r") as f:
                trades = json.load(f)
        except Exception as e:
            logging.error(f"[TRADES] Erreur lecture {TRADE_FILE}: {e}")
    elif os.path.exists("closed_trades.csv"):
        try:
            df = pd.read_csv("closed_trades.csv")
            # Si le CSV ne contient pas de colonne "timestamp", nous créons un timestamp à partir de exit_date
            if "timestamp" not in df.columns and "exit_date" in df.columns:
                df["timestamp"] = pd.to_datetime(df["exit_date"]).astype(int) // 10**9
            trades = df.to_dict(orient="records")
        except Exception as e:
            logging.error(f"[TRADES] Erreur lecture closed_trades.csv: {e}")
    trades.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return trades

########################
# 3) Performance
########################

def record_portfolio_value(value_usdt):
    """
    Enregistre la valeur 'value_usdt' du portefeuille dans performance_history.json.
    """
    history = []
    if os.path.exists(PERF_FILE):
        try:
            with open(PERF_FILE, "r") as f:
                history = json.load(f)
        except Exception as e:
            logging.error(f"[PERF] Erreur lecture {PERF_FILE}: {e}")
    now_ts = time.time()
    entry = {
        "timestamp": now_ts,
        "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts)),
        "value_usdt": round(value_usdt, 2)
    }
    history.append(entry)
    history.sort(key=lambda x: x["timestamp"])
    with open(PERF_FILE, "w") as f:
        json.dump(history, f, indent=2)

def get_performance_history():
    """
    Calcule la performance sur 1d, 7d, 30d, etc. en se basant sur performance_history.json.
    Retourne un dict du type :
      { "1d": {"usdt": ..., "pct": ...}, "7d": {...}, "30d": {...}, "all": {...} }
    """
    if not os.path.exists(PERF_FILE):
        pf = get_portfolio_state()
        tv = pf["total_value_usdt"]
        return {
            "1d": {"usdt": tv, "pct": 0.0},
            "7d": {"usdt": tv, "pct": 0.0},
            "30d": {"usdt": tv, "pct": 0.0},
            "all": {"usdt": tv, "pct": 0.0},
        }
    with open(PERF_FILE, "r") as f:
        history = json.load(f)
    if not history:
        pf = get_portfolio_state()
        tv = pf["total_value_usdt"]
        return {
            "1d": {"usdt": tv, "pct": 0.0},
            "7d": {"usdt": tv, "pct": 0.0},
            "30d": {"usdt": tv, "pct": 0.0},
            "all": {"usdt": tv, "pct": 0.0},
        }
    last_entry = history[-1]
    current_val = last_entry["value_usdt"]
    now_ts = last_entry["timestamp"]

    def find_val_x_days_ago(x_days):
        target_ts = now_ts - x_days * 86400
        candidates = [h for h in history if h["timestamp"] <= target_ts]
        if not candidates:
            return None
        return candidates[-1]["value_usdt"]

    def compute_perf(x_days):
        old_val = find_val_x_days_ago(x_days)
        if old_val is None or old_val <= 0:
            return {"usdt": current_val, "pct": 0.0}
        diff = current_val - old_val
        pct = (diff / old_val) * 100
        return {"usdt": current_val, "pct": round(pct, 2)}

    perf_1d = compute_perf(1)
    perf_7d = compute_perf(7)
    perf_30d = compute_perf(30)
    first_val = history[0]["value_usdt"]
    pct_all = (current_val - first_val) / first_val * 100 if first_val > 0 else 0.0

    return {
        "1d": perf_1d,
        "7d": perf_7d,
        "30d": perf_30d,
        "all": {"usdt": current_val, "pct": round(pct_all, 2)}
    }

########################
# 4) Emergency Out
########################

def emergency_out():
    """
    Vend toutes les positions (sauf USDT).
    """
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    info = bexec.client.get_account()
    for b in info["balances"]:
        asset = b["asset"]
        qty = float(b["free"]) + float(b["locked"])
        if qty > 0 and asset.upper() != "USDT":
            bexec.sell_all(asset, qty)
    logging.info("[EMERGENCY] Tout vendu.")
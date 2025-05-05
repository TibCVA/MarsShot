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
# Si trade_history.json n'existe pas, on pourra tenter de lire closed_trades.csv
CLOSED_TRADES_FILE = "closed_trades.csv"
PERF_FILE  = "performance_history.json"

########################
# 1) Portfolio actuel
########################

def get_portfolio_state():
    """
    Retourne un dict {"positions": [...], "total_value_USDC": ...}
    représentant la liste des tokens détenus (symbol, qty, value_USDC)
    et la somme totale en USDC.
    
    Pour l'affichage, seuls les tokens dont la valeur est >= 1.5 USDC
    sont inclus, à l'exception de USDC qui est toujours affiché.
    """
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    info  = bexec.client.get_account()
    bals  = info["balances"]

    positions_all = []
    total_val = 0.0

    for b in bals:
        asset = b["asset"]
        free  = float(b["free"])
        locked = float(b["locked"])
        qty   = free + locked
        if qty <= 0:
            continue

        if asset.upper() == "USDC":
            val_USDC = qty
        else:
            px = bexec.get_symbol_price(asset)
            val_USDC = px * qty

        pos = {
            "symbol": asset,
            "qty": round(qty, 4),
            "value_USDC": round(val_USDC, 2)
        }
        positions_all.append(pos)
        total_val += val_USDC

    positions_display = [
        pos for pos in positions_all
        if pos["symbol"].upper() == "USDC" or pos["value_USDC"] >= 1.5
    ]

    try:
        if os.path.exists(PERF_FILE):
            with open(PERF_FILE, "r") as f:
                hist = json.load(f)
            if hist:
                last_ts = hist[-1]["timestamp"]
                if time.time() - last_ts > 300:
                    record_portfolio_value(total_val)
            else:
                record_portfolio_value(total_val)
        else:
            record_portfolio_value(total_val)
    except Exception as e:
        logging.error(f"[PORTFOLIO] record_portfolio_value error: {e}")

    return {
        "positions": positions_display,
        "total_value_USDC": round(total_val, 2)
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
    Si ce fichier n'existe pas, on tente de lire closed_trades.csv et on réalise un mapping
    pour que chaque trade ait les clés attendues par le Dashboard :
      - symbol
      - buy_prob
      - sell_prob
      - days_held
      - pnl_USDC
      - pnl_pct
      - status
    """
    trades = []
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, "r") as f:
                trades = json.load(f)
        except Exception as e:
            logging.error(f"[TRADES] Erreur lecture {TRADE_FILE}: {e}")
    elif os.path.exists(CLOSED_TRADES_FILE):
        try:
            df = pd.read_csv(CLOSED_TRADES_FILE)
            # Si le CSV contient exit_date, créer un champ timestamp
            if "timestamp" not in df.columns and "exit_date" in df.columns:
                df["timestamp"] = pd.to_datetime(df["exit_date"]).astype(int) // 10**9
            trades = df.to_dict(orient="records")
        except Exception as e:
            logging.error(f"[TRADES] Erreur lecture {CLOSED_TRADES_FILE}: {e}")

    # Pour chaque trade, s'assurer que les clés attendues existent
    expected_keys = ["symbol", "buy_prob", "sell_prob", "days_held", "pnl_USDC", "pnl_pct", "status"]
    for trade in trades:
        # Pour days_held, si entry_date et exit_date sont présents, on peut calculer
        if "days_held" not in trade:
            if "entry_date" in trade and "exit_date" in trade:
                try:
                    entry = pd.to_datetime(trade["entry_date"])
                    exit = pd.to_datetime(trade["exit_date"])
                    trade["days_held"] = (exit - entry).days
                except Exception:
                    trade["days_held"] = "N/A"
            else:
                trade["days_held"] = "N/A"
        # Pour les autres clés, si elles n'existent pas, on leur affecte une valeur par défaut
        for key in ["buy_prob", "sell_prob", "pnl_USDC", "pnl_pct", "status"]:
            if key not in trade:
                # Pour pnl_USDC et pnl_pct, on met 0 ; pour les autres, "N/A"
                trade[key] = 0 if key in ["pnl_USDC", "pnl_pct"] else "N/A"

    trades.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return trades

########################
# 3) Performance
########################

def record_portfolio_value(value_USDC):
    """
    Enregistre la valeur 'value_USDC' du portefeuille dans performance_history.json.
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
        "value_USDC": round(value_USDC, 2)
    }
    history.append(entry)
    history.sort(key=lambda x: x["timestamp"])
    with open(PERF_FILE, "w") as f:
        json.dump(history, f, indent=2)

def get_performance_history():
    """
    Calcule la performance sur 1d, 7d, 30d, etc. en se basant sur performance_history.json.
    Retourne un dict du type :
      { "1d": {"USDC": ..., "pct": ...}, "7d": {...}, "30d": {...}, "all": {...} }
    """
    if not os.path.exists(PERF_FILE):
        pf = get_portfolio_state()
        tv = pf["total_value_USDC"]
        return {
            "1d": {"USDC": tv, "pct": 0.0},
            "7d": {"USDC": tv, "pct": 0.0},
            "30d": {"USDC": tv, "pct": 0.0},
            "all": {"USDC": tv, "pct": 0.0},
        }
    with open(PERF_FILE, "r") as f:
        history = json.load(f)
    if not history:
        pf = get_portfolio_state()
        tv = pf["total_value_USDC"]
        return {
            "1d": {"USDC": tv, "pct": 0.0},
            "7d": {"USDC": tv, "pct": 0.0},
            "30d": {"USDC": tv, "pct": 0.0},
            "all": {"USDC": tv, "pct": 0.0},
        }
    last_entry = history[-1]
    current_val = last_entry["value_USDC"]
    now_ts = last_entry["timestamp"]

    def find_val_x_days_ago(x_days):
        target_ts = now_ts - x_days * 86400
        candidates = [h for h in history if h["timestamp"] <= target_ts]
        if not candidates:
            return None
        return candidates[-1]["value_USDC"]

    def compute_perf(x_days):
        old_val = find_val_x_days_ago(x_days)
        if old_val is None or old_val <= 0:
            return {"USDC": current_val, "pct": 0.0}
        diff = current_val - old_val
        pct = (diff / old_val) * 100
        return {"USDC": current_val, "pct": round(pct, 2)}

    perf_1d = compute_perf(1)
    perf_7d = compute_perf(7)
    perf_30d = compute_perf(30)
    first_val = history[0]["value_USDC"]
    pct_all = (current_val - first_val) / first_val * 100 if first_val > 0 else 0.0

    return {
        "1d": perf_1d,
        "7d": perf_7d,
        "30d": perf_30d,
        "all": {"USDC": current_val, "pct": round(pct_all, 2)}
    }

########################
# 4) Emergency Out
########################

def emergency_out():
    """
    Vend toutes les positions (sauf USDC).
    """
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    info = bexec.client.get_account()
    for b in info["balances"]:
        asset = b["asset"]
        qty = float(b["free"]) + float(b["locked"])
        if qty > 0 and asset.upper() != "USDC":
            bexec.sell_all(asset, qty)
    logging.info("[EMERGENCY] Tout vendu.")

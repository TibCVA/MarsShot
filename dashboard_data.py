#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import yaml
import json
import time
import datetime

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

TRADE_FILE = "trade_history.json"
PERF_FILE  = "performance_history.json"

########################
# 1) Portfolio actuel
########################

def get_portfolio_state():
    """
    Retourne un dict {"positions":[...], "total_value_usdt":...} 
    représentant la liste des tokens (symbol, qty, value_usdt)
    et la somme totale en USDT.
    """
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    info  = bexec.client.get_account()
    bals  = info["balances"]

    positions = []
    total_val = 0.0

    for b in bals:
        asset = b["asset"]
        free  = float(b["free"])
        locked= float(b["locked"])
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
            "qty":   round(qty, 4),
            "value_usdt": round(val_usdt, 2)
        })
        total_val += val_usdt

    return {
        "positions": positions,
        "total_value_usdt": round(total_val, 2)
    }

def list_tokens_tracked():
    """
    Retourne la liste des tokens_daily définis dans config.yaml
    (qu'on veut surveiller/présenter).
    """
    return CONFIG.get("tokens_daily", [])

########################
# 2) Historique de trades
########################

def get_trades_history():
    """
    Lit le fichier trade_history.json pour récupérer l'historique complet 
    (BUY / SELL). On retourne une liste triée par date décroissante 
    (du plus récent au plus ancien).
    """
    if not os.path.exists(TRADE_FILE):
        return []

    with open(TRADE_FILE, "r") as f:
        trades = json.load(f)

    # Tri par timestamp décroissant
    trades.sort(key=lambda x: x["timestamp"], reverse=True)
    return trades

########################
# 3) Performance 
########################

def record_portfolio_value(value_usdt):
    """
    Enregistre la valeur 'value_usdt' du portefeuille dans 
    performance_history.json, associée à la date/heure actuelle.
    On stocke un timestamp (en secondes) et la valeur.
    """
    history = []
    if os.path.exists(PERF_FILE):
        with open(PERF_FILE, "r") as f:
            history = json.load(f)

    now_ts = time.time()
    # Optionnel : arrondir la valeur pour un JSON plus lisible
    entry = {
        "timestamp": now_ts,
        "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts)),
        "value_usdt": round(value_usdt, 2)
    }
    history.append(entry)

    # On peut trier par timestamp croissant
    history.sort(key=lambda x: x["timestamp"])
    with open(PERF_FILE, "w") as f:
        json.dump(history, f, indent=2)

def get_performance_history():
    """
    Calcul la performance sur 1j, 7j, 30j, etc. en se basant 
    sur performance_history.json (les enregistrements successifs).
    
    Retourne un dict du type:
      {
        "1d":  {"usdt": ..., "pct": ...},
        "7d":  {"usdt": ..., "pct": ...},
        "30d": {"usdt": ..., "pct": ...},
        "all": {"usdt": ..., "pct": ...}
      }
    """
    # On charge l'historique
    if not os.path.exists(PERF_FILE):
        # Pas d'historique => on prend la valeur courante 
        pf = get_portfolio_state()
        tv = pf["total_value_usdt"]
        return {
            "1d":  {"usdt": tv, "pct": 0.0},
            "7d":  {"usdt": tv, "pct": 0.0},
            "30d": {"usdt": tv, "pct": 0.0},
            "all": {"usdt": tv, "pct": 0.0},
        }

    with open(PERF_FILE, "r") as f:
        history = json.load(f)

    if not history:
        # Pareil, pas d'histo => juste la valeur courante
        pf = get_portfolio_state()
        tv = pf["total_value_usdt"]
        return {
            "1d":  {"usdt": tv, "pct": 0.0},
            "7d":  {"usdt": tv, "pct": 0.0},
            "30d": {"usdt": tv, "pct": 0.0},
            "all": {"usdt": tv, "pct": 0.0},
        }

    # Valeur actuelle = dernier enregistrement
    last_entry = history[-1]
    current_val = last_entry["value_usdt"]

    # Pour trouver la valeur d'il y a X jours, 
    # on remonte dans l'historique pour trouver la plus proche
    # ex: horizon 1d => on cherche timestamp ~ Tnow - 86400
    now_ts = last_entry["timestamp"]

    def find_val_x_days_ago(x_days):
        target_ts = now_ts - x_days * 86400
        # On cherche l'entrée la plus proche (mais <= target_ts)
        candidates = [h for h in history if h["timestamp"] <= target_ts]
        if not candidates:
            return None
        return candidates[-1]["value_usdt"]  # la plus récente avant ou à target_ts

    def compute_perf(x_days):
        old_val = find_val_x_days_ago(x_days)
        if old_val is None or old_val<=0:
            # pas d'entrée => ou 0 => on renvoie {usdt=.., pct=0}
            return {"usdt": current_val, "pct": 0.0}
        # Variation
        diff = current_val - old_val
        pct  = (diff / old_val)*100
        return {"usdt": current_val, "pct": round(pct,2)}

    perf_1d   = compute_perf(1)
    perf_7d   = compute_perf(7)
    perf_30d  = compute_perf(30)

    # Perf "all" => par rapport au tout premier
    first_val = history[0]["value_usdt"]
    if first_val>0:
        diff_all = current_val - first_val
        pct_all  = (diff_all / first_val)*100
    else:
        pct_all  = 0.0

    return {
        "1d":   perf_1d,
        "7d":   perf_7d,
        "30d":  perf_30d,
        "all":  {"usdt": current_val, "pct": round(pct_all,2)}
    }

########################
# 4) Emergency Out
########################

def emergency_out():
    """
    Vend tout sauf USDT.
    """
    bexec= TradeExecutor(BINANCE_KEY,BINANCE_SECRET)
    info= bexec.client.get_account()
    for b in info["balances"]:
        asset= b["asset"]
        qty= float(b["free"])+ float(b["locked"])
        if qty>0 and asset.upper()!="USDT":
            bexec.sell_all(asset, qty)
    logging.info("[EMERGENCY] Tout vendu.")
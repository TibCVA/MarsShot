#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import yaml
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

# ------------------------------
# 1) Portfolio actuel
# ------------------------------
def get_portfolio_state():
    """
    Retourne un dict {"positions":[...], "total_value_usdt":...} 
    avec la liste des tokens et leur valeur en USDT.
    """
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    info  = bexec.client.get_account()
    bals  = info["balances"]
    positions= []
    total_val= 0.0

    for b in bals:
        asset= b["asset"]
        free = float(b["free"])
        locked= float(b["locked"])
        qty= free + locked
        if qty<=0:
            continue
        if asset.upper()=="USDT":
            val_usdt= qty
        else:
            px= bexec.get_symbol_price(asset)
            val_usdt= px*qty
        positions.append({
            "symbol": asset,
            "qty": round(qty,4),
            "value_usdt": round(val_usdt,2)
        })
        total_val += val_usdt

    return {
        "positions": positions,
        "total_value_usdt": round(total_val,2)
    }

def list_tokens_tracked():
    """Retourne la liste des tokens_daily (extrait de config.yaml)."""
    return CONFIG.get("tokens_daily", [])

# ------------------------------
# 2) Performance (exemple minimal)
# ------------------------------
def get_performance_history():
    """
    Ex. renvoie un dict structuré pour usage simplifié:
      {
        "1d": {"usdt":..., "pct":...},
        "7d": {"usdt":..., "pct":...},
        "all": {...}
      }
    Pour l'instant c'est fictif, on se base juste sur la valeur courante.
    """
    pf= get_portfolio_state()
    tv= pf["total_value_usdt"]
    return {
      "1d":  {"usdt":tv, "pct":0.0},
      "7d":  {"usdt":tv, "pct":0.0},
      "1m":  {"usdt":tv, "pct":0.0},
      "3m":  {"usdt":tv, "pct":0.0},
      "1y":  {"usdt":tv, "pct":0.0},
      "all": {"usdt":tv, "pct":0.0}
    }

# ------------------------------
# 3) Lecture de l'historique de trades
# ------------------------------
def get_trades_history():
    """
    Charge le fichier trade_history.json pour récupérer l'historique complet 
    (BUY / SELL). Retourne une liste triée par date (récente d'abord).
    """
    import json
    TRADE_FILE = "trade_history.json"
    if not os.path.exists(TRADE_FILE):
        return []

    with open(TRADE_FILE,"r") as f:
        trades= json.load(f)

    # On peut trier trades par timestamp descendant
    trades.sort(key=lambda x: x["timestamp"], reverse=True)
    return trades

# ------------------------------
# 4) Emergency
# ------------------------------
def emergency_out():
    """
    Vend tout sauf USDT (pour un "panic sell" complet).
    """
    bexec= TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    info= bexec.client.get_account()
    for b in info["balances"]:
        asset= b["asset"]
        qty= float(b["free"])+ float(b["locked"])
        if qty>0 and asset.upper()!="USDT":
            bexec.sell_all(asset, qty)
    logging.info("[EMERGENCY] Tout vendu.")
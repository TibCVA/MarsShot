#!/usr/bin/env python3
# coding: utf-8

import os
import logging
import yaml

from modules.positions_store import load_state, save_state
from modules.trade_executor import TradeExecutor
from modules.utils import send_telegram_message

CONFIG_FILE = "config.yaml"
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

BINANCE_KEY    = CONFIG["binance_api"]["api_key"]
BINANCE_SECRET = CONFIG["binance_api"]["api_secret"]

logging.basicConfig(level=logging.INFO)

###########################
# FONCTIONS "REAL DATA"
###########################

def get_portfolio_state():
    """
    Renvoie un dict du type:
      {
        "positions": [
           {
             "symbol": "FET",
             "qty": 123.45,
             "value_usdt": 456.78,
             "pnl_1d": +5.0,
             "pnl_7d": +12.0,
             "pnl_30d": +20.0,
             "pnl_since_entry": +30.0
           },
           ...
        ],
        "total_value_usdt": 2345.67
      }
    """
    from modules.trade_executor import TradeExecutor
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)

    # Charger l'état => bot_state.json (positions, capital_usdt, etc.)
    from modules.positions_store import load_state
    st = load_state(CONFIG["strategy"]["capital_initial"])
    positions_dict = st["positions"]  # ex: { "FET":{qty=...,entry_price=...}, ... }

    total_val = 0.0
    pos_list = []

    for sym, pos in positions_dict.items():
        qty = pos["qty"]
        entry_px = pos["entry_price"]
        # Récup prix actuel
        current_px = bexec.get_symbol_price(sym)  # ex. "FET" => FETUSDT
        val_usdt = current_px * qty
        total_val += val_usdt

        # Perf "since entry"
        if entry_px>0:
            perf_since = ((current_px - entry_px)/entry_px)*100
        else:
            perf_since = 0.0

        # Perf 1j
        px_1d_ago = bexec.get_kline_close(sym, days=1)
        if px_1d_ago and px_1d_ago>0:
            pnl_1d = (current_px - px_1d_ago)/px_1d_ago*100
        else:
            pnl_1d = 0.0

        # Perf 7j
        px_7d_ago = bexec.get_kline_close(sym, days=7)
        if px_7d_ago and px_7d_ago>0:
            pnl_7d = (current_px - px_7d_ago)/px_7d_ago*100
        else:
            pnl_7d = 0.0

        # Perf 30j
        px_30d_ago = bexec.get_kline_close(sym, days=30)
        if px_30d_ago and px_30d_ago>0:
            pnl_30d = (current_px - px_30d_ago)/px_30d_ago*100
        else:
            pnl_30d = 0.0

        pos_list.append({
            "symbol": sym,
            "qty": round(qty,4),
            "value_usdt": round(val_usdt,2),
            "pnl_1d": round(pnl_1d,1),
            "pnl_7d": round(pnl_7d,1),
            "pnl_30d": round(pnl_30d,1),
            "pnl_since_entry": round(perf_since,1)
        })

    return {
        "positions": pos_list,
        "total_value_usdt": round(total_val,2)
    }

def list_tokens_tracked():
    return CONFIG["tokens_daily"]

def get_performance_history():
    """
    Ici, si tu veux un autre format (1d,7d,1m,3m,1y,all),
    tu peux soit réutiliser le portfolio info,
    soit calculer plus globalement.
    Pour l'exemple, on va calculer la perf "moyenne" sur 1d,7d,... 
    Mieux : On peut te renvoyer un dict comme :

    {
      "1d":  {"usdt": +XX, "pct": +YY},
      "7d":  {"usdt": +..., "pct": ...},
      ...
    }

    Mais c'est libre selon ton usage. On peut se baser sur la
    somme "positions" -> "pnl_1d" ...
    """
    pf = get_portfolio_state()

    # On calcule la somme des variations ?

    # Ex: On fait un "moyenne" => pour l'exemple, on additionne les value_usdt
    # On somme p['pnl_1d'] ...
    # Code simplifié:
    sum_val = pf["total_value_usdt"]
    sum_1d = 0.0
    sum_7d = 0.0
    sum_30d = 0.0
    for p in pf["positions"]:
        sum_1d += p["pnl_1d"]
        sum_7d += p["pnl_7d"]
        sum_30d+= p["pnl_30d"]

    # On renvoie un exemple. Tu peux affiner.
    return {
      "1d":  {"usdt": round(sum_val*(sum_1d/100.0),2),
              "pct": round(sum_1d/len(pf["positions"]),2) if pf["positions"] else 0.0 },
      "7d":  {"usdt": round(sum_val*(sum_7d/100.0),2),
              "pct": round(sum_7d/len(pf["positions"]),2) if pf["positions"] else 0.0 },
      "1m":  {"usdt": round(sum_val*(sum_30d/100.0),2),
              "pct": round(sum_30d/len(pf["positions"]),2) if pf["positions"] else 0.0 },
      # on fait "3m", "1y", "all" => placeholders
      "3m":  {"usdt": 0.0, "pct":0.0},
      "1y":  {"usdt": 0.0, "pct":0.0},
      "all": {"usdt": 0.0, "pct":0.0}
    }

def get_trades_history():
    """
    Récupérer l'historique de trades fermés => tu peux stocker dans un fichier
    ou dans bot_state.json (une section 'closed_trades' ?).
    Ici on fait un exemple pour dire 'gagnant', 'perdant'.

    Pour un vrai code: 
    - Soit tu conserves un log de trades dans positions_store.py,
    - Soit tu as un CSV ou une DB.

    Je te mets un exemple "réel" => lisons st["closed_trades"] si existant :
    """
    st = load_state(CONFIG["strategy"]["capital_initial"])
    closed_list = st.get("closed_trades", [])

    # Chaque élément pourrait ressembler à:
    # {
    #   "symbol":"FET",
    #   "buy_prob":0.85,
    #   "sell_prob":0.25,
    #   "days_held":12,
    #   "pnl_usdt":30.0,
    #   "pnl_pct":60.0,
    #   "status":"gagnant"
    # }
    # on le renvoie direct
    return closed_list

def emergency_out():
    """
    Vend TOUTES les positions => USDT (même code que Telegram).
    """
    st = load_state(CONFIG["strategy"]["capital_initial"])
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    for sym, pos in list(st["positions"].items()):
        qty = pos["qty"]
        val = bexec.sell_all(sym, qty)
        st["capital_usdt"] += val
        del st["positions"][sym]
    save_state(st)
    logging.info("[EMERGENCY] Tout vendu via dashboard_data")


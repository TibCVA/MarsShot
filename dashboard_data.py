#!/usr/bin/env python3
# coding: utf-8

import os
import logging
import yaml

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

##########################################
# Lecture réelle du solde sur Binance
##########################################

def get_portfolio_state():
    """
    Lit le solde spot sur Binance (free + locked).
    Pour chaque coin > 0, convertit en USDT via le pair "COINUSDT" (si existant).
    Renvoie:
      {
        "positions":[
          {"symbol":"BNB", "qty": 2.345, "value_usdt":123.45},
          {"symbol":"USDT","qty":80.0,  "value_usdt":80.0},
          ...
        ],
        "total_value_usdt": 456.78
      }
    """
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    client = bexec.client  # binance.client.Client

    account_info = client.get_account()  # dict => { "balances":[{"asset":"BNB","free":"2.3","locked":"0.1"},...], ...}
    balances = account_info.get("balances", [])

    positions_list = []
    total_val = 0.0

    for b in balances:
        asset = b["asset"]
        free  = float(b["free"])
        locked= float(b["locked"])
        qty   = free + locked
        if qty <= 0:
            continue  # ignore

        # Cas simple: si asset="USDT", on le prend tel quel
        if asset == "USDT":
            val_usdt = qty
            positions_list.append({
                "symbol": asset,
                "qty": round(qty,4),
                "value_usdt": round(val_usdt,2)
            })
            total_val += val_usdt
            continue

        # Sinon, on tente de convertir en USDT => pair = ASSET + "USDT"
        pair_symbol = asset + "USDT"
        try:
            px = bexec.get_symbol_price(asset)  # On adaptera => voir plus bas
            # ou on fait: px = bexec.client.get_symbol_ticker(symbol=pair_symbol)["price"]
            # s'il n'existe pas => exception
        except Exception as e:
            logging.warning(f"[REAL BALANCES] {asset} => pair {pair_symbol} introuvable => skip. {e}")
            continue

        px = bexec.get_symbol_price(asset)
        val_usdt = px * qty
        positions_list.append({
            "symbol": asset,
            "qty": round(qty,4),
            "value_usdt": round(val_usdt,2)
        })
        total_val += val_usdt

    return {
        "positions": positions_list,
        "total_value_usdt": round(total_val,2)
    }

def list_tokens_tracked():
    """
    Par cohérence, on peut renvoyer config["tokens_daily"] ou lister
    réellement ce qu'on a sur Binance. A vous de décider.
    Ici, on fait comme avant => config
    """
    return CONFIG["tokens_daily"]

def get_performance_history():
    """
    On ne peut pas calculer de "pnl_1d" etc. sur un vrai compte
    sans un tracking plus poussé. 
    Soit on renvoie qqch de minimal, 
    soit on fait un "placeholder" 0.0
    """
    pf = get_portfolio_state()
    total_val = pf["total_value_usdt"]
    # On renvoie un dict standard
    return {
      "1d":  {"usdt": 0.0, "pct":0.0},
      "7d":  {"usdt": 0.0, "pct":0.0},
      "1m":  {"usdt": 0.0, "pct":0.0},
      "3m":  {"usdt": 0.0, "pct":0.0},
      "1y":  {"usdt": 0.0, "pct":0.0},
      "all": {"usdt": round(total_val,2), "pct":0.0}  # "all" => total
    }

def get_trades_history():
    """
    Sur un vrai compte, on pourrait faire client.get_my_trades() ...
    Ici, renvoie un tableau vide => ou l'historique si on le veut.
    """
    return []

def emergency_out():
    """
    Sur un vrai compte, 'emergency out' = Vendre TOUT
    => on vend tout sauf USDT (car c'est déjà USDT).
    """
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    client = bexec.client
    # On relit get_account => pour tout soldes
    account_info = client.get_account()
    balances = account_info.get("balances", [])

    for b in balances:
        asset = b["asset"]
        free  = float(b["free"])
        locked= float(b["locked"])
        qty   = free + locked
        if qty<=0:
            continue
        if asset=="USDT":
            continue  # rien à vendre
        pair_symbol = asset+"USDT"

        try:
            # On vend tout
            bexec.sell_all(asset, qty)  # ex. "BNB", 2.345 => => BNBUSDT market SELL
        except Exception as e:
            logging.warning(f"[EMERGENCY OUT real] Echec de vente {asset} => {e}")
    logging.info("[EMERGENCY] Tout vendu en USDT sur compte spot.")

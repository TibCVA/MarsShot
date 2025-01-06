#!/usr/bin/env python3
# coding: utf-8

import os
import logging
import yaml

from modules.trade_executor import TradeExecutor

CONFIG_FILE = "config.yaml"
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

BINANCE_KEY    = CONFIG["binance_api"]["api_key"]
BINANCE_SECRET = CONFIG["binance_api"]["api_secret"]

logging.basicConfig(level=logging.INFO)

def get_portfolio_state():
    """
    Lit solde SPOT sur Binance => renvoie un dict positions[], total_value_usdt
    """
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    client= bexec.client
    info= client.get_account()
    bals= info["balances"]

    positions=[]
    total_val=0.0

    for b in bals:
        asset= b["asset"]
        free= float(b["free"])
        locked= float(b["locked"])
        qty= free+ locked
        if qty<=0: 
            continue
        if asset.upper()=="USDT":
            val_usdt= qty
        else:
            try:
                px= bexec.get_symbol_price(asset)
                val_usdt= px* qty
            except:
                logging.warning(f"[DASHBOARD] No pair {asset}USDT => skipping.")
                continue
        positions.append({
            "symbol": asset,
            "qty": round(qty,4),
            "value_usdt": round(val_usdt,2)
        })
        total_val+= val_usdt

    return {
        "positions": positions,
        "total_value_usdt": round(total_val,2)
    }

def list_tokens_tracked():
    return CONFIG["tokens_daily"]

def get_performance_history():
    pf= get_portfolio_state()
    tv= pf["total_value_usdt"]
    return {
      "1d":{"usdt":0.0,"pct":0.0},
      "7d":{"usdt":0.0,"pct":0.0},
      "1m":{"usdt":0.0,"pct":0.0},
      "3m":{"usdt":0.0,"pct":0.0},
      "1y":{"usdt":0.0,"pct":0.0},
      "all":{"usdt": tv,"pct":0.0}
    }

def get_trades_history():
    # On pourrait recup client.get_my_trades()...
    # Pour l'instant, on renvoie []
    return []

def emergency_out():
    """
    On vend tout sauf USDT
    """
    bexec= TradeExecutor(BINANCE_KEY,BINANCE_SECRET)
    info= bexec.client.get_account()
    for b in info["balances"]:
        asset= b["asset"]
        qty= float(b["free"])+ float(b["locked"])
        if qty>0 and asset.upper()!="USDT":
            val= bexec.sell_all(asset, qty)
            logging.info(f"[EMERGENCY] sold {asset} => {val:.2f} USDT")
    logging.info("[EMERGENCY] Tout vendu.")

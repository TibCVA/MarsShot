import logging
import time
import os
from binance.client import Client
from .positions_store import get_symbol_for_token

def _init_binance_client(config):
    k = config["binance_api"]["api_key"]
    s = config["binance_api"]["api_secret"]
    return Client(k,s)

def smart_buy(sym, quantity, config, data_map):
    symbol = get_symbol_for_token(sym)
    attempts = config["execution"]["retry_count"]
    qty = round(quantity,5)
    client = _init_binance_client(config)
    for attempt in range(attempts):
        try:
            order = client.create_order(
                symbol=symbol,
                side="BUY",
                type="MARKET",
                quantity=qty
            )
            logging.info(f"[BUY] {sym} => qty={qty}")
            return True
        except Exception as e:
            logging.error(f"[BUY ERROR] {sym} => {e}")
            time.sleep(2)
    return False

def smart_sell(sym, quantity, config):
    symbol = get_symbol_for_token(sym)
    attempts = config["execution"]["retry_count"]
    qty = round(quantity,5)
    client = _init_binance_client(config)
    for attempt in range(attempts):
        try:
            order = client.create_order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=qty
            )
            logging.info(f"[SELL] {sym} => qty={qty}")
            return True
        except Exception as e:
            logging.error(f"[SELL ERROR] {sym} => {e}")
            time.sleep(2)
    return False

def sell_all_positions(state, config):
    for sym, pos in list(state["positions"].items()):
        qty = pos["qty"]
        smart_sell(sym, qty, config)
    state["positions"] = {}

def sync_balances(state, config):
    client = _init_binance_client(config)
    try:
        acc = client.get_account()["balances"]
        usdt = 0.0
        for b in acc:
            if b["asset"]=="USDT":
                usdt = float(b["free"])
        state["capital"] = usdt
    except Exception as e:
        logging.error(f"[SYNC BAL ERROR] {e}")


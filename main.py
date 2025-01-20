#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import logging
import datetime
import yaml
import os
import pytz
import subprocess

from modules.trade_executor import TradeExecutor
from modules.positions_store import load_state, save_state
from modules.risk_manager import intraday_check_real

########################################
# Fonctions utilitaires
########################################

def load_probabilities_csv(csv_path="daily_probabilities.csv"):
    import pandas as pd
    if not os.path.exists(csv_path):
        logging.warning(f"[load_probabilities_csv] {csv_path} introuvable => return {{}}")
        return {}
    df = pd.read_csv(csv_path)
    if df.empty:
        logging.warning(f"[load_probabilities_csv] {csv_path} est vide => return {{}}")
        return {}
    prob_map = {}
    for i, row in df.iterrows():
        sym = str(row["symbol"]).strip()
        p   = float(row["prob"])
        prob_map[sym] = p
    return prob_map

def run_auto_select_once_per_day(state):
    """
    Vérifie si nous avons déjà lancé 'auto_select_tokens.py' aujourd'hui.
    Si non, on exécute le script, puis on met à jour le state pour ne pas relancer.
    """
    if state.get("did_auto_select_today", False):
        return  # déjà fait ce jour

    logging.info("[MAIN] => auto_select_tokens.py => start")
    try:
        # Lancement du script auto_select_tokens.py
        subprocess.run(["python", "auto_select_tokens.py"], check=False)
        state["did_auto_select_today"] = True
        save_state(state)
        logging.info("[MAIN] => auto_select_tokens OK => state updated")
    except Exception as e:
        logging.error(f"[MAIN] run_auto_select_once_per_day => {e}")

def daily_update_live(state, config, bexec):
    """
    Exécute le data_fetcher + ml_decision, puis la logique SELL/BUY 'daily'
    """
    logging.info("[DAILY UPDATE] Start daily_update_live")

    # 1) data_fetcher
    try:
        logging.info("[DAILY UPDATE] => modules/data_fetcher.py")
        subprocess.run(["python", "modules/data_fetcher.py"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] data_fetcher => {e}")

    # 2) ml_decision
    try:
        logging.info("[DAILY UPDATE] => modules/ml_decision.py")
        subprocess.run(["python", "modules/ml_decision.py"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] ml_decision => {e}")

    # 3) Chargement probas
    prob_map = load_probabilities_csv("daily_probabilities.csv")
    tokens   = config["tokens_daily"]
    strat    = config["strategy"]
    logging.info(f"[DAILY UPDATE] tokens_daily={tokens}")

    # 4) Récup solde compte
    try:
        account_info = bexec.client.get_account()
    except Exception as e:
        logging.error(f"[DAILY UPDATE] get_account => {e}")
        return

    balances = account_info.get("balances", [])
    holdings = {}
    usdt_balance = 0.0
    for b in balances:
        asset  = b["asset"]
        free   = float(b["free"])
        locked = float(b["locked"])
        qty    = free + locked
        if asset.upper() == "USDT":
            usdt_balance = qty
        elif qty > 0:
            holdings[asset] = qty

    logging.info(f"[DAILY UPDATE] holdings={holdings}, usdt={usdt_balance:.2f}")

    # 5) SELL logic
    for asset, real_qty in holdings.items():
        prob = prob_map.get(asset, None)
        logging.info(f"[DAILY SELL CHECK] {asset}, prob={prob}")
        if prob is None:
            logging.info(f"[DAILY SELL] {asset} => prob=None => skip.")
            continue

        if prob < strat["sell_threshold"]:
            meta      = state["positions_meta"].get(asset, {})
            did_skip  = meta.get("did_skip_sell_once", False)
            entry_px  = meta.get("entry_px", None)
            current_px= bexec.get_symbol_price(asset)

            if entry_px and entry_px > 0:
                ratio = current_px / entry_px
                # big_gain_exception_pct => on skip la vente 1 fois si on dépasse
                if ratio >= strat["big_gain_exception_pct"] and not did_skip:
                    meta["did_skip_sell_once"] = True
                    state["positions_meta"][asset] = meta
                    logging.info(f"[DAILY SELL SKIP big gain] {asset}, ratio={ratio:.2f}, prob={prob:.2f}")
                    continue

            sold_val = bexec.sell_all(asset, real_qty)
            logging.info(f"[DAILY SELL LIVE] {asset}, prob={prob:.2f}, sold_val={sold_val:.2f}")
            if asset in state["positions_meta"]:
                del state["positions_meta"][asset]
            save_state(state)

    # 6) BUY => top 5 par proba
    buy_candidates = []
    for sym in tokens:
        if sym in holdings:
            continue
        p = prob_map.get(sym, None)
        logging.info(f"[DAILY BUY CHECK] {sym}, prob={p}")
        if p is not None and p >= strat["buy_threshold"]:
            buy_candidates.append((sym, p))

    buy_candidates.sort(key=lambda x: x[1], reverse=True)
    buy_candidates = buy_candidates[:5]
    logging.info(f"[DAILY BUY SELECT] => {buy_candidates}")

    if buy_candidates and usdt_balance > 10:
        alloc = usdt_balance / len(buy_candidates)
        for sym, pb in buy_candidates:
            qty_bought, avg_px = bexec.buy(sym, alloc)
            logging.info(f"[DAILY BUY EXEC] => {sym}, qty={qty_bought}, px={avg_px:.4f}")
            if qty_bought > 0:
                state["positions_meta"][sym] = {
                    "entry_px": avg_px,
                    "did_skip_sell_once": False,
                    "partial_sold": False,
                    "max_price": avg_px
                }
                usdt_balance -= alloc
                save_state(state)

    logging.info("[DAILY UPDATE] Done daily_update_live")

########################################
# MAIN
########################################
def main():
    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml introuvable.")
        return

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    logging.basicConfig(
        filename=config["logging"]["file"],
        filemode='a',
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("[MAIN] Starting main loop (LIVE).")

    # Chargement du state
    state = load_state()
    logging.info(f"[MAIN] Loaded state => keys={list(state.keys())}")

    # Initialisation Binance
    bexec = TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )
    logging.info("[MAIN] TradeExecutor initialized.")

    # Fuseau pour heure Paris
    paris_tz = pytz.timezone("Europe/Paris")

    while True:
        try:
            now_paris = datetime.datetime.now(paris_tz)
            hour_p = now_paris.hour
            min_p  = now_paris.minute

            # 1) auto_select => 22h25
            if hour_p == 22 and min_p == 25 and not state.get("did_auto_select_today", False):
                run_auto_select_once_per_day(state)

            # 2) daily => 22h35
            if hour_p == 22 and min_p == 35 and not state.get("did_daily_update_today", False):
                logging.info("[MAIN] 22h35 => daily_update_live.")
                daily_update_live(state, config, bexec)
                state["did_daily_update_today"] = True
                save_state(state)
                logging.info("[MAIN] daily_update_today => True.")

            # 3) Reset flags si on n'est plus dans l'heure 22
            if hour_p != 22:
                if state.get("did_auto_select_today", False):
                    logging.info("[MAIN] reset did_auto_select_today.")
                state["did_auto_select_today"] = False

                if state.get("did_daily_update_today", False):
                    logging.info("[MAIN] reset daily_update_today.")
                state["did_daily_update_today"] = False

                save_state(state)

            # 4) Intraday check => toutes X secondes
            last_check = state.get("last_risk_check_ts", 0)
            elapsed = time.time() - last_check
            if elapsed >= config["strategy"]["check_interval_seconds"]:
                logging.info("[MAIN] intraday_check_real()")
                intraday_check_real(state, bexec, config)
                state["last_risk_check_ts"] = time.time()
                save_state(state)

        except Exception as e:
            logging.error(f"[MAIN ERROR] {e}")

        time.sleep(10)

if __name__ == "__main__":
    main()
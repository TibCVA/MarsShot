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
        prob = float(row["prob"])
        prob_map[sym] = prob
    return prob_map

def run_auto_select_once_per_day(state):
    """
    Sélection auto de tokens (exécute auto_select_tokens.py) si pas déjà fait aujourd'hui.
    """
    if state.get("did_auto_select_today", False):
        return
    logging.info("[MAIN] => auto_select_tokens.py => start")
    try:
        # Exécution synchronisée : on attend la fin du script
        subprocess.run(["python", "auto_select_tokens.py"], check=False)
        state["did_auto_select_today"] = True
        save_state(state)
        logging.info("[MAIN] => auto_select_tokens OK => state updated")
    except Exception as e:
        logging.error(f"[MAIN] run_auto_select_once_per_day => {e}")

def daily_update_live(state, bexec):
    """
    Recharge config.yaml (pour lire les tokens modifiés par auto_select),
    lance data_fetcher, puis ml_decision si CSV existe et n'est pas vide,
    puis effectue la logique daily SELL/BUY sur base des probas.
    """
    logging.info("[DAILY UPDATE] Start daily_update_live")

    # Recharger config.yaml (important si auto_select_tokens.py a modifié tokens_daily)
    if not os.path.exists("config.yaml"):
        logging.error("[DAILY UPDATE] config.yaml introuvable.")
        return
    with open("config.yaml","r") as f:
        config = yaml.safe_load(f)

    # 1) data_fetcher
    try:
        logging.info("[DAILY UPDATE] => modules/data_fetcher.py")
        ret = subprocess.run(["python", "modules/data_fetcher.py"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] data_fetcher => {e}")
        return

    # Vérifier si daily_inference_data.csv est créé et non vide
    csv_data = "daily_inference_data.csv"
    if not os.path.exists(csv_data):
        logging.warning(f"[DAILY UPDATE] {csv_data} introuvable => skip ml_decision.")
        # On skip la suite => pas de probas
        return
    import os
    if os.path.getsize(csv_data) < 100:  # par ex. 100 octets
        logging.warning(f"[DAILY UPDATE] {csv_data} trop petit => skip ml_decision.")
        return

    # 2) ml_decision
    try:
        logging.info("[DAILY UPDATE] => modules/ml_decision.py")
        ret2 = subprocess.run(["python", "modules/ml_decision.py"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] ml_decision => {e}")
        return

    # 3) Charger probas
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
        asset = b["asset"]
        free  = float(b["free"])
        locked= float(b["locked"])
        qty   = free + locked
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
            meta = state["positions_meta"].get(asset, {})
            did_skip = meta.get("did_skip_sell_once", False)
            entry_px = meta.get("entry_px", None)
            current_px = bexec.get_symbol_price(asset)

            if entry_px and entry_px > 0:
                ratio = current_px / entry_px
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

    # 6) BUY => top 5
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

def main():
    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml introuvable.")
        return

    # Charger une première fois config.yaml (même si on rechargera plus tard)
    with open("config.yaml","r") as f:
        config = yaml.safe_load(f)

    logging.basicConfig(
        filename=config["logging"]["file"],
        filemode='a',
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("[MAIN] Starting main loop (LIVE).")

    # Charger le state
    state = load_state()
    logging.info(f"[MAIN] Loaded state => keys={list(state.keys())}")

    # Init binance
    bexec = TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )
    logging.info("[MAIN] TradeExecutor initialized.")

    # Fuseau
    paris_tz = pytz.timezone("Europe/Paris")

    while True:
        try:
            now_paris = datetime.datetime.now(paris_tz)
            hour_p = now_paris.hour
            min_p  = now_paris.minute

            # 1) auto_select => 00h25 (heure Paris)
            if hour_p == 0 and min_p == 25 and not state.get("did_auto_select_today", False):
                run_auto_select_once_per_day(state)

            # 2) daily => 00h35 (heure Paris)
            if hour_p == 0 and min_p == 35 and not state.get("did_daily_update_today", False):
                logging.info("[MAIN] 00h35 => daily_update_live.")
                daily_update_live(state, bexec)
                state["did_daily_update_today"] = True
                save_state(state)
                logging.info("[MAIN] daily_update_today => True.")

            # 3) Reset flags si on n'est plus dans l'heure 0
            if hour_p != 0:
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

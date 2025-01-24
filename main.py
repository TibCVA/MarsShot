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
    for _, row in df.iterrows():
        sym = str(row["symbol"]).strip()
        p   = float(row["prob"])
        prob_map[sym] = p
    return prob_map

def run_auto_select_once_per_day(state):
    """
    Vérifie si on a déjà lancé auto_select_tokens.py aujourd'hui.
    Si non, on exécute le script et on met à jour le state => did_auto_select_today.
    """
    if state.get("did_auto_select_today", False):
        return
    logging.info("[MAIN] => auto_select_tokens.py => start")
    try:
        subprocess.run(["python", "auto_select_tokens.py"], check=False)
        state["did_auto_select_today"] = True
        save_state(state)
        logging.info("[MAIN] => auto_select_tokens OK => state updated")
    except Exception as e:
        logging.error(f"[MAIN] run_auto_select_once_per_day => {e}")

def daily_update_live(state, bexec):
    """
    Logique daily update (Option2):
      - Recharge config.yaml => tokens_daily
      - Fusion => tokens_daily + positions_meta => extended_tokens_daily
      - data_fetcher + ml_decision => daily_probabilities.csv
      - SELL => tokens < 10 USDT de valeur + prob < sell_threshold (sauf USDT/BTC/FDUSD)
      - BUY => top 5 par prob, leftover dynamique, on autorise un “complément d'achat”
        si la valeur du token < 1 USDT par ex.
    """
    logging.info("[DAILY UPDATE] Start daily_update_live")

    if not os.path.exists("config.yaml"):
        logging.error("[DAILY UPDATE] config.yaml introuvable => skip daily_update.")
        return

    with open("config.yaml","r") as f:
        config = yaml.safe_load(f)

    tokens_daily = config.get("tokens_daily", [])
    strat        = config.get("strategy", {})
    threshold_val_usdt = 1.0  # si on a < 1 USDT sur un token, on considère qu'on peut le compléter

    # 1) Fusion tokens_daily + positions_meta => extended_tokens_daily
    system_positions = list(state["positions_meta"].keys())
    full_list = list(set(tokens_daily).union(set(system_positions)))
    logging.info(f"[DAILY UPDATE] union tokens => {full_list}")

    # On stocke ça dans config_temp.yaml
    config["extended_tokens_daily"] = full_list
    with open("config_temp.yaml","w") as fw:
        yaml.safe_dump(config, fw, sort_keys=False)

    # 2) data_fetcher => daily_inference_data.csv
    try:
        subprocess.run(["python", "modules/data_fetcher.py", "--config", "config_temp.yaml"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] data_fetcher => {e}")
        return

    # Vérif existence daily_inference_data.csv
    if (not os.path.exists("daily_inference_data.csv") 
        or os.path.getsize("daily_inference_data.csv") < 100):
        logging.warning("[DAILY UPDATE] daily_inference_data.csv introuvable ou vide => skip ml_decision")
        return

    # 3) ml_decision => daily_probabilities.csv
    try:
        subprocess.run(["python", "modules/ml_decision.py"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] ml_decision => {e}")
        return

    # 4) Charger probas
    prob_map = load_probabilities_csv("daily_probabilities.csv")
    logging.info(f"[DAILY UPDATE] tokens_daily={tokens_daily}, prob_map.size={len(prob_map)}")

    # 5) Récup solde compte
    try:
        account_info = bexec.client.get_account()
    except Exception as e:
        logging.error(f"[DAILY UPDATE] get_account => {e}")
        return

    # On calcule holdings en ignorant la partie locked pour USDT
    balances = account_info.get("balances", [])
    holdings = {}
    usdt_balance = 0.0
    for b in balances:
        asset = b["asset"]
        free_qty   = float(b["free"])
        locked_qty = float(b["locked"])

        # On ignore locked pour USDT => potentiellement cause d’erreur “Insufficient balance”
        if asset.upper() == "USDT":
            usdt_balance = free_qty  # on ne rajoute pas locked
        elif free_qty + locked_qty > 0:
            holdings[asset] = (free_qty + locked_qty)

    logging.info(f"[DAILY UPDATE] holdings={holdings}, usdt={usdt_balance:.2f}")

    # 6) SELL => tokens < 10 USDT + prob < sell_threshold (sauf USDT/BTC/FDUSD)
    sell_threshold = strat.get("sell_threshold", 0.3)
    big_gain_pct   = strat.get("big_gain_exception_pct", 10.0)
    for asset, real_qty in list(holdings.items()):
        if asset.upper() in ["USDT","BTC","FDUSD"]:
            logging.info(f"[DAILY SELL] skip => {asset} => stablecoin/BTC/FDUSD")
            continue

        current_px = bexec.get_symbol_price(asset)
        val_in_usd = current_px * real_qty
        if val_in_usd > 10.0:
            logging.info(f"[DAILY SELL] skip => {asset}, val_in_usd={val_in_usd:.2f} > 10")
            continue

        prob = prob_map.get(asset, None)
        logging.info(f"[DAILY SELL CHECK] {asset}, prob={prob}, val={val_in_usd:.2f}")
        if prob is None:
            logging.info(f"[DAILY SELL] skip => pas de prob pour {asset}")
            continue

        if prob < sell_threshold:
            # Vérif big_gain_exception
            meta = state["positions_meta"].get(asset, {})
            entry_px = meta.get("entry_px", 0.0)
            if entry_px>0:
                ratio = current_px / entry_px
                did_skip = meta.get("did_skip_sell_once", False)
                if ratio >= big_gain_pct and not did_skip:
                    meta["did_skip_sell_once"] = True
                    state["positions_meta"][asset] = meta
                    logging.info(f"[DAILY SELL SKIP big_gain] => {asset}, ratio={ratio:.2f}")
                    continue

            sold_val = bexec.sell_all(asset, real_qty)
            logging.info(f"[DAILY SELL LIVE] {asset}, prob={prob:.2f}, sold_val={sold_val:.2f}")
            if asset in state["positions_meta"]:
                del state["positions_meta"][asset]
            save_state(state)

    # 7) BUY => top 5 par prob + leftover dynamique
    buy_candidates = []
    buy_threshold = strat.get("buy_threshold", 0.5)
    for sym in tokens_daily:
        p = prob_map.get(sym, None)
        logging.info(f"[DAILY BUY CHECK] {sym}, prob={p}")
        if p is None or p < buy_threshold:
            continue

        # si on en possède déjà + de 1 USDT => skip
        cur_qty = holdings.get(sym, 0.0)
        if cur_qty > 0:
            px_tmp = bexec.get_symbol_price(sym)
            val_tmp = cur_qty * px_tmp
            if val_tmp > threshold_val_usdt:
                logging.info(f"[BUY] skip => {sym}, val_tmp={val_tmp:.2f} > {threshold_val_usdt}")
                continue

        buy_candidates.append((sym, p))

    # tri décroissant
    buy_candidates.sort(key=lambda x: x[1], reverse=True)
    top5 = buy_candidates[:5]
    logging.info(f"[DAILY BUY SELECT] => {top5}")

    # On achète
    if top5 and usdt_balance > 10:
        leftover = usdt_balance
        n = len(top5)
        # On laisse un coussin de 0.999 pour éviter l'erreur “Insufficient balance”
        leftover *= 0.999

        for i, (sym, prob) in enumerate(top5, start=1):
            tokens_left = n - i + 1
            if leftover < 10:
                logging.info("[DAILY BUY] leftover < 10 => skip remaining tokens.")
                break
            alloc = leftover / tokens_left

            qty_bought, avg_px, fill_sum = bexec.buy(sym, alloc)
            logging.info(f"[DAILY BUY EXEC] => {sym}, qty={qty_bought:.4f}, cost={fill_sum:.2f}, px={avg_px:.4f}")
            if qty_bought > 0:
                # maj state
                state["positions_meta"][sym] = {
                    "entry_px": avg_px,
                    "did_skip_sell_once": False,
                    "partial_sold": False,
                    "max_price": avg_px
                }
                leftover -= fill_sum
                save_state(state)

    logging.info("[DAILY UPDATE] Done daily_update_live")


def main():
    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml introuvable.")
        return

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Logger
    logging.basicConfig(
        filename=config["logging"]["file"],
        filemode='a',
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("[MAIN] Starting main loop (LIVE).")

    state = load_state()
    logging.info(f"[MAIN] Loaded state => keys={list(state.keys())}")

    # Init
    bexec = TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )
    logging.info("[MAIN] TradeExecutor initialized.")

    # Fuseau Paris
    tz_paris = pytz.timezone("Europe/Paris")

    while True:
        try:
            now_p = datetime.datetime.now(tz_paris)
            hour_p = now_p.hour
            min_p  = now_p.minute

            # 1) auto_select => 23h45
            if hour_p == 09 and min_p == 00 and not state.get("did_auto_select_today", False):
                run_auto_select_once_per_day(state)

            # 2) daily => 23h55
            if hour_p == 09 and min_p == 15 and not state.get("did_daily_update_today", False):
                logging.info("[MAIN] => daily_update_live.")
                daily_update_live(state, bexec)
                state["did_daily_update_today"] = True
                save_state(state)
                logging.info("[MAIN] daily_update_today => True.")

            # Reset si on n'est plus dans l'heure 23
            if hour_p != 09:
                if state.get("did_auto_select_today", False):
                    logging.info("[MAIN] reset did_auto_select_today.")
                state["did_auto_select_today"] = False

                if state.get("did_daily_update_today", False):
                    logging.info("[MAIN] reset daily_update_today.")
                state["did_daily_update_today"] = False
                save_state(state)

            # Intraday check
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
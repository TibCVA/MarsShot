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
        p = float(row["prob"])
        prob_map[sym] = p
    return prob_map

def run_auto_select_once_per_day(state):
    """
    Vérifie si on a déjà lancé auto_select_tokens.py aujourd'hui.
    Si non, on exécute le script, puis on met à jour did_auto_select_today.
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
    Logique daily_update avec temporisation entre SELL et BUY :
      1) Recharger config.yaml => tokens_daily
      2) Fusion tokens_daily + positions_meta => extended_tokens_daily => config_temp.yaml
      3) data_fetcher => daily_inference_data.csv
      4) ml_decision => daily_probabilities.csv
      5) SELL => selon les règles (prob < threshold, val > 5 USDT, etc.)
      6) Attendre 5 minutes pour laisser le solde USDT se mettre à jour.
      7) Re-fetch account info pour recalculer 'holdings' et 'usdt_balance'.
      8) BUY => top 3 par prob, leftover dynamique.
    """
    logging.info("[DAILY UPDATE] Start daily_update_live")

    # --- Vérif config.yaml
    if not os.path.exists("config.yaml"):
        logging.error("[DAILY UPDATE] config.yaml introuvable => skip daily_update.")
        return

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    tokens_daily = config.get("tokens_daily", [])
    strat = config.get("strategy", {})
    sell_threshold = strat.get("sell_threshold", 0.3)
    big_gain_pct   = strat.get("big_gain_exception_pct", 10.0)  # ratio x10
    buy_threshold  = strat.get("buy_threshold", 0.5)

    MIN_VALUE_TO_SELL = 5.0   # si > 5 USDT + prob < threshold => on vend
    MAX_VALUE_TO_SKIP_BUY = 10.0  # si on a déjà > 10 USDT => skip rachat

    # 1) Fusion tokens_daily + positions_meta => extended_tokens_daily
    system_positions = list(state["positions_meta"].keys())
    full_list = list(set(tokens_daily).union(set(system_positions)))
    logging.info(f"[DAILY UPDATE] union tokens => {full_list}")

    # On stocke dans config_temp.yaml
    config["extended_tokens_daily"] = full_list
    with open("config_temp.yaml", "w") as fw:
        yaml.safe_dump(config, fw, sort_keys=False)

    # 2) data_fetcher => daily_inference_data.csv
    try:
        subprocess.run(["python", "modules/data_fetcher.py", "--config", "config_temp.yaml"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] data_fetcher => {e}")
        return

    # Vérifie daily_inference_data.csv
    if (not os.path.exists("daily_inference_data.csv")
        or os.path.getsize("daily_inference_data.csv") < 100):
        logging.warning("[DAILY UPDATE] daily_inference_data.csv introuvable ou vide => skip ml_decision.")
        return

    # 3) ml_decision => daily_probabilities.csv
    try:
        subprocess.run(["python", "modules/ml_decision.py"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] ml_decision => {e}")
        return

    # 4) Charger prob_map
    prob_map = load_probabilities_csv("daily_probabilities.csv")
    logging.info(f"[DAILY UPDATE] tokens_daily={tokens_daily}, prob_map.size={len(prob_map)}")

    # 5) Récup solde => holdings + usdt_balance
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
        qty   = float(b["free"]) + float(b["locked"])
        if asset.upper() == "USDT":
            usdt_balance = qty
        elif qty > 0:
            holdings[asset] = qty

    logging.info(f"[DAILY UPDATE] holdings={holdings}, usdt={usdt_balance:.2f}")

    # 6) SELL => tokens dont la valeur est > 5 USDT + prob < sell_threshold
    #    sauf USDT/BTC/FDUSD
    for asset, real_qty in list(holdings.items()):
        if asset.upper() in ["USDT","BTC","FDUSD"]:
            logging.info(f"[DAILY SELL] skip stable/BTC => {asset}")
            continue

        current_px = bexec.get_symbol_price(asset)
        val_in_usd = current_px * real_qty
        prob = prob_map.get(asset, None)
        logging.info(f"[DAILY SELL CHECK] {asset}, val_in_usd={val_in_usd:.2f}, prob={prob}")

        if prob is None:
            logging.info(f"[DAILY SELL] skip => prob=None => {asset}")
            continue

        # Condition : val_in_usd > 5 ET prob < sell_threshold
        if val_in_usd > MIN_VALUE_TO_SELL and prob < sell_threshold:
            # big_gain_exception
            meta = state["positions_meta"].get(asset, {})
            entry_px = meta.get("entry_px", 0.0)
            if entry_px > 0:
                ratio = current_px / entry_px
                did_skip = meta.get("did_skip_sell_once", False)
                if ratio >= big_gain_pct and not did_skip:
                    meta["did_skip_sell_once"] = True
                    state["positions_meta"][asset] = meta
                    logging.info(f"[DAILY SELL SKIP big_gain] => {asset}, ratio={ratio:.2f}")
                    continue

            sold_val = bexec.sell_all(asset, real_qty)
            logging.info(f"[DAILY SELL LIVE] {asset}, sold_val={sold_val:.2f}, prob={prob:.2f}")
            if asset in state["positions_meta"]:
                del state["positions_meta"][asset]
            save_state(state)
        else:
            logging.info(f"[DAILY SELL] skip => {asset}, condition non remplie.")

    # == Temporisation de 5 minutes avant la phase d'achat ==
    logging.info("[DAILY UPDATE] Wait 300s (5min) to let sells finalize & USDT free up.")
    time.sleep(300)

    # == On re-fetch le solde compte pour mettre à jour usdt_balance et holdings ==
    try:
        account_info = bexec.client.get_account()
    except Exception as e:
        logging.error(f"[DAILY UPDATE] get_account after sleep => {e}")
        return

    balances2 = account_info.get("balances", [])
    new_holdings = {}
    new_usdt_balance = 0.0
    for b in balances2:
        asset = b["asset"]
        qty   = float(b["free"]) + float(b["locked"])
        if asset.upper() == "USDT":
            new_usdt_balance = qty
        elif qty > 0:
            new_holdings[asset] = qty

    logging.info(f"[DAILY UPDATE] After wait => holdings={new_holdings}, usdt={new_usdt_balance:.2f}")

    # 7) BUY => top 3 par prob
    buy_candidates = []
    for sym in tokens_daily:
        p = prob_map.get(sym, None)
        logging.info(f"[DAILY BUY CHECK] {sym}, prob={p}")
        if p is None or p < buy_threshold:
            continue

        # skip si on en a déjà > 10 USDT
        cur_qty = new_holdings.get(sym, 0.0)
        if cur_qty > 0:
            px_tmp = bexec.get_symbol_price(sym)
            val_tmp = px_tmp * cur_qty
            if val_tmp > MAX_VALUE_TO_SKIP_BUY:
                logging.info(f"[DAILY BUY] skip => {sym}, already {val_tmp:.2f} USDT > {MAX_VALUE_TO_SKIP_BUY}")
                continue

        buy_candidates.append((sym, p))

    buy_candidates.sort(key=lambda x: x[1], reverse=True)
    top3 = buy_candidates[:3]
    logging.info(f"[DAILY BUY SELECT] => {top3}")

    if top3 and new_usdt_balance > 10:
        leftover = new_usdt_balance
        leftover *= 0.999  # léger coussin
        n = len(top3)
        for i, (sym, p) in enumerate(top3, start=1):
            tokens_left = n - i + 1
            if leftover < 10:
                logging.info("[DAILY BUY] leftover < 10 => stop buys.")
                break
            alloc = leftover / tokens_left

            qty_b, px_b, sum_b = bexec.buy(sym, alloc)
            logging.info(f"[DAILY BUY EXEC] => {sym}, qty={qty_b:.4f}, cost={sum_b:.2f}, px={px_b:.4f}")
            if qty_b > 0:
                state["positions_meta"][sym] = {
                    "entry_px": px_b,
                    "did_skip_sell_once": False,
                    "partial_sold": False,
                    "max_price": px_b
                }
                leftover -= sum_b
                save_state(state)

    logging.info("[DAILY UPDATE] Done daily_update_live")


def main():
    # Vérif config.yaml
    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml introuvable.")
        return

    with open("config.yaml","r") as f:
        config = yaml.safe_load(f)

    # Logger
    logging.basicConfig(
        filename=config["logging"]["file"],
        filemode='a',
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("[MAIN] Starting main loop (LIVE).")

    # State
    state = load_state()
    logging.info(f"[MAIN] Loaded state => keys={list(state.keys())}")

    # Init executor
    bexec = TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )
    logging.info("[MAIN] TradeExecutor initialized.")

    tz_paris = pytz.timezone("Europe/Paris")

    while True:
        try:
            now_p = datetime.datetime.now(tz_paris)
            hour_p = now_p.hour
            min_p  = now_p.minute

            # auto_select => 19h45
            if hour_p == 19 and min_p == 45 and not state.get("did_auto_select_today", False):
                run_auto_select_once_per_day(state)

            # daily => 19h55
            if hour_p == 19 and min_p == 55 and not state.get("did_daily_update_today", False):
                logging.info("[MAIN] => daily_update_live.")
                daily_update_live(state, bexec)
                state["did_daily_update_today"] = True
                save_state(state)
                logging.info("[MAIN] daily_update_today => True.")

            # Reset si on n'est plus dans l'heure 19
            if hour_p != 19:
                if state.get("did_auto_select_today", False):
                    logging.info("[MAIN] reset did_auto_select_today.")
                state["did_auto_select_today"] = False

                if state.get("did_daily_update_today", False):
                    logging.info("[MAIN] reset daily_update_today.")
                state["did_daily_update_today"] = False

                save_state(state)

            # Intraday check => toutes les X secondes
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
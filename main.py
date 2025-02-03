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
    (Cette fonction reste inchangée et s'exécute une fois par jour à 19h45.)
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
    Même logique daily_update_live que votre version actuelle.
    (Aucune modification dans la logique interne.)
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
    big_gain_pct   = strat.get("big_gain_exception_pct", 10.0)
    buy_threshold  = strat.get("buy_threshold", 0.5)

    MIN_VALUE_TO_SELL = 5.0   
    MAX_VALUE_TO_SKIP_BUY = 10.0  

    # 1) Fusion tokens_daily + positions_meta => extended_tokens_daily
    system_positions = list(state.get("positions_meta", {}).keys())
    full_list = list(set(tokens_daily).union(set(system_positions)))
    logging.info(f"[DAILY UPDATE] union tokens => {full_list}")
    config["extended_tokens_daily"] = full_list
    with open("config_temp.yaml", "w") as fw:
        yaml.safe_dump(config, fw, sort_keys=False)

    # 2) data_fetcher => daily_inference_data.csv
    try:
        subprocess.run(["python", "modules/data_fetcher.py", "--config", "config_temp.yaml"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] data_fetcher => {e}")
        return

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

    # 6) SELL phase
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
        if val_in_usd > MIN_VALUE_TO_SELL and prob < sell_threshold:
            meta = state.get("positions_meta", {}).get(asset, {})
            entry_px = meta.get("entry_px", 0.0)
            if entry_px > 0:
                ratio = current_px / entry_px
                did_skip = meta.get("did_skip_sell_once", False)
                if ratio >= big_gain_pct and not did_skip:
                    meta["did_skip_sell_once"] = True
                    state.setdefault("positions_meta", {})[asset] = meta
                    logging.info(f"[DAILY SELL SKIP big_gain] => {asset}, ratio={ratio:.2f}")
                    continue
            sold_val = bexec.sell_all(asset, real_qty)
            logging.info(f"[DAILY SELL LIVE] {asset}, sold_val={sold_val:.2f}, prob={prob:.2f}")
            if asset in state.get("positions_meta", {}):
                del state["positions_meta"][asset]
            save_state(state)
        else:
            logging.info(f"[DAILY SELL] skip => {asset}, condition non remplie.")

    logging.info("[DAILY UPDATE] Wait 300s (5min) to let sells finalize & USDT free up.")
    time.sleep(300)

    # 7) Récupération du solde après temporisation
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

    # 8) BUY phase => top 3 par prob
    buy_candidates = []
    for sym in tokens_daily:
        p = prob_map.get(sym, None)
        logging.info(f"[DAILY BUY CHECK] {sym}, prob={p}")
        if p is None or p < buy_threshold:
            continue
        cur_qty = new_holdings.get(sym, 0.0)
        if cur_qty > 0:
            px_tmp = bexec.get_symbol_price(sym)
            val_tmp = px_tmp * cur_qty
            if val_tmp >  MAX_VALUE_TO_SKIP_BUY:
                logging.info(f"[DAILY BUY] skip => {sym}, already {val_tmp:.2f} USDT > {MAX_VALUE_TO_SKIP_BUY}")
                continue
        buy_candidates.append((sym, p))
    buy_candidates.sort(key=lambda x: x[1], reverse=True)
    top3 = buy_candidates[:3]
    logging.info(f"[DAILY BUY SELECT] => {top3}")
    if top3 and new_usdt_balance > 10:
        leftover = new_usdt_balance * 0.999  # léger coussin
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
                state.setdefault("positions_meta", {})[sym] = {
                    "entry_px": px_b,
                    "did_skip_sell_once": False,
                    "partial_sold": False,
                    "max_price": px_b
                }
                leftover -= sum_b
                save_state(state)
    logging.info("[DAILY UPDATE] Done daily_update_live")

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

    state = load_state()
    logging.info(f"[MAIN] Loaded state => keys={list(state.keys())}")

    bexec = TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )
    logging.info("[MAIN] TradeExecutor initialized.")
    tz_paris = pytz.timezone("Europe/Paris")

    # Nous utilisons désormais une variable de type timestamp pour gérer les daily update
    # 12h = 43 200 secondes
    UPDATE_INTERVAL_SEC = 12 * 3600  # 43 200 secondes

    # Pour l'auto_select qui se déclenche toujours à 19h45 (inchangé)
    AUTO_SELECT_HOUR = 19
    AUTO_SELECT_MIN  = 45

    # Pour le premier daily update fixe (à 19h55) :
    FIRST_UPDATE_HOUR = 19
    FIRST_UPDATE_MIN  = 55

    while True:
        try:
            now = datetime.datetime.now(tz_paris)
            current_ts = time.time()

            # --- Auto_select (une fois par jour à 19h45)
            if now.hour == AUTO_SELECT_HOUR and now.minute == AUTO_SELECT_MIN and not state.get("did_auto_select_today", False):
                run_auto_select_once_per_day(state)

            # --- Daily update live :
            # Si aucun update n'a encore été lancé, on attend le créneau de 19h55
            if "last_daily_update_ts" not in state or state["last_daily_update_ts"] == 0:
                if now.hour == FIRST_UPDATE_HOUR and now.minute == FIRST_UPDATE_MIN:
                    logging.info("[MAIN] => daily_update_live (first update).")
                    daily_update_live(state, bexec)
                    state["last_daily_update_ts"] = current_ts
                    save_state(state)
            else:
                # Si 12 heures se sont écoulées depuis le dernier update, on déclenche le daily update
                if current_ts - state["last_daily_update_ts"] >= UPDATE_INTERVAL_SEC:
                    logging.info("[MAIN] => daily_update_live (12h after previous update).")
                    daily_update_live(state, bexec)
                    state["last_daily_update_ts"] = current_ts
                    save_state(state)

            # --- Réinitialisation des flags auto_select une fois par jour
            # On réinitialise did_auto_select_today à minuit
            if now.hour == 0 and now.minute < 5:
                if state.get("did_auto_select_today", False):
                    logging.info("[MAIN] Reset auto_select flag for new day.")
                    state["did_auto_select_today"] = False
                    save_state(state)

            # --- Intraday risk check toutes les X secondes
            last_check = state.get("last_risk_check_ts", 0)
            if time.time() - last_check >= config["strategy"]["check_interval_seconds"]:
                logging.info("[MAIN] intraday_check_real()")
                intraday_check_real(state, bexec, config)
                state["last_risk_check_ts"] = time.time()
                save_state(state)

        except Exception as e:
            logging.error(f"[MAIN ERROR] {e}")

        time.sleep(10)

if __name__ == "__main__":
    main()
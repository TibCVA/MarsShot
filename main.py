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
    """
    Lit un CSV de probabilités (symbol, prob).
    Retourne un dict { 'SYM': prob, ... }.
    """
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
    Lance auto_select_tokens.py si pas déjà fait ce jour.
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
    1) Recharge config.yaml (pour lire la liste tokens_daily mise à jour).
    2) Construit l’union : tokens_daily ∪ positions_meta (tokens du bot).
    3) Appelle data_fetcher.py (avec config_temp.yaml) + ml_decision
    4) SELL pour tout token de positions_meta si prob < sell_threshold
    5) BUY pour tokens_daily si prob >= buy_threshold
    """
    logging.info("[DAILY UPDATE] Start daily_update_live")

    # 0) Recharger config.yaml
    if not os.path.exists("config.yaml"):
        logging.error("[DAILY UPDATE] config.yaml introuvable => skip daily update.")
        return
    with open("config.yaml","r") as f:
        config = yaml.safe_load(f)

    tokens_daily = config.get("tokens_daily", [])
    strat        = config.get("strategy", {})

    # 1) Union => tokens_daily + positions_meta
    system_positions = list(state["positions_meta"].keys())  # tokens achetés par le bot
    full_list = list(set(tokens_daily).union(set(system_positions)))
    logging.info(f"[DAILY UPDATE] union tokens => {full_list}")

    # On crée un config_temp.yaml pour que data_fetcher.py lise full_list
    config["extended_tokens_daily"] = full_list
    with open("config_temp.yaml","w") as fw:
        yaml.safe_dump(config, fw, sort_keys=False)

    # 2) data_fetcher => attend la fin
    try:
        ret = subprocess.run(["python", "modules/data_fetcher.py", 
                              "--config", "config_temp.yaml"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] data_fetcher => {e}")
        return

    # Vérifier daily_inference_data.csv
    csv_data = "daily_inference_data.csv"
    if (not os.path.exists(csv_data)) or (os.path.getsize(csv_data)<100):
        logging.warning("[DAILY UPDATE] daily_inference_data.csv introuvable ou vide => skip ml_decision")
        return

    # 3) ml_decision => attend la fin
    try:
        ret2 = subprocess.run(["python", "modules/ml_decision.py"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] ml_decision => {e}")
        return

    # Charger probas
    prob_map = load_probabilities_csv("daily_probabilities.csv")
    logging.info(f"[DAILY UPDATE] tokens_daily={tokens_daily}, prob_map.size={len(prob_map)}")

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

    # SELL => tokens achetés par le bot
    for asset in list(state["positions_meta"].keys()):
        real_qty = holdings.get(asset, 0.0)
        if real_qty<=0:
            # plus en portefeuille => remove meta
            del state["positions_meta"][asset]
            save_state(state)
            continue
        prob = prob_map.get(asset, None)
        logging.info(f"[DAILY SELL CHECK] {asset}, prob={prob}")
        if prob is None:
            logging.info(f"[DAILY SELL] {asset} => prob=None => skip => reste au prochain daily.")
            continue

        if prob < strat["sell_threshold"]:
            meta = state["positions_meta"].get(asset, {})
            did_skip = meta.get("did_skip_sell_once", False)
            entry_px = meta.get("entry_px", None)
            current_px = bexec.get_symbol_price(asset)

            if entry_px and entry_px>0:
                ratio = current_px / entry_px
                if ratio >= strat["big_gain_exception_pct"] and not did_skip:
                    meta["did_skip_sell_once"]= True
                    state["positions_meta"][asset]= meta
                    logging.info(f"[DAILY SELL SKIP big gain] => {asset}, ratio={ratio:.2f}, prob={prob:.2f}")
                    save_state(state)
                    continue

            sold_val = bexec.sell_all(asset, real_qty)
            logging.info(f"[DAILY SELL LIVE] => {asset}, sold_val={sold_val:.2f}")
            if asset in state["positions_meta"]:
                del state["positions_meta"][asset]
            save_state(state)

    # BUY => tokens_daily seulement
    buy_candidates= []
    for sym in tokens_daily:
        if sym in state["positions_meta"]:
            # on l'a déjà
            continue
        p = prob_map.get(sym,None)
        logging.info(f"[DAILY BUY CHECK] {sym}, prob={p}")
        if p is not None and p>= strat["buy_threshold"]:
            buy_candidates.append((sym,p))

    buy_candidates.sort(key=lambda x: x[1], reverse=True)
    top5 = buy_candidates[:5]
    logging.info(f"[DAILY BUY SELECT] => {top5}")

    if top5 and usdt_balance>10:
        alloc = usdt_balance / len(top5)
        for sym, pb in top5:
            qty_bought, avg_px = bexec.buy(sym, alloc)
            logging.info(f"[DAILY BUY EXEC] => {sym}, qty={qty_bought}, px={avg_px:.4f}")
            if qty_bought>0:
                state["positions_meta"][sym] = {
                    "entry_px": avg_px,
                    "did_skip_sell_once": False,
                    "partial_sold": False,
                    "max_price": avg_px
                }
                usdt_balance-= alloc
                save_state(state)

    logging.info("[DAILY UPDATE] Done daily_update_live")

def main():
    # Charger config.yaml
    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml introuvable => exit.")
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
    logging.info("[MAIN] Starting main loop (Option2).")

    # Charger le state
    state = load_state()
    logging.info(f"[MAIN] loaded state => {list(state.keys())}")

    # TradeExecutor
    bexec= TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )
    logging.info("[MAIN] bexec init ok.")

    # Fuseau Paris
    tz_paris = pytz.timezone("Europe/Paris")

    while True:
        try:
            now_p = datetime.datetime.now(tz_paris)
            h     = now_p.hour
            m     = now_p.minute

            # 1) auto_select => 17h45
            if h==17 and m==45 and not state.get("did_auto_select_today", False):
                run_auto_select_once_per_day(state)

            # 2) daily_update => 18h00
            if h==18 and m==0 and not state.get("did_daily_update_today", False):
                logging.info("[MAIN] => daily_update_live.")
                daily_update_live(state, bexec)
                state["did_daily_update_today"]= True
                save_state(state)
                logging.info("[MAIN] daily_update_today => True.")

            # Reset flags si on n'est plus dans l'heure 17 ou 18
            if h!=17:
                if state.get("did_auto_select_today",False):
                    logging.info("[MAIN] reset did_auto_select_today.")
                state["did_auto_select_today"]=False

            if h!=18:
                if state.get("did_daily_update_today",False):
                    logging.info("[MAIN] reset daily_update_today.")
                state["did_daily_update_today"]=False

            save_state(state)

            # Intraday check
            last_check= state.get("last_risk_check_ts", 0)
            elapsed= time.time()- last_check
            interval= config["strategy"]["check_interval_seconds"]
            if elapsed>= interval:
                logging.info("[MAIN] intraday_check_real()")
                intraday_check_real(state, bexec, config)
                state["last_risk_check_ts"]= time.time()
                save_state(state)

        except Exception as e:
            logging.error(f"[MAIN ERROR] {e}")

        time.sleep(10)

if __name__=="__main__":
    main()
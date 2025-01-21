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

def load_prob_csv(csv_path="daily_probabilities.csv"):
    """
    Lit le fichier daily_probabilities.csv et renvoie un dict { 'SYM': prob, ... }.
    """
    import pandas as pd
    if not os.path.exists(csv_path):
        logging.warning(f"[load_prob_csv] {csv_path} introuvable => return {{}}")
        return {}
    df = pd.read_csv(csv_path)
    if df.empty:
        logging.warning(f"[load_prob_csv] {csv_path} vide => return {{}}")
        return {}
    d = {}
    for i, row in df.iterrows():
        sym = str(row["symbol"]).strip()
        p   = float(row["prob"])
        d[sym] = p
    return d

def run_auto_select_once_per_day(state):
    """
    Exécute auto_select_tokens.py si pas déjà fait aujourd'hui.
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
    1) Recharge config.yaml pour voir la dernière liste tokens_daily
    2) Construit l'union (tokens_daily + positions_meta.keys()) pour fetch ML
    3) Exécute data_fetcher, ml_decision
    4) SELL (uniquement tokens du bot => positions_meta) si prob<sell_threshold
    5) BUY (uniquement tokens_daily) si prob>buy_threshold
    """
    logging.info("[DAILY UPDATE] Start daily_update_live")

    # 0) Recharger config.yaml
    if not os.path.exists("config.yaml"):
        logging.error("[DAILY UPDATE] config.yaml introuvable => skip daily update.")
        return
    with open("config.yaml","r") as f:
        config = yaml.safe_load(f)

    tokens_daily = config["tokens_daily"]
    strat        = config["strategy"]

    # 1) Union => tokens_daily + positions_meta
    system_positions = list(state["positions_meta"].keys())  # tokens que le bot détient
    full_list = list(set(tokens_daily).union(set(system_positions)))
    logging.info(f"[DAILY UPDATE] union tokens => {full_list}")

    # 2) Ecrire un config_temp.yaml => data_fetcher lira extended_tokens_daily
    config["extended_tokens_daily"] = full_list
    with open("config_temp.yaml","w") as fw:
        yaml.safe_dump(config, fw, sort_keys=False)

    # Appeler data_fetcher => attend la fin
    try:
        ret = subprocess.run(["python", "modules/data_fetcher.py", "--config", "config_temp.yaml"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] data_fetcher => {e}")
        return

    # Vérifier daily_inference_data.csv
    csv_data = "daily_inference_data.csv"
    if not os.path.exists(csv_data) or (os.path.getsize(csv_data)<100):
        logging.warning("[DAILY UPDATE] daily_inference_data.csv introuvable ou vide => skip ml_decision")
        return

    # Appeler ml_decision => attend la fin
    try:
        ret2 = subprocess.run(["python", "modules/ml_decision.py"], check=False)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] ml_decision => {e}")
        return

    # Charger probas
    prob_map = load_prob_csv("daily_probabilities.csv")
    logging.info(f"[DAILY UPDATE] tokens_daily={tokens_daily}, got {len(prob_map)} prob(s)")

    # 3) Récupérer les holdings
    try:
        account_info = bexec.client.get_account()
    except Exception as e:
        logging.error(f"[DAILY UPDATE] get_account => {e}")
        return

    bals = account_info.get("balances", [])
    holdings = {}
    usdt_balance= 0.0
    for b in bals:
        asset= b["asset"]
        qty= float(b["free"])+ float(b["locked"])
        if asset.upper()=="USDT":
            usdt_balance= qty
        elif qty>0:
            holdings[asset]= qty

    logging.info(f"[DAILY UPDATE] holdings={holdings}, usdt={usdt_balance:.2f}")

    # 4) SELL => tokens achetés par le bot (positions_meta)
    for asset in list(state["positions_meta"].keys()):
        real_qty= holdings.get(asset, 0.0)
        if real_qty<=0:
            # plus aucune qty => remove meta
            del state["positions_meta"][asset]
            save_state(state)
            continue

        prob= prob_map.get(asset,None)
        logging.info(f"[DAILY SELL CHECK] {asset}, prob={prob}")
        if prob is None:
            logging.info(f"[DAILY SELL] {asset} => prob=None => skip => on continue a le tracker plus tard.")
            continue

        if prob< strat["sell_threshold"]:
            meta= state["positions_meta"].get(asset,{})
            did_skip= meta.get("did_skip_sell_once",False)
            entry_px= meta.get("entry_px",None)
            current_px= bexec.get_symbol_price(asset)
            if entry_px and entry_px>0:
                ratio= current_px/ entry_px
                if ratio>= strat["big_gain_exception_pct"] and not did_skip:
                    meta["did_skip_sell_once"]= True
                    state["positions_meta"][asset]= meta
                    logging.info(f"[DAILY SELL SKIP big gain] {asset}, ratio={ratio:.2f}, prob={prob:.2f}")
                    save_state(state)
                    continue
            # SELL
            sold_val= bexec.sell_all(asset, real_qty)
            logging.info(f"[DAILY SELL LIVE] => {asset}, sold_val={sold_val}")
            del state["positions_meta"][asset]
            save_state(state)

    # 5) BUY => dans tokens_daily uniquement
    buy_candidates=[]
    for sym in tokens_daily:
        if sym in state["positions_meta"]:
            continue
        p = prob_map.get(sym, None)
        logging.info(f"[DAILY BUY CHECK] {sym}, prob={p}")
        if p is not None and p>= strat["buy_threshold"]:
            buy_candidates.append((sym,p))

    buy_candidates.sort(key=lambda x: x[1], reverse=True)
    top5 = buy_candidates[:5]
    logging.info(f"[DAILY BUY SELECT] => {top5}")

    if top5 and usdt_balance>10:
        alloc= usdt_balance/len(top5)
        for sym, pr in top5:
            qty_bought, avg_px= bexec.buy(sym, alloc)
            logging.info(f"[DAILY BUY EXEC] => {sym}, qty={qty_bought}, px={avg_px:.4f}")
            if qty_bought>0:
                state["positions_meta"][sym]= {
                    "entry_px": avg_px,
                    "did_skip_sell_once": False,
                    "partial_sold": False,
                    "max_price": avg_px
                }
                usdt_balance-= alloc
                save_state(state)

    logging.info("[DAILY UPDATE] Done daily_update_live")

def main():
    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml introuvable => exit.")
        return

    with open("config.yaml","r") as f:
        config = yaml.safe_load(f)

    logging.basicConfig(
        filename=config["logging"]["file"],
        filemode='a',
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("[MAIN] Starting main loop (Option2).")

    state= load_state()
    logging.info(f"[MAIN] loaded state => {list(state.keys())}")

    bexec= TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )
    logging.info("[MAIN] bexec init ok.")

    tz_paris= pytz.timezone("Europe/Paris")

    while True:
        try:
            now_p = datetime.datetime.now(tz_paris)
            h= now_p.hour
            m= now_p.minute

            # 1) auto_select => 09h15
            if h==9 and m==15 and not state.get("did_auto_select_today",False):
                run_auto_select_once_per_day(state)

            # 2) daily => 09h30
            if h==9 and m==30 and not state.get("did_daily_update_today",False):
                logging.info("[MAIN] => daily_update_live.")
                daily_update_live(state, bexec)
                state["did_daily_update_today"]=True
                save_state(state)
                logging.info("[MAIN] daily_update_today => True.")

            # reset flags
            if h!=9:
                if state.get("did_auto_select_today",False):
                    logging.info("[MAIN] reset did_auto_select_today.")
                state["did_auto_select_today"]=False

                if state.get("did_daily_update_today",False):
                    logging.info("[MAIN] reset daily_update_today.")
                state["did_daily_update_today"]=False
                save_state(state)

            # intraday check
            last_check= state.get("last_risk_check_ts",0)
            if time.time()- last_check>= config["strategy"]["check_interval_seconds"]:
                logging.info("[MAIN] intraday_check_real()")
                intraday_check_real(state, bexec, config)
                state["last_risk_check_ts"]= time.time()
                save_state(state)

        except Exception as e:
            logging.error(f"[MAIN ERR] {e}")

        time.sleep(10)

if __name__=="__main__":
    main()

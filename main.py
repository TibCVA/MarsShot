#!/usr/bin/env python3
# coding: utf-8

import time
import logging
import datetime
import yaml
import os
import threading

# Gestion du fuseau horaire Europe/Paris
import pytz

from modules.trade_executor import TradeExecutor
#from modules.utils import send_telegram_message
from modules.positions_store import load_state, save_state
from modules.risk_manager import intraday_check_real

#try:
    #from modules.telegram_integration import run_telegram_bot
#except ImportError:
    #def run_telegram_bot():
        #pass


def load_probabilities_csv(csv_path="daily_probabilities.csv"):
    """
    Lit un CSV au format:
        symbol,prob
        HIVE,0.8321
        ACT,0.4249
        ...
    Retourne un dict { 'HIVE':0.8321, 'ACT':0.4249, ... }.
    S'il est introuvable ou vide, renvoie {}.
    """
    import pandas as pd
    if not os.path.exists(csv_path):
        logging.warning(f"[load_probabilities_csv] {csv_path} introuvable => return {}")
        return {}

    df = pd.read_csv(csv_path)
    if df.empty:
        logging.warning(f"[load_probabilities_csv] {csv_path} est vide => return {}")
        return {}

    prob_map = {}
    for i, row in df.iterrows():
        sym = str(row["symbol"]).strip()
        p   = float(row["prob"])
        prob_map[sym] = p
    return prob_map


def main():
    """
    Boucle principale du bot de trading en mode LIVE.
    - Chaque jour à 22h00 heure de Paris => daily_update_live(...) => SELL/BUY
    - Intraday => intraday_check_real(...) => trailing/stop-loss live
    - Stockage local (positions_meta) dans bot_state.json
    """

    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml introuvable.")
        return

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    logging.basicConfig(
        filename=config["logging"]["file"],  # ex: "bot.log"
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("[MAIN] Starting main loop (LIVE).")

    # Lancement du bot Telegram dans un thread séparé (désactivable)
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()

    # Chargement de l'état local
    state = load_state()
    logging.info(f"[MAIN] Loaded state => keys={list(state.keys())}")

    # Initialisation TradeExecutor
    bexec = TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )
    logging.info("[MAIN] TradeExecutor initialized.")

    # Fuseau de Paris
    paris_tz = pytz.timezone("Europe/Paris")

    while True:
        try:
            now_paris = datetime.datetime.now(paris_tz)
            hour_p = now_paris.hour
            min_p  = now_paris.minute

            # => Tâche daily à 22h00 PARIS
            if (
                hour_p == 22
                and min_p == 0
                and not state.get("did_daily_update_today", False)
            ):
                logging.info("[MAIN] It's 22h00 in Paris => launching daily_update_live.")
                daily_update_live(state, config, bexec)
                state["did_daily_update_today"] = True
                save_state(state)
                logging.info("[MAIN] daily_update_today flag => True.")

            # Reset du flag si on n'est plus à 22h
            if hour_p != 22:
                if state.get("did_daily_update_today", False):
                    logging.info("[MAIN] hour!=22 => reset did_daily_update_today=False.")
                state["did_daily_update_today"] = False
                save_state(state)

            # Intraday check
            last_check = state.get("last_risk_check_ts", 0)
            elapsed = time.time() - last_check
            if elapsed >= config["strategy"]["check_interval_seconds"]:
                logging.info("[MAIN] Intraday check => risk_manager.intraday_check_real()")
                intraday_check_real(state, bexec, config)
                state["last_risk_check_ts"] = time.time()
                save_state(state)

        except Exception as e:
            logging.error(f"[MAIN ERROR] {e}")

        time.sleep(10)


def daily_update_live(state, config, bexec):
    """
    Achète/Vend en direct => 
     1) SELL si prob < sell_threshold (sauf skip big_gain_exception_pct).
     2) BUY top 5 tokens => en utilisant USDT du compte.

    Les probabilités proviennent désormais du fichier daily_probabilities.csv
    (généré par ml_decision.py), et non plus d'un appel "live" get_probability_for_symbol(...).
    """
    logging.info("[DAILY UPDATE] Starting daily_update (live).")

    tokens = config["tokens_daily"]
    strat  = config["strategy"]
    logging.info(f"[DAILY UPDATE] tokens_daily={tokens}")

    # On charge le CSV des probabilités
    prob_map = load_probabilities_csv("daily_probabilities.csv")

    # On récupère le solde complet => On vend si prob < threshold
    try:
        account_info = bexec.client.get_account()
    except Exception as e:
        logging.error(f"[DAILY UPDATE] get_account error => {e}")
        return

    balances = account_info["balances"]
    holdings = {}
    usdt_balance = 0.0

    # Récup balance
    for b in balances:
        asset = b["asset"]
        free  = float(b["free"])
        locked= float(b["locked"])
        qty   = free + locked
        if asset == "USDT":
            usdt_balance = qty
        elif qty > 0:
            holdings[asset] = qty
    logging.info(f"[DAILY UPDATE] holdings={holdings}, usdt_balance={usdt_balance:.2f}")

    # --------------------
    # SELL logic
    # --------------------
    for asset, real_qty in holdings.items():
        prob = prob_map.get(asset, None)  # On lit la prob depuis daily_probabilities.csv
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

    # --------------------
    # BUY logic => top 5
    # --------------------
    buy_candidates = []
    for sym in tokens:
        if sym in holdings:
            continue
        pr = prob_map.get(sym, None)
        logging.info(f"[DAILY BUY CHECK] {sym}, prob={pr}")
        if pr is not None and pr >= strat["buy_threshold"]:
            buy_candidates.append((sym, pr))

    buy_candidates.sort(key=lambda x: x[1], reverse=True)
    buy_candidates = buy_candidates[:5]
    logging.info(f"[DAILY BUY SELECT] => {buy_candidates}")

    if buy_candidates and usdt_balance > 10:
        alloc = usdt_balance / len(buy_candidates)
        for sym, pb in buy_candidates:
            qty_bought, avg_px = bexec.buy(sym, alloc)
            logging.info(f"[DAILY BUY EXEC] => {sym}, qty={qty_bought}, px={avg_px}")
            if qty_bought > 0:
                state["positions_meta"][sym] = {
                    "entry_px": avg_px,
                    "did_skip_sell_once": False,
                    "partial_sold": False,
                    "max_price": avg_px
                }
                usdt_balance -= alloc
                save_state(state)

    logging.info("[DAILY UPDATE] Done daily_update (live).")


if __name__ == "__main__":
    main()

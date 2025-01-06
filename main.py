#!/usr/bin/env python3
# coding: utf-8

import time
import logging
import datetime
import yaml
import os
import threading

from zoneinfo import ZoneInfo  # <-- Import pour fuseau horaire "Europe/Paris"

from modules.trade_executor import TradeExecutor
from modules.utils import send_telegram_message
from modules.ml_decision import get_probability_for_symbol
from modules.positions_store import load_state, save_state
from modules.risk_manager import intraday_check_real  # Intraday => live

try:
    from modules.telegram_integration import run_telegram_bot
except ImportError:
    def run_telegram_bot():
        pass

def main():
    """
    Boucle principale du bot de trading en mode LIVE.
    - A 1h00 du matin heure Paris => daily_update_live => SELL/BUY sur Binance
    - Intraday => intraday_check_real => trailing / stop-loss live
    - On stocke des métadonnées dans bot_state.json => partial_sold, max_price, ...
    """

    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml introuvable.")
        return

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    logging.basicConfig(
        filename=config["logging"]["file"],
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("[MAIN] Starting main loop (LIVE, 1h Paris).")

    # Lancement bot Telegram
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()

    # Charger le state
    state = load_state()

    # Init trade executor
    bexec = TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )

    while True:
        try:
            # On prend l'heure locale Paris
            now_paris = datetime.datetime.now(ZoneInfo("Europe/Paris"))

            # => 01:00 Paris
            if (
                now_paris.hour == 1
                and now_paris.minute == 0
                and not state.get("did_daily_update_today", False)
            ):
                daily_update_live(state, config, bexec)
                state["did_daily_update_today"] = True
                save_state(state)

            # Reset le flag si on repasse avant 01:00
            if now_paris.hour < 1:
                state["did_daily_update_today"] = False
                save_state(state)

            # Intraday check
            last_check = state.get("last_risk_check_ts", 0)
            if (time.time() - last_check) >= config["strategy"]["check_interval_seconds"]:
                intraday_check_real(state, bexec, config)
                state["last_risk_check_ts"] = time.time()
                save_state(state)

        except Exception as e:
            logging.error(f"[MAIN ERROR] {e}")

        time.sleep(10)

def daily_update_live(state, config, bexec):
    """
    Achète/Vend en direct => 
     1) SELL si prob<sell_threshold (sauf skip big_gain_exception_pct).
     2) BUY top 5 tokens => en utilisant USDT du compte.
    """
    logging.info("[DAILY UPDATE] Starting daily_update (live, 1h Paris).")

    tokens = config["tokens_daily"]
    strat  = config["strategy"]

    # On récup le solde complet (live)
    account_info = bexec.client.get_account()
    balances = account_info["balances"]
    holdings = {}
    usdt_balance=0.0

    for b in balances:
        asset= b["asset"]
        free= float(b["free"])
        locked= float(b["locked"])
        qty= free+ locked
        if asset=="USDT":
            usdt_balance= qty
        elif qty>0:
            holdings[asset]= qty

    # SELL logic
    for asset, real_qty in holdings.items():
        prob = get_probability_for_symbol(asset)
        if prob is None:
            logging.info(f"[DAILY SELL] {asset} => prob=None => skip.")
            continue
        if prob< strat["sell_threshold"]:
            meta= state["positions_meta"].get(asset, {})
            did_skip= meta.get("did_skip_sell_once",False)
            entry_px= meta.get("entry_px",None)

            current_px= bexec.get_symbol_price(asset)
            if entry_px:
                ratio= current_px / entry_px
                if ratio>= strat["big_gain_exception_pct"] and not did_skip:
                    meta["did_skip_sell_once"]= True
                    state["positions_meta"][asset]= meta
                    logging.info(f"[DAILY SELL SKIP big gain] {asset}, ratio={ratio:.2f}, prob={prob:.2f}")
                    continue

            # SELL
            sold_val= bexec.sell_all(asset, real_qty)
            logging.info(f"[DAILY SELL LIVE] {asset}, prob={prob:.2f}, sold_val={sold_val:.2f}")
            if asset in state["positions_meta"]:
                del state["positions_meta"][asset]
            save_state(state)

    # BUY logic => top 5
    buy_candidates=[]
    for sym in tokens:
        if sym in holdings:
            continue
        pr= get_probability_for_symbol(sym)
        if pr and pr>= strat["buy_threshold"]:
            buy_candidates.append((sym, pr))

    buy_candidates.sort(key=lambda x:x[1], reverse=True)
    buy_candidates= buy_candidates[:5]

    if buy_candidates and usdt_balance>10:
        alloc= usdt_balance/ len(buy_candidates)
        for sym, pb in buy_candidates:
            qty_bought, avg_px= bexec.buy(sym, alloc)
            if qty_bought>0:
                logging.info(f"[DAILY BUY LIVE] {sym}, prob={pb:.2f}, cost={alloc:.2f}, px={avg_px:.4f}")
                state["positions_meta"][sym]= {
                    "entry_px": avg_px,
                    "did_skip_sell_once": False,
                    "partial_sold": False,
                    "max_price": avg_px
                }
                usdt_balance-= alloc
                save_state(state)

    logging.info("[DAILY UPDATE] Done daily_update (live).")


if __name__=="__main__":
    main()

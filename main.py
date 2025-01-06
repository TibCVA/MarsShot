#!/usr/bin/env python3
# coding: utf-8

import time
import logging
import datetime
import yaml
import os
import threading

from modules.trade_executor import TradeExecutor
from modules.utils import send_telegram_message
from modules.ml_decision import get_probability_for_symbol
from modules.positions_store import load_state, save_state
from modules.risk_manager import intraday_check_real
# Si vous avez un telegram_integration => on l'importe
try:
    from modules.telegram_integration import run_telegram_bot
except ImportError:
    def run_telegram_bot():
        pass  # pas de fallback, juste vide

def main():
    """
    Boucle principale du bot de trading en mode 100% "live" sur Binance.
    - A 13h00 UTC => daily_update(...) => SELL/BUY en direct sur Binance
    - Intraday => toutes les X sec => intraday_check_real(...) => partial/trailing
    - Stockage minimal local : bot_state.json => pour did_skip_sell_once, partial_sold, max_price
    """
    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml manquant.")
        return

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    logging.basicConfig(
        filename=config["logging"]["file"],
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("[MAIN] Starting main loop (LIVE).")

    # Telegram bot dans un thread
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()

    # charge state (juste pour ephemeral metadata)
    state = load_state()  # plus de param capital_initial

    # init trade executor
    bexec = TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )

    while True:
        try:
            now_utc = datetime.datetime.utcnow()

            # daily update => ex. 13h00 UTC
            if (
                now_utc.hour == config["strategy"]["daily_update_hour_utc"]
                and now_utc.minute == 0
                and not state.get("did_daily_update_today", False)
            ):
                daily_update_live(state, config, bexec)
                state["did_daily_update_today"] = True
                save_state(state)

            # reset flag avant 13h
            if (
                now_utc.hour == config["strategy"]["daily_update_hour_utc"]
                and now_utc.minute < 0
            ):
                state["did_daily_update_today"] = False
                save_state(state)

            # intraday check
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
    1) SELL => si prob < sell_threshold (sauf skip si ratio >= big_gain_exception_pct).
    2) BUY => max 5 tokens (plus forte prob >= buy_threshold)
       On regarde le solde USDT sur Binance pour savoir combien on peut allouer.
    """
    logging.info("[DAILY UPDATE] Starting daily_update (live).")
    tokens = config["tokens_daily"]
    strat  = config["strategy"]

    # SELL logic (live)
    # => on récup le solde:  client.get_account() + pour chaque coin > 0 (sauf USDT), check prob
    # => on applique la skip big gain
    account_info = bexec.client.get_account()
    balances = account_info["balances"]
    # On fait un dict { "FET": qty, "AGIX": qty, ... }, ignoring USDT
    holdings = {}
    for b in balances:
        asset = b["asset"]
        free  = float(b["free"])
        locked= float(b["locked"])
        qty   = free + locked
        if qty>0 and asset != "USDT":
            holdings[asset] = qty

    # check each holding => prob => SELL if prob<sell_threshold
    for asset, real_qty in holdings.items():
        prob = get_probability_for_symbol(asset)
        if prob is None:
            logging.info(f"[DAILY SELL] {asset} => prob=None => skip.")
            continue

        if prob < strat["sell_threshold"]:
            # check ratio => on calcule ratio = current_px / entry_px ??? 
            # On n'a pas d'entry_px local => on va lire ephemeral state
            meta = state["positions_meta"].get(asset, {})
            did_skip = meta.get("did_skip_sell_once", False)

            current_px = bexec.get_symbol_price(asset)
            # on simule "entry_px" ??? => si on n'a pas, on skip big gain ?
            entry_px = meta.get("entry_px", None)
            if entry_px:
                ratio = current_px/ entry_px
                if ratio >= strat["big_gain_exception_pct"] and not did_skip:
                    meta["did_skip_sell_once"] = True
                    logging.info(f"[DAILY SELL SKIP big gain] {asset}, ratio={ratio:.2f}, prob={prob:.2f}")
                    state["positions_meta"][asset] = meta
                    continue
            # sinon, on vend
            sold_val = bexec.sell_all(asset, real_qty)
            logging.info(f"[DAILY SELL] {asset}, prob={prob:.2f}, sold_val={sold_val:.2f}")
            # on supprime la meta
            if asset in state["positions_meta"]:
                del state["positions_meta"][asset]
            save_state(state)

    # BUY logic => tri par prob desc => top5 => on alloue capital USDT
    # On lit solde USDT reel
    usdt_balance=0.0
    for b in balances:
        if b["asset"]=="USDT":
            usdt_balance = float(b["free"])+ float(b["locked"])
            break

    buy_candidates=[]
    for sym in tokens:
        # skip si on a deja le sym
        if sym in holdings:
            continue
        prob = get_probability_for_symbol(sym)
        if prob and prob>=strat["buy_threshold"]:
            buy_candidates.append((sym, prob))

    buy_candidates.sort(key=lambda x:x[1], reverse=True)
    buy_candidates = buy_candidates[:5]  # top5

    if buy_candidates and usdt_balance>10:  # on met un mini
        # On repartit => ex. usdt_balance / len(buy_candidates)
        alloc = usdt_balance/len(buy_candidates)
        for sym, pb in buy_candidates:
            qty_bought, avg_px = bexec.buy(sym, alloc)
            if qty_bought>0:
                logging.info(f"[DAILY BUY] {sym}, prob={pb:.2f}, cost={alloc:.2f}, px={avg_px:.4f}")
                # On store la meta => entry_px=avg_px, did_skip_sell_once=False, partial_sold=False, max_price=avg_px
                state["positions_meta"][sym] = {
                    "entry_px": avg_px,
                    "did_skip_sell_once": False,
                    "partial_sold": False,
                    "max_price": avg_px
                }
                save_state(state)

    logging.info("[DAILY UPDATE] Done daily_update (live).")

if __name__=="__main__":
    main()

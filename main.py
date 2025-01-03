#!/usr/bin/env python3
# coding: utf-8

import time
import logging
import datetime
import yaml
import os
import threading

from modules.positions_store import load_state, save_state
from modules.data_fetcher import fetch_prices_for_symbols
from modules.risk_manager import update_positions_in_intraday
from modules.trade_executor import TradeExecutor
from modules.utils import send_telegram_message

# ML pour daily_update
from modules.ml_decision import get_probability_for_symbol

# => NOUVEAU => si tu veux lancer le bot Telegram en même temps
# (si tu as créé telegram_integration.py)
from telegram_integration import run_telegram_bot

def main():
    # Optionnel => lancer le bot
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()

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
    logging.info("[BOT] Started.")

    state = load_state(config["strategy"]["capital_initial"])
    bexec = TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )

    while True:
        try:
            now_utc = datetime.datetime.utcnow()

            # 00h30 => daily update
            if (now_utc.hour == config["strategy"]["daily_update_hour_utc"]
                and now_utc.minute >= 30
                and not state.get("did_daily_update_today", False)):
                daily_update(state, config, bexec)
                state["did_daily_update_today"] = True
                save_state(state)

            # reset flag avant 00h30
            if (now_utc.hour == config["strategy"]["daily_update_hour_utc"]
                and now_utc.minute < 30):
                state["did_daily_update_today"] = False
                save_state(state)

            # Intraday check
            if (time.time() - state.get("last_risk_check_ts", 0)
               ) >= config["strategy"]["check_interval_seconds"]:

                symbols_in_portfolio = list(state["positions"].keys())
                if symbols_in_portfolio:
                    px_map = fetch_prices_for_symbols(symbols_in_portfolio)
                    update_positions_in_intraday(state, px_map, config, bexec)
                    save_state(state)

                state["last_risk_check_ts"] = time.time()

        except Exception as e:
            logging.error(f"[MAIN ERROR] {e}")

        time.sleep(10)

def daily_update(state, config, bexec):
    tokens = config["tokens_daily"]
    strat = config["strategy"]

    # SELL
    for sym in list(state["positions"].keys()):
        prob = get_probability_for_symbol(sym)
        if prob is None:
            logging.info(f"[DAILY SELL] {sym} => prob=None => skip")
            continue

        if prob < strat["sell_threshold"]:
            current_px = get_live_price(sym)
            if current_px is None:
                continue

            ratio = current_px / state["positions"][sym]["entry_price"]
            if ratio >= strat["big_gain_exception_pct"] and not state["positions"][sym].get("did_skip_sell_once", False):
                state["positions"][sym]["did_skip_sell_once"] = True
                logging.info(f"[DAILY SELL SKIPPED +300%] {sym}, ratio={ratio:.2f}, prob={prob:.2f}")
            else:
                liquidation = bexec.sell_all(sym, state["positions"][sym]["qty"])
                state["capital_usdt"] += liquidation
                del state["positions"][sym]
                logging.info(f"[DAILY SELL] {sym}, prob={prob:.2f}, liquidation={liquidation:.2f}")

    save_state(state)

    # BUY
    buy_candidates = []
    for sym in tokens:
        if sym in state["positions"]:
            continue

        prob = get_probability_for_symbol(sym)
        if prob is None:
            continue

        if prob >= strat["buy_threshold"]:
            buy_candidates.append(sym)

    if buy_candidates:
        if state["capital_usdt"] > 0:
            alloc = state["capital_usdt"] / len(buy_candidates)
            for sym in buy_candidates:
                if alloc < 5:
                    break

                qty, px = bexec.buy(sym, alloc)
                if qty > 0:
                    state["capital_usdt"] -= alloc
                    state["positions"][sym] = {
                        "qty": qty,
                        "entry_price": px,
                        "did_skip_sell_once": False,
                        "partial_sold": False
                    }
                    logging.info(f"[DAILY BUY] {sym}, prob>=? => qty={qty}, px={px}")

    save_state(state)

def get_live_price(sym):
    from modules.data_fetcher import fetch_current_price_from_coinbase
    return fetch_current_price_from_coinbase(sym)

if __name__ == "__main__":
    main()
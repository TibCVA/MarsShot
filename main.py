#!/usr/bin/env python3
# coding: utf-8

import time
import logging
import datetime
import yaml
import os
import threading

from modules.positions_store import load_state, save_state
from modules.data_fetcher import fetch_prices_for_symbols, fetch_current_price_from_binance
from modules.risk_manager import update_positions_in_intraday
from modules.trade_executor import TradeExecutor
from modules.utils import send_telegram_message
from modules.ml_decision import get_probability_for_symbol

# Optionnel => si tu as un telegram_integration.py
try:
    from telegram_integration import run_telegram_bot
except ImportError:
    def run_telegram_bot():
        pass  # fallback si pas de telegram_integration

def main():
    """
    Boucle principale du bot de trading.
    - Tourne en continu, exécute daily_update à 00h30 UTC, intraday check toutes X secondes.
    - Gère la persistance dans bot_state.json via load_state/save_state.
    - Lance le bot telegram (run_telegram_bot) dans un thread, si dispo.
    """
    # Lancer le bot Telegram dans un thread
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()

    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml manquant.")
        return

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Init logging
    logging.basicConfig(
        filename=config["logging"]["file"],
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("[BOT] Started main loop.")

    # Charger état + init trade executor
    state = load_state(config["strategy"]["capital_initial"])
    bexec = TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )

    while True:
        try:
            now_utc = datetime.datetime.utcnow()

            # 00h30 => daily update
            if (
                now_utc.hour == config["strategy"]["daily_update_hour_utc"]
                and now_utc.minute >= 30
                and not state.get("did_daily_update_today", False)
            ):
                daily_update(state, config, bexec)
                state["did_daily_update_today"] = True
                save_state(state)

            # reset flag avant 00h30
            if (
                now_utc.hour == config["strategy"]["daily_update_hour_utc"]
                and now_utc.minute < 30
            ):
                state["did_daily_update_today"] = False
                save_state(state)

            # Intraday check
            last_check = state.get("last_risk_check_ts", 0)
            if (time.time() - last_check) >= config["strategy"]["check_interval_seconds"]:
                
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
    """
    Appelé 1 fois/jour (à 00h30 UTC).
    1) SELL => si prob < sell_threshold (sauf big_gain_exception_pct).
    2) BUY => max 5 tokens (ceux qui ont la plus forte prob >= buy_threshold),
              en répartissant le capital usdt disponible.
    """
    tokens = config["tokens_daily"]
    strat  = config["strategy"]

    # --- SELL LOGIC ---
    for sym in list(state["positions"].keys()):
        prob = get_probability_for_symbol(sym)
        if prob is None:
            logging.info(f"[DAILY SELL] {sym} => prob=None => skip")
            continue

        if prob < strat["sell_threshold"]:
            current_px = fetch_current_price_from_binance(sym)
            if not current_px:
                continue

            entry_px = state["positions"][sym]["entry_price"]
            ratio = current_px / entry_px
            # big_gain_exception_pct => skip la vente 1x si ratio >= 4.0 par ex.
            if ratio >= strat["big_gain_exception_pct"] and not state["positions"][sym].get("did_skip_sell_once", False):
                state["positions"][sym]["did_skip_sell_once"] = True
                logging.info(f"[DAILY SELL SKIPPED >{strat['big_gain_exception_pct']}x] {sym}, ratio={ratio:.2f}, prob={prob:.2f}")
            else:
                liquidation = bexec.sell_all(sym, state["positions"][sym]["qty"])
                state["capital_usdt"] += liquidation
                del state["positions"][sym]
                logging.info(f"[DAILY SELL] {sym}, prob={prob:.2f}, liquidation={liquidation:.2f}")

    save_state(state)

    # --- BUY LOGIC ---
    buy_candidates = []
    for sym in tokens:
        if sym in state["positions"]:
            continue  # déjà en portefeuille => skip
        prob = get_probability_for_symbol(sym)
        if prob is None:
            continue
        if prob >= strat["buy_threshold"]:
            buy_candidates.append((sym, prob))

    # On ne veut acheter que 5 tokens max => on trie par prob desc
    # ex: buy_candidates = [("FET",0.82), ("AGIX",0.88), ...]
    buy_candidates.sort(key=lambda x: x[1], reverse=True)
    # On garde top 5
    buy_candidates = buy_candidates[:5]

    if buy_candidates and state["capital_usdt"] > 0:
        # On répartit capital_usdt sur len(buy_candidates)
        alloc = state["capital_usdt"] / len(buy_candidates)
        for sym, pb in buy_candidates:
            qty_bought, avg_px = bexec.buy(sym, alloc)
            if qty_bought>0:
                # On ajoute la position
                state["positions"][sym] = {
                    "qty": qty_bought,
                    "entry_price": avg_px,
                    "did_skip_sell_once": False,
                    "partial_sold": False,
                    "max_price": None
                }
                state["capital_usdt"] -= alloc
                logging.info(f"[DAILY BUY] {sym}, prob={pb:.2f}>= {strat['buy_threshold']}, cost={alloc:.2f}, px={avg_px:.4f}")
    save_state(state)


if __name__=="__main__":
    main()
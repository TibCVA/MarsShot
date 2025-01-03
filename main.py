#!/usr/bin/env python3
# coding: utf-8

import time
import logging
import datetime
import yaml
import os

# Modules inchangés pour la gestion d'état, risk management, exécution d'ordres, etc.
from modules.positions_store import load_state, save_state
from modules.data_fetcher import fetch_prices_for_symbols
from modules.risk_manager import update_positions_in_intraday
from modules.trade_executor import TradeExecutor
from modules.utils import send_telegram_message

# Nouveau : on appelle la fonction qui réplique build_csv.py, avec TOUTES les features
# (galaxy_score, alt_rank, sentiment, rsi, macd, atr, etc.)
# Elle renvoie directement la prob => None si data insuffisante
from modules.ml_decision import get_probability_for_symbol

def main():
    # 1) Lecture de la config
    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml manquant.")
        return

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # 2) Setup logging
    logging.basicConfig(
        filename=config["logging"]["file"],
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("[BOT] Started.")

    # 3) Chargement de l'état du bot + init TradeExecutor
    state = load_state(config["strategy"]["capital_initial"])
    bexec = TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )

    # 4) Boucle infinie
    while True:
        try:
            now_utc = datetime.datetime.utcnow()

            # => 00h30 UTC => daily check
            if (now_utc.hour == config["strategy"]["daily_update_hour_utc"]
                and now_utc.minute >= 30
                and not state.get("did_daily_update_today", False)):
                daily_update(state, config, bexec)
                state["did_daily_update_today"] = True
                save_state(state)

            # => On reset le flag avant 00h30
            if (now_utc.hour == config["strategy"]["daily_update_hour_utc"]
                and now_utc.minute < 30):
                state["did_daily_update_today"] = False
                save_state(state)

            # => Intraday check toutes les X secondes
            if (time.time() - state.get("last_risk_check_ts", 0)
               ) >= config["strategy"]["check_interval_seconds"]:
                # Mise à jour intraday (stop-loss, trailing, partial, etc.)
                symbols_in_portfolio = list(state["positions"].keys())
                if symbols_in_portfolio:
                    # Récup prix via Coinbase
                    px_map = fetch_prices_for_symbols(symbols_in_portfolio)
                    update_positions_in_intraday(state, px_map, config, bexec)
                    save_state(state)

                state["last_risk_check_ts"] = time.time()

        except Exception as e:
            logging.error(f"[MAIN ERROR] {e}")
            # Envoi Telegram si besoin
            # send_telegram_message(config["telegram_bot_token"], config["telegram_chat_id"], f"[MAIN ERROR] {e}")

        time.sleep(10)


def daily_update(state, config, bexec):
    """
    Routine exécutée 1x/jour (après 00h30 UTC).
    1) SELL step : pour chaque token en portefeuille, on calcule la proba => si prob<sell_threshold => on vend (sauf +300% => skip).
    2) BUY step : pour chaque token de tokens_daily qui n'est pas en portefeuille, on calcule la proba => si prob>=buy_threshold => on achète.
    """

    tokens = config["tokens_daily"]
    strat = config["strategy"]

    ##############
    # SELL Step
    ##############
    for sym in list(state["positions"].keys()):
        prob = get_probability_for_symbol(sym)  # None => data insuffisante
        if prob is None:
            # On ne peut pas calculer => on skip la vente forcée
            logging.info(f"[DAILY SELL] {sym} => prob=None => skip")
            continue

        if prob < strat["sell_threshold"]:
            # check exception +300% => x4
            current_px = get_live_price(sym)
            if current_px is None:
                continue

            ratio = current_px / state["positions"][sym]["entry_price"]
            # si ratio >= 4.0 => skip 1x
            if ratio >= strat["big_gain_exception_pct"] and not state["positions"][sym].get("did_skip_sell_once", False):
                state["positions"][sym]["did_skip_sell_once"] = True
                logging.info(f"[DAILY SELL SKIPPED +300%] {sym}, ratio={ratio:.2f}, prob={prob:.2f}")
            else:
                # On vend
                liquidation = bexec.sell_all(sym, state["positions"][sym]["qty"])
                state["capital_usdt"] += liquidation
                del state["positions"][sym]
                logging.info(f"[DAILY SELL] {sym}, prob={prob:.2f}, liquidation={liquidation:.2f}")

    save_state(state)

    ##############
    # BUY Step
    ##############
    buy_candidates = []
    for sym in tokens:
        if sym in state["positions"]:
            # déjà en portefeuille => skip
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
                if alloc < 5:  # Montant minimum pour un trade
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
    """
    Intraday => on utilise fetch_current_price_from_coinbase (pour le risk mgmt).
    """
    from modules.data_fetcher import fetch_current_price_from_coinbase
    return fetch_current_price_from_coinbase(sym)


if __name__ == "__main__":
    main()
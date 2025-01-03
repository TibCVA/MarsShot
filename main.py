#!/usr/bin/env python3
# coding: utf-8

import time
import logging
import datetime
import yaml
import os

from modules.positions_store import load_state, save_state
from modules.data_fetcher import fetch_prices_for_symbols, fetch_last_day_from_lunarcrush
from modules.risk_manager import update_positions_in_intraday
from modules.trade_executor import TradeExecutor
from modules.utils import send_telegram_message
from modules.ml_decision import predict_probability

def main():
    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml manquant.")
        return

    with open("config.yaml","r") as f:
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

            # => 00h30 UTC => daily check
            if now_utc.hour == config["strategy"]["daily_update_hour_utc"] and now_utc.minute >= 30 and not state.get("did_daily_update_today", False):
                daily_update(state, config, bexec)
                state["did_daily_update_today"] = True
                save_state(state)

            if now_utc.hour == config["strategy"]["daily_update_hour_utc"] and now_utc.minute < 30:
                # Reset pour le prochain jour
                state["did_daily_update_today"] = False
                save_state(state)

            # => Intraday check toutes les X secondes
            if (time.time() - state.get("last_risk_check_ts", 0)) >= config["strategy"]["check_interval_seconds"]:
                symbols_in_portfolio = list(state["positions"].keys())
                if symbols_in_portfolio:
                    px_map = fetch_prices_for_symbols(symbols_in_portfolio)
                    update_positions_in_intraday(state, px_map, config, bexec)
                    save_state(state)
                state["last_risk_check_ts"] = time.time()

        except Exception as e:
            logging.error(f"[MAIN ERROR] {e}")
            # Envoi Telegram si besoin
            # send_telegram_message(...)

        time.sleep(10)

def daily_update(state, config, bexec):
    """
    1) Pour chaque token => calculer prob via la dernière bougie LunarCrush (fetch_last_day_from_lunarcrush).
    2) Sell si prob<0.30 (sauf exception +300% => x4).
    3) Buy si prob≥0.70 (et pas déjà en position). On répartit le capital equally sur tous les signaux.
    """
    tokens = config["tokens_daily"]
    strat  = config["strategy"]

    # SELL step
    # On veut d'abord connaître la prob de tous les tokens en portefeuille
    for sym in list(state["positions"].keys()):
        feats = get_daily_features_for(sym, config)
        prob = predict_probability(feats) if feats else 0.0
        if prob < strat["sell_threshold"]:
            # check +300% => x4
            current_px = get_live_price(sym)
            if current_px is None:
                continue

            ratio = current_px / state["positions"][sym]["entry_price"]
            # si ratio>=4.0 et pas encore skip => on skip la vente
            if ratio >= strat["big_gain_exception_pct"] and not state["positions"][sym].get("did_skip_sell_once", False):
                state["positions"][sym]["did_skip_sell_once"] = True
                logging.info(f"[DAILY SELL SKIPPED +300%] {sym}, ratio={ratio:.2f}, prob={prob:.2f}")
            else:
                # on vend
                liquidation = bexec.sell_all(sym, state["positions"][sym]["qty"])
                state["capital_usdt"] += liquidation
                del state["positions"][sym]
                logging.info(f"[DAILY SELL] {sym}, prob={prob:.2f}, liquidation={liquidation:.2f}")

    save_state(state)

    # BUY step
    buy_candidates = []
    for sym in tokens:
        # si déjà en position => skip
        if sym in state["positions"]:
            continue
        feats = get_daily_features_for(sym, config)
        if not feats:
            continue
        prob = predict_probability(feats)
        if prob >= strat["buy_threshold"]:
            buy_candidates.append(sym)

    if buy_candidates:
        if state["capital_usdt"]>0:
            alloc = state["capital_usdt"] / len(buy_candidates)
            for sym in buy_candidates:
                if alloc<5:  # si trop petit
                    break
                qty, px = bexec.buy(sym, alloc)
                if qty>0:
                    state["capital_usdt"] -= alloc
                    state["positions"][sym] = {
                        "qty": qty,
                        "entry_price": px,
                        "did_skip_sell_once": False,
                        "partial_sold": False
                    }
                    logging.info(f"[DAILY BUY] {sym}, prob=?, qty={qty}, px={px}")

    save_state(state)

def get_live_price(sym):
    from modules.data_fetcher import fetch_current_price_from_coinbase
    return fetch_current_price_from_coinbase(sym)

def get_daily_features_for(sym, config):
    """
    Va récupérer la dernière bougie daily sur LunarCrush (2 jours),
    calcule RSI, MACD, ATR, merge btc/eth daily change => renvoie un dict de features.
    """
    api_key = config["lunarcrush"]["api_key"]
    feats = fetch_last_day_from_lunarcrush(sym, api_key)
    return feats


if __name__=="__main__":
    main()
import time
import logging
import yaml
import os

from modules.positions_store import load_state, save_state
from modules.data_fetcher import fetch_data_for_all_tokens, is_global_crash
from modules.ml_decision import get_buy_signal
from modules.risk_manager import (
    manage_positions,
    extract_profits_if_needed,
    circuit_breaker_check,
    global_drawdown_check
)
from modules.trade_executor import (
    sell_all_positions,
    smart_buy,
    sync_balances
)
from modules.utils import send_telegram_message

def main_loop():
    with open("config.yaml","r") as f:
        config = yaml.safe_load(f)

    log_file = config["logging"]["file"]
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("Bot started")

    state = load_state(config["capital"]["initial"])
    tokens_list = config["tokens"]

    while True:
        try:
            # 1) Crash global ?
            if is_global_crash(config):
                logging.warning("Global crash => SELL ALL")
                sell_all_positions(state, config)
                state["positions"] = {}
                save_state(state)
                time.sleep(600)
                continue
            
            # 2) Circuit breaker => trop de trades perdants ?
            if circuit_breaker_check(state, config):
                logging.warning("Circuit breaker => pause 10min")
                time.sleep(600)
                continue

            # 3) drawdown global ?
            if global_drawdown_check(state, config):
                logging.warning("Max drawdown => SELL ALL + pause 10min")
                sell_all_positions(state, config)
                state["positions"] = {}
                save_state(state)
                time.sleep(600)
                continue

            # 4) fetch data
            data_map = fetch_data_for_all_tokens(tokens_list, config)

            # 5) manage positions (stop-loss, trailing, etc.)
            manage_positions(state, data_map, config)
            extract_profits_if_needed(state, config)
            save_state(state)

            # 6) nouvelles positions
            if len(state["positions"]) < config["risk"]["max_positions"]:
                sync_balances(state, config)
                for t in tokens_list:
                    sym = t["symbol"]
                    if sym in state["positions"]:
                        continue
                    if len(state["positions"]) >= config["risk"]["max_positions"]:
                        break
                    feats = data_map.get(sym, {}).get("features", None)
                    if not feats:
                        continue
                    buy_signal, prob = get_buy_signal(feats, config["ml"]["buy_probability_threshold"])
                    if buy_signal:
                        p = feats["price"]
                        if p > 0:
                            pos_size = state["capital"] * config["risk"]["risk_per_position"]
                            qty = pos_size / p
                            success = smart_buy(sym, qty, config, data_map)
                            if success:
                                state["capital"] -= pos_size
                                atr_val = feats.get("ATR", 0)
                                sl_price = p - config["risk"]["atr_stop_loss_multiplier"] * atr_val
                                if sl_price <= 0:
                                    sl_price = p * 0.8
                                state["positions"][sym] = {
                                    "qty": qty,
                                    "entry_price": p,
                                    "stop_loss": sl_price,
                                    "trailing_active": False
                                }
                                logging.info(f"[BUY] {sym}, prob={prob:.2f}, SL={sl_price:.4f}")
                                save_state(state)

            time.sleep(300)  # 5 minutes
        except Exception as e:
            logging.error(f"[MAIN ERROR] {e}")
            send_telegram_message(config, f"[MAIN ERROR] {e}")
            time.sleep(60)

if __name__=="__main__":
    main_loop()


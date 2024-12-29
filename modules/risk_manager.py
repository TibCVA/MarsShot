import logging
from .trade_executor import smart_sell

def manage_positions(state, data_map, config):
    positions = state["positions"]
    to_remove = []
    for sym, pos in positions.items():
        feats = data_map.get(sym, {}).get("features", {})
        price = feats.get("price", 0)
        if price <= 0:
            continue

        # STOPLOSS
        if price <= pos["stop_loss"]:
            qty = pos["qty"]
            liquidation = price*qty
            ok = smart_sell(sym, qty, config)
            if ok:
                state["capital"] += liquidation
                logging.info(f"[STOPLOSS SELL] {sym} => +{liquidation:.2f}")
                if price < pos["entry_price"]:
                    state["losses_count"] = state.get("losses_count",0)+1
            to_remove.append(sym)
            continue

        # TRAILING STOP
        if not pos["trailing_active"]:
            trigger = 1 + config["risk"]["trailing_trigger_gain"]
            if price >= pos["entry_price"]*trigger:
                pos["trailing_active"] = True
                keep = 1 + config["risk"]["trailing_stop_keep"]
                new_sl = pos["entry_price"]*keep
                if new_sl>pos["stop_loss"]:
                    pos["stop_loss"] = new_sl
                logging.info(f"[TRAILING ACTIVATED] {sym} => SL={new_sl:.4f}")
        else:
            pass

    for s in to_remove:
        del positions[s]

def extract_profits_if_needed(state, config):
    cap = state["capital"]
    cap_high = state.get("capital_high", cap)
    if cap > 2*cap_high:
        ext = cap*config["risk"]["extraction_ratio"]
        state["capital"] -= ext
        state["capital_high"] = state["capital"]
        logging.info(f"[EXTRACTION] {ext:.2f} USDT")
    else:
        if cap>cap_high:
            state["capital_high"] = cap

def circuit_breaker_check(state, config):
    losses_count = state.get("losses_count",0)
    max_loss = config["risk"]["max_consecutive_losses"]
    return (losses_count>=max_loss)

def global_drawdown_check(state, config):
    cap = state["capital"]
    cap_high = state.get("capital_high", cap)
    md = config["risk"].get("max_drawdown",0.30)
    if cap <= (1-md)*cap_high:
        return True
    return False


import logging

def update_positions_in_intraday(state, prices_map, config, trade_executor):
    """
    prices_map = { 'FET': 0.234, 'AGIX': 0.67, ... }  => prix spot en USD
    Applique :
      - STOP-LOSS => -30% (car stop_loss_pct=0.30)
      - PARTIAL SELL => +50% (partial_take_profit_pct=0.5) => vend 35% (partial_take_profit_ratio=0.35) si pas déjà fait
      - TRAILING STOP => si ratio >= 2.0 => on tolère 30% retracement
    """
    strat = config["strategy"]
    to_remove = []

    for sym, pos in state["positions"].items():
        current_price = prices_map.get(sym)
        if not current_price:
            continue
        
        entry = pos["entry_price"]
        
        # STOP-LOSS => -30%
        if current_price <= entry * (1 - strat["stop_loss_pct"]):
            logging.info(f"[STOPLOSS] {sym}")
            liquidation = trade_executor.sell_all(sym, pos["qty"])
            state["capital_usdt"] += liquidation
            to_remove.append(sym)
            continue
        
        # Calcul du ratio (ex: 1.5 => +50%)
        gain_ratio = current_price / entry

        # PARTIAL => +50% => vend 35% => si pas encore partial_sold
        if gain_ratio >= (1 + strat["partial_take_profit_pct"]) and not pos.get("partial_sold", False):
            qty_to_sell = pos["qty"] * strat["partial_take_profit_ratio"]
            partial_val = trade_executor.sell_partial(sym, qty_to_sell)
            state["capital_usdt"] += partial_val
            pos["qty"] -= qty_to_sell
            pos["partial_sold"] = True
            logging.info(f"[PARTIAL SELL +{int(strat['partial_take_profit_pct']*100)}%] {sym} => +{partial_val:.2f} USDT")

        # TRAILING => si ratio>= 2.0
        if gain_ratio >= strat["trailing_trigger_pct"]:
            if "max_price" not in pos or pos["max_price"] < current_price:
                pos["max_price"] = current_price

            if pos["max_price"] and current_price <= pos["max_price"]*(1 - strat["trailing_pct"]):
                logging.info(f"[TRAILING STOP] {sym}")
                liquidation = trade_executor.sell_all(sym, pos["qty"])
                state["capital_usdt"] += liquidation
                to_remove.append(sym)

    for s in to_remove:
        if s in state["positions"]:
            del state["positions"][s]
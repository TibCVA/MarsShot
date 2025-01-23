import logging
from modules.positions_store import save_state

def intraday_check_real(state, bexec, config):
    """
    Lecture du compte => on applique stop-loss, partial, trailing...
    """
    logging.info("[INTRADAY] Starting intraday_check_real")

    strat = config["strategy"]

    try:
        account_info = bexec.client.get_account()
    except Exception as e:
        logging.error(f"[INTRADAY] get_account error => {e}")
        return

    balances = account_info["balances"]
    holdings={}
    for b in balances:
        asset= b["asset"]
        free= float(b["free"])
        locked= float(b["locked"])
        qty= free+ locked
        # On skip si c'est 0 ou USDT
        if qty>0 and asset.upper()!="USDT":
            holdings[asset]= qty

    logging.info(f"[INTRADAY] holdings={holdings}")

    for asset, real_qty in holdings.items():
        current_px = bexec.get_symbol_price(asset)
        meta = state["positions_meta"].get(asset, {})
        entry_px = meta.get("entry_px", 0.0)
        if entry_px<=0:
            # Si on n'a pas d'entry_px, on l'initialise 1 fois,
            # ou alors on dit ratio=1.0 si on veut "ignorer" 
            # ce n'est pas un token acheté par le bot.
            ratio = 1.0
            entry_px = 0.0
        else:
            ratio= current_px / entry_px

        logging.info(
            f"[INTRADAY] {asset} => ratio={ratio:.3f}, "
            f"entry_px={entry_px:.4f}, current_px={current_px:.4f}"
        )

        # STOP-LOSS
        if ratio <= (1 - strat["stop_loss_pct"]) and entry_px>0:
            logging.info(f"[INTRADAY STOPLOSS] {asset}, ratio={ratio:.2f}")
            sold_val= bexec.sell_all(asset, real_qty)
            logging.info(f"[INTRADAY STOPLOSS] => sold_val={sold_val:.2f}")
            if asset in state["positions_meta"]:
                del state["positions_meta"][asset]
            save_state(state)
            continue

        # PARTIAL => if ratio>= (1+ partial_take_profit_pct) & not partial_sold
        if ratio >= (1 + strat["partial_take_profit_pct"]) and not meta.get("partial_sold",False) and entry_px>0:
            qty_to_sell= real_qty * strat["partial_take_profit_ratio"]
            partial_val= bexec.sell_partial(asset, qty_to_sell)
            meta["partial_sold"]= True
            logging.info(f"[INTRADAY PARTIAL SELL] {asset}, ratio={ratio:.2f}, partial_val={partial_val:.2f}")
            state["positions_meta"][asset]= meta
            save_state(state)

        # TRAILING => if ratio>= trailing_trigger_pct => track max_price => if drop -X% => sell all
        if ratio>= strat["trailing_trigger_pct"] and entry_px>0:
            mx= meta.get("max_price", entry_px)
            if current_px> mx:
                mx= current_px
                meta["max_price"]= mx
                logging.info(f"[INTRADAY TRAILING] new max {asset} => {mx:.4f}")
                state["positions_meta"][asset]= meta
                save_state(state)

            if mx>0 and current_px <= mx*(1 - strat["trailing_pct"]):
                logging.info(f"[INTRADAY TRAILING STOP] {asset}, ratio={ratio:.2f}")
                sold_val= bexec.sell_all(asset, real_qty)
                logging.info(f"[INTRADAY TRAILING STOP] => sold_val={sold_val:.2f}")
                if asset in state["positions_meta"]:
                    del state["positions_meta"][asset]
                save_state(state)

    # Supprimer metas d'assets qu'on ne détient plus
    for a in list(state["positions_meta"].keys()):
        if a not in holdings:
            del state["positions_meta"][a]
            logging.info(f"[INTRADAY CLEAN META] remove {a}, not in holdings.")
            save_state(state)

    logging.info("[INTRADAY] done.")
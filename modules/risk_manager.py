import logging
from modules.positions_store import load_state, save_state

def intraday_check_real(state, bexec, config):
    """
    Lecture en live: on liste TOUTES les positions sur Binance (sauf USDT).
    On applique stop-loss, partial, trailing => on manipule la "positions_meta" locale
    pour savoir "entry_px", "did_skip_sell_once", "partial_sold", "max_price", etc.
    """
    strat = config["strategy"]

    # Récup l'account => live holdings
    account_info = bexec.client.get_account()
    balances = account_info["balances"]
    real_holdings={}
    for b in balances:
        asset = b["asset"]
        free = float(b["free"])
        locked=float(b["locked"])
        qty=free+locked
        if qty>0 and asset!="USDT":
            real_holdings[asset]=qty

    for asset, real_qty in real_holdings.items():
        current_px = bexec.get_symbol_price(asset)
        # On récup meta => entry_px, partial_sold, max_price
        meta = state["positions_meta"].get(asset,{})
        entry_px = meta.get("entry_px", None)
        if not entry_px:
            # On n'a pas d'info => on definit un entry_px a la volée
            # ou on skip le stop-loss
            meta["entry_px"] = current_px
            meta["partial_sold"] = False
            meta["max_price"] = current_px
            state["positions_meta"][asset] = meta
            save_state(state)
            logging.info(f"[INTRADAY REAL] new meta for {asset}, set entry_px={current_px:.4f}")
            continue

        # STOP-LOSS => ratio <= (1 - stop_loss_pct)
        ratio = current_px/ entry_px
        if ratio <= (1 - strat["stop_loss_pct"]):
            logging.info(f"[STOPLOSS REAL] {asset}, ratio={ratio:.2f}")
            sold_val = bexec.sell_all(asset, real_qty)
            logging.info(f"[STOPLOSS REAL] => sold_val={sold_val:.2f} USDT")
            if asset in state["positions_meta"]:
                del state["positions_meta"][asset]
            save_state(state)
            continue

        # partial => si ratio >= (1 + partial_take_profit_pct) && not partial_sold
        if ratio >= (1+ strat["partial_take_profit_pct"]) and not meta.get("partial_sold",False):
            qty_to_sell = real_qty * strat["partial_take_profit_ratio"]
            partial_val = bexec.sell_partial(asset, qty_to_sell)
            meta["partial_sold"]= True
            logging.info(f"[PARTIAL SELL REAL] {asset} ratio={ratio:.2f} => partial_val={partial_val:.2f}")
            state["positions_meta"][asset]=meta
            save_state(state)

        # trailing => if ratio >= trailing_trigger_pct => track max_price => if down -30% => sell all
        if ratio >= strat["trailing_trigger_pct"]:
            # update max_price si c plus haut
            mx = meta.get("max_price", entry_px)
            if current_px>mx:
                mx = current_px
                meta["max_price"]=mx
                logging.info(f"[TRAILING REAL] new max for {asset} => {mx:.4f}")
                state["positions_meta"][asset]=meta
                save_state(state)
            # check si on retombe de trailing_pct
            if current_px <= mx*(1- strat["trailing_pct"]):
                logging.info(f"[TRAILING STOP REAL] {asset}, ratio={ratio:.2f}")
                sold_val = bexec.sell_all(asset, real_qty)
                logging.info(f"[TRAILING STOP REAL] => sold_val={sold_val:.2f}")
                if asset in state["positions_meta"]:
                    del state["positions_meta"][asset]
                save_state(state)

    # On check si on a des meta sur des assets qu'on ne détient plus => on supprime
    for s in list(state["positions_meta"].keys()):
        if s not in real_holdings:
            del state["positions_meta"][s]
            logging.info(f"[INTRADAY REAL] Removed meta for {s}, no longer hold.")
            save_state(state)

    logging.info("[INTRADAY REAL] done check.")

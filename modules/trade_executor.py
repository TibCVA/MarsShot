#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import time
import os
import json
from binance.client import Client

TRADE_HISTORY_FILE = "trade_history.json"


# ------------------------------------------------------------------ #
# Utils JSON                                                         #
# ------------------------------------------------------------------ #
def load_trade_history():
    """Charge la liste de tous les trades stockés dans trade_history.json."""
    if not os.path.exists(TRADE_HISTORY_FILE):
        return []
    with open(TRADE_HISTORY_FILE, "r") as f:
        return json.load(f)


def save_trade_history(trades):
    """Enregistre la liste complète des trades dans trade_history.json."""
    with open(TRADE_HISTORY_FILE, "w") as f:
        json.dump(trades, f, indent=2)


def record_trade(side, asset, qty, cost, avg_px):
    """
    Ajoute un enregistrement de trade dans trade_history.json.
      • side  : "BUY" ou "SELL"
      • asset : ex. "BTC"
      • qty   : quantité échangée
      • cost  : montant USDC déboursé / reçu
      • avg_px: prix moyen d’exécution
    """
    trades = load_trade_history()
    now_ts = time.time()
    trades.append({
        "timestamp": now_ts,
        "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts)),
        "side": side.upper(),
        "asset": asset.upper(),
        "qty": float(qty),
        "cost_USDC": float(cost),
        "avg_px": float(avg_px)
    })
    save_trade_history(trades)


# ------------------------------------------------------------------ #
# TradeExecutor                                                      #
# ------------------------------------------------------------------ #
class TradeExecutor:
    def __init__(self, api_key, api_secret):
        self.client = Client(api_key, api_secret)
        logging.info("[TradeExecutor] Initialized with given API/Secret")

    # --------------------------- Helpers --------------------------- #
    def get_symbol_price(self, asset):
        """Retourne le prix spot de asset/USDC."""
        if asset.upper() == "USDC":
            return 1.0
        pair = asset.upper() + "USDC"
        try:
            tick = self.client.get_symbol_ticker(symbol=pair)
            px = float(tick["price"])
            logging.info(f"[get_symbol_price] {pair} => {px}")
            return px
        except Exception as e:
            logging.error(f"[get_symbol_price ERROR] {asset} => {e}")
            return 0.0

    # ------------------------------ SELL --------------------------- #
    def sell_all(self, asset, qty):
        """
        Vend la totalité du token `asset` (`qty`) contre USDC.
        Retourne la somme reçue en USDC.
        """
        if qty <= 0:
            logging.warning(f"[SELL_ALL] qty<=0 – skip {asset}")
            return 0.0

        pair = asset.upper() + "USDC"
        real_qty = self.adjust_quantity_lot_size(pair, qty)
        if real_qty <= 0:
            logging.warning(f"[SELL_ALL] real_qty<=0 – skip {asset}")
            return 0.0

        try:
            order = self.client.create_order(
                symbol=pair,
                side="SELL",
                type="MARKET",
                quantity=real_qty
            )

            # ---- NOUVEL ALGORITHME DE COMPTABILISATION --------------
            fill_qty = float(order.get("executedQty", 0))
            fill_sum = float(order.get("cummulativeQuoteQty", 0))

            # Si Binance retourne quand même le détail des fills, on les
            # utilise – sinon on garde les totaux calculés ci‑dessus.
            if fill_qty == 0 or fill_sum == 0:
                for f in order.get("fills", []):
                    px = float(f["price"])
                    qf = float(f["qty"])
                    fill_qty += qf
                    fill_sum += px * qf

            avg_px = fill_sum / fill_qty if fill_qty else 0.0
            logging.info(f"[SELL_ALL REAL] {pair} qty={fill_qty:.8f}, "
                         f"received={fill_sum:.2f} USDC, avg_px={avg_px:.6f}")

            record_trade("SELL", asset, fill_qty, fill_sum, avg_px)
            return fill_sum

        except Exception as e:
            logging.error(f"[SELL_ALL ERROR] {asset} => {e}", exc_info=True)
            return 0.0

    def sell_partial(self, asset, qty):
        """Vend partiellement `qty` – wrapper autour de sell_all()."""
        logging.info(f"[SELL_PARTIAL] {asset}, qty={qty}")
        return self.sell_all(asset, qty)

    # ------------------------------ BUY ---------------------------- #
    def buy(self, asset, usdc_amount):
        """
        Achète `asset` pour un montant `usdc_amount` (USDC) au marché.
        Retourne (fill_qty, avg_px, fill_sum).
        """
        pair = asset.upper() + "USDC"
        try:
            logging.info(f"[BUY] Init {pair} pour {usdc_amount:.2f} USDC")

            current_px = float(
                self.client.get_symbol_ticker(symbol=pair)["price"]
            )
            if current_px <= 0:
                logging.error(f"[BUY ERROR] Prix nul pour {pair}.")
                return 0.0, 0.0, 0.0

            raw_qty = usdc_amount / current_px
            adj_qty = self.adjust_quantity_lot_size(pair, raw_qty)
            if adj_qty <= 0:
                logging.warning(f"[BUY] Qty ajustée trop faible – skip {asset}")
                return 0.0, 0.0, 0.0

            order = self.client.create_order(
                symbol=pair,
                side="BUY",
                type="MARKET",
                quantity=adj_qty
            )

            # ---- Comptabilisation robuste --------------------------
            fill_qty = float(order.get("executedQty", 0))
            fill_sum = float(order.get("cummulativeQuoteQty", 0))

            if fill_qty == 0 or fill_sum == 0:
                for f in order.get("fills", []):
                    px = float(f["price"])
                    qf = float(f["qty"])
                    fill_qty += qf
                    fill_sum += px * qf

            avg_px = fill_sum / fill_qty if fill_qty else current_px
            logging.info(f"[BUY REAL] {pair} qty={fill_qty:.8f}, "
                         f"cost={fill_sum:.2f} USDC, avg_px={avg_px:.6f}")

            record_trade("BUY", asset, fill_qty, fill_sum, avg_px)
            return fill_qty, avg_px, fill_sum

        except Exception as e:
            logging.error(f"[BUY ERROR] {asset}: {e}", exc_info=True)
            return 0.0, 0.0, 0.0

    # ------------------ Ajustement des quantités ------------------- #
    def adjust_quantity_lot_size(self, symbol, raw_qty):
        """
        Ajuste `raw_qty` pour respecter LOT_SIZE / MIN_NOTIONAL.
        Retourne 0.0 si quantité impossible.
        """
        try:
            info = self.client.get_symbol_info(symbol)
            lot, notional = None, None
            for f in info["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    lot = f
                elif f["filterType"] == "MIN_NOTIONAL":
                    notional = f

            step = float(lot["stepSize"]) if lot else 1.0
            min_qty = float(lot["minQty"]) if lot else 1e-8
            min_notional = float(notional["minNotional"]) if notional else 10.0

            adj_qty = (raw_qty // step) * step
            if adj_qty < min_qty:
                return 0.0

            px = float(self.client.get_symbol_ticker(symbol=symbol)["price"])
            if px * adj_qty < min_notional:
                return 0.0

            return float(f"{adj_qty:.8f}")

        except Exception as e:
            logging.warning(f"[adjust_quantity_lot_size] {symbol} => {e}")
            return 0.0

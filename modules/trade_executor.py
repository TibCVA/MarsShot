import logging
import math
import time
from binance.client import Client

class TradeExecutor:
    def __init__(self, api_key, api_secret):
        self.client = Client(api_key, api_secret)
        logging.info("[TradeExecutor] Initialized with given API/Secret")

    def get_symbol_price(self, asset):
        """
        asset="BNB" => BNBUSDT
        asset="USDT" => return 1.0
        """
        if asset.upper() == "USDT":
            return 1.0
        pair = asset.upper() + "USDT"
        try:
            tick = self.client.get_symbol_ticker(symbol=pair)
            px = float(tick["price"])
            logging.info(f"[TradeExecutor.get_symbol_price] {pair} => {px}")
            return px
        except Exception as e:
            logging.error(f"[get_symbol_price ERROR] {asset} => {e}")
            return 0.0

    def sell_all(self, asset, qty):
        if qty <= 0:
            logging.warning(f"[SELL_ALL] qty<=0 => skip {asset}")
            return 0.0
        pair = asset.upper() + "USDT"

        # On ajuste la quantité selon LOT_SIZE (stepSize / minQty / minNotional)
        real_qty = self.adjust_quantity_lot_size(pair, qty)
        if real_qty <= 0:
            logging.warning(f"[SELL_ALL] real_qty <=0 après ajust => skip {asset}")
            return 0.0

        try:
            order = self.client.create_order(
                symbol=pair,
                side="SELL",
                type="MARKET",
                quantity=real_qty
            )
            fill_sum = 0.0
            fill_qty = 0.0
            for fill in order.get("fills", []):
                px = float(fill["price"])
                qf = float(fill["qty"])
                fill_sum += px * qf
                fill_qty += qf
            avg_px = fill_sum/fill_qty if fill_qty > 0 else 0
            logging.info(f"[SELL_ALL REAL] {pair} qty={real_qty:.8f}, fill_sum={fill_sum:.2f}, avg_px={avg_px:.4f}")
            return fill_sum
        except Exception as e:
            logging.error(f"[SELL_ALL ERROR] {asset} => {e}")
            return 0.0

    def sell_partial(self, asset, qty):
        logging.info(f"[SELL_PARTIAL] {asset}, qty={qty}")
        return self.sell_all(asset, qty)

    def buy(self, asset, usdt_amount):
        """
        Renvoie (fill_qty, avg_px, fill_sum):
          - fill_qty : quantité effectivement achetée
          - avg_px   : prix moyen d’exécution
          - fill_sum : coût total (en USDT)
        """
        pair = asset.upper() + "USDT"
        try:
            # Prix spot d'approximation
            px_info = self.client.get_symbol_ticker(symbol=pair)
            px = float(px_info["price"])

            raw_qty = usdt_amount / px
            adj_qty = self.adjust_quantity_lot_size(pair, raw_qty)
            if adj_qty <= 0:
                logging.warning(f"[BUY] {asset}, qty={adj_qty} => trop faible => skip")
                return (0.0, 0.0, 0.0)

            order = self.client.create_order(
                symbol=pair,
                side="BUY",
                type="MARKET",
                quantity=adj_qty
            )
            fill_sum = 0.0
            fill_qty = 0.0
            for fill in order.get("fills", []):
                fxp = float(fill["price"])
                fxq = float(fill["qty"])
                fill_sum += fxp * fxq
                fill_qty += fxq

            avg_px = fill_sum/fill_qty if fill_qty > 0 else px
            logging.info(f"[BUY REAL] {pair} => qty={fill_qty:.8f}, cost={fill_sum:.2f}, avg_px={avg_px:.4f}")
            return (fill_qty, avg_px, fill_sum)

        except Exception as e:
            logging.error(f"[BUY ERROR] {asset} => {e}")
            return (0.0, 0.0, 0.0)

    def adjust_quantity_lot_size(self, symbol, raw_qty):
        """
        Ajuste la quantité 'raw_qty' pour respecter:
          - stepSize (LOT_SIZE)
          - minQty   (LOT_SIZE)
          - minNotional
        Retourne la nouvelle quantité (float). Si 0 => skip.
        """
        try:
            info = self.client.get_symbol_info(symbol)
            lot_size_filter = None
            min_notional_filter = None

            for f_ in info["filters"]:
                if f_["filterType"] == "LOT_SIZE":
                    lot_size_filter = f_
                elif f_["filterType"] == "MIN_NOTIONAL":
                    min_notional_filter = f_

            step_size = float(lot_size_filter["stepSize"]) if lot_size_filter else 1.0
            min_qty   = float(lot_size_filter["minQty"])   if lot_size_filter else 1e-8
            min_notional = float(min_notional_filter["minNotional"]) if min_notional_filter else 10.0

            # Arrondi au multiple step_size => floor(raw_qty / step_size) * step_size
            adj_qty = (raw_qty // step_size) * step_size

            # Vérifie si adj_qty < min_qty => skip
            if adj_qty < min_qty:
                return 0.0

            # Vérifie minNotional => px * adj_qty >= min_notional
            px_info = self.client.get_symbol_ticker(symbol=symbol)
            px = float(px_info["price"])
            notional = px * adj_qty
            if notional < min_notional:
                return 0.0

            return float(f"{adj_qty:.8f}")  # arrondi final
        except Exception as e:
            logging.warning(f"[adjust_quantity_lot_size] {symbol} => {e}")
            # si erreur => on renvoie 0 => skip
            return 0.0
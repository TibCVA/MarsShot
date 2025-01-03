import logging
import time
from binance.client import Client

class TradeExecutor:
    def __init__(self, api_key, api_secret):
        self.client = Client(api_key, api_secret)

    def sell_all(self, symbol, qty):
        """
        Vend toute la qty sur la paire symbolUSDT (MARKET).
        Retourne la valeur en USDT (approx).
        """
        if qty<=0:
            return 0.0
        real_qty = round(qty, 5)
        try:
            order = self.client.create_order(
                symbol=f"{symbol}USDT",
                side="SELL",
                type="MARKET",
                quantity=real_qty
            )
            fill_sum = 0.0
            fill_qty = 0.0
            for fill in order.get("fills", []):
                px  = float(fill["price"])
                qf  = float(fill["qty"])
                fill_sum += px*qf
                fill_qty += qf
            avg_px = fill_sum/fill_qty if fill_qty>0 else 0
            logging.info(f"[SELL_ALL] {symbol} qty={real_qty}, avg_px={avg_px:.4f}")
            return fill_sum
        except Exception as e:
            logging.error(f"[SELL_ALL ERROR] {symbol} => {e}")
            return 0.0

    def sell_partial(self, symbol, qty):
        """
        Vend une partie de la position => quantite qty (MARKET).
        """
        return self.sell_all(symbol, qty)

    def buy(self, symbol, usdt_amount):
        """
        Achète en MARKET pour un certain montant USDT.
        Retourne (qty_effectivement_achetee, avg_px).
        """
        try:
            # 1) Récupérer le dernier prix
            ticker = self.client.get_symbol_ticker(symbol=f"{symbol}USDT")
            px = float(ticker["price"])
            raw_qty = usdt_amount / px
            real_qty = round(raw_qty, 5)
            if real_qty<=0:
                return (0.0, 0.0)

            order = self.client.create_order(
                symbol=f"{symbol}USDT",
                side="BUY",
                type="MARKET",
                quantity=real_qty
            )
            fill_sum = 0.0
            fill_qty = 0.0
            for fill in order.get("fills", []):
                fxp  = float(fill["price"])
                fxq  = float(fill["qty"])
                fill_sum += fxp*fxq
                fill_qty += fxq
            avg_px = fill_sum/fill_qty if fill_qty>0 else px
            logging.info(f"[BUY] {symbol} => qty={fill_qty}, avg_px={avg_px}")
            return (fill_qty, avg_px)
        except Exception as e:
            logging.error(f"[BUY ERROR] {symbol} => {e}")
            return (0.0, 0.0)
import logging
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
        if asset.upper()=="USDT":
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
        if qty<=0:
            logging.warning(f"[SELL_ALL] qty<=0 => skip {asset}")
            return 0.0
        real_qty= round(qty,5)
        pair= asset.upper()+"USDT"
        try:
            order= self.client.create_order(
                symbol= pair,
                side="SELL",
                type="MARKET",
                quantity= real_qty
            )
            fill_sum=0.0
            fill_qty=0.0
            for fill in order.get("fills", []):
                px= float(fill["price"])
                qf= float(fill["qty"])
                fill_sum+= px*qf
                fill_qty+= qf
            avg_px= fill_sum/fill_qty if fill_qty>0 else 0
            logging.info(f"[SELL_ALL REAL] {pair} qty={real_qty:.5f}, fill_sum={fill_sum:.2f}, avg_px={avg_px:.4f}")
            return fill_sum
        except Exception as e:
            logging.error(f"[SELL_ALL ERROR] {asset} => {e}")
            return 0.0

    def sell_partial(self, asset, qty):
        logging.info(f"[SELL_PARTIAL] {asset}, qty={qty}")
        return self.sell_all(asset, qty)

    def buy(self, asset, usdt_amount):
        pair= asset.upper()+"USDT"
        try:
            px_info= self.client.get_symbol_ticker(symbol=pair)
            px= float(px_info["price"])
            raw_qty= usdt_amount/ px
            real_qty= round(raw_qty,5)
            if real_qty<=0:
                logging.warning(f"[BUY] real_qty<=0 => skip {asset}")
                return (0.0,0.0)
            order= self.client.create_order(
                symbol= pair,
                side="BUY",
                type="MARKET",
                quantity= real_qty
            )
            fill_sum=0.0
            fill_qty=0.0
            for fill in order.get("fills", []):
                fxp= float(fill["price"])
                fxq= float(fill["qty"])
                fill_sum+= fxp*fxq
                fill_qty+= fxq
            avg_px= fill_sum/fill_qty if fill_qty>0 else px
            logging.info(f"[BUY REAL] {pair} => qty={fill_qty:.5f}, cost={fill_sum:.2f}, avg_px={avg_px:.4f}")
            return (fill_qty, avg_px)
        except Exception as e:
            logging.error(f"[BUY ERROR] {asset} => {e}")
            return (0.0,0.0)

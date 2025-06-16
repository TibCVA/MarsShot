#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import math
import time
import os
import json
from binance.client import Client

TRADE_HISTORY_FILE = "trade_history.json"

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
    side  => "BUY" ou "SELL"
    asset => ex: "BTC"
    qty   => quantité achetée/vendue
    cost  => somme en USDC payée ou reçue
    avg_px=> prix moyen d'exécution
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

class TradeExecutor:
    def __init__(self, api_key, api_secret):
        self.client = Client(api_key, api_secret)
        logging.info("[TradeExecutor] Initialized with given API/Secret")

    def get_symbol_price(self, asset):
        """Retourne le prix de asset/USDC."""
        if asset.upper() == "USDC":
            return 1.0
        pair = asset.upper() + "USDC"
        try:
            tick = self.client.get_symbol_ticker(symbol=pair)
            px = float(tick["price"])
            logging.info(f"[TradeExecutor.get_symbol_price] {pair} => {px}")
            return px
        except Exception as e:
            logging.error(f"[get_symbol_price ERROR] {asset} => {e}")
            return 0.0

    def sell_all(self, asset, qty):
        """
        Vend la totalité du token 'asset' (qty) contre USDC.
        Retourne la somme reçue en USDC.
        """
        if qty <= 0:
            logging.warning(f"[SELL_ALL] qty<=0 => skip {asset}")
            return 0.0
        pair = asset.upper() + "USDC"

        real_qty = self.adjust_quantity_lot_size(pair, qty)
        if real_qty <= 0:
            logging.warning(f"[SELL_ALL] real_qty <= 0 => skip {asset}")
            return 0.0

        try:
            order = self.client.create_order(
                symbol= pair,
                side= "SELL",
                type= "MARKET",
                quantity= real_qty
            )
            fill_sum= 0.0
            fill_qty= 0.0
            for fill in order.get("fills", []):
                px= float(fill["price"])
                qf= float(fill["qty"])
                fill_sum+= px*qf
                fill_qty+= qf

            avg_px= fill_sum/fill_qty if fill_qty>0 else 0.0
            logging.info(f"[SELL_ALL REAL] {pair} qty={real_qty:.8f}, fill_sum={fill_sum:.2f}, avg_px={avg_px:.4f}")

            # Enregistrement
            record_trade("SELL", asset, fill_qty, fill_sum, avg_px)
            return fill_sum
        except Exception as e:
            logging.error(f"[SELL_ALL ERROR] {asset} => {e}")
            return 0.0

    def sell_partial(self, asset, qty):
        """Vend partiellement 'qty' en appelant sell_all (même code)."""
        logging.info(f"[SELL_PARTIAL] {asset}, qty={qty}")
        return self.sell_all(asset, qty)

    def buy(self, asset, USDC_amount):
        """
        Achète 'asset' pour un montant 'USDC_amount' USDC au prix du marché.
        Retourne (fill_qty, avg_px, fill_sum).
        """
        pair = asset.upper() + "USDC"
        try:
            # +++ DÉBUT DES AJOUTS DE LOGS DE DEBUG +++
            logging.info(f"[BUY_DEBUG] Début achat pour {pair} avec {USDC_amount:.2f} USDC.")
            
            px_info = self.client.get_symbol_ticker(symbol=pair)
            px = float(px_info["price"])
            logging.info(f"[BUY_DEBUG] Prix actuel de {pair}: {px}")

            if px <= 0:
                logging.error(f"[BUY ERROR] Le prix de {pair} est nul ou négatif. Achat annulé.")
                return (0.0, 0.0, 0.0)

            raw_qty = USDC_amount / px
            logging.info(f"[BUY_DEBUG] Quantité brute calculée: {raw_qty}")
            
            adj_qty = self.adjust_quantity_lot_size(pair, raw_qty)
            logging.info(f"[BUY_DEBUG] Quantité ajustée: {adj_qty}")

            if adj_qty <= 0:
                logging.warning(f"[BUY] {asset}, qty ajustée ({adj_qty}) trop faible après contraintes (LOT_SIZE, MIN_NOTIONAL). Achat skippé.")
                return (0.0, 0.0, 0.0)

            logging.info(f"[BUY] Passage de l'ordre MARKET pour {adj_qty} {asset}.")
            # +++ FIN DES AJOUTS DE LOGS DE DEBUG +++
            
            order = self.client.create_order(
                symbol= pair,
                side= "BUY",
                type= "MARKET",
                quantity= adj_qty
            )
            fill_sum= 0.0
            fill_qty= 0.0
            for fill in order.get("fills", []):
                fxp= float(fill["price"])
                fxq= float(fill["qty"])
                fill_sum+= fxp*fxq
                fill_qty+= fxq

            avg_px = fill_sum/fill_qty if fill_qty>0 else px
            logging.info(f"[BUY REAL] {pair} => qty={fill_qty:.8f}, cost={fill_sum:.2f}, avg_px={avg_px:.4f}")

            record_trade("BUY", asset, fill_qty, fill_sum, avg_px)
            return (fill_qty, avg_px, fill_sum)

        except Exception as e:
            # +++ MODIFICATION CRUCIALE : LOG DE L'EXCEPTION DÉTAILLÉE +++
            logging.error(f"[BUY ERROR] Exception pour {asset}: {e}", exc_info=True)
            return (0.0, 0.0, 0.0)

    def adjust_quantity_lot_size(self, symbol, raw_qty):
        """
        Ajuste 'raw_qty' pour respecter LOT_SIZE, minQty, minNotional, etc.
        Retourne 0.0 si trop petit.
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
            min_notional= float(min_notional_filter["minNotional"]) if min_notional_filter else 10.0

            # arrondi => floor
            adj_qty = (raw_qty // step_size)* step_size
            if adj_qty < min_qty:
                return 0.0

            # check minNotional
            px_info= self.client.get_symbol_ticker(symbol=symbol)
            px= float(px_info["price"])
            notional= px* adj_qty
            if notional < min_notional:
                return 0.0

            # on force un arrondi final
            return float(f"{adj_qty:.8f}")

        except Exception as e:
            logging.warning(f"[adjust_quantity_lot_size] {symbol} => {e}")
            return 0.0
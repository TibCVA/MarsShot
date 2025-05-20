#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import math # Non utilisé directement, mais pourrait l'être pour des calculs de précision
import time
import os
import json
from binance.client import Client
# Assurez-vous que trade_history est au bon endroit ou ajustez l'import
# Si trade_history.py est dans le même répertoire 'modules'
# from .trade_history import record_trade # Utilisation de l'import relatif si c'est un package
# Si trade_history.py est à la racine et que ce module est dans modules/
# sys.path.append(os.path.join(os.path.dirname(__file__), '..')) # Pourrait être nécessaire
# from trade_history import record_trade
# Pour l'instant, on suppose qu'il est trouvable ou que vous gérez l'import autrement.
# Si trade_history.py est un module séparé, il est préférable de l'importer.
# Si les fonctions sont petites, on peut les intégrer ici.

# Pour simplifier, je vais intégrer la logique de record_trade ici
# car trade_history.py n'a pas été fourni dans les derniers échanges comme fichier à modifier.

TRADE_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trade_history.json") # Suppose à la racine

def load_trade_history():
    if not os.path.exists(TRADE_HISTORY_FILE):
        return []
    try:
        with open(TRADE_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Erreur lecture {TRADE_HISTORY_FILE}: {e}")
        return []

def save_trade_history(trades):
    try:
        with open(TRADE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2)
    except Exception as e:
        logging.error(f"Erreur écriture {TRADE_HISTORY_FILE}: {e}")


def record_trade(side, asset, qty, cost, avg_px):
    """
    Ajoute un enregistrement de trade dans trade_history.json.
    """
    trades = load_trade_history()
    now_ts = time.time()
    # Utiliser datetime pour un format plus standard
    dt_now = datetime.datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S")
    
    new_trade = {
        "timestamp": now_ts,
        "datetime": dt_now,
        "side": str(side).upper(),
        "asset": str(asset).upper(),
        "qty": float(qty),
        "cost_USDC": float(cost), # Renommé pour clarté vs votre version originale
        "avg_px": float(avg_px)
    }
    trades.append(new_trade)
    logging.info(f"Enregistrement du trade: {new_trade}")
    save_trade_history(trades)


class TradeExecutor:
    def __init__(self, api_key, api_secret): # Corrigé __init__
        self.client = Client(api_key, api_secret)
        # Utiliser le logger du module trade_executor si configuré, sinon le logger root
        self.logger = logging.getLogger("trade_executor_logic")
        if not self.logger.hasHandlers(): # Fallback si non configuré par l'appelant
             _h = logging.StreamHandler(sys.stderr); _f = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"); _h.setFormatter(_f)
             self.logger.addHandler(_h); self.logger.setLevel(logging.INFO); self.logger.propagate = False
        self.logger.info("TradeExecutor initialisé avec les clés API fournies.")

    def get_symbol_price(self, asset: str) -> float:
        """Retourne le prix de asset/USDC."""
        if not isinstance(asset, str) or not asset:
            self.logger.error(f"Asset invalide fourni à get_symbol_price: {asset}")
            return 0.0
        asset_upper = asset.upper()
        if asset_upper == "USDC":
            return 1.0
        
        pair = asset_upper + "USDC"
        try:
            tick = self.client.get_symbol_ticker(symbol=pair)
            px = float(tick["price"])
            self.logger.debug(f"Prix pour {pair} => {px}")
            return px
        except BinanceAPIException as e:
            if e.code == -1121: # Invalid symbol
                self.logger.warning(f"get_symbol_price: Paire {pair} invalide sur Binance. Erreur: {e.message}")
            else:
                self.logger.error(f"get_symbol_price Erreur API Binance pour {pair}: {e.message} (code {e.code})")
            return 0.0
        except KeyError:
            self.logger.error(f"get_symbol_price: Clé 'price' manquante dans la réponse du ticker pour {pair}.")
            return 0.0
        except ValueError:
            self.logger.error(f"get_symbol_price: Impossible de convertir le prix en float pour {pair}.")
            return 0.0
        except Exception as e:
            self.logger.error(f"get_symbol_price Erreur inattendue pour {pair}: {e}", exc_info=True)
            return 0.0

    def adjust_quantity_lot_size(self, symbol: str, raw_qty: float) -> float:
        """
        Ajuste 'raw_qty' pour respecter LOT_SIZE, minQty, minNotional de Binance.
        Retourne la quantité ajustée, ou 0.0 si non conforme.
        """
        if raw_qty <= 0: return 0.0
        try:
            info = self.client.get_symbol_info(symbol)
        except Exception as e_info:
            self.logger.error(f"adjust_quantity: Impossible de récupérer les infos pour {symbol}: {e_info}")
            return 0.0 # Impossible d'ajuster sans les règles

        lot_size_filter = next((f for f in info["filters"] if f["filterType"] == "LOT_SIZE"), None)
        min_notional_filter = next((f for f in info["filters"] if f["filterType"] == "MARKET_LOT_SIZE"), # Souvent MARKET_LOT_SIZE pour minNotional sur ordres MARKET
                                   next((f for f in info["filters"] if f["filterType"] == "MIN_NOTIONAL"), None))
        
        if not lot_size_filter:
            self.logger.warning(f"Filtre LOT_SIZE non trouvé pour {symbol}. Utilisation de raw_qty.")
            # Sans LOT_SIZE, on ne peut pas garantir la conformité. On pourrait retourner 0 ou raw_qty.
            # Pour l'instant, on continue, mais c'est risqué.
            step_size = 1e-8 # Plus petite précision possible
            min_qty = 1e-8
        else:
            step_size = float(lot_size_filter["stepSize"])
            min_qty   = float(lot_size_filter["minQty"])
        
        # Ajuster à la précision de step_size (arrondi inférieur)
        # Exemple: raw_qty = 12.345, step_size = 0.01 => (12.345 // 0.01) * 0.01 = 1234.0 * 0.01 = 12.34
        if step_size > 0:
            adj_qty = math.floor(raw_qty / step_size) * step_size
        else: # step_size est 0, ce qui ne devrait pas arriver
            adj_qty = raw_qty 
            self.logger.warning(f"step_size est 0 pour {symbol}. Utilisation de raw_qty.")

        # Formater avec une précision suffisante pour éviter les problèmes de float
        # 8 décimales est commun pour les cryptos.
        adj_qty = float(f"{adj_qty:.8f}")


        if adj_qty < min_qty:
            self.logger.warning(f"adjust_quantity: {symbol}, Qty ajustée {adj_qty} < minQty {min_qty}. Retour 0.")
            return 0.0

        # Vérifier MIN_NOTIONAL si le filtre existe
        if min_notional_filter:
            min_notional_val = float(min_notional_filter.get("minNotional", 0.0)) # .get car la clé peut varier
            if min_notional_val > 0:
                current_price = self.get_symbol_price(symbol[:-4] if symbol.endswith("USDC") else symbol) # Obtenir le prix du base asset
                if current_price <= 0:
                    self.logger.warning(f"adjust_quantity: {symbol}, Prix actuel non disponible pour vérifier minNotional. Ordre risqué.")
                    # On pourrait retourner 0 ici pour être sûr, ou laisser passer.
                else:
                    notional_value = current_price * adj_qty
                    if notional_value < min_notional_val:
                        self.logger.warning(f"adjust_quantity: {symbol}, Valeur notionnelle {notional_value:.2f} < minNotional {min_notional_val:.2f}. Retour 0.")
                        return 0.0
        
        self.logger.debug(f"adjust_quantity: {symbol}, Raw Qty: {raw_qty:.8f} -> Adjusted Qty: {adj_qty:.8f}")
        return adj_qty

    def sell_all(self, asset: str, qty: float):
        if qty <= 0:
            self.logger.warning(f"SELL_ALL: Quantité <= 0 pour {asset}. Skip.")
            return 0.0
        
        pair = asset.upper() + "USDC"
        self.logger.info(f"SELL_ALL: Tentative de vente de {qty} {asset} sur la paire {pair}.")

        adjusted_qty = self.adjust_quantity_lot_size(pair, qty)
        if adjusted_qty <= 0:
            self.logger.warning(f"SELL_ALL: Quantité ajustée pour {pair} est {adjusted_qty} (depuis {qty}). Vente annulée.")
            return 0.0

        try:
            self.logger.info(f"SELL_ALL: Exécution de l'ordre MARKET SELL pour {adjusted_qty} {pair}.")
            order = self.client.create_order(
                symbol=pair,
                side=Client.SIDE_SELL,
                type=Client.ORDER_TYPE_MARKET,
                quantity=adjusted_qty
            )
            self.logger.info(f"SELL_ALL: Ordre de vente pour {pair} placé: {order.get('orderId')}")
            
            # Calculer la valeur totale vendue et le prix moyen à partir des fills
            total_cost_usdc = 0.0
            total_qty_filled = 0.0
            avg_price = 0.0

            if 'fills' in order and order['fills']:
                for fill in order['fills']:
                    price = float(fill['price'])
                    quantity = float(fill['qty'])
                    total_cost_usdc += price * quantity
                    total_qty_filled += quantity
                if total_qty_filled > 0:
                    avg_price = total_cost_usdc / total_qty_filled
            else: # Fallback si pas de fills (rare pour MARKET order mais possible)
                # Tenter de récupérer le prix moyen via un autre endpoint ou estimer
                # Pour l'instant, on logge et on utilise le prix au moment de l'ordre si possible
                self.logger.warning(f"SELL_ALL: Pas de 'fills' dans la réponse de l'ordre pour {pair}. Valeur vendue pourrait être imprécise.")
                # On pourrait essayer de récupérer le prix via get_symbol_price juste après, mais il peut avoir changé.
                # Pour l'instant, on se base sur ce qu'on a.
                if 'price' in order: # Certains ordres MARKET peuvent retourner un prix moyen
                     avg_price = float(order['price'])
                     total_cost_usdc = avg_price * total_qty_filled # total_qty_filled vient de order['executedQty']
                     total_qty_filled = float(order.get('executedQty', 0.0))


            self.logger.info(f"SELL_ALL RÉUSSI: {total_qty_filled:.8f} {asset} vendus pour ~{total_cost_usdc:.2f} USDC @ ~{avg_price:.4f} sur {pair}.")
            record_trade("SELL", asset, total_qty_filled, total_cost_usdc, avg_price)
            return total_cost_usdc
            
        except BinanceAPIException as e:
            self.logger.error(f"SELL_ALL Erreur API Binance pour {pair}: {e.message} (code {e.code})", exc_info=True)
        except Exception as e:
            self.logger.error(f"SELL_ALL Erreur inattendue pour {pair}: {e}", exc_info=True)
        return 0.0 # Échec

    def sell_partial(self, asset: str, qty_to_sell: float):
        self.logger.info(f"SELL_PARTIAL: Demande de vente de {qty_to_sell} {asset}.")
        # La logique de sell_all gère déjà l'ajustement de quantité et l'enregistrement.
        return self.sell_all(asset, qty_to_sell)

    def buy(self, asset: str, usdc_amount_to_spend: float):
        pair = asset.upper() + "USDC"
        self.logger.info(f"BUY: Tentative d'achat de {asset} avec ~{usdc_amount_to_spend:.2f} USDC sur {pair}.")

        if usdc_amount_to_spend < 5.0: # Seuil minimal pour un trade (Binance est souvent 10 USDT/USDC)
            self.logger.warning(f"BUY: Montant USDC ({usdc_amount_to_spend:.2f}) trop faible pour {pair}. Skip.")
            return 0.0, 0.0, 0.0

        try:
            # Pour un ordre MARKET avec quoteOrderQty, Binance s'occupe de la quantité de base asset.
            # Cependant, python-binance ne supporte pas toujours quoteOrderQty pour tous les types d'ordres MARKET.
            # On va donc calculer la quantité, l'ajuster, puis passer un ordre quantity.
            
            current_price = self.get_symbol_price(asset)
            if current_price <= 0:
                self.logger.error(f"BUY: Prix invalide ou nul ({current_price}) pour {asset}. Achat annulé.")
                return 0.0, 0.0, 0.0
            
            raw_base_qty = usdc_amount_to_spend / current_price
            adjusted_base_qty = self.adjust_quantity_lot_size(pair, raw_base_qty)

            if adjusted_base_qty <= 0:
                self.logger.warning(f"BUY: Quantité ajustée pour {pair} est {adjusted_base_qty} (depuis {raw_base_qty} pour {usdc_amount_to_spend:.2f} USDC). Achat annulé.")
                return 0.0, 0.0, 0.0

            self.logger.info(f"BUY: Exécution de l'ordre MARKET BUY pour {adjusted_base_qty} {pair}.")
            order = self.client.create_order(
                symbol=pair,
                side=Client.SIDE_BUY,
                type=Client.ORDER_TYPE_MARKET,
                quantity=adjusted_base_qty
                # Si quoteOrderQty était supporté et préféré:
                # type=Client.ORDER_TYPE_MARKET,
                # quoteOrderQty=usdc_amount_to_spend 
            )
            self.logger.info(f"BUY: Ordre d'achat pour {pair} placé: {order.get('orderId')}")

            total_cost_usdc = 0.0
            total_qty_filled = 0.0
            avg_price = 0.0

            if 'fills' in order and order['fills']:
                for fill in order['fills']:
                    price = float(fill['price'])
                    quantity = float(fill['qty'])
                    commission = float(fill.get('commission', 0.0))
                    commission_asset = fill.get('commissionAsset', '')

                    total_cost_usdc += price * quantity # Le coût brut
                    total_qty_filled += quantity
                    # Gérer la commission si elle est dans l'asset acheté (pour BUY)
                    # Si la commission est en BNB ou USDC, le coût est déjà bon.
                    # Si la commission est dans l'asset acheté, la quantité reçue est moindre.
                    # if commission_asset == asset.upper():
                    #    total_qty_filled -= commission # Réduire la quantité reçue
                if total_qty_filled > 0:
                    avg_price = total_cost_usdc / total_qty_filled
            else:
                self.logger.warning(f"BUY: Pas de 'fills' dans la réponse de l'ordre pour {pair}. Valeurs pourraient être imprécises.")
                # Fallback
                total_qty_filled = float(order.get('executedQty', 0.0))
                if total_qty_filled > 0:
                    if 'cummulativeQuoteQty' in order: # Binance retourne souvent ça pour les ordres MARKET
                        total_cost_usdc = float(order['cummulativeQuoteQty'])
                        avg_price = total_cost_usdc / total_qty_filled
                    elif 'price' in order : # Moins précis
                        avg_price = float(order['price'])
                        total_cost_usdc = avg_price * total_qty_filled


            self.logger.info(f"BUY RÉUSSI: {total_qty_filled:.8f} {asset} achetés pour ~{total_cost_usdc:.2f} USDC @ ~{avg_price:.4f} sur {pair}.")
            record_trade("BUY", asset, total_qty_filled, total_cost_usdc, avg_price)
            return total_qty_filled, avg_price, total_cost_usdc

        except BinanceAPIException as e:
            self.logger.error(f"BUY Erreur API Binance pour {pair}: {e.message} (code {e.code})", exc_info=True)
        except Exception as e:
            self.logger.error(f"BUY Erreur inattendue pour {pair}: {e}", exc_info=True)
        return 0.0, 0.0, 0.0 # Échec

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
auto_select_tokens.py
---------------------
Sélectionne automatiquement les 60 meilleurs tokens "moonshot"
basés sur leur performance intraday et momentum,
**uniquement** pour les paires Spot en USDC tradables sur Binance.
Met à jour la clé 'extended_tokens_daily' dans config.yaml.
"""

import os
import yaml
import logging
import time
import sys # Pour sys.exit en cas d'erreur critique

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException
except ImportError:
    # Ce print est pour le cas où le script est lancé manuellement sans logging configuré
    print("ERREUR: Le module python-binance est manquant. Installez-le avec 'pip install python-binance'")
    # Si logging est déjà configuré (par ex. si importé), cela sera loggué aussi.
    if logging.getLogger().hasHandlers():
        logging.critical("Le module python-binance est manquant.")
    sys.exit(1)


# Configuration du logging de base si le script est exécuté seul
if not logging.getLogger().hasHandlers():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)] # Log vers stdout pour subprocess
    )

# Définir le chemin absolu vers config.yaml
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.yaml")


def fetch_USDC_spot_pairs(client):
    # ... (fonction inchangée, elle est correcte) ...
    try:
        info = client.get_exchange_info()
    except BinanceAPIException as e:
        logging.error(f"[fetch_USDC_spot_pairs] Erreur get_exchange_info: {e}")
        return []
    except requests.exceptions.RequestException as e: # Ajout pour les erreurs réseau
        logging.error(f"[fetch_USDC_spot_pairs] Erreur réseau lors de get_exchange_info: {e}")
        return []


    usdc_pairs = []
    for s in info.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        if s.get("quoteAsset") != "USDC":
            continue
        if "SPOT" not in s.get("permissions", []):
            continue
        base = s.get("baseAsset", "")
        if any(tag in base for tag in ["UP", "DOWN", "BULL", "BEAR"]): # Effet de levier
            continue
        if base in {"USDC", "BUSD", "TUSD", "USDT", "FDUSD", "DAI", "PAX", "GUSD", "PYUSD"}: # Stablecoins
            continue
        symbol = s.get("symbol", "")
        if symbol.endswith("USDC"):
            usdc_pairs.append(symbol)
    return sorted(list(set(usdc_pairs)))


def get_24h_change(client, symbol):
    # ... (fonction inchangée, elle est correcte) ...
    try:
        tick = client.get_ticker(symbol=symbol)
        return float(tick.get("priceChangePercent", 0)) / 100.0
    except Exception as e:
        logging.warning(f"[get_24h_change] {symbol} => {e}")
        return 0.0

def get_kline_change(client, symbol, days=7):
    # ... (fonction inchangée, elle est correcte) ...
    limit = days + 1 # Besoin de 'days+1' points pour avoir 'days' intervalles
    try:
        klines = client.get_klines(
            symbol=symbol,
            interval=Client.KLINE_INTERVAL_1DAY,
            limit=limit
        )
        # S'assurer qu'on a assez de klines pour la période demandée
        # klines[-1] est la kline actuelle (peut-être pas clôturée)
        # klines[-limit] est la kline 'days' jours avant la kline actuelle
        if len(klines) < limit : # Ex: pour 7 jours, on a besoin de 8 klines pour comparer kline[0] et kline[7]
            logging.debug(f"[get_kline_change] {symbol}, days={days}: Données klines insuffisantes ({len(klines)}/{limit}).")
            return 0.0
        
        # Utiliser l'avant-dernière kline comme "last_close" si la dernière n'est pas encore finie.
        # Pour la simplicité, on prend la dernière disponible.
        last_close = float(klines[-1][4]) # Clôture de la kline la plus récente
        old_close  = float(klines[-limit][4]) # Clôture de la kline 'days' jours avant

        if old_close <= 0:
            return 0.0
        return (last_close - old_close) / old_close
    except BinanceAPIException as e:
        if e.code == -1003: # Rate limit
            logging.warning(f"[get_kline_change] Rate limit atteint pour {symbol}. Pause de 60s.")
            time.sleep(60)
            return get_kline_change(client, symbol, days) # Réessayer une fois
        logging.warning(f"[get_kline_change] {symbol}, days={days} => API Error: {e}")
        return 0.0
    except Exception as e:
        logging.warning(f"[get_kline_change] {symbol}, days={days} => Erreur inattendue: {e}")
        return 0.0


def compute_token_score(p24, p7, p30):
    # ... (fonction inchangée, elle est correcte) ...
    return 0.8 * p7 + 0.0 * p30 + 0.2 * p24


def select_top_tokens(client, top_n=60):
    usdc_pairs = fetch_USDC_spot_pairs(client)
    if not usdc_pairs:
        logging.warning("[select_top_tokens] Aucune paire USDC spot n'a été trouvée sur Binance.")
        return []
        
    logging.info(f"[select_top_tokens] {len(usdc_pairs)} paires USDC spot détectées pour scoring.")

    scored_tokens = []
    for idx, pair_symbol in enumerate(usdc_pairs, start=1):
        if idx > 0 and idx % 30 == 0: # Réduire la fréquence des pauses si nécessaire
            logging.debug(f"[select_top_tokens] Pause de 1s après {idx} tokens traités...")
            time.sleep(1)

        p24  = get_24h_change(client, pair_symbol)
        p7   = get_kline_change(client, pair_symbol, days=7)
        p30  = get_kline_change(client, pair_symbol, days=30) # p30 n'est pas utilisé dans le score mais calculé
        
        score = compute_token_score(p24, p7, p30)
        
        # On ne garde que les tokens avec un score positif pour éviter les erreurs ou les perfs négatives
        if score > 0:
             scored_tokens.append({"symbol": pair_symbol[:-4], "score": score, "p7": p7, "p24": p24}) # Stocker base asset
        else:
            logging.debug(f"[select_top_tokens] {pair_symbol[:-4]} a un score non positif ({score:.4f}) et est ignoré.")


    if not scored_tokens:
        logging.warning("[select_top_tokens] Aucun token n'a obtenu un score positif.")
        return []

    scored_tokens.sort(key=lambda x: x["score"], reverse=True)
    
    logging.info(f"[select_top_tokens] Top 5 tokens scorés (avant sélection de top_n):")
    for i, item in enumerate(scored_tokens[:5]):
        logging.info(f"  {i+1}. {item['symbol']}: Score={item['score']:.4f} (P7={item['p7']:.2%}, P24={item['p24']:.2%})")

    top_n_selected = scored_tokens[:top_n]
    return [item["symbol"] for item in top_n_selected]


def update_config_with_new_tokens(config_path, new_tokens_list):
    """
    Met à jour la clé 'extended_tokens_daily' dans le fichier config.yaml spécifié.
    Préserve les commentaires et la structure autant que possible avec ruamel.yaml si disponible,
    sinon utilise PyYAML standard.
    """
    if not os.path.isfile(config_path):
        logging.error(f"[update_config] Fichier de configuration introuvable: {config_path}")
        return False

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            # Utiliser ruamel.yaml pour préserver les commentaires si disponible
            try:
                import ruamel.yaml
                yaml_parser = ruamel.yaml.YAML()
                yaml_parser.preserve_quotes = True
                config_data = yaml_parser.load(f)
                use_ruamel = True
            except ImportError:
                config_data = yaml.safe_load(f)
                use_ruamel = False
        
        if not isinstance(config_data, dict):
            logging.error(f"[update_config] Le contenu de {config_path} n'est pas un dictionnaire YAML valide.")
            return False

        logging.info(f"[update_config] Ancienne liste 'extended_tokens_daily' (si existante): {config_data.get('extended_tokens_daily', 'Non présente')}")
        config_data["extended_tokens_daily"] = new_tokens_list # Écrase ou ajoute la clé
        logging.info(f"[update_config] Nouvelle liste 'extended_tokens_daily' ({len(new_tokens_list)} tokens): {new_tokens_list[:10] if new_tokens_list else '[]'}...")

        with open(config_path, "w", encoding="utf-8") as f:
            if use_ruamel:
                yaml_parser.dump(config_data, f)
            else:
                yaml.dump(config_data, f, sort_keys=False, allow_unicode=True)
        
        logging.info(f"[update_config] {config_path} mis à jour avec succès avec {len(new_tokens_list)} tokens dans 'extended_tokens_daily'.")
        return True
    except Exception as e:
        logging.error(f"[update_config] Erreur lors de la mise à jour de {config_path}: {e}", exc_info=True)
        return False


def main():
    logging.info("=== Démarrage de auto_select_tokens.py ===")
    
    if not os.path.isfile(CONFIG_FILE_PATH):
        logging.critical(f"Fichier de configuration principal introuvable: {CONFIG_FILE_PATH}. Arrêt.")
        sys.exit(1)

    try:
        with open(CONFIG_FILE_PATH, "r") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logging.critical(f"Impossible de lire ou parser {CONFIG_FILE_PATH}: {e}. Arrêt.")
        sys.exit(1)

    binance_api_cfg = config.get("binance_api", {})
    api_key = binance_api_cfg.get("api_key")
    api_secret = binance_api_cfg.get("api_secret")

    if not api_key or not api_secret:
        logging.critical("Clés API Binance manquantes dans config.yaml. Arrêt.")
        sys.exit(1)

    try:
        client = Client(api_key, api_secret)
        client.ping() # Vérifier la connexion et l'authentification
        logging.info("Client Binance initialisé et connexion vérifiée.")
    except Exception as e:
        logging.critical(f"Erreur d'initialisation du client Binance: {e}. Arrêt.")
        sys.exit(1)
    
    top_n_to_select = config.get("strategy", {}).get("auto_select_top_n", 60) # Rendre configurable
    logging.info(f"Sélection des {top_n_to_select} meilleurs tokens...")
    
    best_tokens_bases = select_top_tokens(client, top_n=top_n_to_select)
    
    if best_tokens_bases:
        logging.info(f"[AUTO] Sélection finale des {len(best_tokens_bases)} meilleurs tokens (base assets): {best_tokens_bases[:10] if best_tokens_bases else '[]'}...")
        if update_config_with_new_tokens(CONFIG_FILE_PATH, best_tokens_bases):
            print(f"[OK] {CONFIG_FILE_PATH} mis à jour avec {len(best_tokens_bases)} tokens dans extended_tokens_daily.") # Pour subprocess stdout
        else:
            print(f"[ERREUR] Échec de la mise à jour de {CONFIG_FILE_PATH}.")
            sys.exit(1) # Sortir avec un code d'erreur si la mise à jour échoue
    else:
        logging.warning("[AUTO] Aucun token n'a été sélectionné. config.yaml ne sera pas modifié pour 'extended_tokens_daily'.")
        print("[WARN] Aucun token sélectionné par auto_select_tokens.py.")
        # Optionnel: décider si on doit vider extended_tokens_daily dans config ou le laisser tel quel.
        # Pour l'instant, on ne le modifie pas si aucun token n'est sélectionné.
        # update_config_with_new_tokens(CONFIG_FILE_PATH, []) # Décommenter pour vider la liste

    logging.info("=== auto_select_tokens.py terminé ===")

if __name__ == "__main__":
    main()

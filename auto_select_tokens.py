#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
auto_select_tokens.py (Module Version)
---------------------
Fonctions pour sélectionner automatiquement les N meilleurs tokens.
La fonction principale `select_and_update_config` prend un client Binance
et met à jour config.yaml ET retourne la liste des tokens.
"""

import os
import yaml
import logging
import time
import sys
import traceback
import json

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException
    import requests
except ImportError as e:
    # Ce print est pour le cas où le script est lancé manuellement sans logging configuré
    print(f"ERREUR CRITIQUE auto_select_tokens.py: Module manquant: {e}. Installez les dépendances (ex: pip install python-binance requests PyYAML).")
    # Tenter de logger même si la config de logging principale n'est pas encore faite
    logging.basicConfig(level=logging.CRITICAL) # Minimal logging
    logging.critical(f"Module manquant pour auto_select_tokens.py: {e}.")
    sys.exit(1)


logger = logging.getLogger("auto_select_module") # Logger spécifique
if not logger.hasHandlers():
    _handler = logging.StreamHandler(sys.stderr) # Logs sur stderr
    _formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s")
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)
    logger.propagate = False 
    logger.setLevel(logging.INFO)

try:
    PROJECT_ROOT_AUTO = os.path.dirname(os.path.abspath(__file__))
    CONFIG_FILE_PATH_AUTO = os.path.join(PROJECT_ROOT_AUTO, "config.yaml")
except NameError: 
    PROJECT_ROOT_AUTO = os.getcwd()
    CONFIG_FILE_PATH_AUTO = os.path.join(PROJECT_ROOT_AUTO, "config.yaml")
    logger.warning(f"__file__ non défini dans auto_select_tokens, CWD utilisé: {PROJECT_ROOT_AUTO}")


def fetch_USDC_spot_pairs(client: Client):
    logger.info("Récupération des paires USDC spot sur Binance...")
    try:
        info = client.get_exchange_info()
    except BinanceAPIException as e:
        logger.error(f"Erreur API Binance lors de get_exchange_info: {e}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur réseau lors de get_exchange_info: {e}")
        return []
    except Exception as e:
        logger.error(f"Erreur inattendue lors de get_exchange_info: {e}", exc_info=True)
        return []

    usdc_pairs = []
    symbols_data = info.get("symbols", [])
    if not symbols_data:
        logger.warning("Aucun symbole retourné par get_exchange_info.")
        return []

    for s in symbols_data:
        if s.get("status") == "TRADING" and \
           s.get("quoteAsset") == "USDC" and \
           "SPOT" in s.get("permissions", []):
            base = s.get("baseAsset", "")
            if any(tag in base for tag in ["UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S", "EDGE", "HALF", "LEVERAGED"]):
                continue
            if base in {"USDC", "BUSD", "TUSD", "USDT", "FDUSD", "USDP", "DAI", "PAX", "GUSD", "PYUSD", "EURC", "AEUR"}:
                continue
            symbol = s.get("symbol", "")
            if symbol.endswith("USDC"):
                usdc_pairs.append(symbol)
                
    unique_usdc_pairs = sorted(list(set(usdc_pairs)))
    logger.info(f"{len(unique_usdc_pairs)} paires USDC spot uniques et tradables trouvées après filtrage.")
    return unique_usdc_pairs


def get_24h_change(client: Client, symbol: str):
    try:
        tick = client.get_ticker(symbol=symbol)
        pc_str = tick.get("priceChangePercent")
        if pc_str is None:
            logger.warning(f"[get_24h_change] {symbol}: 'priceChangePercent' manquant.")
            return 0.0
        return float(pc_str) / 100.0
    except ValueError:
        logger.warning(f"[get_24h_change] {symbol}: Impossible de convertir '{pc_str}' en float.")
        return 0.0
    except BinanceAPIException as e:
        logger.warning(f"[get_24h_change] {symbol} => API Error: {e.status_code} - {e.message}")
        return 0.0
    except Exception as e:
        logger.warning(f"[get_24h_change] {symbol} => Erreur: {e}", exc_info=False)
        return 0.0

def get_kline_change(client: Client, symbol: str, days=7):
    limit = days + 1 
    retry_count = 0
    max_retries = 1 

    while retry_count <= max_retries:
        try:
            klines = client.get_klines(
                symbol=symbol,
                interval=Client.KLINE_INTERVAL_1DAY,
                limit=limit
            )
            if len(klines) < limit :
                logger.debug(f"[get_kline_change] {symbol}, days={days}: Données klines insuffisantes ({len(klines)}/{limit}).")
                return 0.0
            
            last_close = float(klines[-1][4]) 
            old_close  = float(klines[-limit][4])

            if old_close == 0: 
                logger.warning(f"[get_kline_change] {symbol}, days={days}: Ancien prix de clôture est 0.")
                return 0.0
            return (last_close - old_close) / old_close
        except BinanceAPIException as e:
            if e.code == -1003 and retry_count < max_retries: 
                retry_count += 1
                wait_time = 30 * retry_count 
                logger.warning(f"[get_kline_change] Rate limit pour {symbol}. Tentative {retry_count}/{max_retries} après {wait_time}s.")
                time.sleep(wait_time)
                continue 
            logger.warning(f"[get_kline_change] {symbol}, days={days} => API Error: {e.status_code} - {e.message}")
            return 0.0
        except Exception as e:
            logger.warning(f"[get_kline_change] {symbol}, days={days} => Erreur inattendue: {e}", exc_info=False)
            return 0.0
    logger.warning(f"[get_kline_change] {symbol}, days={days}: Échec après {max_retries} nouvelles tentatives.")
    return 0.0

def compute_token_score(p24, p7, p30):
    return 0.8 * p7 + 0.0 * p30 + 0.2 * p24

def select_top_tokens(client: Client, top_n=60):
    usdc_pairs = fetch_USDC_spot_pairs(client)
    if not usdc_pairs:
        logger.warning("[select_top_tokens] Aucune paire USDC spot trouvée. Retour d'une liste vide.")
        return []
        
    logger.info(f"[select_top_tokens] {len(usdc_pairs)} paires USDC spot trouvées. Calcul des scores...")

    scored_tokens = []
    processed_count = 0
    for idx, pair_symbol in enumerate(usdc_pairs):
        if idx > 0 and idx % 20 == 0: 
            logger.debug(f"[select_top_tokens] Pause de 1s après {idx} tokens...")
            time.sleep(1)

        base_asset = pair_symbol[:-4] if pair_symbol.endswith("USDC") else pair_symbol
        logger.debug(f"Traitement de {base_asset} ({idx+1}/{len(usdc_pairs)})...")

        p24 = get_24h_change(client, pair_symbol)
        p7  = get_kline_change(client, pair_symbol, days=7)
        p30 = get_kline_change(client, pair_symbol, days=30)
        
        score = compute_token_score(p24, p7, p30)
        
        if score > 0.0001: 
             scored_tokens.append({"symbol": base_asset, "score": score, "p7": p7, "p24": p24})
             logger.debug(f"Token {base_asset}: p24={p24:.4f}, p7={p7:.4f}, p30={p30:.4f}, Score={score:.4f} -> Conservé")
        else:
            logger.debug(f"Token {base_asset}: Score={score:.4f} -> Ignoré (score trop bas)")
        processed_count +=1

    logger.info(f"{processed_count}/{len(usdc_pairs)} tokens traités pour le scoring. {len(scored_tokens)} ont un score suffisant.")

    if not scored_tokens:
        logger.warning("[select_top_tokens] Aucun token n'a obtenu un score suffisant après évaluation.")
        return []

    scored_tokens.sort(key=lambda x: x["score"], reverse=True)
    
    logger.info(f"[select_top_tokens] Top 5 tokens scorés (parmi {len(scored_tokens)} tokens avec score > 0):")
    for i, item in enumerate(scored_tokens[:5]):
        logger.info(f"  {i+1}. {item['symbol']}: Score={item['score']:.4f} (P7={item['p7']:.2%}, P24={item['p24']:.2%})")

    top_n_selected_items = scored_tokens[:top_n]
    final_list = [item["symbol"] for item in top_n_selected_items]
    logger.info(f"Sélection finale de {len(final_list)} tokens (objectif top_n={top_n}).")
    return final_list


def update_config_file(config_file_path, new_tokens_list):
    logger.info(f"Tentative de mise à jour de {config_file_path} avec {len(new_tokens_list)} tokens.")
    if not os.path.isfile(config_file_path):
        logger.error(f"Fichier de configuration introuvable: {config_file_path}")
        return False
    try:
        try:
            import ruamel.yaml
            yaml_parser = ruamel.yaml.YAML()
            yaml_parser.indent(mapping=2, sequence=4, offset=2)
            yaml_parser.preserve_quotes = True
            with open(config_file_path, "r", encoding="utf-8") as f:
                config_data = yaml_parser.load(f)
            use_ruamel = True
            logger.debug("Utilisation de ruamel.yaml pour lire/écrire config.")
        except ImportError:
            logger.debug("ruamel.yaml non trouvé, utilisation de PyYAML standard.")
            with open(config_file_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
            use_ruamel = False
        
        if not isinstance(config_data, dict):
            logger.error(f"Le contenu de {config_file_path} n'est pas un dictionnaire YAML valide.")
            return False

        old_list_len = len(config_data.get("extended_tokens_daily", []))
        config_data["extended_tokens_daily"] = new_tokens_list
        
        with open(config_file_path, "w", encoding="utf-8") as f:
            if use_ruamel:
                yaml_parser.dump(config_data, f)
            else:
                yaml.dump(config_data, f, sort_keys=False, allow_unicode=True, default_flow_style=None)
        
        logger.info(f"{config_file_path} mis à jour. 'extended_tokens_daily': {old_list_len} -> {len(new_tokens_list)} tokens.")
        return True
    except Exception as e:
        logger.error(f"Erreur lors de la lecture/écriture de {config_file_path}: {e}\n{traceback.format_exc()}")
        return False

# Fonction principale exportée pour être appelée par main.py
def select_and_write_tokens(binance_client_instance: Client, config_path: str, num_top_tokens: int):
    logger.info(f"Début de select_and_write_tokens. Objectif: top {num_top_tokens} tokens. Config: {config_path}")
    if not binance_client_instance:
        logger.error("Instance du client Binance non fournie à select_and_write_tokens.")
        return [] 
    
    best_tokens = select_top_tokens(binance_client_instance, top_n=num_top_tokens)

    # Toujours tenter de mettre à jour config.yaml, même si best_tokens est vide
    # pour s'assurer que extended_tokens_daily reflète la dernière sélection (ou son absence)
    list_to_write = best_tokens if best_tokens else []
    if update_config_file(config_path, list_to_write):
        logger.info(f"{config_path} mis à jour avec {len(list_to_write)} tokens dans 'extended_tokens_daily'.")
    else:
        logger.error(f"Échec de la mise à jour de {config_path} avec les tokens sélectionnés.")
        # En cas d'échec d'écriture, on retourne quand même les tokens trouvés,
        # mais main.py pourrait décider d'utiliser une liste de secours.
            
    return list_to_write


if __name__ == "__main__":
    # Ce bloc est pour l'exécution directe du script (par exemple, pour des tests ou via cron)
    logger.info("auto_select_tokens.py exécuté directement (__name__ == '__main__').")
    
    if not os.path.isfile(CONFIG_FILE_PATH_AUTO):
        logger.critical(f"Fichier de configuration principal introuvable: {CONFIG_FILE_PATH_AUTO}. Arrêt.")
        # Imprimer un JSON d'erreur pour la capture par subprocess si c'est le cas
        print(f"JSON_OUTPUT: {json.dumps({'status': 'error', 'message': f'{CONFIG_FILE_PATH_AUTO} introuvable', 'tokens': []})}")
        sys.stdout.flush()
        sys.exit(1)

    try:
        with open(CONFIG_FILE_PATH_AUTO, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.critical(f"Impossible de lire ou parser {CONFIG_FILE_PATH_AUTO}: {e}. Arrêt.")
        print(f"JSON_OUTPUT: {json.dumps({'status': 'error', 'message': f'Lecture/Parsing {CONFIG_FILE_PATH_AUTO} échoué', 'tokens': []})}")
        sys.stdout.flush()
        sys.exit(1)

    binance_api_cfg = config.get("binance_api", {})
    api_key = binance_api_cfg.get("api_key")
    api_secret = binance_api_cfg.get("api_secret")

    if not api_key or not api_secret:
        logger.critical("Clés API Binance manquantes dans config.yaml. Arrêt.")
        print(f"JSON_OUTPUT: {json.dumps({'status': 'error', 'message': 'Clés API Binance manquantes', 'tokens': []})}")
        sys.stdout.flush()
        sys.exit(1)

    client_instance = None
    try:
        client_instance = Client(api_key, api_secret)
        client_instance.ping() 
        logger.info("Client Binance initialisé pour exécution directe.")
    except Exception as e:
        logger.critical(f"Erreur d'initialisation du client Binance: {e}. Arrêt.")
        print(f"JSON_OUTPUT: {json.dumps({'status': 'error', 'message': f'Init client Binance échouée: {e}', 'tokens': []})}")
        sys.stdout.flush()
        sys.exit(1)
    
    top_n = config.get("strategy", {}).get("auto_select_top_n", 60)
    if not isinstance(top_n, int) or top_n <=0: top_n = 60
    
    # Appel de la fonction principale du module
    selected_tokens_list = select_and_write_tokens(client_instance, CONFIG_FILE_PATH_AUTO, top_n)
    
    # Préparer la sortie JSON pour stdout
    output_payload = {
        "status": "ok", # Supposer ok, sera modifié si l'écriture config échoue
        "message": "",
        "tokens_selected_count": len(selected_tokens_list),
        "tokens": selected_tokens_list
    }

    # Vérifier si config.yaml a bien été mis à jour (la fonction select_and_write_tokens le fait)
    # Ici, on se fie au fait que select_and_write_tokens a loggué les erreurs d'écriture.
    # Le message sera basé sur le nombre de tokens.
    if selected_tokens_list:
        output_payload["message"] = f"{os.path.basename(CONFIG_FILE_PATH_AUTO)} devrait être à jour avec {len(selected_tokens_list)} tokens."
    else:
        output_payload["message"] = f"Aucun token sélectionné. {os.path.basename(CONFIG_FILE_PATH_AUTO)} devrait contenir une liste vide pour extended_tokens_daily."
        # Si la liste est vide mais que update_config_file a échoué, ce serait un problème.
        # select_and_write_tokens logue déjà cet échec.

    print(f"JSON_OUTPUT: {json.dumps(output_payload)}")
    sys.stdout.flush()
    
    logger.info(f"auto_select_tokens.py (exécution directe) terminé. {output_payload['message']}")
    sys.exit(0) # Toujours sortir avec 0 si on arrive ici, les erreurs critiques sont gérées avant.

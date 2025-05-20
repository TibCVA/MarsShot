#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
auto_select_tokens.py
---------------------
Sélectionne automatiquement les N meilleurs tokens (configurable, défaut 60)
basés sur leur performance, pour les paires Spot en USDC tradables sur Binance.
Met à jour la clé 'extended_tokens_daily' dans config.yaml ET
IMPRIME la liste des tokens sélectionnés en JSON sur stdout pour capture.
"""

import os
import yaml
import logging
import time
import sys
import traceback
import json # Pour la sortie JSON

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException
    import requests
except ImportError as e:
    print(f"ERREUR CRITIQUE auto_select_tokens.py: Module manquant: {e}. Installez les dépendances.")
    logging.basicConfig(level=logging.CRITICAL)
    logging.critical(f"Module manquant pour auto_select_tokens.py: {e}.")
    sys.exit(1)

logger = logging.getLogger("auto_select_tokens")
if not logger.hasHandlers():
    handler = logging.StreamHandler(sys.stderr) # Logs sur stderr
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.INFO)

try:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.yaml")
except NameError:
    PROJECT_ROOT = os.getcwd()
    CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.yaml")
    logger.warning(f"__file__ non défini, utilisation de CWD pour PROJECT_ROOT: {PROJECT_ROOT}")

# --- Les fonctions fetch_USDC_spot_pairs, get_24h_change, get_kline_change, compute_token_score, select_top_tokens ---
# --- RESTENT LES MÊMES que dans ma réponse précédente (version robuste avec logging amélioré) ---
# --- Je ne les recopie pas ici pour la concision, mais assurez-vous d'utiliser cette version ---

def fetch_USDC_spot_pairs(client):
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

def get_24h_change(client, symbol):
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

def get_kline_change(client, symbol, days=7):
    limit = days + 1 
    retry_count = 0
    max_retries = 1
    while retry_count <= max_retries:
        try:
            klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1DAY, limit=limit)
            if len(klines) < limit :
                logger.debug(f"[get_kline_change] {symbol}, days={days}: Données klines insuffisantes ({len(klines)}/{limit}).")
                return 0.0
            last_close = float(klines[-1][4]); old_close  = float(klines[-limit][4])
            if old_close == 0:
                logger.warning(f"[get_kline_change] {symbol}, days={days}: Ancien prix de clôture est 0.")
                return 0.0
            return (last_close - old_close) / old_close
        except BinanceAPIException as e:
            if e.code == -1003 and retry_count < max_retries:
                retry_count += 1; wait_time = 30 * retry_count
                logger.warning(f"[get_kline_change] Rate limit pour {symbol}. Tentative {retry_count}/{max_retries} après {wait_time}s.")
                time.sleep(wait_time); continue
            logger.warning(f"[get_kline_change] {symbol}, days={days} => API Error: {e.status_code} - {e.message}")
            return 0.0
        except Exception as e:
            logger.warning(f"[get_kline_change] {symbol}, days={days} => Erreur inattendue: {e}", exc_info=False)
            return 0.0
    logger.warning(f"[get_kline_change] {symbol}, days={days}: Échec après {max_retries} nouvelles tentatives.")
    return 0.0

def compute_token_score(p24, p7, p30):
    return 0.8 * p7 + 0.0 * p30 + 0.2 * p24

def select_top_tokens(client, top_n=60):
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
        p24 = get_24h_change(client, pair_symbol); p7  = get_kline_change(client, pair_symbol, days=7); p30 = get_kline_change(client, pair_symbol, days=30)
        score = compute_token_score(p24, p7, p30)
        if score > 0.0001:
             scored_tokens.append({"symbol": base_asset, "score": score, "p7": p7, "p24": p24})
             logger.debug(f"Token {base_asset}: p24={p24:.4f}, p7={p7:.4f}, p30={p30:.4f}, Score={score:.4f} -> Conservé")
        else:
            logger.debug(f"Token {base_asset}: Score={score:.4f} -> Ignoré (score trop bas)")
        processed_count +=1
    logger.info(f"{processed_count}/{len(usdc_pairs)} tokens traités. {len(scored_tokens)} ont un score suffisant.")
    if not scored_tokens:
        logger.warning("[select_top_tokens] Aucun token n'a obtenu un score suffisant.")
        return []
    scored_tokens.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"[select_top_tokens] Top 5 tokens scorés (parmi {len(scored_tokens)}):")
    for i, item in enumerate(scored_tokens[:5]): logger.info(f"  {i+1}. {item['symbol']}: Score={item['score']:.4f} (P7={item['p7']:.2%}, P24={item['p24']:.2%})")
    top_n_selected_items = scored_tokens[:top_n]
    final_list = [item["symbol"] for item in top_n_selected_items]
    logger.info(f"Sélection finale de {len(final_list)} tokens (objectif top_n={top_n}).")
    return final_list

def update_config_with_new_tokens(config_file_path, new_tokens_list):
    # ... (fonction inchangée, elle est correcte pour écrire dans config.yaml) ...
    logger.info(f"Tentative de mise à jour de {config_file_path} avec {len(new_tokens_list)} tokens.")
    if not os.path.isfile(config_file_path):
        logger.error(f"Fichier de configuration introuvable: {config_file_path}")
        return False
    try:
        try:
            import ruamel.yaml
            yaml_parser = ruamel.yaml.YAML(); yaml_parser.indent(mapping=2, sequence=4, offset=2); yaml_parser.preserve_quotes = True
            with open(config_file_path, "r", encoding="utf-8") as f: config_data = yaml_parser.load(f)
            use_ruamel = True; logger.debug("Utilisation de ruamel.yaml pour lire/écrire config.")
        except ImportError:
            logger.debug("ruamel.yaml non trouvé, utilisation de PyYAML standard.")
            with open(config_file_path, "r", encoding="utf-8") as f: config_data = yaml.safe_load(f)
            use_ruamel = False
        if not isinstance(config_data, dict):
            logger.error(f"Le contenu de {config_file_path} n'est pas un dictionnaire YAML valide."); return False
        old_list_len = len(config_data.get("extended_tokens_daily", []))
        config_data["extended_tokens_daily"] = new_tokens_list
        with open(config_file_path, "w", encoding="utf-8") as f:
            if use_ruamel: yaml_parser.dump(config_data, f)
            else: yaml.dump(config_data, f, sort_keys=False, allow_unicode=True, default_flow_style=None)
        logger.info(f"{config_file_path} mis à jour. 'extended_tokens_daily': {old_list_len} -> {len(new_tokens_list)} tokens.")
        return True
    except Exception as e:
        logger.error(f"Erreur lors de la lecture/écriture de {config_file_path}: {e}\n{traceback.format_exc()}"); return False

def main():
    logger.info("=== Démarrage de auto_select_tokens.py (main function) ===")
    # ... (lecture config, init client Binance - inchangé) ...
    if not os.path.isfile(CONFIG_FILE_PATH):
        logger.critical(f"Fichier de configuration principal introuvable: {CONFIG_FILE_PATH}. Arrêt.")
        print(f"JSON_OUTPUT: {json.dumps({'status': 'error', 'message': f'{CONFIG_FILE_PATH} introuvable', 'tokens': []})}")
        sys.stdout.flush(); sys.exit(1)
    try:
        with open(CONFIG_FILE_PATH, "r") as f: config = yaml.safe_load(f)
    except Exception as e:
        logger.critical(f"Impossible de lire/parser {CONFIG_FILE_PATH}: {e}. Arrêt.")
        print(f"JSON_OUTPUT: {json.dumps({'status': 'error', 'message': f'Lecture/Parsing {CONFIG_FILE_PATH} échoué', 'tokens': []})}")
        sys.stdout.flush(); sys.exit(1)
    binance_api_cfg = config.get("binance_api", {}); api_key = binance_api_cfg.get("api_key"); api_secret = binance_api_cfg.get("api_secret")
    if not api_key or not api_secret:
        logger.critical("Clés API Binance manquantes. Arrêt."); print(f"JSON_OUTPUT: {json.dumps({'status': 'error', 'message': 'Clés API Binance manquantes', 'tokens': []})}")
        sys.stdout.flush(); sys.exit(1)
    try:
        client = Client(api_key, api_secret); client.ping(); logger.info("Client Binance initialisé.")
    except Exception as e:
        logger.critical(f"Erreur init client Binance: {e}. Arrêt."); print(f"JSON_OUTPUT: {json.dumps({'status': 'error', 'message': f'Init client Binance échouée: {e}', 'tokens': []})}")
        sys.stdout.flush(); sys.exit(1)
    
    top_n_to_select = config.get("strategy", {}).get("auto_select_top_n", 60)
    if not isinstance(top_n_to_select, int) or top_n_to_select <= 0:
        logger.warning(f"Valeur 'auto_select_top_n' invalide ({top_n_to_select}), défaut 60.")
        top_n_to_select = 60
    logger.info(f"Sélection des {top_n_to_select} meilleurs tokens...")
    
    best_tokens_bases = select_top_tokens(client, top_n=top_n_to_select)
    
    # Tenter de mettre à jour config.yaml dans tous les cas (même si best_tokens_bases est vide)
    config_updated = update_config_with_new_tokens(CONFIG_FILE_PATH, best_tokens_bases if best_tokens_bases else [])
    
    output_payload = {
        "status": "ok",
        "message": "",
        "tokens_selected_count": len(best_tokens_bases) if best_tokens_bases else 0,
        "tokens": best_tokens_bases if best_tokens_bases else []
    }

    if not config_updated:
        output_payload["status"] = "error"
        output_payload["message"] = f"Échec de la mise à jour de {os.path.basename(CONFIG_FILE_PATH)}."
        logger.error(output_payload["message"])
        print(f"JSON_OUTPUT: {json.dumps(output_payload)}")
        sys.stdout.flush()
        sys.exit(1) # Erreur critique si la config ne peut pas être mise à jour

    if best_tokens_bases:
        output_payload["message"] = f"{os.path.basename(CONFIG_FILE_PATH)} mis à jour avec {len(best_tokens_bases)} tokens."
        logger.info(f"Message de succès: {output_payload['message']}")
    else:
        output_payload["message"] = "Aucun token n'a été sélectionné. 'extended_tokens_daily' mis à jour avec une liste vide."
        logger.warning(output_payload["message"])

    # Imprimer le payload JSON sur stdout
    print(f"JSON_OUTPUT: {json.dumps(output_payload)}")
    sys.stdout.flush()
    logger.info("=== auto_select_tokens.py terminé. ===")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e_main:
        logger.critical(f"Erreur non gérée dans main() de auto_select_tokens: {e_main}\n{traceback.format_exc()}")
        # Imprimer une sortie JSON d'erreur aussi en cas de crash inattendu
        try:
            print(f"JSON_OUTPUT: {json.dumps({'status': 'critical_error', 'message': str(e_main), 'tokens': []})}")
            sys.stdout.flush()
        except: # En dernier recours, simple print
            print(f"[ERREUR CRITIQUE] auto_select_tokens.py: {e_main}")
        sys.exit(1)

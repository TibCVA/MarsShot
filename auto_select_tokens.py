#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
auto_select_tokens.py
---------------------
Sélectionne automatiquement les N meilleurs tokens (configurable, défaut 60)
basés sur leur performance, pour les paires Spot en USDC tradables sur Binance.
Met à jour la clé 'extended_tokens_daily' dans config.yaml.
"""

import os
import yaml
import logging
import time
import sys
import traceback # Pour un meilleur logging d'exception

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException
    import requests # Souvent utilisé indirectement par python-binance, ou pour d'autres appels
except ImportError as e:
    # Ce print est pour le cas où le script est lancé manuellement sans logging configuré
    print(f"ERREUR CRITIQUE auto_select_tokens.py: Module manquant: {e}. Installez les dépendances (ex: pip install python-binance requests PyYAML).")
    # Si logging est déjà configuré (par ex. si importé), cela sera loggué aussi.
    # Tenter de logger même si la config de logging principale n'est pas encore faite
    logging.basicConfig(level=logging.CRITICAL)
    logging.critical(f"Module manquant pour auto_select_tokens.py: {e}.")
    sys.exit(1)


# Configuration du logging de base si le script est exécuté seul
# Le nom du logger sera 'auto_select_tokens' pour l'identifier dans les logs consolidés.
logger = logging.getLogger("auto_select_tokens")
if not logger.hasHandlers(): # Configurer seulement si pas déjà configuré par un importeur
    # Créer un handler qui écrit sur sys.stderr pour être capturé par subprocess
    # car stdout est utilisé pour le message de succès/échec principal.
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False # Éviter la double journalisation si le logger root est aussi configuré
    logger.setLevel(logging.INFO) # Mettre à DEBUG pour plus de détails si besoin

# Définir le chemin absolu vers config.yaml
try:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.yaml")
except NameError: # __file__ n'est pas défini (ex: console interactive)
    PROJECT_ROOT = os.getcwd()
    CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.yaml")
    logger.warning(f"__file__ non défini, utilisation de CWD pour PROJECT_ROOT: {PROJECT_ROOT}")


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
            # Liste plus complète de tags pour tokens à effet de levier et stablecoins
            if any(tag in base for tag in ["UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S", "EDGE", "HALF", "LEVERAGED"]):
                logger.debug(f"Exclusion token à effet de levier: {base}")
                continue
            if base in {"USDC", "BUSD", "TUSD", "USDT", "FDUSD", "USDP", "DAI", "PAX", "GUSD", "PYUSD", "EURC", "AEUR"}:
                logger.debug(f"Exclusion stablecoin: {base}")
                continue

            symbol = s.get("symbol", "")
            if symbol.endswith("USDC"):
                usdc_pairs.append(symbol)
            # else: # Pas besoin de logger cela, peut être bruyant
                # logger.debug(f"Symbole {symbol} a quoteAsset USDC mais ne finit pas par USDC. Ignoré.")
                
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
    max_retries = 1 # Une seule nouvelle tentative après une pause

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
            if e.code == -1003 and retry_count < max_retries: # Rate limit
                retry_count += 1
                wait_time = 30 * retry_count # Augmenter le temps d'attente
                logger.warning(f"[get_kline_change] Rate limit pour {symbol}. Tentative {retry_count}/{max_retries} après {wait_time}s.")
                time.sleep(wait_time)
                continue # Reboucler pour la nouvelle tentative
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

        p24 = get_24h_change(client, pair_symbol)
        p7  = get_kline_change(client, pair_symbol, days=7)
        p30 = get_kline_change(client, pair_symbol, days=30)
        
        score = compute_token_score(p24, p7, p30)
        
        if score > 0.0001: # Seuil minimal pour éviter les scores nuls ou négligeables
             scored_tokens.append({"symbol": base_asset, "score": score, "p7": p7, "p24": p24})
             logger.debug(f"Token {base_asset}: p24={p24:.4f}, p7={p7:.4f}, p30={p30:.4f}, Score={score:.4f} -> Conservé")
        else:
            logger.debug(f"Token {base_asset}: p24={p24:.4f}, p7={p7:.4f}, p30={p30:.4f}, Score={score:.4f} -> Ignoré (score trop bas)")
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


def update_config_with_new_tokens(config_file_path, new_tokens_list):
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

def main():
    # Le logger est déjà configuré en haut du script s'il n'a pas de handlers.
    logger.info("=== Démarrage de auto_select_tokens.py (main function) ===")
    
    if not os.path.isfile(CONFIG_FILE_PATH):
        logger.critical(f"Fichier de configuration principal introuvable: {CONFIG_FILE_PATH}. Arrêt.")
        print(f"[ERREUR CRITIQUE] {CONFIG_FILE_PATH} introuvable.")
        sys.exit(1)

    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.critical(f"Impossible de lire ou parser {CONFIG_FILE_PATH}: {e}. Arrêt.")
        print(f"[ERREUR CRITIQUE] Lecture/Parsing {CONFIG_FILE_PATH} échoué.")
        sys.exit(1)

    binance_api_cfg = config.get("binance_api", {})
    api_key = binance_api_cfg.get("api_key")
    api_secret = binance_api_cfg.get("api_secret")

    if not api_key or not api_secret:
        logger.critical("Clés API Binance manquantes dans config.yaml. Arrêt.")
        print("[ERREUR CRITIQUE] Clés API Binance manquantes.")
        sys.exit(1)

    try:
        client = Client(api_key, api_secret)
        client.ping() 
        logger.info("Client Binance initialisé et connexion vérifiée.")
    except Exception as e:
        logger.critical(f"Erreur d'initialisation du client Binance: {e}. Arrêt.")
        print(f"[ERREUR CRITIQUE] Init client Binance échouée: {e}")
        sys.exit(1)
    
    top_n_to_select = config.get("strategy", {}).get("auto_select_top_n", 60)
    if not isinstance(top_n_to_select, int) or top_n_to_select <= 0:
        logger.warning(f"Valeur 'auto_select_top_n' invalide ({top_n_to_select}), utilisation de 60 par défaut.")
        top_n_to_select = 60
        
    logger.info(f"Sélection des {top_n_to_select} meilleurs tokens...")
    
    best_tokens_bases = select_top_tokens(client, top_n=top_n_to_select)
    
    if best_tokens_bases:
        logger.info(f"Sélection finale de {len(best_tokens_bases)} tokens (base assets): {str(best_tokens_bases[:10])+'...' if len(best_tokens_bases) > 10 else best_tokens_bases}")
        if update_config_with_new_tokens(CONFIG_FILE_PATH, best_tokens_bases):
            success_message = f"[OK] {os.path.basename(CONFIG_FILE_PATH)} mis à jour avec {len(best_tokens_bases)} tokens dans extended_tokens_daily."
            logger.info(success_message)
            print(success_message) # Pour subprocess stdout
            sys.stdout.flush()     # S'assurer que la sortie est écrite
            logger.info("=== auto_select_tokens.py terminé avec succès (config mise à jour). ===")
            sys.exit(0) 
        else:
            error_message = f"[ERREUR] Échec de la mise à jour de {os.path.basename(CONFIG_FILE_PATH)}."
            logger.error(error_message)
            print(error_message)
            sys.stdout.flush()
            sys.exit(1) 
    else:
        warn_message = "[WARN] Aucun token n'a été sélectionné par auto_select_tokens.py. config.yaml non modifié pour extended_tokens_daily."
        logger.warning(warn_message)
        print(warn_message)
        sys.stdout.flush()
        # Si aucun token n'est sélectionné, nous devrions probablement écrire une liste vide dans config.yaml
        # pour éviter d'utiliser une ancienne liste de 'extended_tokens_daily'.
        logger.info("Tentative d'écriture d'une liste vide pour 'extended_tokens_daily' dans config.yaml.")
        if update_config_with_new_tokens(CONFIG_FILE_PATH, []):
            print(f"[OK] {os.path.basename(CONFIG_FILE_PATH)} mis à jour avec une liste vide pour extended_tokens_daily.")
            sys.stdout.flush()
        else:
            print(f"[ERREUR] Échec de la mise à jour de {os.path.basename(CONFIG_FILE_PATH)} avec une liste vide.")
            sys.stdout.flush()
            sys.exit(1) # C'est un échec si on ne peut pas mettre à jour la config
            
        logger.info("=== auto_select_tokens.py terminé (aucun token sélectionné, extended_tokens_daily vidé). ===")
        sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except Exception as e_main:
        # Utiliser le logger configuré s'il existe, sinon print
        if logger.hasHandlers():
            logger.critical(f"Erreur non gérée dans main() de auto_select_tokens: {e_main}\n{traceback.format_exc()}")
        else: # Fallback si le logger n'est pas initialisé
            print(f"ERREUR CRITIQUE (auto_select_tokens.py __main__): {e_main}\n{traceback.format_exc()}")
        sys.exit(1)

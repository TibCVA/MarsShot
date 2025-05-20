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
    print(f"ERREUR: Module manquant pour auto_select_tokens.py: {e}. Installez les dépendances.")
    # Si logging est déjà configuré (par ex. si importé), cela sera loggué aussi.
    if logging.getLogger().hasHandlers():
        logging.critical(f"Module manquant pour auto_select_tokens.py: {e}.")
    sys.exit(1)


# Configuration du logging de base si le script est exécuté seul
# Le nom du logger sera 'auto_select_tokens' pour l'identifier dans les logs consolidés.
logger = logging.getLogger("auto_select_tokens")
if not logger.hasHandlers(): # Configurer seulement si pas déjà configuré par un importeur
    handler = logging.StreamHandler(sys.stdout) # Log vers stdout pour subprocess
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO) # Mettre à DEBUG pour plus de détails si besoin

# Définir le chemin absolu vers config.yaml
# __file__ est le chemin du script auto_select_tokens.py lui-même.
# os.path.dirname(__file__) est le répertoire où se trouve ce script.
# Donc, si config.yaml est dans le même répertoire, c'est correct.
# Votre structure indique que auto_select_tokens.py et config.yaml sont à la racine (/app).
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.yaml")


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
            if any(tag in base for tag in ["UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S"]): # Plus de tags pour levier
                logger.debug(f"Exclusion token à effet de levier: {base}")
                continue
            if base in {"USDC", "BUSD", "TUSD", "USDT", "FDUSD", "USDP", "DAI", "PAX", "GUSD", "PYUSD", "EURC", "AEUR"}: # Liste étendue de stables
                logger.debug(f"Exclusion stablecoin: {base}")
                continue

            symbol = s.get("symbol", "")
            if symbol.endswith("USDC"):
                usdc_pairs.append(symbol)
            else:
                logger.warning(f"Symbole {symbol} a quoteAsset USDC mais ne finit pas par USDC. Ignoré.")
                
    unique_usdc_pairs = sorted(list(set(usdc_pairs)))
    logger.info(f"{len(unique_usdc_pairs)} paires USDC spot uniques et tradables trouvées après filtrage.")
    return unique_usdc_pairs


def get_24h_change(client, symbol):
    try:
        tick = client.get_ticker(symbol=symbol)
        # Vérifier si priceChangePercent est présent et est un nombre
        pc_str = tick.get("priceChangePercent")
        if pc_str is None:
            logger.warning(f"[get_24h_change] {symbol}: 'priceChangePercent' manquant dans la réponse du ticker.")
            return 0.0
        return float(pc_str) / 100.0
    except ValueError:
        logger.warning(f"[get_24h_change] {symbol}: Impossible de convertir 'priceChangePercent' en float: '{pc_str}'.")
        return 0.0
    except BinanceAPIException as e:
        logger.warning(f"[get_24h_change] {symbol} => API Error: {e}")
        return 0.0
    except Exception as e:
        logger.warning(f"[get_24h_change] {symbol} => Erreur inattendue: {e}", exc_info=False) # exc_info=False pour moins de bruit
        return 0.0

def get_kline_change(client, symbol, days=7):
    limit = days + 1 
    try:
        # logger.debug(f"Fetching klines for {symbol}, interval=1d, limit={limit}")
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

        if old_close == 0: # Éviter division par zéro
            logger.warning(f"[get_kline_change] {symbol}, days={days}: Ancien prix de clôture est 0.")
            return 0.0
        return (last_close - old_close) / old_close
    except BinanceAPIException as e:
        if e.code == -1003: 
            logger.warning(f"[get_kline_change] Rate limit atteint pour {symbol}. Pause de 60s et une nouvelle tentative.")
            time.sleep(60)
            # Attention à la récursion infinie ici. Une seule nouvelle tentative.
            # Pour une meilleure gestion, utiliser une boucle de reintentions avec backoff exponentiel.
            # Pour l'instant, on simplifie.
            try:
                klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1DAY, limit=limit)
                if len(klines) < limit: return 0.0
                last_close = float(klines[-1][4]); old_close  = float(klines[-limit][4])
                if old_close == 0: return 0.0
                return (last_close - old_close) / old_close
            except Exception as e_retry:
                logger.warning(f"[get_kline_change] {symbol}, days={days} => Échec après nouvelle tentative: {e_retry}")
                return 0.0
        logger.warning(f"[get_kline_change] {symbol}, days={days} => API Error: {e}")
        return 0.0
    except Exception as e:
        logger.warning(f"[get_kline_change] {symbol}, days={days} => Erreur inattendue: {e}", exc_info=False)
        return 0.0

def compute_token_score(p24, p7, p30):
    # Votre formule de scoring
    return 0.8 * p7 + 0.0 * p30 + 0.2 * p24

def select_top_tokens(client, top_n=60):
    usdc_pairs = fetch_USDC_spot_pairs(client)
    if not usdc_pairs:
        logger.warning("[select_top_tokens] Aucune paire USDC spot n'a été trouvée. Retour d'une liste vide.")
        return []
        
    logger.info(f"[select_top_tokens] {len(usdc_pairs)} paires USDC spot trouvées. Calcul des scores...")

    scored_tokens = []
    processed_count = 0
    for idx, pair_symbol in enumerate(usdc_pairs):
        # Ralentir un peu pour éviter les rate limits stricts de Binance sur get_ticker/get_klines en boucle rapide
        if idx > 0 and idx % 10 == 0: # Pause toutes les 10 requêtes
            logger.debug(f"[select_top_tokens] Pause de 0.5s après {idx} tokens (sur {len(usdc_pairs)})...")
            time.sleep(0.5)

        # Extraire base_asset pour logging avant l'appel API qui pourrait échouer
        base_asset = pair_symbol[:-4] if pair_symbol.endswith("USDC") else pair_symbol

        p24 = get_24h_change(client, pair_symbol)
        p7  = get_kline_change(client, pair_symbol, days=7)
        p30 = get_kline_change(client, pair_symbol, days=30) # Calculé même si non utilisé dans le score actuel
        
        # Si un des changements n'a pas pu être récupéré (retourne 0.0 par défaut),
        # cela peut fausser le score. On pourrait choisir de skipper ces tokens.
        # Pour l'instant, on les inclut avec score potentiellement bas.
        
        score = compute_token_score(p24, p7, p30)
        
        if score > 0: # Ne considérer que les scores positifs
             scored_tokens.append({"symbol": base_asset, "score": score, "p7": p7, "p24": p24})
             logger.debug(f"Token {base_asset}: p24={p24:.4f}, p7={p7:.4f}, p30={p30:.4f}, Score={score:.4f}")
        else:
            logger.debug(f"Token {base_asset} a un score non positif ({score:.4f}) et est ignoré pour la sélection.")
        processed_count +=1

    logger.info(f"{processed_count}/{len(usdc_pairs)} tokens traités pour le scoring. {len(scored_tokens)} ont un score positif.")

    if not scored_tokens:
        logger.warning("[select_top_tokens] Aucun token n'a obtenu un score positif après évaluation.")
        return []

    scored_tokens.sort(key=lambda x: x["score"], reverse=True)
    
    logger.info(f"[select_top_tokens] Top 5 tokens scorés (parmi {len(scored_tokens)} tokens avec score > 0):")
    for i, item in enumerate(scored_tokens[:5]):
        logger.info(f"  {i+1}. {item['symbol']}: Score={item['score']:.4f} (P7={item['p7']:.2%}, P24={item['p24']:.2%})")

    top_n_selected_items = scored_tokens[:top_n]
    final_list = [item["symbol"] for item in top_n_selected_items]
    logger.info(f"Sélection finale de {len(final_list)} tokens (top_n={top_n}).")
    return final_list


def update_config_with_new_tokens(config_file_path, new_tokens_list):
    logger.info(f"Tentative de mise à jour de {config_file_path} avec {len(new_tokens_list)} tokens.")
    if not os.path.isfile(config_file_path):
        logger.error(f"Fichier de configuration introuvable: {config_file_path}")
        return False

    try:
        # Utiliser ruamel.yaml pour préserver les commentaires et la mise en page si disponible
        try:
            import ruamel.yaml
            yaml_parser = ruamel.yaml.YAML()
            yaml_parser.indent(mapping=2, sequence=4, offset=2) # Configuration de l'indentation
            yaml_parser.preserve_quotes = True
            with open(config_file_path, "r", encoding="utf-8") as f:
                config_data = yaml_parser.load(f)
            use_ruamel = True
            logger.debug("Utilisation de ruamel.yaml pour lire config.")
        except ImportError:
            logger.debug("ruamel.yaml non trouvé, utilisation de PyYAML standard.")
            with open(config_file_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
            use_ruamel = False
        
        if not isinstance(config_data, dict):
            logger.error(f"Le contenu de {config_file_path} n'est pas un dictionnaire YAML valide.")
            return False

        # Sauvegarder l'ancienne liste pour comparaison dans les logs
        old_list = config_data.get("extended_tokens_daily", None)
        if old_list is not None:
            logger.info(f"Ancienne liste 'extended_tokens_daily' ({len(old_list)} tokens): {str(old_list[:10])+'...' if len(old_list) > 10 else old_list}")
        else:
            logger.info("Clé 'extended_tokens_daily' non présente avant mise à jour.")

        config_data["extended_tokens_daily"] = new_tokens_list # Écrase ou ajoute la clé
        
        # Écriture du fichier mis à jour
        with open(config_file_path, "w", encoding="utf-8") as f:
            if use_ruamel:
                yaml_parser.dump(config_data, f)
            else:
                yaml.dump(config_data, f, sort_keys=False, allow_unicode=True, default_flow_style=None)
        
        logger.info(f"{config_file_path} mis à jour avec succès avec {len(new_tokens_list)} tokens dans 'extended_tokens_daily'.")
        return True
    except Exception as e:
        logger.error(f"Erreur lors de la lecture/écriture de {config_file_path}: {e}\n{traceback.format_exc()}")
        return False

def main():
    logger.info("=== Démarrage de auto_select_tokens.py (version robuste) ===")
    
    if not os.path.isfile(CONFIG_FILE_PATH):
        logger.critical(f"Fichier de configuration principal introuvable: {CONFIG_FILE_PATH}. Arrêt.")
        print(f"[ERREUR CRITIQUE] {CONFIG_FILE_PATH} introuvable.") # Pour subprocess
        sys.exit(1)

    try:
        with open(CONFIG_FILE_PATH, "r") as f:
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
    
    # Permettre de configurer top_n depuis config.yaml, sinon 60 par défaut
    top_n_to_select = config.get("strategy", {}).get("auto_select_top_n", 60)
    if not isinstance(top_n_to_select, int) or top_n_to_select <= 0:
        logger.warning(f"Valeur 'auto_select_top_n' invalide ({top_n_to_select}), utilisation de 60 par défaut.")
        top_n_to_select = 60
        
    logger.info(f"Sélection des {top_n_to_select} meilleurs tokens...")
    
    best_tokens_bases = select_top_tokens(client, top_n=top_n_to_select)
    
    if best_tokens_bases: # Si la liste n'est pas vide
        logger.info(f"Sélection finale de {len(best_tokens_bases)} tokens (base assets): {str(best_tokens_bases[:10])+'...' if len(best_tokens_bases) > 10 else best_tokens_bases}")
        if update_config_with_new_tokens(CONFIG_FILE_PATH, best_tokens_bases):
            # Ce print est important pour que subprocess.run dans main.py puisse le capturer
            print(f"[OK] {os.path.basename(CONFIG_FILE_PATH)} mis à jour avec {len(best_tokens_bases)} tokens dans extended_tokens_daily.")
            logger.info("=== auto_select_tokens.py terminé avec succès. ===")
            sys.exit(0) # Succès explicite
        else:
            print(f"[ERREUR] Échec de la mise à jour de {os.path.basename(CONFIG_FILE_PATH)}.")
            logger.error("Échec de la mise à jour de config.yaml. Voir logs précédents.")
            sys.exit(1) # Échec explicite
    else:
        logger.warning("Aucun token n'a été sélectionné (liste vide retournée par select_top_tokens). config.yaml ne sera pas modifié pour 'extended_tokens_daily'.")
        print("[WARN] Aucun token sélectionné par auto_select_tokens.py. config.yaml non modifié pour extended_tokens_daily.")
        # Optionnel: décider si on doit vider extended_tokens_daily dans config ou le laisser tel quel.
        # Pour l'instant, on ne le modifie pas si aucun token n'est sélectionné.
        # Si vous voulez vider la liste dans ce cas:
        # update_config_with_new_tokens(CONFIG_FILE_PATH, [])
        logger.info("=== auto_select_tokens.py terminé (aucun token sélectionné). ===")
        sys.exit(0) # Terminé, mais sans sélection. Ce n'est pas une erreur en soi.

if __name__ == "__main__":
    try:
        main()
    except Exception as e_main:
        logger.critical(f"Erreur non gérée dans main() de auto_select_tokens: {e_main}\n{traceback.format_exc()}")
        print(f"[ERREUR CRITIQUE] auto_select_tokens.py: {e_main}")
        sys.exit(1)

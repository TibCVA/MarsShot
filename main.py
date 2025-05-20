#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import logging
import datetime
import yaml
import os
import pytz
import subprocess
import json
import sys
# pandas est utilisé dans load_probabilities_csv et dans daily_update_live pour créer un CSV vide
import pandas as pd


from modules.trade_executor import TradeExecutor
from modules.positions_store import load_state, save_state
from modules.risk_manager import intraday_check_real

# --- Configuration des Chemins (au niveau du module) ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.yaml")
CONFIG_TEMP_FILE_PATH = os.path.join(PROJECT_ROOT, "config_temp.yaml")
STATE_FILE_PATH = os.path.join(PROJECT_ROOT, "bot_state.json") # Assumer que positions_store le gère
DAILY_PROBABILITIES_CSV_PATH = os.path.join(PROJECT_ROOT, "daily_probabilities.csv")
DAILY_INFERENCE_CSV_PATH = os.path.join(PROJECT_ROOT, "daily_inference_data.csv")
AUTO_SELECT_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "auto_select_tokens.py")
DATA_FETCHER_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "modules", "data_fetcher.py")
ML_DECISION_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "modules", "ml_decision.py")

# --- Configuration du Logger (au niveau du module) ---
# Ce logger sera utilisé par toutes les fonctions de ce module.
logger = logging.getLogger("main_bot_logic") # Nom spécifique pour ce logger
# Le handler et le niveau seront configurés dans configure_logging() ou main()

def configure_main_logging(config_logging_settings=None):
    """Configure le logging pour le module main et potentiellement globalement."""
    global logger # Pour modifier le logger défini au niveau du module

    if config_logging_settings is None:
        config_logging_settings = {}

    log_file_name = config_logging_settings.get("file", "bot.log")
    log_file_path = os.path.join(PROJECT_ROOT, log_file_name)
    log_level_str = str(config_logging_settings.get("level", "INFO")).upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    log_dir = os.path.dirname(log_file_path)
    if log_dir and not os.path.exists(log_dir):
        try: os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            print(f"Erreur création répertoire log {log_dir}: {e}. Log dans le répertoire courant.")
            log_file_path = os.path.basename(log_file_name)

    # Si le logger 'main_bot_logic' a déjà des handlers, les retirer pour éviter la duplication
    # Cela peut arriver si cette fonction est appelée plusieurs fois ou si dashboard configure aussi
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s")
    
    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Optionnel: ajouter un handler console pour voir les logs directement
    # console_handler = logging.StreamHandler(sys.stdout)
    # console_handler.setFormatter(formatter)
    # logger.addHandler(console_handler)
    
    logger.setLevel(log_level)
    logger.propagate = False # Important pour éviter que le logger root ne duplique les messages si lui aussi est configuré

    # Configurer aussi le logger root pour attraper les logs des modules non configurés
    # Mais faire attention à ne pas dupliquer si main_bot_logic est un enfant du root
    # et que root a aussi un FileHandler vers le même fichier.
    # Pour l'instant, on se concentre sur le logger 'main_bot_logic'.
    
    logger.info(f"Logging pour 'main_bot_logic' configuré. Fichier: {log_file_path}, Niveau: {log_level_str}")
    return log_file_path


def load_probabilities_csv(csv_path=DAILY_PROBABILITIES_CSV_PATH):
    # ... (fonction inchangée, mais utilise `logger` au lieu de `logging`) ...
    if not os.path.exists(csv_path):
        logger.warning(f"Fichier de probabilités {csv_path} introuvable => retour de {{}}")
        return {}
    try:
        df = pd.read_csv(csv_path) # Assurez-vous que pandas est importé
        if df.empty:
            logger.warning(f"Fichier de probabilités {csv_path} est vide => retour de {{}}")
            return {}
        prob_map = {}
        for _, row in df.iterrows():
            sym = str(row["symbol"]).strip()
            p = float(row["prob"])
            prob_map[sym] = p
        logger.info(f"{len(prob_map)} probabilités chargées depuis {csv_path}")
        return prob_map
    except pd.errors.EmptyDataError:
        logger.warning(f"Fichier de probabilités {csv_path} est vide ou mal formaté (EmptyDataError) => retour de {{}}")
        return {}
    except Exception as e:
        logger.error(f"Erreur lors de la lecture de {csv_path}: {e}", exc_info=True)
        return {}


def run_auto_select_once_per_day(state_unused): # state n'est plus utilisé pour la condition ici
    # ... (fonction inchangée par rapport à ma dernière version - celle qui parse le JSON de stdout) ...
    # ... (elle utilise `logger.info`, `logger.error`, etc.) ...
    logger.info(f"Tentative d'exécution de {AUTO_SELECT_SCRIPT_PATH} pour la sélection automatique des tokens.")
    if not os.path.exists(AUTO_SELECT_SCRIPT_PATH):
        logger.error(f"Script {AUTO_SELECT_SCRIPT_PATH} introuvable.")
        return None 
    selected_tokens_from_script = None
    try:
        python_executable = sys.executable 
        process = subprocess.run([python_executable, AUTO_SELECT_SCRIPT_PATH], 
                                 capture_output=True, text=True, cwd=PROJECT_ROOT)
        if process.stderr:
            logger.info(f"Stderr (logs) de {os.path.basename(AUTO_SELECT_SCRIPT_PATH)}:\n{process.stderr.strip()}")
        if process.stdout:
            logger.info(f"Stdout de {os.path.basename(AUTO_SELECT_SCRIPT_PATH)}:\n{process.stdout.strip()}")
            for line in process.stdout.strip().splitlines():
                if line.startswith("JSON_OUTPUT:"):
                    try:
                        json_str = line.replace("JSON_OUTPUT:", "").strip()
                        payload = json.loads(json_str)
                        if payload.get("status") == "ok":
                            selected_tokens_from_script = payload.get("tokens", [])
                            logger.info(f"{len(selected_tokens_from_script)} tokens récupérés depuis la sortie JSON de auto_select_tokens.py.")
                        else:
                            logger.error(f"auto_select_tokens.py a signalé une erreur via JSON: {payload.get('message', 'Message non spécifié')}")
                        break 
                    except json.JSONDecodeError as e_json:
                        logger.error(f"Impossible de parser la sortie JSON de auto_select_tokens.py: {e_json}. Sortie: {line}")
                    except Exception as e_payload:
                        logger.error(f"Erreur lors du traitement du payload JSON de auto_select_tokens.py: {e_payload}. Payload: {payload if 'payload' in locals() else 'Non parsé'}")
            if selected_tokens_from_script is None:
                 logger.warning("Aucune liste de tokens valide (JSON_OUTPUT) n'a été trouvée dans la sortie de auto_select_tokens.py.")
        if process.returncode != 0:
            logger.error(f"{os.path.basename(AUTO_SELECT_SCRIPT_PATH)} s'est terminé avec le code d'erreur {process.returncode}.")
        return selected_tokens_from_script
    except Exception as e:
        logger.error(f"Exception inattendue lors de l'exécution de {os.path.basename(AUTO_SELECT_SCRIPT_PATH)}: {e}", exc_info=True)
        return None


def daily_update_live(state, bexec):
    # ... (fonction inchangée par rapport à ma dernière version - celle qui utilise la sortie de run_auto_select_once_per_day) ...
    # ... (elle utilise `logger.info`, `logger.error`, etc.) ...
    logger.info("Début de daily_update_live.")
    logger.info("Appel de run_auto_select_once_per_day...")
    auto_selected_tokens_from_script = run_auto_select_once_per_day(state) 

    if auto_selected_tokens_from_script is not None:
        logger.info("Attente de 1s pour la synchronisation disque de config.yaml (si auto_select_tokens l'a modifié).")
        time.sleep(1)

    if not os.path.exists(CONFIG_FILE_PATH):
        logger.error(f"{CONFIG_FILE_PATH} introuvable. Arrêt de daily_update_live.")
        return

    try:
        logger.info(f"Lecture de {CONFIG_FILE_PATH}...")
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        cfg_extended_tokens = config.get('extended_tokens_daily', 'Non présente ou vide')
        logger.info(f"'extended_tokens_daily' lu depuis {CONFIG_FILE_PATH} (après auto_select): {str(cfg_extended_tokens)[:200]}...")
    except Exception as e:
        logger.error(f"Erreur lors de la lecture de {CONFIG_FILE_PATH}: {e}", exc_info=True); return

    if auto_selected_tokens_from_script is not None:
        auto_selected_tokens = auto_selected_tokens_from_script
        logger.info(f"Utilisation de la liste de tokens ({len(auto_selected_tokens)}) retournée par auto_select_tokens.py.")
    else:
        logger.warning("auto_select_tokens.py n'a pas retourné de liste. Fallback sur 'extended_tokens_daily' de config.yaml.")
        auto_selected_tokens = config.get("extended_tokens_daily", [])
        if not isinstance(auto_selected_tokens, list):
            logger.warning(f"'extended_tokens_daily' (fallback) n'est pas une liste. Utilisation d'une liste vide.")
            auto_selected_tokens = []
    
    manual_tokens = config.get("tokens_daily", []); system_positions = list(state.get("positions_meta", {}).keys())
    if not isinstance(manual_tokens, list): manual_tokens = []

    final_token_list_for_fetcher = sorted(list(set(auto_selected_tokens).union(set(manual_tokens)).union(set(system_positions))))

    logger.info(f"Auto-selected (script/config): {len(auto_selected_tokens)} tokens. Aperçu: {str(auto_selected_tokens[:10]) if auto_selected_tokens else '[]'}")
    logger.info(f"Manual (config): {manual_tokens}")
    logger.info(f"Positions (state): {system_positions}")
    logger.info(f"Liste finale pour data_fetcher ({len(final_token_list_for_fetcher)} tokens). Aperçu: {str(final_token_list_for_fetcher[:10]) if final_token_list_for_fetcher else '[]'}")

    if not final_token_list_for_fetcher:
        logger.warning("Liste finale de tokens pour data_fetcher est vide. Arrêt du daily_update."); 
        try: pd.DataFrame().to_csv(DAILY_INFERENCE_CSV_PATH, index=False); logger.info(f"Fichier {os.path.basename(DAILY_INFERENCE_CSV_PATH)} vide créé.")
        except Exception as e_csv: logger.error(f"Erreur création CSV vide: {e_csv}");
        return

    config_for_temp = config.copy(); config_for_temp["extended_tokens_daily"] = final_token_list_for_fetcher
    with open(CONFIG_TEMP_FILE_PATH, "w", encoding="utf-8") as fw: yaml.safe_dump(config_for_temp, fw, sort_keys=False)
    logger.info(f"{os.path.basename(CONFIG_TEMP_FILE_PATH)} créé avec {len(final_token_list_for_fetcher)} tokens.")

    strat = config.get("strategy", {}); sell_threshold = strat.get("sell_threshold", 0.3)
    try: big_gain_pct = float(strat.get("big_gain_exception_pct", 3.0))
    except ValueError: logger.error(f"Valeur invalide pour big_gain_exception_pct. Utilisation de 3.0."); big_gain_pct = 3.0
    buy_threshold  = strat.get("buy_threshold", 0.5)
    MIN_VALUE_TO_SELL = 5.0; MAX_VALUE_TO_SKIP_BUY = 20.0
    python_executable = sys.executable

    try:
        logger.info(f"Exécution de {os.path.basename(DATA_FETCHER_SCRIPT_PATH)} avec {CONFIG_TEMP_FILE_PATH}")
        process_df = subprocess.run(
            [python_executable, DATA_FETCHER_SCRIPT_PATH, "--config", CONFIG_TEMP_FILE_PATH],
            check=True, capture_output=True, text=True, cwd=PROJECT_ROOT, encoding='utf-8', errors='ignore' # Ajout encoding
        )
        logger.info(f"{os.path.basename(DATA_FETCHER_SCRIPT_PATH)} exécuté avec succès.")
        if process_df.stdout: logger.info(f"data_fetcher stdout:\n{process_df.stdout.strip()}")
        if process_df.stderr: logger.warning(f"data_fetcher stderr:\n{process_df.stderr.strip()}")
    except subprocess.CalledProcessError as e:
        logger.error(f"{os.path.basename(DATA_FETCHER_SCRIPT_PATH)} a échoué (code: {e.returncode}).")
        if hasattr(e, 'stdout') and e.stdout: logger.error(f"data_fetcher stdout de l'erreur:\n{e.stdout.strip()}")
        if hasattr(e, 'stderr') and e.stderr: logger.error(f"data_fetcher stderr de l'erreur:\n{e.stderr.strip()}")
        return
    except Exception as e:
        logger.error(f"Exception lors de l'appel à {os.path.basename(DATA_FETCHER_SCRIPT_PATH)}: {e}", exc_info=True); return

    if (not os.path.exists(DAILY_INFERENCE_CSV_PATH) or os.path.getsize(DAILY_INFERENCE_CSV_PATH) < 10):
        logger.warning(f"{os.path.basename(DAILY_INFERENCE_CSV_PATH)} introuvable/vide après data_fetcher => skip ml_decision."); return

    try:
        logger.info(f"Exécution de {os.path.basename(ML_DECISION_SCRIPT_PATH)}")
        process_ml = subprocess.run([python_executable, ML_DECISION_SCRIPT_PATH], 
                                    check=True, capture_output=True, text=True, cwd=PROJECT_ROOT, encoding='utf-8', errors='ignore')
        logger.info(f"{os.path.basename(ML_DECISION_SCRIPT_PATH)} exécuté avec succès.")
        if process_ml.stdout: logger.info(f"ml_decision stdout:\n{process_ml.stdout.strip()}")
        if process_ml.stderr: logger.warning(f"ml_decision stderr:\n{process_ml.stderr.strip()}")
    except subprocess.CalledProcessError as e:
        logger.error(f"{os.path.basename(ML_DECISION_SCRIPT_PATH)} a échoué (code: {e.returncode}).")
        if hasattr(e, 'stdout') and e.stdout: logger.error(f"ml_decision stdout de l'erreur:\n{e.stdout.strip()}")
        if hasattr(e, 'stderr') and e.stderr: logger.error(f"ml_decision stderr de l'erreur:\n{e.stderr.strip()}")
        return
    except Exception as e:
        logger.error(f"Exception lors de l'appel à {os.path.basename(ML_DECISION_SCRIPT_PATH)}: {e}", exc_info=True); return

    prob_map = load_probabilities_csv(); 
    logger.info(f"Probabilités chargées pour {len(prob_map)} tokens. Liste de fetcher: {len(final_token_list_for_fetcher)} tokens.")

    try: account_info = bexec.client.get_account()
    except Exception as e: logger.error(f"get_account a échoué: {e}", exc_info=True); return

    balances = account_info.get("balances", []); holdings = {}; USDC_balance = 0.0
    for b in balances:
        asset = b["asset"]
        try: qty = float(b.get("free", 0.0)) + float(b.get("locked", 0.0))
        except ValueError: logger.warning(f"Impossible de parser free/locked pour {asset}. Ignoré."); continue
        if asset.upper() == "USDC": USDC_balance = qty
        elif qty > 0: holdings[asset] = qty
    logger.info(f"Holdings actuels: {holdings}, Solde USDC: {USDC_balance:.2f}")

    assets_sold_this_cycle = []
    for asset, real_qty in list(holdings.items()): 
        if asset.upper() in ["USDC", "BTC", "FDUSD"]: logger.debug(f"Skip vente pour stable/core: {asset}"); continue
        current_px = bexec.get_symbol_price(asset)
        if current_px <= 0: logger.warning(f"Prix invalide ({current_px}) pour {asset} lors vérif vente."); continue
        val_in_usd = current_px * real_qty; prob = prob_map.get(asset, None)
        logger.info(f"Vérification VENTE pour {asset}: Val={val_in_usd:.2f}, Qty={real_qty}, Px={current_px:.4f}, Prob={prob if prob is not None else 'N/A'}")
        if prob is None: logger.info(f"Skip vente {asset}: probabilité non trouvée."); continue
        if val_in_usd >= MIN_VALUE_TO_SELL and prob < sell_threshold:
            meta = state.get("positions_meta", {}).get(asset, {}); entry_px = meta.get("entry_px", 0.0)
            perform_sell = True
            if entry_px > 0:
                ratio = current_px / entry_px; did_skip = meta.get("did_skip_sell_once", False)
                if ratio >= big_gain_pct: 
                    if not did_skip:
                        meta["did_skip_sell_once"] = True; state.setdefault("positions_meta", {})[asset] = meta
                        logger.info(f"SKIP VENTE (BIG GAIN) {asset}: ratio={ratio:.2f} >= {big_gain_pct:.2f}."); perform_sell = False
                    else: logger.info(f"VENTE AUTORISÉE (BIG GAIN DÉJÀ UTILISÉE) {asset}: ratio={ratio:.2f}.")
            if perform_sell:
                logger.info(f"Condition VENTE REMPLIE {asset} (Prob: {prob:.2f} < {sell_threshold}, Val: {val_in_usd:.2f} >= {MIN_VALUE_TO_SELL}). Vente...");
                sold_val = bexec.sell_all(asset, real_qty); logger.info(f"VENTE LIVE {asset}: vendu pour ~{sold_val:.2f} USDC.")
                if asset in state.get("positions_meta", {}): del state["positions_meta"][asset]
                assets_sold_this_cycle.append(asset)
        else: logger.debug(f"Skip vente {asset}. Conditions non remplies.")
    if assets_sold_this_cycle: save_state(state); logger.info(f"État sauvegardé post-VENTE. Vendus: {assets_sold_this_cycle}")

    logger.info("Attente 180s post-vente."); time.sleep(180)
    try: account_info_after_sell = bexec.client.get_account()
    except Exception as e: logger.error(f"get_account post-vente échoué: {e}", exc_info=True); return
    balances_after_sell = account_info_after_sell.get("balances", []); new_holdings = {}; new_USDC_balance = 0.0
    for b_as in balances_after_sell:
        asset = b_as["asset"];
        try: qty = float(b_as.get("free", 0.0)) + float(b_as.get("locked", 0.0))
        except ValueError: continue
        if asset.upper() == "USDC": new_USDC_balance = qty
        elif qty > 0: new_holdings[asset] = qty
    logger.info(f"Post-vente => Holdings: {new_holdings}, USDC: {new_USDC_balance:.2f}")

    buy_candidates_source_list = final_token_list_for_fetcher; buy_candidates = []
    logger.info(f"Recherche candidats ACHAT parmi {len(buy_candidates_source_list)} tokens.")
    for sym in buy_candidates_source_list:
        p = prob_map.get(sym, None); logger.debug(f"Vérif ACHAT {sym}: Prob={p if p is not None else 'N/A'}")
        if p is None or p < buy_threshold:
            if p is None: logger.debug(f"SKIP ACHAT {sym}: Prob non trouvée.")
            else: logger.debug(f"SKIP ACHAT {sym}: Prob {p:.2f} < seuil {buy_threshold:.2f}.")
            continue
        current_quantity_held = new_holdings.get(sym, 0.0)
        if current_quantity_held > 0:
            price_for_value_check = bexec.get_symbol_price(sym)
            if price_for_value_check > 0:
                value_held = price_for_value_check * current_quantity_held
                if value_held > MAX_VALUE_TO_SKIP_BUY:
                    logger.info(f"SKIP ACHAT {sym}: Déjà en portefeuille ({value_held:.2f} USDC > {MAX_VALUE_TO_SKIP_BUY} USDC)."); continue
            else: logger.warning(f"Vérif ACHAT {sym}: Prix non récupérable. Achat autorisé si prob OK.")
        logger.info(f"Candidat ACHAT: {sym} (Prob: {p:.2f})"); buy_candidates.append((sym, p))
    buy_candidates.sort(key=lambda x: x[1], reverse=True); top3_buy_candidates = buy_candidates[:3]
    logger.info(f"Top {len(top3_buy_candidates)} candidats ACHAT: {top3_buy_candidates}")
    assets_bought_this_cycle = []
    if top3_buy_candidates and new_USDC_balance > 10:
        usdc_to_allocate_total = new_USDC_balance * 0.99; num_buys_to_make = len(top3_buy_candidates)
        logger.info(f"Allocation {usdc_to_allocate_total:.2f} USDC pour {num_buys_to_make} token(s).")
        for i, (sym, p_val) in enumerate(top3_buy_candidates, start=1):
            remaining_tokens_to_buy = num_buys_to_make - i + 1
            if usdc_to_allocate_total < 10 or remaining_tokens_to_buy == 0 : 
                logger.info("Reliquat USDC < 10 ou plus de tokens à acheter. Arrêt achats."); break
            usdc_per_buy = usdc_to_allocate_total / remaining_tokens_to_buy
            if usdc_per_buy < 5: logger.info(f"Allocation pour {sym} ({usdc_per_buy:.2f} USDC) trop faible. Arrêt achats."); break
            logger.info(f"Tentative ACHAT {sym} avec ~{usdc_per_buy:.2f} USDC (Prob: {p_val:.2f}).")
            qty_bought, price_bought, cost_of_buy = bexec.buy(sym, usdc_per_buy)
            if qty_bought > 0 and cost_of_buy > 0:
                logger.info(f"ACHAT RÉUSSI {sym}: {qty_bought:.4f} pour {cost_of_buy:.2f} USDC @ {price_bought:.4f}")
                state.setdefault("positions_meta", {})[sym] = {"entry_px": price_bought, "did_skip_sell_once": False, "partial_sold": False, "max_price": price_bought}
                usdc_to_allocate_total -= cost_of_buy; assets_bought_this_cycle.append(sym)
            else: logger.warning(f"ACHAT ÉCHOUÉ/SKIPPÉ pour {sym}.")
        if assets_bought_this_cycle: save_state(state); logger.info(f"État sauvegardé post-ACHAT. Achetés: {assets_bought_this_cycle}")
    else:
        if not top3_buy_candidates: logger.info("Aucun candidat ACHAT trouvé.")
        if new_USDC_balance <= 10: logger.info(f"Solde USDC ({new_USDC_balance:.2f}) insuffisant pour achats.")
    logger.info("daily_update_live terminé.")


def main():
    # --- Configuration du Logging ---
    # Tenter de lire la config pour le logging avant toute autre chose
    temp_config_for_log = {}
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                temp_config_for_log = yaml.safe_load(f)
        except Exception as e_cfg_log:
            print(f"AVERTISSEMENT: Impossible de lire {CONFIG_FILE_PATH} pour la config du log: {e_cfg_log}. Utilisation des paramètres par défaut.")
    
    log_settings = temp_config_for_log.get("logging", {})
    # Appel à la fonction de configuration du logger
    log_file_path_main = configure_main_logging(log_settings) # configure_main_logging utilise/modifie le logger 'main_bot_logic'

    logger.info("======================================================================")
    logger.info(f"[MAIN] Démarrage du bot de trading MarsShot (PID: {os.getpid()}).")
    logger.info(f"[MAIN] Version Python: {sys.version.split()[0]}")
    logger.info(f"[MAIN] Répertoire du projet: {PROJECT_ROOT}")
    logger.info(f"[MAIN] Fichier de configuration: {CONFIG_FILE_PATH}")
    logger.info(f"[MAIN] Fichier de log: {log_file_path_main}") # Utiliser le chemin retourné
    logger.info("======================================================================")

    # Maintenant, 'config' peut être utilisé pour le reste des opérations
    config = temp_config_for_log # Réutiliser la config déjà chargée pour le logging

    if not config: # Si config.yaml n'a pas pu être chargé du tout
        logger.critical(f"{CONFIG_FILE_PATH} est introuvable ou invalide. Arrêt.")
        return

    state = load_state() 
    logger.info(f"État chargé: keys={list(state.keys())}")

    try:
        binance_api_cfg = config.get("binance_api", {})
        api_key = binance_api_cfg.get("api_key")
        api_secret = binance_api_cfg.get("api_secret")
        if not api_key or not api_secret:
            raise KeyError("api_key ou api_secret manquant dans config.binance_api")
        bexec = TradeExecutor(api_key=api_key, api_secret=api_secret)
        logger.info("TradeExecutor initialisé.")
    except KeyError as e:
        logger.critical(f"Configuration API Binance manquante: {e}. Arrêt.")
        return
    except Exception as e:
        logger.critical(f"Erreur initialisation TradeExecutor: {e}. Arrêt.", exc_info=True)
        return
        
    DAILY_UPDATE_HOUR_UTC = config.get("strategy", {}).get("daily_update_hour_utc", 0) 
    DAILY_UPDATE_MINUTE_UTC = config.get("strategy", {}).get("daily_update_minute_utc", 10) 

    logger.info(f"Boucle principale démarrée. Mise à jour quotidienne prévue à {DAILY_UPDATE_HOUR_UTC:02d}:{DAILY_UPDATE_MINUTE_UTC:02d} UTC.")

    if "last_daily_update_ts" not in state: 
        state["last_daily_update_ts"] = 0 
        logger.info("'last_daily_update_ts' initialisé dans l'état.")
    if "last_risk_check_ts" not in state: 
        state["last_risk_check_ts"] = 0
        logger.info("'last_risk_check_ts' initialisé dans l'état.")
    if "did_daily_update_today" not in state: # S'assurer que ce flag existe aussi
        state["did_daily_update_today"] = False # False pour permettre le premier update
        logger.info("'did_daily_update_today' initialisé dans l'état.")
    
    if state.get("last_daily_update_ts") == 0 or state.get("last_risk_check_ts") == 0 or state.get("did_daily_update_today") is False :
        save_state(state) # Sauvegarder si des initialisations ont eu lieu

    while True:
        try:
            now_utc = datetime.datetime.now(pytz.utc)
            current_date_utc = now_utc.date()
            last_update_timestamp = state.get("last_daily_update_ts", 0)
            last_update_date_utc = None
            if last_update_timestamp > 0:
                last_update_date_utc = datetime.datetime.fromtimestamp(last_update_timestamp, tz=pytz.utc).date()

            if state.get("did_daily_update_today", False): 
                if last_update_date_utc is None or current_date_utc > last_update_date_utc:
                    logger.info(f"Réinitialisation du flag 'did_daily_update_today' car nouveau jour UTC ({current_date_utc}) par rapport à la dernière màj ({last_update_date_utc}).")
                    state["did_daily_update_today"] = False
                    save_state(state)
            
            if (now_utc.hour == DAILY_UPDATE_HOUR_UTC and
                now_utc.minute == DAILY_UPDATE_MINUTE_UTC and
                not state.get("did_daily_update_today", False)):
                logger.info(f"Déclenchement de daily_update_live (heure planifiée: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}).")
                daily_update_live(state, bexec) 
                state["did_daily_update_today"] = True
                state["last_daily_update_ts"] = time.time() 
                save_state(state)
                logger.info("daily_update_live terminé et flag 'did_daily_update_today' positionné.")

            last_risk_check_ts = state.get("last_risk_check_ts", 0)
            check_interval = config.get("strategy", {}).get("check_interval_seconds", 300)
            current_time_for_check = time.time()
            if current_time_for_check - last_risk_check_ts >= check_interval:
                logger.info(f"Exécution de intraday_check_real() (dernier check il y a {current_time_for_check - last_risk_check_ts:.0f}s).")
                intraday_check_real(state, bexec, config) 
                state["last_risk_check_ts"] = current_time_for_check 
                save_state(state)
        except KeyboardInterrupt:
            logger.info("Interruption clavier détectée (SIGINT). Arrêt du bot.")
            break 
        except SystemExit as e_sys: 
            logger.info(f"Arrêt du bot demandé (SystemExit code: {e_sys.code}).")
            break
        except Exception as e:
            logger.error(f"Erreur inattendue dans la boucle principale: {e}", exc_info=True)
            logger.info("Pause de 60 secondes suite à l'erreur avant de reprendre.")
            time.sleep(60) 
        time.sleep(10) 
    logger.info("Boucle principale terminée. Arrêt du bot.")

if __name__ == "__main__":
    # Si main() est appelé directement, il configurera son propre logging.
    # Si dashboard.py importe des fonctions de main.py, le logging pourrait déjà être configuré
    # par dashboard.py. La fonction configure_main_logging essaie de gérer cela.
    main()

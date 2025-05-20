#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import logging
import datetime
import yaml
import os
import pytz
# subprocess n'est plus nécessaire pour auto_select_tokens si on l'appelle directement
# import subprocess 
import json 
import sys
import pandas as pd

from modules.trade_executor import TradeExecutor
from modules.positions_store import load_state, save_state
from modules.risk_manager import intraday_check_real

# --- Import de la fonction depuis auto_select_tokens.py ---
try:
    # auto_select_tokens.py est à la racine, comme main.py
    from auto_select_tokens import select_and_write_tokens as select_tokens_and_update_config_auto
    from auto_select_tokens import CONFIG_FILE_PATH as AUTO_SELECT_CONFIG_PATH # Récupérer le chemin de config utilisé par auto_select
except ImportError as e:
    logging.getLogger(__name__).critical(f"Impossible d'importer depuis auto_select_tokens.py: {e}. La sélection automatique sera désactivée.", exc_info=True)
    # Définir une fonction factice pour éviter les crashs
    def select_tokens_and_update_config_auto(client, config_path, num_tokens):
        logging.getLogger(__name__).error("Fonction factice select_tokens_and_update_config_auto appelée.")
        return [] # Retourne une liste vide
    AUTO_SELECT_CONFIG_PATH = "config.yaml" # Fallback


# --- Configuration des Chemins (au niveau du module) ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.yaml") # Fichier principal de config
CONFIG_TEMP_FILE_PATH = os.path.join(PROJECT_ROOT, "config_temp.yaml")
DAILY_PROBABILITIES_CSV_PATH = os.path.join(PROJECT_ROOT, "daily_probabilities.csv")
DAILY_INFERENCE_CSV_PATH = os.path.join(PROJECT_ROOT, "daily_inference_data.csv")
# AUTO_SELECT_SCRIPT_PATH n'est plus nécessaire si on appelle la fonction directement
DATA_FETCHER_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "modules", "data_fetcher.py")
ML_DECISION_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "modules", "ml_decision.py")

logger = logging.getLogger("main_bot_logic")

def configure_main_logging(config_logging_settings=None):
    # ... (fonction inchangée par rapport à la version précédente) ...
    global logger
    if config_logging_settings is None: config_logging_settings = {}
    log_file_name = config_logging_settings.get("file", "bot.log")
    log_file_path = os.path.join(PROJECT_ROOT, log_file_name)
    log_level_str = str(config_logging_settings.get("level", "INFO")).upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    log_dir = os.path.dirname(log_file_path)
    if log_dir and not os.path.exists(log_dir):
        try: os.makedirs(log_dir, exist_ok=True)
        except OSError as e: print(f"Erreur création répertoire log {log_dir}: {e}"); log_file_path = os.path.basename(log_file_name)
    if logger.hasHandlers(): logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s")
    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    file_handler.setFormatter(formatter); logger.addHandler(file_handler)
    logger.setLevel(log_level); logger.propagate = False
    logger.info(f"Logging pour 'main_bot_logic' configuré. Fichier: {log_file_path}, Niveau: {log_level_str}")
    return log_file_path

def load_probabilities_csv(csv_path=DAILY_PROBABILITIES_CSV_PATH):
    # ... (fonction inchangée, utilise `logger`) ...
    if not os.path.exists(csv_path): logger.warning(f"Fichier probabilités {csv_path} introuvable."); return {}
    try:
        df = pd.read_csv(csv_path)
        if df.empty: logger.warning(f"Fichier probabilités {csv_path} vide."); return {}
        prob_map = {str(r["symbol"]).strip(): float(r["prob"]) for _, r in df.iterrows()}
        logger.info(f"{len(prob_map)} probabilités chargées depuis {csv_path}"); return prob_map
    except pd.errors.EmptyDataError: logger.warning(f"Fichier probabilités {csv_path} vide/mal formaté."); return {}
    except Exception as e: logger.error(f"Erreur lecture {csv_path}: {e}", exc_info=True); return {}

# MODIFICATION: run_auto_select_once_per_day appelle maintenant la fonction importée
def run_auto_select_once_per_day(bexec_client: Client, config_path_to_update: str, num_top_n: int):
    """
    Appelle la fonction de sélection de tokens de auto_select_tokens_module.
    Retourne la liste des tokens sélectionnés, ou None en cas d'échec.
    """
    logger.info(f"Appel de la fonction de sélection de tokens depuis auto_select_tokens module...")
    if bexec_client is None:
        logger.error("Client Binance (bexec.client) non fourni à run_auto_select_once_per_day.")
        return None
    try:
        # Appeler la fonction importée en passant le client Binance
        # et le chemin vers config.yaml que auto_select_tokens doit mettre à jour.
        # Le nombre de tokens à sélectionner (top_n) vient de la config principale.
        selected_tokens = select_tokens_and_update_config_auto(
            binance_client_instance=bexec_client,
            config_path=config_path_to_update, # C'est CONFIG_FILE_PATH de main.py
            num_top_tokens=num_top_n
        )
        if selected_tokens is not None: # Peut être une liste vide si aucun token sélectionné
            logger.info(f"{len(selected_tokens)} tokens retournés par la fonction de sélection automatique.")
        else: # La fonction a retourné None, indiquant un échec plus grave
            logger.error("La fonction de sélection automatique a retourné None (échec).")
        return selected_tokens
    except RuntimeError as e_rt: # Si la fonction factice est appelée
        logger.error(f"Erreur d'exécution lors de l'appel à la fonction de sélection: {e_rt}")
        return None
    except Exception as e:
        logger.error(f"Exception inattendue lors de l'appel à la fonction de sélection de tokens: {e}", exc_info=True)
        return None


def daily_update_live(state, bexec):
    logger.info("Début de daily_update_live.")

    # Lire la config une première fois pour obtenir top_n pour auto_select
    # et pour les paramètres de stratégie, etc.
    if not os.path.exists(CONFIG_FILE_PATH):
        logger.error(f"{CONFIG_FILE_PATH} introuvable. Arrêt de daily_update_live.")
        return
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Erreur lors de la lecture initiale de {CONFIG_FILE_PATH}: {e}", exc_info=True)
        return
    
    top_n_for_auto_select = config.get("strategy", {}).get("auto_select_top_n", 60)

    logger.info("Appel de run_auto_select_once_per_day (appel de fonction directe)...")
    # Passer bexec.client, le chemin de config.yaml à mettre à jour, et top_n
    auto_selected_tokens = run_auto_select_once_per_day(bexec.client, CONFIG_FILE_PATH, top_n_for_auto_select)

    if auto_selected_tokens is None:
        logger.error("Échec critique de la sélection automatique des tokens. Utilisation des tokens de config.yaml comme fallback si présents.")
        auto_selected_tokens = config.get("extended_tokens_daily", []) # Fallback sur ce qui est dans config
        if not isinstance(auto_selected_tokens, list): auto_selected_tokens = []
    elif not auto_selected_tokens: # Liste vide retournée, mais pas d'erreur critique
        logger.warning("Aucun token retourné par la sélection automatique. 'extended_tokens_daily' dans config.yaml devrait être vide.")
        # Relire config pour être sûr de son état après l'appel (auto_select_tokens est censé l'avoir mis à jour)
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f: temp_cfg_check = yaml.safe_load(f)
            auto_selected_tokens = temp_cfg_check.get("extended_tokens_daily", [])
            if not isinstance(auto_selected_tokens, list): auto_selected_tokens = []
            logger.info(f"Vérification: 'extended_tokens_daily' dans config après auto_select (liste vide): {len(auto_selected_tokens)} tokens.")
        except Exception as e_cfg:
            logger.error(f"Erreur relecture config pour vérification liste vide: {e_cfg}")
            auto_selected_tokens = [] # Sécurité
    else:
        logger.info(f"{len(auto_selected_tokens)} tokens reçus de la sélection automatique.")
        # Pas besoin de relire config.yaml pour cette liste, on l'a directement.
        # auto_select_tokens.py est toujours censé avoir mis à jour config.yaml en parallèle.

    manual_tokens = config.get("tokens_daily", [])
    if not isinstance(manual_tokens, list): manual_tokens = []
        
    system_positions = list(state.get("positions_meta", {}).keys())

    final_token_list_for_fetcher = sorted(list( 
        set(auto_selected_tokens).union(set(manual_tokens)).union(set(system_positions))
    ))

    logger.info(f"Tokens from auto_select function: {len(auto_selected_tokens)} - Aperçu: {str(auto_selected_tokens[:10]) if auto_selected_tokens else '[]'}")
    logger.info(f"Tokens from manual list (config:tokens_daily): {manual_tokens}")
    logger.info(f"Tokens from current positions (state:positions_meta): {system_positions}")
    logger.info(f"Liste finale combinée pour data_fetcher ({len(final_token_list_for_fetcher)} tokens) - Aperçu: {str(final_token_list_for_fetcher[:10]) if final_token_list_for_fetcher else '[]'}")

    if not final_token_list_for_fetcher:
        logger.warning("La liste finale de tokens pour data_fetcher est vide. Arrêt du daily_update.")
        try: pd.DataFrame().to_csv(DAILY_INFERENCE_CSV_PATH, index=False); logger.info(f"Fichier {os.path.basename(DAILY_INFERENCE_CSV_PATH)} vide créé.")
        except Exception as e_csv: logger.error(f"Erreur création CSV vide: {e_csv}");
        return

    # Utiliser l'objet 'config' déjà chargé et potentiellement mis à jour par auto_select_tokens
    config_for_temp = config.copy() 
    config_for_temp["extended_tokens_daily"] = final_token_list_for_fetcher

    with open(CONFIG_TEMP_FILE_PATH, "w", encoding="utf-8") as fw: 
        yaml.safe_dump(config_for_temp, fw, sort_keys=False)
    logger.info(f"{os.path.basename(CONFIG_TEMP_FILE_PATH)} créé avec {len(final_token_list_for_fetcher)} tokens dans extended_tokens_daily.")

    # --- Le reste de la fonction daily_update_live (stratégie, data_fetcher, ml_decision, SELL, BUY) ---
    # --- est identique à la version précédente que je vous ai fournie. ---
    # --- S'assurer que les appels subprocess utilisent python_executable et cwd=PROJECT_ROOT ---
    strat = config.get("strategy", {}); sell_threshold = strat.get("sell_threshold", 0.3)
    try: big_gain_pct = float(strat.get("big_gain_exception_pct", 3.0))
    except ValueError: logger.error(f"Valeur invalide pour big_gain_exception_pct. Utilisation de 3.0."); big_gain_pct = 3.0
    buy_threshold  = strat.get("buy_threshold", 0.5)
    MIN_VALUE_TO_SELL = 5.0; MAX_VALUE_TO_SKIP_BUY = 20.0
    python_executable = sys.executable # Défini au niveau du module

    try:
        logger.info(f"Exécution de {os.path.basename(DATA_FETCHER_SCRIPT_PATH)} avec {CONFIG_TEMP_FILE_PATH}")
        process_df = subprocess.run(
            [python_executable, DATA_FETCHER_SCRIPT_PATH, "--config", CONFIG_TEMP_FILE_PATH],
            check=True, capture_output=True, text=True, cwd=PROJECT_ROOT, encoding='utf-8', errors='ignore'
        )
        logger.info(f"{os.path.basename(DATA_FETCHER_SCRIPT_PATH)} exécuté avec succès.")
        if process_df.stdout: logger.info(f"data_fetcher stdout:\n{process_df.stdout.strip()}")
        if process_df.stderr: logger.warning(f"data_fetcher stderr:\n{process_df.stderr.strip()}")
    except subprocess.CalledProcessError as e:
        logger.error(f"{os.path.basename(DATA_FETCHER_SCRIPT_PATH)} a échoué (code: {e.returncode}).")
        if hasattr(e, 'stdout') and e.stdout: logger.error(f"data_fetcher stdout de l'erreur:\n{e.stdout.strip()}")
        if hasattr(e, 'stderr') and e.stderr: logger.error(f"data_fetcher stderr de l'erreur:\n{e.stderr.strip()}")
        return
    except Exception as e: logger.error(f"Exception appel {os.path.basename(DATA_FETCHER_SCRIPT_PATH)}: {e}", exc_info=True); return

    if (not os.path.exists(DAILY_INFERENCE_CSV_PATH) or os.path.getsize(DAILY_INFERENCE_CSV_PATH) < 10):
        logger.warning(f"{os.path.basename(DAILY_INFERENCE_CSV_PATH)} introuvable/vide => skip ml_decision."); return

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
    except Exception as e: logger.error(f"Exception appel {os.path.basename(ML_DECISION_SCRIPT_PATH)}: {e}", exc_info=True); return

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
        if asset.upper() in ["USDC", "BTC", "FDUSD"]: logger.debug(f"Skip vente stable/core: {asset}"); continue
        current_px = bexec.get_symbol_price(asset)
        if current_px <= 0: logger.warning(f"Prix invalide ({current_px}) pour {asset} lors vérif vente."); continue
        val_in_usd = current_px * real_qty; prob = prob_map.get(asset, None)
        logger.info(f"Vérification VENTE {asset}: Val={val_in_usd:.2f}, Qty={real_qty}, Px={current_px:.4f}, Prob={prob if prob is not None else 'N/A'}")
        if prob is None: logger.info(f"Skip vente {asset}: prob non trouvée."); continue
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
                logger.info(f"Condition VENTE REMPLIE {asset}. Vente...");
                sold_val = bexec.sell_all(asset, real_qty); logger.info(f"VENTE LIVE {asset}: ~{sold_val:.2f} USDC.")
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
    config = {}
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except Exception as e_cfg_log:
            print(f"AVERTISSEMENT: Impossible de lire {CONFIG_FILE_PATH} pour la config du log: {e_cfg_log}. Utilisation des paramètres par défaut.")
    
    log_settings = config.get("logging", {}) # Utiliser la config chargée ou un dict vide
    log_file_path_main = configure_main_logging(log_settings)

    logger.info("======================================================================")
    logger.info(f"[MAIN] Démarrage du bot de trading MarsShot (PID: {os.getpid()}).")
    logger.info(f"[MAIN] Version Python: {sys.version.split()[0]}")
    logger.info(f"[MAIN] Répertoire du projet: {PROJECT_ROOT}")
    logger.info(f"[MAIN] Fichier de configuration: {CONFIG_FILE_PATH}")
    logger.info(f"[MAIN] Fichier de log: {log_file_path_main}")
    logger.info("======================================================================")

    if not config: 
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

    # Initialisation des clés de l'état si elles n'existent pas
    changed_state = False
    if "last_daily_update_ts" not in state: 
        state["last_daily_update_ts"] = 0 
        logger.info("'last_daily_update_ts' initialisé dans l'état.")
        changed_state = True
    if "last_risk_check_ts" not in state: 
        state["last_risk_check_ts"] = 0
        logger.info("'last_risk_check_ts' initialisé dans l'état.")
        changed_state = True
    if "did_daily_update_today" not in state:
        state["did_daily_update_today"] = False
        logger.info("'did_daily_update_today' initialisé dans l'état.")
        changed_state = True
    if changed_state:
        save_state(state)

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
                    logger.info(f"Réinitialisation 'did_daily_update_today' (nouveau jour UTC: {current_date_utc}, dernière màj: {last_update_date_utc}).")
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
    main()

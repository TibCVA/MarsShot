#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import logging
import datetime
import yaml
import os
import pytz
import subprocess # Toujours nécessaire pour data_fetcher et ml_decision
import json 
import sys
import pandas as pd

from modules.trade_executor import TradeExecutor
from modules.positions_store import load_state, save_state
from modules.risk_manager import intraday_check_real

# --- Import de la fonction depuis auto_select_tokens.py ---
auto_select_module_imported = False
select_tokens_and_update_config_auto_func = None
try:
    from auto_select_tokens import select_and_write_tokens, CONFIG_FILE_PATH as AUTO_SELECT_CONFIG_PATH_FROM_MODULE
    select_tokens_and_update_config_auto_func = select_and_write_tokens
    auto_select_module_imported = True
except ImportError as e:
    # Le logger n'est pas encore configuré, utiliser print pour cette erreur critique initiale
    print(f"ERREUR CRITIQUE main.py: Impossible d'importer depuis auto_select_tokens.py: {e}. La sélection automatique sera désactivée.", file=sys.stderr)
    # Définir une fonction factice pour éviter les crashs ultérieurs
    def select_tokens_and_update_config_auto_placeholder(binance_client_instance, config_path, num_top_tokens):
        if logging.getLogger("main_bot_logic").hasHandlers(): # Vérifier si le logger est dispo
            logging.getLogger("main_bot_logic").error("Fonction factice select_tokens_and_update_config_auto appelée car import a échoué.")
        return [] 
    select_tokens_and_update_config_auto_func = select_tokens_and_update_config_auto_placeholder
    AUTO_SELECT_CONFIG_PATH_FROM_MODULE = "config.yaml" # Fallback


# --- Configuration des Chemins (au niveau du module) ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.yaml") 
CONFIG_TEMP_FILE_PATH = os.path.join(PROJECT_ROOT, "config_temp.yaml")
# STATE_FILE_PATH est géré par positions_store.py
DAILY_PROBABILITIES_CSV_PATH = os.path.join(PROJECT_ROOT, "daily_probabilities.csv")
DAILY_INFERENCE_CSV_PATH = os.path.join(PROJECT_ROOT, "daily_inference_data.csv")
# AUTO_SELECT_SCRIPT_PATH n'est plus utilisé pour subprocess
DATA_FETCHER_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "modules", "data_fetcher.py")
ML_DECISION_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "modules", "ml_decision.py")

logger = logging.getLogger("main_bot_logic")

def configure_main_logging(config_logging_settings=None):
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
    
    # Nettoyer les handlers existants pour éviter la duplication si la fonction est appelée plusieurs fois
    # (par exemple, par le dashboard)
    for handler in logger.handlers[:]: logger.removeHandler(handler)
    # Idem pour le logger root si on le configure aussi, mais attention aux interférences
    # for handler in logging.getLogger().handlers[:]: logging.getLogger().removeHandler(handler)


    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s")
    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    file_handler.setFormatter(formatter); logger.addHandler(file_handler)
    
    # Optionnel: Handler console pour le bot principal
    # console_h = logging.StreamHandler(sys.stdout)
    # console_h.setFormatter(formatter)
    # logger.addHandler(console_h)
    
    logger.setLevel(log_level); logger.propagate = False
    logger.info(f"Logging pour 'main_bot_logic' configuré. Fichier: {log_file_path}, Niveau: {log_level_str}")
    return log_file_path

def load_probabilities_csv(csv_path=DAILY_PROBABILITIES_CSV_PATH):
    if not os.path.exists(csv_path): logger.warning(f"Fichier prob {csv_path} introuvable."); return {}
    try:
        df = pd.read_csv(csv_path)
        if df.empty: logger.warning(f"Fichier prob {csv_path} vide."); return {}
        prob_map = {str(r["symbol"]).strip(): float(r["prob"]) for _, r in df.iterrows()}
        logger.info(f"{len(prob_map)} probabilités chargées depuis {csv_path}"); return prob_map
    except pd.errors.EmptyDataError: logger.warning(f"Fichier prob {csv_path} vide/mal formaté."); return {}
    except Exception as e: logger.error(f"Erreur lecture {csv_path}: {e}", exc_info=True); return {}

def run_auto_select_and_get_tokens(binance_client_instance: Client, config_path_main: str, num_top_n: int):
    """
    Appelle la fonction de sélection de tokens et retourne la liste.
    auto_select_tokens.py est aussi censé mettre à jour config.yaml.
    """
    logger.info(f"Appel de la fonction select_tokens_and_update_config_auto_func (de auto_select_tokens.py)...")
    if not auto_select_module_imported or select_tokens_and_update_config_auto_func is None:
        logger.error("Le module/fonction de sélection automatique de tokens n'a pas été importé correctement.")
        return None # Échec clair
        
    selected_tokens = None
    try:
        # La fonction importée select_and_write_tokens s'occupe de la logique et de la mise à jour de config.yaml
        # Elle prend le client Binance, le chemin vers config.yaml, et le nombre de tokens.
        # Utiliser AUTO_SELECT_CONFIG_PATH_FROM_MODULE pour être sûr que c'est le même config.yaml
        # que celui que auto_select_tokens.py utiliserait s'il était lancé seul.
        selected_tokens = select_tokens_and_update_config_auto_func(
            binance_client_instance=binance_client_instance,
            config_path=AUTO_SELECT_CONFIG_PATH_FROM_MODULE, 
            num_top_tokens=num_top_n
        )
        
        if selected_tokens is not None: # Peut être une liste vide
            logger.info(f"{len(selected_tokens)} tokens retournés par la fonction de sélection automatique.")
        else: # La fonction a explicitement retourné None, indiquant un échec
            logger.error("La fonction de sélection automatique a retourné None (échec interne probable).")
        return selected_tokens # Retourne la liste (peut être vide) ou None
        
    except Exception as e:
        logger.error(f"Exception inattendue lors de l'appel à la fonction de sélection de tokens: {e}", exc_info=True)
        return None # Échec majeur


def daily_update_live(state, bexec):
    logger.info("Début de daily_update_live.")

    # Lire la config une première fois pour obtenir top_n pour auto_select
    if not os.path.exists(CONFIG_FILE_PATH):
        logger.error(f"{CONFIG_FILE_PATH} introuvable. Arrêt de daily_update_live.")
        return
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Erreur lors de la lecture initiale de {CONFIG_FILE_PATH}: {e}", exc_info=True); return
    
    top_n_for_auto_select = config.get("strategy", {}).get("auto_select_top_n", 60)
    if not isinstance(top_n_for_auto_select, int) or top_n_for_auto_select <= 0:
        logger.warning(f"Valeur 'auto_select_top_n' invalide ({top_n_for_auto_select}), défaut 60.")
        top_n_for_auto_select = 60

    logger.info("Appel de run_auto_select_and_get_tokens (appel de fonction directe)...")
    auto_selected_tokens = run_auto_select_and_get_tokens(bexec.client, CONFIG_FILE_PATH, top_n_for_auto_select)

    # Attendre un peu pour que les écritures sur config.yaml par auto_select_tokens.py se terminent.
    if auto_selected_tokens is not None:
        logger.info("Attente de 0.5s pour la synchronisation disque de config.yaml.")
        time.sleep(0.5)
    
    # Relire config.yaml pour obtenir la version la plus à jour (au cas où auto_select l'aurait modifié)
    # et pour les autres paramètres.
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) # Relit la config, potentiellement mise à jour
        logger.info(f"Config relue depuis {CONFIG_FILE_PATH}.")
    except Exception as e:
        logger.error(f"Erreur lors de la relecture de {CONFIG_FILE_PATH}: {e}", exc_info=True); return

    if auto_selected_tokens is None: # Échec critique de la sélection
        logger.error("Échec critique de la sélection auto. Fallback sur 'extended_tokens_daily' de config (si existe).")
        auto_selected_tokens = config.get("extended_tokens_daily", [])
    elif not auto_selected_tokens: # Sélection réussie, mais 0 token trouvé
        logger.warning("Aucun token retourné par la sélection auto. 'extended_tokens_daily' dans config devrait être vide.")
        # S'assurer qu'on utilise bien la liste vide de la config si c'est le cas
        auto_selected_tokens = config.get("extended_tokens_daily", [])

    if not isinstance(auto_selected_tokens, list): auto_selected_tokens = []
    
    manual_tokens = config.get("tokens_daily", [])
    if not isinstance(manual_tokens, list): manual_tokens = []
        
    system_positions = list(state.get("positions_meta", {}).keys())

    final_token_list_for_fetcher = sorted(list( 
        set(auto_selected_tokens).union(set(manual_tokens)).union(set(system_positions))
    ))

    logger.info(f"Tokens from auto_select_func: {len(auto_selected_tokens)} - Aperçu: {str(auto_selected_tokens[:10]) if auto_selected_tokens else '[]'}")
    logger.info(f"Tokens from manual list: {manual_tokens}")
    logger.info(f"Tokens from positions: {system_positions}")
    logger.info(f"Liste finale pour data_fetcher ({len(final_token_list_for_fetcher)} tokens) - Aperçu: {str(final_token_list_for_fetcher[:10]) if final_token_list_for_fetcher else '[]'}")

    if not final_token_list_for_fetcher:
        logger.warning("Liste finale de tokens pour data_fetcher est vide. Arrêt du daily_update."); 
        try: pd.DataFrame().to_csv(DAILY_INFERENCE_CSV_PATH, index=False); logger.info(f"Fichier {os.path.basename(DAILY_INFERENCE_CSV_PATH)} vide créé.")
        except Exception as e_csv: logger.error(f"Erreur création CSV vide: {e_csv}");
        return

    config_for_temp = config.copy(); config_for_temp["extended_tokens_daily"] = final_token_list_for_fetcher
    with open(CONFIG_TEMP_FILE_PATH, "w", encoding="utf-8") as fw: yaml.safe_dump(config_for_temp, fw, sort_keys=False)
    logger.info(f"{os.path.basename(CONFIG_TEMP_FILE_PATH)} créé avec {len(final_token_list_for_fetcher)} tokens.")

    # --- Reste de daily_update_live ---
    # (Stratégie, data_fetcher, ml_decision, SELL, BUY - identique à la version précédente)
    # ... (copier le reste de la fonction daily_update_live à partir d'ici) ...
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
        if process_ml.stderr: logger.warning(f"ml_decision stderr:\n{process_ml.stderr.strip()}") # Les warnings sklearn iront ici
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
    config = {} # Initialiser config pour qu'elle soit toujours définie
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except Exception as e_cfg_log:
            # Utiliser print car le logger n'est pas encore configuré
            print(f"AVERTISSEMENT: Impossible de lire {CONFIG_FILE_PATH} pour la config du log: {e_cfg_log}. Utilisation des paramètres par défaut.")
            config = {} # Assurer que config est un dict
    
    log_settings = config.get("logging", {}) 
    log_file_path_main = configure_main_logging(log_settings)

    # Le reste des logs utilisera 'logger'
    logger.info("======================================================================")
    logger.info(f"[MAIN] Démarrage du bot de trading MarsShot (PID: {os.getpid()}).")
    logger.info(f"[MAIN] Version Python: {sys.version.split()[0]}")
    logger.info(f"[MAIN] Répertoire du projet: {PROJECT_ROOT}")
    logger.info(f"[MAIN] Fichier de configuration: {CONFIG_FILE_PATH}")
    logger.info(f"[MAIN] Fichier de log: {log_file_path_main}")
    logger.info("======================================================================")

    if not config: 
        logger.critical(f"{CONFIG_FILE_PATH} est introuvable ou invalide après tentative de chargement. Arrêt.")
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

    changed_state_on_init = False
    if "last_daily_update_ts" not in state: 
        state["last_daily_update_ts"] = 0 
        logger.info("'last_daily_update_ts' initialisé dans l'état.")
        changed_state_on_init = True
    if "last_risk_check_ts" not in state: 
        state["last_risk_check_ts"] = 0
        logger.info("'last_risk_check_ts' initialisé dans l'état.")
        changed_state_on_init = True
    if "did_daily_update_today" not in state:
        state["did_daily_update_today"] = False
        logger.info("'did_daily_update_today' initialisé dans l'état.")
        changed_state_on_init = True
    if changed_state_on_init:
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

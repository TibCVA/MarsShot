#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import logging
import datetime
import yaml
import os
import pytz
import subprocess
import json # Pour logger le contenu de config
import sys # <--- ASSUREZ-VOUS QUE CET IMPORT EST PRÉSENT

from modules.trade_executor import TradeExecutor
from modules.positions_store import load_state, save_state
from modules.risk_manager import intraday_check_real

# Définir le chemin absolu vers config.yaml une bonne fois pour toutes
# en supposant que main.py est à la racine du projet.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.yaml")
CONFIG_TEMP_FILE_PATH = os.path.join(PROJECT_ROOT, "config_temp.yaml")
DAILY_PROBABILITIES_CSV_PATH = os.path.join(PROJECT_ROOT, "daily_probabilities.csv")
DAILY_INFERENCE_CSV_PATH = os.path.join(PROJECT_ROOT, "daily_inference_data.csv")
AUTO_SELECT_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "auto_select_tokens.py")
DATA_FETCHER_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "modules", "data_fetcher.py")
ML_DECISION_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "modules", "ml_decision.py")


def load_probabilities_csv(csv_path=DAILY_PROBABILITIES_CSV_PATH):
    import pandas as pd
    if not os.path.exists(csv_path):
        logging.warning(f"[load_probabilities_csv] {csv_path} introuvable => return {{}}")
        return {}
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            logging.warning(f"[load_probabilities_csv] {csv_path} est vide => return {{}}")
            return {}
        prob_map = {}
        for _, row in df.iterrows():
            sym = str(row["symbol"]).strip()
            p = float(row["prob"])
            prob_map[sym] = p
        return prob_map
    except pd.errors.EmptyDataError:
        logging.warning(f"[load_probabilities_csv] {csv_path} est vide ou mal formaté (EmptyDataError) => return {{}}")
        return {}
    except Exception as e:
        logging.error(f"[load_probabilities_csv] Erreur lors de la lecture de {csv_path}: {e}")
        return {}

def run_auto_select_once_per_day(state): # state n'est plus utilisé pour la condition ici
    logging.info(f"[MAIN run_auto_select] Tentative d'exécution de {AUTO_SELECT_SCRIPT_PATH}")
    if not os.path.exists(AUTO_SELECT_SCRIPT_PATH):
        logging.error(f"[MAIN run_auto_select] Script {AUTO_SELECT_SCRIPT_PATH} introuvable.")
        return False
    try:
        python_executable = sys.executable 
        process = subprocess.run([python_executable, AUTO_SELECT_SCRIPT_PATH], 
                                 check=True, capture_output=True, text=True, cwd=PROJECT_ROOT)
        logging.info(f"[MAIN run_auto_select] {os.path.basename(AUTO_SELECT_SCRIPT_PATH)} exécuté avec succès.")
        if process.stdout:
            logging.info(f"[MAIN run_auto_select] Stdout:\n{process.stdout.strip()}")
        if process.stderr:
             logging.warning(f"[MAIN run_auto_select] Stderr:\n{process.stderr.strip()}")
        return True 
    except subprocess.CalledProcessError as e:
        logging.error(f"[MAIN run_auto_select] Erreur lors de l'exécution de {os.path.basename(AUTO_SELECT_SCRIPT_PATH)} (code: {e.returncode}): {e}")
        if hasattr(e, 'stdout') and e.stdout: logging.error(f"[MAIN run_auto_select] Stdout de l'erreur:\n{e.stdout.strip()}")
        if hasattr(e, 'stderr') and e.stderr: logging.error(f"[MAIN run_auto_select] Stderr de l'erreur:\n{e.stderr.strip()}")
        return False
    except FileNotFoundError:
        logging.error(f"[MAIN run_auto_select] Interpréteur Python '{python_executable}' ou script '{AUTO_SELECT_SCRIPT_PATH}' non trouvé. Vérifiez le chemin et l'environnement.")
        return False
    except Exception as e:
        logging.error(f"[MAIN run_auto_select] Exception inattendue: {e}", exc_info=True)
        return False


def daily_update_live(state, bexec):
    logging.info("[DAILY UPDATE] Start daily_update_live")
    logging.info("[DAILY UPDATE] Appel de run_auto_select_once_per_day depuis daily_update_live.")
    auto_select_success = run_auto_select_once_per_day(state)

    if not auto_select_success:
        logging.error("[DAILY UPDATE] auto_select_tokens.py n'a pas pu s'exécuter correctement ou a signalé une erreur. La liste de tokens pourrait être incomplète ou périmée.")
    else:
        logging.info("[DAILY UPDATE] auto_select_tokens.py semble s'être exécuté. Attente de 1s pour s'assurer que les écritures disque sont terminées.")
        time.sleep(1)

    if not os.path.exists(CONFIG_FILE_PATH):
        logging.error(f"[DAILY UPDATE] {CONFIG_FILE_PATH} introuvable => skip daily_update.")
        return

    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config_content_for_log = f.read()
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        logging.info(f"[DAILY UPDATE] Contenu de {CONFIG_FILE_PATH} lu (après tentative auto_select_tokens). 'extended_tokens_daily' est: {config.get('extended_tokens_daily', 'Non présente')[:200] if isinstance(config.get('extended_tokens_daily'), (list,str)) else config.get('extended_tokens_daily', 'Non présente') }")
    except Exception as e:
        logging.error(f"[DAILY UPDATE] Erreur lors de la lecture de {CONFIG_FILE_PATH} après auto_select: {e}", exc_info=True)
        return

    auto_selected_tokens = config.get("extended_tokens_daily", [])
    if not isinstance(auto_selected_tokens, list):
        logging.warning(f"[DAILY UPDATE] 'extended_tokens_daily' dans config n'est pas une liste (type: {type(auto_selected_tokens)}). Utilisation d'une liste vide.")
        auto_selected_tokens = []
    if not auto_selected_tokens and auto_select_success: # Si auto_select a réussi mais que la liste est vide
        logging.warning("[DAILY UPDATE] auto_select_tokens.py s'est exécuté mais 'extended_tokens_daily' est vide dans config.yaml. Cela peut être normal si aucun token ne correspond aux critères de sélection.")
    
    manual_tokens = config.get("tokens_daily", [])
    if not isinstance(manual_tokens, list): manual_tokens = []
        
    system_positions = list(state.get("positions_meta", {}).keys())

    final_token_list_for_fetcher = sorted(list(
        set(auto_selected_tokens).union(set(manual_tokens)).union(set(system_positions))
    ))

    logging.info(f"[DAILY UPDATE] Tokens from auto_select_tokens (config:extended_tokens_daily): {len(auto_selected_tokens)} - Aperçu: {auto_selected_tokens[:10] if auto_selected_tokens else '[]'}")
    logging.info(f"[DAILY UPDATE] Tokens from manual list (config:tokens_daily): {manual_tokens}")
    logging.info(f"[DAILY UPDATE] Tokens from current positions (state:positions_meta): {system_positions}")
    logging.info(f"[DAILY UPDATE] Final combined list for data_fetcher ({len(final_token_list_for_fetcher)} tokens) - Aperçu: {final_token_list_for_fetcher[:10] if final_token_list_for_fetcher else '[]'}")

    if not final_token_list_for_fetcher:
        logging.warning("[DAILY UPDATE] La liste finale de tokens pour data_fetcher est vide. Arrêt du daily_update.")
        # Créer un daily_inference_data.csv vide pour éviter des erreurs en aval si c'est le comportement attendu
        try:
            pd.DataFrame().to_csv(DAILY_INFERENCE_CSV_PATH, index=False)
            logging.info(f"[DAILY UPDATE] Fichier {os.path.basename(DAILY_INFERENCE_CSV_PATH)} vide créé.")
        except Exception as e_csv:
            logging.error(f"[DAILY UPDATE] Erreur lors de la création du fichier CSV vide: {e_csv}")
        return

    config_for_temp = config.copy()
    config_for_temp["extended_tokens_daily"] = final_token_list_for_fetcher

    with open(CONFIG_TEMP_FILE_PATH, "w") as fw:
        yaml.safe_dump(config_for_temp, fw, sort_keys=False)
    logging.info(f"[DAILY UPDATE] {os.path.basename(CONFIG_TEMP_FILE_PATH)} créé avec {len(final_token_list_for_fetcher)} tokens dans extended_tokens_daily.")

    strat = config.get("strategy", {})
    sell_threshold = strat.get("sell_threshold", 0.3)
    try: 
        big_gain_pct = float(strat.get("big_gain_exception_pct", 3.0)) # Default 3.0 (3x)
    except ValueError:
        logging.error(f"[DAILY UPDATE] Valeur invalide pour big_gain_exception_pct: {strat.get('big_gain_exception_pct')}. Utilisation de 3.0.")
        big_gain_pct = 3.0
    buy_threshold  = strat.get("buy_threshold", 0.5)

    MIN_VALUE_TO_SELL    = 5.0   
    MAX_VALUE_TO_SKIP_BUY = 20.0

    python_executable = sys.executable
    try:
        process_df = subprocess.run(
            [python_executable, DATA_FETCHER_SCRIPT_PATH, "--config", CONFIG_TEMP_FILE_PATH],
            check=True, capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        logging.info(f"[DAILY UPDATE] {os.path.basename(DATA_FETCHER_SCRIPT_PATH)} exécuté avec succès.")
        if process_df.stdout: logging.debug(f"[DAILY UPDATE] data_fetcher stdout:\n{process_df.stdout.strip()}")
        if process_df.stderr: logging.warning(f"[DAILY UPDATE] data_fetcher stderr:\n{process_df.stderr.strip()}")
    except subprocess.CalledProcessError as e:
        logging.error(f"[DAILY UPDATE] {os.path.basename(DATA_FETCHER_SCRIPT_PATH)} a échoué (code: {e.returncode}).")
        if hasattr(e, 'stdout') and e.stdout: logging.error(f"[DAILY UPDATE] data_fetcher stdout de l'erreur:\n{e.stdout.strip()}")
        if hasattr(e, 'stderr') and e.stderr: logging.error(f"[DAILY UPDATE] data_fetcher stderr de l'erreur:\n{e.stderr.strip()}")
        return
    except Exception as e:
        logging.error(f"[DAILY UPDATE] Exception lors de l'appel à {os.path.basename(DATA_FETCHER_SCRIPT_PATH)}: {e}", exc_info=True)
        return

    if (not os.path.exists(DAILY_INFERENCE_CSV_PATH) 
        or os.path.getsize(DAILY_INFERENCE_CSV_PATH) < 10):
        logging.warning(
            f"[DAILY UPDATE] {os.path.basename(DAILY_INFERENCE_CSV_PATH)} introuvable ou vide après data_fetcher => skip ml_decision."
        )
        return

    try:
        process_ml = subprocess.run([python_executable, ML_DECISION_SCRIPT_PATH], 
                                    check=True, capture_output=True, text=True, cwd=PROJECT_ROOT)
        logging.info(f"[DAILY UPDATE] {os.path.basename(ML_DECISION_SCRIPT_PATH)} exécuté avec succès.")
        if process_ml.stdout: logging.debug(f"[DAILY UPDATE] ml_decision stdout:\n{process_ml.stdout.strip()}")
        if process_ml.stderr: logging.warning(f"[DAILY UPDATE] ml_decision stderr:\n{process_ml.stderr.strip()}")
    except subprocess.CalledProcessError as e:
        logging.error(f"[DAILY UPDATE] {os.path.basename(ML_DECISION_SCRIPT_PATH)} a échoué (code: {e.returncode}).")
        if hasattr(e, 'stdout') and e.stdout: logging.error(f"[DAILY UPDATE] ml_decision stdout de l'erreur:\n{e.stdout.strip()}")
        if hasattr(e, 'stderr') and e.stderr: logging.error(f"[DAILY UPDATE] ml_decision stderr de l'erreur:\n{e.stderr.strip()}")
        return
    except Exception as e:
        logging.error(f"[DAILY UPDATE] Exception lors de l'appel à {os.path.basename(ML_DECISION_SCRIPT_PATH)}: {e}", exc_info=True)
        return

    prob_map = load_probabilities_csv() 
    logging.info(f"[DAILY UPDATE] Tokens considérés pour fetch (count): {len(final_token_list_for_fetcher)}, prob_map.size={len(prob_map)}")

    try:
        account_info = bexec.client.get_account()
    except Exception as e:
        logging.error(f"[DAILY UPDATE] get_account => {e}")
        return

    balances     = account_info.get("balances", [])
    holdings     = {}
    USDC_balance = 0.0
    for b in balances:
        asset = b["asset"]
        try:
            qty   = float(b.get("free", 0.0)) + float(b.get("locked", 0.0))
        except ValueError:
            logging.warning(f"[DAILY UPDATE] Impossible de parser free/locked pour {asset}. Ignoré.")
            continue
        if asset.upper() == "USDC":
            USDC_balance = qty
        elif qty > 0:
            holdings[asset] = qty
    logging.info(f"[DAILY UPDATE] Holdings actuels: {holdings}, USDC: {USDC_balance:.2f}")

    assets_sold_this_cycle = []
    for asset, real_qty in list(holdings.items()): 
        if asset.upper() in ["USDC","BTC","FDUSD"]:
            logging.debug(f"[DAILY SELL] Skip stable/BTC/FDUSD => {asset}")
            continue
        
        current_px = bexec.get_symbol_price(asset)
        if current_px <= 0:
            logging.warning(f"[DAILY SELL CHECK] {asset}, prix invalide ou nul ({current_px}). Impossible d'évaluer pour la vente.")
            continue

        val_in_usd = current_px * real_qty
        prob = prob_map.get(asset, None)
        
        logging.info(f"[DAILY SELL CHECK] {asset}, Val: {val_in_usd:.2f} USDC, Qty: {real_qty}, Px: {current_px:.4f}, Prob: {prob if prob is not None else 'N/A'}")

        if prob is None:
            logging.info(f"[DAILY SELL] Skip {asset} => probabilité non trouvée.")
            continue
            
        if val_in_usd >= MIN_VALUE_TO_SELL and prob < sell_threshold:
            meta = state.get("positions_meta", {}).get(asset, {})
            entry_px = meta.get("entry_px", 0.0)
            
            perform_sell = True
            if entry_px > 0:
                ratio    = current_px / entry_px
                did_skip = meta.get("did_skip_sell_once", False)
                if ratio >= big_gain_pct and not did_skip:
                    meta["did_skip_sell_once"] = True
                    state.setdefault("positions_meta", {})[asset] = meta
                    logging.info(f"[DAILY SELL] SKIP VENTE (BIG GAIN EXCEPTION): {asset}, ratio={ratio:.2f} >= {big_gain_pct:.2f}. Marqué pour ne plus skipper.")
                    perform_sell = False

            if perform_sell:
                logging.info(f"[DAILY SELL] Condition de vente remplie pour {asset} (Prob: {prob:.2f} < {sell_threshold}, Val: {val_in_usd:.2f} >= {MIN_VALUE_TO_SELL}).")
                sold_val = bexec.sell_all(asset, real_qty)
                logging.info(f"[DAILY SELL LIVE] {asset}, vendu pour ~{sold_val:.2f} USDC.")
                if asset in state.get("positions_meta", {}):
                    del state["positions_meta"][asset]
                assets_sold_this_cycle.append(asset)
        else:
            logging.debug(f"[DAILY SELL] Skip vente {asset}. Conditions non remplies (Val: {val_in_usd:.2f}, Prob: {prob}, SellThr: {sell_threshold}).")
    
    if assets_sold_this_cycle: 
        save_state(state) 
        logging.info(f"[DAILY UPDATE] État sauvegardé après la phase de VENTE. Tokens vendus: {assets_sold_this_cycle}")

    logging.info("[DAILY UPDATE] Attente de 180s (3min) pour finalisation des ventes et libération USDC.")
    time.sleep(180)

    try:
        account_info_after_sell = bexec.client.get_account()
    except Exception as e:
        logging.error(f"[DAILY UPDATE] get_account après attente a échoué: {e}")
        return

    balances_after_sell = account_info_after_sell.get("balances", [])
    new_holdings      = {}
    new_USDC_balance  = 0.0
    for b_as in balances_after_sell:
        asset = b_as["asset"]
        try:
            qty   = float(b_as.get("free", 0.0)) + float(b_as.get("locked", 0.0))
        except ValueError: continue
        if asset.upper() == "USDC": new_USDC_balance = qty
        elif qty > 0: new_holdings[asset] = qty
    logging.info(f"[DAILY UPDATE] Après attente => Holdings: {new_holdings}, USDC: {new_USDC_balance:.2f}")

    buy_candidates_source_list = final_token_list_for_fetcher
    buy_candidates = []
    for sym in buy_candidates_source_list:
        p = prob_map.get(sym, None)
        logging.debug(f"[DAILY BUY CHECK] Token: {sym}, Probabilité: {p if p is not None else 'N/A'}")

        if p is None or p < buy_threshold:
            if p is None: logging.debug(f"[DAILY BUY SKIP] {sym}: Probabilité non trouvée.")
            else: logging.debug(f"[DAILY BUY SKIP] {sym}: Probabilité {p:.2f} < seuil d'achat {buy_threshold:.2f}.")
            continue
        
        current_quantity_held = new_holdings.get(sym, 0.0)
        if current_quantity_held > 0:
            price_for_value_check = bexec.get_symbol_price(sym)
            if price_for_value_check > 0:
                value_held = price_for_value_check * current_quantity_held
                if value_held > MAX_VALUE_TO_SKIP_BUY:
                    logging.info(f"[DAILY BUY SKIP] {sym}: Déjà en portefeuille avec une valeur de {value_held:.2f} USDC (> {MAX_VALUE_TO_SKIP_BUY} USDC).")
                    continue
            else:
                logging.warning(f"[DAILY BUY CHECK] {sym}: Impossible de récupérer le prix pour vérifier la valeur détenue. Achat autorisé si prob OK.")
        buy_candidates.append((sym, p))

    buy_candidates.sort(key=lambda x: x[1], reverse=True)
    top3_buy_candidates = buy_candidates[:3]
    logging.info(f"[DAILY BUY SELECT] Top 3 candidats pour achat: {top3_buy_candidates}")

    assets_bought_this_cycle = []
    if top3_buy_candidates and new_USDC_balance > 10:
        usdc_to_allocate_total = new_USDC_balance * 0.99 
        num_buys_to_make = len(top3_buy_candidates)
        logging.info(f"[DAILY BUY] Allocation de {usdc_to_allocate_total:.2f} USDC pour {num_buys_to_make} token(s).")

        for i, (sym, p_val) in enumerate(top3_buy_candidates, start=1):
            remaining_tokens_to_buy = num_buys_to_make - i + 1
            if usdc_to_allocate_total < 10 or remaining_tokens_to_buy == 0 : 
                logging.info("[DAILY BUY] Reliquat USDC < 10 ou plus de tokens à acheter. Arrêt des achats.")
                break
            
            usdc_per_buy = usdc_to_allocate_total / remaining_tokens_to_buy 
            
            logging.info(f"[DAILY BUY EXEC] Tentative d'achat de {sym} avec ~{usdc_per_buy:.2f} USDC (Prob: {p_val:.2f}).")
            qty_bought, price_bought, cost_of_buy = bexec.buy(sym, usdc_per_buy)
            
            if qty_bought > 0 and cost_of_buy > 0:
                logging.info(f"[DAILY BUY EXEC SUCCESS] {sym}: Acheté {qty_bought:.4f} pour {cost_of_buy:.2f} USDC @ {price_bought:.4f}")
                state.setdefault("positions_meta", {})[sym] = {
                    "entry_px": price_bought, "did_skip_sell_once": False,
                    "partial_sold": False, "max_price": price_bought
                }
                usdc_to_allocate_total -= cost_of_buy
                assets_bought_this_cycle.append(sym)
            else:
                logging.warning(f"[DAILY BUY EXEC FAILED/SKIPPED] {sym}. Achat non effectué ou quantité nulle.")
        
        if assets_bought_this_cycle: 
            save_state(state)
            logging.info(f"[DAILY UPDATE] État sauvegardé après la phase d'ACHAT. Tokens achetés: {assets_bought_this_cycle}")
    else:
        if not top3_buy_candidates: logging.info("[DAILY BUY] Aucun candidat d'achat trouvé répondant aux critères.")
        if new_USDC_balance <= 10: logging.info(f"[DAILY BUY] Solde USDC ({new_USDC_balance:.2f}) insuffisant pour initier des achats.")

    logging.info("[DAILY UPDATE] Done daily_update_live")


def main():
    if not os.path.exists(CONFIG_FILE_PATH):
        print(f"[ERREUR] {CONFIG_FILE_PATH} introuvable.")
        logging.basicConfig(level=logging.ERROR) 
        logging.critical(f"[MAIN] {CONFIG_FILE_PATH} introuvable. Arrêt.")
        return

    try:
        with open(CONFIG_FILE_PATH, "r") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"[ERREUR] Impossible de lire ou parser {CONFIG_FILE_PATH}: {e}")
        logging.basicConfig(level=logging.ERROR)
        logging.critical(f"[MAIN] Impossible de lire ou parser {CONFIG_FILE_PATH}: {e}. Arrêt.")
        return

    log_config = config.get("logging", {})
    log_file_name = log_config.get("file", "bot.log")
    log_file_path = os.path.join(PROJECT_ROOT, log_file_name) 

    log_dir = os.path.dirname(log_file_path)
    if log_dir and not os.path.exists(log_dir): # S'assurer que le répertoire du log existe
        try: os.makedirs(log_dir, exist_ok=True) # exist_ok=True pour ne pas échouer s'il existe déjà
        except OSError as e: print(f"Erreur création répertoire log {log_dir}: {e}")

    logging.basicConfig(
        filename=log_file_path,
        filemode='a',
        level=getattr(logging, str(log_config.get("level", "INFO")).upper(), logging.INFO), 
        format="%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s"
    )
    logging.info("======================================================================")
    logging.info(f"[MAIN] Démarrage du bot de trading MarsShot (PID: {os.getpid()}).")
    logging.info(f"[MAIN] Version Python: {sys.version.split()[0]}")
    logging.info(f"[MAIN] Répertoire du projet: {PROJECT_ROOT}")
    logging.info(f"[MAIN] Fichier de configuration: {CONFIG_FILE_PATH}")
    logging.info(f"[MAIN] Fichier de log: {log_file_path}")
    logging.info("======================================================================")

    state = load_state() 
    logging.info(f"[MAIN] État chargé: keys={list(state.keys())}")

    try:
        binance_api_cfg = config.get("binance_api", {})
        api_key = binance_api_cfg.get("api_key")
        api_secret = binance_api_cfg.get("api_secret")
        if not api_key or not api_secret:
            raise KeyError("api_key ou api_secret manquant dans config.binance_api")
            
        bexec = TradeExecutor(api_key=api_key, api_secret=api_secret)
        logging.info("[MAIN] TradeExecutor initialisé.")
    except KeyError as e:
        logging.critical(f"[MAIN] Configuration API Binance manquante: {e}. Arrêt.")
        return
    except Exception as e:
        logging.critical(f"[MAIN] Erreur initialisation TradeExecutor: {e}. Arrêt.", exc_info=True)
        return
        
    DAILY_UPDATE_HOUR_UTC = config.get("strategy", {}).get("daily_update_hour_utc", 2)
    DAILY_UPDATE_MINUTE_UTC = config.get("strategy", {}).get("daily_update_minute_utc", 10) 

    logging.info(f"[MAIN] Boucle principale démarrée. Mise à jour quotidienne prévue à {DAILY_UPDATE_HOUR_UTC:02d}:{DAILY_UPDATE_MINUTE_UTC:02d} UTC.")

    if "last_daily_update_ts" not in state:
        state["last_daily_update_ts"] = 0 
        logging.info("[MAIN] 'last_daily_update_ts' initialisé dans l'état.")
        save_state(state) # Sauvegarder l'état initialisé

    while True:
        try:
            now_utc = datetime.datetime.now(pytz.utc)
            
            current_date_utc = now_utc.date()
            last_update_date_utc = None
            if state.get("last_daily_update_ts", 0) > 0: # S'assurer que le timestamp est valide
                last_update_date_utc = datetime.datetime.fromtimestamp(state["last_daily_update_ts"], tz=pytz.utc).date()

            if state.get("did_daily_update_today", False):
                if last_update_date_utc is None or current_date_utc > last_update_date_utc:
                    logging.info(f"[MAIN] Réinitialisation du flag 'did_daily_update_today' car nouveau jour UTC ({current_date_utc}) et dernière màj ({last_update_date_utc}).")
                    state["did_daily_update_today"] = False
                    save_state(state)

            if (now_utc.hour == DAILY_UPDATE_HOUR_UTC and
                now_utc.minute == DAILY_UPDATE_MINUTE_UTC and
                not state.get("did_daily_update_today", False)):
                
                logging.info(f"[MAIN] Déclenchement de daily_update_live (heure planifiée: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}).")
                daily_update_live(state, bexec)
                state["did_daily_update_today"] = True
                state["last_daily_update_ts"] = time.time() 
                save_state(state)
                logging.info("[MAIN] daily_update_live terminé et flag positionné.")

            last_risk_check_ts = state.get("last_risk_check_ts", 0)
            check_interval = config.get("strategy", {}).get("check_interval_seconds", 300)
            
            current_time_for_check = time.time()
            if current_time_for_check - last_risk_check_ts >= check_interval:
                logging.info(f"[MAIN] Exécution de intraday_check_real() (dernier check il y a {current_time_for_check - last_risk_check_ts:.0f}s).")
                intraday_check_real(state, bexec, config)
                state["last_risk_check_ts"] = current_time_for_check 
                save_state(state)

        except KeyboardInterrupt:
            logging.info("[MAIN] Interruption clavier détectée. Arrêt du bot.")
            break
        except Exception as e:
            logging.error(f"[MAIN ERROR] Erreur inattendue dans la boucle principale: {e}", exc_info=True)
            time.sleep(60) 

        time.sleep(10)
    
    logging.info("[MAIN] Boucle principale terminée.")

if __name__ == "__main__":
    main()

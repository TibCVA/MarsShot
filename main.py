#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import logging
import datetime
import yaml
import os
import pytz
import subprocess
import json # Pour parser la sortie JSON de auto_select_tokens
import sys

from modules.trade_executor import TradeExecutor
from modules.positions_store import load_state, save_state
from modules.risk_manager import intraday_check_real

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.yaml")
CONFIG_TEMP_FILE_PATH = os.path.join(PROJECT_ROOT, "config_temp.yaml")
DAILY_PROBABILITIES_CSV_PATH = os.path.join(PROJECT_ROOT, "daily_probabilities.csv")
DAILY_INFERENCE_CSV_PATH = os.path.join(PROJECT_ROOT, "daily_inference_data.csv")
AUTO_SELECT_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "auto_select_tokens.py")
DATA_FETCHER_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "modules", "data_fetcher.py")
ML_DECISION_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "modules", "ml_decision.py")

logger = logging.getLogger(__name__)

def load_probabilities_csv(csv_path=DAILY_PROBABILITIES_CSV_PATH):
    # ... (inchangé par rapport à votre dernière version) ...
    import pandas as pd
    if not os.path.exists(csv_path):
        logger.warning(f"Fichier de probabilités {csv_path} introuvable => retour de {{}}")
        return {}
    try:
        df = pd.read_csv(csv_path)
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


def run_auto_select_once_per_day(state_unused):
    """Retourne la liste des tokens sélectionnés via auto_select_tokens.

    La fonction tente d'abord d'importer ``auto_select_tokens`` et d'exécuter
    sa logique directement pour récupérer la liste des meilleurs tokens. En cas
    d'échec, un fallback via ``subprocess`` est effectué. ``None`` est renvoyé si
    aucune liste n'a pu être obtenue.
    """

    logger.info(
        f"Tentative d'exécution de {AUTO_SELECT_SCRIPT_PATH} pour la sélection automatique des tokens."
    )

    selected_tokens = None

    # --------------------------------------------------------------
    # 1) Tentative via import direct du module auto_select_tokens
    # --------------------------------------------------------------
    try:
        import auto_select_tokens as ast

        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f_cfg:
            cfg = yaml.safe_load(f_cfg)

        api_key = cfg.get("binance_api", {}).get("api_key")
        api_secret = cfg.get("binance_api", {}).get("api_secret")
        top_n = cfg.get("strategy", {}).get("auto_select_top_n", 60)

        if api_key and api_secret:
            client = ast.Client(api_key, api_secret)
            client.ping()
            selected_tokens = ast.select_top_tokens(client, top_n=top_n)
            ast.update_config_with_new_tokens(CONFIG_FILE_PATH, selected_tokens)
            logger.info(
                f"Sélection interne réussie via import: {len(selected_tokens)} tokens."
            )
        else:
            logger.error(
                "Clés API Binance manquantes dans la configuration pour la sélection interne."
            )
    except Exception as e:
        logger.error(
            "Sélection interne via import de auto_select_tokens échouée: %s",
            e,
            exc_info=True,
        )
        selected_tokens = None

    if selected_tokens:
        return selected_tokens

    # --------------------------------------------------------------
    # 2) Fallback : exécution du script via subprocess
    # --------------------------------------------------------------
    if not os.path.exists(AUTO_SELECT_SCRIPT_PATH):
        logger.error(f"Script {AUTO_SELECT_SCRIPT_PATH} introuvable.")
        return None

    try:
        python_executable = sys.executable
        process = subprocess.run(
            [python_executable, AUTO_SELECT_SCRIPT_PATH],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        if process.stderr:
            logger.info(
                f"Stderr (logs) de {os.path.basename(AUTO_SELECT_SCRIPT_PATH)}:\n{process.stderr.strip()}"
            )

        if process.stdout:
            logger.info(
                f"Stdout de {os.path.basename(AUTO_SELECT_SCRIPT_PATH)}:\n{process.stdout.strip()}"
            )
            for line in process.stdout.strip().splitlines():
                if line.startswith("JSON_OUTPUT:"):
                    try:
                        json_str = line.replace("JSON_OUTPUT:", "").strip()
                        payload = json.loads(json_str)
                        if payload.get("status") == "ok":
                            selected_tokens = payload.get("tokens", [])
                            logger.info(
                                f"{len(selected_tokens)} tokens récupérés depuis la sortie de auto_select_tokens.py."
                            )
                        else:
                            logger.error(
                                f"auto_select_tokens.py a signalé une erreur: {payload.get('message', 'Message non spécifié')}"
                            )
                        break
                    except json.JSONDecodeError as e_json:
                        logger.error(
                            f"Impossible de parser la sortie JSON de auto_select_tokens.py: {e_json}. Sortie: {line}"
                        )
                    except Exception as e_payload:
                        logger.error(
                            f"Erreur lors du traitement du payload JSON de auto_select_tokens.py: {e_payload}."
                        )

        if process.returncode != 0:
            logger.error(
                f"{os.path.basename(AUTO_SELECT_SCRIPT_PATH)} s'est terminé avec le code d'erreur {process.returncode}."
            )

        return selected_tokens

    except Exception as e:
        logger.error(
            "Exception inattendue lors de l'exécution de %s: %s",
            os.path.basename(AUTO_SELECT_SCRIPT_PATH),
            e,
            exc_info=True,
        )
        return None


def daily_update_live(state, bexec):
    logger.info("Début de daily_update_live.")

    logger.info("Appel de run_auto_select_once_per_day...")
    # Récupérer la liste des tokens directement depuis la fonction
    auto_selected_tokens_from_script = run_auto_select_once_per_day(state) 

    # Attendre un peu pour que les écritures sur config.yaml par auto_select_tokens.py (s'il y en a) se terminent.
    if auto_selected_tokens_from_script is not None: # Si le script a au moins tenté de s'exécuter
        logger.info("Attente de 1s pour la synchronisation disque de config.yaml.")
        time.sleep(1)

    if not os.path.exists(CONFIG_FILE_PATH):
        logger.error(f"{CONFIG_FILE_PATH} introuvable. Arrêt de daily_update_live.")
        return

    try:
        logger.info(f"Lecture de {CONFIG_FILE_PATH}...")
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        # Log pour vérifier si la mise à jour de config.yaml par auto_select_tokens.py est visible
        cfg_extended_tokens = config.get('extended_tokens_daily', 'Non présente ou vide')
        logger.info(f"'extended_tokens_daily' lu depuis {CONFIG_FILE_PATH}: {str(cfg_extended_tokens)[:200]}...")
    except Exception as e:
        logger.error(f"Erreur lors de la lecture de {CONFIG_FILE_PATH}: {e}", exc_info=True)
        return

    # Utiliser la liste retournée par le script en priorité.
    # Si elle est None (échec majeur du script), essayer de lire depuis config.yaml comme fallback.
    if auto_selected_tokens_from_script is not None:
        auto_selected_tokens = auto_selected_tokens_from_script
        logger.info(f"Utilisation de la liste de tokens retournée par auto_select_tokens.py ({len(auto_selected_tokens)} tokens).")
    else:
        logger.warning("auto_select_tokens.py n'a pas retourné de liste de tokens. Tentative de lecture depuis config.yaml (extended_tokens_daily).")
        auto_selected_tokens = config.get("extended_tokens_daily", [])
        if not isinstance(auto_selected_tokens, list):
            logger.warning(f"'extended_tokens_daily' dans config (fallback) n'est pas une liste. Utilisation d'une liste vide.")
            auto_selected_tokens = []
    
    manual_tokens = config.get("tokens_daily", [])
    if not isinstance(manual_tokens, list): manual_tokens = []
        
    system_positions = list(state.get("positions_meta", {}).keys())

    final_token_list_for_fetcher = sorted(list( 
        set(auto_selected_tokens).union(set(manual_tokens)).union(set(system_positions))
    ))

    logger.info(f"Tokens from auto_select_script (direct return or fallback from config): {len(auto_selected_tokens)} - Aperçu: {str(auto_selected_tokens[:10]) if auto_selected_tokens else '[]'}")
    logger.info(f"Tokens from manual list (config:tokens_daily): {manual_tokens}")
    logger.info(f"Tokens from current positions (state:positions_meta): {system_positions}")
    logger.info(f"Liste finale combinée pour data_fetcher ({len(final_token_list_for_fetcher)} tokens) - Aperçu: {str(final_token_list_for_fetcher[:10]) if final_token_list_for_fetcher else '[]'}")

    if not final_token_list_for_fetcher:
        logger.warning("La liste finale de tokens pour data_fetcher est vide. Arrêt du daily_update.")
        try:
            pd.DataFrame().to_csv(DAILY_INFERENCE_CSV_PATH, index=False) # Assurez-vous que pandas est importé si vous l'utilisez ici
            logger.info(f"Fichier {os.path.basename(DAILY_INFERENCE_CSV_PATH)} vide créé.")
        except Exception as e_csv:
            logger.error(f"Erreur lors de la création du fichier CSV vide {os.path.basename(DAILY_INFERENCE_CSV_PATH)}: {e_csv}")
        return

    config_for_temp = config.copy() 
    config_for_temp["extended_tokens_daily"] = final_token_list_for_fetcher

    with open(CONFIG_TEMP_FILE_PATH, "w", encoding="utf-8") as fw: 
        yaml.safe_dump(config_for_temp, fw, sort_keys=False)
    logger.info(f"{os.path.basename(CONFIG_TEMP_FILE_PATH)} créé avec {len(final_token_list_for_fetcher)} tokens dans extended_tokens_daily.")

    # --- Le reste de la fonction daily_update_live (stratégie, data_fetcher, ml_decision, SELL, BUY) ---
    # --- est identique à la version précédente que je vous ai fournie. ---
    # --- Je ne la recopie pas ici pour la concision. ---
    # --- Assurez-vous d'utiliser cette version avec les appels subprocess robustes et logging. ---

    strat = config.get("strategy", {})
    sell_threshold = strat.get("sell_threshold", 0.3)
    try: 
        big_gain_pct = float(strat.get("big_gain_exception_pct", 3.0)) 
    except ValueError:
        logger.error(f"Valeur invalide pour big_gain_exception_pct: {strat.get('big_gain_exception_pct')}. Utilisation de 3.0.")
        big_gain_pct = 3.0
    buy_threshold  = strat.get("buy_threshold", 0.5)

    MIN_VALUE_TO_SELL    = 5.0   
    MAX_VALUE_TO_SKIP_BUY = 20.0

    python_executable = sys.executable
    try:
        logger.info(f"Exécution de {os.path.basename(DATA_FETCHER_SCRIPT_PATH)} avec {CONFIG_TEMP_FILE_PATH}")
        process_df = subprocess.run(
            [python_executable, DATA_FETCHER_SCRIPT_PATH, "--config", CONFIG_TEMP_FILE_PATH],
            check=True, capture_output=True, text=True, cwd=PROJECT_ROOT
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
        logger.error(f"Exception lors de l'appel à {os.path.basename(DATA_FETCHER_SCRIPT_PATH)}: {e}", exc_info=True)
        return

    if (not os.path.exists(DAILY_INFERENCE_CSV_PATH) 
        or os.path.getsize(DAILY_INFERENCE_CSV_PATH) < 10):
        logger.warning(
            f"{os.path.basename(DAILY_INFERENCE_CSV_PATH)} introuvable ou vide après data_fetcher => skip ml_decision."
        )
        return

    try:
        logger.info(f"Exécution de {os.path.basename(ML_DECISION_SCRIPT_PATH)}")
        process_ml = subprocess.run([python_executable, ML_DECISION_SCRIPT_PATH], 
                                    check=True, capture_output=True, text=True, cwd=PROJECT_ROOT)
        logger.info(f"{os.path.basename(ML_DECISION_SCRIPT_PATH)} exécuté avec succès.")
        if process_ml.stdout: logger.info(f"ml_decision stdout:\n{process_ml.stdout.strip()}")
        if process_ml.stderr: logger.warning(f"ml_decision stderr:\n{process_ml.stderr.strip()}")
    except subprocess.CalledProcessError as e:
        logger.error(f"{os.path.basename(ML_DECISION_SCRIPT_PATH)} a échoué (code: {e.returncode}).")
        if hasattr(e, 'stdout') and e.stdout: logger.error(f"ml_decision stdout de l'erreur:\n{e.stdout.strip()}")
        if hasattr(e, 'stderr') and e.stderr: logger.error(f"ml_decision stderr de l'erreur:\n{e.stderr.strip()}")
        return
    except Exception as e:
        logger.error(f"Exception lors de l'appel à {os.path.basename(ML_DECISION_SCRIPT_PATH)}: {e}", exc_info=True)
        return

    prob_map = load_probabilities_csv() 
    logger.info(f"Probabilités chargées pour {len(prob_map)} tokens. Liste de fetcher: {len(final_token_list_for_fetcher)} tokens.")

    try:
        account_info = bexec.client.get_account()
    except Exception as e:
        logger.error(f"get_account a échoué: {e}", exc_info=True)
        return

    balances = account_info.get("balances", [])
    holdings = {}
    USDC_balance = 0.0
    for b in balances:
        asset = b["asset"]
        try:
            qty = float(b.get("free", 0.0)) + float(b.get("locked", 0.0))
        except ValueError:
            logger.warning(f"Impossible de parser free/locked pour {asset}. Ignoré.")
            continue
        if asset.upper() == "USDC":
            USDC_balance = qty
        elif qty > 0:
            holdings[asset] = qty
    logger.info(f"Holdings actuels: {holdings}, Solde USDC: {USDC_balance:.2f}")

    assets_sold_this_cycle = []
    for asset, real_qty in list(holdings.items()): 
        if asset.upper() in ["USDC", "BTC", "FDUSD"]:
            logger.debug(f"Skip vente pour stable/core: {asset}")
            continue
        
        current_px = bexec.get_symbol_price(asset)
        if current_px <= 0:
            logger.warning(f"Prix invalide ou nul ({current_px}) pour {asset} lors de la vérification de vente.")
            continue

        val_in_usd = current_px * real_qty
        prob = prob_map.get(asset, None)
        
        logger.info(f"Vérification VENTE pour {asset}: Val={val_in_usd:.2f}, Qty={real_qty}, Px={current_px:.4f}, Prob={prob if prob is not None else 'N/A'}")

        if prob is None:
            logger.info(f"Skip vente {asset}: probabilité non trouvée.")
            continue
            
        if val_in_usd >= MIN_VALUE_TO_SELL and prob < sell_threshold:
            meta = state.get("positions_meta", {}).get(asset, {})
            entry_px = meta.get("entry_px", 0.0)
            
            perform_sell = True
            if entry_px > 0:
                ratio = current_px / entry_px
                did_skip = meta.get("did_skip_sell_once", False)
                if ratio >= big_gain_pct: 
                    if not did_skip:
                        meta["did_skip_sell_once"] = True
                        state.setdefault("positions_meta", {})[asset] = meta
                        logger.info(f"SKIP VENTE (BIG GAIN EXCEPTION) pour {asset}: ratio={ratio:.2f} >= {big_gain_pct:.2f}. Marqué pour ne plus skipper.")
                        perform_sell = False
                    else:
                        logger.info(f"VENTE AUTORISÉE (BIG GAIN EXCEPTION DÉJÀ UTILISÉE) pour {asset}: ratio={ratio:.2f}.")
            if perform_sell:
                logger.info(f"Condition de VENTE REMPLIE pour {asset} (Prob: {prob:.2f} < {sell_threshold}, Val: {val_in_usd:.2f} >= {MIN_VALUE_TO_SELL}). Vente en cours...")
                sold_val = bexec.sell_all(asset, real_qty)
                logger.info(f"VENTE LIVE {asset}: vendu pour ~{sold_val:.2f} USDC.")
                if asset in state.get("positions_meta", {}):
                    del state["positions_meta"][asset]
                assets_sold_this_cycle.append(asset)
        else:
            logger.debug(f"Skip vente {asset}. Conditions non remplies (Val: {val_in_usd:.2f}, Prob: {prob}, SellThr: {sell_threshold}).")
    
    if assets_sold_this_cycle: 
        save_state(state) 
        logger.info(f"État sauvegardé après phase de VENTE. Tokens vendus: {assets_sold_this_cycle}")

    logger.info("Attente de 180s pour finalisation des ventes et libération USDC.")
    time.sleep(180)

    try:
        account_info_after_sell = bexec.client.get_account()
    except Exception as e:
        logger.error(f"get_account après attente (post-vente) a échoué: {e}", exc_info=True)
        return

    balances_after_sell = account_info_after_sell.get("balances", [])
    new_holdings = {}
    new_USDC_balance = 0.0
    for b_as in balances_after_sell:
        asset = b_as["asset"]
        try:
            qty = float(b_as.get("free", 0.0)) + float(b_as.get("locked", 0.0))
        except ValueError: continue
        if asset.upper() == "USDC": new_USDC_balance = qty
        elif qty > 0: new_holdings[asset] = qty
    logger.info(f"Après attente (post-vente) => Holdings: {new_holdings}, USDC: {new_USDC_balance:.2f}")

    buy_candidates_source_list = final_token_list_for_fetcher
    buy_candidates = []
    logger.info(f"Début de la recherche de candidats pour ACHAT parmi {len(buy_candidates_source_list)} tokens.")
    for sym in buy_candidates_source_list:
        p = prob_map.get(sym, None)
        logger.debug(f"Vérification ACHAT pour {sym}: Prob={p if p is not None else 'N/A'}")

        if p is None or p < buy_threshold:
            if p is None: logger.debug(f"SKIP ACHAT {sym}: Probabilité non trouvée.")
            else: logger.debug(f"SKIP ACHAT {sym}: Probabilité {p:.2f} < seuil d'achat {buy_threshold:.2f}.")
            continue
        
        current_quantity_held = new_holdings.get(sym, 0.0)
        if current_quantity_held > 0:
            price_for_value_check = bexec.get_symbol_price(sym)
            if price_for_value_check > 0:
                value_held = price_for_value_check * current_quantity_held
                if value_held > MAX_VALUE_TO_SKIP_BUY:
                    logger.info(f"SKIP ACHAT {sym}: Déjà en portefeuille avec valeur {value_held:.2f} USDC (> {MAX_VALUE_TO_SKIP_BUY} USDC).")
                    continue
            else:
                logger.warning(f"Vérification ACHAT {sym}: Impossible de récupérer le prix pour la valeur détenue. Achat autorisé si prob OK.")
        
        logger.info(f"Candidat ACHAT: {sym} (Prob: {p:.2f})")
        buy_candidates.append((sym, p))

    buy_candidates.sort(key=lambda x: x[1], reverse=True)
    top3_buy_candidates = buy_candidates[:3]
    logger.info(f"Top {len(top3_buy_candidates)} candidats pour ACHAT: {top3_buy_candidates}")

    assets_bought_this_cycle = []
    if top3_buy_candidates and new_USDC_balance > 10:
        usdc_to_allocate_total = new_USDC_balance * 0.99 
        num_buys_to_make = len(top3_buy_candidates)
        logger.info(f"Allocation de {usdc_to_allocate_total:.2f} USDC pour {num_buys_to_make} token(s).")

        for i, (sym, p_val) in enumerate(top3_buy_candidates, start=1):
            remaining_tokens_to_buy = num_buys_to_make - i + 1
            if usdc_to_allocate_total < 10 or remaining_tokens_to_buy == 0 : 
                logger.info("Reliquat USDC < 10 ou plus de tokens à acheter dans ce cycle. Arrêt des achats.")
                break
            
            usdc_per_buy = usdc_to_allocate_total / remaining_tokens_to_buy
            if usdc_per_buy < 5: 
                logger.info(f"Allocation par achat pour {sym} ({usdc_per_buy:.2f} USDC) trop faible. Arrêt des achats.")
                break

            logger.info(f"Tentative d'ACHAT de {sym} avec ~{usdc_per_buy:.2f} USDC (Prob: {p_val:.2f}).")
            qty_bought, price_bought, cost_of_buy = bexec.buy(sym, usdc_per_buy)
            
            if qty_bought > 0 and cost_of_buy > 0:
                logger.info(f"ACHAT RÉUSSI {sym}: {qty_bought:.4f} pour {cost_of_buy:.2f} USDC @ {price_bought:.4f}")
                state.setdefault("positions_meta", {})[sym] = {
                    "entry_px": price_bought, "did_skip_sell_once": False,
                    "partial_sold": False, "max_price": price_bought
                }
                usdc_to_allocate_total -= cost_of_buy
                assets_bought_this_cycle.append(sym)
            else:
                logger.warning(f"ACHAT ÉCHOUÉ/SKIPPÉ pour {sym}. Achat non effectué ou quantité/coût nul.")
        
        if assets_bought_this_cycle: 
            save_state(state)
            logger.info(f"État sauvegardé après phase d'ACHAT. Tokens achetés: {assets_bought_this_cycle}")
    else:
        if not top3_buy_candidates: logger.info("Aucun candidat d'achat trouvé répondant aux critères.")
        if new_USDC_balance <= 10: logger.info(f"Solde USDC ({new_USDC_balance:.2f}) insuffisant pour initier des achats.")

    logger.info("daily_update_live terminé.")


def main():
    # ... (Configuration du logging et initialisations comme dans la version précédente) ...
    # ... (Le reste de la fonction main est identique à la version précédente) ...
    if not os.path.exists(CONFIG_FILE_PATH):
        print(f"[ERREUR CRITIQUE] {CONFIG_FILE_PATH} introuvable. Le bot ne peut pas démarrer.")
        logging.basicConfig(level=logging.CRITICAL) 
        logging.critical(f"[MAIN] {CONFIG_FILE_PATH} introuvable. Arrêt.")
        return

    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"[ERREUR CRITIQUE] Impossible de lire ou parser {CONFIG_FILE_PATH}: {e}. Arrêt.")
        logging.basicConfig(level=logging.CRITICAL)
        logging.critical(f"[MAIN] Impossible de lire ou parser {CONFIG_FILE_PATH}: {e}. Arrêt.")
        return

    log_config = config.get("logging", {})
    log_file_name = log_config.get("file", "bot.log") 
    log_file_path_main = os.path.join(PROJECT_ROOT, log_file_name) 

    log_dir = os.path.dirname(log_file_path_main)
    if log_dir and not os.path.exists(log_dir):
        try: os.makedirs(log_dir, exist_ok=True)
        except OSError as e: 
            print(f"Erreur création répertoire log {log_dir}: {e}. Tentative d'écriture dans le répertoire courant.")
            log_file_path_main = os.path.basename(log_file_name)

    logging.basicConfig(
        filename=log_file_path_main,
        filemode='a',
        level=getattr(logging, str(log_config.get("level", "INFO")).upper(), logging.INFO), 
        format="%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s"
    )
    logger.info("======================================================================") # Utiliser logger au lieu de logging
    logger.info(f"[MAIN] Démarrage du bot de trading MarsShot (PID: {os.getpid()}).")
    logger.info(f"[MAIN] Version Python: {sys.version.split()[0]}")
    logger.info(f"[MAIN] Répertoire du projet: {PROJECT_ROOT}")
    logger.info(f"[MAIN] Fichier de configuration: {CONFIG_FILE_PATH}")
    logger.info(f"[MAIN] Fichier de log: {log_file_path_main}")
    logger.info("======================================================================")

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
        save_state(state)

    if "last_risk_check_ts" not in state: 
        state["last_risk_check_ts"] = 0
        logger.info("'last_risk_check_ts' initialisé dans l'état.")
        save_state(state) # Sauvegarder l'état après l'initialisation des clés manquantes

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
    main()

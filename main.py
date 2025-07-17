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

# --- Imports pour le filtrage (inchangé) ---
try:
    from auto_select_tokens import get_24h_change, get_kline_change, compute_token_score
except ImportError:
    def get_24h_change(*args, **kwargs): return 0.0
    def get_kline_change(*args, **kwargs): return 0.0
    def compute_token_score(*args, **kwargs): return -1.0


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.yaml")
CONFIG_TEMP_FILE_PATH = os.path.join(PROJECT_ROOT, "config_temp.yaml")
DAILY_PROBABILITIES_CSV_PATH = os.path.join(PROJECT_ROOT, "daily_probabilities.csv")
DAILY_INFERENCE_CSV_PATH = os.path.join(PROJECT_ROOT, "daily_inference_data.csv")
AUTO_SELECT_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "auto_select_tokens.py")
DATA_FETCHER_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "modules", "data_fetcher.py")
ML_DECISION_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "modules", "ml_decision.py")

# +++ AJOUT 1 : CHEMIN VERS LE NOUVEAU FICHIER DE LOG DÉDIÉ +++
DAILY_UPDATE_LOG_FILE = os.path.join(PROJECT_ROOT, "daily_update.log")

# Logger global (pour les messages généraux du bot)
logger = logging.getLogger(__name__)
# Logger dédié pour le cycle de mise à jour quotidienne
daily_logger = logging.getLogger('daily_update')

def setup_daily_logger():
    """Configure le logger dédié pour écraser le fichier à chaque cycle."""
    # Retirer les anciens handlers pour éviter les logs dupliqués
    for handler in daily_logger.handlers[:]:
        daily_logger.removeHandler(handler)
    
    # Configurer le nouveau handler pour écrire en mode 'w' (écrasement)
    file_handler = logging.FileHandler(DAILY_UPDATE_LOG_FILE, mode='w', encoding='utf-8')
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] - %(message)s")
    file_handler.setFormatter(formatter)
    
    daily_logger.addHandler(file_handler)
    daily_logger.setLevel(logging.INFO)
    daily_logger.propagate = False # Empêche les logs de remonter au logger racine

def load_probabilities_csv(csv_path=DAILY_PROBABILITIES_CSV_PATH):
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


def select_top_performers_from_list(client, token_list, top_n=150):
    """
    Calcule le score de performance et renvoie les 'top_n' meilleurs.
    Inclut des pauses pour éviter les rate limits de l'API.
    """
    daily_logger.info(f"Début du calcul de performance sur {len(token_list)} tokens pour sélectionner le top {top_n}.")
    scored_tokens = []
    for i, token in enumerate(token_list):
        if i > 0 and i % 20 == 0:
            daily_logger.debug(f"Pause de 1 seconde après avoir traité {i} tokens...")
            time.sleep(1)
        pair_symbol = f"{token.upper()}USDC"
        try:
            p24 = get_24h_change(client, pair_symbol)
            p7 = get_kline_change(client, pair_symbol, days=7)
            score = compute_token_score(p24, p7, 0.0)
            scored_tokens.append({"symbol": token, "score": score})
            daily_logger.debug(f"Token {token}: p7d={p7:.2%}, p24h={p24:.2%}, Score={score:.4f}")
        except Exception as e:
            daily_logger.warning(f"Impossible de calculer le score pour {token} (paire: {pair_symbol}). Erreur: {e}. Token ignoré du classement.")
    
    scored_tokens.sort(key=lambda x: x["score"], reverse=True)
    top_performers = [item["symbol"] for item in scored_tokens[:top_n]]
    
    daily_logger.info(f"Calcul de performance terminé. {len(top_performers)} tokens retenus.")
    top_5_with_scores = [(item['symbol'], round(item.get('score', 0), 4)) for item in scored_tokens[:5]]
    daily_logger.info(f"Top 5 performers (score): {top_5_with_scores}")
    
    return top_performers


def daily_update_live(state, bexec):
    # +++ SETUP DU LOGGER DÉDIÉ AU DÉBUT DU CYCLE +++
    setup_daily_logger()
    daily_logger.info("========== DÉBUT DU CYCLE DAILY UPDATE LIVE ==========")
    
    daily_logger.info("Étape 1: Sélection des tokens via auto_select_tokens.py...")
    auto_selected_tokens_from_script = run_auto_select_once_per_day(state) 
    daily_logger.info(f"auto_select_tokens.py a retourné {len(auto_selected_tokens_from_script) if auto_selected_tokens_from_script else 0} token(s).")
    
    if auto_selected_tokens_from_script is not None:
        time.sleep(1)

    if not os.path.exists(CONFIG_FILE_PATH):
        daily_logger.error(f"{CONFIG_FILE_PATH} introuvable. Arrêt.")
        return
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        daily_logger.error(f"Erreur lecture {CONFIG_FILE_PATH}: {e}", exc_info=True)
        return

    if auto_selected_tokens_from_script is not None:
        auto_selected_tokens = auto_selected_tokens_from_script
    else:
        auto_selected_tokens = config.get("extended_tokens_daily", [])
        if not isinstance(auto_selected_tokens, list):
            auto_selected_tokens = []
    
    manual_tokens = config.get("tokens_daily", [])
    if not isinstance(manual_tokens, list): manual_tokens = []
        
    system_positions = list(state.get("positions_meta", {}).keys())

    final_token_list_for_fetcher = sorted(list( 
        set(auto_selected_tokens).union(set(manual_tokens)).union(set(system_positions))
    ))

    daily_logger.info(f"Liste de tokens manuels (config): {len(manual_tokens)}")
    daily_logger.info(f"Liste de positions détenues (state): {len(system_positions)} - {system_positions}")
    daily_logger.info(f"Liste finale pour la collecte de données : {len(final_token_list_for_fetcher)} tokens.")
    
    if not final_token_list_for_fetcher:
        daily_logger.warning("Liste de tokens pour data_fetcher est vide. Arrêt du cycle.")
        # L'import de pandas est déjà fait dans load_probabilities_csv, pas besoin de le refaire
        import pandas as pd
        pd.DataFrame().to_csv(DAILY_INFERENCE_CSV_PATH, index=False)
        return

    config_for_temp = config.copy() 
    config_for_temp["extended_tokens_daily"] = final_token_list_for_fetcher

    with open(CONFIG_TEMP_FILE_PATH, "w", encoding="utf-8") as fw: 
        yaml.safe_dump(config_for_temp, fw, sort_keys=False)
    
    daily_logger.info("Étape 2: Lancement de data_fetcher.py...")
    python_executable = sys.executable
    try:
        process_df = subprocess.run(
            [python_executable, DATA_FETCHER_SCRIPT_PATH, "--config", CONFIG_TEMP_FILE_PATH],
            check=True, capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        daily_logger.info("data_fetcher.py terminé avec succès.")
        if process_df.stderr: daily_logger.warning(f"data_fetcher.py stderr: {process_df.stderr.strip()}")
    except subprocess.CalledProcessError as e:
        daily_logger.error(f"data_fetcher.py a échoué. Stderr: {e.stderr}")
        return
    
    daily_logger.info("Étape 3: Lancement de ml_decision.py...")
    try:
        process_ml = subprocess.run([python_executable, ML_DECISION_SCRIPT_PATH], 
                                    check=True, capture_output=True, text=True, cwd=PROJECT_ROOT)
        daily_logger.info("ml_decision.py terminé avec succès.")
        if process_ml.stderr: daily_logger.warning(f"ml_decision.py stderr: {process_ml.stderr.strip()}")
    except subprocess.CalledProcessError as e:
        daily_logger.error(f"ml_decision.py a échoué. Stderr: {e.stderr}")
        return
        
    prob_map = load_probabilities_csv() 
    daily_logger.info(f"{len(prob_map)} probabilités chargées.")
    
    daily_logger.info("Étape 4: Phase de VENTE...")
    try:
        account_info = bexec.client.get_account()
        balances = account_info.get("balances", [])
    except Exception as e:
        daily_logger.error(f"get_account a échoué: {e}")
        return
    
    holdings = {}
    USDC_balance = 0.0
    for b in balances:
        asset = b["asset"]
        qty = float(b.get("free", 0.0)) + float(b.get("locked", 0.0))
        if qty > 0:
            if asset.upper() == "USDC":
                USDC_balance = qty
            else:
                holdings[asset] = qty
    daily_logger.info(f"Positions actuelles pour vérification de vente: {list(holdings.keys())}")

    strat = config.get("strategy", {})
    sell_threshold = strat.get("sell_threshold", 0.3)
    big_gain_pct = float(strat.get("big_gain_exception_pct", 3.0))
    buy_threshold  = strat.get("buy_threshold", 0.5)
    MIN_VALUE_TO_SELL    = 5.0   
    MAX_VALUE_TO_SKIP_BUY = 20.0

    assets_sold_this_cycle = []
    for asset, real_qty in list(holdings.items()): 
        if asset.upper() in ["BTC", "FDUSD"]:
            continue
        current_px = bexec.get_symbol_price(asset)
        if current_px <= 0: continue
        val_in_usd = current_px * real_qty
        prob = prob_map.get(asset, None)
        daily_logger.info(f"Vérification VENTE pour {asset}: Val={val_in_usd:.2f}, Px={current_px:.4f}, Prob={prob if prob is not None else 'N/A'}")
        if prob is None: continue
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
                        daily_logger.info(f"SKIP VENTE (BIG GAIN) pour {asset}: ratio={ratio:.2f}.")
                        perform_sell = False
                    else:
                        daily_logger.info(f"VENTE AUTORISÉE (BIG GAIN DÉJÀ UTILISÉE) pour {asset}.")
            if perform_sell:
                daily_logger.info(f"ORDRE DE VENTE: Déclenchement pour {asset} (Prob: {prob:.2f} < {sell_threshold})")
                sold_val = bexec.sell_all(asset, real_qty)
                daily_logger.info(f"VENTE EXÉCUTÉE: {asset} vendu pour ~{sold_val:.2f} USDC.")
                if asset in state.get("positions_meta", {}):
                    del state["positions_meta"][asset]
                assets_sold_this_cycle.append(asset)
    
    if assets_sold_this_cycle: 
        save_state(state) 
        daily_logger.info(f"État sauvegardé après phase de VENTE. Tokens vendus: {assets_sold_this_cycle}")

    daily_logger.info("Attente de 180s pour finalisation des ordres...")
    time.sleep(180)

    daily_logger.info("Étape 5: Phase d'ACHAT...")
    try:
        account_info_after_sell = bexec.client.get_account()
        balances_after_sell = account_info_after_sell.get("balances", [])
    except Exception as e:
        daily_logger.error(f"get_account (post-vente) a échoué: {e}")
        return

    new_holdings = {}
    new_USDC_balance = 0.0
    for b_as in balances_after_sell:
        asset = b_as["asset"]
        qty = float(b_as.get("free", 0.0)) + float(b_as.get("locked", 0.0))
        if asset.upper() == "USDC": new_USDC_balance = qty
        elif qty > 0: new_holdings[asset] = qty
    daily_logger.info(f"Solde USDC disponible pour achat: {new_USDC_balance:.2f}")

    manual_tokens_for_perf = config.get("tokens_daily", [])
    if not manual_tokens_for_perf:
        daily_logger.warning("Liste 'tokens_daily' vide, pas de filtrage de performance possible.")
        top_150_performers = []
    else:
        top_150_performers = select_top_performers_from_list(bexec.client, manual_tokens_for_perf, top_n=150)
    
    buy_candidates_source_list = top_150_performers
    daily_logger.info(f"Recherche de candidats à l'achat parmi {len(buy_candidates_source_list)} meilleurs performeurs.")

    buy_candidates = []
    for sym in buy_candidates_source_list:
        p = prob_map.get(sym, None)
        if p is None or p < buy_threshold: continue
        current_quantity_held = new_holdings.get(sym, 0.0)
        if current_quantity_held > 0:
            price_for_value_check = bexec.get_symbol_price(sym)
            if price_for_value_check > 0:
                value_held = price_for_value_check * current_quantity_held
                if value_held > MAX_VALUE_TO_SKIP_BUY:
                    daily_logger.info(f"Candidat {sym} (Prob: {p:.2f}) ignoré car déjà en portefeuille avec valeur > {MAX_VALUE_TO_SKIP_BUY} USDC.")
                    continue
        daily_logger.info(f"CANDIDAT ACHAT trouvé: {sym} (Prob: {p:.2f})")
        buy_candidates.append((sym, p))
    
    buy_candidates.sort(key=lambda x: x[1], reverse=True)
    top3_buy_candidates = buy_candidates[:3]
    daily_logger.info(f"Top {len(top3_buy_candidates)} candidats retenus pour achat: {top3_buy_candidates}")

    assets_bought_this_cycle = []
    if top3_buy_candidates and new_USDC_balance > 10:
        usdc_to_allocate_total = new_USDC_balance * 0.99 
        num_buys_to_make = len(top3_buy_candidates)
        daily_logger.info(f"Allocation de {usdc_to_allocate_total:.2f} USDC pour {num_buys_to_make} token(s).")
        for i, (sym, p_val) in enumerate(top3_buy_candidates, start=1):
            remaining_tokens_to_buy = num_buys_to_make - i + 1
            if usdc_to_allocate_total < 10 or remaining_tokens_to_buy == 0 : break
            usdc_per_buy = usdc_to_allocate_total / remaining_tokens_to_buy
            if usdc_per_buy < 5: break
            daily_logger.info(f"ORDRE D'ACHAT: Tentative pour {sym} avec ~{usdc_per_buy:.2f} USDC.")
            qty_bought, price_bought, cost_of_buy = bexec.buy(sym, usdc_per_buy)
            if qty_bought > 0 and cost_of_buy > 0:
                daily_logger.info(f"ACHAT EXÉCUTÉ: {qty_bought:.4f} {sym} pour {cost_of_buy:.2f} USDC @ {price_bought:.4f}")
                state.setdefault("positions_meta", {})[sym] = {"entry_px": price_bought, "did_skip_sell_once": False, "partial_sold": False, "max_price": price_bought}
                usdc_to_allocate_total -= cost_of_buy
                assets_bought_this_cycle.append(sym)
            else:
                daily_logger.warning(f"ACHAT ÉCHOUÉ pour {sym}.")
        
        if assets_bought_this_cycle: 
            save_state(state)
            daily_logger.info(f"État sauvegardé après phase d'ACHAT. Tokens achetés: {assets_bought_this_cycle}")
    else:
        if not top3_buy_candidates: daily_logger.info("Aucun candidat d'achat ne remplissait les conditions.")
        if new_USDC_balance <= 10: daily_logger.info("Solde USDC insuffisant pour des achats.")

    daily_logger.info("========== FIN DU CYCLE DAILY UPDATE LIVE ==========")


def main():
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
    logger.info("======================================================================")
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
        
    DAILY_UPDATE_HOUR_UTC = config.get("strategy", {}).get("daily_update_hour_utc", 09) 
    DAILY_UPDATE_MINUTE_UTC = config.get("strategy", {}).get("daily_update_minute_utc", 45) 

    logger.info(f"Boucle principale démarrée. Mise à jour quotidienne prévue à {DAILY_UPDATE_HOUR_UTC:02d}:{DAILY_UPDATE_MINUTE_UTC:02d} UTC.")

    if "last_daily_update_ts" not in state: 
        state["last_daily_update_ts"] = 0 
        logger.info("'last_daily_update_ts' initialisé dans l'état.")
        save_state(state)

    if "last_risk_check_ts" not in state: 
        state["last_risk_check_ts"] = 0
        logger.info("'last_risk_check_ts' initialisé dans l'état.")
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

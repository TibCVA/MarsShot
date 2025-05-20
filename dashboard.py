#!/usr/bin/env python3
# coding: utf-8

"""
Mini-dashboard Flask pour MarsShot.
"""

import os
import datetime
import logging
import yaml 
from flask import Flask, request, jsonify, render_template_string
import sys

# --- Configuration des Chemins (au niveau du module) ---
DASHBOARD_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH_DASH = os.path.join(DASHBOARD_PROJECT_ROOT, "config.yaml") # Pour le dashboard lui-même
MODEL_DEUXPOINTCINQ_PATH = os.path.join(DASHBOARD_PROJECT_ROOT, "model_deuxpointcinq.pkl")
MODEL_PKL_PATH = os.path.join(DASHBOARD_PROJECT_ROOT, "model.pkl")

# Logger spécifique pour le dashboard
dashboard_logger = logging.getLogger("dashboard_app")
if not dashboard_logger.hasHandlers():
    console_handler_dash = logging.StreamHandler(sys.stderr)
    formatter_dash = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    console_handler_dash.setFormatter(formatter_dash)
    dashboard_logger.addHandler(console_handler_dash)
    dashboard_logger.setLevel(logging.INFO)
    dashboard_logger.propagate = False

# Imports pour les données du dashboard
try:
    from dashboard_data import (
        get_portfolio_state, get_performance_history,
        get_trades_history, emergency_out
    )
except ImportError as e:
    dashboard_logger.error(f"Erreur critique: dashboard_data: {e}.")
    def get_portfolio_state(): return {"positions": [], "total_value_USDC": "Erreur: dashboard_data"}
    def get_performance_history(): return {}
    def get_trades_history(): return []
    def emergency_out(): dashboard_logger.error("Fonction emergency_out non disponible.")

# Imports pour la fonction "Force Daily Update"
main_module_imported_successfully = False
main_daily_update_live_func = None # Pour stocker la fonction importée
load_state_func = None
configure_main_logging_func = None
TradeExecutor_class = None

try:
    from main import daily_update_live, load_state as main_load_state, configure_main_logging as main_configure_logging
    from modules.trade_executor import TradeExecutor as ModTradeExecutor
    
    main_daily_update_live_func = daily_update_live
    load_state_func = main_load_state
    configure_main_logging_func = main_configure_logging
    TradeExecutor_class = ModTradeExecutor
    main_module_imported_successfully = True
    dashboard_logger.info("Modules de main.py et TradeExecutor importés avec succès pour le dashboard.")
except ImportError as e:
    dashboard_logger.error(f"Erreur lors de l'import des modules de main.py ou TradeExecutor pour force_daily_update: {e}. La fonction 'Forcer Daily Update' sera désactivée.", exc_info=True)


ALL_LOG_FILES_RELATIVE = ["bot.log", "data_fetcher.log", "ml_decision.log"]
NUM_LOG_LINES = 400

def tail_all_logs(num_lines=NUM_LOG_LINES):
    # ... (fonction inchangée) ...
    combined_lines = []
    for logf_relative in ALL_LOG_FILES_RELATIVE:
        actual_log_path = os.path.join(DASHBOARD_PROJECT_ROOT, logf_relative)
        if os.path.exists(actual_log_path):
            try:
                with open(actual_log_path, "r", encoding='utf-8', errors='ignore') as f: lines = f.readlines()
                lines = lines[-num_lines:]; combined_lines.append(f"\n=== [ {os.path.basename(actual_log_path)} ] ===\n"); combined_lines.extend(lines)
            except Exception as e: combined_lines.append(f"\n[LOG ERROR] Impossible de lire {actual_log_path} => {e}\n")
        else: combined_lines.append(f"\n[{os.path.basename(actual_log_path)}] n'existe pas (chemin testé: {actual_log_path}).\n")
    return "".join(combined_lines)

def get_model_version_date():
    # ... (fonction inchangée) ...
    if os.path.exists(MODEL_DEUXPOINTCINQ_PATH): fname_to_check = MODEL_DEUXPOINTCINQ_PATH
    elif os.path.exists(MODEL_PKL_PATH): fname_to_check = MODEL_PKL_PATH
    else: return "model_deuxpointcinq.pkl ou model.pkl introuvable."
    try:
        t = os.path.getmtime(fname_to_check); dt = datetime.datetime.fromtimestamp(t)
        return f"{os.path.basename(fname_to_check)} - {dt.strftime('%Y-%m-%d %H:%M:%S')}"
    except Exception as e: return f"Erreur lecture date {os.path.basename(fname_to_check)}: {e}"

app = Flask(__name__)
SECRET_PWD = os.environ.get("MARSSHOT_DASHBOARD_PWD", "SECRET123") 

TEMPLATE_HTML = r"""
# ... (VOTRE TEMPLATE HTML COMPLET ICI) ...
""" # Assurez-vous que c'est le HTML complet

def get_tokens_live():
    # ... (fonction inchangée) ...
    if os.path.exists(CONFIG_FILE_PATH_DASH):
        try:
            with open(CONFIG_FILE_PATH_DASH, "r", encoding="utf-8") as f: conf = yaml.safe_load(f)
            if "extended_tokens_daily" in conf and conf["extended_tokens_daily"]: return sorted(list(set(conf["extended_tokens_daily"])))
            elif "tokens_daily" in conf and conf["tokens_daily"]: return sorted(list(set(conf.get("tokens_daily", []))))
            else: return []
        except Exception as e: dashboard_logger.error(f"Erreur lecture {CONFIG_FILE_PATH_DASH} dans get_tokens_live: {e}"); return ["Erreur lecture config"]
    else: return [f"{os.path.basename(CONFIG_FILE_PATH_DASH)} introuvable"]

@app.route(f"/dashboard/<pwd>", methods=["GET"])
def dashboard_route(pwd): # Renommer pour éviter conflit avec nom de module
    # ... (fonction inchangée) ...
    if pwd != SECRET_PWD: return "Accès Interdit", 403
    try: pf = get_portfolio_state()
    except Exception as e: dashboard_logger.error(f"Erreur get_portfolio_state: {e}"); pf = {"positions": [], "total_value_USDC": "Erreur"}
    tokens = get_tokens_live()
    try: perf = get_performance_history()
    except Exception as e: dashboard_logger.error(f"Erreur get_performance_history: {e}"); perf = {}
    try: trades = get_trades_history()
    except Exception as e: dashboard_logger.error(f"Erreur get_trades_history: {e}"); trades = []
    model_date = get_model_version_date()
    return render_template_string( TEMPLATE_HTML, pf=pf, tokens=tokens, perf=perf, trades=trades, model_date=model_date, secret_pwd=SECRET_PWD, num_log_lines=NUM_LOG_LINES)

@app.route(f"/emergency/<pwd>", methods=["POST"])
def emergency_api(pwd):
    # ... (fonction inchangée) ...
    if pwd != SECRET_PWD: return jsonify({"message": "Accès Interdit"}), 403
    try:
        emergency_out(); dashboard_logger.info("Sortie d'urgence déclenchée via dashboard.")
        return jsonify({"message": "Sortie d'urgence déclenchée avec succès."})
    except Exception as e:
        dashboard_logger.error(f"Erreur lors de la sortie d'urgence via dashboard: {e}", exc_info=True)
        return jsonify({"message": f"Erreur sortie d'urgence: {e}"}), 500

@app.route(f"/force_daily_update/<pwd>", methods=["POST"])
def force_daily_update(pwd):
    if pwd != SECRET_PWD:
        return jsonify({"message": "Accès Interdit"}), 403

    dashboard_logger.info("Déclenchement manuel du Daily Update via le dashboard.")

    if not main_module_imported_successfully or not all([main_daily_update_live_func, load_state_func, configure_main_logging_func, TradeExecutor_class]):
        msg = "Les modules de main.py n'ont pas pu être importés correctement. 'Forcer Daily Update' est désactivé."
        dashboard_logger.error(msg)
        return jsonify({"message": msg}), 500

    try:
        if not os.path.exists(CONFIG_FILE_PATH_DASH):
            msg = f"Erreur critique: {CONFIG_FILE_PATH_DASH} (config pour dashboard) introuvable."
            dashboard_logger.error(msg); return jsonify({"message": msg}), 500
        
        with open(CONFIG_FILE_PATH_DASH, "r", encoding="utf-8") as f:
            config_main_for_call = yaml.safe_load(f)
        
        # Configurer le logging du module 'main_bot_logic' pour que ses logs aillent dans bot.log
        main_log_settings = config_main_for_call.get("logging", {})
        configure_main_logging_func(main_log_settings) 
        dashboard_logger.info("Logging pour 'main_bot_logic' (ré)configuré pour cet appel de force_daily_update.")

        state = load_state_func()
        
        binance_api_config = config_main_for_call.get("binance_api", {})
        api_key = binance_api_config.get("api_key")
        api_secret = binance_api_config.get("api_secret")

        if not api_key or not api_secret:
            msg = "Erreur de configuration: Clés API Binance manquantes."; dashboard_logger.error(msg)
            return jsonify({"message": msg}), 500

        bexec = TradeExecutor_class(api_key=api_key, api_secret=api_secret)
        dashboard_logger.info("TradeExecutor initialisé pour le forçage du daily update.")

    except Exception as e_init:
        dashboard_logger.error(f"Erreur générale initialisation pour force_daily_update: {e_init}", exc_info=True)
        return jsonify({"message": f"Erreur d'initialisation: {e_init}"}), 500

    try:
        dashboard_logger.info("Appel de main_daily_update_live_func...")
        main_daily_update_live_func(state, bexec) 
        dashboard_logger.info("main_daily_update_live_func terminé (appelé depuis dashboard).")
        return jsonify({"message": "Mise à jour quotidienne (forcée) déclenchée et semble terminée. Vérifiez les logs."})
    except RuntimeError as e_rt: 
        dashboard_logger.error(f"Erreur d'exécution (RuntimeError) dans main_daily_update_live_func: {e_rt}", exc_info=True)
        return jsonify({"message": f"Erreur d'exécution: {e_rt}"}), 500
    except Exception as e_daily:
        dashboard_logger.error(f"Erreur lors de l'exécution de main_daily_update_live_func: {e_daily}", exc_info=True)
        return jsonify({"message": f"Erreur lors de la mise à jour quotidienne forcée: {e_daily}"}), 500

@app.route(f"/logs/<pwd>", methods=["GET"])
def get_logs(pwd):
    # ... (fonction inchangée) ...
    if pwd != SECRET_PWD: return "Accès Interdit", 403
    txt = tail_all_logs(num_lines=NUM_LOG_LINES)
    return txt, 200, {"Content-Type": "text/plain; charset=utf-8"}

def run_dashboard():
    # ... (fonction inchangée) ...
    werkzeug_logger = logging.getLogger('werkzeug'); werkzeug_logger.setLevel(logging.ERROR) 
    dashboard_logger.info(f"Démarrage du serveur Flask du Dashboard sur 0.0.0.0:5000 (PID: {os.getpid()})")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False) # use_reloader=False est important

if __name__ == "__main__":
    # ... (fonction inchangée) ...
    dashboard_logger.info("Dashboard exécuté directement (__name__ == '__main__').")
    run_dashboard()

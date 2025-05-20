#!/usr/bin/env python3
# coding: utf-8

"""
Mini-dashboard Flask pour MarsShot.
Affiche plusieurs onglets, concatène les logs.
+ Bouton "Forcer daily update" qui exécute le cycle quotidien complet.
"""

import os
import datetime
import logging
import yaml 
from flask import Flask, request, jsonify, render_template_string
import sys # Pour sys.path si nécessaire pour les imports

# --- Configuration des Chemins (au niveau du module) ---
# Supposer que dashboard.py est à la racine du projet
DASHBOARD_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH_DASH = os.path.join(DASHBOARD_PROJECT_ROOT, "config.yaml")
MODEL_DEUXPOINTCINQ_PATH = os.path.join(DASHBOARD_PROJECT_ROOT, "model_deuxpointcinq.pkl")
MODEL_PKL_PATH = os.path.join(DASHBOARD_PROJECT_ROOT, "model.pkl")

# Configurer le logger pour le dashboard lui-même
dashboard_logger = logging.getLogger("dashboard_app")
if not dashboard_logger.hasHandlers():
    # Logguer les messages du dashboard sur la console pour le débogage de Flask
    # ou dans un fichier séparé si vous préférez.
    # Ne pas configurer le logger root ici pour ne pas interférer avec main.py
    console_handler_dash = logging.StreamHandler(sys.stderr)
    formatter_dash = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    console_handler_dash.setFormatter(formatter_dash)
    dashboard_logger.addHandler(console_handler_dash)
    dashboard_logger.setLevel(logging.INFO)
    dashboard_logger.propagate = False


# Imports pour les données du dashboard
try:
    from dashboard_data import (
        get_portfolio_state,
        get_performance_history,
        get_trades_history,
        emergency_out
    )
except ImportError as e:
    dashboard_logger.error(f"Erreur critique: Impossible d'importer dashboard_data: {e}. Assurez-vous que dashboard_data.py est accessible.")
    def get_portfolio_state(): return {"positions": [], "total_value_USDC": "Erreur: dashboard_data"}
    def get_performance_history(): return {}
    def get_trades_history(): return []
    def emergency_out(): dashboard_logger.error("Fonction emergency_out non disponible.")

# Imports pour la fonction "Force Daily Update"
main_module_imported_successfully = False
try:
    from main import daily_update_live as main_daily_update_live
    from main import load_state
    from main import configure_main_logging # Importer la fonction de configuration du logging de main.py
    from modules.trade_executor import TradeExecutor
    main_module_imported_successfully = True
except ImportError as e:
    dashboard_logger.error(f"Erreur lors de l'import des modules de main.py ou TradeExecutor pour force_daily_update: {e}. La fonction 'Forcer Daily Update' sera désactivée.")
    # Définir des factices pour que le reste du dashboard ne plante pas
    def main_daily_update_live(state, bexec):
        raise RuntimeError("Dépendances de main.py manquantes pour 'Forcer Daily Update'.")
    def load_state(): return {}
    def configure_main_logging(s=None): pass
    class TradeExecutor:
        def __init__(self, api_key, api_secret): pass

########################
# Logs
########################
ALL_LOG_FILES_RELATIVE = [ # Noms de fichiers relatifs à PROJECT_ROOT
    "bot.log",
    "data_fetcher.log",
    "ml_decision.log"
]
NUM_LOG_LINES = 400

def tail_all_logs(num_lines=NUM_LOG_LINES):
    combined_lines = []
    for logf_relative in ALL_LOG_FILES_RELATIVE:
        # Construire le chemin absolu basé sur DASHBOARD_PROJECT_ROOT
        actual_log_path = os.path.join(DASHBOARD_PROJECT_ROOT, logf_relative)
        
        if os.path.exists(actual_log_path):
            try:
                with open(actual_log_path, "r", encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                lines = lines[-num_lines:]
                combined_lines.append(f"\n=== [ {os.path.basename(actual_log_path)} ] ===\n")
                combined_lines.extend(lines)
            except Exception as e:
                combined_lines.append(f"\n[LOG ERROR] Impossible de lire {actual_log_path} => {e}\n")
        else:
            combined_lines.append(f"\n[{os.path.basename(actual_log_path)}] n'existe pas (chemin testé: {actual_log_path}).\n")
    return "".join(combined_lines)

def get_model_version_date():
    # ... (fonction inchangée, mais utilise MODEL_DEUXPOINTCINQ_PATH et MODEL_PKL_PATH) ...
    if os.path.exists(MODEL_DEUXPOINTCINQ_PATH): fname_to_check = MODEL_DEUXPOINTCINQ_PATH
    elif os.path.exists(MODEL_PKL_PATH): fname_to_check = MODEL_PKL_PATH
    else: return "model_deuxpointcinq.pkl ou model.pkl introuvable à la racine."
    try:
        t = os.path.getmtime(fname_to_check)
        dt = datetime.datetime.fromtimestamp(t)
        return f"{os.path.basename(fname_to_check)} - {dt.strftime('%Y-%m-%d %H:%M:%S')}"
    except Exception as e: return f"Erreur lecture date {os.path.basename(fname_to_check)}: {e}"

app = Flask(__name__)
SECRET_PWD = os.environ.get("MARSSHOT_DASHBOARD_PWD", "SECRET123") # Lire depuis env var, sinon défaut

TEMPLATE_HTML = r""" 
# ... (TEMPLATE_HTML inchangé par rapport à votre version) ...
"""

def get_tokens_live():
    # ... (fonction inchangée, mais utilise CONFIG_FILE_PATH_DASH) ...
    if os.path.exists(CONFIG_FILE_PATH_DASH):
        try:
            with open(CONFIG_FILE_PATH_DASH, "r", encoding="utf-8") as f: conf = yaml.safe_load(f)
            if "extended_tokens_daily" in conf and conf["extended_tokens_daily"]:
                return sorted(list(set(conf["extended_tokens_daily"])))
            elif "tokens_daily" in conf and conf["tokens_daily"]:
                return sorted(list(set(conf.get("tokens_daily", []))))
            else: return []
        except Exception as e:
            dashboard_logger.error(f"Erreur lecture {CONFIG_FILE_PATH_DASH} dans get_tokens_live: {e}")
            return ["Erreur lecture config"]
    else: return [f"{os.path.basename(CONFIG_FILE_PATH_DASH)} introuvable"]


@app.route(f"/dashboard/<pwd>", methods=["GET"])
def dashboard(pwd):
    # ... (fonction inchangée, mais utilise dashboard_logger) ...
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
    # ... (fonction inchangée, mais utilise dashboard_logger) ...
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

    if not main_module_imported_successfully:
        msg = "Les modules de main.py n'ont pas pu être importés. 'Forcer Daily Update' est désactivé."
        dashboard_logger.error(msg)
        return jsonify({"message": msg}), 500

    try:
        # ÉTAPE 1: Charger la configuration pour le logger de main et TradeExecutor
        if not os.path.exists(CONFIG_FILE_PATH_DASH): # Utiliser le chemin défini pour le dashboard
            msg = f"Erreur critique: {CONFIG_FILE_PATH_DASH} introuvable."
            dashboard_logger.error(msg)
            return jsonify({"message": msg}), 500
        
        with open(CONFIG_FILE_PATH_DASH, "r", encoding="utf-8") as f:
            config_main = yaml.safe_load(f) # config pour main.py
        
        # Configurer le logging de main.py pour qu'il logue dans le même fichier
        # La fonction configure_main_logging de main.py s'en charge.
        # Elle utilise le logger nommé "main_bot_logic".
        main_log_settings = config_main.get("logging", {})
        configure_main_logging(main_log_settings) # Appeler la fonction importée de main.py
        dashboard_logger.info("Logging pour 'main_bot_logic' reconfiguré pour cet appel.")

        state = load_state() # load_state est importé de main.py, il utilise son propre chemin pour bot_state.json
        
        binance_api_config = config_main.get("binance_api", {})
        api_key = binance_api_config.get("api_key")
        api_secret = binance_api_config.get("api_secret")

        if not api_key or not api_secret:
            msg = "Erreur de configuration: Clés API Binance manquantes."
            dashboard_logger.error(msg)
            return jsonify({"message": msg}), 500

        bexec = TradeExecutor(api_key=api_key, api_secret=api_secret)
        dashboard_logger.info("TradeExecutor initialisé pour le forçage du daily update.")

    except FileNotFoundError as e_fnf:
        dashboard_logger.error(f"Fichier non trouvé lors de l'initialisation pour force_daily_update: {e_fnf}", exc_info=True)
        return jsonify({"message": f"Erreur init (fichier non trouvé): {e_fnf}"}), 500
    except KeyError as e_key:
        dashboard_logger.error(f"Clé manquante dans config pour force_daily_update: {e_key}", exc_info=True)
        return jsonify({"message": f"Erreur config (clé manquante): {e_key}"}), 500
    except Exception as e_init:
        dashboard_logger.error(f"Erreur générale initialisation pour force_daily_update: {e_init}", exc_info=True)
        return jsonify({"message": f"Erreur init: {e_init}"}), 500

    # ÉTAPE 2: Appeler la fonction daily_update_live de main.py
    try:
        dashboard_logger.info("Appel de main_daily_update_live...")
        # Les logs de main_daily_update_live iront dans bot.log grâce à configure_main_logging
        main_daily_update_live(state, bexec) 
        dashboard_logger.info("main_daily_update_live terminé (appelé depuis dashboard).")
        return jsonify({"message": "Mise à jour quotidienne (forcée) déclenchée et semble terminée. Vérifiez les logs."})
    except RuntimeError as e_rt: 
        dashboard_logger.error(f"Erreur d'exécution (RuntimeError) dans main_daily_update_live: {e_rt}", exc_info=True)
        return jsonify({"message": f"Erreur d'exécution: {e_rt}"}), 500
    except Exception as e_daily:
        dashboard_logger.error(f"Erreur lors de l'exécution de main_daily_update_live: {e_daily}", exc_info=True)
        return jsonify({"message": f"Erreur lors de la mise à jour quotidienne forcée: {e_daily}"}), 500


@app.route(f"/logs/<pwd>", methods=["GET"])
def get_logs(pwd):
    # ... (fonction inchangée) ...
    if pwd != SECRET_PWD: return "Accès Interdit", 403
    txt = tail_all_logs(num_lines=NUM_LOG_LINES)
    return txt, 200, {"Content-Type": "text/plain; charset=utf-8"}

def run_dashboard():
    # ... (fonction inchangée, mais utilise dashboard_logger) ...
    werkzeug_logger = logging.getLogger('werkzeug') # Logger de Flask/Werkzeug
    werkzeug_logger.setLevel(logging.ERROR) 
    dashboard_logger.info(f"Démarrage du serveur Flask du Dashboard sur 0.0.0.0:5000 (PID: {os.getpid()})")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    # Le logger 'dashboard_app' est déjà configuré au niveau du module.
    # Pas besoin de logging.basicConfig ici si on utilise dashboard_logger.
    dashboard_logger.info("Dashboard exécuté directement (__name__ == '__main__').")
    run_dashboard()

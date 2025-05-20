#!/usr/bin/env python3
# coding: utf-8

"""
Mini-dashboard Flask pour MarsShot.
"""

import os
import datetime
import logging # Importé
import yaml  # Importé
from flask import Flask, request, jsonify, render_template_string # Importé
import sys # Importé

# --- Configuration des Chemins (au niveau du module) ---
DASHBOARD_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE_PATH_DASH = os.path.join(DASHBOARD_PROJECT_ROOT, "config.yaml")
MODEL_DEUXPOINTCINQ_PATH = os.path.join(DASHBOARD_PROJECT_ROOT, "model_deuxpointcinq.pkl")
MODEL_PKL_PATH = os.path.join(DASHBOARD_PROJECT_ROOT, "model.pkl")

# Logger spécifique pour le dashboard
dashboard_logger = logging.getLogger("dashboard_app")
if not dashboard_logger.hasHandlers():
    console_handler_dash = logging.StreamHandler(sys.stderr) # Utilise sys
    formatter_dash = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    console_handler_dash.setFormatter(formatter_dash)
    dashboard_logger.addHandler(console_handler_dash)
    dashboard_logger.setLevel(logging.INFO)
    dashboard_logger.propagate = False

# Imports pour les données du dashboard
try:
    from dashboard_data import ( # dashboard_data.py doit être dans le même répertoire ou PYTHONPATH
        get_portfolio_state, get_performance_history,
        get_trades_history, emergency_out
    )
    dashboard_logger.info("dashboard_data importé avec succès.")
except ImportError as e:
    dashboard_logger.error(f"Erreur critique: Impossible d'importer dashboard_data: {e}. Les fonctions de données seront factices.", exc_info=True)
    def get_portfolio_state(): return {"positions": [], "total_value_USDC": "Erreur: dashboard_data"}
    def get_performance_history(): return {}
    def get_trades_history(): return []
    def emergency_out(): dashboard_logger.error("Fonction emergency_out non disponible.")

# Imports pour la fonction "Force Daily Update"
main_module_imported_successfully = False
main_daily_update_live_func = None
load_state_func = None
configure_main_logging_func = None
TradeExecutor_class = None

try:
    # main.py et modules/ sont relatifs à l'emplacement de dashboard.py
    # Si dashboard.py est à la racine, et main.py aussi, et modules/ est un sous-répertoire.
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
    # Les factices sont définis ci-dessous pour que le reste du code ne plante pas à la définition
    def main_daily_update_live_func_placeholder(state, bexec): # Nom différent pour éviter conflit
        raise RuntimeError("Dépendances de main.py manquantes pour 'Forcer Daily Update'.")
    def load_state_func_placeholder(): return {}
    def configure_main_logging_func_placeholder(s=None): pass
    class TradeExecutor_class_placeholder: __init__ = lambda self, api_key, api_secret: None
    # Assigner les placeholders si l'import a échoué
    if main_daily_update_live_func is None: main_daily_update_live_func = main_daily_update_live_func_placeholder
    if load_state_func is None: load_state_func = load_state_func_placeholder
    if configure_main_logging_func is None: configure_main_logging_func = configure_main_logging_func_placeholder
    if TradeExecutor_class is None: TradeExecutor_class = TradeExecutor_class_placeholder


ALL_LOG_FILES_RELATIVE = ["bot.log", "data_fetcher.log", "ml_decision.log"]
NUM_LOG_LINES = 400

def tail_all_logs(num_lines=NUM_LOG_LINES):
    combined_lines = []
    for logf_relative in ALL_LOG_FILES_RELATIVE:
        actual_log_path = os.path.join(DASHBOARD_PROJECT_ROOT, logf_relative)
        if os.path.exists(actual_log_path):
            try:
                with open(actual_log_path, "r", encoding='utf-8', errors='ignore') as f: lines = f.readlines()
                lines = lines[-num_lines:]; combined_lines.append(f"\n=== [ {os.path.basename(actual_log_path)} ] ===\n"); combined_lines.extend(lines)
            except Exception as e:
                combined_lines.append(f"\n[LOG ERROR] Impossible de lire {actual_log_path} => {e}\n")
                dashboard_logger.warning(f"Erreur lecture log {actual_log_path}: {e}")
        else:
            combined_lines.append(f"\n[{os.path.basename(actual_log_path)}] n'existe pas (chemin testé: {actual_log_path}).\n")
    return "".join(combined_lines)

def get_model_version_date():
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
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>MarsShot Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link 
    rel="stylesheet" 
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <style>
    body { margin: 20px; font-family: Arial, sans-serif; }
    h1,h2,h3 { margin-top: 10px; margin-bottom: 15px; color: #333; }
    pre { background: #f8f9fa; padding:15px; border: 1px solid #dee2e6; border-radius: 4px; white-space: pre-wrap; word-wrap: break-word; font-size: 0.9em; }
    .nav-link.active { background-color:#e9ecef !important; color: #007bff !important; border-color: #dee2e6 #dee2e6 #fff !important; }
    .nav-tabs .nav-link { color: #495057; }
    .table { margin-top: 15px; }
    .badge { font-size: 0.9em; }
    #forceDailyResult, #emergencyResult { margin-top: 10px; font-weight: bold; }
  </style>
</head>
<body>

<div class="container-fluid">
    <h1>MarsShot Dashboard</h1>
    <hr/>

    <!-- NAV TABS -->
    <ul class="nav nav-tabs" id="myTab" role="tablist">
      <li class="nav-item" role="presentation">
        <button class="nav-link active" id="positions-tab" 
                data-bs-toggle="tab" data-bs-target="#positions" 
                type="button" role="tab" aria-controls="positions" aria-selected="true">
          Positions
        </button>
      </li>
      <li class="nav-item" role="presentation">
        <button class="nav-link" id="perf-tab" 
                data-bs-toggle="tab" data-bs-target="#perf" 
                type="button" role="tab" aria-controls="perf" aria-selected="false">
          Performance
        </button>
      </li>
      <li class="nav-item" role="presentation">
        <button class="nav-link" id="tokens-tab" 
                data-bs-toggle="tab" data-bs-target="#tokens" 
                type="button" role="tab" aria-controls="tokens" aria-selected="false">
          Tokens Suivis
        </button>
      </li>
      <li class="nav-item" role="presentation">
        <button class="nav-link" id="history-tab" 
                data-bs-toggle="tab" data-bs-target="#history" 
                type="button" role="tab" aria-controls="history" aria-selected="false">
          Historique Trades
        </button>
      </li>
      <li class="nav-item" role="presentation">
        <button class="nav-link" id="emergency-tab" 
                data-bs-toggle="tab" data-bs-target="#emergency" 
                type="button" role="tab" aria-controls="emergency" aria-selected="false">
          Urgence
        </button>
      </li>
      <li class="nav-item" role="presentation">
        <button class="nav-link" id="logs-tab" 
                data-bs-toggle="tab" data-bs-target="#logs" 
                type="button" role="tab" aria-controls="logs" aria-selected="false">
          Logs
        </button>
      </li>
    </ul>

    <div class="tab-content" id="myTabContent" style="margin-top:20px;">

      <!-- Positions Tab -->
      <div class="tab-pane fade show active" id="positions" role="tabpanel" aria-labelledby="positions-tab">
        <h2>Positions Actuelles (Compte Live)</h2>
        <p>Valeur Totale du Portefeuille: <strong>{{ pf['total_value_USDC'] }} USDC</strong></p>
        <table class="table table-striped table-hover">
          <thead class="table-light"><tr><th>Symbole</th><th>Quantité</th><th>Valeur (USDC)</th></tr></thead>
          <tbody>
          {% for pos in pf['positions'] %}
            <tr>
              <td>{{ pos.symbol }}</td>
              <td>{{ pos.qty }}</td>
              <td>{{ pos.value_USDC }}</td>
            </tr>
          {% else %}
            <tr><td colspan="3" class="text-center">Aucune position significative à afficher.</td></tr>
          {% endfor %}
          </tbody>
        </table>

        <h4>Date du Modèle Actif</h4>
        <p>{{ model_date }}</p>

        <hr/>
        <h4>Forcer la Mise à Jour Quotidienne</h4>
        <p>Cela exécutera le cycle complet : sélection des tokens, récupération des données, décision ML, et phases Achat/Vente.</p>
        <p>
          <button class="btn btn-warning" onclick="forceDailyUpdate()">Forcer la mise à jour quotidienne</button>
        </p>
        <p id="forceDailyResult" style="color:blue;"></p>
      </div>

      <!-- Perf Tab -->
      <div class="tab-pane fade" id="perf" role="tabpanel" aria-labelledby="perf-tab">
        <h2>Performance du Portefeuille</h2>
        <table class="table table-bordered table-hover">
          <thead class="table-light"><tr><th>Horizon</th><th>Valeur (USDC)</th><th>Performance (%)</th></tr></thead>
          <tbody>
          {% for horizon, vals in perf.items() %}
           <tr>
             <td>{{ horizon }}</td>
             <td>{{ vals.USDC }}</td>
             <td>{{ vals.pct }}%</td>
           </tr>
          {% else %}
            <tr><td colspan="3" class="text-center">Données de performance non disponibles.</td></tr>
          {% endfor %}
          </tbody>
        </table>
      </div>

      <!-- Tokens Tab -->
      <div class="tab-pane fade" id="tokens" role="tabpanel" aria-labelledby="tokens-tab">
        <h2>Tokens Actuellement Suivis pour Récupération de Données</h2>
        <p><em>Cette liste est dynamique et est utilisée par data_fetcher. Elle est issue de la fusion des tokens auto-sélectionnés, de la liste manuelle et des positions en portefeuille.</em></p>
        <p>
          {% for t in tokens %}
            <span class="badge bg-info text-dark m-1 p-2">{{ t }}</span>
          {% else %}
            <span class="text-muted">Aucun token suivi actuellement (vérifiez config.yaml et l'état du bot).</span>
          {% endfor %}
        </p>
      </div>

      <!-- History Tab -->
      <div class="tab-pane fade" id="history" role="tabpanel" aria-labelledby="history-tab">
        <h2>Historique des Trades</h2>
        <table class="table table-sm table-hover table-striped">
          <thead class="table-light">
            <tr>
              <th>Symbole</th><th>Prob. Achat</th><th>Prob. Vente</th>
              <th>Jours Détenus</th><th>PNL (USDC)</th><th>PNL (%)</th><th>Statut</th>
            </tr>
          </thead>
          <tbody>
          {% for tr in trades %}
            <tr>
              <td>{{ tr.symbol }}</td>
              <td>{{ tr.buy_prob if tr.buy_prob not in ['N/A', None] else '-' }}</td>
              <td>{{ tr.sell_prob if tr.sell_prob not in ['N/A', None] else '-' }}</td>
              <td>{{ tr.days_held if tr.days_held not in ['N/A', None] else '-' }}</td>
              <td>{{ tr.pnl_USDC if tr.pnl_USDC not in ['N/A', None] else '-' }}</td>
              <td>{{ tr.pnl_pct if tr.pnl_pct not in ['N/A', None] else '-' }}%</td>
              <td><span class="badge {% if tr.status == 'GAGNANT' %}bg-success{% elif tr.status == 'PERDANT' %}bg-danger{% else %}bg-secondary{% endif %}">{{ tr.status }}</span></td>
            </tr>
          {% else %}
            <tr><td colspan="7" class="text-center">Aucun trade dans l'historique.</td></tr>
          {% endfor %}
          </tbody>
        </table>
      </div>

      <!-- Emergency Tab -->
      <div class="tab-pane fade" id="emergency" role="tabpanel" aria-labelledby="emergency-tab">
        <h2>Sortie d'Urgence</h2>
        <p class="alert alert-danger"><strong>Attention :</strong> Ce bouton vendra immédiatement toutes les positions en portefeuille (sauf USDC et autres stables/BTC) au prix du marché.</p>
        <p>
          <button class="btn btn-danger btn-lg" onclick="triggerEmergency()">Vendre Toutes les Positions (Urgence)</button>
        </p>
        <p id="emergencyResult" style="color:red;"></p>
      </div>

      <!-- Logs Tab -->
      <div class="tab-pane fade" id="logs" role="tabpanel" aria-labelledby="logs-tab">
        <h2>Logs (Toutes sources)</h2>
        <p><em>Affiche les {{ num_log_lines }} dernières lignes de chaque fichier de log. Rafraîchissement automatique.</em></p>
        <div style="max-height:600px; overflow-y:auto; border:1px solid #ccc; padding:10px;" id="logsContainer">
          <pre id="logsContent">Chargement des logs...</pre>
        </div>
      </div>

    </div> <!-- tab-content -->
</div> <!-- container-fluid -->

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
// Emergency
function triggerEmergency(){
  if(confirm("Êtes-vous absolument sûr de vouloir vendre toutes les positions non-stables ? Cette action est irréversible.")) {
    document.getElementById("emergencyResult").innerText = "Déclenchement de la sortie d'urgence...";
    fetch("{{ url_for('emergency_api', pwd=secret_pwd) }}", {method:'POST'})
    .then(response => response.json())
    .then(data => {
      document.getElementById("emergencyResult").innerText = data.message;
      alert("Sortie d'urgence: " + data.message); 
    })
    .catch(error => {
      document.getElementById("emergencyResult").innerText = "Erreur lors de la sortie d'urgence: " + error;
      alert("Erreur sortie d'urgence: " + error);
    });
  }
}

// Logs
function refreshLogs(){
  fetch("{{ url_for('get_logs', pwd=secret_pwd) }}")
   .then(response => response.text())
   .then(text => {
     document.getElementById("logsContent").innerText = text;
   })
   .catch(error => {
     console.error("Erreur lors du rafraîchissement des logs:", error);
     document.getElementById("logsContent").innerText = "Erreur lors du chargement des logs.\\n" + error;
   });
}
document.addEventListener('DOMContentLoaded', function() {
    refreshLogs(); 
    setInterval(refreshLogs, 5000); 
});

// Forcer daily update
function forceDailyUpdate(){
  if(confirm("Forcer la mise à jour quotidienne maintenant ? Cela peut prendre plusieurs minutes.")) {
    document.getElementById("forceDailyResult").innerText = "Mise à jour quotidienne en cours...";
    fetch("{{ url_for('force_daily_update', pwd=secret_pwd) }}", {method:'POST'})
    .then(response => {
        if (!response.ok) {
            return response.json().then(errData => { 
                throw new Error(errData.message || `Erreur HTTP ${response.status} - ${response.statusText}`);
            }).catch(() => { 
                throw new Error(`Erreur HTTP ${response.status} - ${response.statusText}`);
            });
        }
        return response.json();
    })
    .then(data => {
      document.getElementById("forceDailyResult").innerText = data.message;
      alert("Mise à jour quotidienne: " + data.message); 
      refreshLogs(); 
    })
    .catch(error => {
      let errorMessage = "Erreur lors du forçage de la mise à jour: " + error.message;
      document.getElementById("forceDailyResult").innerText = errorMessage;
      alert(errorMessage);
    });
  }
}
</script>
</body>
</html>
""" # FIN DE TEMPLATE_HTML

def get_tokens_live():
    if os.path.exists(CONFIG_FILE_PATH_DASH):
        try:
            with open(CONFIG_FILE_PATH_DASH, "r", encoding="utf-8") as f: conf = yaml.safe_load(f)
            # Logique de fusion pour afficher une liste plus représentative de ce que data_fetcher utilisera
            auto_selected = conf.get("extended_tokens_daily", [])
            manual = conf.get("tokens_daily", [])
            # Pour les positions, il faudrait lire bot_state.json, ce qui est un peu lourd ici.
            # On se contente de la config.
            combined_preview = sorted(list(set(auto_selected).union(set(manual))))
            if combined_preview:
                return combined_preview
            else: # Fallback si les deux sont vides
                return ["Aucune liste de tokens définie dans config.yaml"]
        except Exception as e:
            dashboard_logger.error(f"Erreur lecture {CONFIG_FILE_PATH_DASH} dans get_tokens_live: {e}")
            return ["Erreur lecture config"]
    else:
        return [f"{os.path.basename(CONFIG_FILE_PATH_DASH)} introuvable"]

@app.route(f"/dashboard/<pwd>", methods=["GET"])
def dashboard_route(pwd): # Renommé pour éviter conflit potentiel
    if pwd != SECRET_PWD:
        return "Accès Interdit", 403

    try: pf = get_portfolio_state()
    except Exception as e: dashboard_logger.error(f"Erreur get_portfolio_state: {e}"); pf = {"positions": [], "total_value_USDC": "Erreur"}
    
    tokens = get_tokens_live()
    
    try: perf = get_performance_history()
    except Exception as e: dashboard_logger.error(f"Erreur get_performance_history: {e}"); perf = {}
    
    try: trades = get_trades_history()
    except Exception as e: dashboard_logger.error(f"Erreur get_trades_history: {e}"); trades = []
    
    model_date = get_model_version_date()

    return render_template_string(
        TEMPLATE_HTML,
        pf=pf,
        tokens=tokens,
        perf=perf,
        trades=trades,
        model_date=model_date,
        secret_pwd=SECRET_PWD,
        num_log_lines=NUM_LOG_LINES
    )

@app.route(f"/emergency/<pwd>", methods=["POST"])
def emergency_api_route(pwd): # Renommé
    if pwd != SECRET_PWD:
        return jsonify({"message": "Accès Interdit"}), 403
    try:
        emergency_out()
        dashboard_logger.info("Sortie d'urgence déclenchée via dashboard.")
        return jsonify({"message": "Sortie d'urgence déclenchée avec succès."})
    except Exception as e:
        dashboard_logger.error(f"Erreur lors de la sortie d'urgence via dashboard: {e}", exc_info=True)
        return jsonify({"message": f"Erreur sortie d'urgence: {e}"}), 500

@app.route(f"/force_daily_update/<pwd>", methods=["POST"])
def force_daily_update_route(pwd): # Renommé
    if pwd != SECRET_PWD:
        return jsonify({"message": "Accès Interdit"}), 403

    dashboard_logger.info("Déclenchement manuel du Daily Update via le dashboard.")

    if not main_module_imported_successfully:
        msg = "Les modules de main.py n'ont pas pu être importés correctement. 'Forcer Daily Update' est désactivé."
        dashboard_logger.error(msg)
        return jsonify({"message": msg}), 500

    try:
        if not os.path.exists(CONFIG_FILE_PATH_DASH):
            msg = f"Erreur critique: {CONFIG_FILE_PATH_DASH} (config pour dashboard) introuvable."
            dashboard_logger.error(msg); return jsonify({"message": msg}), 500
        
        with open(CONFIG_FILE_PATH_DASH, "r", encoding="utf-8") as f:
            config_main_for_call = yaml.safe_load(f)
        
        # S'assurer que le logger de main.py est configuré pour cet appel
        if configure_main_logging_func:
            main_log_settings = config_main_for_call.get("logging", {})
            configure_main_logging_func(main_log_settings) 
            dashboard_logger.info("Logging pour 'main_bot_logic' (ré)configuré pour cet appel de force_daily_update.")
        else:
            dashboard_logger.error("configure_main_logging_func non disponible. Les logs de main.py pourraient ne pas être corrects.")


        if not load_state_func: raise RuntimeError("load_state_func non importé")
        state = load_state_func()
        
        binance_api_config = config_main_for_call.get("binance_api", {})
        api_key = binance_api_config.get("api_key")
        api_secret = binance_api_config.get("api_secret")

        if not api_key or not api_secret:
            msg = "Erreur de configuration: Clés API Binance manquantes."; dashboard_logger.error(msg)
            return jsonify({"message": msg}), 500

        if not TradeExecutor_class: raise RuntimeError("TradeExecutor_class non importé")
        bexec = TradeExecutor_class(api_key=api_key, api_secret=api_secret)
        dashboard_logger.info("TradeExecutor initialisé pour le forçage du daily update.")

    except Exception as e_init:
        dashboard_logger.error(f"Erreur générale initialisation pour force_daily_update: {e_init}", exc_info=True)
        return jsonify({"message": f"Erreur d'initialisation: {e_init}"}), 500

    try:
        dashboard_logger.info("Appel de main_daily_update_live_func...")
        if not main_daily_update_live_func: raise RuntimeError("main_daily_update_live_func non importé")
        
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
def get_logs_route(pwd): # Renommé
    if pwd != SECRET_PWD:
        return "Accès Interdit", 403
    txt = tail_all_logs(num_lines=NUM_LOG_LINES)
    return txt, 200, {"Content-Type": "text/plain; charset=utf-8"}

def run_dashboard():
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.ERROR) 
    dashboard_logger.info(f"Démarrage du serveur Flask du Dashboard sur 0.0.0.0:5000 (PID: {os.getpid()})")
    # Mettre debug=True temporairement pour voir les erreurs Flask dans le navigateur si nécessaire, mais False en prod.
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    # Si dashboard.py est exécuté directement, configurer son propre logging de base
    # si ce n'est pas déjà fait (par exemple, si le logger 'dashboard_app' n'a pas de handlers)
    if not dashboard_logger.hasHandlers():
        logging.basicConfig(level=logging.INFO, 
                            format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                            handlers=[logging.StreamHandler(sys.stderr)])
    dashboard_logger.info("Dashboard exécuté directement (__name__ == '__main__').")
    run_dashboard()

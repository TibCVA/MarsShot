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
# subprocess n'est plus nécessaire pour force_daily_update si on appelle la fonction Python directement
# import subprocess
import yaml # Nécessaire pour lire config.yaml dans force_daily_update
from flask import Flask, request, jsonify, render_template_string

# Imports pour les données du dashboard (inchangé)
try:
    from dashboard_data import (
        get_portfolio_state,
        get_performance_history,
        get_trades_history,
        emergency_out
    )
# ---------- P1 : capte tout type d'exception pour éviter erreur 500 ----------
except Exception as e:
    logging.error(f"[DASHBOARD] Erreur critique: Impossible d'importer dashboard_data: {e}. Assurez-vous que dashboard_data.py est dans le PYTHONPATH ou le même répertoire.")
    # Fournir des fonctions factices pour que le dashboard puisse démarrer mais afficher des erreurs
    def get_portfolio_state(): return {"positions": [], "total_value_USDC": "Erreur: dashboard_data"}
    def get_performance_history(): return {}
    def get_trades_history(): return []
    def emergency_out(): logging.error("Fonction emergency_out non disponible.")

# Imports pour la fonction "Force Daily Update"
try:
    # S'assurer que main.py et modules sont accessibles depuis l'endroit où dashboard.py est exécuté
    from main import daily_update_live as main_daily_update_live # Renommer pour clarté
    from main import load_state # save_state n'est pas directement appelé par le dashboard ici
    from modules.trade_executor import TradeExecutor
# ---------- P2 : même élargissement ici ----------
except Exception as e:
    logging.error(f"[DASHBOARD] Erreur lors de l'import des modules de main.py ou TradeExecutor pour force_daily_update: {e}")
    # Définir une fonction factice pour main_daily_update_live si l'import échoue
    def main_daily_update_live(state, bexec):
        logging.error("[DASHBOARD] main_daily_update_live n'a pas pu être importée. La fonction 'Forcer Daily Update' ne fonctionnera pas.")
        raise RuntimeError("Dépendances manquantes pour 'Forcer Daily Update'. Vérifiez les logs du dashboard.")
    # Définir des factices pour les autres si nécessaire pour éviter des crashs à l'initialisation de Flask
    def load_state(): return {}
    class TradeExecutor:
        def __init__(self, api_key, api_secret):
            logging.error("[DASHBOARD] TradeExecutor factice utilisé.")
            pass


########################
# Logs
########################
# +++ MODIFICATION 1 : AJOUT DE daily_update.log ET REFACTORING LECTURE LOGS +++
ALL_LOG_FILES = [
    "bot.log",
    "data_fetcher.log",
    "ml_decision.log"
]
DAILY_UPDATE_LOG_FILE = "daily_update.log" # Fichier de log dédié
NUM_LOG_LINES = 400

def read_log_file(log_path, num_lines):
    """Lit les N dernières lignes d'un fichier de log de manière robuste."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Le chemin est construit à partir de la racine du projet où se trouve dashboard.py
    full_path = os.path.join(base_dir, log_path)

    if os.path.exists(full_path):
        try:
            with open(full_path, "r", encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            return lines[-num_lines:]
        except Exception as e:
            return [f"[LOG ERROR] Impossible de lire {full_path} => {e}\n"]
    return [f"[{os.path.basename(full_path)}] n'existe pas.\n"]

def tail_all_logs(num_lines=NUM_LOG_LINES):
    combined_lines = []
    for logf in ALL_LOG_FILES:
        lines = read_log_file(logf, num_lines)
        combined_lines.append(f"\n=== [ {logf} ] ===\n")
        combined_lines.extend(lines)
    return "".join(combined_lines)


def get_model_version_date():
    # S'attendre à ce que model.pkl soit à la racine du projet, comme les autres fichiers de données
    fname = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_deuxpointcinq.pkl") # Nom du modèle mis à jour
    
    model_path_new = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ensemble_mixcalib.pkl")
    model_path_old = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.pkl")

    if os.path.exists(model_path_new):
        fname_to_check = model_path_new
    elif os.path.exists(model_path_old):
        fname_to_check = model_path_old
    else:
        return "model_deuxpointcinq.pkl ou model.pkl introuvable à la racine."

    try:
        t = os.path.getmtime(fname_to_check)
        dt = datetime.datetime.fromtimestamp(t)
        return f"{os.path.basename(fname_to_check)} - {dt.strftime('%Y-%m-%d %H:%M:%S')}"
    except Exception as e:
        return f"Erreur lecture date {os.path.basename(fname_to_check)}: {e}"


app = Flask(__name__)
SECRET_PWD = "SECRET123"

# +++ MODIFICATION 2 : MISE À JOUR DU TEMPLATE HTML AVEC LE NOUVEL ONGLET +++
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
    .logs-container { max-height:600px; overflow-y:auto; border:1px solid #ccc; padding:10px; }
  </style>
</head>
<body>

<div class="container-fluid">
    <h1>MarsShot Dashboard</h1>
    <hr/>

    <!-- NAV TABS -->
    <ul class="nav nav-tabs" id="myTab" role="tablist">
      <li class="nav-item" role="presentation"><button class="nav-link active" id="positions-tab" data-bs-toggle="tab" data-bs-target="#positions" type="button" role="tab">Positions</button></li>
      <li class="nav-item" role="presentation"><button class="nav-link" id="perf-tab" data-bs-toggle="tab" data-bs-target="#perf" type="button" role="tab">Performance</button></li>
      <!-- NOUVEL ONGLET -->
      <li class="nav-item" role="presentation"><button class="nav-link" id="daily-update-logs-tab" data-bs-toggle="tab" data-bs-target="#daily-update-logs" type="button" role="tab">Daily Update Logs</button></li>
      <li class="nav-item" role="presentation"><button class="nav-link" id="history-tab" data-bs-toggle="tab" data-bs-target="#history" type="button" role="tab">Historique</button></li>
      <li class="nav-item" role="presentation"><button class="nav-link" id="emergency-tab" data-bs-toggle="tab" data-bs-target="#emergency" type="button" role="tab">Urgence</button></li>
      <li class="nav-item" role="presentation"><button class="nav-link" id="logs-tab" data-bs-toggle="tab" data-bs-target="#logs" type="button" role="tab">Logs Généraux</button></li>
    </ul>

    <div class="tab-content" id="myTabContent" style="margin-top:20px;">
      <!-- Positions Tab -->
      <div class="tab-pane fade show active" id="positions" role="tabpanel">
        <h2>Positions Actuelles (Compte Live)</h2>
        <p>Valeur Totale du Portefeuille: <strong>{{ pf['total_value_USDC'] }} USDC</strong></p>
        <table class="table table-striped table-hover">
          <thead><tr><th>Symbole</th><th>Quantité</th><th>Valeur (USDC)</th></tr></thead>
          <tbody>
          {% for pos in pf['positions'] %}
            <tr><td>{{ pos.symbol }}</td><td>{{ pos.qty }}</td><td>{{ pos.value_USDC }}</td></tr>
          {% else %}
            <tr><td colspan="3" class="text-center">Aucune position significative.</td></tr>
          {% endfor %}
          </tbody>
        </table>
        <h4>Date du Modèle Actif</h4><p>{{ model_date }}</p><hr/>
        <h4>Forcer la Mise à Jour Quotidienne</h4>
        <p>Cela exécutera le cycle complet : sélection des tokens, récupération des données, décision ML, et phases Achat/Vente.</p>
        <p><button class="btn btn-warning" onclick="forceDailyUpdate()">Forcer la mise à jour quotidienne</button></p>
        <p id="forceDailyResult" style="color:blue;"></p>
      </div>
      <!-- Perf Tab -->
      <div class="tab-pane fade" id="perf" role="tabpanel">
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
      <!-- NOUVEAU CONTENU D'ONGLET -->
      <div class="tab-pane fade" id="daily-update-logs" role="tabpanel">
        <h2>Logs du Dernier Cycle de Mise à Jour Quotidienne</h2>
        <p><em>Affiche les logs spécifiques au dernier cycle <code>daily_update_live</code>. Rafraîchissement automatique.</em></p>
        <div class="logs-container">
          <pre id="dailyLogsContent">Chargement des logs...</pre>
        </div>
      </div>
      <!-- History Tab -->
      <div class="tab-pane fade" id="history" role="tabpanel">
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
      <div class="tab-pane fade" id="emergency" role="tabpanel">
        <h2>Sortie d'Urgence</h2>
        <p class="alert alert-danger"><strong>Attention :</strong> Ce bouton vendra immédiatement toutes les positions en portefeuille (sauf USDC et autres stables/BTC) au prix du marché.</p>
        <p><button class="btn btn-danger btn-lg" onclick="triggerEmergency()">Vendre Toutes les Positions (Urgence)</button></p>
        <p id="emergencyResult" style="color:red;"></p>
      </div>
      <!-- Logs Généraux Tab -->
      <div class="tab-pane fade" id="logs" role="tabpanel">
        <h2>Logs Généraux (Toutes sources)</h2>
        <p><em>Affiche les {{ num_log_lines }} dernières lignes des fichiers de log principaux.</em></p>
        <div class="logs-container">
          <pre id="generalLogsContent">Chargement des logs...</pre>
        </div>
      </div>
    </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
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

function forceDailyUpdate(){
  if(confirm("Forcer la mise à jour quotidienne maintenant ? Cela peut prendre plusieurs minutes.")) {
    document.getElementById("forceDailyResult").innerText = "Mise à jour quotidienne en cours...";
    fetch("{{ url_for('force_daily_update', pwd=secret_pwd) }}", {method:'POST'})
    .then(response => { if (!response.ok) { return response.json().then(err => {throw new Error(err.message || 'Erreur inconnue')}) } return response.json(); })
    .then(data => {
      document.getElementById("forceDailyResult").innerText = data.message;
      alert("Mise à jour quotidienne: " + data.message);
      refreshDailyLogs();
      refreshGeneralLogs();
    })
    .catch(error => {
      document.getElementById("forceDailyResult").innerText = "Erreur: " + error;
      alert("Erreur: " + error);
    });
  }
}

// --- Fonctions de rafraîchissement des logs modifiées ---
function refreshGeneralLogs(){
  fetch("{{ url_for('get_general_logs', pwd=secret_pwd) }}")
   .then(response => response.text())
   .then(text => { document.getElementById("generalLogsContent").innerText = text; })
   .catch(error => { document.getElementById("generalLogsContent").innerText = "Erreur chargement logs.\n" + error; });
}
function refreshDailyLogs(){
  fetch("{{ url_for('get_daily_update_logs', pwd=secret_pwd) }}")
   .then(response => response.text())
   .then(text => { document.getElementById("dailyLogsContent").innerText = text; })
   .catch(error => { document.getElementById("dailyLogsContent").innerText = "Erreur chargement logs.\n" + error; });
}
document.addEventListener('DOMContentLoaded', function() {
    refreshGeneralLogs();
    refreshDailyLogs();
    setInterval(refreshGeneralLogs, 7000);
    setInterval(refreshDailyLogs, 3000);
});
</script>
</body>
</html>
"""

def get_tokens_live():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                conf = yaml.safe_load(f)
            if "extended_tokens_daily" in conf and conf["extended_tokens_daily"]:
                return sorted(list(set(conf["extended_tokens_daily"])))
            elif "tokens_daily" in conf and conf["tokens_daily"]:
                return sorted(list(set(conf.get("tokens_daily", []))))
            else:
                return []
        except Exception as e:
            logging.error(f"[DASHBOARD get_tokens_live] Erreur lecture config.yaml: {e}")
            return ["Erreur lecture config"]
    else:
        return ["config.yaml introuvable"]

@app.route(f"/dashboard/<pwd>", methods=["GET"])
def dashboard(pwd):
    if pwd != SECRET_PWD:
        return "Accès Interdit", 403
    try: pf = get_portfolio_state()
    except Exception as e: logging.error(f"Erreur get_portfolio_state: {e}"); pf = {"positions": [], "total_value_USDC": "Erreur"}
    tokens = get_tokens_live()
    try: perf = get_performance_history()
    except Exception as e: logging.error(f"Erreur get_performance_history: {e}"); perf = {}
    try: trades = get_trades_history()
    except Exception as e: logging.error(f"Erreur get_trades_history: {e}"); trades = []
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
def emergency_api(pwd):
    if pwd != SECRET_PWD: return jsonify({"message": "Accès Interdit"}), 403
    try:
        emergency_out()
        logging.info("[DASHBOARD EMERGENCY] Sortie d'urgence déclenchée.")
        return jsonify({"message": "Sortie d'urgence déclenchée avec succès."})
    except Exception as e:
        logging.error(f"[DASHBOARD EMERGENCY] Erreur: {e}", exc_info=True)
        return jsonify({"message": f"Erreur: {e}"}), 500

@app.route(f"/force_daily_update/<pwd>", methods=["POST"])
def force_daily_update(pwd):
    if pwd != SECRET_PWD: return jsonify({"message": "Accès Interdit"}), 403
    logging.info("[DASHBOARD] Déclenchement manuel du Daily Update.")
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
        if not os.path.exists(config_path):
            raise FileNotFoundError("config.yaml introuvable.")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        state = load_state()
        binance_api_config = config.get("binance_api", {})
        api_key = binance_api_config.get("api_key")
        api_secret = binance_api_config.get("api_secret")
        if not api_key or not api_secret:
            raise KeyError("Clés API Binance manquantes dans config.yaml.")
        bexec = TradeExecutor(api_key=api_key, api_secret=api_secret)
        main_daily_update_live(state, bexec)
        return jsonify({"message": "Mise à jour quotidienne (forcée) terminée."})
    except Exception as e:
        logging.error(f"[DASHBOARD] Erreur lors du forçage de la mise à jour: {e}", exc_info=True)
        return jsonify({"message": f"Erreur: {e}"}), 500

# +++ MODIFICATION 3 : SÉPARATION DES ROUTES DE LOGS +++
@app.route(f"/logs/<pwd>", methods=["GET"])
def get_general_logs(pwd):
    if pwd != SECRET_PWD:
        return "Accès Interdit", 403
    txt = tail_all_logs(num_lines=NUM_LOG_LINES)
    return txt, 200, {"Content-Type": "text/plain; charset=utf-8"}

@app.route(f"/daily_update_logs/<pwd>", methods=["GET"])
def get_daily_update_logs(pwd):
    if pwd != SECRET_PWD:
        return "Accès Interdit", 403
    # On lit tout le fichier, car il est spécifique au cycle
    lines = read_log_file(DAILY_UPDATE_LOG_FILE, num_lines=9999) 
    return "".join(lines), 200, {"Content-Type": "text/plain; charset=utf-8"}

def run_dashboard():
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.ERROR)
    logging.info("[DASHBOARD] Démarrage du serveur Flask sur 0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    run_dashboard()

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
except ImportError as e:
    # Log plus explicite si dashboard_data n'est pas trouvé
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
except ImportError as e:
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
# Logs (inchangé)
########################
ALL_LOG_FILES = [
    "bot.log",
    "data_fetcher.log", # Ces logs seront maintenant générés par l'appel à main_daily_update_live
    "ml_decision.log"   # Idem
]
NUM_LOG_LINES = 400

def tail_all_logs(num_lines=NUM_LOG_LINES):
    combined_lines = []
    for logf in ALL_LOG_FILES:
        log_path = os.path.join(os.path.dirname(__file__), "..", logf) if "modules" not in logf else os.path.join(os.path.dirname(__file__), logf) # Ajustement chemin si nécessaire
        # Plus simple: supposer que les logs sont à la racine du projet
        log_path_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), logf)

        actual_log_path = log_path_root # Par défaut
        if not os.path.exists(actual_log_path) and "/" not in logf and "\\" not in logf : # Si pas à la racine, et pas un chemin absolu/relatif déjà
             # Tenter de le trouver dans le répertoire parent si dashboard.py est dans un sous-répertoire
             parent_dir_log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), logf)
             if os.path.exists(parent_dir_log_path):
                 actual_log_path = parent_dir_log_path
        
        if os.path.exists(actual_log_path):
            try:
                with open(actual_log_path, "r", encoding='utf-8', errors='ignore') as f: # Ajout encoding et errors
                    lines = f.readlines()
                lines = lines[-num_lines:]
                combined_lines.append(f"\n=== [ {os.path.basename(actual_log_path)} ] ===\n") # Utiliser basename
                combined_lines.extend(lines)
            except Exception as e:
                combined_lines.append(f"\n[LOG ERROR] Impossible de lire {actual_log_path} => {e}\n")
        else:
            combined_lines.append(f"\n[{os.path.basename(actual_log_path)}] n'existe pas (chemin testé: {actual_log_path}).\n")
    return "".join(combined_lines)

def get_model_version_date():
    # S'attendre à ce que model.pkl soit à la racine du projet, comme les autres fichiers de données
    fname = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_deuxpointcinq.pkl") # Nom du modèle mis à jour
    # Ou si vous voulez le modèle original:
    # fname = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.pkl")
    
    # Pour être plus flexible, on pourrait chercher model.pkl ou model_deuxpointcinq.pkl
    model_path_new = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_deuxpointcinq.pkl")
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
# Le logging de Flask peut être configuré ici si besoin, mais les logs principaux viendront de main.py
# logging.basicConfig(level=logging.INFO) # Déjà fait globalement, mais peut être spécifique à Flask

SECRET_PWD = "SECRET123" # À CHANGER EN PRODUCTION et à gérer via variable d'environnement

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
      alert("Sortie d'urgence: " + data.message); // Alerte pour confirmation visuelle
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
     // Optionnel: faire défiler vers le bas si l'utilisateur n'a pas fait défiler manuellement
     // const logsContainer = document.getElementById("logsContainer");
     // if (logsContainer.scrollTop + logsContainer.clientHeight >= logsContainer.scrollHeight - 20) { // Si proche du bas
     //    logsContainer.scrollTop = logsContainer.scrollHeight;
     // }
   })
   .catch(error => {
     console.error("Erreur lors du rafraîchissement des logs:", error);
     document.getElementById("logsContent").innerText = "Erreur lors du chargement des logs.\\n" + error;
   });
}
// Premier chargement des logs, puis intervalle
document.addEventListener('DOMContentLoaded', function() {
    refreshLogs(); // Charger les logs immédiatement
    setInterval(refreshLogs, 5000); // Rafraîchir toutes les 5 secondes
});


// Forcer daily update
function forceDailyUpdate(){
  if(confirm("Forcer la mise à jour quotidienne maintenant ? Cela peut prendre plusieurs minutes.")) {
    document.getElementById("forceDailyResult").innerText = "Mise à jour quotidienne en cours...";
    fetch("{{ url_for('force_daily_update', pwd=secret_pwd) }}", {method:'POST'})
    .then(response => {
        if (!response.ok) {
            return response.json().then(errData => { throw new Error(errData.message || `Erreur HTTP ${response.status}`) });
        }
        return response.json();
    })
    .then(data => {
      document.getElementById("forceDailyResult").innerText = data.message;
      alert("Mise à jour quotidienne: " + data.message); // Alerte pour confirmation visuelle
      refreshLogs(); // Rafraîchir les logs pour voir les nouvelles entrées
    })
    .catch(error => {
      document.getElementById("forceDailyResult").innerText = "Erreur lors du forçage de la mise à jour: " + error;
      alert("Erreur mise à jour quotidienne: " + error);
    });
  }
}
</script>
</body>
</html>
"""

#############################################
# On relit config.yaml à chaque requête pour afficher la liste réelle des tokens
# qui SERONT UTILISÉS par data_fetcher lors du prochain cycle.
#############################################
def get_tokens_live():
    # Cette fonction lit config.yaml pour la clé "extended_tokens_daily"
    # car c'est ce que auto_select_tokens.py est censé mettre à jour.
    # Si elle n'est pas là, elle prend "tokens_daily" (manuel).
    # Pour une vue plus "live" de ce que data_fetcher utilisera, il faudrait simuler
    # la fusion faite dans main.py, mais c'est complexe ici.
    # On se contente de ce qui est dans config.yaml.
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                conf = yaml.safe_load(f)
            # Priorité à extended_tokens_daily si elle existe et n'est pas vide
            if "extended_tokens_daily" in conf and conf["extended_tokens_daily"]:
                return sorted(list(set(conf["extended_tokens_daily"]))) # Trié et unique
            # Sinon, fallback sur tokens_daily
            elif "tokens_daily" in conf and conf["tokens_daily"]:
                return sorted(list(set(conf.get("tokens_daily", [])))) # Trié et unique
            else:
                return [] # Si les deux sont vides ou absents
        except Exception as e:
            logging.error(f"[DASHBOARD get_tokens_live] Erreur lecture config.yaml: {e}")
            return ["Erreur lecture config"]
    else:
        return ["config.yaml introuvable"]

#############################################
@app.route(f"/dashboard/<pwd>", methods=["GET"])
def dashboard(pwd):
    if pwd != SECRET_PWD:
        return "Accès Interdit", 403 # Message plus clair

    # Utiliser des blocs try-except pour chaque appel à dashboard_data pour la robustesse
    try: pf = get_portfolio_state()
    except Exception as e: logging.error(f"Erreur get_portfolio_state: {e}"); pf = {"positions": [], "total_value_USDC": "Erreur"}
    
    tokens = get_tokens_live() # Déjà gère ses erreurs
    
    try: perf = get_performance_history()
    except Exception as e: logging.error(f"Erreur get_performance_history: {e}"); perf = {}
    
    try: trades = get_trades_history()
    except Exception as e: logging.error(f"Erreur get_trades_history: {e}"); trades = []
    
    model_date = get_model_version_date() # Déjà gère ses erreurs

    return render_template_string(
        TEMPLATE_HTML,
        pf=pf,
        tokens=tokens,
        perf=perf,
        trades=trades,
        model_date=model_date,
        secret_pwd=SECRET_PWD,
        num_log_lines=NUM_LOG_LINES # Passer NUM_LOG_LINES au template
    )

@app.route(f"/emergency/<pwd>", methods=["POST"])
def emergency_api(pwd):
    if pwd != SECRET_PWD:
        return jsonify({"message": "Accès Interdit"}), 403
    try:
        emergency_out()
        logging.info("[DASHBOARD EMERGENCY] Sortie d'urgence déclenchée.")
        return jsonify({"message": "Sortie d'urgence déclenchée avec succès. Toutes les positions non-stables devraient être vendues."})
    except Exception as e:
        logging.error(f"[DASHBOARD EMERGENCY] Erreur lors de la sortie d'urgence: {e}", exc_info=True)
        return jsonify({"message": f"Erreur lors de la sortie d'urgence: {e}"}), 500

# MODIFICATION DE LA FONCTION force_daily_update
@app.route(f"/force_daily_update/<pwd>", methods=["POST"])
def force_daily_update(pwd):
    if pwd != SECRET_PWD:
        return jsonify({"message": "Accès Interdit"}), 403

    logging.info("[DASHBOARD FORCE UPDATE] Déclenchement manuel du Daily Update via le dashboard.")

    try:
        # ÉTAPE 1: Charger l'état et la configuration, initialiser TradeExecutor
        # S'assurer que config.yaml est à la racine du projet
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
        if not os.path.exists(config_path):
            logging.error("[DASHBOARD FORCE UPDATE] config.yaml introuvable à la racine du projet.")
            return jsonify({"message": "Erreur critique: config.yaml introuvable."}), 500
        
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        
        # S'assurer que bot_state.json est également accessible (généralement à la racine)
        state = load_state() # load_state devrait gérer le chemin de son fichier
        
        # Vérifier si les clés API sont présentes avant d'initialiser TradeExecutor
        binance_api_config = config.get("binance_api", {})
        api_key = binance_api_config.get("api_key")
        api_secret = binance_api_config.get("api_secret")

        if not api_key or not api_secret:
            logging.error("[DASHBOARD FORCE UPDATE] Clés API Binance manquantes dans config.yaml.")
            return jsonify({"message": "Erreur de configuration: Clés API Binance manquantes."}), 500

        bexec = TradeExecutor(
            api_key=api_key,
            api_secret=api_secret
        )
        logging.info("[DASHBOARD FORCE UPDATE] TradeExecutor initialisé pour le forçage.")

    except FileNotFoundError as e_fnf:
        logging.error(f"[DASHBOARD FORCE UPDATE] Fichier non trouvé lors de l'initialisation: {e_fnf}")
        return jsonify({"message": f"Erreur d'initialisation (fichier non trouvé): {e_fnf}"}), 500
    except KeyError as e_key:
        logging.error(f"[DASHBOARD FORCE UPDATE] Clé manquante dans la configuration: {e_key}")
        return jsonify({"message": f"Erreur de configuration (clé manquante): {e_key}"}), 500
    except Exception as e_init:
        logging.error(f"[DASHBOARD FORCE UPDATE] Erreur générale lors de l'initialisation pour le forçage: {e_init}", exc_info=True)
        return jsonify({"message": f"Erreur d'initialisation: {e_init}"}), 500

    # ÉTAPE 2: Appeler la fonction daily_update_live de main.py
    try:
        logging.info("[DASHBOARD FORCE UPDATE] Appel de main_daily_update_live...")
        # main_daily_update_live est la fonction importée de main.py
        # Elle gère maintenant l'appel à auto_select_tokens, la fusion des listes,
        # la création de config_temp.yaml, et les appels à data_fetcher et ml_decision.
        main_daily_update_live(state, bexec) 
        
        # save_state(state) est appelé à l'intérieur de main_daily_update_live
        # et/ou de ses sous-fonctions comme intraday_check_real ou lors des phases SELL/BUY.
        # Il n'est donc pas strictement nécessaire de le rappeler ici,
        # mais cela ne fait pas de mal de s'assurer que l'état final est sauvegardé.
        # Cependant, pour éviter des sauvegardes redondantes, on peut l'omettre ici.
        # save_state(state) 

        logging.info("[DASHBOARD FORCE UPDATE] main_daily_update_live terminé avec succès.")
        return jsonify({"message": "Mise à jour quotidienne (forcée) déclenchée et terminée avec succès."})
    except RuntimeError as e_rt: # Peut être levée par la fonction factice si l'import a échoué
        logging.error(f"[DASHBOARD FORCE UPDATE] Erreur d'exécution (RuntimeError) : {e_rt}", exc_info=True)
        return jsonify({"message": f"Erreur d'exécution: {e_rt}"}), 500
    except Exception as e_daily:
        logging.error(f"[DASHBOARD FORCE UPDATE] Erreur lors de l'exécution de main_daily_update_live: {e_daily}", exc_info=True)
        return jsonify({"message": f"Erreur lors de la mise à jour quotidienne forcée: {e_daily}"}), 500


@app.route(f"/logs/<pwd>", methods=["GET"])
def get_logs(pwd):
    if pwd != SECRET_PWD:
        return "Accès Interdit", 403
    txt = tail_all_logs(num_lines=NUM_LOG_LINES)
    return txt, 200, {"Content-Type": "text/plain; charset=utf-8"}

def run_dashboard():
    # Configurer le logger de Flask pour qu'il n'interfère pas trop avec les logs du bot
    # ou pour qu'il logge dans un fichier séparé si nécessaire.
    # Pour l'instant, on laisse le logging global.
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.ERROR) # Pour réduire le bruit des requêtes HTTP dans les logs principaux

    logging.info("[DASHBOARD] Démarrage du serveur Flask sur 0.0.0.0:5000")
    # debug=False est important en production
    # use_reloader=False est important si le dashboard est lancé dans le même processus/thread que le bot principal
    # pour éviter les redémarrages intempestifs. Si c'est un processus séparé, use_reloader=True est ok pour le dev.
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    # Configuration de logging de base si le script est exécuté directement
    # (sera écrasée si main.py configure le logging différemment et que dashboard est importé)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s (%(module)s.%(funcName)s:%(lineno)d): %(message)s")
    run_dashboard()

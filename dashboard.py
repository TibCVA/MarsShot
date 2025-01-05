#!/usr/bin/env python3
# coding: utf-8

"""
Mini-dashboard Flask pour MarsShot, intégré à ton système.
Affiche plusieurs onglets (Positions, Perf, Tokens, Trades, Emergency, Logs)
en mode responsive (Bootstrap), et utilise tes fonctions existantes
pour obtenir les données réelles (sans modifier tes autres fichiers).
"""

import os
import datetime
import logging
from flask import Flask, request, jsonify, render_template_string

# On suppose que tes modules sont installés comme suit :
# - telegram_integration.py => contient get_portfolio_state, list_tokens_tracked,
#   get_performance_history, get_trades_history, emergency_out
# - bot.log => fichier log
try:
    from telegram_integration import (
        get_portfolio_state,
        list_tokens_tracked,
        get_performance_history,
        get_trades_history,
        emergency_out
    )
except ImportError:
    # Si besoin, on met un fallback / exemple minimal
    # A TOI d'ajuster selon la conversation
    def get_portfolio_state():
        return {
          "positions": [
            {"symbol":"FET","qty":120.0,"value_usdt":100.0},
            {"symbol":"AGIX","qty":50.0,"value_usdt":150.0}
          ],
          "total_value_usdt":250.0
        }
    def list_tokens_tracked():
        return ["FET","AGIX","ARB","OP","INJ","RNDR","MANA","SAND"]
    def get_performance_history():
        return {
          "1d":  {"usdt":  45.0, "pct":  6.2},
          "7d":  {"usdt":  78.0, "pct": 10.1},
          "1m":  {"usdt": 150.0, "pct": 22.5},
          "3m":  {"usdt": 280.0, "pct": 39.9},
          "1y":  {"usdt": 600.0, "pct": 75.0},
          "all": {"usdt": 750.0, "pct": 93.8}
        }
    def get_trades_history():
        return [
          {"symbol":"FET","buy_prob":0.85,"sell_prob":0.25,"days_held":12,
           "pnl_usdt":30.0,"pnl_pct":60.0,"status":"gagnant"},
          {"symbol":"AGIX","buy_prob":0.82,"sell_prob":0.28,"days_held":5,
           "pnl_usdt":-15.0,"pnl_pct":-30.0,"status":"perdant"}
        ]
    def emergency_out():
        logging.info("[EMERGENCY] Tout vendu en USDT.")
        print("[EMERGENCY] Out (exemple)")

# Pour la date du model.pkl
def get_model_version_date():
    fname = "model.pkl"
    if os.path.exists(fname):
        t = os.path.getmtime(fname)
        dt = datetime.datetime.fromtimestamp(t)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        return "model.pkl introuvable"

# Lecture du log
LOG_FILE = "bot.log"
def tail_logs(num_lines=200):
    """
    Lit les `num_lines` dernières lignes de bot.log
    Retourne un str formaté (avec \n).
    """
    if not os.path.exists(LOG_FILE):
        return "Aucun fichier de log bot.log"
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
    lines = lines[-num_lines:]
    return "".join(lines)


###########################################
# Flask APP
###########################################
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

SECRET_PWD = "SECRET123"  # A adapter si besoin

TEMPLATE_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>MarsShot Dashboard</title>
  <!-- Responsive meta + Bootstrap CSS -->
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link 
    rel="stylesheet" 
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <style>
    body { margin: 20px; }
    h1,h2,h3 { margin-top: 10px; }
    pre { background: #f4f4f4; padding:10px; }
    .nav-link.active { background-color:#ddd !important; }
  </style>
</head>
<body>

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
      Tokens
    </button>
  </li>
  <li class="nav-item" role="presentation">
    <button class="nav-link" id="history-tab" 
            data-bs-toggle="tab" data-bs-target="#history" 
            type="button" role="tab" aria-controls="history" aria-selected="false">
      Historique
    </button>
  </li>
  <li class="nav-item" role="presentation">
    <button class="nav-link" id="emergency-tab" 
            data-bs-toggle="tab" data-bs-target="#emergency" 
            type="button" role="tab" aria-controls="emergency" aria-selected="false">
      Emergency
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
    <h2>Positions Actuelles</h2>
    <p>Valeur Totale: {{ pf['total_value_usdt'] }} USDT</p>
    <table class="table table-striped">
      <thead><tr><th>Symbol</th><th>QTY</th><th>Value (USDT)</th></tr></thead>
      <tbody>
      {% for pos in pf['positions'] %}
        <tr>
          <td>{{ pos.symbol }}</td>
          <td>{{ pos.qty }}</td>
          <td>{{ pos.value_usdt }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>

    <h4>Date du model.pkl</h4>
    <p>{{ model_date }}</p>
  </div>

  <!-- Perf Tab -->
  <div class="tab-pane fade" id="perf" role="tabpanel" aria-labelledby="perf-tab">
    <h2>Performance</h2>
    <table class="table table-bordered">
      <thead><tr><th>Horizon</th><th>USDT</th><th>%</th></tr></thead>
      <tbody>
      {% for horizon, vals in perf.items() %}
       <tr>
         <td>{{ horizon }}</td>
         <td>{{ vals.usdt }}</td>
         <td>{{ vals.pct }}%</td>
       </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Tokens Tab -->
  <div class="tab-pane fade" id="tokens" role="tabpanel" aria-labelledby="tokens-tab">
    <h2>Tokens Suivis</h2>
    <p>
      {% for t in tokens %}
        <span class="badge bg-info text-dark" style="margin:3px;">{{ t }}</span>
      {% endfor %}
    </p>
  </div>

  <!-- History Tab -->
  <div class="tab-pane fade" id="history" role="tabpanel" aria-labelledby="history-tab">
    <h2>Historique des Trades</h2>
    <table class="table table-sm table-hover">
      <thead>
        <tr>
          <th>Symbol</th><th>Buy Prob</th><th>Sell Prob</th>
          <th>Jours</th><th>PNL (USDT)</th><th>PNL (%)</th><th>Status</th>
        </tr>
      </thead>
      <tbody>
      {% for tr in trades %}
        <tr>
          <td>{{ tr.symbol }}</td>
          <td>{{ tr.buy_prob }}</td>
          <td>{{ tr.sell_prob }}</td>
          <td>{{ tr.days_held }}</td>
          <td>{{ tr.pnl_usdt }}</td>
          <td>{{ tr.pnl_pct }}%</td>
          <td>{{ tr.status }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Emergency Tab -->
  <div class="tab-pane fade" id="emergency" role="tabpanel" aria-labelledby="emergency-tab">
    <h2>Emergency Exit</h2>
    <p>
      <button class="btn btn-danger" onclick="triggerEmergency()">Vendre toutes les positions (Emergency Out)</button>
    </p>
    <p id="emergencyResult" style="color:red;"></p>
  </div>

  <!-- Logs Tab -->
  <div class="tab-pane fade" id="logs" role="tabpanel" aria-labelledby="logs-tab">
    <h2>Logs (bot.log)</h2>
    <div style="max-height:400px; overflow:auto; border:1px solid #ccc; padding:10px;" id="logsContainer">
      <pre id="logsContent"></pre>
    </div>
  </div>

</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
// Appel Ajax pour "Emergency"
function triggerEmergency(){
  if(confirm("Confirmer l'Emergency Out ?")) {
    fetch("{{ url_for('emergency_api', pwd=secret_pwd) }}", {method:'POST'})
    .then(r=>r.json())
    .then(j=>{
      document.getElementById("emergencyResult").innerText = j.message;
    })
    .catch(e=>{
      document.getElementById("emergencyResult").innerText="Erreur: "+e;
    });
  }
}

// Rafraichir logs toutes les 3s
function refreshLogs(){
  fetch("{{ url_for('get_logs', pwd=secret_pwd) }}")
   .then(r=>r.text())
   .then(txt=>{
     document.getElementById("logsContent").innerText = txt;
   })
   .catch(e=>{
     console.log("Erreur logs", e);
   });
}
setInterval(refreshLogs, 3000);
</script>
</body>
</html>
"""

app = Flask(__name__)

###########################################
# Configuration
###########################################
SECRET_PWD = "SECRET123"  # URL => /dashboard/SECRET123

###########################################
# ROUTES
###########################################
@app.route(f"/dashboard/<pwd>", methods=["GET"])
def dashboard(pwd):
    """
    URL: /dashboard/SECRET123
    Affiche page avec onglets: Positions, Perf, Tokens, Hist Trades, Emergency, Logs
    """
    if pwd != SECRET_PWD:
        return "Forbidden", 403

    # Récup data
    pf = get_portfolio_state()
    tokens = list_tokens_tracked()
    perf = get_performance_history()
    trades = get_trades_history()
    model_date = get_model_version_date()

    return render_template_string(
        TEMPLATE_HTML,
        pf=pf,
        tokens=tokens,
        perf=perf,
        trades=trades,
        model_date=model_date,
        secret_pwd=SECRET_PWD
    )

@app.route(f"/emergency/<pwd>", methods=["POST"])
def emergency_api(pwd):
    """
    Appel AJAX => vend tout
    """
    if pwd != SECRET_PWD:
        return jsonify({"message":"Forbidden"}), 403
    emergency_out()
    return jsonify({"message":"Emergency Out déclenché."})

@app.route(f"/logs/<pwd>", methods=["GET"])
def get_logs(pwd):
    """
    Affiche ~200 dernières lignes du log
    """
    if pwd != SECRET_PWD:
        return "Forbidden", 403
    txt = tail_logs(num_lines=200)
    return txt, 200, {"Content-Type":"text/plain; charset=utf-8"}


def run_dashboard():
    # Lance le serveur Flask
    app.run(host="0.0.0.0", port=5000, debug=False)

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    run_dashboard()
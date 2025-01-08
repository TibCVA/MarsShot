#!/usr/bin/env python3
# coding: utf-8

"""
Mini-dashboard Flask pour MarsShot.
Affiche plusieurs onglets (Positions, Perf, Tokens, Trades, Emergency, Logs)
en mode responsive (Bootstrap), et concatène TOUS vos logs :
 - bot.log
 - data_fetcher.log
 - ml_decision.log
dans l'onglet "Logs".

# === AJOUT BOUTON FORCE DAILY UPDATE ===
 => On ajoute un bouton "Forcer Daily Update" qui appelle la route Flask "/force_daily_update/<pwd>".
"""

import os
import datetime
import logging
from flask import Flask, request, jsonify, render_template_string

# === On importe les fonctions REELLES (sans fallback) ===
try:
    from modules.telegram_integration import (
        get_portfolio_state,
        list_tokens_tracked,
        get_performance_history,
        get_trades_history,
        emergency_out
    )
except ImportError as e:
    raise ImportError(f"[ERREUR] Impossible d'importer telegram_integration: {e}")

########################
# 1) Lecture + concaténation de TOUS les logs
########################

ALL_LOG_FILES = [
    "bot.log",
    "data_fetcher.log",
    "ml_decision.log"
]

def tail_all_logs(num_lines=200):
    combined_lines = []
    for logf in ALL_LOG_FILES:
        if os.path.exists(logf):
            try:
                with open(logf, "r") as f:
                    lines = f.readlines()
                lines = lines[-num_lines:]
                combined_lines.append(f"\n=== [ {logf} ] ===\n")
                for line in lines:
                    combined_lines.append(line)
            except Exception as e:
                combined_lines.append(f"\n[LOG ERROR] Impossible de lire {logf} => {e}\n")
        else:
            combined_lines.append(f"\n[{logf}] n'existe pas.\n")
    return "".join(combined_lines)

########################
# 2) Model info
########################
def get_model_version_date():
    fname = "model.pkl"
    if os.path.exists(fname):
        t = os.path.getmtime(fname)
        dt = datetime.datetime.fromtimestamp(t)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        return "model.pkl introuvable"

########################
# 3) Flask app
########################
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

SECRET_PWD = "SECRET123"

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
    <h2>Positions Actuelles (Compte Live)</h2>
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

    <!-- === AJOUT BOUTON FORCE DAILY UPDATE === -->
    <hr/>
    <h4>Forcer le Daily Update</h4>
    <p>
      <button class="btn btn-warning" onclick="forceDailyUpdate()">Forcer le daily update</button>
    </p>
    <p id="forceDailyResult" style="color:blue;"></p>

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
    <h2>Logs (Toutes sources)</h2>
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

// === AJOUT BOUTON FORCE DAILY UPDATE ===
function forceDailyUpdate(){
  if(confirm("Forcer le daily update ?")) {
    fetch("{{ url_for('force_daily_update', pwd=secret_pwd) }}", {method:'POST'})
    .then(r=>r.json())
    .then(j=>{
      alert("Réponse daily update: " + j.message);
    })
    .catch(e=>{
      alert("Erreur daily update: " + e);
    });
  }
}

</script>
</body>
</html>
"""

app = Flask(__name__)

@app.route(f"/dashboard/<pwd>", methods=["GET"])
def dashboard(pwd):
    if pwd != SECRET_PWD:
        return "Forbidden", 403

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
    if pwd != SECRET_PWD:
        return jsonify({"message":"Forbidden"}), 403
    emergency_out()
    return jsonify({"message":"Emergency Out déclenché."})

# === AJOUT BOUTON FORCE DAILY UPDATE ===
@app.route(f"/force_daily_update/<pwd>", methods=["POST"])
def force_daily_update(pwd):
    if pwd != SECRET_PWD:
        return jsonify({"message":"Forbidden"}), 403
    # On appelle la fonction daily_update_live (depuis main)
    # => Il faut l'importer ou la dupliquer. On va faire un import tardif :
    from main import load_state, save_state, daily_update_live
    import yaml

    with open("config.yaml","r") as f:
        config = yaml.safe_load(f)

    state = load_state()
    bexec = TradeExecutor(
        api_key=config["binance_api"]["api_key"],
        api_secret=config["binance_api"]["api_secret"]
    )
    daily_update_live(state, config, bexec)
    return jsonify({"message":"Daily Update déclenché manuellement."})

@app.route(f"/logs/<pwd>", methods=["GET"])
def get_logs(pwd):
    if pwd != SECRET_PWD:
        return "Forbidden", 403
    txt = tail_all_logs(num_lines=200)
    return txt, 200, {"Content-Type":"text/plain; charset=utf-8"}

def run_dashboard():
    logging.info("[DASHBOARD] Starting Flask on 0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    run_dashboard()

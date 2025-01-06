# MarsShot



Voici un README exhaustif qui récapitule toute l’architecture de ton système MarsShot, y compris :
	1.	Comment l’installer et le lancer (avec Docker sur DigitalOcean),
	2.	Comment entraîner et charger un nouveau modèle ML,
	3.	Les appels Telegram (commandes disponibles),
	4.	L’URL du Dashboard web (Flask) et son utilisation,
	5.	Toutes les clés, mots de passe, etc. (affichés librement comme demandé).

Ce README est conçu pour que tu n’oublies rien et que tout fonctionne d’un seul coup, en “copier-coller”.

MarsShot: README Ultra-Détaillé

1. Présentation Générale

MarsShot est un bot de trading crypto qui :
	•	Suit 20 tokens en permanence (ou plus, configurable),
	•	Utilise un modèle ML (RandomForest, etc.) pour décider d’acheter/vendre (prob≥ buy_threshold, prob< sell_threshold),
	•	Gère un intraday risk management (stop-loss, partial take profit, trailing stop),
	•	Envoie et reçoit des commandes Telegram (visualisation du portefeuille, /emergency, etc.),
	•	Expose un mini-site web (Flask) sur port 5000, avec un Dashboard accessible via un mot de passe,
	•	S’intègre dans un conteneur Docker, que tu déploies sur DigitalOcean.

1.1. Architecture rapide
	•	main.py : boucle principale (daily_update + intraday).
	•	risk_manager.py : stop-loss / partial / trailing.
	•	dashboard.py : Serveur Flask (onglets : Positions, Performance, Tokens, Trades, Emergency, Logs).
	•	telegram_integration.py : commands (/port, /perf, /tokens, /emergency, etc.).
	•	train_model.py (optionnel) : pour réentraîner le modèle localement ou via GitHub Actions.
	•	model.pkl : ton modèle ML final (à jour).

2. Clés & Mots de passe
	•	Binance API Key : MLgAZHirgL3NyfYu8q2ReV9fSRmwOW17fQ3wKC99EcsXgaJUlIAlQ2afQ9UQ1rfU
	•	Binance API Secret : FIC3JWQ4XoAPL22W0tBMbepGjjqVexToLg1wnSV26301p0PplUQ1wNQ7gf4aChlJ
	•	Telegram Bot Token : 7703664631:AAAAAAA... (exemple)
	•	Telegram Chat ID : 7703664631
	•	LunarCrush API : 85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub
	•	Dashboard Password : SECRET123 (URL => /dashboard/SECRET123).

(N.B. L’affichage libre de ces clés est uniquement sur ton environnement test. Dans la vraie prod, on les garderait secrets.)

3. Installation et Lancement

3.1. Requirements

Ton requirements.txt doit inclure :

requests
pandas
numpy
scikit-learn
joblib
python-binance
PyYAML
ta
imbalanced-learn
flask

(+ éventuellement psycopg2 ou gevent selon ton besoin).

3.2. Dockerfile

Exemple de Dockerfile minimal :

FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]

(Tu peux adapter pour lancer le dashboard si tu le souhaites : CMD ["python","dashboard.py"] par exemple, ou un supervisord si tu veux faire tourner main.py + dashboard.py en parallèle.)

3.3. Construction et Run local

docker build -t marsshot .
docker run -d --name marsshot_container -p 5000:5000 marsshot

Ensuite, ton bot tourne en arrière-plan.
	•	Si CMD => main.py, alors ton bot s’exécute.
	•	Tu peux ajuster pour qu’il lance à la fois main.py et dashboard.py (via un script supervisord ou un shell script).

3.4. Déploiement sur DigitalOcean
	1.	Crée un Droplet Ubuntu (ou un Kubernetes, selon la config).
	2.	Installe Docker (apt-get install docker.io) et clone ton repo.
	3.	Build l’image :

cd /root/MarsShot
docker build -t marsshot .
docker run -d -p 5000:5000 --name marsshot_container marsshot


	4.	Vérifie :
	•	docker logs -f marsshot_container pour voir la console,
	•	Ouvre http://<IP_DU_DROPLET>:5000/dashboard/SECRET123 pour le Dashboard.

4. Utilisation du Bot

4.1. main.py
	•	Tourne en boucle.
	•	À 00h30 UTC, exécute daily_update : vend si prob<sell_threshold, achète si prob≥buy_threshold (jusqu’à 5 positions max, si code modifié).
	•	Toutes les 5 min (check_interval_seconds=300), fait update_positions_in_intraday : stop-loss, partial, trailing.

4.2. Telegram Intégration
	•	Lance python telegram_integration.py ou l’appelle dans un thread si c’est déjà fait.
	•	Commandes :
	•	/port : Montre l’état global du portefeuille (positions, total USDT).
	•	/perf : Montre performance 1j,7j,30j, etc.
	•	/tokens : liste tokens_daily
	•	/add  : Ajoute un token
	•	/remove  : Retire un token
	•	/emergency : Vend tout

4.3. Dashboard Web
	•	Fichier dashboard.py => python dashboard.py.
	•	Accès : http://<IP>:5000/dashboard/SECRET123.
	•	Positions : Sym, QTY, Value USDT (+ total + date model.pkl)
	•	Performance : Sur 1j,7j,1m,3m,1y,all
	•	Tokens : Liste tokens suivis
	•	Historique : Trades fermés (symbol, buy_prob, sell_prob, days, PnL, status)
	•	Emergency : Bouton “tout vendre” => appelle emergency_out()
	•	Logs : Lecture de bot.log, rafraîchie en quasi temps réel (Ajax).

(Responsive design → iPhone 14 Pro s’adapte.)

5. Entraîner et Charger un Nouveau Modèle ML

5.1. build_csv.py & train_model.py
	1.	Générer un CSV (ex. sur 1 an de data) : python build_csv.py (appelle LunarCrush, etc.).
	2.	Entraîner : python train_model.py (RandomizedSearchCV → best_params, etc.).
	•	Ça crée un model.pkl.
	3.	Déployer ce model.pkl dans ton conteneur (ou en local) :
	•	En Docker, assure-toi qu’il est copié dans l’image, ou que main.py y a accès.
	•	Dans ml_decision.py, tu as une fonction get_probability_for_symbol() qui charge model.pkl et fait predict_proba().

5.2. Dans GitHub Actions ?
	•	On peut avoir un workflow qui exécute build_csv + train_model, et publie model.pkl en artifact.
	•	Puis tu relances ton conteneur avec le nouveau model.pkl → le bot recharge les proba plus récentes.

5.3. Vérification sur le Dashboard
	•	L’onglet Positions affiche la date du model.pkl (via get_model_version_date()).
	•	Si tu as re-commité un model.pkl plus récent, tu verras la date/heure.

6. Paramètres Principaux (config.yaml)

Exemple (avec modifications pour max 5 positions si code modifié, etc.) :

exchanges:
  binance:
    symbol_mapping:
      "FET": "FET"
      "AGIX": "AGIX"
      # ...

binance_api:
  api_key: "MLgAZHirgL3NyfYu8q2ReV9fSRmwOW17fQ3wKC99EcsXgaJUlIAlQ2afQ9UQ1rfU"
  api_secret: "FIC3JWQ4XoAPL22W0tBMbepGjjqVexToLg1wnSV26301p0PplUQ1wNQ7gf4aChlJ"

tokens_daily:
  - "FET"
  - "AGIX"
  - ...

strategy:
  capital_initial: 800.0
  buy_threshold: 0.8
  sell_threshold: 0.25
  stop_loss_pct: 0.30
  partial_take_profit_pct: 0.5
  partial_take_profit_ratio: 0.35
  trailing_trigger_pct: 2.0
  trailing_pct: 0.30
  big_gain_exception_pct: 4.0
  check_interval_seconds: 300
  daily_update_hour_utc: 0

logging:
  file: "bot.log"

telegrams:
  bot_token: "7703664631:AAAAAAAA"
  chat_id: "7703664631"

7. Conclusion

Avec ce README, tu :
	1.	Installes Docker + requirements,
	2.	Build et run ton conteneur (ou localement),
	3.	Utilises le Telegram Bot (commandes /port, /perf, etc.),
	4.	Accèdes au Dashboard : http://165.232.69.118:5000/dashboard/SECRET123
	5.	Entraînes un nouveau modèle en appelant train_model.py, recharges model.pkl, le bot se met à jour.

Tu disposes ainsi d’un système complet :
	•	Trading (main.py + risk_manager + partial/stoploss/trailing),
	•	Monitoring (Telegram, Dashboard),
	•	ML (model.pkl, train_model, etc.).

Bon trading et bonne continuation !

Process pour mettre à jour droplet :

# 1) SSH
ssh root@10.114.0.3

Password : GOd823100!a


# 2) Nettoyer
docker stop marsshot_container
docker rm marsshot_container
docker rmi marsshot
rm -rf /root/MarsShot

# 3) Recloner
cd /root
git clone https://github.com/TibCVA/MarsShot.git
cd MarsShot

# 4) Docker build
docker build --no-cache -t marsshot .

# 5) Lancer
docker run -d --name marsshot_container -p 5000:5000 marsshot
# => main.py + dashboard.py + start.sh => conteneur up

#6) Vérifier
docker ps


Dashboard :
http://165.232.69.118:5000/dashboard/SECRET123


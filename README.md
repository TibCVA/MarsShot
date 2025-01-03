# MarsShot

Voici un récapitulatif didactique et exhaustif du fonctionnement bout en bout de ton système de trading actuel, tel qu’il ressort de l’ensemble des fichiers et de la logique que nous avons mis en place :

1. Vue d’ensemble du système

Ton système de trading se compose de deux grands volets :
	1.	Le volet “Entraînement ML” (off-chain, si l’on peut dire)
	•	Génère un dataset d’entraînement complet via build_csv.py.
	•	Entraîne un modèle RandomForest via train_model.py.
	•	Produit un fichier model.pkl qui encapsule les paramètres du meilleur modèle trouvé.
	2.	Le volet “Exécution du Bot de Trading” (en continu)
	•	Lance main.py, qui tourne en boucle 24 h/24.
	•	Gère :
	•	Les décisions d’achat/vente quotidiennes (basées sur la probabilité ML).
	•	Le suivi intraday (5 min) pour appliquer le stop-loss, la prise de profit partielle, le trailing stop, etc.
	•	Se connecte à des API externes (Binance pour trader, Coinbase pour le prix intraday, LunarCrush pour les données journalières, etc.).
	•	S’appuie sur model.pkl pour calculer des probabilités et décider des actions à mener.

2. Le volet “Entraînement ML”

2.1. Fichiers principaux
	•	build_csv.py
	•	Récupère l’historique (1 an) des tokens depuis l’API LunarCrush (en daily).
	•	Calcule RSI, MACD, ATR (via indicators.py).
	•	Calcule la colonne label (1 si +5 % sur 2 jours, 0 sinon) selon la configuration (SHIFT_DAYS=2, THRESHOLD=0.05).
	•	Merge BTC et ETH “daily_change” pour chaque date.
	•	Produit un fichier CSV nommé training_data.csv.
	•	train_model.py
	•	Lit training_data.csv.
	•	Détermine un ensemble de features (close, volume, market_cap, galaxy_score, alt_rank, sentiment, rsi, macd, atr, btc_daily_change, eth_daily_change, etc.).
	•	Exécute une RandomizedSearchCV pour trouver les meilleurs hyperparamètres d’un RandomForest.
	•	Sauvegarde le meilleur modèle dans model.pkl.
	•	indicators.py
	•	Calcule RSI, MACD et ATR avec la même logique de “cleaning” (si open=0, close=0 => on force NaN, on drop la ligne).
	•	Se retrouve “appelé” à la fois par build_csv.py (pour construire le dataset) et potentiellement par d’autres scripts qui veulent le même calcul (ex. en inference si besoin).

2.2. Quand et comment ré-entraîner le modèle

2.2.1. Via GitHub Actions (pipeline)
	•	Tu as un workflow GitHub (dans .github/workflows/ci_pipeline.yml) qui se déclenche sur workflow_dispatch.
	•	Étapes pour un non-codeur :
	1.	Aller sur GitHub, trouver l’onglet “Actions” dans ton repo.
	2.	Sélectionner le workflow “Build and Train Pipeline”.
	3.	Cliquer sur “Run workflow” (ou “Dispatch workflow”).
	4.	GitHub Actions va :
	•	Installer Python, exécuter build_csv.py => produire/artifact training_data.csv.
	•	Puis exécuter train_model.py => produire/artifact model.pkl.
	5.	Tu pourras récupérer model.pkl en artifact ou le laisser tel quel dans le repo (selon la config).

2.2.2. En local (option)
	•	Tu peux aussi lancer manuellement :

python build_csv.py
python train_model.py

Cela génère training_data.csv et model.pkl dans le même dossier.

Une fois le nouveau model.pkl généré, le bot qui tourne en continu s’il détecte que tu as mis à jour model.pkl (et relancé le bot), utilisera la nouvelle version du modèle.

3. Le volet “Exécution du Bot de Trading” (main.py)

3.1. Fichier main.py
	•	Tourne en continu.
	•	Charge la config (config.yaml), initialise les logs, etc.
	•	Charge l’état (positions en cours, capital USDT, etc.) depuis bot_state.json (géré par positions_store.py).
	•	Dans une boucle infinie :
	•	Vérifie l’heure pour déclencher un “daily_update” si on est après 00h30 UTC.
	•	Applique un “intraday check” toutes les 5 minutes (stop-loss, trailing, etc.).
	•	Dort 10 secondes entre chaque itération.

3.2. daily_update (une fois par jour, 00h30 UTC)
	•	Pour chaque token en portefeuille, on calcule la proba ML (via get_probability_for_symbol) :
	•	Si prob<0.30, on vend (sauf exception si la position a déjà fait +300 %, ce qui est ×4, et qu’on n’a pas encore “skip” la vente une fois).
	•	Pour chaque token de la liste tokens_daily (depuis config.yaml) qu’on ne détient pas encore :
	•	On calcule la proba. Si prob≥0.70, on achète en répartissant le capital USDT disponible équitablement entre tous les signaux.
	•	Exemple :
	•	Il est 00h45 UTC. Ton bot voit 5 tokens avec prob≥0.70 => tu as 1000 USDT => 1000/5 = 200 USDT par token. Tu fais 5 ordres “BUY” sur Binance, 200 USDT chacun.
	•	Inversement, si tu avais 3 tokens en portefeuille et l’un a prob<0.30, tu le vends tout (sauf si la position est déjà à ×4 et qu’on n’a pas encore skip la vente).

3.3. Intraday check (toutes les 5 min)
	•	On utilise fetch_prices_for_symbols (Coinbase API) pour récupérer le prix spot USD de tous les tokens qu’on détient déjà.
	•	Positions => passées dans risk_manager.update_positions_in_intraday(...), qui applique :
	1.	Stop-loss = -50 % vs. prix d’entrée. On vend tout si on tombe sous ce niveau.
	2.	Partial take profit = +100 % => on vend 20 % de la position, une seule fois.
	3.	Trailing stop = +200 % (×3). Dès qu’on atteint ×3, on track le plus haut ; si le prix retombe de 30 %, on vend tout.

Exemple d’intraday
	•	Tu as acheté FET à 0.10 $. 2 heures plus tard, le prix passe à 0.20 $. On est à ×2 => +100 %. La fonction intraday check voit le gain_ratio=2.0≥2.0, vend 20 % et marque “partial_sold=True”.
	•	Plus tard, FET monte à 0.30 => gain_ratio=3 => on active le trailing. Si le prix atteint 0.32 => on met max_price=0.32, donc le stop est 0.224 (70 % de 0.32). Si le prix retombe sous 0.224 => on vend tout.

Le capital (USDT) récupéré est alors disponible pour le jour suivant (daily_update) si on veut acheter un autre token.

4. Les données captées et leurs sources
	1.	LunarCrush (API)
	•	build_csv.py : Récupère 1 an d’historique daily pour ~150 tokens + BTC/ETH.
	•	ml_decision.py (ou get_probability_for_symbol) : Récupère à la demande 1 an d’historique daily pour 1 token + BTC/ETH.
	•	Champs collectés : open, high, low, close, volume_24h, market_cap, galaxy_score, alt_rank, sentiment, etc.
	•	Dans le dataset final, on calcule RSI, MACD, ATR (indicators.py).
	2.	Coinbase (API)
	•	Intraday : toutes les 5 min, pour chaque token qu’on détient en portefeuille, on fait un appel “spot price” sur l’endpoint public (ex. FET-USD/spot).
	•	Utilisé pour la gestion des SL, partial, trailing.
	3.	Binance (API)
	•	Exécution des ordres : Le bot appelle trade_executor.py, qui crée des ordres MARKET (BUY ou SELL) sur Binance.
	•	Clé API/Secret stockés dans config.yaml.
	4.	Local (fichiers)
	•	model.pkl : ton modèle ML.
	•	bot_state.json : l’état du bot (positions, capital_usdt, etc.).
	•	config.yaml : paramétrage global.

5. Mise à jour de la liste de tokens et variables clés

Tout se passe dans config.yaml :
	•	tokens_daily : la liste des tokens surveillés en daily-update (pour acheter/vendre). Exemple :

tokens_daily:
  - "FET"
  - "AGIX"
  - "ARB"
  - "OP"

Tu peux l’éditer pour en enlever/rajouter. Au prochain daily_update, le bot tiendra compte de ces tokens.

	•	Variables stratégiques :

strategy:
  capital_initial: 1000.0
  buy_threshold: 0.70
  sell_threshold: 0.30
  stop_loss_pct: 0.50
  partial_take_profit_pct: 1.0
  trailing_trigger_pct: 3.0
  trailing_pct: 0.30
  big_gain_exception_pct: 4.0
  check_interval_seconds: 300
  daily_update_hour_utc: 0

	•	buy_threshold (≥0.70) : si la proba modélisée est ≥0.70 => achat.
	•	sell_threshold (<0.30) : si la proba est <0.30 => vente.
	•	stop_loss_pct = 0.50 => -50 % du prix d’entrée => intraday.
	•	etc.

Exemple concret

Si tu veux augmenter le buy_threshold à 0.75 et mettre le stop_loss à -40 % :

strategy:
  buy_threshold: 0.75
  stop_loss_pct: 0.40
  ...

Puis, tu redémarres ton bot (python main.py). Désormais, la stratégie d’achat/vente suivra ces nouveaux réglages.

6. Exemples concrets pour illustrer
	1.	Exemple d’achat
	•	Tokens_daily = ￼.
	•	À 00h35 UTC, le bot calcule la proba pour FET = 0.72 et AGIX = 0.65.
	•	buy_threshold=0.70 => FET≥0.72 => on achète FET. AGIX=0.65 => sous 0.70 => on ne l’achète pas.
	•	On a 1000 USDT => on met tout sur FET (ou si tu avais 2 signaux≥0.70, on partage).
	2.	Exemple de vente (daily)
	•	On détient FET acheté à 0.10 $.
	•	24 h plus tard, la proba = 0.25 => c’est <0.30 => on vend.
	•	Sauf si FET a fait ×4 => 0.40 => “big_gain_exception_pct=4.0” => on ignore le signal vente une seule fois si on n’a jamais skip.
	3.	Exemple intraday (toutes les 5 min)
	•	FET vient de monter à +100 % => 0.20 => gain_ratio=2.0.
	•	La fonction intraday check vend 20 % pour “securiser” un profit partiel.
	•	Ou si on monte à ×3 => trailing stop ; on track le plus haut, et si on retrace de 30 %, on vend tout.

7. Conclusion

En résumé :
	1.	Pour ré-entraîner le modèle :
	•	Option GitHub Actions :
	•	Ouvrir l’onglet “Actions” sur GitHub.
	•	Choisir “Build and Train Pipeline”.
	•	Cliquer sur “Run workflow”.
	•	Patienter ; le CSV sera construit, le modèle sera entraîné, et model.pkl sera mis à jour (uploadé en artifact ou dans le repo, selon ta config).
	2.	Pour mettre à jour la liste de tokens ou ajuster le risk management :
	•	Éditer config.yaml.
	•	Modifier tokens_daily: pour ajouter/enlever.
	•	Modifier les valeurs de strategy: (buy_threshold, stop_loss_pct, etc.).
	•	Sauvegarder et relancer main.py (ou laisser le bot recharger la conf s’il en est capable).
	3.	Le bot (main.py) :
	•	Achète et vend une fois par jour en se basant sur la proba ML (≥0.70 ou <0.30).
	•	Surveille ensuite en continu (toutes les 5 min) le prix spot sur Coinbase pour appliquer SL, partial TP, trailing.
	•	Communique avec Binance pour exécuter les ordres MARKET.
	•	Stocke son état dans bot_state.json.

Tout cela te donne un système complet :
	•	Transversal (des données journalières via LunarCrush, des prix intraday via Coinbase).
	•	Automatique (le bot prend les décisions d’achat/vente selon le modèle ML + la stratégie agressive).
	•	Facile à paramétrer (via config.yaml).
	•	Facile à ré-entraîner (via GitHub Actions ou python build_csv.py && python train_model.py).

Voilà pour un rendu didactique et exhaustif !
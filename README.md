# MarsShot



Voici un récapitulatif très détaillé du fonctionnement bout en bout de ton système de trading actuel ; je vais l’expliquer de manière didactique et exhaustive, avec des exemples concrets.

1. Vue d’ensemble

Ton système se compose de deux grands volets :
	1.	Le volet “Entraînement ML” (pour créer et mettre à jour un modèle de prédiction).
	•	Génère un fichier CSV d’entraînement via LunarCrush (données daily).
	•	Entraîne un RandomForest (ou autre) pour estimer la probabilité de hausse à +5 % en 2 jours.
	•	Produit un fichier model.pkl qui contient le modèle sauvegardé.
	2.	Le volet “Bot de Trading” (pour exécuter la stratégie au quotidien).
	•	Lance main.py (qui tourne en continu).
	•	Utilise Binance pour récupérer les prix “intraday” (toutes les 5 minutes) afin d’appliquer :
	•	Le stop-loss,
	•	Le trailing stop,
	•	La prise de profit partielle, etc.
	•	Utilise LunarCrush + le modèle ML pour décider une fois par jour (00h30 UTC) quels tokens acheter/vendre (prob≥0.70 => buy, prob<0.30 => sell).
	•	Traite la liste tokens_daily définie dans config.yaml.
	•	Gère un bot Telegram pour recevoir des commandes (/port, /perf, etc.) et envoyer des notifications.

L’idée générale est de ne rien louper :
	•	Intraday (toutes les 5 min), on check le cours sur Binance pour sortir rapidement d’une position si elle chute trop (stop-loss) ou si on veut prendre des profits partiels, etc.
	•	Daily (une fois par jour après la clôture ~00h00 UTC, vers 00h30), on calcule la probabilité ML (via LunarCrush + model.pkl) et on prend les décisions d’achat/vente globales (ex. on achète les tokens dont la prob≥0.70 et on vend ceux dont la prob<0.30, sauf exception si la position a fait ×4).

2. Données captées et à quel moment

2.1. Données “daily” (pour le ML)
	•	Source : LunarCrush.
	•	Script : build_csv.py ou data_fetcher.py (partie “LunarCrush”), selon comment tu l’as structuré.
	•	Contenu :
	•	Historique daily pour 1 an (ou N jours) : open, high, low, close, volume, market_cap, plus galaxy_score, alt_rank, etc.
	•	On calcule RSI(14), MACD, ATR, la colonne label (si +5 % sur 2 jours).
	•	Usage : création du training_data.csv, qui sert à entraîner le modèle.

2.2. Données “intraday” (toutes les 5 min)
	•	Source : Binance.
	•	Script : data_fetcher.py (partie “intraday => binance”).
	•	Contenu :
	•	On récupère le prix spot (par ex. FETUSDT) via get_symbol_ticker.
	•	Usage :
	•	Dans risk_manager.py, pour voir le cours actuel.
	•	On applique le stop-loss, trailing, etc.

2.3. Données “Telegram”
	•	Source : utilisateur, via /port, /perf, /tokens, /add, /remove, /emergency.
	•	Script : telegram_integration.py.
	•	Usage : pilotage, monitoring, notifications (4 fois par jour + alertes d’achat/vente).

3. Logique de trading “step by step” (avec exemples)

3.1. Boucle principale (main.py)
	•	Tourne en continu (ex: python main.py).
	•	Toutes les 10 secondes, on vérifie :
	1.	Est-on après 00h30 UTC ?
	•	Si oui et qu’on n’a pas fait le “daily update” aujourd’hui, on l’exécute.
	•	Daily update = on calcule la prob ML pour chaque token de tokens_daily :
	•	Si prob<0.30 => on vend (sauf exception +300 %).
	•	Si prob≥0.70 => on achète (répartition de la trésorerie USDT disponible).
	•	Exemple : tu arrives à 00h35. prob(FET) = 0.72 => achat de FET, prob(AGIX) = 0.65 => pas d’achat.
	2.	Intraday check (toutes les 5 minutes)
	•	On récupère le prix BINANCE des tokens en portefeuille : ex. FET=0.12 $.
	•	On applique risk_manager.update_positions_in_intraday(...) :
	•	Stop-loss => si FET chute sous 0.05 $, on vend tout.
	•	Prise partielle => si FET fait ×2 => on vend 20 %.
	•	Trailing => si FET fait ×3 => on suit le plus haut, si on redescend de 30 % => on vend tout.
	3.	Sommeil 10 secondes, puis on boucle.

3.2. Exemples concrets
	•	Exemple d’achat intraday :
	•	En réalité, l’achat se déclenche uniquement lors du daily update. Ex. à 00h35, FET a prob=0.73, on achète 200 USDT de FET.
	•	Exemple de vente intraday :
	•	À 3h du matin, FET s’effondre, le prix passe sous ton stop-loss -50 % => le bot intraday le voit => vend immédiatement.
	•	Exemple de prise de profits :
	•	FET monte de 0.10 $ à 0.20 $ => gain +100 %. Intraday le repère => vend 20 % de ta position pour sécuriser.
	•	Exemple de trailing :
	•	FET part de 0.10 $ à 0.30 $ => ×3 => active un trailing stop à -30 % => tant qu’on grimpe, on reste. Si on retombe à 0.21 $ => on vend tout.

3.3. État stocké dans positions_store
	•	À chaque action, on met à jour bot_state.json.
	•	Ex. positions["FET"] = { qty=..., entry_price=..., partial_sold=False, etc. }.

4. Comment ré-entraîner le modèle ML via GitHub Actions (pour un non-codeur)

4.1. Pipeline “Build and Train Pipeline”
	1.	Aller sur GitHub : Sur la page de ton repo, onglet “Actions”.
	2.	Sélectionner le workflow “Build and Train Pipeline” (dans .github/workflows/ci_pipeline.yml).
	3.	Cliquer sur “Run workflow” => tu peux laisser la branche “main” ou ta branche.
	4.	GitHub va exécuter :
	•	build_csv.py => génère training_data.csv (avec RSI, MACD, ATR, label=+5 %/2jours).
	•	train_model.py => lit ce CSV, fait un RandomizedSearchCV, et enregistre le meilleur modèle dans model.pkl.
	•	Ce model.pkl est ensuite uploadé en “artifact” ou dans le repo, selon ta config.

4.2. Récupérer le nouveau modèle
	•	Télécharger l’artifact “model_pkl” depuis l’onglet “Actions”, ou le laisser dans le repo si le pipeline y pousse.
	•	Redémarrer ton bot (main.py) avec le nouveau model.pkl (ou si le bot recharge le modèle dynamiquement, il le prendra à la prochaine daily update).

Exemple :
	•	“Je viens de rajouter 10 tokens dans build_csv.py => j’ai push => j’ai lancé la pipeline => j’ai un nouveau CSV => j’ai un nouveau model.pkl => maintenant le RandomForest est potentiellement plus pertinent sur ces tokens.”

5. Mettre à jour la liste de tokens ou les variables de risk management

5.1. Mettre à jour la liste tokens_daily dans config.yaml
	•	Ouvre config.yaml :

tokens_daily:
  - "FET"
  - "AGIX"
  - "ARB"
  - "OP"
  # ...


	•	Ajoute ou retire un token. Ex. - "SOLVEX".
	•	Attention : assure-toi que SOLVEX existe côté LunarCrush (pour le daily) et sur Binance (pour l’intraday).
	•	Si Binance s’appelle “SOL” ou “SOLVEXUSDT”, n’oublie pas de l’indiquer dans le symbol_mapping:

exchanges:
  binance:
    symbol_mapping:
      "SOLVEX": "SOLVEX"


	•	Redémarre le bot (ou laisse le recharger config.yaml s’il le fait dynamiquement).
	•	À la prochaine daily_update, il décidera si on achète ce nouveau token (si prob≥0.70), etc.

5.2. Changer les variables de risk management

Toujours dans config.yaml, section strategy :

strategy:
  capital_initial: 2000.0
  buy_threshold: 0.75
  sell_threshold: 0.25
  stop_loss_pct: 0.40
  partial_take_profit_pct: 1.0
  trailing_trigger_pct: 3.0
  trailing_pct: 0.30
  big_gain_exception_pct: 4.0
  check_interval_seconds: 300
  daily_update_hour_utc: 0

	•	Exemple : tu passes capital_initial de 1000 à 2000 => tu as plus de capital en USDT au départ.
	•	buy_threshold=0.75 => on sera plus sélectif pour acheter.
	•	stop_loss_pct=0.40 => on coupe la position à -40 %.
	•	Redémarre le bot => Les modifications prendront effet immédiatement.

6. Exemples concrets pour illustrer
	1.	Exemple d’entraînement
	•	Tu viens d’ajouter le token “OP” dans tokens_daily et le label build_csv.py.
	•	Sur GitHub, tu merges. Tu vas dans l’onglet Actions => “Build and Train Pipeline” => “Run”.
	•	Au bout de quelques minutes, la pipeline finit. “model.pkl” est mis à jour.
	•	Tu récupères ce model.pkl => tu le places dans le dossier du bot => tu redémarres => désormais le bot sait évaluer “OP” dans son daily update.
	2.	Exemple de trade
	•	Jour J (00h35 UTC) : prob(OP)=0.78 => Bot achète 200 USDT de OP => 30 minutes plus tard, OP s’envole.
	•	Intraday à 4h00 : OP continue de monter, on atteint +100 % => le bot vend 20 % pour sécuriser.
	•	À 12h, c’est l’heure du report Telegram => tu reçois un message auto : “valeur totale = 2000 USDT, positions = OP, etc.”
	3.	Exemple de mise à jour
	•	Tu trouves que “AGIX” n’est plus pertinent => tu l’enlèves de tokens_daily.
	•	Tu modifies config.yaml, supprimes la ligne - "AGIX".
	•	Tu redémarres le bot => s’il y a encore AGIX en portefeuille, il ne sera pas racheté à l’avenir (il sera revendu si la proba chute sous 0.30).

7. Conclusion

Bout en bout, ton système de trading :
	1.	Collecte (via build_csv.py + train_model.py) des données journalières sur ~N tokens (dont BTC, ETH pour le daily change) via LunarCrush, calcule RSI/MACD/ATR, crée training_data.csv, et génère un model.pkl.
	2.	Chaque jour, main.py fait un “daily update” pour acheter/vendre selon la prob ML (≥0.70 / <0.30).
	3.	Ttes les 5 min, un “intraday check” lit le prix sur Binance pour gérer stop-loss, trailing, etc.
	4.	État stocké dans bot_state.json, géré par positions_store.py.
	5.	Bot Telegram (telegram_integration.py) permet de :
	•	Voir /port, /perf, la liste de tokens, etc.
	•	Ajouter/supprimer un token en direct.
	•	Recevoir des alertes quand on achète/vend.
	•	Lancer un “emergency out” (tout vendre).

Pour reformer ton modèle ML : tu utilises la pipeline GitHub (onglet “Actions”) ou tu lances python build_csv.py && python train_model.py en local. Tu récupères le nouveau model.pkl. Tu redémarres le bot si nécessaire, et voilà.

Pour mettre à jour la liste de tokens ou les variables de risk management, tu modifies directement config.yaml. Par exemple tu changes stop_loss_pct=0.40 pour diminuer la tolérance aux baisses, ou tu ajoutes - "SOLVEX" dans tokens_daily (tout en vérifiant qu’il existe sur LunarCrush et sur Binance, et en renseignant symbol_mapping: { "SOLVEX": "SOLVEX" }). Ensuite tu redémarres.

Le tout forme un système complet, évolutif, et automatisé qui combine ML (données daily, prise de décision journalière) et Risk Management (intraday).



Dans la version finale du bot Telegram (tel qu’il est codé dans le script « telegram_integration.py »), les commandes disponibles sont :
	1.	/start
	•	Affiche un message de bienvenue et la liste des autres commandes disponibles.
	2.	/port
	•	Montre l’état global du portefeuille, c’est-à-dire :
	•	La valeur totale en USDT.
	•	Les positions actuelles (symbol, quantité, valeur estimée).
	3.	/perf
	•	Montre la performance détaillée par position (exemple : +X % sur 1 jour, +Y % sur 7 jours, +Z % sur 30 jours, etc.).
	•	Calcule ces performances via l’historique (klines) sur Binance.
	4.	/tokens
	•	Liste les tokens actuellement suivis (c’est-à-dire ceux présents dans la section tokens_daily de ton fichier config.yaml).
	5.	/add <symbol>
	•	Ajoute un token à la liste de suivi (ajout direct dans tokens_daily du config.yaml).
	•	Exemple : /add FET pour commencer à suivre « FET ».
	6.	/remove <symbol>
	•	Retire un token de la liste de suivi (tokens_daily).
	•	Exemple : /remove MANA pour cesser de suivre « MANA ».
	7.	/emergency
	•	Déclenche la vente immédiate de toutes les positions en portefeuille (tout passe en USDT).
	•	Cas d’usage : “panic button” si tu veux sortir du marché très rapidement.

Rappels :
	•	Les rapports automatiques (sans commande de ta part) sont aussi envoyés à 7h, 12h, 17h et 22h (par défaut), présentant la valeur totale du portefeuille.
	•	Les notifications de transaction (BUY/SELL) sont envoyées dès qu’une opération d’achat ou de vente est réalisée.

Ainsi, tu as un bot Telegram couvrant à la fois les commandes manuelles et les notifications automatiques.
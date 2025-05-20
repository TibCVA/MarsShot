#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import logging
import datetime
import yaml
import os
import pytz
import subprocess

from modules.trade_executor import TradeExecutor
from modules.positions_store import load_state, save_state
from modules.risk_manager import intraday_check_real

def load_probabilities_csv(csv_path="daily_probabilities.csv"):
    import pandas as pd
    if not os.path.exists(csv_path):
        logging.warning(f"[load_probabilities_csv] {csv_path} introuvable => return {{}}")
        return {}
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            logging.warning(f"[load_probabilities_csv] {csv_path} est vide => return {{}}")
            return {}
        prob_map = {}
        for _, row in df.iterrows():
            sym = str(row["symbol"]).strip()
            p = float(row["prob"])
            prob_map[sym] = p
        return prob_map
    except pd.errors.EmptyDataError:
        logging.warning(f"[load_probabilities_csv] {csv_path} est vide ou mal formaté (EmptyDataError) => return {{}}")
        return {}
    except Exception as e:
        logging.error(f"[load_probabilities_csv] Erreur lors de la lecture de {csv_path}: {e}")
        return {}

def run_auto_select_once_per_day(state):
    """
    Exécute auto_select_tokens.py une fois par jour.
    Ce script est censé mettre à jour config.yaml avec la clé 'extended_tokens_daily'.
    """
    # La condition "did_daily_update_today" est gérée dans la boucle principale de main()
    # avant d'appeler daily_update_live, qui elle-même appelle run_auto_select_once_per_day
    # si ce flag n'est pas positionné.
    # Pour s'assurer qu'il ne tourne qu'une fois, on pourrait ajouter un flag spécifique
    # ou se fier au fait que daily_update_live ne tourne qu'une fois.
    # La logique actuelle dans main() semble correcte pour l'exécution unique.

    logging.info("[MAIN] Tentative d'exécution de auto_select_tokens.py")
    try:
        # S'assurer que le chemin vers auto_select_tokens.py est correct si ce n'est pas dans le même répertoire
        # ou si le PYTHONPATH n'est pas configuré. Ici, on suppose qu'il est trouvable.
        script_path = "auto_select_tokens.py" 
        if not os.path.exists(script_path):
            # Essayer de le localiser par rapport au script main.py
            current_script_dir = os.path.dirname(os.path.abspath(__file__))
            script_path_alt = os.path.join(current_script_dir, script_path)
            if os.path.exists(script_path_alt):
                script_path = script_path_alt
            else:
                logging.error(f"[MAIN] Script auto_select_tokens.py introuvable à {script_path} ou {script_path_alt}")
                return

        process = subprocess.run(["python", script_path], check=True, capture_output=True, text=True)
        logging.info(f"[MAIN] auto_select_tokens.py exécuté avec succès. Output:\n{process.stdout}")
        if process.stderr:
             logging.warning(f"[MAIN] auto_select_tokens.py a produit des messages d'erreur (stderr):\n{process.stderr}")
    except subprocess.CalledProcessError as e:
        logging.error(f"[MAIN] Erreur lors de l'exécution de auto_select_tokens.py: {e}")
        logging.error(f"[MAIN] Stderr de auto_select_tokens.py:\n{e.stderr}")
    except FileNotFoundError:
        logging.error(f"[MAIN] Script auto_select_tokens.py non trouvé. Vérifiez le chemin.")
    except Exception as e:
        logging.error(f"[MAIN] Exception inattendue lors de run_auto_select_once_per_day: {e}")


def daily_update_live(state, bexec):
    """
    Exécute le daily update live (auto_select, data_fetcher, ml_decision, SELL/BUY, etc.)
    """
    logging.info("[DAILY UPDATE] Start daily_update_live")

    # Exécuter auto_select_tokens.py pour mettre à jour config.yaml
    # Cette fonction est maintenant appelée DANS daily_update_live pour s'assurer
    # que config.yaml est à jour AVANT sa lecture.
    # Le flag "did_daily_update_today" dans main() empêchera daily_update_live
    # de tourner plusieurs fois, donc auto_select aussi.
    logging.info("[DAILY UPDATE] Appel de run_auto_select_once_per_day depuis daily_update_live.")
    # Note: run_auto_select_once_per_day n'utilise plus le 'state' pour sa condition d'exécution,
    # car daily_update_live elle-même est conditionnée par ce flag.
    run_auto_select_once_per_day(state) # L'argument state est conservé pour la signature mais non utilisé dans la fonction modifiée.

    if not os.path.exists("config.yaml"):
        logging.error("[DAILY UPDATE] config.yaml introuvable => skip daily_update.")
        return

    # Relire config.yaml APRÈS l'exécution potentielle de auto_select_tokens.py
    # pour obtenir la liste la plus à jour de 'extended_tokens_daily'.
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logging.error(f"[DAILY UPDATE] Erreur lors de la lecture de config.yaml après auto_select: {e}")
        return

    # Récupération des listes de tokens
    # 1. Tokens auto-sélectionnés (devraient être dans "extended_tokens_daily" par auto_select_tokens.py)
    auto_selected_tokens = config.get("extended_tokens_daily", [])
    if not auto_selected_tokens:
        logging.warning("[DAILY UPDATE] La clé 'extended_tokens_daily' est vide ou absente de config.yaml après l'exécution de auto_select_tokens.py.")
    
    # 2. Tokens manuels (votre liste de suivi permanent)
    manual_tokens = config.get("tokens_daily", [])
    
    # 3. Tokens actuellement en position (significatifs, grâce à risk_manager.py modifié)
    system_positions = list(state.get("positions_meta", {}).keys())

    # Fusion des listes pour la liste finale à passer à data_fetcher
    # Utilisation de sets pour éviter les doublons, puis conversion en liste
    final_token_list_for_fetcher = list(
        set(auto_selected_tokens).union(set(manual_tokens)).union(set(system_positions))
    )

    logging.info(f"[DAILY UPDATE] Tokens from auto_select_tokens (config:extended_tokens_daily): {len(auto_selected_tokens)} - {auto_selected_tokens if len(auto_selected_tokens) < 10 else str(auto_selected_tokens[:10])+'...'}")
    logging.info(f"[DAILY UPDATE] Tokens from manual list (config:tokens_daily): {manual_tokens}")
    logging.info(f"[DAILY UPDATE] Tokens from current positions (state:positions_meta): {system_positions}")
    logging.info(f"[DAILY UPDATE] Final combined list for data_fetcher ({len(final_token_list_for_fetcher)} tokens): {final_token_list_for_fetcher if len(final_token_list_for_fetcher) < 10 else str(final_token_list_for_fetcher[:10])+'...'}")

    # Préparer la configuration pour data_fetcher (dans config_temp.yaml)
    # Créer une copie de la config pour ne pas modifier l'objet 'config' en mémoire pour le reste de cette fonction
    config_for_temp = config.copy()
    config_for_temp["extended_tokens_daily"] = final_token_list_for_fetcher # C'est cette clé que data_fetcher lira

    with open("config_temp.yaml", "w") as fw:
        yaml.safe_dump(config_for_temp, fw, sort_keys=False)
    logging.info(f"[DAILY UPDATE] config_temp.yaml créé avec {len(final_token_list_for_fetcher)} tokens dans extended_tokens_daily.")

    # Le reste de la fonction daily_update_live continue comme avant...
    # ... (récupération des paramètres de stratégie, exécution de data_fetcher, ml_decision, phase SELL, phase BUY) ...
    # Assurez-vous que la "Phase BUY" utilise également une liste de candidats pertinente.
    # Votre code original pour la phase BUY utilise:
    # buy_list = config.get("extended_tokens_daily", tokens_daily)
    # Avec la nouvelle logique, config["extended_tokens_daily"] dans config_for_temp
    # est déjà la liste fusionnée. Il serait plus propre de passer explicitement
    # final_token_list_for_fetcher à la phase BUY ou de s'assurer que config lue
    # pour la phase BUY est bien celle qui contient cette liste complète.
    # Pour l'instant, on garde la logique originale de la phase BUY qui relit `config`.
    # Il faudra s'assurer que `config` utilisé pour `buy_list` est bien celui mis à jour.
    # Le `config` lu au début de `daily_update_live` est celui qui sera utilisé pour la phase BUY.
    # Il est préférable de passer `final_token_list_for_fetcher` explicitement.

    strat          = config.get("strategy", {}) # config est celui lu après auto_select
    sell_threshold = strat.get("sell_threshold", 0.3)
    big_gain_pct   = strat.get("big_gain_exception_pct", 10.0) # Assurez-vous que c'est un float
    buy_threshold  = strat.get("buy_threshold", 0.5)

    MIN_VALUE_TO_SELL    = 5.0   
    MAX_VALUE_TO_SKIP_BUY = 20.0

    try:
        subprocess.run(
            ["python", "modules/data_fetcher.py", "--config", "config_temp.yaml"],
            check=True, # Mettre check=True pour attraper les erreurs de data_fetcher
            capture_output=True, text=True
        )
        logging.info("[DAILY UPDATE] data_fetcher.py exécuté avec succès.")
    except subprocess.CalledProcessError as e:
        logging.error(f"[DAILY UPDATE] data_fetcher.py a échoué avec le code {e.returncode}.")
        logging.error(f"[DAILY UPDATE] Stderr de data_fetcher.py:\n{e.stderr}")
        logging.error(f"[DAILY UPDATE] Stdout de data_fetcher.py:\n{e.stdout}")
        return # Arrêter si data_fetcher échoue
    except Exception as e:
        logging.error(f"[DAILY UPDATE] Exception lors de l'appel à data_fetcher.py: {e}")
        return

    if (not os.path.exists("daily_inference_data.csv")
        or os.path.getsize("daily_inference_data.csv") < 10): # Seuil bas pour un fichier non vide
        logging.warning(
            "[DAILY UPDATE] daily_inference_data.csv introuvable ou vide après data_fetcher => skip ml_decision."
        )
        return

    try:
        subprocess.run(["python", "modules/ml_decision.py"], check=True, capture_output=True, text=True)
        logging.info("[DAILY UPDATE] ml_decision.py exécuté avec succès.")
    except subprocess.CalledProcessError as e:
        logging.error(f"[DAILY UPDATE] ml_decision.py a échoué avec le code {e.returncode}.")
        logging.error(f"[DAILY UPDATE] Stderr de ml_decision.py:\n{e.stderr}")
        logging.error(f"[DAILY UPDATE] Stdout de ml_decision.py:\n{e.stdout}")
        return # Arrêter si ml_decision échoue
    except Exception as e:
        logging.error(f"[DAILY UPDATE] Exception lors de l'appel à ml_decision.py: {e}")
        return

    prob_map = load_probabilities_csv("daily_probabilities.csv")
    # Utiliser final_token_list_for_fetcher pour le log ici serait plus précis que tokens_daily
    logging.info(f"[DAILY UPDATE] Tokens considérés pour fetch (count): {len(final_token_list_for_fetcher)}, prob_map.size={len(prob_map)}")


    try:
        account_info = bexec.client.get_account()
    except Exception as e:
        logging.error(f"[DAILY UPDATE] get_account => {e}")
        return

    balances     = account_info.get("balances", [])
    holdings     = {}
    USDC_balance = 0.0
    for b in balances:
        asset = b["asset"]
        try:
            qty   = float(b.get("free", 0.0)) + float(b.get("locked", 0.0))
        except ValueError:
            logging.warning(f"[DAILY UPDATE] Impossible de parser free/locked pour {asset}. Ignoré.")
            continue
        if asset.upper() == "USDC":
            USDC_balance = qty
        elif qty > 0:
            holdings[asset] = qty

    logging.info(f"[DAILY UPDATE] Holdings actuels: {holdings}, USDC: {USDC_balance:.2f}")

    # Phase SELL
    for asset, real_qty in list(holdings.items()): # list() pour pouvoir modifier le dict en cours d'itération (si del state...)
        if asset.upper() in ["USDC","BTC","FDUSD"]: # FDUSD est un autre stablecoin commun sur Binance
            logging.info(f"[DAILY SELL] Skip stable/BTC/FDUSD => {asset}")
            continue
        
        current_px = bexec.get_symbol_price(asset)
        if current_px <= 0: # Si le prix n'est pas récupérable ou nul, on ne peut pas évaluer la valeur
            logging.warning(f"[DAILY SELL CHECK] {asset}, prix invalide ou nul ({current_px}). Impossible de vendre.")
            continue

        val_in_usd = current_px * real_qty
        prob = prob_map.get(asset, None) # Obtenir la probabilité du modèle
        
        logging.info(f"[DAILY SELL CHECK] {asset}, Val: {val_in_usd:.2f} USDC, Qty: {real_qty}, Px: {current_px:.4f}, Prob: {prob}")

        if prob is None:
            logging.info(f"[DAILY SELL] Skip {asset} => probabilité non trouvée (peut-être pas dans la sélection du modèle ou données manquantes).")
            continue
            
        if val_in_usd >= MIN_VALUE_TO_SELL and prob < sell_threshold: # Note: >= pour MIN_VALUE_TO_SELL
            meta = state.get("positions_meta", {}).get(asset, {})
            entry_px = meta.get("entry_px", 0.0)
            
            perform_sell = True # Flag pour décider de vendre
            if entry_px > 0: # Si nous avons un prix d'entrée
                ratio    = current_px / entry_px
                did_skip = meta.get("did_skip_sell_once", False)
                # S'assurer que big_gain_pct est un float (ex: 3.0 pour 300%, ou 1.1 pour +10%)
                # La logique originale semble être big_gain_exception_pct: 3.0 (pour x3)
                # Si big_gain_pct est 10.0, cela signifie un gain de 900% (ratio = 10)
                # Clarifions: si big_gain_exception_pct = 3.0, cela signifie ratio >= 3.0 (gain de 200%)
                if ratio >= big_gain_pct and not did_skip: # big_gain_pct est un multiplicateur, ex: 3.0 pour 3x
                    meta["did_skip_sell_once"] = True
                    state.setdefault("positions_meta", {})[asset] = meta # setdefault au cas où asset aurait été supprimé entre-temps
                    logging.info(f"[DAILY SELL] SKIP VENTE (BIG GAIN EXCEPTION): {asset}, ratio={ratio:.2f} >= {big_gain_pct:.2f}. Marqué pour ne plus skipper.")
                    save_state(state) # Sauvegarder l'état du flag did_skip_sell_once
                    perform_sell = False # Ne pas vendre cette fois

            if perform_sell:
                logging.info(f"[DAILY SELL] Condition de vente remplie pour {asset} (Prob: {prob:.2f} < {sell_threshold}, Val: {val_in_usd:.2f} >= {MIN_VALUE_TO_SELL}).")
                sold_val = bexec.sell_all(asset, real_qty)
                logging.info(f"[DAILY SELL LIVE] {asset}, vendu pour ~{sold_val:.2f} USDC.")
                if asset in state.get("positions_meta", {}):
                    del state["positions_meta"][asset]
                # Pas besoin de save_state ici si on le fait après la boucle de vente ou à la fin de daily_update_live
            # else: # Cas où perform_sell est False (big gain exception)
                # logging.info(f"[DAILY SELL] Vente de {asset} non effectuée en raison de l'exception big_gain.")

        else:
            logging.info(f"[DAILY SELL] Skip vente {asset}. Conditions non remplies (Val: {val_in_usd:.2f}, Prob: {prob}, SellThr: {sell_threshold}).")
    
    save_state(state) # Sauvegarder l'état après la phase de vente

    logging.info("[DAILY UPDATE] Attente de 180s (3min) pour finalisation des ventes et libération USDC.")
    time.sleep(180)

    # Récupérer à nouveau les soldes après la vente
    try:
        account_info_after_sell = bexec.client.get_account()
    except Exception as e:
        logging.error(f"[DAILY UPDATE] get_account après attente a échoué: {e}")
        return

    balances_after_sell = account_info_after_sell.get("balances", [])
    new_holdings      = {}
    new_USDC_balance  = 0.0
    for b_as in balances_after_sell:
        asset = b_as["asset"]
        try:
            qty   = float(b_as.get("free", 0.0)) + float(b_as.get("locked", 0.0))
        except ValueError:
            continue # Ignorer si free/locked ne sont pas des nombres
        if asset.upper() == "USDC":
            new_USDC_balance = qty
        elif qty > 0:
            new_holdings[asset] = qty
    logging.info(f"[DAILY UPDATE] Après attente => Holdings: {new_holdings}, USDC: {new_USDC_balance:.2f}")

    # Phase BUY
    # Utiliser la liste `final_token_list_for_fetcher` qui contient la fusion des auto-sélectionnés, manuels, et positions.
    # C'est la liste la plus complète des tokens que le système "connaît" pour ce cycle.
    buy_candidates_source_list = final_token_list_for_fetcher
    
    buy_candidates = []
    for sym in buy_candidates_source_list:
        p = prob_map.get(sym, None)
        # Log pour chaque token considéré, même s'il est filtré ensuite
        logging.debug(f"[DAILY BUY CHECK] Token: {sym}, Probabilité: {p}")

        if p is None or p < buy_threshold:
            if p is None: logging.debug(f"[DAILY BUY SKIP] {sym}: Probabilité non trouvée.")
            else: logging.debug(f"[DAILY BUY SKIP] {sym}: Probabilité {p:.2f} < seuil d'achat {buy_threshold:.2f}.")
            continue
        
        # Vérifier si on détient déjà ce token et sa valeur
        current_quantity_held = new_holdings.get(sym, 0.0)
        if current_quantity_held > 0:
            price_for_value_check = bexec.get_symbol_price(sym)
            if price_for_value_check > 0:
                value_held = price_for_value_check * current_quantity_held
                if value_held > MAX_VALUE_TO_SKIP_BUY:
                    logging.info(f"[DAILY BUY SKIP] {sym}: Déjà en portefeuille avec une valeur de {value_held:.2f} USDC (> {MAX_VALUE_TO_SKIP_BUY} USDC).")
                    continue
            else:
                logging.warning(f"[DAILY BUY CHECK] {sym}: Impossible de récupérer le prix pour vérifier la valeur détenue. Achat autorisé par défaut si prob OK.")

        buy_candidates.append((sym, p))

    buy_candidates.sort(key=lambda x: x[1], reverse=True) # Trier par probabilité décroissante
    top3_buy_candidates = buy_candidates[:3] # Sélectionner les 3 meilleurs
    
    logging.info(f"[DAILY BUY SELECT] Top 3 candidats pour achat: {top3_buy_candidates}")

    if top3_buy_candidates and new_USDC_balance > 10: # S'assurer qu'il y a des candidats et assez d'USDC
        # Allouer 99% du solde USDC disponible pour les achats, en le divisant entre les top N candidats
        usdc_to_allocate_total = new_USDC_balance * 0.99 
        num_buys_to_make = len(top3_buy_candidates)
        
        logging.info(f"[DAILY BUY] Allocation de {usdc_to_allocate_total:.2f} USDC pour {num_buys_to_make} token(s).")

        for i, (sym, p_val) in enumerate(top3_buy_candidates, start=1):
            if usdc_to_allocate_total < 10: # Si le reliquat est trop faible
                logging.info("[DAILY BUY] Reliquat USDC < 10. Arrêt des achats.")
                break

            # Diviser le reliquat restant équitablement entre les tokens restants à acheter
            usdc_per_buy = usdc_to_allocate_total / (num_buys_to_make - i + 1)
            
            logging.info(f"[DAILY BUY EXEC] Tentative d'achat de {sym} avec ~{usdc_per_buy:.2f} USDC (Prob: {p_val:.2f}).")
            qty_bought, price_bought, cost_of_buy = bexec.buy(sym, usdc_per_buy)
            
            if qty_bought > 0 and cost_of_buy > 0:
                logging.info(f"[DAILY BUY EXEC SUCCESS] {sym}: Acheté {qty_bought:.4f} pour {cost_of_buy:.2f} USDC @ {price_bought:.4f}")
                state.setdefault("positions_meta", {})[sym] = {
                    "entry_px": price_bought,
                    "did_skip_sell_once": False,
                    "partial_sold": False,
                    "max_price": price_bought # Initialiser max_price
                }
                usdc_to_allocate_total -= cost_of_buy # Réduire le capital disponible pour les achats suivants
                # save_state(state) # Sauvegarder après chaque achat réussi
            else:
                logging.warning(f"[DAILY BUY EXEC FAILED/SKIPPED] {sym}. Achat non effectué ou quantité nulle.")
                # Si l'achat échoue, on ne déduit rien de usdc_to_allocate_total pour cet achat,
                # l'argent sera redistribué aux tokens suivants.
        save_state(state) # Sauvegarder l'état une fois après la boucle d'achat
    else:
        if not top3_buy_candidates: logging.info("[DAILY BUY] Aucun candidat d'achat trouvé répondant aux critères.")
        if new_USDC_balance <= 10: logging.info(f"[DAILY BUY] Solde USDC ({new_USDC_balance:.2f}) insuffisant pour initier des achats.")

    logging.info("[DAILY UPDATE] Done daily_update_live")


def main():
    if not os.path.exists("config.yaml"):
        print("[ERREUR] config.yaml introuvable.")
        logging.critical("[MAIN] config.yaml introuvable. Arrêt.") # Log critique si config manque
        return

    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"[ERREUR] Impossible de lire ou parser config.yaml: {e}")
        logging.critical(f"[MAIN] Impossible de lire ou parser config.yaml: {e}. Arrêt.")
        return

    # Configuration du logging à partir du fichier config
    log_config = config.get("logging", {})
    log_file = log_config.get("file", "bot.log") # Valeur par défaut si non spécifié
    
    # S'assurer que le répertoire du fichier log existe
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
        except OSError as e:
            print(f"Erreur lors de la création du répertoire de log {log_dir}: {e}")
            # Continuer avec le logging dans le répertoire courant si la création échoue
            log_file = os.path.basename(log_file)


    logging.basicConfig(
        filename=log_file,
        filemode='a',
        level=logging.INFO, # Pourrait être configurable depuis config.yaml aussi
        format="%(asctime)s [%(levelname)s] %(module)s.%(funcName)s:%(lineno)d - %(message)s" # Format de log plus détaillé
    )
    logging.info("======================================================================")
    logging.info("[MAIN] Démarrage du bot de trading MarsShot.")
    logging.info("======================================================================")


    state = load_state()
    logging.info(f"[MAIN] État chargé: keys={list(state.keys())}")

    try:
        bexec = TradeExecutor(
            api_key=config["binance_api"]["api_key"],
            api_secret=config["binance_api"]["api_secret"]
        )
        logging.info("[MAIN] TradeExecutor initialisé.")
    except KeyError as e:
        logging.critical(f"[MAIN] Clé API Binance manquante dans config.yaml: {e}. Arrêt.")
        return
    except Exception as e:
        logging.critical(f"[MAIN] Erreur lors de l'initialisation de TradeExecutor: {e}. Arrêt.")
        return
        
    tz_paris = pytz.timezone("Europe/Paris") # Ou UTC si vous préférez travailler en UTC partout

    # Utiliser les heures UTC de config.yaml si disponibles, sinon valeurs par défaut
    # Note: config.yaml a "daily_update_hour_utc" mais pas de minute. On assume minute = 0.
    # La logique originale avait DAILY_UPDATE_HOUR = 2, DAILY_UPDATE_MIN = 10 (en tz_paris)
    # Pour la cohérence, utilisons UTC. Si daily_update_hour_utc est 2, cela correspond à 2h UTC.
    
    # Heure de mise à jour quotidienne (UTC)
    # Si vous voulez que ce soit 02:10 UTC, alors:
    DAILY_UPDATE_HOUR_UTC = config.get("strategy", {}).get("daily_update_hour_utc", 2) # Par défaut 2 UTC
    DAILY_UPDATE_MINUTE_UTC = 10 # Fixé à 10 minutes après l'heure.

    logging.info(f"[MAIN] Boucle principale démarrée. Mise à jour quotidienne prévue à {DAILY_UPDATE_HOUR_UTC:02d}:{DAILY_UPDATE_MINUTE_UTC:02d} UTC.")

    while True:
        try:
            # Utiliser UTC pour la logique de temps interne pour éviter les ambiguïtés de fuseau horaire
            now_utc = datetime.datetime.now(pytz.utc)
            
            # Réinitialisation du flag de daily update (ex: à 00:05 UTC)
            # Ceci doit se produire AVANT la vérification pour lancer le daily update.
            if now_utc.hour == 0 and now_utc.minute >= 0 and now_utc.minute < 5: # Fenêtre de réinitialisation
                if state.get("did_daily_update_today", False):
                    logging.info(f"[MAIN] Réinitialisation du flag 'did_daily_update_today' pour le nouveau jour UTC ({now_utc.date()}).")
                    state["did_daily_update_today"] = False
                    save_state(state)

            # Daily update live
            if (now_utc.hour == DAILY_UPDATE_HOUR_UTC and
                now_utc.minute == DAILY_UPDATE_MINUTE_UTC and
                not state.get("did_daily_update_today", False)):
                
                logging.info(f"[MAIN] Déclenchement de daily_update_live (heure planifiée: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}).")
                daily_update_live(state, bexec) # auto_select_tokens est appelé DANS daily_update_live maintenant
                state["did_daily_update_today"] = True
                state["last_daily_update_ts"] = time.time() # Stocker le timestamp de la dernière mise à jour
                save_state(state)
                logging.info("[MAIN] daily_update_live terminé et flag positionné.")

            # Intraday risk check
            last_risk_check_ts = state.get("last_risk_check_ts", 0)
            check_interval = config.get("strategy", {}).get("check_interval_seconds", 300) # Depuis config
            
            if time.time() - last_risk_check_ts >= check_interval:
                logging.info("[MAIN] Exécution de intraday_check_real().")
                intraday_check_real(state, bexec, config)
                state["last_risk_check_ts"] = time.time()
                save_state(state)

        except KeyboardInterrupt:
            logging.info("[MAIN] Interruption clavier détectée. Arrêt du bot.")
            break # Sortir de la boucle while
        except Exception as e:
            logging.error(f"[MAIN ERROR] Une erreur inattendue s'est produite dans la boucle principale: {e}", exc_info=True)
            # Ajouter un délai plus long en cas d'erreurs répétées pour éviter de spammer les logs ou les APIs
            time.sleep(60) 

        time.sleep(10) # Pause courte entre les itérations de la boucle principale
    
    logging.info("[MAIN] Boucle principale terminée.")

if __name__ == "__main__":
    main()

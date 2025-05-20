#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import yaml
import json
import time
import datetime
import pandas as pd

# Utiliser un logger spécifique pour ce module
logger_dd = logging.getLogger("dashboard_data_module")
# Le handler sera ajouté par l'application principale (dashboard.py ou main.py)
# ou par un basicConfig si ce module est exécuté d'une manière ou d'une autre seul.
if not logger_dd.hasHandlers():
    _ch_dd = logging.StreamHandler(sys.stderr)
    _fmt_dd = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    _ch_dd.setFormatter(_fmt_dd)
    logger_dd.addHandler(_ch_dd)
    logger_dd.setLevel(logging.INFO)
    logger_dd.propagate = False


# --- Import de TradeExecutor avec gestion d'erreur ---
TradeExecutor = None
trade_executor_imported = False
try:
    from modules.trade_executor import TradeExecutor as TE_Class
    TradeExecutor = TE_Class # Assigner à la variable globale du module
    trade_executor_imported = True
    logger_dd.info("TradeExecutor importé avec succès dans dashboard_data.")
except ImportError as e:
    logger_dd.error(f"Échec de l'import de TradeExecutor dans dashboard_data: {e}. Certaines fonctionnalités seront limitées.", exc_info=True)
    # Pas besoin de classe factice ici si les fonctions vérifient si TradeExecutor est None

# --- Configuration et Constantes ---
CONFIG = {}
BINANCE_KEY = None
BINANCE_SECRET = None

try:
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    CONFIG_FILE = os.path.join(CURRENT_DIR, "config.yaml") # config.yaml est à la racine avec dashboard_data.py

    if not os.path.exists(CONFIG_FILE):
        logger_dd.error(f"CRITIQUE: {CONFIG_FILE} introuvable. dashboard_data ne fonctionnera pas correctement.")
        # Ne pas lever d'exception ici pour permettre au reste de dashboard.py de s'importer
    else:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            TEMP_CONFIG = yaml.safe_load(f)
        if isinstance(TEMP_CONFIG, dict):
            CONFIG = TEMP_CONFIG
            BINANCE_KEY = CONFIG.get("binance_api", {}).get("api_key")
            BINANCE_SECRET = CONFIG.get("binance_api", {}).get("api_secret")
            if not BINANCE_KEY or not BINANCE_SECRET:
                logger_dd.error("Clés API Binance non trouvées ou incomplètes dans config.yaml.")
            else:
                logger_dd.info("Configuration et clés API chargées depuis config.yaml.")
        else:
            logger_dd.error(f"Le contenu de {CONFIG_FILE} n'est pas un dictionnaire YAML valide.")
            CONFIG = {} # Assurer que CONFIG est un dict

except FileNotFoundError: # Redondant avec le check os.path.exists mais plus explicite
    logger_dd.error(f"FileNotFoundError: {CONFIG_FILE} introuvable lors du chargement initial.")
except yaml.YAMLError as e_yaml:
    logger_dd.error(f"Erreur de parsing YAML dans {CONFIG_FILE}: {e_yaml}")
except Exception as e_cfg:
    logger_dd.error(f"Erreur inattendue lors du chargement de la configuration: {e_cfg}", exc_info=True)


# Fichiers d'historique (chemins relatifs à la racine du projet)
# Supposer que dashboard_data.py est à la racine
TRADE_FILE = os.path.join(CURRENT_DIR, "trade_history.json")
CLOSED_TRADES_FILE = os.path.join(CURRENT_DIR, "closed_trades.csv")
PERF_FILE  = os.path.join(CURRENT_DIR, "performance_history.json")


########################
# 1) Portfolio actuel
########################
def get_bexec_instance():
    """Crée et retourne une instance de TradeExecutor si possible, sinon None."""
    if not TradeExecutor:
        logger_dd.error("Classe TradeExecutor non importée, impossible de créer une instance.")
        return None
    if not BINANCE_KEY or not BINANCE_SECRET:
        logger_dd.error("Clés API Binance non disponibles, impossible d'initialiser TradeExecutor.")
        return None
    try:
        return TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    except Exception as e:
        logger_dd.error(f"Erreur lors de l'initialisation de TradeExecutor: {e}", exc_info=True)
        return None

def get_portfolio_state():
    bexec = get_bexec_instance()
    if not bexec:
        return {"positions": [], "total_value_USDC": "Erreur (TradeExecutor)"}

    try:
        info  = bexec.client.get_account()
        bals  = info.get("balances", [])
    except Exception as e:
        logger_dd.error(f"Erreur lors de la récupération des informations du compte Binance: {e}", exc_info=True)
        return {"positions": [], "total_value_USDC": "Erreur (API Binance)"}

    positions_all = []
    total_val = 0.0

    for b in bals:
        asset = b["asset"]
        try:
            free  = float(b.get("free", 0.0))
            locked = float(b.get("locked", 0.0))
        except ValueError:
            logger_dd.warning(f"Impossible de parser free/locked pour {asset} dans get_portfolio_state.")
            continue
        qty   = free + locked
        if qty <= 0:
            continue

        val_USDC = 0.0
        if asset.upper() == "USDC":
            val_USDC = qty
        else:
            try:
                px = bexec.get_symbol_price(asset) # Peut retourner 0.0 si la paire n'existe pas
                if px > 0: # Seulement si le prix est valide
                    val_USDC = px * qty
                else:
                    logger_dd.debug(f"Prix non trouvé ou nul pour {asset} lors du calcul de la valeur du portfolio.")
            except Exception as e_price:
                logger_dd.warning(f"Erreur get_symbol_price pour {asset} dans get_portfolio_state: {e_price}")
                # val_USDC reste 0.0

        pos = {
            "symbol": asset,
            "qty": round(qty, 4),
            "value_USDC": round(val_USDC, 2)
        }
        positions_all.append(pos)
        if asset.upper() != "USDC": # Ne pas ajouter la valeur USDC du solde USDC lui-même à total_val ici
            total_val += val_USDC
        elif asset.upper() == "USDC": # Ajouter le solde USDC une fois
             total_val += val_USDC


    positions_display = [
        p for p in positions_all
        if p["symbol"].upper() == "USDC" or p["value_USDC"] >= 1.5
    ]
    
    # S'assurer que total_val est bien calculé en incluant le solde USDC une seule fois.
    # Le code ci-dessus le fait déjà correctement.

    try:
        # Logique d'enregistrement de la performance (inchangée pour l'instant)
        # Mais s'assurer que record_portfolio_value est robuste
        if os.path.exists(PERF_FILE):
            with open(PERF_FILE, "r", encoding="utf-8") as f:
                hist = json.load(f)
            if hist and isinstance(hist, list) and len(hist) > 0 and isinstance(hist[-1], dict): # Plus de checks
                last_ts = hist[-1].get("timestamp", 0)
                if time.time() - last_ts > 300: # 5 minutes
                    record_portfolio_value(total_val)
            else: # Fichier existe mais vide ou mal formaté
                record_portfolio_value(total_val)
        else: # Fichier n'existe pas
            record_portfolio_value(total_val)
    except Exception as e_perf_rec:
        logger_dd.error(f"Erreur dans la logique record_portfolio_value de get_portfolio_state: {e_perf_rec}", exc_info=True)

    return {
        "positions": positions_display,
        "total_value_USDC": round(total_val, 2)
    }

def list_tokens_tracked():
    # Cette fonction dépend de CONFIG. Si CONFIG est vide, elle retournera [].
    return CONFIG.get("tokens_daily", []) if isinstance(CONFIG.get("tokens_daily"), list) else []


########################
# 2) Historique de trades
########################
def get_trades_history():
    # ... (fonction inchangée, mais utilise logger_dd) ...
    trades = []
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, "r", encoding="utf-8") as f: trades = json.load(f)
        except Exception as e: logger_dd.error(f"Erreur lecture {TRADE_FILE}: {e}", exc_info=True)
    elif os.path.exists(CLOSED_TRADES_FILE):
        try:
            df = pd.read_csv(CLOSED_TRADES_FILE)
            if "timestamp" not in df.columns and "exit_date" in df.columns:
                df["timestamp"] = pd.to_datetime(df["exit_date"], errors='coerce').astype(int) // 10**9 # errors='coerce'
            trades = df.to_dict(orient="records")
        except Exception as e: logger_dd.error(f"Erreur lecture {CLOSED_TRADES_FILE}: {e}", exc_info=True)

    # expected_keys = ["symbol", "buy_prob", "sell_prob", "days_held", "pnl_USDC", "pnl_pct", "status"] # Non utilisé
    processed_trades = []
    for trade_orig in trades:
        if not isinstance(trade_orig, dict): continue # Ignorer les entrées non valides
        trade = trade_orig.copy() # Travailler sur une copie
        if "days_held" not in trade:
            if "entry_date" in trade and "exit_date" in trade:
                try:
                    entry = pd.to_datetime(trade["entry_date"], errors='coerce')
                    exit_dt = pd.to_datetime(trade["exit_date"], errors='coerce')
                    if pd.notna(entry) and pd.notna(exit_dt):
                         trade["days_held"] = (exit_dt - entry).days
                    else: trade["days_held"] = "N/A"
                except Exception: trade["days_held"] = "N/A"
            else: trade["days_held"] = "N/A"
        for key in ["buy_prob", "sell_prob", "pnl_USDC", "pnl_pct", "status"]:
            if key not in trade:
                trade[key] = 0.0 if key in ["pnl_USDC", "pnl_pct"] else "N/A"
        processed_trades.append(trade)

    processed_trades.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return processed_trades


########################
# 3) Performance
########################
def record_portfolio_value(value_USDC):
    # ... (fonction inchangée, mais utilise logger_dd et chemins absolus) ...
    history = []
    if os.path.exists(PERF_FILE):
        try:
            with open(PERF_FILE, "r", encoding="utf-8") as f: history = json.load(f)
            if not isinstance(history, list): history = [] # S'assurer que c'est une liste
        except json.JSONDecodeError: logger_dd.warning(f"{PERF_FILE} contient du JSON invalide. Réinitialisation de l'historique."); history = []
        except Exception as e: logger_dd.error(f"Erreur lecture {PERF_FILE}: {e}", exc_info=True); history = [] # Fallback prudent
    
    now_ts = time.time()
    entry = {
        "timestamp": now_ts,
        "datetime": datetime.datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S"), # Utiliser fromtimestamp
        "value_USDC": round(float(value_USDC), 2) # S'assurer que value_USDC est float
    }
    history.append(entry)
    history.sort(key=lambda x: x.get("timestamp", 0)) # .get pour robustesse
    try:
        with open(PERF_FILE, "w", encoding="utf-8") as f: json.dump(history, f, indent=2)
    except Exception as e: logger_dd.error(f"Erreur écriture {PERF_FILE}: {e}", exc_info=True)


def get_performance_history():
    # ... (fonction inchangée, mais utilise logger_dd et chemins absolus) ...
    # Et appelle la version modifiée de get_portfolio_state
    if not os.path.exists(PERF_FILE):
        logger_dd.warning(f"{PERF_FILE} introuvable. Calcul de la performance basé sur la valeur actuelle uniquement.")
        pf_state = get_portfolio_state() # Peut retourner une structure d'erreur
        tv = pf_state.get("total_value_USDC", 0.0)
        if isinstance(tv, str): tv = 0.0 # Si c'est un message d'erreur
        return {"1d": {"USDC": tv, "pct": 0.0}, "7d": {"USDC": tv, "pct": 0.0}, "30d": {"USDC": tv, "pct": 0.0}, "all": {"USDC": tv, "pct": 0.0}}
    try:
        with open(PERF_FILE, "r", encoding="utf-8") as f: history = json.load(f)
        if not isinstance(history, list) or not history: # Si pas une liste ou vide
            raise ValueError("Historique vide ou mal formaté")
    except Exception as e:
        logger_dd.error(f"Erreur lecture ou parsing {PERF_FILE}: {e}. Performance basée sur valeur actuelle.")
        pf_state = get_portfolio_state(); tv = pf_state.get("total_value_USDC", 0.0)
        if isinstance(tv, str): tv = 0.0
        return {"1d": {"USDC": tv, "pct": 0.0}, "7d": {"USDC": tv, "pct": 0.0}, "30d": {"USDC": tv, "pct": 0.0}, "all": {"USDC": tv, "pct": 0.0}}

    last_entry = history[-1]
    current_val = last_entry.get("value_USDC", 0.0)
    now_ts = last_entry.get("timestamp", time.time())

    def find_val_x_days_ago(x_days, hist_data, current_timestamp):
        target_ts = current_timestamp - x_days * 86400
        # Filtrer les entrées valides (dictionnaires avec timestamp et value_USDC)
        valid_entries = [h for h in hist_data if isinstance(h, dict) and "timestamp" in h and "value_USDC" in h and h["timestamp"] <= target_ts]
        if not valid_entries: return None
        return valid_entries[-1]["value_USDC"] # Dernière valeur avant ou à target_ts

    def compute_perf(x_days, hist_data, current_val_pf, current_ts_pf):
        old_val = find_val_x_days_ago(x_days, hist_data, current_ts_pf)
        if old_val is None or old_val <= 0: return {"USDC": current_val_pf, "pct": 0.0}
        diff = current_val_pf - old_val; pct = (diff / old_val) * 100
        return {"USDC": round(current_val_pf,2), "pct": round(pct, 2)}

    perf_1d = compute_perf(1, history, current_val, now_ts)
    perf_7d = compute_perf(7, history, current_val, now_ts)
    perf_30d = compute_perf(30, history, current_val, now_ts)
    
    first_val = history[0].get("value_USDC", 0.0) if history and isinstance(history[0], dict) else 0.0
    pct_all = (current_val - first_val) / first_val * 100 if first_val > 0 else 0.0

    return {
        "1d": perf_1d, "7d": perf_7d, "30d": perf_30d,
        "all": {"USDC": round(current_val,2), "pct": round(pct_all, 2)}
    }

########################
# 4) Emergency Out
########################
def emergency_out():
    # ... (fonction inchangée, mais utilise logger_dd et get_bexec_instance) ...
    logger_dd.info("Tentative de déclenchement de la sortie d'urgence...")
    bexec = get_bexec_instance()
    if not bexec:
        logger_dd.error("Échec de la sortie d'urgence: Impossible d'initialiser TradeExecutor.")
        return False # Indiquer l'échec

    sold_something = False
    try:
        info = bexec.client.get_account()
        balances = info.get("balances", [])
        if not balances: logger_dd.warning("Aucun solde trouvé lors de la sortie d'urgence."); return False

        for b in balances:
            asset = b["asset"]
            try:
                qty = float(b.get("free", 0.0)) + float(b.get("locked", 0.0))
            except ValueError: continue

            if qty > 0.00000001 and asset.upper() not in ["USDC", "USDT", "BUSD", "FDUSD"]: # Seuil très bas, exclure plus de stables
                logger_dd.info(f"[EMERGENCY] Tentative de vente de {qty} {asset}...")
                try:
                    bexec.sell_all(asset, qty) # sell_all devrait logger son succès/échec
                    logger_dd.info(f"[EMERGENCY] Ordre de vente pour {asset} placé.")
                    sold_something = True
                except Exception as e_sell:
                    logger_dd.error(f"[EMERGENCY] Erreur lors de la vente de {asset}: {e_sell}", exc_info=True)
        if sold_something:
            logger_dd.info("[EMERGENCY] Sortie d'urgence terminée (ordres de vente placés).")
            return True
        else:
            logger_dd.info("[EMERGENCY] Sortie d'urgence terminée (rien à vendre ou échecs).")
            return False # Rien n'a été vendu (ou tenté d'être vendu)
            
    except Exception as e_emergency:
        logger_dd.error(f"[EMERGENCY] Erreur majeure pendant la sortie d'urgence: {e_emergency}", exc_info=True)
        return False

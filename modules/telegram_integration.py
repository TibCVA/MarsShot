#!/usr/bin/env python3
# coding: utf-8

"""
Script Telegram pour le système MarsShot.

Fonctionnalités :
- /port => Montre l'état global du portefeuille (valeur USDT, positions)
- /perf => Montre la performance 1j, 7j, 30j, since entry
- /tokens => Liste des tokens suivis (config.yaml => tokens_daily)
- /add <sym> => Ajoute un token
- /remove <sym> => Retire un token
- /emergency => Vend tout

Rapports automatiques (7h,12h,17h,22h).
Notifie toute transaction (BUY/SELL) via la fonction notify_transaction(...).
"""

import os
import logging
import time
import datetime
import threading
import yaml

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

# On importe le trade executor existant
from modules.trade_executor import TradeExecutor
from modules.positions_store import load_state, save_state
from modules.utils import send_telegram_message

CONFIG_FILE = "config.yaml"
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

# Récupération des infos binance, telegram
BINANCE_KEY    = CONFIG["binance_api"]["api_key"]
BINANCE_SECRET = CONFIG["binance_api"]["api_secret"]
BOT_TOKEN      = CONFIG["telegrams"].get("bot_token", None)
CHAT_ID        = CONFIG["telegrams"].get("chat_id", None)

if not BOT_TOKEN:
    raise ValueError("[ERREUR] bot_token manquant dans config.yaml => telegrams")

# Logging local
logging.basicConfig(level=logging.INFO)

#############################################
# 1) Fonctions pour manipuler le portefeuille
#############################################

def notify_transaction(action, symbol, qty, avg_px, usdt_val):
    """
    Notifie sur Telegram qu'on a BUY ou SELL 'symbol', qty=..., px=..., ~usdt_val.
    Cette fonction peut être appelée depuis le code trade_executor.py 
    pour chaque transaction exécutée, par ex. :

        from telegram_integration import notify_transaction
        ...
        notify_transaction("BUY", symbol, fill_qty, avg_px, fill_sum)

    """
    if not BOT_TOKEN or not CHAT_ID:
        return
    msg = (f"[TRADE] {action} {symbol}\n"
           f"QTY={qty:.4f}, PX={avg_px:.4f}, USDT~{usdt_val:.2f}")
    send_telegram_message(BOT_TOKEN, CHAT_ID, msg)

def get_portfolio_state():
    """
    Renvoie un dict contenant:
      {
        "positions": [
           {
             "symbol": "FET",
             "qty": 123.45,
             "value_usdt": 456.78,
             "pnl_1d": +5.0,
             "pnl_7d": +12.0,
             "pnl_30d": +20.0,
             "pnl_since_entry": +30.0
           }, ...
        ],
        "total_value_usdt": 2345.67
      }
    On se base sur positions_store (bot_state.json) + binance klines 
    pour calculer la performance 1j, 7j, 30j, since entry.
    """
    # Chargement de l'état
    st = load_state(CONFIG["strategy"]["capital_initial"])
    positions = st["positions"]  # ex: { "FET": { "qty":..., "entry_price":... } }
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)

    total_val = 0.0
    pos_list = []

    for sym, pos in positions.items():
        qty = pos["qty"]
        entry_px = pos["entry_price"]
        current_px = bexec.get_symbol_price(sym)  # par ex. => FET => FETUSDT
        val_usdt = current_px * qty
        total_val += val_usdt

        # Perf "since entry"
        if entry_px>0:
            perf_since = ((current_px - entry_px)/entry_px)*100
        else:
            perf_since = 0.0

        # Perf 1j
        px_1d_ago = bexec.get_kline_close(sym, days=1)
        if px_1d_ago and px_1d_ago>0:
            pnl_1d = (current_px - px_1d_ago)/px_1d_ago*100
        else:
            pnl_1d = 0.0

        # Perf 7j
        px_7d_ago = bexec.get_kline_close(sym, days=7)
        if px_7d_ago and px_7d_ago>0:
            pnl_7d = (current_px - px_7d_ago)/px_7d_ago*100
        else:
            pnl_7d = 0.0

        # Perf 30j
        px_30d_ago = bexec.get_kline_close(sym, days=30)
        if px_30d_ago and px_30d_ago>0:
            pnl_30d = (current_px - px_30d_ago)/px_30d_ago*100
        else:
            pnl_30d = 0.0

        pos_list.append({
            "symbol": sym,
            "qty": round(qty,4),
            "value_usdt": round(val_usdt,2),
            "pnl_1d": round(pnl_1d,1),
            "pnl_7d": round(pnl_7d,1),
            "pnl_30d": round(pnl_30d,1),
            "pnl_since_entry": round(perf_since,1)
        })

    return {
        "positions": pos_list,
        "total_value_usdt": round(total_val,2)
    }

def list_tokens_tracked():
    return CONFIG["tokens_daily"]

def add_token_tracked(symbol):
    """
    Ajoute 'symbol' dans config["tokens_daily"] si pas déjà présent.
    Sauvegarde config.yaml. Ensuite, le bot daily_update pourra l'acheter 
    si prob≥ buy_threshold.
    """
    sym = symbol.upper()
    if sym not in CONFIG["tokens_daily"]:
        CONFIG["tokens_daily"].append(sym)
        with open(CONFIG_FILE,"w") as f:
            yaml.dump(CONFIG, f)
        return True
    return False

def remove_token_tracked(symbol):
    """
    Retire 'symbol' de config["tokens_daily"] si présent.
    Sauvegarde config.yaml.
    """
    sym = symbol.upper()
    if sym in CONFIG["tokens_daily"]:
        CONFIG["tokens_daily"].remove(sym)
        with open(CONFIG_FILE,"w") as f:
            yaml.dump(CONFIG, f)
        return True
    return False

def emergency_out():
    """
    Vend TOUTES les positions => USDT.
    """
    st = load_state(CONFIG["strategy"]["capital_initial"])
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    for sym, pos in list(st["positions"].items()):
        qty = pos["qty"]
        val = bexec.sell_all(sym, qty)
        st["capital_usdt"] += val
        del st["positions"][sym]
    save_state(st)

#######################################
# 2) Commandes Telegram
#######################################
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Bienvenue sur MarsShot_bot !\n"
        "Commandes:\n"
        "/port => Etat global\n"
        "/perf => Performance de chaque position\n"
        "/tokens => Liste tokens suivis\n"
        "/add <sym> => Ajouter\n"
        "/remove <sym> => Retirer\n"
        "/emergency => Vendre toutes positions\n"
    )
    await update.message.reply_text(msg)

async def cmd_port(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pf = get_portfolio_state()
    msg = f"Valeur Totale: {pf['total_value_usdt']} USDT\n\nPositions:\n"
    for p in pf["positions"]:
        msg += f"- {p['symbol']}: qty={p['qty']}, ~{p['value_usdt']} USDT\n"
    await update.message.reply_text(msg)

async def cmd_perf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pf = get_portfolio_state()
    msg = "Performance:\n"
    for p in pf["positions"]:
        msg += (
            f"- {p['symbol']} => 1j={p['pnl_1d']}%, "
            f"7j={p['pnl_7d']}%, 30j={p['pnl_30d']}%, "
            f"sinceEntry={p['pnl_since_entry']}%\n"
        )
    await update.message.reply_text(msg)

async def cmd_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tokens = list_tokens_tracked()
    if tokens:
        msg = "Tokens suivis:\n" + ", ".join(tokens)
    else:
        msg = "Aucun token suivi."
    await update.message.reply_text(msg)

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args)<1:
        await update.message.reply_text("Usage: /add <symbol>")
        return
    sym = context.args[0].upper()
    ok = add_token_tracked(sym)
    if ok:
        await update.message.reply_text(f"{sym} ajouté à la liste.")
    else:
        await update.message.reply_text(f"{sym} déjà présent ou échec.")

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args)<1:
        await update.message.reply_text("Usage: /remove <symbol>")
        return
    sym = context.args[0].upper()
    ok = remove_token_tracked(sym)
    if ok:
        await update.message.reply_text(f"{sym} retiré de la liste.")
    else:
        await update.message.reply_text(f"{sym} pas trouvé ou échec.")

async def cmd_emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emergency_out()
    await update.message.reply_text(
        "Toutes les positions ont été vendues en USDT (emergency out)."
    )

#######################################
# 3) Rapports Auto (7h,12h,17h,22h)
#######################################
def send_portfolio_report():
    pf = get_portfolio_state()
    txt = f"[Auto-Report]\nValeurTotale: {pf['total_value_usdt']} USDT\n"
    if pf["positions"]:
        txt += "Positions =>\n"
        for p in pf["positions"]:
            txt += f"- {p['symbol']}: ~{p['value_usdt']} USDT\n"
    if BOT_TOKEN and CHAT_ID:
        send_telegram_message(BOT_TOKEN, CHAT_ID, txt)

def schedule_reports():
    while True:
        now = datetime.datetime.now()
        # envoi auto à 7h,12h,17h,22h
        if now.minute == 0 and now.hour in [7,12,17,22]:
            send_portfolio_report()
            time.sleep(60)
        time.sleep(30)

#######################################
# 4) Lancement du Bot
#######################################
def run_telegram_bot():
    # Lancement du thread de reporting auto
    t = threading.Thread(target=schedule_reports, daemon=True)
    t.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("port", cmd_port))
    app.add_handler(CommandHandler("perf", cmd_perf))
    app.add_handler(CommandHandler("tokens", cmd_tokens))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("emergency", cmd_emergency))

    logging.info("[TELEGRAM] Bot en polling... Ctrl+C pour stop.")
    app.run_polling()


if __name__=="__main__":
    run_telegram_bot()
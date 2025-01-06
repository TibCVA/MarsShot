#!/usr/bin/env python3
# coding: utf-8

"""
Script Telegram pour le système MarsShot.
"""

import logging
import time
import datetime
import threading
import os
import yaml
import asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

# On importe les "vraies" fonctions de dashboard_data
from dashboard_data import (
    get_portfolio_state,
    list_tokens_tracked,
    get_performance_history,
    get_trades_history,
    emergency_out
)

from modules.utils import send_telegram_message

CONFIG_FILE = "config.yaml"
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

BOT_TOKEN = CONFIG["telegrams"].get("bot_token", None)
CHAT_ID   = CONFIG["telegrams"].get("chat_id", None)

if not BOT_TOKEN:
    raise ValueError("[ERREUR] bot_token manquant dans config.yaml => telegrams")

logging.basicConfig(level=logging.INFO)

#######################################
# 1) Fonctions "Commandes Telegram"
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
    # On peut afficher la perf "depuis get_performance_history()"
    pf = get_portfolio_state()
    perf = get_performance_history()
    msg = (
        f"Valeur Totale: {pf['total_value_usdt']} USDT\n"
        "Performance estimée:\n"
    )
    for horizon, vals in perf.items():
        msg += f"- {horizon}: {vals['usdt']} USDT / {vals['pct']}%\n"
    await update.message.reply_text(msg)

async def cmd_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tokens = list_tokens_tracked()
    if tokens:
        msg = "Tokens suivis:\n" + ", ".join(tokens)
    else:
        msg = "Aucun token suivi."
    await update.message.reply_text(msg)

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ex. /add FET => on ajoute FET dans config
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /add <symbol>")
        return
    sym = context.args[0].upper()

    with open(CONFIG_FILE, "r") as f:
        conf = yaml.safe_load(f)

    if sym not in conf["tokens_daily"]:
        conf["tokens_daily"].append(sym)
        with open(CONFIG_FILE, "w") as fw:
            yaml.dump(conf, fw)
        await update.message.reply_text(f"{sym} ajouté à la liste.")
    else:
        await update.message.reply_text(f"{sym} déjà présent.")

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ex. /remove FET => on retire FET
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /remove <symbol>")
        return
    sym = context.args[0].upper()

    with open(CONFIG_FILE, "r") as f:
        conf = yaml.safe_load(f)

    if sym in conf["tokens_daily"]:
        conf["tokens_daily"].remove(sym)
        with open(CONFIG_FILE, "w") as fw:
            yaml.dump(conf, fw)
        await update.message.reply_text(f"{sym} retiré de la liste.")
    else:
        await update.message.reply_text(f"{sym} pas trouvé ou échec.")

async def cmd_emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emergency_out()
    await update.message.reply_text(
        "Toutes les positions ont été vendues en USDT (emergency out)."
    )

#######################################
# 2) Rapports auto
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
# 3) Lancement du Bot Telegram en mode asyncio
#######################################
def run_telegram_bot():
    """
    Lance un thread pour schedule_reports,
    et crée un event loop asyncio dédié pour le polling Telegram.
    """
    # Thread de reporting auto (inchangé)
    t = threading.Thread(target=schedule_reports, daemon=True)
    t.start()

    # Coroutine principale pour le bot
    async def main_coroutine():
        app = ApplicationBuilder().token(BOT_TOKEN).build()

        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("port", cmd_port))
        app.add_handler(CommandHandler("perf", cmd_perf))
        app.add_handler(CommandHandler("tokens", cmd_tokens))
        app.add_handler(CommandHandler("add", cmd_add))
        app.add_handler(CommandHandler("remove", cmd_remove))
        app.add_handler(CommandHandler("emergency", cmd_emergency))

        logging.info("[TELEGRAM] Bot en polling (async).")
        await app.run_polling()

    # Création d'un event loop dédié dans ce thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main_coroutine())
    finally:
        loop.close()


if __name__ == "__main__":
    run_telegram_bot()

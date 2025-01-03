import logging
import requests

def send_telegram_message(bot_token, chat_id, text):
    if not bot_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": text})
    except Exception as e:
        logging.error(f"[Telegram Error] {e}")
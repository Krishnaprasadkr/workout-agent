import os
import requests

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

def send(text: str):
    """Send Telegram message."""

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
    }

    resp = requests.post(TELEGRAM_URL, json=payload, timeout=15)

    print("TELEGRAM RESPONSE:")
    print(resp.status_code)
    print(resp.text)

    resp.raise_for_status()

    print("Telegram message sent.")

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

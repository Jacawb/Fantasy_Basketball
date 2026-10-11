"""notify.py - post to Discord webhook."""
import os
import requests
from dotenv import load_dotenv

load_dotenv()
URL = os.getenv("DISCORD_WEBHOOK")


def post(msg):
    # Discord caps messages at 2000 chars, so send in chunks
    for i in range(0, len(msg), 1900):
        requests.post(URL, json={"content": msg[i:i + 1900]}, timeout=20)


if __name__ == "__main__":
    post("AI Slop bot online 🤖")
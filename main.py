# Telethon Auto-Reply Bot with Enhanced AI Fallback and Smart Pause

from telethon import TelegramClient, events
from telethon.errors import PeerIdInvalidError, FloodWaitError, ApiIdInvalidError
from flask import Flask
from collections import defaultdict
import requests
import asyncio
import threading
import logging
import os
import time
import re

# === CONFIG ===
api_id = int(os.getenv('API_ID', '22986717'))
api_hash = os.getenv('API_HASH', '1d1206253d640d42f488341e3b4f0a2f')
bot_token = os.getenv('BOT_TOKEN', '7275314987:AAHfuJwuR6-9L8Powjoc7UCLuT89KXpVi0I')
session_name = '/opt/render/project/src/bot_session'
groq_key_1 = os.getenv('GROQ_KEY_1', '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')
groq_key_2 = os.getenv('GROQ_KEY_2', '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')
bot_username = '@Telethonpy_bot'
reaction_emoji = '👍'
summary_interval = 120
pause_duration = 300  # 5 minutes

# === LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/opt/render/project/src/bot.log')
    ]
)
logger = logging.getLogger(__name__)

# === STATE ===
client = TelegramClient(session_name, api_id=api_id, api_hash=api_hash)
app = Flask(__name__)
conversation_history = defaultdict(list)
active_conversations = {}
pause_ai = set()
temp_pause_expiry = {}

fallback_models = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "gemma-7b-it",
    "llama2-70b-4096"
]

# === WEB SERVER ===
@app.route("/", methods=["GET", "HEAD"])
def ping():
    return "Bot is alive!", 200

port = int(os.getenv('PORT', 10000))
threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port), daemon=True).start()

# === AI RESPONSE ===
def generate_reply(messages):
    for key in [groq_key_1, groq_key_2]:
        for model in fallback_models:
            try:
                logger.info(f"🔁 Trying model: {model} with key: {key[:10]}")
                res = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": messages[-10:],
                        "temperature": 0.7,
                        "max_tokens": 300
                    },
                    timeout=15
                )
                logger.info(f"🌐 {res.status_code} - {res.text[:200]}")
                res.raise_for_status()
                j = res.json()
                if 'choices' in j and j['choices']:
                    return j['choices'][0]['message']['content']
            except Exception as e:
                logger.warning(f"❌ Failed model {model} with key {key[:10]}: {e}")
    return "🤖 Sorry, AI response failed. Please try again later."

# === TEMPORARY PAUSE MONITOR ===
async def monitor_temp_pauses():
    while True:
        now = time.time()
        expired = [uid for uid, expiry in temp_pause_expiry.items() if now >= expiry]
        for uid in expired:
            pause_ai.discard(uid)
            temp_pause_expiry.pop(uid, None)
            logger.info(f"⏯️ Auto-reply re-enabled for {uid}")
        await asyncio.sleep(10)

# === HANDLER ===
@client.on(events.NewMessage(incoming=True))
async def handle(event):
    sender = await event.get_sender()
    uid = sender.id
    text = event.raw_text.strip()
    logger.info(f"📥 {uid}: {text}")

    # Iris stop command
    if text.lower() == "iris stop":
        pause_ai.add(uid)
        temp_pause_expiry[uid] = time.time() + pause_duration
        await event.reply("⏸️ AI auto-replies paused for 5 minutes in this chat.")
        return

    # Check if paused
    if uid in pause_ai:
        logger.info(f"⛔ Auto-reply paused for {uid}")
        return

    # Auto-reply
    conversation_history[uid].append({"role": "user", "content": text})
    conversation_history[uid] = conversation_history[uid][-8:]

    prompt = [
        {"role": "system", "content": f"You are {bot_username}, a friendly Tamil-English Telegram assistant."},
        *conversation_history[uid]
    ]

    ai_reply = generate_reply(prompt)
    reply_msg = await event.reply(ai_reply)
    conversation_history[uid].append({"role": "assistant", "content": ai_reply})
    active_conversations[uid] = time.time()

    if re.search(r'\b(bye|thanks|ok|goodbye|later|gtg|ttyl)\b', text.lower()):
        try:
            await reply_msg.react(reaction_emoji)
        except Exception:
            pass

# === MAIN ===
async def main():
    try:
        await client.start(bot_token=bot_token)
        await asyncio.gather(
            client.run_until_disconnected(),
            monitor_temp_pauses()
        )
    except ApiIdInvalidError:
        logger.error("❌ Invalid API credentials.")
        raise
    except Exception as e:
        logger.error(f"❌ Startup error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())

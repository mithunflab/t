from telethon import TelegramClient, events
from telethon.errors import ApiIdInvalidError
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
api_id = 22986717
api_hash = '1d1206253d640d42f488341e3b4f0a2f'
bot_token = '7275314987:AAHfuJwuR6-9L8Powjoc7UCLuT89KXpVi0I'
session_name = 'session_mithun'
groq_key_1 = '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'
groq_key_2 = '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'
bot_username = '@Telethonpy_bot'
reaction_emoji = '✅'
pause_duration = 300  # 5 minutes

# === LOGGING ===
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger(__name__)

# === STATE ===
client = TelegramClient(session_name, api_id, api_hash)
bot = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)
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

# === WEB SERVER FOR KEEP-ALIVE ===
@app.route("/")
def home():
    return "Iris Bot is running", 200

threading.Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080))), daemon=True).start()

# === AI MESSAGE GENERATION ===
def generate_reply(messages):
    for key in [groq_key_1, groq_key_2]:
        for model in fallback_models:
            try:
                logger.info(f"🧠 Trying model: {model}")
                res = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": messages[-10:],
                        "temperature": 0.7,
                        "max_tokens": 300
                    },
                    timeout=15
                )
                res.raise_for_status()
                reply = res.json()["choices"][0]["message"]["content"]
                return reply
            except Exception as e:
                logger.warning(f"⚠️ Model {model} failed: {e}")
    return "Sorry, I couldn't respond right now. Please try again later."

# === AI SUMMARY GENERATION ===
def generate_summary(history):
    system_prompt = {
        "role": "system",
        "content": "You are Iris, an assistant that summarizes chat conversations between a user and the assistant. Summarize in less than 15 short lines."
    }
    prompt = [{"role": "user", "content": "\n".join(history)}]
    return generate_reply([system_prompt] + prompt)

# === TEMP PAUSE CLEANER ===
async def monitor_temp_pauses():
    while True:
        now = time.time()
        for uid in list(temp_pause_expiry.keys()):
            if now >= temp_pause_expiry[uid]:
                pause_ai.discard(uid)
                temp_pause_expiry.pop(uid, None)
                logger.info(f"✅ Auto-reply resumed for {uid}")
        await asyncio.sleep(5)

# === HANDLE INCOMING MESSAGE ===
@client.on(events.NewMessage(incoming=True))
async def handle_msg(event):
    sender = await event.get_sender()
    uid = sender.id
    text = event.raw_text.strip()
    logger.info(f"[{uid}] {text}")

    if sender.bot:
        return

    if text.lower() == "iris stop":
        pause_ai.add(uid)
        temp_pause_expiry[uid] = time.time() + pause_duration
        await event.reply("⏸️ Auto-reply paused for 5 minutes in this chat.")
        return

    if uid in pause_ai:
        logger.info(f"⛔ Paused for {uid}")
        return

    # Add message to history
    conversation_history[uid].append(f"User: {text}")
    chat = [
        {"role": "system", "content": "You are Iris, a smart and helpful assistant who replies casually, fluently, and clearly in English only. Never use Tamil. Keep responses friendly, human, and intelligent."}
    ] + [{"role": "user" if "User:" in msg else "assistant", "content": msg.split(": ", 1)[1]} for msg in conversation_history[uid][-8:]]

    reply = generate_reply(chat)
    await event.reply(reply)
    conversation_history[uid].append(f"Iris: {reply}")
    active_conversations[uid] = time.time()

    if re.search(r'\b(bye|thank you|goodbye|gtg|ok)\b', text.lower()):
        try:
            await event.respond(reaction_emoji)
        except:
            pass

# === CHECK FOR INACTIVE USERS AND SUMMARIZE ===
async def summarize_inactive_users():
    while True:
        now = time.time()
        for uid in list(active_conversations.keys()):
            if now - active_conversations[uid] > 180:  # 3 min silence
                summary = generate_summary(conversation_history[uid])
                try:
                    await bot.send_message(bot_username, f"📄 Summary of chat with [{uid}]:\n\n{summary}")
                except Exception as e:
                    logger.warning(f"❌ Couldn't send summary to bot: {e}")
                del active_conversations[uid]
                conversation_history[uid].clear()
        await asyncio.sleep(30)

# === MAIN ===
async def main():
    try:
        await client.start()
        await bot.start()
        await asyncio.gather(
            client.run_until_disconnected(),
            monitor_temp_pauses(),
            summarize_inactive_users()
        )
    except ApiIdInvalidError:
        logger.error("❌ Invalid API credentials.")
    except Exception as e:
        logger.error(f"💥 Startup Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())


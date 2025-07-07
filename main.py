from telethon import TelegramClient, events
import requests
import asyncio
import threading
from flask import Flask
from collections import defaultdict
import re
import time

# === CONFIG ===
api_id = 22986717
api_hash = '1d1206253d640d42f488341e3b4f0a2f'
groq_api_key = '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'
session_name = 'session_mithun'
bot_usernames = ['Telethonpy_bot', 'Lunaclaude_bot']

# === STATE ===
client = TelegramClient(session_name, api_id, api_hash)
conversation_history = defaultdict(list)
pause_ai = set()
force_ai = set()
manual_chatting_with = None
active_conversations = {}  # user_id -> last_seen_time

# === MODELS ===
groq_models = [
    "llama3-70b-8192",
    "llama3-8b-8192",
    "gemma-7b-it",
    "llama2-70b-4096"
]

# === FLASK UPTIME SERVER ===
app = Flask(__name__)
@app.route("/", methods=["GET", "HEAD"])
def ping(): return "Bot is alive!", 200
threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

# === AI REPLY ===
def generate_ai_reply(messages):
    for model in groq_models:
        try:
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": messages[-10:],
                    "temperature": 0.7
                }
            )
            if res.ok and 'choices' in res.json():
                return res.json()['choices'][0]['message']['content']
        except Exception as e:
            print(f"⚠️ Model error: {model} – {e}")
    return "🤖 Sorry, AI failed."

# === INCOMING MESSAGE HANDLER ===
@client.on(events.NewMessage(incoming=True))
async def handle(event):
    global manual_chatting_with
    sender = await event.get_sender()
    user_id = sender.id
    message = event.raw_text.strip()
    username = (sender.username or "").lower()

    # Block AI replies to these bots
    if username in [u.lower() for u in bot_usernames]:
        if username == "telethonpy_bot":
            # Start new chat by command: "msg @user" or "message +91..."
            match = re.search(r"(msg|message)\s+(@[\w\d_]+|\+?\d{10,15}|him|her)", message, re.I)
            if match:
                target = match.group(2)
                try:
                    if target.lower() in ['him', 'her'] and manual_chatting_with:
                        await client.send_message(manual_chatting_with, "👋 Hey! I'm Mithun, let's talk.")
                        active_conversations[manual_chatting_with] = time.time()
                        await event.reply("✅ Chat started with previous person.")
                    else:
                        entity = await client.get_entity(target)
                        await client.send_message(entity, "👋 Hey! I'm Mithun, let's talk.")
                        active_conversations[entity.id] = time.time()
                        await event.reply(f"✅ Started chat with {target}.")
                except Exception as e:
                    await event.reply(f"❌ Error: {e}")
        return  # Never reply to Telethonpy_bot or Lunaclaude_bot

    # Pause & force control
    if message == "/":
        pause_ai.add(user_id)
        await event.reply("⏸️ AI paused.")
        return
    elif message == "\\":
        force_ai.add(user_id)
        await event.reply("✅ AI forced ON.")
        return

    if user_id in pause_ai and user_id not in force_ai:
        return

    # Manual typing detection
    me = await client.get_me()
    if event.is_private:
        async for msg in client.iter_messages(event.chat_id, limit=1, from_user=me):
            if msg.date.timestamp() > event.message.date.timestamp():
                manual_chatting_with = user_id
                return

    if manual_chatting_with == user_id and user_id not in force_ai:
        return

    # AI conversation
    print(f"📨 {sender.first_name}: {message}")
    conversation_history[user_id].append({"role": "user", "content": message})
    conversation_history[user_id] = conversation_history[user_id][-6:]

    ai_prompt = [{"role": "system", "content": "You are Mithun, chatting with friends/family in Tamil-English mix."}]
    ai_prompt += conversation_history[user_id]

    reply = generate_ai_reply(ai_prompt)
    await event.reply(reply)
    conversation_history[user_id].append({"role": "assistant", "content": reply})
    active_conversations[user_id] = time.time()

# === MONITOR CONVERSATION AND SUMMARIZE ===
async def monitor_summary():
    while True:
        now = time.time()
        for user_id, last_seen in list(active_conversations.items()):
            if now - last_seen > 120:
                if user_id in conversation_history:
                    summary_prompt = [{"role": "system", "content": "Summarize the following chat in 2 lines."}]
                    summary_prompt += conversation_history[user_id][-6:]
                    summary = generate_ai_reply(summary_prompt)
                    try:
                        await client.send_message("Telethonpy_bot", f"📄 Summary of chat with {user_id}:\n\n{summary}")
                    except Exception as e:
                        print(f"❌ Could not send summary: {e}")
                del active_conversations[user_id]
        await asyncio.sleep(30)

# === START EVERYTHING ===
async def main():
    await client.start()
    print("🤖 Telegram AI bot running...")
    await asyncio.gather(client.run_until_disconnected(), monitor_summary())

asyncio.run(main())



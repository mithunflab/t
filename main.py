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
bot_username = 'Telethonpy_bot'
ignored_usernames = {'Telethonpy_bot', 'Lunaclaude_bot'}

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

# === WEB SERVER ===
app = Flask(__name__)

@app.route("/", methods=["GET", "HEAD"])
def ping():
    return "Bot is alive!", 200

def start_web():
    app.run(host="0.0.0.0", port=10000)

threading.Thread(target=start_web, daemon=True).start()

# === GROQ AI ===
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
            if res.status_code == 200 and 'choices' in res.json():
                return res.json()['choices'][0]['message']['content']
        except Exception as e:
            print(f"Model {model} error: {e}")
    return "🤖 Sorry, something went wrong."

# === AI HANDLER ===
@client.on(events.NewMessage(incoming=True))
async def handle(event):
    global manual_chatting_with
    sender = await event.get_sender()
    user_id = sender.id
    message = event.raw_text.strip()

    # Ignore if from excluded bots
    if sender.username in ignored_usernames:
        return

    # Handle commands from your bot
    if sender.username == bot_username:
        if re.search(r'(?i)\b(msg|message|start chat|talk to|tell)\b', message):
            target_match = re.findall(r'@\w+|\+?\d{10,15}|him|her', message)
            message_content = re.sub(r'(?i)(msg|message|start chat|talk to|tell)\s+(@\w+|\+?\d{10,15}|him|her)', '', message)
            if target_match:
                target_ref = target_match[0]
                try:
                    if target_ref.lower() in ['him', 'her'] and manual_chatting_with:
                        await client.send_message(manual_chatting_with, message_content.strip() or "👋 Hey! I'm Mithun, let's talk.")
                        active_conversations[manual_chatting_with] = time.time()
                        await event.reply("✅ Started chat with them.")
                    else:
                        entity = await client.get_entity(target_ref)
                        await client.send_message(entity, message_content.strip() or "👋 Hey! I'm Mithun, let's talk.")
                        active_conversations[entity.id] = time.time()
                        await event.reply(f"✅ Started chat with {target_ref}.")
                except Exception as e:
                    await event.reply(f"❌ Could not start chat: {e}")
        return

    # Handle pause/force
    if message == "/":
        pause_ai.add(user_id)
        await event.reply("🤖 Paused AI for this user.")
        return
    elif message == "\\":
        force_ai.add(user_id)
        await event.reply("🤖 Forced AI ON for this user.")
        return

    if user_id in pause_ai and user_id not in force_ai:
        return

    # Manual reply detection
    me = await client.get_me()
    if event.is_private:
        async for msg in client.iter_messages(event.chat_id, limit=1, from_user=me):
            if msg.date.timestamp() > event.message.date.timestamp():
                manual_chatting_with = user_id
                return

    if manual_chatting_with == user_id and user_id not in force_ai:
        return

    # Generate AI reply
    conversation_history[user_id].append({"role": "user", "content": message})
    conversation_history[user_id] = conversation_history[user_id][-6:]

    messages = [
        {"role": "system", "content": "You are Mithun. You are chatting casually in Tamil-English mix. Be friendly and real."}
    ] + conversation_history[user_id]

    ai_reply = generate_ai_reply(messages)
    await event.reply(ai_reply)
    conversation_history[user_id].append({"role": "assistant", "content": ai_reply})

    active_conversations[user_id] = time.time()

# === CONVERSATION MONITOR ===
async def monitor_summary():
    while True:
        now = time.time()
        expired = []
        for user_id, last_seen in active_conversations.items():
            if now - last_seen > 120:
                if user_id in conversation_history:
                    history = conversation_history[user_id][-6:]
                    summary_prompt = [
                        {"role": "system", "content": "Summarize this conversation briefly as Mithun chatted with the person and summarize what they said."}
                    ] + history
                    summary = generate_ai_reply(summary_prompt)
                    await client.send_message(bot_username, f"📄 Summary for chat with {user_id}:\n{summary}")
                expired.append(user_id)
        for uid in expired:
            del active_conversations[uid]
        await asyncio.sleep(30)

# === RUN ===
async def main():
    await client.start()
    print("🤖 Bot is running!")
    await asyncio.gather(
        client.run_until_disconnected(),
        monitor_summary()
    )

asyncio.run(main())



from telethon import TelegramClient, events
import requests
import asyncio
import threading
from flask import Flask
from collections import defaultdict
import re
import time
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact

# === CONFIG ===
api_id = 22986717
api_hash = '1d1206253d640d42f488341e3b4f0a2f'
groq_api_key = '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'
session_name = 'session_mithun'
bot_username = 'Telethonpy_bot'
no_ai_usernames = ['Telethonpy_bot', 'Lunaclaude_bot']

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

# === UPTIME SERVER ===
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
    username = sender.username or ""
    message = event.raw_text.strip()

    # Ignore AI reply for specific bot usernames
    if username in no_ai_usernames:
        # Special bot handler for @Telethonpy_bot
        if username == bot_username:
            match = re.search(r"(msg|message)\s+(@[\w\d_]+|\+?\d{10,15}|him|her)", message, re.I)
            if match:
                target = match.group(2).strip()
                try:
                    if target.lower() in ['him', 'her'] and manual_chatting_with:
                        await client.send_message(manual_chatting_with, "\U0001F44B Hey! I'm Mithun, let's talk.")
                        active_conversations[manual_chatting_with] = time.time()
                        await event.reply("\u2705 Chat started with previous person.")
                    else:
                        if target.startswith("+") or target.isdigit():
                            result = await client(ImportContactsRequest([
                                InputPhoneContact(client_id=0, phone=target, first_name="MithunContact", last_name="")
                            ]))
                            user = result.users[0] if result.users else None
                            if user:
                                await client.send_message(user.id, "\U0001F44B Hey! I'm Mithun, let's talk.")
                                active_conversations[user.id] = time.time()
                                await event.reply(f"\u2705 Started chat with {target}")
                            else:
                                await event.reply("\u274C Couldn't find or add contact.")
                        else:
                            entity = await client.get_entity(target)
                            await client.send_message(entity, "\U0001F44B Hey! I'm Mithun, let's talk.")
                            active_conversations[entity.id] = time.time()
                            await event.reply(f"\u2705 Started chat with {target}.")
                except Exception as e:
                    await event.reply(f"\u274C Error: {e}")
        return

    # Handle pause/force
    if message == "/":
        pause_ai.add(user_id)
        await event.reply("\U0001F916 Paused AI for this user.")
        return
    elif message == "\\":
        force_ai.add(user_id)
        await event.reply("\U0001F916 Forced AI ON for this user.")
        return

    # If paused and not forced
    if user_id in pause_ai and user_id not in force_ai:
        return

    # Check if you're manually replying
    me = await client.get_me()
    if event.is_private:
        async for msg in client.iter_messages(event.chat_id, limit=1, from_user=me):
            if msg.date.timestamp() > event.message.date.timestamp():
                manual_chatting_with = user_id
                return

    # If you're chatting manually with this person
    if manual_chatting_with == user_id and user_id not in force_ai:
        return

    # Store conversation
    conversation_history[user_id].append({"role": "user", "content": message})
    conversation_history[user_id] = conversation_history[user_id][-6:]

    messages = [
        {
            "role": "system",
            "content": (
                "You are Mithun. You are chatting casually in English politely mix. Be friendly and real."
            )
        }
    ] + conversation_history[user_id]

    ai_reply = generate_ai_reply(messages)
    await event.reply(ai_reply)
    conversation_history[user_id].append({"role": "assistant", "content": ai_reply})

    # Update last activity
    active_conversations[user_id] = time.time()

# === CONVO SUMMARY CHECKER ===
async def monitor_summary():
    while True:
        now = time.time()
        to_remove = []
        for user_id, last_seen in active_conversations.items():
            if now - last_seen > 120:
                if user_id in conversation_history:
                    history = conversation_history[user_id][-6:]
                    summary_prompt = [{
                        "role": "system",
                        "content": "Summarize this chat in 5 meaningful lines. Avoid using just emojis or vague words. Mention context and tone."
                    }] + history
                    summary = generate_ai_reply(summary_prompt)
                    await client.send_message(bot_username, f"\U0001F4C4 Summary for chat with {user_id}:\n\n{summary}")
                to_remove.append(user_id)
        for uid in to_remove:
            del active_conversations[uid]
        await asyncio.sleep(30)

# === RUN ===
async def main():
    await client.start()
    print("\U0001F916 Bot is running!")
    await asyncio.gather(
        client.run_until_disconnected(),
        monitor_summary()
    )

asyncio.run(main())




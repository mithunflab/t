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
api_hash = '2d1206253d640d42f488341e3b4f0a2f'
session_name = 'session_mithun'
groq_key = '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'
scout_model = 'meta-llama/llama-4-scout-17b-16e-instruct'
bot_username = 'Telethonpy_bot'
ignored_usernames = {'telethonpy_bot', 'lunaclaude_bot'}

# === STATE ===
client = TelegramClient(session_name, api_id, api_hash)
app = Flask(__name__)
conversation_history = defaultdict(list)
active_conversations = {}  # user_id -> last_activity
manual_chatting_with = None
pause_ai = set()
force_ai = set()

fallback_models = [
    scout_model,
    "llama3-70b-8192",
    "llama3-8b-8192",
    "gemma-7b-it",
    "llama2-70b-4096"
]

# === WEB SERVER FOR UPTIME ===
@app.route("/", methods=["GET", "HEAD"])
def ping():
    return "Bot is alive!", 200

threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

# === AI CALLER ===
def generate_reply(messages, use_scout=True):
    models = [scout_model] if use_scout else fallback_models
    for model in models:
        try:
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": messages[-10:],
                    "temperature": 0.7
                }
            )
            j = res.json()
            if res.status_code == 200 and 'choices' in j:
                return j['choices'][0]['message']['content']
        except Exception as e:
            print(f"❌ Model {model} failed: {e}")
    return "🤖 Sorry, failed to generate a reply."

# === AI INSTRUCTION HANDLER ===
@client.on(events.NewMessage(incoming=True))
async def handle(event):
    global manual_chatting_with

    sender = await event.get_sender()
    uid = sender.id
    uname = (sender.username or "").lower()
    text = event.raw_text.strip()

    # === Skip auto-replies for bot usernames
    if uname in ignored_usernames:
        return

    # === Handle command from your bot (e.g. “msg @user tell him this”)
    if uname == bot_username.lower():
        if re.search(r'\b(msg|message|text|talk to|tell)\b', text, re.I):
            # Extract target + message
            match = re.search(r'(?i)(@[\w\d_]+|\+?\d{10,15}|him|her)', text)
            if not match:
                await event.reply("❗ Couldn't find a target user.")
                return
            target = match.group(1).lstrip('@')
            msg_text = re.sub(r'(?i)(msg|message|text|talk to|tell)\s+(@[\w\d_]+|\+?\d{10,15}|him|her)', '', text).strip()
            try:
                if target.lower() in ['him', 'her'] and manual_chatting_with:
                    entity_id = manual_chatting_with
                else:
                    entity = await client.get_entity(target)
                    entity_id = entity.id
                ai_msg = generate_reply([{"role": "user", "content": msg_text}], use_scout=True)
                await client.send_message(entity_id, ai_msg)
                active_conversations[entity_id] = time.time()
                conversation_history[entity_id].append({"role": "user", "content": msg_text})
                conversation_history[entity_id].append({"role": "assistant", "content": ai_msg})
                await event.reply(f"✅ Sent message to {target}.")
            except Exception as e:
                await event.reply(f"❌ Failed: {e}")
        return

    # === Pause / Force AI
    if text == "/":
        pause_ai.add(uid)
        await event.reply("⏸️ Paused AI for this chat.")
        return
    elif text == "\\":
        force_ai.add(uid)
        await event.reply("✅ Forced AI replies ON.")
        return

    if uid in pause_ai and uid not in force_ai:
        return

    # === Manual reply tracking
    me = await client.get_me()
    if event.is_private:
        async for m in client.iter_messages(event.chat_id, limit=1, from_user=me):
            if m.date.timestamp() > event.message.date.timestamp():
                manual_chatting_with = uid
                return
    if manual_chatting_with == uid and uid not in force_ai:
        return

    # === Auto-reply for normal chats
    conversation_history[uid].append({"role": "user", "content": text})
    conversation_history[uid] = conversation_history[uid][-6:]

    prompt = [{"role": "system", "content": "You are Mithun chatting warmly in Tamil-English."}] + conversation_history[uid]
    ai_reply = generate_reply(prompt, use_scout=False)
    await event.reply(ai_reply)
    conversation_history[uid].append({"role": "assistant", "content": ai_reply})
    active_conversations[uid] = time.time()

# === AUTO SUMMARY GENERATOR ===
async def monitor_summaries():
    while True:
        now = time.time()
        done = []
        for uid, last_seen in active_conversations.items():
            if now - last_seen > 120:
                hist = conversation_history.get(uid, [])[-8:]
                if hist:
                    prompt = [{"role": "system", "content": "Summarize this conversation in 10 lines including what Mithun and the user said."}] + hist
                    summary = generate_reply(prompt, use_scout=True)
                    await client.send_message(bot_username, f"📄 10-line Summary for chat with {uid}:\n\n{summary}")
                done.append(uid)
        for uid in done:
            active_conversations.pop(uid, None)
        await asyncio.sleep(30)

# === MAIN ===
async def main():
    await client.start()
    print("🤖 Telegram AI bot is running!")
    await asyncio.gather(
        client.run_until_disconnected(),
        monitor_summaries()
    )

asyncio.run(main())



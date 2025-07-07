from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityMention, MessageEntityTextUrl
import requests
import asyncio
import threading
from flask import Flask
from collections import defaultdict
import re
import time
import uuid

# === CONFIG ===
api_id = 22986717
api_hash = '2d1206253d640d42f488341e3b4f0a2f'
session_name = 'session_mithun'
groq_key_auto_reply = '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'  # For auto-replies
groq_key_bot = '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'  # For bot commands
scout_model = 'meta-llama/llama-4-scout-17b-16e-instruct'
bot_username = '@Telethonpy_bot'
ignored_usernames = {'Telethonpy_bot', 'Lunaclaude_bot'}
reaction_emoji = '👍'  # Emoji to react with when conversation ends
summary_interval = 120  # Seconds of inactivity before considering conversation ended

# === STATE ===
client = TelegramClient(session_name, api_id, api_hash)
app = Flask(__name__)
conversation_history = defaultdict(list)  # Separate history per user
active_conversations = {}  # user_id -> last_activity timestamp
manual_chatting_with = None
pause_ai = set()  # Chats where AI is paused
force_ai = set()  # Chats where AI is forced on

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
def generate_reply(messages, use_scout=True, use_bot_api=False):
    groq_key = groq_key_bot if use_bot_api else groq_key_auto_reply
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
            res.raise_for_status()
            j = res.json()
            if 'choices' in j:
                return j['choices'][0]['message']['content']
        except Exception as e:
            print(f"❌ Model {model} failed: {e}")
    return "🤖 Sorry, I'm having trouble responding right now. Please try again later."

# === MESSAGE HANDLER ===
@client.on(events.NewMessage(incoming=True))
async def handle(event):
    global manual_chatting_with

    sender = await event.get_sender()
    uid = sender.id
    uname = (sender.username or "").lower()
    text = event.raw_text.strip()

    # Skip auto-replies for ignored usernames
    if uname in ignored_usernames:
        return

    # Handle bot commands (e.g., "start a chat with @lunaclaude about today's party")
    if uname == bot_username.lower():
        if re.search(r'\b(start a chat|msg|message|text|talk to|tell)\b', text, re.I):
            # Extract target and message
            match = re.search(r'(?i)(@[\w\d_]+|\+?\d{10,15}|him|her)', text)
            if not match:
                await event.reply("❗ Please specify a valid user (e.g., @username or phone number).")
                return
            target = match.group(1).lstrip('@')
            msg_text = re.sub(r'(?i)(start a chat|msg|message|text|talk to|tell)\s+(@[\w\d_]+|\+?\d{10,15}|him|her)', '', text).strip()
            try:
                if target.lower() in ['him', 'her'] and manual_chatting_with:
                    entity_id = manual_chatting_with
                    target_display = target
                else:
                    entity = await client.get_entity(target)
                    entity_id = entity.id
                    target_display = f"@{entity.username}" if entity.username else target
                # Generate polite AI message using bot API key
                prompt = [
                    {"role": "system", "content": "You are a polite assistant named Mithun, initiating a conversation in a friendly and warm tone. Respond in Tamil-English if appropriate, based on the user's message."},
                    {"role": "user", "content": msg_text}
                ]
                ai_msg = generate_reply(prompt, use_scout=True, use_bot_api=True)
                await client.send_message(entity_id, ai_msg)
                active_conversations[entity_id] = time.time()
                conversation_history[entity_id].append({"role": "user", "content": msg_text})
                conversation_history[entity_id].append({"role": "assistant", "content": ai_msg})
                await event.reply(f"✅ Started chat with {targetස

ystem: target_display}.")
            except Exception as e:
                await event.reply(f"❌ Failed to send message: {e}")
        return

    # Pause/Force AI commands
    if text == "/":
        pause_ai.add(uid)
        await event.reply("⏸️ AI auto-replies paused for this chat.")
        return
    elif text == "\\":
        force_ai.add(uid)
        await event.reply("✅ AI auto-replies forced ON for this chat.")
        return

    # Skip auto-reply if paused and not forced
    if uid in pause_ai and uid not in force_ai:
        return

    # Check for manual reply to set manual_chatting_with
    me = await client.get_me()
    if event.is_private:
        async for m in client.iter_messages(event.chat_id, limit=1, from_user=me):
            if m.date.timestamp() > event.message.date.timestamp():
                manual_chatting_with = uid
                return
    if manual_chatting_with == uid and uid not in force_ai:
        return

    # Auto-reply with polite response
    conversation_history[uid].append({"role": "user", "content": text})
    conversation_history[uid] = conversation_history[uid][-6:]  # Keep last 6 messages for context

    prompt = [
        {"role": "system", "content": "You are Mithun, a polite and friendly assistant. Respond warmly in Tamil-English if appropriate, and always maintain a courteous tone. End the conversation with a polite closing if it seems to be over."},
        *conversation_history[uid]
    ]
    ai_reply = generate_reply(prompt, use_scout=False, use_bot_api=False)
    reply_msg = await event.reply(ai_reply)
    conversation_history[uid].append({"role": "assistant", "content": ai_reply})
    active_conversations[uid] = time.time()

    # Check if conversation seems over (e.g., user says "bye", "thanks", etc.)
    if re.search(r'\b(bye|thanks|ok|goodbye|later|gtg|ttyl)\b', text.lower()):
        await reply_msg.react(reaction_emoji)

# === AUTO SUMMARY AND REACTION ===
async def monitor_summaries():
    while True:
        now = time.time()
        done = []
        for uid, last_seen in active_conversations.items():
            if now - last_seen > summary_interval:
                hist = conversation_history.get(uid, [])[-8:]
                if hist:
                    prompt = [
                        {"role": "system", "content": "Summarize this conversation in 10 lines, including what Mithun and the user said. Use a polite and professional tone."},
                        *hist
                    ]
                    summary = generate_reply(prompt, use_scout=True, use_bot_api=True)
                    user = await client.get_entity(uid)
                    username = f"@{user.username}" if user.username else user.id
                    await client.send_message(bot_username, f"📄 Summary for chat with {username}:\n\n{summary}")
                    # React to last user message if not already reacted
                    async for msg in client.iter_messages(uid, limit=1, from_user=user):
                        if not msg.reactions:
                            await msg.react(reaction_emoji)
                done.append(uid)
        for uid in done:
            active_conversations.pop(uid, None)
            conversation_history[uid] = []  # Clear history after summary
        await asyncio.sleep(30)

# === MAIN ===
async def main():
    await client.start()
    print("�belethon AI bot is running!")
    await asyncio.gather(
        client.run_until_disconnected(),
        monitor_summaries()
    )

if __name__ == "__main__":
    asyncio.run(main())



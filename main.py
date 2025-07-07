from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityMention, MessageEntityTextUrl
import requests
import asyncio
import threading
from flask import Flask
from collections import defaultdict
import re
import time
import os
import logging

# === CONFIG ===
api_id = int(os.getenv('API_ID', 22986717))
api_hash = os.getenv('API_HASH', '2d1206253d640d42f488341e3b4f0a2f')
session_name = '/opt/render/project/src/session_mithun'  # Adjusted for Render's filesystem
groq_key_auto_reply = os.getenv('GROQ_KEY_AUTO_REPLY', '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')
groq_key_bot = os.getenv('GROQ_KEY_BOT', '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')
scout_model = 'meta-llama/llama-4-scout-17b-16e-instruct'
bot_username = '@Telethonpy_bot'
ignored_usernames = {'telethonpy_bot', 'lunaclaude_bot'}
reaction_emoji = '👍'
summary_interval = 120

# === LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')  # Log to a file for Render
    ]
)
logger = logging.getLogger(__name__)

# === STATE ===
client = TelegramClient(session_name, api_id, api_hash)
app = Flask(__name__)
conversation_history = defaultdict(list)
active_conversations = {}
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

port = int(os.getenv('PORT', 10000))
threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port), daemon=True).start()

# === AI CALLER ===
def generate_reply(messages, use_scout=True, use_bot_api=False):
    groq_key = groq_key_bot if use_bot_api else groq_key_auto_reply
    models = [scout_model] if use_scout else fallback_models
    for model in models:
        try:
            logger.info(f"Calling Groq API with model {model}, bot_api={use_bot_api}")
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
                },
                timeout=10
            )
            res.raise_for_status()
            j = res.json()
            if 'choices' in j:
                logger.info("Groq API call successful")
                return j['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"Model {model} failed: {e}")
    logger.error("All models failed to generate a reply")
    return "🤖 Sorry, I'm having trouble responding right now. Please try again later."

# === MESSAGE HANDLER ===
@client.on(events.NewMessage(incoming=True))
async def handle(event):
    global manual_chatting_with

    sender = await event.get_sender()
    uid = sender.id
    uname = (sender.username or "").lower()
    text = event.raw_text.strip()
    logger.info(f"Received message from {uname or uid}: {text}")

    # Skip auto-replies for ignored usernames
    if uname in ignored_usernames:
        logger.info(f"Ignoring message from {uname}")
        return

    # Handle bot commands
    if uname == bot_username.lower():
        if re.search(r'\b(start a chat|msg|message|text|talk to|tell)\b', text, re.I):
            logger.info(f"Processing bot command: {text}")
            match = re.search(r'(?i)(@[\w\d_]+|\+?\d{10,15}|him|her)', text)
            if not match:
                logger.warning("No valid target user found in command")
                await event.reply("❗ Please specify a valid user (e.g., @username or phone number).")
                return
            target = match.group(1).lstrip('@')
            msg_text = re.sub(r'(?i)(start a chat|msg|message|text|talk to|tell)\s+(@[\w\d_]+|\+?\d{10,15}|him|her)', '', text).strip()
            logger.info(f"Target: {target}, Message: {msg_text}")
            try:
                if target.lower() in ['him', 'her'] and manual_chatting_with:
                    entity_id = manual_chatting_with
                    target_display = target
                else:
                    entity = await client.get_entity(target)
                    entity_id = entity.id
                    target_display = f"@{entity.username}" if entity.username else target
                # Generate context-specific message
                prompt = [
                    {"role": "system", "content": "You are Mithun, a polite assistant. Craft a friendly and warm invitation message in Tamil-English if appropriate, based on the user's request. Ensure the message is relevant to the topic provided (e.g., inviting to a party)."},
                    {"role": "user", "content": f"Invite {target} to a party with this message: {msg_text}"}
                ]
                ai_msg = generate_reply(prompt, use_scout=True, use_bot_api=True)
                logger.info(f"Sending AI-generated message to {target_display}: {ai_msg}")
                await client.send_message(entity_id, ai_msg)
                active_conversations[entity_id] = time.time()
                conversation_history[entity_id].append({"role": "user", "content": msg_text})
                conversation_history[entity_id].append({"role": "assistant", "content": ai_msg})
                await event.reply(f"✅ Started chat with {target_display}.")
            except Exception as e:
                logger.error(f"Failed to send message to {target}: {e}")
                await event.reply(f"❌ Failed to send message: {e}")
        return

    # Pause/Force AI commands
    if text == "/":
        pause_ai.add(uid)
        logger.info(f"Paused AI for user {uid}")
        await event.reply("⏸️ AI auto-replies paused for this chat.")
        return
    elif text == "\\":
        force_ai.add(uid)
        logger.info(f"Forced AI for user {uid}")
        await event.reply("✅ AI auto-replies forced ON for this chat.")
        return

    # Skip auto-reply if paused and not forced
    if uid in pause_ai and uid not in force_ai:
        logger.info(f"Skipping auto-reply for paused chat {uid}")
        return

    # Check for manual reply
    me = await client.get_me()
    if event.is_private:
        async for m in client.iter_messages(event.chat_id, limit=1, from_user=me):
            if m.date.timestamp() > event.message.date.timestamp():
                manual_chatting_with = uid
                logger.info(f"Manual reply detected, setting manual_chatting_with to {uid}")
                return
    if manual_chatting_with == uid and uid not in force_ai:
        logger.info(f"Skipping auto-reply due to manual chat with {uid}")
        return

    # Auto-reply
    conversation_history[uid].append({"role": "user", "content": text})
    conversation_history[uid] = conversation_history[uid][-6:]
    prompt = [
        {"role": "system", "content": "You are Mithun, a polite and friendly assistant. Respond warmly in Tamil-English if appropriate, and always maintain a courteous tone. End the conversation with a polite closing if it seems to be over."},
        *conversation_history[uid]
    ]
    ai_reply = generate_reply(prompt, use_scout=False, use_bot_api=False)
    logger.info(f"Auto-replying to {uid}: {ai_reply}")
    reply_msg = await event.reply(ai_reply)
    conversation_history[uid].append({"role": "assistant", "content": ai_reply})
    active_conversations[uid] = time.time()

    # Check if conversation seems over
    if re.search(r'\b(bye|thanks|ok|goodbye|later|gtg|ttyl)\b', text.lower()):
        logger.info(f"Conversation with {uid} seems over, reacting with {reaction_emoji}")
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
                        {"role": "system", "content": "Summarize this conversation in up to 10 lines, including what Mithun and the user said. Use a polite and professional tone."},
                        *hist
                    ]
                    summary = generate_reply(prompt, use_scout=True, use_bot_api=True)
                    try:
                        user = await client.get_entity(uid)
                        username = f"@{user.username}" if user.username else user.id
                        logger.info(f"Sending summary for {username}")
                        await client.send_message(bot_username, f"📄 Summary for chat with {username}:\n\n{summary}")
                        async for msg in client.iter_messages(uid, limit=1, from_user=user):
                            if not msg.reactions:
                                logger.info(f"Reacting to last message from {uid} with {reaction_emoji}")
                                await msg.react(reaction_emoji)
                    except Exception as e:
                        logger.error(f"Failed to send summary for {uid}: {e}")
                done.append(uid)
        for uid in done:
            active_conversations.pop(uid, None)
            conversation_history[uid] = []
        await asyncio.sleep(30)

# === MAIN ===
async def main():
    try:
        await client.start()
        me = await client.get_me()
        logger.info(f"Bot started, logged in as {me.username or me.id}")
        await asyncio.gather(
            client.run_until_disconnected(),
            monitor_summaries()
        )
    except Exception as e:
        logger.error(f"Bot failed to start: {e}")

if __name__ == "__main__":
    asyncio.run(main())

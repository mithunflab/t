from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityMention, MessageEntityTextUrl
from telethon.errors import PeerIdInvalidError, FloodWaitError, ApiIdInvalidError
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
api_id = int(os.getenv('API_ID', '22986717'))
api_hash = os.getenv('API_HASH', '1d1206253d640d42f488341e3b4f0a2f')
bot_token = os.getenv('BOT_TOKEN', '7275314987:AAHfuJwuR6-9L8Powjoc7UCLuT89KXpVi0I')
session_name = '/opt/render/project/src/bot_session'
groq_key_auto_reply = os.getenv('GROQ_KEY_AUTO_REPLY', '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')
groq_key_bot = os.getenv('GROQ_KEY_BOT', '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')
scout_model = 'meta-llama/llama-4-scout-17b-16e-instruct'
bot_username = '@Telethonpy_bot'
ignored_usernames = {'telethonpy_bot', 'lunaclaude_bot'}
reaction_emoji = '👍'
summary_interval = 120
owner_id = int(os.getenv('OWNER_ID', '123456789'))
pause_duration = 300

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
force_ai = set()
temp_pause_expiry = {}

fallback_models = [
    scout_model,
    "llama3-70b-8192",
    "llama3-8b-8192",
    "gemma-7b-it",
    "llama2-70b-4096"
]

# === WEB SERVER FOR RENDER ===
@app.route("/", methods=["GET", "HEAD"])
def ping():
    return "Bot is alive!", 200

port = int(os.getenv('PORT', 10000))
threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port), daemon=True).start()

# === GROQ CALLER ===
def generate_reply(messages, use_scout=True, use_bot_api=False):
    groq_key = groq_key_bot if use_bot_api else groq_key_auto_reply
    models = [scout_model] if use_scout else fallback_models

    logger.info(f"🧠 Generating AI reply | UseScout: {use_scout} | UseBotKey: {use_bot_api}")
    logger.info(f"🤖 Trying models in order: {models}")

    for model in models:
        try:
            logger.info(f"➡️ Calling Groq API with model: {model}, key: {groq_key[:10]}...")
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
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
            logger.info(f"📡 Groq response: {response.status_code} - {response.text[:300]}")
            response.raise_for_status()
            data = response.json()
            if 'choices' in data and data['choices']:
                return data['choices'][0]['message']['content']
        except requests.exceptions.RequestException as req_err:
            logger.error(f"❌ Request error for model {model}: {req_err}")
        except Exception as e:
            logger.error(f"❌ Unexpected error with model {model}: {e}")

    logger.error("🚨 All Groq models failed to generate a reply")
    return "🤖 Sorry, I'm having trouble responding right now. Please try again later."

# === MONITOR TEMPORARY PAUSES ===
async def monitor_temp_pauses():
    while True:
        now = time.time()
        expired = [uid for uid, expiry in temp_pause_expiry.items() if now >= expiry]
        for uid in expired:
            pause_ai.discard(uid)
            temp_pause_expiry.pop(uid, None)
            logger.info(f"⏯️ Unpaused AI for user {uid}")
        await asyncio.sleep(10)

# === MESSAGE HANDLER ===
@client.on(events.NewMessage(incoming=True))
async def handle(event):
    sender = await event.get_sender()
    uid = sender.id
    uname = (sender.username or "").lower()
    text = event.raw_text.strip()
    logger.info(f"📩 From {uname or uid}: {text}")

    if uname in ignored_usernames:
        return

    if text.lower() == "iris stop" and uid == owner_id:
        pause_ai.add(uid)
        temp_pause_expiry[uid] = time.time() + pause_duration
        await event.reply("⏸️ AI auto-replies paused for 5 minutes.")
        return

    if event.is_private and re.search(r'\b(start a chat|msg|message|text|talk to|tell)\b', text, re.I):
        match = re.search(r'(?i)(@[\w\d_]+|\+?\d{10,15})', text)
        if not match:
            await event.reply("❗ Please specify a valid user.")
            return
        target = match.group(1).lstrip('@')
        msg_text = re.sub(r'(?i)(start a chat|msg|message|text|talk to|tell)\s+(@[\w\d_]+|\+?\d{10,15})', '', text).strip()
        try:
            entity = await client.get_entity(target)
            entity_id = entity.id
            target_display = f"@{entity.username}" if entity.username else target
            prompt = [
                {"role": "system", "content": f"You are {bot_username}, a helpful assistant. Write a short, warm, friendly message based on user request."},
                {"role": "user", "content": f"Send this to {target}: {msg_text}"}
            ]
            ai_msg = generate_reply(prompt, use_scout=True, use_bot_api=True)
            await client.send_message(entity_id, ai_msg)
            active_conversations[entity_id] = time.time()
            conversation_history[entity_id].append({"role": "user", "content": msg_text})
            conversation_history[entity_id].append({"role": "assistant", "content": ai_msg})
            await event.reply(f"✅ Sent to {target_display}.")
        except PeerIdInvalidError:
            await event.reply("❌ Cannot message user. Ask them to message you first.")
        except FloodWaitError as e:
            await event.reply(f"❌ Flood wait: wait {e.seconds}s.")
        except Exception as e:
            await event.reply(f"❌ Error: {e}")
        return

    if text == "/":
        pause_ai.add(uid)
        await event.reply("⏸️ AI paused for this chat.")
        return
    elif text == "\\":
        force_ai.add(uid)
        await event.reply("✅ AI forced ON for this chat.")
        return

    if uid in pause_ai and uid not in force_ai:
        return

    conversation_history[uid].append({"role": "user", "content": text})
    conversation_history[uid] = conversation_history[uid][-6:]

    prompt = [
        {"role": "system", "content": f"You are {bot_username}, a warm, polite Telegram assistant in Tamil-English. Keep replies short and helpful."},
        *conversation_history[uid]
    ]

    ai_reply = generate_reply(prompt, use_scout=False, use_bot_api=False)
    reply_msg = await event.reply(ai_reply)
    conversation_history[uid].append({"role": "assistant", "content": ai_reply})
    active_conversations[uid] = time.time()

    if re.search(r'\b(bye|thanks|ok|goodbye|later|gtg|ttyl)\b', text.lower()):
        try:
            await reply_msg.react(reaction_emoji)
        except Exception:
            pass

# === MONITOR SUMMARIES ===
async def monitor_summaries():
    while True:
        now = time.time()
        done = []
        for uid, last_seen in active_conversations.items():
            if now - last_seen > summary_interval:
                hist = conversation_history.get(uid, [])[-8:]
                if hist:
                    prompt = [
                        {"role": "system", "content": f"You are {bot_username}, summarizing a conversation in 10 lines."},
                        *hist
                    ]
                    summary = generate_reply(prompt, use_scout=True, use_bot_api=True)
                    try:
                        user = await client.get_entity(uid)
                        username = f"@{user.username}" if user.username else user.id
                        await client.send_message(bot_username, f"📄 Summary for chat with {username}:\n\n{summary}")
                        async for msg in client.iter_messages(uid, limit=1, from_user=user):
                            try:
                                await msg.react(reaction_emoji)
                            except Exception:
                                pass
                    except Exception as e:
                        logger.error(f"Failed summary: {e}")
                done.append(uid)
        for uid in done:
            active_conversations.pop(uid, None)
            conversation_history[uid] = []
        await asyncio.sleep(30)

# === MAIN ===
async def main():
    try:
        logger.info(f"Starting Telethon bot client...")
        await client.start(bot_token=bot_token)
        me = await client.get_me()
        logger.info(f"✅ Bot logged in as {me.username or me.id}")
        await asyncio.gather(
            client.run_until_disconnected(),
            monitor_summaries(),
            monitor_temp_pauses()
        )
    except ApiIdInvalidError:
        logger.error("❌ Invalid api_id/api_hash. Check https://my.telegram.org")
        raise
    except Exception as e:
        logger.error(f"❌ Bot startup failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())

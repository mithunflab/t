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
# Environment variables with fallbacks from provided values
api_id = int(os.getenv('API_ID', '22986717'))
api_hash = os.getenv('API_HASH', '1d1206253d640d42f488341e3b4f0a2f')
bot_token = os.getenv('BOT_TOKEN', '7275314987:AAHfuJwuR6-9L8Powjoc7UCLuT89KXpVi0I')
session_name = '/opt/render/project/src/bot_session'  # Render-compatible session file
groq_key_auto_reply = os.getenv('GROQ_KEY_AUTO_REPLY', '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')
groq_key_bot = os.getenv('GROQ_KEY_BOT', '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')
scout_model = 'meta-llama/llama-4-scout-17b-16e-instruct'
bot_username = '@Telethonpy_bot'
ignored_usernames = {'telethonpy_bot', 'lunaclaude_bot'}
reaction_emoji = '👍'
summary_interval = 120
owner_id = int(os.getenv('OWNER_ID', '123456789'))  # Replace with your Telegram user ID
pause_duration = 300  # 5 minutes in seconds

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
temp_pause_expiry = {}  # Tracks temporary pause expirations

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
            logger.info(f"Calling Groq API with model {model}, bot_api={use_bot_api}, key={groq_key[:10]}...")
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": messages[-10:],
                    "temperature": 0.7,
                    "max_tokens": 200
                },
                timeout=5
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

# === TEMPORARY PAUSE MONITOR ===
async def monitor_temp_pauses():
    while True:
        now = time.time()
        expired = []
        for uid, expiry in temp_pause_expiry.items():
            if now >= expiry:
                pause_ai.discard(uid)
                logger.info(f"Unpaused AI for user {uid} after {pause_duration} seconds")
                expired.append(uid)
        for uid in expired:
            temp_pause_expiry.pop(uid, None)
        await asyncio.sleep(10)

# === MESSAGE HANDLER ===
@client.on(events.NewMessage(incoming=True))
async def handle(event):
    sender = await event.get_sender()
    uid = sender.id
    uname = (sender.username or "").lower()
    text = event.raw_text.strip()
    logger.info(f"Received message from {uname or uid}: {text}")

    # Skip auto-replies for ignored usernames
    if uname in ignored_usernames:
        logger.info(f"Ignoring message from {uname}")
        return

    # Handle iris stop command (owner only)
    if text.lower() == "iris stop" and uid == owner_id:
        pause_ai.add(uid)
        temp_pause_expiry[uid] = time.time() + pause_duration
        logger.info(f"Owner paused AI for user {uid} for {pause_duration} seconds")
        await event.reply(f"⏸️ AI auto-replies paused for this chat for 5 minutes.")
        return

    # Handle bot commands
    if event.is_private and re.search(r'\b(start a chat|msg|message|text|talk to|tell)\b', text, re.I):
        logger.info(f"Processing bot command: {text}")
        match = re.search(r'(?i)(@[\w\d_]+|\+?\d{10,15})', text)
        if not match:
            logger.warning("No valid target user found in command")
            await event.reply("❗ Please specify a valid user (e.g., @username or phone number).")
            return
        target = match.group(1).lstrip('@')
        msg_text = re.sub(r'(?i)(start a chat|msg|message|text|talk to|tell)\s+(@[\w\d_]+|\+?\d{10,15})', '', text).strip()
        logger.info(f"Target: {target}, Message: {msg_text}")
        try:
            logger.info(f"Resolving entity for {target}")
            entity = await client.get_entity(target)
            entity_id = entity.id
            target_display = f"@{entity.username}" if entity.username else target
            # Generate context-specific message
            prompt = [
                {"role": "system", "content": f"You are {bot_username}, a friendly and polite Telegram assistant bot. Craft a concise, warm message in Tamil-English if appropriate. If the message mentions a party, create an enthusiastic party invitation. Always maintain a professional and courteous tone, acting like a personal assistant."},
                {"role": "user", "content": f"Send a message to {target} with this content: {msg_text}"}
            ]
            logger.info(f"Generating AI message for {target}")
            ai_msg = generate_reply(prompt, use_scout=True, use_bot_api=True)
            logger.info(f"Sending message to {target_display}: {ai_msg}")
            await client.send_message(entity_id, ai_msg)
            active_conversations[entity_id] = time.time()
            conversation_history[entity_id].append({"role": "user", "content": msg_text})
            conversation_history[entity_id].append({"role": "assistant", "content": ai_msg})
            await event.reply(f"✅ Sent message to {target_display}.")
        except PeerIdInvalidError:
            logger.error(f"Invalid peer: {target}")
            await event.reply(f"❌ Cannot send message to {target}. They may have restricted messages from non-contacts. Ask them to send /start to {bot_username} or set their privacy to allow messages from everybody (Settings > Privacy and Security > Who can send me messages? > Everybody).")
        except FloodWaitError as e:
            logger.error(f"Flood wait error: {e}")
            await event.reply(f"❌ Telegram rate limit reached. Please wait {e.seconds} seconds and try again.")
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

    # Auto-reply
    conversation_history[uid].append({"role": "user", "content": text})
    conversation_history[uid] = conversation_history[uid][-6:]
    prompt = [
        {"role": "system", "content": f"You are {bot_username}, a polite and friendly Telegram assistant bot. Respond warmly in Tamil-English if appropriate, acting like a personal assistant. Maintain context from previous messages and end with a polite closing if the conversation seems over."},
        *conversation_history[uid]
    ]
    logger.info(f"Generating auto-reply for {uid}")
    ai_reply = generate_reply(prompt, use_scout=False, use_bot_api=False)
    logger.info(f"Auto-replying to {uid}: {ai_reply}")
    reply_msg = await event.reply(ai_reply)
    conversation_history[uid].append({"role": "assistant", "content": ai_reply})
    active_conversations[uid] = time.time()

    # Check if conversation seems over
    if re.search(r'\b(bye|thanks|ok|goodbye|later|gtg|ttyl)\b', text.lower()):
        logger.info(f"Conversation with {uid} seems over, reacting with {reaction_emoji}")
        try:
            await reply_msg.react(reaction_emoji)
        except Exception as e:
            logger.error(f"Failed to react to message from {uid}: {e}")

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
                        {"role": "system", "content": f"You are {bot_username}, summarizing a conversation in up to 10 lines. Include what you and the user said, using a polite and professional tone."},
                        *hist
                    ]
                    logger.info(f"Generating summary for {uid}")
                    summary = generate_reply(prompt, use_scout=True, use_bot_api=True)
                    try:
                        user = await client.get_entity(uid)
                        username = f"@{user.username}" if user.username else user.id
                        logger.info(f"Sending summary for {username}")
                        await client.send_message(bot_username, f"📄 Summary for chat with {username}:\n\n{summary}")
                        async for msg in client.iter_messages(uid, limit=1, from_user=user):
                            if not msg.reactions:
                                logger.info(f"Reacting to last message from {uid} with {reaction_emoji}")
                                try:
                                    await msg.react(reaction_emoji)
                                except Exception as e:
                                    logger.error(f"Failed to react to message from {uid}: {e}")
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
        logger.info(f"Starting Telethon bot client with api_id={api_id}, bot_token={bot_token[:10]}...")
        await client.start(bot_token=bot_token)
        me = await client.get_me()
        logger.info(f"Bot started, logged in as {me.username or me.id}")
        await asyncio.gather(
            client.run_until_disconnected(),
            monitor_summaries(),
            monitor_temp_pauses()
        )
    except ApiIdInvalidError:
        logger.error("Invalid api_id/api_hash combination. Please verify credentials at https://my.telegram.org and ensure they match the Telegram account that created the bot.")
        raise
    except Exception as e:
        logger.error(f"Bot failed to start: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())

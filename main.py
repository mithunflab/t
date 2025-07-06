from telethon import TelegramClient, events, functions
import requests
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import defaultdict
import re

# === CONFIG ===
api_id = 22986717
api_hash = '1d1206253d640d42f488341e3b4f0a2f'
groq_api_key = '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'
session_name = 'session_mithun'

# === GLOBAL STATE ===
conversation_history = defaultdict(list)
pause_ai = set()   # user_id where AI is paused
force_ai = set()   # user_id where AI is forced even if you're online
manual_chatting_with = None  # Track who you're chatting with
bot_usernames = ['Telethonpy_bot']  # List your bot usernames

# === MODELS ===
groq_models = [
    "llama3-70b-8192",
    "llama3-8b-8192",
    "gemma-7b-it",
    "llama2-70b-4096"
]

# === CLIENT INIT ===
client = TelegramClient(session_name, api_id, api_hash)

# === WEB SERVER FOR UPTIME ===
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    def log_message(self, format, *args):
        return

def start_web():
    server = HTTPServer(('0.0.0.0', 10000), PingHandler)
    print("✅ Web ping server started on port 10000")
    server.serve_forever()

threading.Thread(target=start_web, daemon=True).start()

# === AI GENERATION ===
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
                    "messages": messages,
                    "temperature": 0.7
                }
            )
            if res.status_code == 200 and 'choices' in res.json():
                return res.json()['choices'][0]['message']['content']
        except Exception as e:
            print(f"Model {model} error: {e}")
    return "🤖 Sorry, something went wrong with AI."

# === MAIN REPLY HANDLER ===
@client.on(events.NewMessage(incoming=True))
async def handle_msg(event):
    global manual_chatting_with
    sender = await event.get_sender()
    user_id = sender.id
    message = event.raw_text.strip()

    # Bot Command Parser
    if event.is_private and not sender.bot:
        if message == "/":
            pause_ai.add(user_id)
            await event.reply("🤖 Paused AI replies for this chat.")
            return
        elif message == "\\":
            force_ai.add(user_id)
            await event.reply("🤖 Forced AI replies ON for this chat.")
            return

    # If this is from your bot to you (e.g. @Telethonpy_bot)
    if sender.username in bot_usernames:
        if re.search(r"msg|message\s+(him|her|\+?\d+)", message, re.I):
            target_match = re.findall(r"\+?\d{10,15}|him|her", message)
            if target_match:
                target_ref = target_match[0]
                print(f"👆 You instructed to message: {target_ref}")

                if target_ref.lower() in ["him", "her"]:
                    if manual_chatting_with:
                        await client.send_message(manual_chatting_with, "Hey, what's up! 👋")
                elif target_ref.startswith("+") or target_ref.isdigit():
                    try:
                        ent = await client.get_entity(target_ref)
                        await client.send_message(ent, "Hey! I'm Mithun. Let's chat 😊")
                    except Exception as e:
                        await event.reply(f"❌ Could not message: {e}")
            return

    # === Ignore paused ===
    if user_id in pause_ai and user_id not in force_ai:
        print(f"⏸️ AI paused for {user_id}")
        return

    # Track who you're manually chatting with
    me = await client.get_me()
    if event.is_private:
        async for msg in client.iter_messages(event.chat_id, limit=1, from_user=me):
            if msg.date.timestamp() > event.message.date.timestamp():
                manual_chatting_with = user_id
                print(f"✋ You're manually replying to {user_id}")
                return

    # Skip if you’re manually chatting with this person
    if manual_chatting_with == user_id and user_id not in force_ai:
        print(f"🤐 Suppressing AI since you're chatting manually with {user_id}")
        return

    # Process AI reply
    print(f"📨 Message from {sender.first_name}: {message}")
    conversation_history[user_id].append({"role": "user", "content": message})
    conversation_history[user_id] = conversation_history[user_id][-6:]

    messages = [
        {
            "role": "system",
            "content": (
                "You are Mithun. You are chatting with friends and family in Tamil-English mix, casually and warmly."
            )
        }
    ] + conversation_history[user_id]

    ai_reply = generate_ai_reply(messages)
    await event.reply(ai_reply)
    conversation_history[user_id].append({"role": "assistant", "content": ai_reply})

# === ASYNC MAIN ===
async def main():
    await client.connect()
    print("🤖 Telegram auto-reply bot is starting...")
    await client.run_until_disconnected()

asyncio.run(main())


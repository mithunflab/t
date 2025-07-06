from telethon import TelegramClient, events, functions, types
import requests
from collections import defaultdict
import asyncio
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# === CONFIG ===
api_id = 22986717
api_hash = '1d1206253d640d42f488341e3b4f0a2f'
groq_api_key = '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'

groq_models = ["llama3-8b-8192", "gemma-7b-it", "llama2-70b-4096"]
client = TelegramClient('session_mithun', api_id, api_hash)

conversation_history = defaultdict(list)
active_user_ids = set()
last_seen = {}
target_conversations = {}
summarizing = {}

# === Keep-alive server ===
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

# === Message Generator ===
def query_groq(messages, model=None, max_tokens=300):
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model or groq_models[0],
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": max_tokens
    }
    response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()['choices'][0]['message']['content']
    return None

# === Auto-reply Logic ===
@client.on(events.NewMessage(incoming=True))
async def auto_reply(event):
    sender = await event.get_sender()
    user_id = sender.id
    message = event.raw_text

    # Track online presence
    last_seen[user_id] = time.time()

    # Ignore bots or group messages
    if not event.is_private or sender.bot:
        return

    # Pause AI if you're manually chatting with this user
    if user_id in active_user_ids:
        print(f"⏸️ Skipping auto-reply for active chat with {sender.first_name}")
        return

    # If this user is a Groq instruction target
    if event.chat_id in target_conversations:
        target_conversations[event.chat_id]['messages'].append({"role": "user", "content": message})
        return

    print(f"\n📩 {sender.first_name}: {message}")
    conversation_history[user_id].append({"role": "user", "content": message})
    conversation_history[user_id] = conversation_history[user_id][-6:]

    system_prompt = {
        "role": "system",
        "content": (
            "You are Mithun. You talk to friends and family in a casual Tamil-English way. "
            "Use emojis, slang, and sound like a chill human. Avoid being too formal."
        )
    }
    messages = [system_prompt] + conversation_history[user_id]

    for model in groq_models:
        try:
            ai_reply = query_groq(messages, model)
            if ai_reply:
                print(f"🤖 Replying with {model}: {ai_reply}")
                await event.reply(ai_reply)
                conversation_history[user_id].append({"role": "assistant", "content": ai_reply})
                break
        except Exception as e:
            print(f"❌ Error from model {model}: {e}")

# === AI Command from Bot Chat ===
@client.on(events.NewMessage(from_users='Telethonpy_bot', pattern=r'.*'))
async def command_handler(event):
    cmd = event.raw_text.strip().lower()
    print(f"📥 Command: {cmd}")

    # Get Groq summary of command
    prompt = [
        {
            "role": "system",
            "content": (
                "You're a task interpreter. Extract target username and task from informal commands. "
                "Respond with JSON like {\"action\": \"message\", \"target\": \"@username\", \"text\": \"message to send\"}."
            )
        },
        {"role": "user", "content": cmd}
    ]
    try:
        parsed = query_groq(prompt, max_tokens=150)
        print("🧠 Groq parsed:", parsed)
        import json
        result = json.loads(parsed)

        if result.get("action") == "message" and "target" in result:
            target_username = result["target"].replace("@", "")
            target_entity = await client.get_entity(target_username)
            if not target_entity:
                await event.reply("❌ Could not find that user.")
                return

            target_id = target_entity.id
            ai_msgs = [{
                "role": "system",
                "content": f"You are Mithun. Start a casual conversation with {target_username} like a friend."
            }]
            if result.get("text"):
                ai_msgs.append({"role": "user", "content": result["text"]})

            target_conversations[target_id] = {
                "entity": target_entity,
                "messages": ai_msgs
            }
            await client.send_message(target_entity, ai_msgs[-1]["content"])
            await event.reply(f"✅ Started chatting with @{target_username}")
    except Exception as e:
        print("⚠️ Error handling command:", e)
        await event.reply("❌ Failed to understand your request.")

# === Periodic Summary Checker ===
async def monitor_and_summarize():
    while True:
        now = time.time()
        for user_id in list(target_conversations.keys()):
            if user_id in last_seen and now - last_seen[user_id] > 60 and not summarizing.get(user_id):
                # User has been idle for over 60 seconds
                print(f"📝 Summarizing conversation with user {user_id}")
                summarizing[user_id] = True
                messages = target_conversations[user_id]["messages"][-10:]
                messages.insert(0, {
                    "role": "system",
                    "content": "Summarize this conversation in 3 lines."
                })
                summary = query_groq(messages, max_tokens=100)
                if summary:
                    bot_chat = await client.get_entity('Telethonpy_bot')
                    await client.send_message(bot_chat, f"📝 Chat Summary:\n{summary}")
                del target_conversations[user_id]
                del summarizing[user_id]
        await asyncio.sleep(30)

# === Main async runner ===
async def main():
    await client.start()
    print("🤖 Telegram auto-reply bot is starting...")
    asyncio.create_task(monitor_and_summarize())
    await client.run_until_disconnected()

asyncio.run(main())

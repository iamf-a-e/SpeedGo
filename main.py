import os
import json
import logging
import requests
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from upstash_redis import Redis
import google.generativeai as genai

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# === Load environment variables ===
wa_token = os.environ.get("WA_TOKEN")
phone_id = os.environ.get("PHONE_ID")
gen_api = os.environ.get("GEN_API")

# === Initialize Redis ===
redis = Redis(
    url=os.environ["UPSTASH_REDIS_REST_URL"],
    token=os.environ["UPSTASH_REDIS_REST_TOKEN"]
)

# === Configure Gemini ===
genai.configure(api_key=gen_api)
gemini_model = genai.GenerativeModel("gemini-pro")

# === Save chat message ===
def save_chat_message(phone_number, role, message):
    key = f"chat:{phone_number}"
    entry = {
        "role": role,
        "message": message,
        "timestamp": datetime.utcnow().isoformat()
    }
    redis.rpush(key, json.dumps(entry))

# === Generate reply using Gemini ===
def generate_reply(prompt_text):
    try:
        response = gemini_model.generate_content(prompt_text)
        return response.text.strip()
    except Exception as e:
        logging.error(f"Gemini error: {e}")
        return "Sorry, I couldn't process that right now."

# === Send WhatsApp message ===
def send(reply, recipient, phone_id):
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {wa_token}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": reply}
    }
    try:
        res = requests.post(url, headers=headers, json=data)
        res.raise_for_status()
    except Exception as e:
        logging.error(f"Error sending message: {e}")

# === WhatsApp Webhook ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages")

                if messages:
                    for msg in messages:
                        sender = msg["from"]
                        text = msg["text"]["body"]
                        phone_id = value["metadata"]["phone_number_id"]

                        # Log user message
                        save_chat_message(sender, "user", text)

                        # Generate Gemini reply
                        reply = generate_reply(text)

                        # Send reply to WhatsApp
                        send(reply, sender, phone_id)

                        # Log bot reply
                        save_chat_message(sender, "bot", reply)

        return jsonify({"status": "received"}), 200

    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

# === Admin Chat Viewer UI ===
@app.route("/")
def index():
    return render_template("chat.html")

@app.route("/api/chat-history/<user_id>", methods=["GET"])
def api_chat_history(user_id):
    try:
        key = f"chat:{user_id}"
        entries = redis.lrange(key, 0, -1)
        return jsonify([json.loads(e) for e in entries])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/chat-users", methods=["GET"])
def chat_users():
    try:
        keys = redis.keys("chat:*")
        return jsonify([k.split(":")[1] for k in keys])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/send-message", methods=["POST"])
def send_message():
    data = request.json
    user_id = data.get("user_id")
    message = data.get("message")

    if not user_id or not message:
        return jsonify({"error": "Missing user_id or message"}), 400

    # Save message only (used by UI tester)
    save_chat_message(user_id, "user", message)
    return jsonify({"status": "ok", "logged": True})

# === Verify webhook (GET) ===
@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    challenge = request.args.get("hub.challenge")
    token = request.args.get("hub.verify_token")
    if mode == "subscribe" and token == os.environ.get("VERIFY_TOKEN"):
        return challenge, 200
    return "Unauthorized", 403

# === Run the app ===
if __name__ == "__main__":
    app.run(debug=True)

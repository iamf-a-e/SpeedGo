from flask import Flask, request, jsonify, render_template
from upstash_redis import Redis
from datetime import datetime
import json
import os

app = Flask(__name__)

# Use your actual Upstash values here (DO NOT expose in frontend)
redis = Redis(
    url='https://organic-cub-37552.upstash.io',
    token='AZKwAAIjcDEyOGMzNzE4NmVjYmE0YzA5OGRlNTFlNWM0YWExZjE3ZXAxMA'
)

def save_chat_message(user_id, role, message):
    key = f"chat:{user_id}"
    timestamp = datetime.utcnow().isoformat()
    entry = json.dumps({"role": role, "message": message, "timestamp": timestamp})
    redis.rpush(key, entry)

def get_chat_history(user_id):
    key = f"chat:{user_id}"
    messages = redis.lrange(key, 0, -1)
    return [json.loads(m) for m in messages]

@app.route("/")
def index():
    return render_template("chat.html")

@app.route("/api/chat-history/<user_id>")
def chat_history(user_id):
    try:
        return jsonify(get_chat_history(user_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/send-message", methods=["POST"])
def send_message():
    data = request.json
    user_id = data["user_id"]
    message = data["message"]

    save_chat_message(user_id, "user", message)
    bot_response = f"Echo: {message}"
    save_chat_message(user_id, "bot", bot_response)

    return jsonify({"status": "ok", "reply": bot_response})

if __name__ == "__main__":
    app.run(debug=True)

from flask import Flask, request, jsonify, render_template
from upstash_redis import Redis
from datetime import datetime
import json
import os

app = Flask(__name__)

# Use your actual Upstash values here (DO NOT expose in frontend)
redis = Redis(
    url=os.environ["UPSTASH_REDIS_REST_URL"],
    token=os.environ["UPSTASH_REDIS_REST_TOKEN"]
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



@app.route("/api/chat-history/<user_id>", methods=["GET"])
def api_chat_history(user_id):
    try:
        key = f"chat:{user_id}"
        entries = redis.lrange(key, 0, -1)
        history = [json.loads(e) for e in entries]
        return jsonify(history)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat-users", methods=["GET"])
def chat_users():
    keys = redis.keys("chat:*")
    user_ids = [key.split(":")[1] for key in keys]
    return jsonify(user_ids)


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

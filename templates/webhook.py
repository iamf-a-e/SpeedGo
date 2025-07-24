from flask import Flask, request, jsonify
import os
import requests
import json
from datetime import datetime

app = Flask(__name__)

# Upstash Redis config
UPSTASH_REDIS_URL = "https://organic-cub-37552.upstash.io"
UPSTASH_REDIS_TOKEN = "AZKwAAIjcDEyOGMzNzE4NmVjYmE0YzA5OGRlNTFlNWM0YWExZjE3ZXAxMA"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    try:
        messages = data['entry'][0]['changes'][0]['value']['messages']
        for msg in messages:
            from_number = msg['from']
            text = msg.get('text', {}).get('body', '')
            timestamp = datetime.utcnow().isoformat()

            message_data = {
                "sender": from_number,
                "text": text,
                "timestamp": timestamp
            }

            redis_key = f"chat:+263775127488:{from_number}"
            redis_url = f"{UPSTASH_REDIS_URL}/rpush/{redis_key}"
            headers = {
                "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                "Content-Type": "application/json"
            }
            requests.post(redis_url, headers=headers, data=json.dumps(json.dumps(message_data)))

        return jsonify({"status": "success"}), 200
    except Exception as e:
        print("Error processing webhook:", e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/webhook', methods=['GET'])
def verify_token():
    verify_token = "speedgo_verify_token"
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == verify_token:
            return challenge, 200
        else:
            return "Forbidden", 403
    return "Bad Request", 400

if __name__ == '__main__':
    app.run(port=5000)

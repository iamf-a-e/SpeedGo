import os
import json
import logging
from flask import Flask, request, jsonify, render_template
from upstash_redis import Redis

import main as english
import shona
import ndebele

logging.basicConfig(level=logging.INFO)

redis = Redis(
    url=os.environ["UPSTASH_REDIS_REST_URL"],
    token=os.environ["UPSTASH_REDIS_REST_TOKEN"]
)

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    return render_template("connected.html")

def get_user_language(sender):
    state = redis.get(sender)
    if state and isinstance(state, str):
        state = json.loads(state)
    if state and 'user' in state and 'language' in state['user']:
        return state['user']['language']
    return None

def get_user_state(sender):
    state = redis.get(sender)
    if state is None:
        return {"step": "welcome", "sender": sender}
    if isinstance(state, str):
        return json.loads(state)
    return state

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == "BOT":
            return challenge, 200
        return "Failed", 403

    elif request.method == "POST":
        data = request.get_json()
        logging.info(f"Incoming webhook data: {data}")
        try:
            entry = data["entry"][0]
            changes = entry["changes"][0]
            value = changes["value"]
            phone_id = value["metadata"]["phone_number_id"]
            messages = value.get("messages", [])
            if messages:
                message = messages[0]
                sender = message["from"]
                if "text" in message:
                    prompt = message["text"]["body"].strip()
                    user_state = get_user_state(sender)
                    user_state['sender'] = sender

                    # Determine language phase or delegate to handler
                    lang = None
                    if user_state.get('user') and 'language' in user_state['user']:
                        lang = user_state['user']['language']

                    # Initial phase or language selection
                    if user_state.get('step') in ['welcome', 'select_language'] or not lang:
                        # Always use English logic for language selection
                        next_state = english.get_action(user_state['step'], prompt, user_state, phone_id)
                        # Update user state after language selection
                        if next_state.get('user') and 'language' in next_state['user']:
                            lang = next_state['user']['language']
                        redis.set(sender, json.dumps(next_state))
                    else:
                        # Delegate to language-specific handler
                        if lang.lower() == "shona":
                            next_state = shona.get_action(user_state['step'], prompt, user_state, phone_id)
                            shona.update_user_state(sender, next_state)
                        elif lang.lower() == "ndebele":
                            next_state = ndebele.get_action(user_state['step'], prompt, user_state, phone_id)
                            ndebele.update_user_state(sender, next_state)
                        else:
                            next_state = english.get_action(user_state['step'], prompt, user_state, phone_id)
                            english.update_user_state(sender, next_state)
                else:
                    english.send("Please send a text message", sender, phone_id)
        except Exception as e:
            logging.error(f"Error processing webhook: {e}", exc_info=True)
        return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(debug=True, port=8000)

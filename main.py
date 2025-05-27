import os
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
from upstash_redis import Redis

import english
import shona
import ndebele

logging.basicConfig(level=logging.INFO)

redis = Redis(
    url=os.environ["UPSTASH_REDIS_REST_URL"],
    token=os.environ["UPSTASH_REDIS_REST_TOKEN"]
)

SESSION_TIMEOUT_SECONDS = 60

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
        return None
    if isinstance(state, str):
        state = json.loads(state)
    # Check for session expiration
    ts = state.get("last_active")
    if ts:
        last_active = datetime.fromisoformat(ts)
        if datetime.utcnow() - last_active > timedelta(seconds=SESSION_TIMEOUT_SECONDS):
            # Expired: delete session and return None
            redis.delete(sender)
            return None
    return state

def set_user_state(sender, state):
    state["last_active"] = datetime.utcnow().isoformat()
    redis.set(sender, json.dumps(state))


def get_action(current_state, prompt, user_data, phone_id):
    # Ensure 'user' key exists
    if 'user' not in user_data:
        user_data['user'] = User(user_data['sender']).to_dict()
    handler = action_mapping.get(current_state, handle_welcome)
    return handler(prompt, user_data, phone_id)


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
                    # If user state does not exist, always send language selection logic
                    if user_state is None:
                        # Send language selection prompt and save step as 'select_language'
                        english.send(
                            "Hi there! Welcome to SpeedGo Services for borehole drilling in Zimbabwe. "
                            "We provide reliable borehole drilling and water solutions across Zimbabwe.\n\n"
                            "Choose your preferred language:\n"
                            "1. English\n"
                            "2. Shona\n"
                            "3. Ndebele",
                            sender, phone_id
                        )
                        set_user_state(sender, {"step": "select_language", "sender": sender})
                    else:
                        user_state['sender'] = sender
                        lang = None
                        if user_state.get('user') and 'language' in user_state['user']:
                            lang = user_state['user']['language']

                        # If in language selection phase or language not set, always use English logic for language selection
                        if user_state.get('step') == 'select_language' or not lang:
                            next_state = english.get_action(user_state['step'], prompt, user_state, phone_id)
                            if next_state.get('user') and 'language' in next_state['user']:
                                lang = next_state['user']['language']
                            set_user_state(sender, next_state)
                        else:
                            # Get or initialize user state
                            user_state = get_user_state(sender) or {'sender': sender, 'step': 'handle_welcome'}
                            
                            # Ensure 'user' key exists
                            if 'user' not in user_state:
                                user_state['user'] = User(sender).to_dict()
                            
                            # Call the handler
                            step = user_state.get("step", "handle_welcome")
                            response_state = get_action(step, prompt, user_state, phone_id)

                            # Delegate to language-specific handler
                            if lang.lower() == "shona":
                                next_state = shona.get_action(user_state['step'], prompt, user_state, phone_id)
                                shona.update_user_state(sender, next_state)
                            elif lang.lower() == "ndebele":
                                next_state = ndebele.get_action(user_state['step'], prompt, user_state, phone_id)
                                ndebele.update_user_state(sender, next_state)
                            else:
                                next_state = english.get_action(user_state['step'], prompt, user_state, phone_id)
                                set_user_state(sender, next_state)
                else:
                    english.send("Please send a text message", sender, phone_id)
        except Exception as e:
            logging.error(f"Error processing webhook: {e}", exc_info=True)
        return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(debug=True, port=8000)

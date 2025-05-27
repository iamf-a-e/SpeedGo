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



def get_action(current_state, prompt, user_data, phone_id):
    # Ensure 'user' key exists
    if 'user' not in user_data:
        user_data['user'] = User(user_data['sender']).to_dict()
    handler = action_mapping.get(current_state, welcome)
    return handler(prompt, user_data, phone_id)


def get_user_state(user_id):
    data = redis_client.get(user_id)
    if data:
        try:
            return json.loads(data)
        except Exception:
            return {}
    return {}


def set_user_state(user_id, state_dict):
    redis_client.set(user_id, json.dumps(state_dict))


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json

    # Extract sender phone and message text
    sender = data.get('sender')  # adjust key name as per your webhook JSON
    prompt = data.get('message') # the user message text

    if not sender or not prompt:
        return jsonify({"error": "Missing sender or message"}), 400

    # Load user state from Redis
    user_state = get_user_state(sender)
    if not isinstance(user_state, dict):
        user_state = {}

    # Ensure 'user' key exists
    if 'user' not in user_state:
        # Initialize user data - customize as you like
        user_state['user'] = {
            "id": sender,
            "language": "english",  # default language
            # add other user data here
        }

    # Get user language (default to English)
    user_lang = user_state.get('user', {}).get('language', 'english').lower()

    # Get current step or default
    step = user_state.get('step', 'welcome')

    # Call appropriate language module based on user language
    if user_lang == "shona":
        next_state = shona.get_action(step, prompt, user_state, sender)
        shona.update_user_state(sender, next_state)
    elif user_lang == "ndebele":
        next_state = ndebele.get_action(step, prompt, user_state, sender)
        ndebele.update_user_state(sender, next_state)
    else:
        next_state = english.get_action(step, prompt, user_state, sender)
        english.update_user_state(sender, next_state)

    # Save updated state back to Redis
    set_user_state(sender, next_state)

    # Return a response (adjust based on your language module's output)
    response_text = next_state.get('response', 'Sorry, something went wrong.')

    return jsonify({"response": response_text})



if __name__ == "__main__":
    app.run(debug=True, port=8000)

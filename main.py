from flask import Flask, request, jsonify
from english import english_blueprint
from shona import shona_blueprint
from ndebele import ndebele_blueprint
from utils import get_user_language, set_user_language, send_message, set_user_state, get_user_state
import os
import logging
import json
import requests
import random
import string
from upstash_redis import Redis
import google.generativeai as genai
import threading
import time
from datetime import datetime


# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize Flask app
app = Flask(__name__)

# Register language blueprints
app.register_blueprint(english_blueprint, url_prefix='/english')
app.register_blueprint(shona_blueprint, url_prefix='/shona')
app.register_blueprint(ndebele_blueprint, url_prefix='/ndebele')

@app.route("/", methods=["GET"])
def index():
    return "SpeedGo WhatsApp Bot is running"

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
        logging.info(f"Incoming webhook data: {json.dumps(data, indent=2)}")

        try:
            entry = data.get("entry", [])[0]
            changes = entry.get("changes", [])[0]
            value = changes.get("value", {})
            phone_id = value.get("metadata", {}).get("phone_number_id")
            messages = value.get("messages", [])

            if messages:
                message = messages[0]
                sender = message.get("from")
                msg_type = message.get("type")
                
                # Get user's current state and language
                user_state = get_user_state(sender) or {}
                user_language = user_state.get('language', None)
                
                if not user_language and msg_type == "text":
                    # First time user - ask for language selection
                    prompt = message["text"]["body"].strip()
                    if prompt in ["1", "2", "3"]:
                        # User selected a language
                        if prompt == "1":
                            set_user_language(sender, "english")
                            from english import handle_select_language as handle_select_language
                            handle_select_language(prompt, {'sender': sender, 'step': 'select_language'}, phone_id)
                        elif prompt == "2":
                            set_user_language(sender, "shona")
                            from shona import handle_select_language2
                            handle_select_language(prompt, {'sender': sender, 'step': 'select_language'}, phone_id)
                        elif prompt == "3":
                            set_user_language(sender, "ndebele")
                            from ndebele import handle_select_language3
                            handle_select_language(prompt, {'sender': sender, 'step': 'select_language'}, phone_id)
                    else:
                        send_language_selection(sender, phone_id)
                    return jsonify({"status": "ok"}), 200
                
                # Route message to appropriate language handler
                if user_language == "english":
                    from english import message_handler
                    message_handler(message, sender, phone_id)
                elif user_language == "shona":
                    from shona import message_handler2
                    message_handler(message, sender, phone_id)
                elif user_language == "ndebele":
                    from ndebele import message_handler3
                    message_handler(message, sender, phone_id)

        except Exception as e:
            logging.error(f"Error processing webhook: {e}", exc_info=True)

        return jsonify({"status": "ok"}), 200

def send_language_selection(recipient, phone_id):
    """Send language selection menu to user"""
    message = (
        "Hi there! Welcome to SpeedGo Services for borehole drilling in Zimbabwe.\n\n"
        "Choose your preferred language:\n"
        "1. English\n"
        "2. Shona\n"
        "3. Ndebele"
    )
    
    send_message(message, recipient, phone_id)
    set_user_state(recipient, {'step': 'select_language'})

if __name__ == "__main__":
    app.run(debug=True, port=8000)

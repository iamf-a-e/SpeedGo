from flask import Flask, request, jsonify
import os
import logging
from english import english_blueprint
from shona import shona_blueprint
from ndebele import ndebele_blueprint

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
    return "Welcome to SpeedGo WhatsApp Bot"

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
                
                # Get user's current language preference
                user_language = get_user_language(sender)
                
                if not user_language:
                    # First time user - ask for language selection
                    send_language_selection(sender, phone_id)
                    return jsonify({"status": "ok"}), 200
                
                # Route message to appropriate language handler
                route_message_to_language(user_language, message, sender, phone_id)

        except Exception as e:
            logging.error(f"Error processing webhook: {e}", exc_info=True)

        return jsonify({"status": "ok"}), 200

def get_user_language(phone_number):
    """Get user's preferred language from Redis or database"""
    # This should be implemented based on your storage system
    # For now, we'll use a simple in-memory dictionary
    if not hasattr(get_user_language, 'user_languages'):
        get_user_language.user_languages = {}
    
    return get_user_language.user_languages.get(phone_number)

def set_user_language(phone_number, language):
    """Set user's preferred language in Redis or database"""
    # This should be implemented based on your storage system
    # For now, we'll use a simple in-memory dictionary
    if not hasattr(get_user_language, 'user_languages'):
        get_user_language.user_languages = {}
    
    get_user_language.user_languages[phone_number] = language

def send_language_selection(recipient, phone_id):
    """Send language selection menu to user"""
    from english import send  # Using English version for language selection
    
    message = (
        "Hi there! Welcome to SpeedGo Services for borehole drilling in Zimbabwe.\n\n"
        "Choose your preferred language:\n"
        "1. English\n"
        "2. Shona\n"
        "3. Ndebele"
    )
    
    send(message, recipient, phone_id)
    set_user_state(recipient, {'step': 'select_language'})

def route_message_to_language(language, message, sender, phone_id):
    """Route incoming message to appropriate language handler"""
    if language == "english":
        from english import message_handler as english_handler
        english_handler(message, sender, phone_id)
    elif language == "shona":
        from shona import message_handler as shona_handler
        shona_handler(message, sender, phone_id)
    elif language == "ndebele":
        from ndebele import message_handler as ndebele_handler
        ndebele_handler(message, sender, phone_id)

def set_user_state(phone_number, state_data):
    """Set user's state in Redis or database"""
    # This should be implemented based on your storage system
    # For now, we'll use a simple in-memory dictionary
    if not hasattr(set_user_state, 'user_states'):
        set_user_state.user_states = {}
    
    set_user_state.user_states[phone_number] = state_data

if __name__ == "__main__":
    app.run(debug=True, port=8000)

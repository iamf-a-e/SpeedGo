from flask import Flask, request, jsonify
from upstash_redis import Redis
import os, json, logging, requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# === Redis Setup ===
redis = Redis(
    url=os.environ["UPSTASH_REDIS_REST_URL"],
    token=os.environ["UPSTASH_REDIS_REST_TOKEN"]
)

# WhatsApp API Token
wa_token = os.environ.get("WA_TOKEN")

# === User Model ===
class User:
    def __init__(self, phone_number):
        self.phone_number = phone_number
        self.language = "English"
        self.quote_data = {}
        self.booking_data = {}
        self.offer_data = {}

    def to_dict(self):
        return {
            "phone_number": self.phone_number,
            "language": self.language,
            "quote_data": self.quote_data,
            "booking_data": self.booking_data,
            "offer_data": self.offer_data
        }

    @classmethod
    def from_dict(cls, data):
        user = cls(data.get("phone_number"))
        user.language = data.get("language", "English")
        user.quote_data = data.get("quote_data", {})
        user.booking_data = data.get("booking_data", {})
        user.offer_data = data.get("offer_data", {})
        return user

# === Redis State Functions ===
def get_user_state(phone_number):
    state = redis.get(phone_number)
    if state is None:
        return {"step": "welcome", "sender": phone_number}
    return json.loads(state) if isinstance(state, str) else state

def update_user_state(phone_number, updates):
    updates['phone_number'] = phone_number
    if 'sender' not in updates:
        updates['sender'] = phone_number
    redis.set(phone_number, json.dumps(updates))

# === WhatsApp Message Sender ===
def send(message, recipient, phone_id):
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {wa_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": message}
    }
    try:
        requests.post(url, headers=headers, json=payload).raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send message: {e}")

# === Prompts ===
prompts = {
    "english": {
        "main_menu": "Please choose:\n1. Request a Quote\n2. Book a Site Visit",
        "invalid": "Please choose a valid option: 1 or 2.",
        "quote_ack": "Thanks! We'll review your quote request.",
        "booking_ack": "Thanks! We'll confirm your booking soon.",
        "change_reminder": "\n\nType 'change language' anytime to switch."
    },
    "shona": {
        "main_menu": "Sarudza:\n1. Kukumbira quotation\n2. Bhuka Site Visit",
        "invalid": "Ndapota sarudza 1 kana 2.",
        "quote_ack": "Tatenda! Tichatarisa quotation yako.",
        "booking_ack": "Tatenda! Tichasimbisa bhuku renyu.",
        "change_reminder": "\n\nNyora 'shandura mutauro' kuti uchinje mutauro."
    },
    "ndebele": {
        "main_menu": "Khetha:\n1. Cela ikhotheshini\n2. Bhuka Uvakatjho",
        "invalid": "Sicela ukhethe u-1 noma u-2.",
        "quote_ack": "Siyabonga! Sizobuyela kuwe mayelana nekhotheshini.",
        "booking_ack": "Siyabonga! Sizakuqinisekisa ukubhuka kwakho.",
        "change_reminder": "\n\nBhala 'shintsha ulimi' ukhethe omunye ulimi."
    }
}

# === Language Reset Keywords ===
language_reset_keywords = {
    "english": ["change language"],
    "shona": ["shandura mutauro"],
    "ndebele": ["shintsha ulimi"]
}
all_language_triggers = sum(language_reset_keywords.values(), [])

# === Conversation Handlers ===
def handle_welcome(prompt, user_data, phone_id):
    send(
        "Hi there! Welcome to SpeedGo Services for borehole drilling in Zimbabwe.\n\n"
        "Choose your preferred language:\n1. English\n2. Shona\n3. Ndebele",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'select_language'})
    return {'step': 'select_language', 'sender': user_data['sender']}

def handle_select_language(prompt, user_data, phone_id):
    user = User.from_dict(user_data.get('user', {'phone_number': user_data['sender']}))
    step = "main_menu"

    if prompt == "1":
        user.language = "English"
    elif prompt == "2":
        user.language = "Shona"
    elif prompt == "3":
        user.language = "Ndebele"
    else:
        send("Please select 1, 2 or 3.", user_data['sender'], phone_id)
        return {'step': 'select_language', 'sender': user_data['sender']}

    lang_key = user.language.lower()
    message = prompts[lang_key]["main_menu"] + prompts[lang_key]["change_reminder"]

    update_user_state(user_data['sender'], {'step': step, 'user': user.to_dict()})
    send(message, user_data['sender'], phone_id)
    return {'step': step, 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_main_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language.lower()

    if prompt == "1":
        send("Please provide:\n- Location\n- Depth\n- Purpose", user_data['sender'], phone_id)
        next_step = "collect_quote"
    elif prompt == "2":
        send("Please provide:\n- Full Name\n- Preferred Date\n- Address\n- Payment Method", user_data['sender'], phone_id)
        next_step = "collect_booking"
    else:
        send(prompts[lang]["invalid"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {'step': next_step, 'user': user.to_dict()})
    return {'step': next_step, 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_quote(prompt, user_data, phone_id):
    lang = user_data['user']['language'].lower()
    send(prompts[lang]["quote_ack"], user_data['sender'], phone_id)
    return {'step': 'main_menu', 'user': user_data['user'], 'sender': user_data['sender']}

def handle_collect_booking(prompt, user_data, phone_id):
    lang = user_data['user']['language'].lower()
    send(prompts[lang]["booking_ack"], user_data['sender'], phone_id)
    return {'step': 'main_menu', 'user': user_data['user'], 'sender': user_data['sender']}

# === Action Router ===
action_map = {
    "welcome": handle_welcome,
    "select_language": handle_select_language,
    "main_menu": handle_main_menu,
    "collect_quote": handle_collect_quote,
    "collect_booking": handle_collect_booking
}

def get_action(step, prompt, user_data, phone_id):
    # Check for language switch request
    if prompt.lower() in all_language_triggers:
        return handle_welcome(prompt, user_data, phone_id)

    handler = action_map.get(step, handle_welcome)
    return handler(prompt, user_data, phone_id)

# === Message Handler ===
def message_handler(prompt, sender, phone_id):
    user_state = get_user_state(sender)
    user_state['sender'] = sender
    current_step = user_state.get("step", "welcome")

    next_state = get_action(current_step, prompt, user_state, phone_id)
    update_user_state(sender, next_state)

# === Webhook ===
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        phone_id = value["metadata"]["phone_number_id"]
        messages = value.get("messages", [])

        if not messages:
            return jsonify({"status": "no message"}), 200

        message = messages[0]
        sender = message["from"]

        if "text" in message:
            prompt = message["text"]["body"].strip()
            message_handler(prompt, sender, phone_id)
        else:
            send("Please send a text message.", sender, phone_id)

    except Exception as e:
        logging.error(f"Error processing webhook: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200

@app.route("/", methods=["GET"])
def index():
    return "SpeedGo WhatsApp Bot is running."

if __name__ == "__main__":
    app.run(debug=True, port=8000)

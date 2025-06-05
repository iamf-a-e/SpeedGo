import os
from flask import Flask, request, jsonify, render_template
import logging
from english import handle_main_menu as english_main_menu
from shona import handle_main_menu2 as shona_main_menu
from ndebele import handle_main_menu2 as ndebele_main_menu

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Language selection handler
def handle_language_selection(prompt, user_data, phone_id):
    if prompt == "1":  # English
        return english_main_menu("", user_data, phone_id)
    elif prompt == "2":  # Shona
        return shona_main_menu("", user_data, phone_id)
    elif prompt == "3":  # Ndebele
        return ndebele_main_menu("", user_data, phone_id)
    else:
        send("Please select a valid language option (1-3).", user_data['sender'], phone_id)
        return user_data


def handle_select_language(prompt, user_data, phone_id):
    user = User.from_dict(user_data.get('user', {'phone_number': user_data['sender']}))
    if prompt == "1":
        user.language = "English"
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(
            "Thank you!\n"
            "How can we help you today?\n\n"
            "1. Request a quote\n"
            "2. Search Price Using Location\n"
            "3. Check Project Status\n"
            "4. FAQs or Learn About Borehole Drilling\n"
            "5. Other services\n"
            "6. Talk to a Human Agent\n\n"
            "Please reply with a number (e.g., 1)",
            user_data['sender'], phone_id
        )
        return english_main_menu("", user_data, phone_id)
    
    elif prompt == "2":
        user.language = "Shona"
        update_user_state(user_data['sender'], {
            'step': 'main_menu2',
            'user': user.to_dict()
        })
        send(
            "Tatenda!\n"
            "Tinokubatsirai sei nhasi?\n\n"
            "1. Kukumbira quotation\n"
            "2. Tsvaga Mutengo Uchishandisa Nzvimbo\n"
            "3. Tarisa Mamiriro ePurojekiti\n"
            "4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Kuborehole\n"
            "5. Zvimwe Zvatinoita\n"
            "6. Taura neMunhu\n\n"
            "Pindura nenhamba (semuenzaniso, 1)",
            user_data['sender'], phone_id
        )
        return shona_main_menu("", user_data, phone_id)

    elif prompt == "3":
        user.language = "Ndebele"
        update_user_state(user_data['sender'], {
            'step': 'main_menu3',
            'user': user.to_dict()
        })
        send(
            "Siyabonga!\n"
            "Singakusiza njani lamuhla?\n\n"
            "1. Cela isiphakamiso\n"
            "2. Phanda Intengo Ngokusebenzisa Indawo\n"
            "3. Bheka Isimo Sephrojekthi\n"
            "4. Imibuzo Evame Ukubuzwa noma Funda Ngokuqhuba Ibhorehole\n"
            "5. Eminye Imisebenzi\n"
            "6. Khuluma Nomuntu\n\n"
            "Phendula ngenombolo (umzekeliso: 1)",
            user_data['sender'], phone_id
        )
        return ndebele_main_menu("", user_data, phone_id)
    
    else:
        send("Please select a valid language option (1 for English, 2 for Shona, 3 for Ndebele).", user_data['sender'], phone_id)
        return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}

# Send message function
def send(answer, sender, phone_id):
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {
        'Authorization': f'Bearer {os.environ.get("WA_TOKEN")}',
        'Content-Type': 'application/json'
    }
    data = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "text",
        "text": {"body": answer}
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
    except Exception as e:
        logging.error(f"Failed to send message: {e}")

@app.route("/", methods=["GET"])
def index():
    return render_template("connected.html")

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
                
                if msg_type == "text":
                    prompt = message["text"]["body"].strip()
                    logging.info(f"Text message from {sender}: {prompt}")
                    message_handler(prompt, sender, phone_id, message)
                
                elif msg_type == "location":
                    gps_coords = f"{message['location']['latitude']},{message['location']['longitude']}"
                    logging.info(f"Location from {sender}: {gps_coords}")
                    message_handler(gps_coords, sender, phone_id, message)

        except Exception as e:
            logging.error(f"Error processing webhook: {e}")

        return jsonify({"status": "ok"}), 200

def message_handler(prompt, sender, phone_id, message):
    user_data = get_user_state(sender)
    user_data['sender'] = sender

    if 'user' not in user_data:
        user_data['user'] = {"phone_number": sender, "language": "English"}

    step = user_data.get('step', 'welcome')
    
    if step == 'welcome':
        send(
            "Hi there! Welcome to SpeedGo Services for borehole drilling in Zimbabwe.\n\n"
            "Choose your preferred language:\n"
            "1. English\n"
            "2. Shona\n"
            "3. Ndebele",
            sender, phone_id
        )
        user_data['step'] = 'select_language'
        update_user_state(sender, user_data)
    
    elif step == 'select_language':
        next_state = handle_language_selection(prompt, user_data, phone_id)
        update_user_state(sender, next_state)
    
    else:
        # Delegate to language-specific handlers
        if user_data['user'].get('language') == "English":
            from english import action_mapping
        elif user_data['user'].get('language') == "Shona":
            from shona import action_mapping
        else:
            from ndebele import action_mapping
            
        handler = action_mapping.get(step, handle_welcome)
        next_state = handler(prompt, user_data, phone_id)
        update_user_state(sender, next_state)


def get_user_state(phone_number):
    state = redis.get(phone_number)
    if state is None:
        return {"step": "welcome", "sender": phone_number}
    if isinstance(state, str):
        return json.loads(state)
    return state


def update_user_state(phone_number, updates, ttl_seconds=60):
    updates['phone_number'] = phone_number
    if 'sender' not in updates:
        updates['sender'] = phone_number
    redis.set(phone_number, json.dumps(updates), ex=ttl_seconds)


if __name__ == "__main__":
    app.run(debug=True, port=8000)

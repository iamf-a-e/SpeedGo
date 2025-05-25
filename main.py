import os
import logging
import requests
import random
import string
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient
from bson.objectid import ObjectId
import pymongo
import certifi


logging.basicConfig(level=logging.INFO)

# Environment variables
wa_token = os.environ.get("WA_TOKEN")  # WhatsApp API Key
phone_id = os.environ.get("PHONE_ID") 
mongo_uri = os.environ.get("MONGO_URI")
gen_api = os.environ.get("GEN_API")    # Gemini API Key
owner_phone = os.environ.get("OWNER_PHONE")

# MongoDB setup
client = MongoClient(mongo_uri)
db = client.get_database("SpeedGo")
user_states_collection = db.user_states
quotes_collection = db.quotes
bookings_collection = db.bookings

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
        user = cls(data["phone_number"])
        user.language = data.get("language", "English")
        user.quote_data = data.get("quote_data", {})
        user.booking_data = data.get("booking_data", {})
        user.offer_data = data.get("offer_data", {})
        return user

# State handlers
def handle_welcome(prompt, user_data, phone_id):
    logging.info("Entered handle_welcome")
    try:
        send(
            "Hi there! Welcome to SpeedGo Services for borehole drilling in Zimbabwe. "
            "We provide reliable borehole drilling and water solutions across Zimbabwe.\n\n"
             "Choose your preferred language:\n"
             "1. English\n"
             "2. Shona\n"
             "3. Ndebele",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'select_language'})
        return {'step': 'select_language'}
    except Exception as e:
        logging.error(f"Exception in handle_welcome: {e}", exc_info=True)
        return {'step': 'select_language'}

def handle_select_language(prompt, user_data, phone_id):
    user = User.from_dict(user_data.get('user', {'phone_number': user_data['sender']}))
    
    if prompt in ["1", "2", "3"]:
        languages = {
            "1": "English",
            "2": "Shona",
            "3": "Ndebele"
        }
        user.language = languages[prompt]
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(
            "Thank you!\n"
            "How can we help you today?\n\n"
            "1. Request a quote\n"
            "2. Book a Site Visit\n"
            "3. Check Project Status\n"
            "4. Learn About Borehole Drilling\n"
            "5. Talk to a Human Agent\n\n"
            "Please reply with a number (e.g., 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu', 'user': user.to_dict()}
    else:
        send("Please select a valid language option (1, 2, or 3)", user_data['sender'], phone_id)
        return {'step': 'select_language'}

def handle_main_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if prompt == "1":  # Request a quote
        update_user_state(user_data['sender'], {
            'step': 'select_service',
            'user': user.to_dict()
        })
        send(
            "Thank you!\n"
            "Select the service:\n"
            "1. Borehole drilling\n"
            "2. Borehole pump installation\n"
            "3. Water pond construction\n"
            "4. Weir dam construction",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service', 'user': user.to_dict()}
    elif prompt == "2":  # Book site visit
        # Implementation for site visit booking
        pass
    elif prompt == "5":  # Human agent
        send("Connecting you to a human agent...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict()}
    else:
        send("Please select a valid option (1-5)", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict()}

def handle_select_service(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if prompt in ["1", "2", "3", "4"]:
        services = {
            "1": "Borehole drilling",
            "2": "Borehole pump installation",
            "3": "Water pond construction",
            "4": "Weir dam construction"
        }
        user.quote_data['service'] = services[prompt]
        update_user_state(user_data['sender'], {
            'step': 'collect_quote_details',
            'user': user.to_dict()
        })
        send(
            "To give you a quick estimate, please answer the following:\n\n"
            "1. Your location (City/Town or GPS):\n"
            "2. Desired borehole depth (if known):\n"
            "3. Purpose (Domestic / Agricultural / Industrial):\n"
            "4. Did you conduct a water survey? (Yes or No)\n"
            "5. If you need borehole Deepening, click 5 and proceed\n"
            "6. PVC pipe casing: Class 6 or Class 9 or Class 10\n\n"
            "Once you reply, we'll calculate and send you a quote within minutes.",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_quote_details', 'user': user.to_dict()}
    else:
        send("Please select a valid service (1-4)", user_data['sender'], phone_id)
        return {'step': 'select_service', 'user': user.to_dict()}

def handle_collect_quote_details(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    responses = prompt.split('\n')
    
    if len(responses) >= 4:
        user.quote_data.update({
            'location': responses[0].strip(),
            'depth': responses[1].strip(),
            'purpose': responses[2].strip(),
            'water_survey': responses[3].strip(),
            'casing_type': responses[5].strip() if len(responses) > 5 else "Not specified"
        })
        
        # Save quote to database
        quote_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        quote_data = {
            'quote_id': quote_id,
            'user_data': user.to_dict(),
            'timestamp': datetime.now(),
            'status': 'pending'
        }
        quotes_collection.insert_one(quote_data)
        
        update_user_state(user_data['sender'], {
            'step': 'quote_response',
            'user': user.to_dict()
        })
        
        # Generate sample estimate (in a real app, this would be calculated)
        estimate = "Class 6: Estimated Cost: $2500\nIncludes drilling, PVC casing 140mm"
        
        send(
            f"Thank you! Based on your details:\n\n"
            f"{estimate}\n\n"
            f"Note: Double casing costs are charged as additional costs if need be, and upon client confirmation\n\n"
            f"Would you like to:\n"
            f"1. Offer your price?\n"
            f"2. Book a Site Survey\n"
            f"3. Book for a Drilling\n"
            f"4. Talk to a human Agent",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_response', 'user': user.to_dict()}
    else:
        send("Please provide all the requested information", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details', 'user': user.to_dict()}

def handle_quote_response(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if prompt == "1":  # Offer price
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details',
            'user': user.to_dict()
        })
        send(
            "Sure! You can share your proposed prices below.\n\n"
            "Please reply with your offer in the format:\n\n"
            "- Water Survey: $_\n"
            "- Borehole Drilling: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details', 'user': user.to_dict()}
    elif prompt == "2":  # Book site survey
        # Implementation for site survey booking
        pass
    else:
        send("Please select a valid option (1-4)", user_data['sender'], phone_id)
        return {'step': 'quote_response', 'user': user.to_dict()}

def handle_collect_offer_details(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    # Parse offer details (simplified for example)
    user.offer_data['offer'] = prompt
    user.offer_data['status'] = 'pending'
    
    # Save offer to database
    quotes_collection.update_one(
        {'quote_id': user.quote_data.get('quote_id')},
        {'$set': {'offer_data': user.offer_data}}
    )
    
    update_user_state(user_data['sender'], {
        'step': 'offer_response',
        'user': user.to_dict()
    })
    
    send(
        "Your request has been sent to our sales manager. We will reply within 1 hour.\n\n"
        "Thank you for your offer!\n\n"
        "Our team will review it and respond shortly.\n\n"
        "While we aim to be affordable, our prices reflect quality, safety, and reliability.\n\n"
        "Would you like to:\n"
        "1. Proceed if offer is accepted\n"
        "2. Speak to a human\n"
        "3. Revise your offer",
        user_data['sender'], phone_id
    )
    return {'step': 'offer_response', 'user': user.to_dict()}

def handle_offer_response(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if prompt == "1":  # Offer accepted (simulated)
        user.offer_data['status'] = 'accepted'
        quotes_collection.update_one(
            {'quote_id': user.quote_data.get('quote_id')},
            {'$set': {'offer_data.status': 'accepted'}}
        )
        
        update_user_state(user_data['sender'], {
            'step': 'booking_details',
            'user': user.to_dict()
        })
        
        send(
            "Great news! Your offer has been accepted.\n\n"
            "Let's confirm your next step.\n\n"
            "Would you like to:\n"
            "1. Book Site Survey\n"
            "2. Pay Deposit\n"
            "3. Confirm Drilling Date",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_details', 'user': user.to_dict()}
    elif prompt == "3":  # Revise offer
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details',
            'user': user.to_dict()
        })
        send(
            "Please reply with your revised offer in the format:\n\n"
            "- Water Survey: $_\n"
            "- Borehole Drilling: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details', 'user': user.to_dict()}
    else:
        send("Please select a valid option (1-3)", user_data['sender'], phone_id)
        return {'step': 'offer_response', 'user': user.to_dict()}

def handle_booking_details(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if prompt == "1":  # Book site survey
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info',
            'user': user.to_dict()
        })
        send(
            "Great! Please provide the following information to finalize your booking:\n\n"
            "- Full Name:\n"
            "- Preferred Date (dd/mm/yyyy):\n"
            "- Site Address: GPS or address\n"
            "- Mobile Number:\n"
            "- Payment Method (Prepayment / Cash at site):\n\n"
            "Type: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info', 'user': user.to_dict()}
    else:
        send("Please select a valid option (1-3)", user_data['sender'], phone_id)
        return {'step': 'booking_details', 'user': user.to_dict()}

def handle_collect_booking_info(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if prompt.lower() == "submit":
        # Parse booking details (simplified for example)
        user.booking_data['status'] = 'confirmed'
        user.booking_data['timestamp'] = datetime.now()
        
        # Save booking to database
        booking_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        booking_data = {
            'booking_id': booking_id,
            'user_data': user.to_dict(),
            'timestamp': datetime.now(),
            'status': 'confirmed'
        }
        bookings_collection.insert_one(booking_data)
        
        update_user_state(user_data['sender'], {
            'step': 'booking_confirmation',
            'user': user.to_dict()
        })
        
        # Sample booking details
        booking_date = "25/05/2025"
        booking_time = "10:00 AM"
        
        send(
            "Thank you. Your booking appointment is approved, and a technician will contact you soon.\n\n"
            f"Reminder: Your site survey is scheduled for tomorrow.\n\n"
            f"Date: {booking_date}\n"
            f"Time: {booking_time}\n\n"
            "We look forward to working with you!\n"
            "Need to reschedule? Reply\n\n"
            "1. Yes\n"
            "2. No",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_confirmation', 'user': user.to_dict()}
    else:
        send("Please type 'Submit' to confirm your booking", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info', 'user': user.to_dict()}

def handle_booking_confirmation(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if prompt == "2":  # No reschedule needed
        send(
            "Great! Your borehole drilling appointment is now booked.\n\n"
            "Date: Thursday, 23 May 2025\n"
            "Start Time: 8:00 AM\n"
            "Expected Duration: 5 hrs\n"
            "Team: 4-5 Technicians\n\n"
            "Make sure there is access to the site",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome', 'user': user.to_dict()}
    else:
        send("Please contact our support team to reschedule", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation', 'user': user.to_dict()}

# Utility functions (same as before)
def get_user_state(phone_number):
    state = user_states_collection.find_one({'phone_number': phone_number})
    if state:
        state['_id'] = str(state['_id'])
        return state
    return {'step': 'welcome', 'sender': phone_number}

def update_user_state(phone_number, updates):
    updates['phone_number'] = phone_number
    if 'sender' not in updates:
        updates['sender'] = phone_number
    user_states_collection.update_one(
        {'phone_number': phone_number},
        {'$set': updates},
        upsert=True
    )

def send(answer, sender, phone_id):
    logging.info(f"send() called with answer='{answer}', sender='{sender}', phone_id='{phone_id}'")
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {
        'Authorization': f'Bearer {wa_token}',
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
        logging.info(f"Sent message to {sender}: {answer}")
        logging.info(f"WhatsApp API response: {response.json()}")
    except requests.exceptions.RequestException as e:
        error_text = getattr(e.response, 'text', None)
        logging.error(f"Failed to send message to {sender}: {e} | Response: {error_text}")

# Action mapping
action_mapping = {
    "welcome": handle_welcome,
    "select_language": handle_select_language,
    "main_menu": handle_main_menu,
    "select_service": handle_select_service,
    "collect_quote_details": handle_collect_quote_details,
    "quote_response": handle_quote_response,
    "collect_offer_details": handle_collect_offer_details,
    "offer_response": handle_offer_response,
    "booking_details": handle_booking_details,
    "collect_booking_info": handle_collect_booking_info,
    "booking_confirmation": handle_booking_confirmation
}

def get_action(current_state, prompt, user_data, phone_id):
    handler = action_mapping.get(current_state, handle_welcome)
    return handler(prompt, user_data, phone_id)

# Flask app (same as before)
app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
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
                    message_handler(prompt, sender, phone_id)
                else:
                    logging.info("Received non-text message")
                    send("Please send a text message", sender, phone_id)
                    
        except Exception as e:
            logging.error(f"Error processing webhook: {e}", exc_info=True)
            
        return jsonify({"status": "ok"}), 200

def message_handler(prompt, sender, phone_id):
    logging.info(f"message_handler called with prompt={prompt}, sender={sender}, phone_id={phone_id}")
    user_state = get_user_state(sender)
    user_state['sender'] = sender
    updated_state = get_action(user_state['step'], prompt, user_state, phone_id)
    update_user_state(sender, updated_state)


if __name__ == "__main__":
    app.run(debug=True, port=8000)

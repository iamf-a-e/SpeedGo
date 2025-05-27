from flask import Flask, request, jsonify
from upstash_redis import Redis
import os, json, logging, requests, string, random
from datetime import datetime

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

# === English Chat Logic Handlers ===
def handle_welcome(prompt, user_data, phone_id):
    send(
        "Hi there! Welcome to SpeedGo Services for borehole drilling in Zimbabwe. "
        "We provide reliable borehole drilling and water solutions across Zimbabwe.

"
        "Choose your preferred language:
"
        "1. English
"
        "2. Shona
"
        "3. Ndebele",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'select_language'})
    return {'step': 'select_language', 'sender': user_data['sender']}

def handle_select_language(prompt, user_data, phone_id):
    user = User.from_dict(user_data.get('user', {'phone_number': user_data['sender']}))
    if prompt == "1":
        user.language = "English"
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(
            "Thank you!
"
            "How can we help you today?

"
            "1. Request a quote
"
            "2. Book a Site Visit
"
            "3. Check Project Status
"
            "4. Learn About Borehole Drilling
"
            "5. Talk to a Human Agent

"
            "Please reply with a number (e.g., 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please reply 1 to continue in English.", user_data['sender'], phone_id)
        return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_main_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'select_service',
            'user': user.to_dict()
        })
        send(
            "Thank you!
"
            "Select the service:
"
            "1. Borehole drilling
"
            "2. Borehole pump installation
"
            "3. Water pond construction
"
            "4. Weir dam construction",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info',
            'user': user.to_dict()
        })
        send(
            "To book a site visit, please provide the following:
"
            "- Full Name:
"
            "- Preferred Date (dd/mm/yyyy):
"
            "- Site Address:
"
            "- Mobile Number:
"
            "- Payment Method (Prepayment / Cash at site):

"
            "Type 'Submit' to confirm your booking.",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("This feature is coming soon. Please contact your agent for updates.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":
        send(
            "We offer:
"
            "- Borehole drilling
"
            "- Borehole pump installation
"
            "- Water pond and weir dam construction
"
            "Contact us for more info!", user_data['sender'], phone_id
        )
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "5":
        send("Connecting you to a human agent...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please select a valid option (1-5).", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_select_service(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    services = {
        "1": "Borehole drilling",
        "2": "Borehole pump installation",
        "3": "Water pond construction",
        "4": "Weir dam construction"
    }
    if prompt in services:
        user.quote_data['service'] = services[prompt]
        update_user_state(user_data['sender'], {
            'step': 'collect_quote_details',
            'user': user.to_dict()
        })
        send(
            "To give you a quick estimate, please answer the following:

"
            "1. Your location (City/Town or GPS):
"
            "2. Desired borehole depth (if known):
"
            "3. Purpose (Domestic / Agricultural / Industrial):
"
            "4. Did you conduct a water survey? (Yes or No)
"
            "5. If you need borehole Deepening, type 'Deepening'
"
            "6. PVC pipe casing: Class 6 or Class 9 or Class 10

"
            "Reply with your answers, each on a new line.",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_quote_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please select a valid service (1-4).", user_data['sender'], phone_id)
        return {'step': 'select_service', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_quote_details(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    responses = prompt.split('
')
    if len(responses) >= 4:
        user.quote_data.update({
            'location': responses[0].strip(),
            'depth': responses[1].strip(),
            'purpose': responses[2].strip(),
            'water_survey': responses[3].strip(),
            'casing_type': responses[5].strip() if len(responses) > 5 else "Not specified"
        })
        quote_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        user.quote_data['quote_id'] = quote_id
        redis.set(f"quote:{quote_id}", json.dumps({
            'quote_id': quote_id,
            'user_data': user.to_dict(),
            'timestamp': datetime.now().isoformat(),
            'status': 'pending'
        }))
        update_user_state(user_data['sender'], {
            'step': 'quote_response',
            'user': user.to_dict()
        })
        estimate = "Class 6: Estimated Cost: $2500
Includes drilling, PVC casing 140mm"
        send(
            f"Thank you! Based on your details:

"
            f"{estimate}

"
            f"Note: Double casing costs are charged as additional costs if need be, and upon client confirmation

"
            f"Would you like to:
"
            f"1. Offer your price?
"
            f"2. Book a Site Survey
"
            f"3. Book for a Drilling
"
            f"4. Talk to a human Agent",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_response', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please provide all the requested information (at least 4 lines).", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_quote_response(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details',
            'user': user.to_dict()
        })
        send(
            "Sure! You can share your proposed prices below.

"
            "Please reply with your offer in the format:

"
            "- Water Survey: $_
"
            "- Borehole Drilling: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info',
            'user': user.to_dict()
        })
        send(
            "Great! Please provide the following information to finalize your booking:

"
            "- Full Name:
"
            "- Preferred Date (dd/mm/yyyy):
"
            "- Site Address: GPS or address
"
            "- Mobile Number:
"
            "- Payment Method (Prepayment / Cash at site):

"
            "Type: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("Our agent will contact you to finalize the drilling booking.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":
        send("Connecting you to a human agent...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please select a valid option (1-4).", user_data['sender'], phone_id)
        return {'step': 'quote_response', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_offer_details(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    user.offer_data['offer'] = prompt
    user.offer_data['status'] = 'pending'
    quote_id = user.quote_data.get('quote_id')
    if quote_id:
        q = redis.get(f"quote:{quote_id}")
        if q:
            q = json.loads(q)
            q['offer_data'] = user.offer_data
            redis.set(f"quote:{quote_id}", json.dumps(q))
    update_user_state(user_data['sender'], {
        'step': 'offer_response',
        'user': user.to_dict()
    })
    send(
        "Your request has been sent to our sales manager. We will reply within 1 hour.

"
        "Thank you for your offer!

"
        "Our team will review it and respond shortly.

"
        "While we aim to be affordable, our prices reflect quality, safety, and reliability.

"
        "Would you like to:
"
        "1. Proceed if offer is accepted
"
        "2. Speak to a human
"
        "3. Revise your offer",
        user_data['sender'], phone_id
    )
    return {'step': 'offer_response', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_offer_response(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    quote_id = user.quote_data.get('quote_id')
    if prompt == "1":
        user.offer_data['status'] = 'accepted'
        if quote_id:
            q = redis.get(f"quote:{quote_id}")
            if q:
                q = json.loads(q)
                q['offer_data'] = user.offer_data
                redis.set(f"quote:{quote_id}", json.dumps(q))
        update_user_state(user_data['sender'], {
            'step': 'booking_details',
            'user': user.to_dict()
        })
        send(
            "Great news! Your offer has been accepted.

"
            "Let's confirm your next step.

"
            "Would you like to:
"
            "1. Book Site Survey
"
            "2. Pay Deposit
"
            "3. Confirm Drilling Date",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Connecting you to a human agent...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details',
            'user': user.to_dict()
        })
        send(
            "Please reply with your revised offer in the format:

"
            "- Water Survey: $_
"
            "- Borehole Drilling: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please select a valid option (1-3).", user_data['sender'], phone_id)
        return {'step': 'offer_response', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_details(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info',
            'user': user.to_dict()
        })
        send(
            "Great! Please provide the following information to finalize your booking:

"
            "- Full Name:
"
            "- Preferred Date (dd/mm/yyyy):
"
            "- Site Address: GPS or address
"
            "- Mobile Number:
"
            "- Payment Method (Prepayment / Cash at site):

"
            "Type: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Please contact our office at 077xxxxxxx to arrange deposit payment.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("Our agent will contact you to confirm the drilling date.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please select a valid option (1-3).", user_data['sender'], phone_id)
        return {'step': 'booking_details', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_booking_info(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt.lower().strip() == "submit":
        user.booking_data['status'] = 'confirmed'
        user.booking_data['timestamp'] = datetime.now().isoformat()
        booking_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        user.booking_data['booking_id'] = booking_id
        redis.set(f"booking:{booking_id}", json.dumps({
            'booking_id': booking_id,
            'user_data': user.to_dict(),
            'timestamp': datetime.now().isoformat(),
            'status': 'confirmed'
        }))
        update_user_state(user_data['sender'], {
            'step': 'booking_confirmation',
            'user': user.to_dict()
        })
        booking_date = "25/05/2025"
        booking_time = "10:00 AM"
        send(
            "Thank you. Your booking appointment is approved, and a technician will contact you soon.

"
            f"Reminder: Your site survey is scheduled for tomorrow.

"
            f"Date: {booking_date}
"
            f"Time: {booking_time}

"
            "We look forward to working with you!
"
            "Need to reschedule? Reply

"
            "1. Yes
"
            "2. No",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_confirmation', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please type 'Submit' to confirm your booking.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_confirmation(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "2":  # No reschedule needed
        send(
            "Great! Your borehole drilling appointment is now booked.

"
            "Date: Thursday, 23 May 2025
"
            "Start Time: 8:00 AM
"
            "Expected Duration: 5 hrs
"
            "Team: 4-5 Technicians

"
            "Make sure there is access to the site",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please contact our support team to reschedule.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation', 'user': user.to_dict(), 'sender': user_data['sender']}

# Done. All handlers are now integrated.

import os
import json
import logging
import requests
import random
import string
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from upstash_redis import Redis

logging.basicConfig(level=logging.INFO)

# Environment variables
wa_token = os.environ.get("WA_TOKEN")
phone_id = os.environ.get("PHONE_ID")
gen_api = os.environ.get("GEN_API")
owner_phone = os.environ.get("OWNER_PHONE")

# Upstash Redis setup
redis = Redis(
    url=os.environ["UPSTASH_REDIS_REST_URL"],
    token=os.environ["UPSTASH_REDIS_REST_TOKEN"]
)

# User serialization helpers
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

# State helpers
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

def send(answer, sender, phone_id):
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
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send message: {e}")

def select_service(user_state):
    services = {
        "1": "Borehole drilling",
        "2": "Borehole pump installation",
        "3": "Water pond construction",
        "4": "Weir dam construction",
    }
    
    print("\nAvailable Services:")
    for key, value in services.items():
        print(f"{key}. {value}")
    
    while True:
        choice = input("\nSelect a service (1-4) or 'q' to quit: ")
        if choice.lower() == 'q':
            return None
        if choice in services:
            selected_service = services[choice]
            print(f"\nYou selected: {selected_service}")
            return {'selected_service':selected_service, 'step': 'handle_select_service'}
        print("Invalid selection. Please try again.")
        # Update and return user_state
        user_state["selected_service"] = selected_service
        user_state["step"] = "handle_main_menu"
        return user_state
        
    print("Invalid choice. Please select a number between 1 and 4.")


def select_service2(user_state):
    services = {
        "1": "Kuchera chibhorani",
        "2": "Kuisa pombi yechibhorani",
        "3": "Kuvaka pond yemvura",
        "4": "Kuvaka weir dam",
    }
    
    print("\nAvailable Services:")
    for key, value in services.items():
        print(f"{key}. {value}")
    
    while True:
        choice = input("\nSelect a service (1-4) or 'q' to quit: ")
        if choice.lower() == 'q':
            return None
        if choice in services:
            selected_service = services[choice]
            print(f"\nYou selected: {selected_service}")
            return {'selected_service':selected_service, 'step': 'handle_select_service2'}
        print("Invalid selection. Please try again.")
        # Update and return user_state
        user_state["selected_service"] = selected_service
        user_state["step"] = "handle_main_menu2"
        return user_state
        
    print("Ndapota sarudza sevhisi pakati pa1-4.")
        

# State handlers (English flow only)
def handle_welcome(prompt, user_data, phone_id):
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
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
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
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

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
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        send("Please select a valid language option (1 for English, 2 for Shona, 3 for Ndebele).", user_data['sender'], phone_id)
        return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}

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
            "1. Water survey\n"
            "2. Borehole drilling\n"
            "3. Pump installation\n"
            "4. Commercial hole drilling"
            "5. Borehole Deepening",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":  # Book site visit
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info',
            'user': user.to_dict()
        })
        send(
            "To book a site visit, please provide the following:\n"
            "- Full Name:\n"
            "- Preferred Date (dd/mm/yyyy):\n"
            "- Site Address:\n"
            "- Mobile Number:\n"
            "- Payment Method (Prepayment / Cash at site):\n\n"
            "Type 'Submit' to confirm your booking.",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Check Project Status
        send("This feature is coming soon. Please contact your agent for updates.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":  # Learn About Borehole Drilling
        send(
            "We offer:\n"
            "- Borehole drilling\n"
            "- Borehole pump installation\n"
            "- Water pond and weir dam construction\n"
            "Contact us for more info!", user_data['sender'], phone_id
        )
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "5":  # Human agent
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
            "To give you a quick estimate, tell me your location (City/Town or GPS)\n"
            user_data['sender'], phone_id
        )
        return {'step': 'collect_quote_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please select a valid service (1-4).", user_data['sender'], phone_id)
        return {'step': 'select_service', 'user': user.to_dict(), 'sender': user_data['sender']}

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
        quote_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        user.quote_data['quote_id'] = quote_id
        # Save quote to Redis (simulate DB)
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
        return {'step': 'quote_response', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please provide all the requested information (at least 4 lines).", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details', 'user': user.to_dict(), 'sender': user_data['sender']}

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
        return {'step': 'collect_offer_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":  # Book site survey
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
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Book for a Drilling
        send("Our agent will contact you to finalize the drilling booking.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":  # Human Agent
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
    return {'step': 'offer_response', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_offer_response(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    quote_id = user.quote_data.get('quote_id')
    if prompt == "1":  # Offer accepted (simulated)
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
            "Great news! Your offer has been accepted.\n\n"
            "Let's confirm your next step.\n\n"
            "Would you like to:\n"
            "1. Book Site Survey\n"
            "2. Pay Deposit\n"
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
            "Please reply with your revised offer in the format:\n\n"
            "- Water Survey: $_\n"
            "- Borehole Drilling: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please select a valid option (1-3).", user_data['sender'], phone_id)
        return {'step': 'offer_response', 'user': user.to_dict(), 'sender': user_data['sender']}

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
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":  # Pay Deposit
        send("Please contact our office at 077xxxxxxx to arrange deposit payment.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Confirm Drilling Date
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
        return {'step': 'booking_confirmation', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please type 'Submit' to confirm your booking.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}

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
        return {'step': 'welcome', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please contact our support team to reschedule.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_select_language2(prompt, user_data, phone_id):
    user = User.from_dict(user_data.get('user', {'phone_number': user_data['sender']}))
    if prompt == "2":
        user.language = "Shona"
        update_user_state(user_data['sender'], {
            'step': 'main_menu2',
            'user': user.to_dict()
        })
        send(
            "Tatenda!\n"
            "Tinokubatsirai sei nhasi?\n\n"
            "1. Kukumbira quotation\n"
            "2. Bhuka Site Visit\n"
            "3. Tarisa Project Status\n"
            "4. Dzidza nezve Kuchera chibhorani\n"
            "5. Taura neMunhu\n\n"
            "Pindura nenhamba (semuenzaniso, 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota pindura ne2 kuti urambe uchishandisa chiShona.", user_data['sender'], phone_id)
        return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}
        


def handle_main_menu2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Kukumbira quotation
        update_user_state(user_data['sender'], {
            'step': 'select_service2',
            'user': user.to_dict()
        })
        send(
            "Tatenda!\n"
            "Sarudza sevhisi yaunoda:\n"
            "1. Kuongorora mvura\n"
            "2. Kuchera chibhorani\n"
            "3. Kuisa pombi yechibhorani\n"
            "4. Kuvaka chibhorani chebhizimusi\n"
            "5. Kudzikisa chibhorani",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":  # Bhuka site visit
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info2',
            'user': user.to_dict()
        })
        send(
            "Kubhuka site visit, ndapota ipa zvinotevera:\n"
            "- Zita rizere:\n"
            "- Zuva raunoda (dd/mm/yyyy):\n"
            "- Kero yesaiti:\n"
            "- Nhamba yefoni:\n"
            "- Nzira yekubhadhara (Prepayment / Cash paSaiti):\n\n"
            "Nyora 'Submit' kuti usimbise booking.",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Tarisa Project Status
        send("Chikamu ichi chichauya munguva pfupi. Bata agent yenyu kuti muwane mamiriro epurojekiti.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":  # Dzidza nezve Kuchera chibhorani
        send(
            "Tinopa:\n"
            "- Kuchera chibhorani\n"
            "- Kuisa pombi yechibhorani\n"
            "- Kuvaka pond nemadhamu eWeir\n"
            "Bata isu kuti uwane ruzivo rwakadzama!", user_data['sender'], phone_id
        )
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "5":  # Taura neMunhu
        send("Tiri kukubatanidza neagent chaiye...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sarudzo iri pakati pa1-5.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_select_service2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    services = {
        "1": "Kuchera chibhorani",
        "2": "Kuisa pombi yechibhorani",
        "3": "Kuvaka pond yemvura",
        "4": "Kuvaka weir dam"
    }
    if prompt in services:
        user.quote_data['service'] = services[prompt]
        update_user_state(user_data['sender'], {
            'step': 'collect_quote_details2',
            'user': user.to_dict()
        })
        send(
            "Kuti ndikupai fungidziro inokurumidza, ndiudzei nzvimbo yenyu (Guta/Kumba kana GPS)\n"
            user_data['sender'], phone_id
        )
        return {'step': 'collect_quote_details2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sevhisi pakati pa1-4.", user_data['sender'], phone_id)
        return {'step': 'select_service2', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_quote_details2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    responses = prompt.split('\n')
    if len(responses) >= 4:
        user.quote_data.update({
            'location': responses[0].strip(),
            'depth': responses[1].strip(),
            'purpose': responses[2].strip(),
            'water_survey': responses[3].strip(),
            'casing_type': responses[5].strip() if len(responses) > 5 else "Hazvataurwa"
        })
        quote_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        user.quote_data['quote_id'] = quote_id
        # Save quote to Redis (simulate DB)
        redis.set(f"quote:{quote_id}", json.dumps({
            'quote_id': quote_id,
            'user_data': user.to_dict(),
            'timestamp': datetime.now().isoformat(),
            'status': 'pending'
        }))
        update_user_state(user_data['sender'], {
            'step': 'quote_response2',
            'user': user.to_dict()
        })
        estimate = "Class 6: Mutengo Unofungidzirwa: $2500\nZvinobatanidza kuchera, PVC casing 140mm"
        send(
            f"Tatenda! Zvichienderana nezvamakapa:\n\n"
            f"{estimate}\n\n"
            f"Ziva: Double casing inobhadharwa semari yekuwedzera kana zvichidikanwa uye pakubvumirana nemutengi\n\n"
            f"Mungada:\n"
            f"1. Kupa mutengo wenyu?\n"
            f"2. Bhuka Site Survey\n"
            f"3. Bhuka Kuchera\n"
            f"4. Taura ne Munhu",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_response2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota ipa ruzivo rwese rwakumbirwa (kanokwana 4 lines).", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details2', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_quote_response2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details2',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Nyorai mutengo wenyu muchitevedza fomati:\n\n"
            "- Water Survey: $_\n"
            "- Kuchera chibhorani: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info2',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Ipa ruzivo urwu kuti booking yako ipedzwe:\n\n"
            "- Zita rizere:\n"
            "- Zuva raunoda (dd/mm/yyyy):\n"
            "- Kero yesaiti kana GPS\n"
            "- Nhamba yefoni:\n"
            "- Nzira yekubhadhara (Prepayment / Cash paSaiti):\n\n"
            "Nyora: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("Agent wedu achakubata kubvumirana kuchera.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":
        send("Tiri kukubatanidza neagent chaiye...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sarudzo pakati pa1-4.", user_data['sender'], phone_id)
        return {'step': 'quote_response2', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_offer_details2(prompt, user_data, phone_id):
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
        'step': 'offer_response2',
        'user': user.to_dict()
    })
    send(
        "Chikumbiro chako chatumirwa kune maneja wedu. Tichakupindura muawa rimwe.\n\n"
        "Tatenda nemutengo wawakapa!\n\n"
        "Chikwata chedu chichachiongorora nokukupindura.\n\n"
        "Sevhisi yedu inotora mutengo wakakodzera, mhando, uye kuchengetedzeka.\n\n"
        "Mungada:\n"
        "1. Kupfuurira kana mutengo wabvumirwa\n"
        "2. Taura neMunhu\n"
        "3. Chinja mutengo",
        user_data['sender'], phone_id
    )
    return {'step': 'offer_response2', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_offer_response2(prompt, user_data, phone_id):
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
            'step': 'booking_details2',
            'user': user.to_dict()
        })
        send(
            "Nhau dzakanaka! Mutengo wawakapa wabvumirwa.\n\n"
            "Chikamu chinotevera ndechekusimbisa:\n\n"
            "1. Bhuka Site Survey\n"
            "2. Bhadhara deposit\n"
            "3. Simbisa zuva rekuchera",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_details2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Tiri kukubatanidza neagent chaiye...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details2',
            'user': user.to_dict()
        })
        send(
            "Nyorai zvakare mutengo wenyu muchitevedza fomati:\n\n"
            "- Water Survey: $_\n"
            "- Kuchera chibhorani: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sarudzo pakati pa1-3.", user_data['sender'], phone_id)
        return {'step': 'offer_response2', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_details2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info2',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Ipa ruzivo urwu kuti booking yako ipedzwe:\n\n"
            "- Zita rizere:\n"
            "- Zuva raunoda (dd/mm/yyyy):\n"
            "- Kero yesaiti kana GPS\n"
            "- Nhamba yefoni:\n"
            "- Nzira yekubhadhara (Prepayment / Cash paSaiti):\n\n"
            "Nyora: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Bata hofisi yedu pa 077xxxxxxx kuti muronge kubhadhara deposit.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("Agent wedu achakubata kusimbisa zuva rekuchera.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza pakati pa1-3.", user_data['sender'], phone_id)
        return {'step': 'booking_details2', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_booking_info2(prompt, user_data, phone_id):
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
            'step': 'booking_confirmation2',
            'user': user.to_dict()
        })
        booking_date = "25/05/2025"
        booking_time = "10:00 AM"
        send(
            "Tatenda. Bhuku rako ratambirwa, technician achakufonera munguva pfupi.\n\n"
            f"Chiyeuchidzo: Site survey yako yakarongwa mangwana.\n\n"
            f"Zuva: {booking_date}\n"
            f"Nguva: {booking_time}\n\n"
            "Tinotarisira kushanda nemi!\n"
            "Unoda kuchinja here? Pindura\n\n"
            "1. Ehe\n"
            "2. Kwete",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_confirmation2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota nyora 'Submit' kuti usimbise booking yako.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info2', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_confirmation2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "2":
        send(
            "Zvakanaka! Bhuku rako rekuchera chibhorani raitwa.\n\n"
            "Zuva: China, 23 Chivabvu 2025\n"
            "Nguva: 8:00 AM\n"
            "Inotora: 5hrs\n"
            "Chikwata: 4-5 Matekiniki\n\n"
            "Iva nechokwadi chekuti nzvimbo inowanikwa.",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Bata support yedu kuti uchinje zuva.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation2', 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_select_language3(prompt, user_data, phone_id):
    user = User.from_dict(user_data.get('user', {'phone_number': user_data['sender']}))
    if prompt == "3":
        user.language = "Ndebele"
        update_user_state(user_data['sender'], {
            'step': 'main_menu3',
            'user': user.to_dict()
        })
        send(
            "Siyabonga!\n"
            "Singakusiza njani lamuhla?\n\n"
            "1. Cela ikhotheshini\n"
            "2. Bhuka Uvakatjho Lwendawo\n"
            "3. Hlola Isimo Sephrojekthi\n"
            "4. Funda Ngokucubungula Amanzi\n"
            "5. Khuluma Lomuntu\n\n"
            "Phendula ngenombolo (umzekeliso: 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela uphendule ngo-1 ukuqhubeka ngesiNdebele.", user_data['sender'], phone_id)
        return {'step': 'select_language3', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_main_menu3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'select_service3',
            'user': user.to_dict()
        })
        send(
            "Siyabonga!\n"
            "Khetha insiza oyidingayo:\n"
            "1. Ukuhlolwa kwamanzi\n"
            "2. Ukugwanywa komthombo\n"
            "3. Ukufakelwa kwepompo\n"
            "4. Ukugwanywa kwemithombo yezentengiso\n"
            "5. Ukwembelwa kwakhona umthombo (ukujiya)",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info3',
            'user': user.to_dict()
        })
        send(
            "Ukuze ubhuke uvakatjho, sicela unikeze okulandelayo:\n"
            "- Igama eliphelele:\n"
            "- Usuku olufisayo (dd/mm/yyyy):\n"
            "- Ikheli lendawo:\n"
            "- Inombolo yocingo:\n"
            "- Indlela yokukhokha (Prepayment / Imali endaweni):\n\n"
            "Bhala 'Submit' ukuqinisekisa ukubhuka.",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("Lesi sici sizafika maduzane. Xhumana ne-agent yakho ukuthola isimo sephrojekthi.", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":
        send(
            "Sinikeza:\n"
            "- Ukucubungula amanzi\n"
            "- Ukufakwa kwepompi yeborehole\n"
            "- Ukwakhiwa kwepond kanye leweir dam\n"
            "Xhumana nathi ukuthola ulwazi oluthe xaxa!", user_data['sender'], phone_id
        )
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "5":
        send("Sizakuxhumanisa lomuntu okwamanje...", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ukhethe inketho phakathi kuka-1-5.", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_select_service3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    services = {
        "1": "Ukucubungula amanzi",
        "2": "Ukufakwa kwepompi yeborehole",
        "3": "Ukwakhiwa kwepond yamanzi",
        "4": "Ukwakhiwa kweweir dam"
    }
    if prompt in services:
        user.quote_data['service'] = services[prompt]
        update_user_state(user_data['sender'], {
            'step': 'collect_quote_details3',
            'user': user.to_dict()
        })
        send(
            "Ukukwenzela isilinganiso esisheshayo, ngicela ungitshele indawo yakho (City/Town noma GPS)\n"
            user_data['sender'], phone_id
        )
        return {'step': 'collect_quote_details3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ukhethe insiza phakathi kuka-1-4.", user_data['sender'], phone_id)
        return {'step': 'select_service3', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_quote_details3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    responses = prompt.split('\n')
    if len(responses) >= 4:
        user.quote_data.update({
            'location': responses[0].strip(),
            'depth': responses[1].strip(),
            'purpose': responses[2].strip(),
            'water_survey': responses[3].strip(),
            'casing_type': responses[5].strip() if len(responses) > 5 else "Akutshiwanga"
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
            'step': 'quote_response3',
            'user': user.to_dict()
        })
        estimate = "Class 6: Inani elilinganisiwe: $2500\nKufaka ukucubungula, PVC casing 140mm"
        send(
            f"Siyabonga! Ngokusekelwe kulwazi olunikiweyo:\n\n"
            f"{estimate}\n\n"
            f"Qaphela: Izindleko ze-double casing zikhokhelwa njengenani elengezelelweyo uma kudingeka, ngemvumo yeklayenti\n\n"
            f"Ungathanda:\n"
            f"1. Ukunikeza inani lakho?\n"
            f"2. Bhuka iSite Survey\n"
            f"3. Bhuka Ukucubungula\n"
            f"4. Khuluma lomuntu",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_response3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela unikeze lonke ulwazi oluceliwe (okungenani imigqa emi-4).", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details3', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_quote_response3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details3',
            'user': user.to_dict()
        })
        send(
            "Kulungile! Bhala inani lakho ngendlela elandelayo:\n\n"
            "- Ucwaningo lwamanzi: $_\n"
            "- Ukucubungula amanzi: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info3',
            'user': user.to_dict()
        })
        send(
            "Kulungile! Nikeza ulwazi olulandelayo ukuqedela ukubhuka:\n\n"
            "- Igama eliphelele:\n"
            "- Usuku olufisayo (dd/mm/yyyy):\n"
            "- Ikheli lendawo noma GPS\n"
            "- Inombolo yocingo:\n"
            "- Indlela yokukhokha (Prepayment / Imali endaweni):\n\n"
            "Bhala: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("I-agent yethu izokuthinta ukuqedela ukubhuka kokucubungula.", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":
        send("Sizakuxhumanisa lomuntu okwamanje...", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ukhethe inketho phakathi kuka-1-4.", user_data['sender'], phone_id)
        return {'step': 'quote_response3', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_offer_details3(prompt, user_data, phone_id):
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
        'step': 'offer_response3',
        'user': user.to_dict()
    })
    send(
        "Isicelo sakho sithunyelwe kumphathi wethu wezokuthengisa. Sizakuphendula kungakapheli ihora.\n\n"
        "Siyabonga ngenani lakho!\n\n"
        "Iqembu lethu lizalihlola likuphendule maduze.\n\n"
        "Amanani ethu asekelwe kwikhwalithi, ukuphepha, lokwethembeka.\n\n"
        "Ungathanda:\n"
        "1. Qhubeka uma inani lamukelwe\n"
        "2. Khuluma lomuntu\n"
        "3. Lungisa inani lakho",
        user_data['sender'], phone_id
    )
    return {'step': 'offer_response3', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_offer_response3(prompt, user_data, phone_id):
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
            'step': 'booking_details3',
            'user': user.to_dict()
        })
        send(
            "Izindaba ezinhle! Inani lakho lamukelwe.\n\n"
            "Ake siqinisekise okuzolandela:\n\n"
            "1. Bhuka iSite Survey\n"
            "2. Khokha idiphozithi\n"
            "3. Qinisekisa usuku lokucubungula",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_details3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Sizakuxhumanisa lomuntu okwamanje...", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details3',
            'user': user.to_dict()
        })
        send(
            "Bhala kabusha inani lakho ngendlela elandelayo:\n\n"
            "- Ucwaningo lwamanzi: $_\n"
            "- Ukucubungula amanzi: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela uphendule phakathi kuka-1-3.", user_data['sender'], phone_id)
        return {'step': 'offer_response3', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_details3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info3',
            'user': user.to_dict()
        })
        send(
            "Kulungile! Nikeza ulwazi oludingekayo ukuqedela ukubhuka:\n\n"
            "- Igama eliphelele:\n"
            "- Usuku olufisayo (dd/mm/yyyy):\n"
            "- Ikheli lendawo noma GPS\n"
            "- Inombolo yocingo:\n"
            "- Indlela yokukhokha (Prepayment / Imali endaweni):\n\n"
            "Bhala: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Xhumana lehhovisi lethu ku-077xxxxxxx ukuze ukhokhe idiphozithi.", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("I-agent yethu izakuthinta ukuqinisekisa usuku lokucubungula.", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ukhethe phakathi kuka-1-3.", user_data['sender'], phone_id)
        return {'step': 'booking_details3', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_booking_info3(prompt, user_data, phone_id):
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
            'step': 'booking_confirmation3',
            'user': user.to_dict()
        })
        booking_date = "25/05/2025"
        booking_time = "10:00 AM"
        send(
            "Siyabonga. Ukubhuka kwakho kugunyaziwe, uchwepheshe uzokuthinta maduze.\n\n"
            f"Isikhumbuzo: Ukuhlolwa kwendawo kuhlelwe kusasa.\n\n"
            f"Usuku: {booking_date}\n"
            f"Isikhathi: {booking_time}\n\n"
            "Sibheke phambili ukusebenza lawe!\n"
            "Udinga ukuhlela kabusha? Phendula\n\n"
            "1. Yebo\n"
            "2. Cha",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_confirmation3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Bhala 'Submit' ukuqinisekisa ukubhuka kwakho.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info3', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_confirmation3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "2":
        send(
            "Kuhle! Ukubhuka kwakho kokucubungula amanzi sekulungisiwe.\n\n"
            "Usuku: ULwesine, 23 May 2025\n"
            "Isikhathi: 8:00 AM\n"
            "Kulindeleke kuthathe: amahora ama-5\n"
            "Iqembu: 4-5 Ochwepheshe\n\n"
            "Qinisekisa ukuthi indawo iyatholakala.",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Xhumana nethimba lethu ukuze uhlele kabusha usuku.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation3', 'user': user.to_dict(), 'sender': user_data['sender']}
        

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
    "booking_confirmation": handle_booking_confirmation,
    "human_agent": lambda prompt, user_data, phone_id: (
        send("A human agent will contact you soon.", user_data['sender'], phone_id)
        or {'step': 'main_menu', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
    ),
    "select_language2": handle_select_language2,
    "main_menu2": handle_main_menu2,
    "select_service2": handle_select_service2,
    "collect_quote_details2": handle_collect_quote_details2,
    "quote_response2": handle_quote_response2,
    "collect_offer_details2": handle_collect_offer_details2,
    "offer_response2": handle_offer_response2,
    "booking_details2": handle_booking_details2,
    "collect_booking_info2": handle_collect_booking_info2,
    "booking_confirmation2": handle_booking_confirmation2,
    "human_agent2": lambda prompt, user_data, phone_id: (
        send("Agent chaiye achakubata munguva pfupi.", user_data['sender'], phone_id)
        or {'step': 'main_menu', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
    ),
    "select_language3": handle_select_language3,
    "main_menu3": handle_main_menu3,
    "select_service3": handle_select_service3,
    "collect_quote_details3": handle_collect_quote_details3,
    "quote_response3": handle_quote_response3,
    "collect_offer_details3": handle_collect_offer_details3,
    "offer_response3": handle_offer_response3,
    "booking_details3": handle_booking_details3,
    "collect_booking_info3": handle_collect_booking_info3,
    "booking_confirmation3": handle_booking_confirmation3,
    "human_agent3": lambda prompt, user_data, phone_id: (
        send("Umuntu uzokuthinta maduze.", user_data['sender'], phone_id)
        or {'step': 'main_menu3', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
    ),
}

def get_action(current_state, prompt, user_data, phone_id):
    handler = action_mapping.get(current_state, handle_welcome)
    return handler(prompt, user_data, phone_id)

# Flask app
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
                    send("Please send a text message", sender, phone_id)
        except Exception as e:
            logging.error(f"Error processing webhook: {e}", exc_info=True)
        return jsonify({"status": "ok"}), 200

def message_handler(prompt, sender, phone_id):
    user_state = get_user_state(sender)
    user_state['sender'] = sender
    # Ensure we always run the handler for the current step
    next_state = get_action(user_state['step'], prompt, user_state, phone_id)
    update_user_state(sender, next_state)

if __name__ == "__main__":
    app.run(debug=True, port=8000)

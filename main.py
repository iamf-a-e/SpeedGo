import os
import json
import logging
import requests
import random
import string
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from upstash_redis import Redis
import google.generativeai as genai
import threading
import time

logging.basicConfig(level=logging.INFO)

# Environment variables
wa_token = os.environ.get("WA_TOKEN")
phone_id = os.environ.get("PHONE_ID")
gen_api = os.environ.get("GEN_API")
owner_phone = os.environ.get("OWNER_PHONE")
GOOGLE_MAPS_API_KEY = "AlzaSyCXDMMhg7FzP|ElKmrlkv1TqtD3HgHwW50"
AGENT_NUMBER = "+263719835124"
AGENT_INITIAL_STATE = "agent_available"

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

def reverse_geocode_location(gps_coords):
    """
    Converts GPS coordinates (latitude,longitude) to a city using local logic first,
    then Google Maps API if not matched.
    """
    if not gps_coords or ',' not in gps_coords:
        return None

    try:
        lat_str, lng_str = gps_coords.strip().split(',')
        lat = float(lat_str.strip())
        lng = float(lng_str.strip())
    except ValueError:
        return None

    # Local fallback mapping
    
    if -22.27 < lat < -22.16 and 29.94 < lng < 30.06:
        return "Beitbridge Town"
    elif -20.06 < lat < -19.95 and 31.54 < lng < 31.65:
        return "Nyika Growth Point"
    elif -17.36 < lat < -17.25 and 31.28 < lng < 31.39:
        return "Bindura Town"
    elif -17.68 < lat < -17.57 and 27.29 < lng < 27.40:
        return "Binga Town"
    elif -19.58 < lat < -19.47 and 28.62 < lng < 28.73:
        return "Bubi Town/Centre"
    elif -19.33 < lat < -19.22 and 31.59 < lng < 31.70:
        return "Murambinda Town"
    elif -19.39 < lat < -19.28 and 31.38 < lng < 31.49:
        return "Buhera"
    elif -20.20 < lat < -20.09 and 28.51 < lng < 28.62:
        return "Bulawayo City/Town"
    elif -19.691 < lat < -19.590 and 31.103 < lng < 31.204:
        return "Gutu"
    elif -20.99 < lat < -20.88 and 28.95 < lng < 29.06:
        return "Gwanda"
    elif -19.50 < lat < -19.39 and 29.76 < lng < 29.87:
        return "Gweru"
    elif -17.88 < lat < -17.77 and 31.00 < lng < 31.11:
        return "Harare"

    # If not found locally, use Google Maps API
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lng}&key={GOOGLE_MAPS_API_KEY}"

    try:
        response = requests.get(url)
        data = response.json()

        if data['status'] != 'OK':
            return None

        for result in data['results']:
            for component in result['address_components']:
                if 'locality' in component['types'] or 'administrative_area_level_1' in component['types']:
                    return component['long_name'].lower()

        return data['results'][0]['formatted_address'].lower()

    except Exception as e:
        print("Geocoding error:", e)
        return None

# Pricing dictionaries
location_pricing = {
    "beitbridge": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 27           
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "nyika": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1050,
            "class 9": 1181.25,
            "class 10": 1312.5,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "bindura": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "binga": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1300,
            "class 9": 1462.5,
            "class 10": 1625,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "bubi": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1200,
            "class 9": 1350,
            "class 10": 1500,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "murambinda": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1050,
            "class 9": 1181.25,
            "class 10": 1312.5,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "buhera": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1150,
            "class 9": 1293.75,
            "class 10": 1437.5,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "harare": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250
        },       
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "bulawayo": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    }
}

pump_installation_options = {
    "1": {
        "description": "D.C solar (direct solar NO inverter) - I have tank and tank stand",
        "price": 1640
    },
    "2": {
        "description": "D.C solar (direct solar NO inverter) - I don't have anything",
        "price": 2550
    },
    "3": {
        "description": "D.C solar (direct solar NO inverter) - Labour only",
        "price": 200
    },
    "4": {
        "description": "A.C electric (ZESA or solar inverter) - Fix and supply",
        "price": 1900
    },
    "5": {
        "description": "A.C electric (ZESA or solar inverter) - Labour only",
        "price": 170
    },
    "6": {
        "description": "A.C electric (ZESA or solar inverter) - I have tank and tank stand",
        "price": 950
    }
}

def get_pricing_for_location_quotes(location, service_type, pump_option_selected=None):
    location_key = location.strip().lower()
    service_key = service_type.strip().title()  # Normalize e.g. "Pump Installation"

    # Handle Pump Installation separately
    if service_key == "Pump Installation":
        if pump_option_selected is None:            
            message_lines = [f"💧 Pump Installation Options:\n"]
            for key, option in pump_installation_options.items():
                desc = option.get('description', 'No description')
                message_lines.append(f"{key}. {desc}")
            return "\n".join(message_lines)
        else:
            option = pump_installation_options.get(pump_option_selected)
            if not option:
                return "Sorry, invalid Pump Installation option selected."
            desc = option.get('description', 'No description')
            price = option.get('price', 'N/A')
            message = f"💧 Pricing for option {pump_option_selected}:\n{desc}\nPrice: ${price}\n"
            message += "\nWould you like to:\n1. Ask pricing for another service\n2. Return to Main Menu\n3. Offer Price"
            return message

    # Rest of the function remains the same...
    loc_data = location_pricing.get(location_key)
    if not loc_data:
        return "Sorry, pricing not available for this location."

    price = loc_data.get(service_key)
    if not price:
        return f"Sorry, pricing for {service_key} not found in {location.title()}."

    # Format complex pricing dicts nicely
    if isinstance(price, dict):
        included_depth = price.get("included_depth_m", "N/A")
        extra_rate = price.get("extra_per_m", "N/A")

        classes = {k: v for k, v in price.items() if k.startswith("class")}
        message_lines = [f"{service_key} Pricing in {location.title()}:"]
        for cls, amt in classes.items():
            message_lines.append(f"- {cls.title()}: ${amt}")
        message_lines.append("Would you like to:\n1. Ask pricing for another service\n2. Return to Main Menu\n3. Offer Price\n4. Select Borehole Class")
        return "\n".join(message_lines)

    # Flat rate or per meter pricing
    unit = "per meter" if service_key in ["Commercial Hole Drilling", "Borehole Deepening"] else "flat rate"
    return (f"{service_key} in {location.title()}: ${price} {unit}\n\n"
            "Would you like to:\n1. Ask pricing for another service\n2. Return to Main Menu\n3. Offer Price")


# State handlers
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
            'step': 'enter_location_for_quote',
            'user': user.to_dict()
        })
        send("please enter your location (City/Town or GPS coordinates) to get started.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Search Price Using Location
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote',
            'user': user.to_dict()
        })
        send(
           "To get you pricing, please enter your location (City/Town or GPS coordinates):",
            user_data['sender'], phone_id
        )
        return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Check Project Status
        update_user_state(user_data['sender'], {
            'step': 'check_project_status_menu',
            'user': user.to_dict()
        })
        send(
            "Please choose an option:\n"
            "1. Check status of borehole drilling\n"
            "2. Check status of pump installation\n"
            "3. Speak to a human agent\n"
            "4. Main Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'check_project_status_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        update_user_state(user_data['sender'], {
            'step': 'faq_menu',
            'user': user.to_dict()
        })
        send(
            "Please choose an FAQ category:\n\n"
            "1. Borehole Drilling FAQs\n"
            "2. Pump Installation FAQs\n"
            "3. Ask a different question\n"
            "4. Speak to a human agent\n"
            "5. Main Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Other Services
        update_user_state(user_data['sender'], {
            'step': 'other_services_menu',
            'user': user.to_dict()
        })
        send(
            "Welcome to Other Borehole Services. What service do you need?\n"
            "1. Borehole Deepening\n"
            "2. Borehole Flushing\n"
            "3. PVC Casing Pipe Selection\n"
            "4. Back to Main Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'other_services_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
        
    elif prompt == "6":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent',
            'user': user.to_dict(),
            'original_prompt': prompt  # Store the original message
        })
        # Immediately call the human_agent handler
        return human_agent(prompt, {
            'step': 'human_agent',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }, phone_id)
    
    else:
        send("Please select a valid option (1-6).", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}



def human_agent(prompt, user_data, phone_id):
    customer_number = user_data['sender']

    # 1. Notify customer
    send("Connecting you to a human agent...", customer_number, phone_id)

    # 2. Notify agent with clear options
    agent_message = (
        f"👋 New customer request on WhatsApp\n\n"
        f"📱 Customer: {customer_number}\n"
        f"📩 Message: \"{prompt}\"\n\n"
        f"Reply with:\n"
        f"1 - Take over conversation (customer messages will come to you)\n"
        f"2 - Let bot handle it (customer returns to main menu)"
    )
    send(agent_message, AGENT_NUMBER, phone_id)
    
    # Initialize agent state
    update_user_state(AGENT_NUMBER, {
        'step': 'agent_reply',
        'customer_number': customer_number,
        'phone_id': phone_id,
        'original_message': prompt
    }, ttl_seconds=3600)  # Longer TTL for agent conversations

    # Update customer's state (waiting for agent)
    update_user_state(customer_number, {
        'step': 'waiting_for_human_agent_response',
        'user': user_data.get('user', {}),
        'sender': customer_number,
        'waiting_since': time.time()
    }, ttl_seconds=3600)

    # 3. Schedule fallback
    def send_fallback():
        user_data = get_user_state(customer_number)
        if user_data and user_data.get('step') == 'waiting_for_human_agent_response':
            send("If you haven't been contacted yet, you can call us directly at +263719835124", customer_number, phone_id)
            send("Would you like to:\n1. Return to main menu\n2. Keep waiting", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'human_agent_followup',
                'user': user_data.get('user', {}),
                'sender': customer_number
            })

    threading.Timer(120, send_fallback).start()  # Increased to 2 minutes

    return {
        'step': 'waiting_for_human_agent_response',
        'user': user_data.get('user', {}),
        'sender': customer_number
    }

# Enhanced agent message handling
def handle_agent_message(prompt, sender, phone_id, message):
    """
    Handles all messages coming from the agent number.
    """
    agent_state = get_user_state(sender) or {'step': AGENT_INITIAL_STATE}
    current_step = agent_state.get('step', AGENT_INITIAL_STATE)
    
    logging.info(f"Agent message received. Current state: {current_step}, Message: {message}")
    
    # Get text content regardless of message type
    if isinstance(message, dict) and message.get('type') == 'text':
        prompt = message.get('text', {}).get('body', '').strip()
    elif isinstance(prompt, str):
        prompt = prompt.strip()
    else:
        prompt = ""

    # Dispatch to appropriate handler
    if current_step == 'agent_reply':
        return handle_agent_reply(prompt, sender, phone_id, message, agent_state)
    elif current_step == 'talking_to_customer':
        return handle_agent_conversation(prompt, sender, phone_id, message, agent_state)
    else:
        return handle_agent_available(prompt, sender, phone_id, message, agent_state)

# Improved agent reply handler
def handle_agent_reply(prompt, sender, phone_id, message, agent_state):
    """Handles agent's initial response to customer request"""
    customer_number = agent_state.get('customer_number')
    
    if not customer_number:
        send("⚠️ Error: No customer assigned. Please wait for a new request.", sender, phone_id)
        return {'step': 'agent_available'}
    
    if prompt == '1':  # Accept conversation
        # Notify both parties
        send("✅ You're now connected to the customer. Send '2' at any time to return the customer to the bot.", 
             sender, phone_id)
        send("✅ You are now connected to a human agent. Please ask your question.", customer_number, phone_id)
        
        # Update states
        update_user_state(customer_number, {
            'step': 'talking_to_human_agent',
            'user': get_user_state(customer_number).get('user', {}),
            'sender': customer_number,
            'agent_number': sender
        }, ttl_seconds=3600)
        
        update_user_state(sender, {
            'step': 'talking_to_customer',
            'customer_number': customer_number,
            'phone_id': phone_id,
            'started_at': time.time()
        }, ttl_seconds=3600)
        
        return {
            'step': 'talking_to_customer',
            'customer_number': customer_number,
            'phone_id': phone_id,
            'started_at': time.time()
        }
        
    elif prompt == '2':  # Decline conversation
        send("✅ You've returned the customer to the bot.", sender, phone_id)
        send("👋 You're now back with our automated assistant.", customer_number, phone_id)
        
        update_user_state(customer_number, {
            'step': 'main_menu',
            'user': get_user_state(customer_number).get('user', {}),
            'sender': customer_number
        })
        update_user_state(sender, {'step': 'agent_available'})
        show_main_menu(customer_number, phone_id)
        
    else:
        send("⚠️ Please reply with:\n1 - Talk to customer\n2 - Back to bot", sender, phone_id)
        return agent_state  # Maintain current state

# Enhanced agent conversation handler
def handle_agent_conversation(prompt, sender, phone_id, message, agent_state):
    """Handles ongoing conversation between agent and customer"""
    customer_number = agent_state.get('customer_number')
    
    if prompt.strip().lower() == '2':  # End conversation
        send("✅ Conversation ended. The bot will take over.", sender, phone_id)
        send("👋 The agent has ended the conversation. You're back with our automated assistant.", 
             customer_number, phone_id)
        
        update_user_state(customer_number, {
            'step': 'main_menu',
            'user': get_user_state(customer_number).get('user', {}),
            'sender': customer_number
        })
        update_user_state(sender, {'step': 'agent_available'})
        show_main_menu(customer_number, phone_id)
        return {'step': 'agent_available'}
    else:
        # Forward message to customer
        forward_agent_message(prompt, message, customer_number, phone_id)
        return agent_state  # Maintain current state

def handle_agent_available(prompt, sender, phone_id, message, agent_state):
    """Handles agent when not in active conversation"""
    send("ℹ️ You're currently available. You'll be notified when a customer needs assistance.", sender, phone_id)
    return {'step': 'agent_available'}

def forward_agent_message(prompt, message, customer_number, phone_id):
    """Forwards different message types from agent to customer"""
    if not customer_number:
        return
        
    if isinstance(message, dict):
        if message.get("type") == "text":
            send(f"Agent: {message.get('text', {}).get('body', '')}", customer_number, phone_id)
        elif message.get("type") == "image":
            caption = f"Agent: {message.get('caption', '')}" if message.get('caption') else "From agent:"
            send_image(message.get('url'), caption, customer_number, phone_id)
        elif message.get("type") == "location":
            send_location(
                message.get('location', {}).get('latitude'),
                message.get('location', {}).get('longitude'),
                "Agent shared location",
                customer_number,
                phone_id
            )
    else:
        send(f"Agent: {prompt}", customer_number, phone_id)

# Add this helper function (you'll need to implement send_image and send_location)
def send_image(image_url, caption, recipient, phone_id):
    """Sends an image message"""
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {
        'Authorization': f'Bearer {wa_token}',
        'Content-Type': 'application/json'
    }
    data = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "image",
        "image": {
            "link": image_url,
            "caption": caption
        }
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send image: {e}")

def send_location(latitude, longitude, name, recipient, phone_id):
    """Sends a location message"""
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {
        'Authorization': f'Bearer {wa_token}',
        'Content-Type': 'application/json'
    }
    data = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "location",
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "name": name
        }
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send location: {e}")
        

def handle_customer_message_during_agent_chat(message, user_data, phone_id):
    customer_number = user_data['sender']
    
    # If still in agent chat, suppress bot actions
    if user_data.get('step') == 'talking_to_human_agent':
        send("💬 You're still connected to a human agent. Please wait for them to respond.", customer_number, phone_id)
        return True  # means the bot should not process further
    return False


def handle_user_message(prompt, user_data, phone_id):
    if user_data.get('step') == 'human_agent_followup':
        if prompt.strip() == '1':
            # Return to main menu
            update_user_state(user_data['sender'], {
                'step': 'main_menu',
                'user': user_data['user']
            })
            send_main_menu(user_data['sender'], phone_id)
        elif prompt.strip() == '2':
            # Continue waiting
            send("We'll keep trying to connect you. Thank you for your patience.", user_data['sender'], phone_id)
            update_user_state(user_data['sender'], {
                'step': 'waiting_for_human_agent_response',
                'user': user_data['user']
            })
        else:
            send("Please choose 1 or 2", user_data['sender'], phone_id)
    
    return user_data


def human_agent_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        return handle_select_language("1", user_data, phone_id)

    elif prompt == "2":
        send("Okay. Feel free to ask if you need anything else.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Please reply with 1 for Main Menu or 2 to stay here.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user']) 

    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole',
            'user': user.to_dict()
        })
        send(
            "Here are the most common questions about borehole drilling:\n\n"
            "1. How much does borehole drilling cost?\n"
            "2. How long does it take to drill a borehole?\n"
            "3. How deep will my borehole be?\n"
            "4. Do I need permission to drill a borehole?\n"
            "5. Do you do a water survey and drilling at the same time?\n"
            "6. What if you do a water survey and find no water?\n"
            "7. What equipment do you use?\n"
            "8. Back to FAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}


    elif prompt == "2":  # Pump Installation FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_pump',
            'user': user.to_dict()
        })
        send(
            "Here are common questions about pump installation:\n\n"
            "1. What’s the difference between solar and electric pumps?\n"
            "2. Can you install if I already have materials?\n"
            "3. How long does pump installation take?\n"
            "4. What pump size do I need?\n"
            "5. Do you supply tanks and tank stands?\n"
            "6. Back to FAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Ask a different question
        update_user_state(user_data['sender'], {
            'step': 'custom_question',
            'user': user.to_dict()
        })
        send(
            "Please type your question below, and we’ll do our best to assist you.\n",
            user_data['sender'], phone_id
        )
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent',
            'user': user.to_dict(),
            'sender': user_data['sender']
        })
        send("Please hold while I connect you to a representative…", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Back to Main Menu
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Please select a valid option (1–5).", user_data['sender'], phone_id)
        return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

def custom_question(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    # Validate that prompt is not empty
    if not prompt.strip():
        send("Please type your question.", user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Gemini prompt template
    system_prompt = (
        "You are a helpful assistant for SpeedGo, a borehole drilling and pump installation company in Zimbabwe. "
        "You will only answer questions related to SpeedGo's services, pricing, processes, or customer support. "
        "If the user's question is unrelated to SpeedGo, politely let them know that you can only assist with SpeedGo-related topics."
    )

    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content([system_prompt, prompt])

        answer = response.text.strip() if hasattr(response, "text") else "I'm sorry, I give you a response at the moment."

    except Exception as e:
        answer = "Sorry, something went wrong while processing your question. Please try again later."
        print(f"[Gemini error] {e}")

    send(answer, user_data['sender'], phone_id)

    # Follow up options
    send(
        "Would you like to:\n"
        "1. Ask another question\n"
        "2. Return to Main Menu",
        user_data['sender'], phone_id
    )

    return {'step': 'custom_question_followup', 'user': user.to_dict(), 'sender': user_data['sender']}


def custom_question_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send("Please type your next question.", user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Please reply 1 to ask another question or 2 to return to the main menu.", user_data['sender'], phone_id)
        return {'step': 'custom_question_followup', 'user': user.to_dict(), 'sender': user_data['sender']}



def faq_borehole(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "The cost depends on your location, depth, and soil conditions. Please send us your location and site access details for a personalized quote.",
        "2": "Typically 4–6 hours or up to several days, depending on site conditions, rock type, and accessibility.",
        "3": "Depth varies by area. The standard depth is around 40 meters, but boreholes can range from 40 to 150 meters depending on the underground water table.",
        "4": "In some areas, a water permit may be required. We can assist you with the application if necessary.",
        "5": "Yes, we offer both as a combined package or separately, depending on your preference.",
        "6": "If the client wishes to drill at a second point, we offer a discount.\n\nNote: Survey machines detect underground water-bearing fractures or convergence points of underground streams. However, they do not measure the volume or flow rate of water. Therefore, borehole drilling carries no 100% guarantee of hitting water, as the fractures could be dry, moist, or wet.",
        "7": "We use professional-grade rotary and percussion drilling rigs, GPS tools, and geological survey equipment.",
        "8": "Returning to FAQ Menu..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Would you like to:\n"
            "1. Ask another question from Borehole Drilling FAQs\n"
            "2. Return to Main Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Please choose a valid option (1–8).", user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_borehole_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send(
            "Please choose a question:\n\n"
            "1. How much does borehole drilling cost?\n"
            "2. How long does it take to drill a borehole?\n"
            "3. How deep will my borehole be?\n"
            "4. Do I need permission to drill a borehole?\n"
            "5. Do you do a water survey and drilling at the same time?\n"
            "6. What if you do a water survey and find no water?\n"
            "7. What equipment do you use?\n"
            "8. Back to FAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Please choose 1 to ask another question or 2 to return to the main menu.", user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Solar pumps use energy from solar panels and are ideal for off-grid or remote areas. Electric pumps rely on the power grid and are typically more affordable upfront but depend on electricity availability.",
        "2": "Yes! We offer labor-only packages if you already have the necessary materials.",
        "3": "Installation usually takes one day, provided materials are ready and site access is clear.",
        "4": "Pump size depends on your water needs and borehole depth. We can assess your site and recommend the best option.",
        "5": "Yes, we supply complete packages including water tanks, tank stands, and all necessary plumbing fittings.",
        "6": "Returning to FAQ Menu..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)

        if prompt == "6":
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

        # ✅ After answering, show follow-up options
        send(
            "Would you like to:\n"
            "1. Ask another question from Pump Installation FAQs\n"
            "2. Return to Main Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Please choose a valid option (1–6).", user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send(
            "Please choose a question:\n\n"
            "1. What’s the difference between solar and electric pumps?\n"
            "2. Can you install if I already have materials?\n"
            "3. How long does pump installation take?\n"
            "4. What pump size do I need?\n"
            "5. Do you supply tanks and tank stands?\n"
            "6. Back to FAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Please choose 1 to ask another question or 2 to return to the main menu.", user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_enter_location_for_quote(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    # Check if we have a location object from WhatsApp
    if 'location' in user_data and 'latitude' in user_data['location'] and 'longitude' in user_data['location']:
        # This is a WhatsApp location message
        lat = user_data['location']['latitude']
        lng = user_data['location']['longitude']
        gps_coords = f"{lat},{lng}"
        location_name = reverse_geocode_location(gps_coords)
        
        if location_name:
            user.quote_data['location'] = location_name
            user.quote_data['gps_coords'] = gps_coords
            update_user_state(user_data['sender'], {
                'step': 'select_service_quote',
                'user': user.to_dict()
            })
            send(
                f"Location detected: {location_name.title()}\n\n"
                "Now select the service:\n"
                "1. Water survey\n"
                "2. Borehole drilling\n"
                "3. Pump installation\n"
                "4. Commercial hole drilling\n"
                "5. Borehole Deepening",
                user_data['sender'], phone_id
            )
            return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}
        else:
            send("We couldn't identify your location. Please type your city/town name manually.", user_data['sender'], phone_id)
            return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        # This is a text message with location name
        location_name = prompt.strip()
        user.quote_data['location'] = location_name.lower()
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote',
            'user': user.to_dict()
        })
        send(
            "Now select the service:\n"
            "1. Water survey\n"
            "2. Borehole drilling\n"
            "3. Pump installation\n"
            "4. Commercial hole drilling\n"
            "5. Borehole Deepening",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_select_service(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    services = {
        "1": "Water survey",
        "2": "Borehole drilling",
        "3": "Pump installation",
        "4": "Commercial hole drilling",
        "5": "Borehole Deepening",
    }
    if prompt in services:
        user.quote_data['service'] = services[prompt]
        update_user_state(user_data['sender'], {
            'step': 'collect_quote_details',
            'user': user.to_dict()
        })
        send(
            "To give you a quick estimate, please answer the following:\n\n"
            "1. Your location (City/Town or GPS):\n",            
            user_data['sender'], phone_id
        )
        return {'step': 'handle_select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}
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


def handle_select_service_quote(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if not location:
        send("Please provide your location first before selecting a service.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

    service_map = {
        "1": "Water Survey",
        "2": "Borehole Drilling",
        "3": "Pump Installation",
        "4": "Commercial Hole Drilling",
        "5": "Borehole Deepening"
    }

    selected_service = service_map.get(prompt.strip())

    if not selected_service:
        send("Invalid option. Please reply with 1, 2, 3, 4 or 5 to choose a service.", user_data['sender'], phone_id)
        return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Store selected service
    user.quote_data['service'] = selected_service

    # Handle Pump Installation separately as it has options
    if selected_service == "Pump Installation":
        update_user_state(user_data['sender'], {
            'step': 'select_pump_option',
            'user': user.to_dict()
        })
        message_lines = [f"💧 Pump Installation Options:\n"]
        for key, option in pump_installation_options.items():
            desc = option.get('description', 'No description')
            message_lines.append(f"{key}. {desc}")
        send("\n".join(message_lines), user_data['sender'], phone_id)
        return {'step': 'select_pump_option', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Get pricing for other services
    pricing_message = get_pricing_for_location_quotes(location, selected_service)
    
    # Ask if user wants to return to main menu or choose another service
    update_user_state(user_data['sender'], {
        'step': 'quote_followup',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'quote_followup',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_other_services_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Borehole Deepening casing question
        send(
            "To check if your borehole can be deepened:\n"
            "Was the borehole cased:\n"
            "1. Only at the top, with 180mm or larger diameter pipe\n"
            "2. Top to bottom with 140mm or smaller diameter pipe",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_deepening_casing', 'user': user.to_dict()})
        return {'step': 'borehole_deepening_casing', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        # Borehole Flushing problem type
        send(
            "What is the problem with your borehole?\n"
            "1. Collapsed Borehole\n"
            "2. Dirty Water Borehole",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_flushing_problem', 'user': user.to_dict()})
        return {'step': 'borehole_flushing_problem', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "3":
        # PVC casing class selection
        send(
            "We offer drilling boreholes following PVC casing pipe classes:\n"
            "1. Class 6 – Standard\n"
            "2. Class 9 – Stronger\n"
            "3. Class 10 – Strongest\n"
            "Which one would you like to check?",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'pvc_casing_selection', 'user': user.to_dict()})
        return {'step': 'pvc_casing_selection', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "4":
        # Back to main menu
        update_user_state(user_data['sender'], {'step': 'main_menu', 'user': user.to_dict()})
        send_main_menu(user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Please select a valid option (1-4).", user_data['sender'], phone_id)
        return {'step': 'other_services_menu', 'user': user.to_dict(), 'sender': user_data['sender']}


def send_main_menu(phone_number, phone_id):
    menu_text = (
        "How can we help you today?\n\n"
        "1. Request a quote\n"
        "2. Search Price Using Location\n"
        "3. Check Project Status\n"
        "4. FAQs or Learn About Borehole Drilling\n"
        "5. Other services\n"
        "6. Talk to a Human Agent\n\n"
        "Please reply with a number (e.g., 1)"
    )
    send(menu_text, phone_number, phone_id)
    

def handle_borehole_deepening_casing(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Only at top, qualifies for deepening
        send("Your borehole qualifies for deepening.\nPlease enter your location (town, ward, growth point, or GPS pin):",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'deepening_location', 'user': user.to_dict()})
        return {'step': 'deepening_location', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        # Top to bottom with smaller pipe - no deepening
        send(
            "Unfortunately, boreholes cased from top to bottom with pipes smaller than 180mm cannot be deepened.\n"
            "Options:\n"
            "1. Back to Other Services\n"
            "2. Talk to Support",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'deepening_no_deepening_options', 'user': user.to_dict()})
        return {'step': 'deepening_no_deepening_options', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Please select a valid option (1 or 2).", user_data['sender'], phone_id)
        return {'step': 'borehole_deepening_casing', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_no_deepening_options(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Back to Other Services menu
        return handle_other_services_menu("0", user_data, phone_id)  # or send menu prompt directly

    elif choice == "2":
        send("Connecting you to support...", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'human_agent', 'user': user.to_dict()})
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Please select a valid option (1 or 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_no_deepening_options', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_location(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()

    # Save location for deepening request
    user.quote_data['location'] = location

    # Fetch pricing from backend (you must implement this function)
    price = get_pricing_for_location_quotes(location, "borehole_deepening")

    send(
        f"Deepening cost in {location} starts from USD {price} per meter.\n"
        "Would you like to:\n"
        "1. Confirm & Book Job\n"
        "2. Back to Other Services",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'deepening_booking_confirm', 'user': user.to_dict()})
    return {'step': 'deepening_booking_confirm', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_booking_confirm(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Start booking details collection
        user.booking_data = {}
        send("Please provide your full name:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name', 'user': user.to_dict()})
        return {'step': 'booking_full_name', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        # Back to other services menu
        return other_services_menu("0", user_data, phone_id)

    else:
        send("Please select a valid option (1 or 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_booking_confirm', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_borehole_flushing_problem(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Collapsed Borehole
        send(
            "Do you know the borehole diameter?\n"
            "1. 180mm or larger\n"
            "2. Between 140mm and 180mm\n"
            "3. 140mm or smaller",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'flushing_collapsed_diameter', 'user': user.to_dict()})
        return {'step': 'flushing_collapsed_diameter', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        # Dirty Water Borehole
        send("Please enter your location to check the price:", user_data['sender'], phone_id)
        user.quote_data['flushing_type'] = 'dirty_water'
        update_user_state(user_data['sender'], {'step': 'flushing_location', 'user': user.to_dict()})
        return {'step': 'flushing_location', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Please select a valid option (1 or 2).", user_data['sender'], phone_id)
        return {'step': 'borehole_flushing_problem', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_flushing_collapsed_diameter(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()
    diameter_map = {
        "1": "180mm_or_larger",
        "2": "between_140_and_180mm",
        "3": "140mm_or_smaller"
    }

    diameter = diameter_map.get(choice)
    if not diameter:
        send("Please select a valid option (1-3).", user_data['sender'], phone_id)
        return {'step': 'flushing_collapsed_diameter', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['flushing_type'] = 'collapsed'
    user.quote_data['diameter'] = diameter

    if diameter == "180mm_or_larger":
        send("We can flush your borehole using rods with a drilling bit (more effective).\nPlease enter your location to check the price:",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'flushing_location', 'user': user.to_dict()})
        return {'step': 'flushing_location', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif diameter == "between_140_and_180mm":
        send("We can flush borehole with rods, no drilling bit.\nPlease enter your location to check the price:",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'flushing_location', 'user': user.to_dict()})
        return {'step': 'flushing_location', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif diameter == "140mm_or_smaller":
        send("We can flush the borehole using rods only (without drilling bit).\nPlease enter your location to check the price:",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'flushing_location', 'user': user.to_dict()})
        return {'step': 'flushing_location', 'user': user.to_dict(), 'sender': user_data['sender']}


def calculate_borehole_drilling_price(location, drilling_class, actual_depth_m):
    drilling_info = location_pricing[location]["Borehole Drilling"]
    base_price = drilling_info[drilling_class]
    included_depth = drilling_info["included_depth_m"]
    extra_per_m = drilling_info["extra_per_m"]

    if actual_depth_m <= included_depth:
        return base_price

    extra_depth = actual_depth_m - included_depth
    extra_cost = extra_depth * extra_per_m
    return base_price + extra_cost



def handle_flushing_location(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.quote_data['location'] = location

    flushing_type = user.quote_data.get('flushing_type')
    diameter = user.quote_data.get('diameter')  # could be None

    # Fetch price based on flushing_type and diameter
    price = get_pricing_for_other_services(location, "borehole_flushing", {
        'flushing_type': flushing_type,
        'diameter': diameter
    })

    send(
        f"Flushing cost in {location} starts from USD {price}.\n"
        "Would you like to:\n"
        "1. Confirm & Book Job\n"
        "2. Back to Other Services",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'flushing_booking_confirm', 'user': user.to_dict()})
    return {'step': 'flushing_booking_confirm', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_flushing_booking_confirm(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Please provide your full name:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name', 'user': user.to_dict()})
        return {'step': 'booking_full_name', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu("0", user_data, phone_id)

    else:
        send("Please select a valid option (1 or 2).", user_data['sender'], phone_id)
        return {'step': 'flushing_booking_confirm', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pvc_casing_selection(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()
    pvc_map = {
        "1": "Class 6 – Standard",
        "2": "Class 9 – Stronger",
        "3": "Class 10 – Strongest"
    }

    casing_class = pvc_map.get(choice)
    if not casing_class:
        send("Please select a valid option (1-3).", user_data['sender'], phone_id)
        return {'step': 'pvc_casing_selection', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['pvc_casing_class'] = casing_class

    send(f"The price for {casing_class} PVC casing depends on your location.\nPlease enter your location:",
         user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'pvc_casing_location', 'user': user.to_dict()})
    return {'step': 'pvc_casing_location', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pvc_casing_location(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.quote_data['location'] = location

    casing_class = user.quote_data.get('pvc_casing_class')

    price = get_pricing_for_other_services(location, "pvc_casing", {'class': casing_class})

    send(
        f"Price for {casing_class} PVC casing in {location} is USD {price}.\n"
        "Would you like to:\n"
        "1. Confirm & Book\n"
        "2. Back to Other Services",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'pvc_casing_booking_confirm', 'user': user.to_dict()})
    return {'step': 'pvc_casing_booking_confirm', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pvc_casing_booking_confirm(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Please provide your full name:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name', 'user': user.to_dict()})
        return {'step': 'booking_full_name', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu("0", user_data, phone_id)

    else:
        send("Please select a valid option (1 or 2).", user_data['sender'], phone_id)
        return {'step': 'pvc_casing_booking_confirm', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_full_name(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    full_name = prompt.strip()
    user.booking_data['full_name'] = full_name
    send("Please provide your phone number:", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_phone', 'user': user.to_dict()})
    return {'step': 'booking_phone', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_phone(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    phone = prompt.strip()
    user.booking_data['phone'] = phone
    send("Please enter your exact location/address or share your GPS pin:", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_location', 'user': user.to_dict()})
    return {'step': 'booking_location', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_location(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.booking_data['location'] = location
    send("Please enter your preferred booking date (e.g., 2024-10-15):", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_date', 'user': user.to_dict()})
    return {'step': 'booking_date', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_date(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    booking_date = prompt.strip()
    user.booking_data['date'] = booking_date
    send("If you have any notes or special requests, please enter them now. Otherwise, type 'No':", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_notes', 'user': user.to_dict()})
    return {'step': 'booking_notes', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_notes(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    notes = prompt.strip()
    user.booking_data['notes'] = notes if notes.lower() != 'no' else ''
    
    # At this point, save booking to database or call booking API
    booking_confirmation_number = save_booking(user.booking_data)  # You must implement save_booking

    send(
        f"Thank you {user.booking_data['full_name']}! Your booking is confirmed.\n"
        f"Booking Reference: {booking_confirmation_number}\n"
        "Our team will contact you soon.\n"
        "Type 'menu' to return to the main menu.",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'main_menu', 'user': user.to_dict()})
    return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pump_status_info_request(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        # 👇 Only send this error message if the user input is incomplete
        send(
            "Please provide at least your full name and reference number or phone number, each on a new line.\n\n"
            "Example:\n"
            "Jane Doe\nREF123456\nOptional: Harare",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    # Parse input
    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Not Provided"

    user.project_status_request = {
        'type': 'pump',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    # ✅ Proceed normally if input is valid
    send("Thank you. Please wait while we retrieve your project status...", user_data['sender'], phone_id)

    send(
        f"Here is your pump installation project status:\n\n"
        f"Project Name: Pump - {full_name}\n"
        f"Current Stage: Installation Completed\n"
        f"Next Step: Final Inspection\n"
        f"Estimated Hand-Over: 12/06/2025\n\n"
        "Would you like WhatsApp updates when your status changes?\nOptions: Yes / No",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'pump_status_updates_opt_in',
        'user': user.to_dict()
    })

    return {
        'step': 'pump_status_updates_opt_in',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_pump_status_updates_opt_in(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yes', 'y']:
        send(
            "Great! You'll now receive WhatsApp updates whenever your borehole drilling status changes.\n\n"
            "Thank you for using our service.",
            user_data['sender'], phone_id
        )
    elif response in ['no', 'n']:
        send(
            "No problem. You can always check the status again later if needed.\n\n"
            "Thank you for using our service.",
            user_data['sender'], phone_id
        )
    else:
        send("Sorry, I didn't understand that. Please reply with Yes or No.", user_data['sender'], phone_id)
        return {'step': 'pump_status_updates_opt_in', 'user': user.to_dict(), 'sender': user_data['sender']}

    # No further step – end the flow
    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_drilling_status_updates_opt_in(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yes', 'y']:
        send(
            "Great! You'll now receive WhatsApp updates whenever your borehole drilling status changes.\n\n"
            "Thank you for using our service.",
            user_data['sender'], phone_id
        )
    elif response in ['no', 'n']:
        send(
            "No problem. You can always check the status again later if needed.\n\n"
            "Thank you for using our service.",
            user_data['sender'], phone_id
        )
    else:
        send("Sorry, I didn't understand that. Please reply with Yes or No.", user_data['sender'], phone_id)
        return {'step': 'drilling_status_updates_opt_in', 'user': user.to_dict(), 'sender': user_data['sender']}

    # No further step – end the flow
    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_check_project_status_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'drilling_status_info_request',
            'user': user.to_dict()
        })
    
        send(
            "To check your borehole drilling status, please provide the following:\n\n"
            "- Full Name used during booking\n"
            "- Project Reference Number or Phone Number\n"
            "- Drilling Site Location (optional)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'pump_status_info_request',
            'user': user.to_dict()
        })
        send(
            "To check your pump installation status, please provide the following:\n\n"
            "- Full Name used during booking\n"
            "- Project Reference Number or Phone Number\n"
            "- Installation Site Location (optional)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }


    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'human_agent',
            'user': user.to_dict()
        })
        send("Please hold while I connect you to one of our support team members.", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        return handle_main_menu("", user_data, phone_id)

    else:
        send("Invalid option. Please select 1, 2, 3, or 4.", user_data['sender'], phone_id)
        return {'step': 'check_project_status_menu', 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_drilling_status_info_request(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        # 👇 Only send this if the user's input is incomplete
        send(
            "Please provide at least your full name and reference number or phone number, each on a new line.\n\n"
            "Example:\n"
            "John Doe\nREF789123 or 0779876543\nOptional: Bulawayo",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    # ✅ Valid input: store and proceed
    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Not Provided"

    user.project_status_request = {
        'type': 'drilling',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Thank you. Please wait while we retrieve your project status...", user_data['sender'], phone_id)

    send(
        f"Here is your borehole drilling project status:\n\n"
        f"Project Name: Borehole - {full_name}\n"
        f"Current Stage: Drilling In Progress\n"
        f"Next Step: Casing\n"
        f"Estimated Completion Date: 10/06/2025\n\n"
        "Would you like WhatsApp updates when the status changes?\nOptions: Yes / No",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'drilling_status_updates_opt_in',
        'user': user.to_dict()
    })

    return {
        'step': 'drilling_status_updates_opt_in',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }



def handle_select_pump_option(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Invalid option. Please select a valid pump installation option (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    # Store the selected pump option
    user.quote_data['pump_option'] = prompt.strip()
    
    # Get pricing for the selected pump option
    pricing_message = get_pricing_for_location_quotes(location, "Pump Installation", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_quote_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt.strip() == "1":
        # Stay in quote flow, show services again
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote',
            'user': user.to_dict()
        })
        send(
            "Select another service:\n"
            "1. Water survey\n"
            "2. Borehole drilling\n"
            "3. Pump installation\n"
            "4. Commercial hole drilling\n"
            "5. Borehole Deepening",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "2":
        # Go back to main menu
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(
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

    elif prompt.strip() == "3":
        # Offer price
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details',
            'user': user.to_dict()    
        })
        send(
            "Sure! You can share your proposed price below.\n\n",
            user_data['sender'], phone_id
        )

    elif prompt.strip() == "4":
        # Borehole Classes
        update_user_state(user_data['sender'], {
            'step': 'borehole_class_pricing',
            'user': user.to_dict()    
        })
        send(
            "Please select a class\n\n"
            "1. Class 6\n"
            "2. Class 9\n"
            "3. Class 10\n",
            user_data['sender'], phone_id
        )
        return {'step': 'borehole_class_pricing', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        send("Invalid option. Reply 1 to ask about another service or 2 to return to the main menu or 3 if you want to make a price offer.", 
             user_data['sender'], phone_id)
        return {'step': 'quote_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_borehole_class_pricing(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if prompt.strip() == "1":
        # Stay in quote flow, show services again
        update_user_state(user_data['sender'], {
            'step': 'selected_borehole_class',
            'user': user.to_dict()
        })
        send(
            "Class 6 Pricing Extension:\n\n"
            "extra_per_m is $27\n"
            "included_depth_m 40m\n\n"
            "Would you like to:\n"
            "1. Ask pricing for another service\n"
            "2. Return to Main Menu\n"
            "3. Offer Price",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "2":
        # Stay in quote flow, show services again
        update_user_state(user_data['sender'], {
            'step': 'selected_borehole_class',
            'user': user.to_dict()
        })
        send(
            "Class 9 Pricing Extension:\n\n"
            "extra_per_m is $30\n"
            "included_depth_m 40m\n\n"
            "Would you like to:\n"
            "1. Ask pricing for another service\n"
            "2. Return to Main Menu\n"
            "3. Offer Price",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "3":
        # Stay in quote flow, show services again
        update_user_state(user_data['sender'], {
            'step': 'selected_borehole_class',
            'user': user.to_dict()
        })
        send(
            "Class 10 Pricing Extension:\n\n"
            "extra_per_m is $35\n"
            "included_depth_m 40m\n\n"
            "Would you like to:\n"
            "1. Ask pricing for another service\n"
            "2. Return to Main Menu\n"
            "3. Offer Price",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_followup', 'user': user.to_dict(), 'sender': user_data['sender']}  



def handle_agent_reply(prompt, sender, phone_id, message, agent_state):
    """Handles agent's initial response to customer request"""
    prompt = prompt.strip() if isinstance(prompt, str) else ""
    customer_number = agent_state.get('customer_number')
    
    if not customer_number:
        send("⚠️ Error: No customer assigned. Please wait for a new request.", sender, phone_id)
        update_user_state(sender, {'step': 'agent_available'})
        return
    
    if prompt == '1':  # Accept conversation
        send("✅ You're now talking to the customer. Send '2' to return to bot.", sender, phone_id)
        send("✅ You are now connected to a human agent. Please wait for their response.", customer_number, phone_id)
        
        update_user_state(customer_number, {
            'step': 'talking_to_human_agent',
            'user': get_user_state(customer_number).get('user', {}),
            'sender': customer_number
        })
        update_user_state(sender, {
            'step': 'talking_to_customer',
            'customer_number': customer_number,
            'phone_id': phone_id,
            'started_at': time.time()
        })
        
    elif prompt == '2':  # Decline conversation
        send("✅ You've returned the customer to the bot.", sender, phone_id)
        send("👋 You're now back with our automated assistant.", customer_number, phone_id)
        
        update_user_state(customer_number, {
            'step': 'main_menu',
            'user': get_user_state(customer_number).get('user', {}),
            'sender': customer_number
        })
        update_user_state(sender, {'step': 'agent_available'})
        show_main_menu(customer_number, phone_id)
        
    else:
        send("⚠️ Please reply with:\n1 - Talk to customer\n2 - Back to bot", sender, phone_id)

def handle_agent_conversation(prompt, sender, phone_id, message, agent_state):
    """Handles ongoing agent-customer conversation"""
    customer_number = agent_state.get('customer_number')
    
    if prompt.strip().lower() == '2':  # End conversation
        send("✅ Conversation ended. The bot will take over.", sender, phone_id)
        send("👋 The agent has ended the conversation. You're back with our automated assistant.", customer_number, phone_id)
        
        update_user_state(customer_number, {
            'step': 'main_menu',
            'user': get_user_state(customer_number).get('user', {}),
            'sender': customer_number
        })
        update_user_state(sender, {'step': 'agent_available'})
        show_main_menu(customer_number, phone_id)
    else:
        forward_agent_message(prompt, message, customer_number, phone_id)

def handle_agent_available(prompt, sender, phone_id, message, agent_state):
    """Handles agent when not in conversation"""
    send("ℹ️ You're currently not handling any conversation. Please wait for a new customer request.", sender, phone_id)

def forward_agent_message(prompt, message, customer_number, phone_id):
    """Helper to forward different message types"""
    if not customer_number:
        return
        
    if isinstance(message, dict):
        if message.get("type") == "text":
            send(f"Agent: {message.get('text', '')}", customer_number, phone_id)
        elif message.get("type") == "image":
            caption = f"Agent: {message.get('caption', '')}" if message.get('caption') else "From agent:"
            send_image(message.get('url'), caption, customer_number, phone_id)
        elif message.get("type") == "location":
            send_location(
                message.get('location', {}).get('latitude'),
                message.get('location', {}).get('longitude'),
                "Agent shared location",
                customer_number,
                phone_id
            )
    else:
        send(f"Agent: {prompt}", customer_number, phone_id)


def handle_agent_message(prompt, sender, phone_id, message):
    """
    Handles all messages coming from the agent number.
    """
    agent_state = get_user_state(sender) or {}
    current_step = agent_state.get('step', 'agent_available')
    
    # Get the appropriate handler
    handler = action_mapping.get(current_step, handle_agent_available)
    return handler(prompt, sender, phone_id, message, agent_state)


# Agent Handler Functions
def handle_agent_reply(prompt, sender, phone_id, message, agent_state):
    """Handles agent's initial response to customer request"""
    prompt = prompt.strip() if isinstance(prompt, str) else ""
    customer_number = agent_state.get('customer_number')
    
    if not customer_number:
        send("⚠️ Error: No customer assigned.", sender, phone_id)
        return {'step': 'agent_available'}

    if prompt == '1':  # Accept conversation
        # Notify both parties
        send("✅ You're now connected. Send '2' to return to bot.", sender, phone_id)
        send("✅ Connected to agent. Please ask your question.", customer_number, phone_id)
        
        # Update states
        update_user_state(customer_number, {
            'step': 'talking_to_human_agent',
            'user': get_user_state(customer_number).get('user', {}),
            'sender': customer_number
        })
        
        return {
            'step': 'talking_to_customer',
            'customer_number': customer_number,
            'phone_id': phone_id,
            'started_at': time.time()
        }
        
    elif prompt == '2':  # Decline conversation
        send("✅ Customer returned to bot.", sender, phone_id)
        send("👋 You're back with our automated assistant.", customer_number, phone_id)
        
        update_user_state(customer_number, {
            'step': 'main_menu',
            'user': get_user_state(customer_number).get('user', {}),
            'sender': customer_number
        })
        show_main_menu(customer_number, phone_id)
        return {'step': 'agent_available'}
        
    else:
        send("⚠️ Reply with:\n1 - Talk to customer\n2 - Back to bot", sender, phone_id)
        return agent_state  # Maintain current state

def handle_agent_conversation(prompt, sender, phone_id, message, agent_state):
    """Handles ongoing conversation between agent and customer"""
    customer_number = agent_state.get('customer_number')
    
    if prompt.strip().lower() == '2':  # End conversation
        send("✅ Conversation ended. Bot will take over.", sender, phone_id)
        send("👋 Back to automated assistant.", customer_number, phone_id)
        
        update_user_state(customer_number, {
            'step': 'main_menu',
            'user': get_user_state(customer_number).get('user', {}),
            'sender': customer_number
        })
        show_main_menu(customer_number, phone_id)
        return {'step': 'agent_available'}
    else:
        # Forward message to customer
        forward_agent_message(prompt, message, customer_number, phone_id)
        return agent_state  # Maintain current state

def handle_agent_available(prompt, sender, phone_id, message, agent_state):
    """Handles agent when not in active conversation"""
    send("ℹ️ You're not currently handling any conversation.", sender, phone_id)
    return {'step': 'agent_available'}

def forward_agent_message(prompt, message, customer_number, phone_id):
    """Forwards different message types from agent to customer"""
    if not customer_number:
        return
        
    if isinstance(message, dict):
        if message.get("type") == "text":
            send(f"Agent: {message.get('text', '')}", customer_number, phone_id)
        elif message.get("type") == "image":
            caption = f"Agent: {message.get('caption', '')}" if message.get('caption') else "From agent:"
            send_image(message.get('url'), caption, customer_number, phone_id)
        elif message.get("type") == "location":
            send_location(
                message.get('location', {}).get('latitude'),
                message.get('location', {}).get('longitude'),
                "Agent shared location",
                customer_number,
                phone_id
            )
    else:
        send(f"Agent: {prompt}", customer_number, phone_id)

def handle_default(prompt, user_data, phone_id, message):
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


# Action mapping
action_mapping = {
    "welcome": handle_welcome,
    "select_language": handle_select_language,
    "main_menu": handle_main_menu,
    "enter_location_for_quote": handle_enter_location_for_quote,
    "select_service_quote": handle_select_service_quote,
    "select_service": handle_select_service,
    "borehole_class_pricing": handle_borehole_class_pricing,
    "agent_reply": handle_agent_reply,
    
    "agent_reply": handle_agent_reply,
    "talking_to_customer": handle_agent_conversation,
    "agent_available": handle_agent_available,


    "select_pump_option": handle_select_pump_option,
    "quote_followup": handle_quote_followup,   
    "collect_quote_details": handle_collect_quote_details,
    "quote_response": handle_quote_response,
    "collect_offer_details": handle_collect_offer_details,
    "quote_followup": handle_quote_followup,
    "offer_response": handle_offer_response,
    "booking_details": handle_booking_details,
    "collect_booking_info": handle_collect_booking_info,
    "booking_confirmation": handle_booking_confirmation,
    "faq_menu": faq_menu,
    "faq_borehole": faq_borehole,
    "faq_pump": faq_pump,
    "faq_borehole_followup": faq_borehole_followup,
    "faq_pump_followup": faq_pump_followup,
    "check_project_status_menu": handle_check_project_status_menu,
    "drilling_status_info_request": handle_drilling_status_info_request,
    "pump_status_info_request": handle_pump_status_info_request,
    "pump_status_updates_opt_in": handle_pump_status_updates_opt_in,
    "drilling_status_updates_opt_in": handle_drilling_status_updates_opt_in,
    "custom_question": custom_question,
    "custom_question_followup": custom_question_followup,
    "human_agent": human_agent,
    "waiting_for_human_agent_response": handle_user_message,
    "human_agent_followup": handle_user_message,   
    "other_services_menu": handle_other_services_menu,
    "borehole_deepening_casing": handle_borehole_deepening_casing,
    "borehole_flushing_problem": handle_borehole_flushing_problem,
    "pvc_casing_selection": handle_pvc_casing_selection,
    "deepening_location": handle_deepening_location,
    "human_agent": lambda prompt, user_data, phone_id: (
        send("A human agent will contact you soon.", user_data['sender'], phone_id)
        or {'step': 'main_menu', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
    ),
}

       

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
        logging.info(f"Incoming webhook data: {json.dumps(data, indent=2)}")

        try:
            entry = data.get("entry", [])[0]
            changes = entry.get("changes", [])[0]
            value = changes.get("value", {})
            phone_id = value.get("metadata", {}).get("phone_number_id")
            messages = value.get("messages", [])

            if messages:
                message = messages[0]
                from_number = message.get("from")
                msg_type = message.get("type")

                # Handle agent messages separately
                if from_number == AGENT_NUMBER:
                    message_text = message.get("text", {}).get("body", "").strip() if msg_type == "text" else ""
                    handle_agent_message(message_text, from_number, phone_id, message)
                    return "OK"

                # Handle regular user messages
                user_data = get_user_state(from_number) or {'step': 'welcome', 'sender': from_number}
                
                # Check if user is talking to agent
                if user_data.get('step') == 'talking_to_human_agent':
                    agent_number = user_data.get('agent_number', AGENT_NUMBER)
                    forward_agent_message(
                        message.get("text", {}).get("body", "") if msg_type == "text" else "[Media message]",
                        message,
                        agent_number,
                        phone_id
                    )
                    return "OK"
                
                # Normal message processing
                message_handler(
                    message.get("text", {}).get("body", "") if msg_type == "text" else "",
                    from_number,
                    phone_id,
                    message
                )

        
        except Exception as e:
            logging.error(f"Error processing webhook: {e}", exc_info=True)

        return jsonify({"status": "ok"}), 200



def message_handler(prompt, sender, phone_id, message):
    
    if sender == AGENT_NUMBER:
        return
        
    user_data = get_user_state(sender)
    user_data['sender'] = sender
    

    # If this is a location message, inject location into user_data
    if message.get("type") == "location":
        location = message.get("location", {})
        if "latitude" in location and "longitude" in location:
            user_data["location"] = {
                "latitude": location["latitude"],
                "longitude": location["longitude"]
            }
            # override prompt with coordinates if needed
            prompt = f"{location['latitude']},{location['longitude']}"
        else:
            prompt = ""

    # Ensure user object is present
    if 'user' not in user_data:
        user_data['user'] = User(sender).to_dict()

    # Dispatch to the correct step
    step = user_data.get('step', 'welcome')
    next_state = get_action(step, prompt, user_data, phone_id)
    update_user_state(sender, next_state)

def get_action(current_state, prompt, user_data, phone_id):
    handler = action_mapping.get(current_state, handle_welcome)
    return handler(prompt, user_data, phone_id)
    

if __name__ == "__main__":
    app.run(debug=True, port=8000)

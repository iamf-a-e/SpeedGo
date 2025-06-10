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
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 30
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
        message_lines.append(f"- Includes depth up to {included_depth}m")
        message_lines.append(f"- Extra charge: ${extra_rate}/m beyond included depth\n")
        message_lines.append("Would you like to:\n1. Ask pricing for another service\n2. Return to Main Menu\n3. Offer Price")
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
            'step': 'main_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Tatenda!\n"
            "Tinokubatsirai sei nhasi?\n\n"
            "1. Kukumbira quotation\n"
            "2. Tsvaga Mutengo Uchishandisa Nzvimbo\n"
            "3. Tarisa Mamiriro ePurojekiti\n"
            "4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Chibhorani\n"
            "5. Zvimwe Zvatinoita\n"
            "6. Taura neMunhu\n\n"
            "Pindura nenhamba (semuenzaniso, 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":
        user.language = "Ndebele"
        update_user_state(user_data['sender'], {
            'step': 'main_menu_ndebele',
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
        return {'step': 'main_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
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
    
    # 1. Immediately notify customer
    send("Connecting you to a human agent...", customer_number, phone_id)
    
    # 2. Notify agent in background
    agent_number = "+263719835124"
    agent_message = f"New customer request from {customer_number}\nMessage: {prompt}"
    threading.Thread(target=send, args=(agent_message, agent_number, phone_id)).start()
    
    # 3. After 10 seconds, send fallback options
    def send_fallback():
        user_data = get_user_state(customer_number)
        if user_data and user_data.get('step') in ['human_agent', 'waiting_for_human_agent_response']:
            send("If you haven't been contacted yet, you can call us directly at +263719835124", customer_number, phone_id)
            send("Would you like to:\n1. Return to main menu\n2. Keep waiting", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'human_agent_followup',
                'user': user_data.get('user', {}),
                'sender': customer_number
            })
    
    threading.Timer(10, send_fallback).start()
    
    # 4. Update state to waiting
    update_user_state(customer_number, {
        'step': 'waiting_for_human_agent_response',
        'user': user_data.get('user', {}),
        'sender': customer_number,
        'waiting_since': time.time()
    })
    
    return {'step': 'waiting_for_human_agent_response', 'user': user_data.get('user', {}), 'sender': customer_number}


def notify_agent(customer_number, prompt, agent_number, phone_id):
    agent_message = (
        f"👋 New customer request on WhatsApp\n\n"
        f"📱 Number: {customer_number}\n"
        f"📩 Message: \"{prompt}\""
    )
    send(agent_message, agent_number, phone_id)

def send_fallback_option(customer_number, phone_id):
    # Check if still waiting
    user_data = get_user_state(customer_number)
    if user_data and user_data.get('step') == 'waiting_for_human_agent_response':
        send("Alternatively, you can contact us directly at +263719835124", customer_number, phone_id)
        send("Would you like to:\n1. Return to main menu\n2. End conversation", customer_number, phone_id)
        update_user_state(customer_number, {
            'step': 'human_agent_followup',
            'user': user_data.get('user', {}),
            'sender': customer_number
        })


def send_fallback_option(customer_number, phone_id):
    # Check if user is still waiting
    user_data = get_user_state(customer_number)
    if user_data.get('step') == 'waiting_for_human_agent_response':
        send(
            "Alternatively, you can message or call us directly at +263719835124.",
            customer_number, phone_id
        )
        send(
            "Would you like to return to the main menu?\n1. Yes\n2. No",
            customer_number, phone_id
        )
        update_user_state(customer_number, {
            'step': 'human_agent_followup',
            'user': user_data.get('user', {}),
            'sender': customer_number
        })
        

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
        return {'step': 'collect_offer_details', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Invalid option. Reply 1 to ask about another service or 2 to return to the main menu or 3 if you want to make a price offer.", user_data['sender'], phone_id)
        return {'step': 'quote_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

#-------------------------------------------------------SHONA---------------------------------------------------------------------------
location_pricing_shona = {
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
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 30
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


pump_installation_options_shona = {
    "1": {
        "description": "D.C solar (solar isina inverter) - Ndine tangi ne stand yetangi",
        "price": 1640
    },
    "2": {
        "description": "D.C solar (solar isina inverter) - Handina chinhu zvachose",
        "price": 2550
    },
    "3": {
        "description": "D.C solar (solar isina inverter) - Basa chete",
        "price": 200
    },
    "4": {
        "description": "A.C yemagetsi (ZESA kana solar inverter) - Kugadzirisa nekuunza zvinhu",
        "price": 1900
    },
    "5": {
        "description": "A.C yemagetsi (ZESA kana solar inverter) - Basa chete",
        "price": 170
    },
    "6": {
        "description": "A.C yemagetsi (ZESA kana solar inverter) - Ndine tangi ne stand yetangi",
        "price": 950
    }
}


def handle_select_service_quote(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if not location:
        send("Ndokumbirawo kuti utange wapa nzvimbo yako usati wasarudza sevhisi.", user_data['sender'], phone_id)
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
        send("Sarudzo isiri iyo. Ndapota pindura ne 1, 2, 3, 4 kana 5 kuti usarudze sevhisi.", user_data['sender'], phone_id)
        return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Store selected service
    user.quote_data['service'] = selected_service

    # Handle Pump Installation separately as it has options
    if selected_service == "Pump Installation":
        update_user_state(user_data['sender'], {
            'step': 'select_pump_option',
            'user': user.to_dict()
        })
        message_lines = [f"💧 Sarudzo dzekuisa Pombi:\n"]
        for key, option in pump_installation_options.items():
            desc = option.get('description', 'Tsananguro haisipo')
            message_lines.append(f"{key}. {desc}")
        send("\n".join(message_lines), user_data['sender'], phone_id)
        return {'step': 'select_pump_option', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Get pricing for other services
    pricing_message = get_pricing_for_location_quotes_shona(location, selected_service)
    
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

# Shona version of human agent handler
def human_agent_shona(prompt, user_data, phone_id):
    customer_number = user_data['sender']
    
    send("Tiri kukubatanidza nemumiriri wevanhu...", customer_number, phone_id)
    
    agent_number = "+263719835124"
    agent_message = f"Mutengi mutsva kubva ku{customer_number}\nMharidzo: {prompt}"
    threading.Thread(target=send, args=(agent_message, agent_number, phone_id)).start()
    
    def send_fallback():
        user_data = get_user_state(customer_number)
        if user_data and user_data.get('step') in ['human_agent_shona', 'waiting_for_human_agent_response_shona']:
            send("Kana usati wafonerwa, unogona kutifonera pa +263719835124", customer_number, phone_id)
            send("Unoda here:\n1. Dzokera kumenu huru\n2. Ramba wakamirira", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'human_agent_followup_shona',
                'user': user_data.get('user', {}),
                'sender': customer_number
            })
    
    threading.Timer(10, send_fallback).start()
    
    update_user_state(customer_number, {
        'step': 'waiting_for_human_agent_response_shona',
        'user': user_data.get('user', {}),
        'sender': customer_number,
        'waiting_since': time.time()
    })
    
    return {'step': 'waiting_for_human_agent_response_shona', 'user': user_data.get('user', {}), 'sender': customer_number}


# Shona version of location handler
def handle_enter_location_for_quote_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if 'location' in user_data and 'latitude' in user_data['location'] and 'longitude' in user_data['location']:
        lat = user_data['location']['latitude']
        lng = user_data['location']['longitude']
        gps_coords = f"{lat},{lng}"
        location_name = reverse_geocode_location(gps_coords)
        
        if location_name:
            user.quote_data['location'] = location_name
            user.quote_data['gps_coords'] = gps_coords
            update_user_state(user_data['sender'], {
                'step': 'select_service_quote_shona',
                'user': user.to_dict()
            })
            send(
                f"Nzvimbo yaonekwa: {location_name.title()}\n\n"
                "Sarudza sevhisi:\n"
                "1. Ongororo Yemvura\n"
                "2. Kuchera chibhorani\n"
                "3. Kuiswa kwepombi\n"
                "4. Kuchera chibhorani cheBhizinesi\n"
                "5. Kuwedzera kuchera Chibhorani",
                user_data['sender'], phone_id
            )
            return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
        else:
            send("Hatina kukwanisa kuona nzvimbo yako. Ndapota nyora zita reguta/dhorobha rako.", user_data['sender'], phone_id)
            return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        location_name = prompt.strip()
        user.quote_data['location'] = location_name.lower()
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote_shona',
            'user': user.to_dict()
        })
        send(
            "Sarudza sevhisi:\n"
            "1. Ongororo Yemvura\n"
            "2. Kuchera chibhorani\n"
            "3. Kuiswa kwepombi\n"
            "4. Kuchera chibhorani cheBhizinesi\n"
            "5. Kuwedzera kuchera Chibhorani",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

# Shona version of service selection
def handle_select_service_quote_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if not location:
        send("Ndokumbirawo kuti utange wapa nzvimbo yako usati wasarudza sevhisi.", user_data['sender'], phone_id)
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
        send("Sarudzo isiri iyo. Ndapota pindura ne 1, 2, 3, 4 kana 5 kuti usarudze sevhisi.", user_data['sender'], phone_id)
        return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Store selected service
    user.quote_data['service'] = selected_service

    # Handle Pump Installation separately as it has options
    if selected_service == "Pump Installation":
        update_user_state(user_data['sender'], {
            'step': 'select_pump_option',
            'user': user.to_dict()
        })
        message_lines = [f"💧 Sarudzo dzekuisa Pombi:\n"]
        for key, option in pump_installation_options.items():
            desc = option.get('description', 'Tsananguro haisipo')
            message_lines.append(f"{key}. {desc}")
        send("\n".join(message_lines), user_data['sender'], phone_id)
        return {'step': 'select_pump_option', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Get pricing for other services
    pricing_message = get_pricing_for_location_quotes_shona(location, selected_service)
    
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

# Shona version of quote followup
def handle_quote_followup_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt.strip() == "1":
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote_shona',
            'user': user.to_dict()
        })
        send(
            "Sarudza imwe sevhisi:\n"
            "1. Ongororo Yemvura\n"
            "2. Kuchera chibhorani\n"
            "3. Kuiswa kwepombi\n"
            "4. Kuchera chibhorani cheBhizinesi\n"
            "5. Kuwedzera kuchera Chibhorani",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "2":
        update_user_state(user_data['sender'], {
            'step': 'main_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Tinokubatsira sei nhasi?\n\n"
            "1. Kukumbira quotation\n"
            "2. Tsvaga Mutengo Uchishandisa Nzvimbo\n"
            "3. Tarisa Mamiriro ePurojekiti\n"
            "4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Chibhorani\n"
            "5. Zvimwe Zvatinoita\n"
            "6. Taura neMunhu\n\n"
            "Pindura nenhamba (semuenzaniso, 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details_shona',
            'user': user.to_dict()    
        })
        send(
            "Hongu! Unogona kugovera mutengo wako pazasi.\n\n",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sarudzo isiriyo. Pindura ne1 kubvunza nezveimwe sevhisi kana 2 kudzokera kumenu huru kana 3 kana uchida kuita mutengo.", user_data['sender'], phone_id)
        return {'step': 'quote_followup_shona', 'user': user.to_dict(), 'sender': user_data['sender']}


def custom_question_followup_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    # Basic response for follow-up in Shona
    response = (
        "Tatambira mhinduro yenyu. Kana muchida kudzokera kumenu huru, tumirai 0.\n"
        "Kana muchida kubvunza imwe nyaya, nyorai mubvunzo wenyu."
    )
    send(response, user_data['sender'], phone_id)
    return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_main_menu_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Request a quote
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote_shona',
            'user': user.to_dict()
        })
        send("ndapota isa nzvimbo yako (Guta/Dhorobha kana GPS) kuti titange.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Search Price Using Location
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote_shona',
            'user': user.to_dict()
        })
        send(
           "Kuti uwane mitengo, ndapota isa nzvimbo yako (Guta/Dhorobha kana GPS):",
            user_data['sender'], phone_id
        )
        return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Check Project Status
        update_user_state(user_data['sender'], {
            'step': 'check_project_status_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Ndapota sarudza sarudzo:\n"
            "1. Tarisa mamiriro ekuchera borehole\n"
            "2. Tarisa mamiriro ekuisa pombi\n"
            "3. Taura nemumiriri wevanhu\n"
            "4. Dzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'check_project_status_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        update_user_state(user_data['sender'], {
            'step': 'faq_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Ndapota sarudza chikamu chemibvunzo:\n\n"
            "1. Mibvunzo Inowanzo bvunzwa nezve Borehole Drilling\n"
            "2. Mibvunzo Inowanzo bvunzwa nezve Pump Installation\n"
            "3. Bvunza mumwe mubvunzo\n"
            "4. Taura nemumiriri wevanhu\n"
            "5. Dzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Other Services
        update_user_state(user_data['sender'], {
            'step': 'other_services_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Kugamuchirwa kune mamwe masevhisi eBorehole. Ndeapi sevhisi aunoda?\n"
            "1. Borehole Deepening\n"
            "2. Borehole Flushing\n"
            "3. PVC Casing Pipe Sarudzo\n"
            "4. Dzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'other_services_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
        
    elif prompt == "6":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent_shona',
            'user': user.to_dict(),
            'original_prompt': prompt
        })
        return human_agent_shona(prompt, {
            'step': 'human_agent_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }, phone_id)
    
    else:
        send("Ndapota sarudza sarudzo inoshanda (1-6).", user_data['sender'], phone_id)
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def human_agent_shona(prompt, user_data, phone_id):
    customer_number = user_data['sender']
    
    # 1. Notify customer immediately
    send("Tiri kukubatanidza nemumiriri wevanhu...", customer_number, phone_id)
    
    # 2. Notify agent in background
    agent_number = "+263719835124"
    agent_message = f"Mutengi mutsva kubva ku {customer_number}\nMharidzo: {prompt}"
    threading.Thread(target=send, args=(agent_message, agent_number, phone_id)).start()
    
    # 3. After 10 seconds, send fallback options
    def send_fallback():
        user_data = get_user_state(customer_number)
        if user_data and user_data.get('step') in ['human_agent_shona', 'waiting_for_human_agent_response_shona']:
            send("Kana musati mafonerwa, mungatideedzera pa +263719835124", customer_number, phone_id)
            send("Unoda here:\n1. Kudzokera kumain menu\n2. Kuramba wakamirira", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'human_agent_followup_shona',
                'user': user_data.get('user', {}),
                'sender': customer_number
            })
    
    threading.Timer(10, send_fallback).start()
    
    # 4. Update state to waiting
    update_user_state(customer_number, {
        'step': 'waiting_for_human_agent_response_shona',
        'user': user_data.get('user', {}),
        'sender': customer_number,
        'waiting_since': time.time()
    })
    
    return {'step': 'waiting_for_human_agent_response_shona', 'user': user_data.get('user', {}), 'sender': customer_number}

def handle_enter_location_for_quote_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if 'location' in user_data and 'latitude' in user_data['location'] and 'longitude' in user_data['location']:
        lat = user_data['location']['latitude']
        lng = user_data['location']['longitude']
        gps_coords = f"{lat},{lng}"
        location_name = reverse_geocode_location(gps_coords)
        
        if location_name:
            user.quote_data['location'] = location_name
            user.quote_data['gps_coords'] = gps_coords
            update_user_state(user_data['sender'], {
                'step': 'select_service_quote_shona',
                'user': user.to_dict()
            })
            send(
                f"Nzvimbo yaonekwa: {location_name.title()}\n\n"
                "Sarudza sevhisi:\n"
                "1. Ongororo yemvura\n"
                "2. Kuchera borehole\n"
                "3. Kuiswa kwepombi\n"
                "4. Kuchera maburi ekutengesa\n"
                "5. Kudzika borehole",
                user_data['sender'], phone_id
            )
            return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
        else:
            send("Hatina kukwanisa kuona nzvimbo yako. Ndapota nyora zita reguta/dhorobha rako.", user_data['sender'], phone_id)
            return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        location_name = prompt.strip()
        user.quote_data['location'] = location_name.lower()
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote_shona',
            'user': user.to_dict()
        })
        send(
            "Sarudza sevhisi:\n"
            "1. Ongororo yemvura\n"
            "2. Kuchera borehole\n"
            "3. Kuiswa kwepombi\n"
            "4. Kuchera maburi ekutengesa\n"
            "5. Kudzika borehole",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_select_service_quote_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if not location:
        send("Ndapota taura nzvimbo yako kutanga.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    service_map = {
        "1": "Water Survey",
        "2": "Borehole Drilling",
        "3": "Pump Installation",
        "4": "Commercial Hole Drilling",
        "5": "Borehole Deepening"
    }

    selected_service = service_map.get(prompt.strip())

    if not selected_service:
        send("Sarudzo isiriyo. Ndapota pindura ne1, 2, 3, 4 kana 5 kusarudza sevhisi.", user_data['sender'], phone_id)
        return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['service'] = selected_service

    if selected_service == "Kuiswa kwepombi":
        update_user_state(user_data['sender'], {
            'step': 'select_pump_option_shona',
            'user': user.to_dict()
        })
        message_lines = [f"💧 Sarudzo dzekuiswa kwepombi:\n"]
        for key, option in pump_installation_options.items():
            desc = option.get('description', 'Hapana tsananguro')
            message_lines.append(f"{key}. {desc}")
        send("\n".join(message_lines), user_data['sender'], phone_id)
        return {'step': 'select_pump_option_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    pricing_message = get_pricing_for_location_quotes_shona(location, selected_service)
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_shona',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'quote_followup_shona',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def get_pricing_for_location_quotes_shona(location, service_key_input, pump_option_selected=None):
    # Normalize location key (strip + lowercase)
    location_key = location.strip().lower()
    loc_data_shona = location_pricing_shona.get(location_key)

    if not loc_data_shona:
        return "Ndine urombo, hatina mitengo yenzvimbo iyi."

    # Map textual service names and numeric options to internal keys
    SERVICE_KEY_MAP_SHONA = {
        # Numeric options
        "1": "Ongororo Yemvura",
        "2": "Kuchera chibhorani",
        "3": "Kuiswa kwepombi",
        "4": "Kuchera chibhorani cheBhizinesi",
        "5": "Kuwedzera Udzamu hwechibhorani",
        
        # Textual options
        "ongororo yemvura": "Ongororo Yemvura",
        "kuchera chibhorani": "Kuchera chibhorani",
        "kuchera borehole": "Kuchera chibhorani",
        "kuiswa kwepombi": "Kuiswa kwepombi",
        "kuchera chibhorani chebhizinesi": "Kuchera chibhorani cheBhizinesi",
        "kuchera maburi ekutengesa": "Kuchera chibhorani cheBhizinesi",
        "kuwedzera kuchera chibhorani": "Kuwedzera Udzamu hwechibhorani",
        "kudzika borehole": "Kuwedzera Udzamu hwechibhorani"
    }

    # Normalize service key input
    service_key_raw = str(service_key_input).strip().lower()
    service_key_shona = SERVICE_KEY_MAP_SHONA.get(service_key_raw, service_key_raw)

    # Get price with case-insensitive fallback
    price = None
    for key in loc_data_shona.keys():
        if key.lower() == service_key_shona.lower():
            price = loc_data_shona[key]
            break

    if not price:
        return f"Ndine urombo, hatina mutengo we {service_key_shona} mu {location.title()}."

    # Format response based on price type
    if isinstance(price, dict):  # For drilling services with multiple classes
        included_depth = price.get("udzamu hwunosanganisirwa_m", "N/A")
        extra_rate = price.get("mari yekuwedzera pamita", "N/A")
        
        message_lines = [
            f"💧 Mitengo ye {service_key_shona} mu {location.title()}:",
            *[f"- {k.title()}: ${v}" for k, v in price.items() if k.startswith("kirasi")],
            f"- Inosanganisira kudzika kusvika {included_depth}m",
            f"- Mari yekuwedzera: ${extra_rate}/m pamusoro pekudzika kwakapihwa",
            "",
            "Unoda here:",
            "1. Kukumbira mitengo yeimwe sevhisi",
            "2. Kudzokera kuMain Menu",
            "3. Kupa mutengo wako"
        ]
        return "\n".join(message_lines)
    else:  # For simple pricing
        unit = "pamita" if service_key_shona in ["Kuchera chibhorani cheBhizinesi", "Kuwedzera Udzamu hwechibhorani"] else "mutengo wakafanira"
        return (
            f"{service_key_shona} mu {location.title()}: ${price} {unit}\n\n"
            "Unoda here:\n"
            "1. Kukumbira mitengo yeimwe sevhisi\n"
            "2. Kudzokera kuMain Menu\n"
            "3. Kupa mutengo wako"
        )        

def handle_select_pump_option_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Sarudzo isiriyo. Ndapota sarudza sarudzo inoshanda yekuiswa kwepombi (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_shona(location, "Kuiswa kwepombi", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_shona',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_shona',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_quote_followup_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt.strip() == "1":
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote_shona',
            'user': user.to_dict()
        })
        send(
            "Sarudza imwe sevhisi:\n"
            "1. Ongororo yemvura\n"
            "2. Kuchera borehole\n"
            "3. Kuiswa kwepombi\n"
            "4. Kuchera maburi ekutengesa\n"
            "5. Kudzika borehole",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "2":
        update_user_state(user_data['sender'], {
            'step': 'main_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Tingakubatsira sei nhasi?\n\n"
            "1. Kukumbira quotation\n"
            "2. Tsvaga Mutengo Uchishandisa Nzvimbo\n"
            "3. Tarisa Mamiriro ePurojekiti\n"
            "4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Chibhorani\n"
            "5. Zvimwe Zvatinoita\n"
            "6. Taura neMunhu\n\n"
            "Pindura nenhamba (semuenzaniso, 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details_shona',
            'user': user.to_dict()    
        })
        send(
            "Hongu! Unogona kugovera mutengo wako pazasi.\n\n",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sarudzo isiriyo. Pindura ne1 kuti ubvunze nezveimwe sevhisi kana 2 kudzokera kumain menu kana 3 kana uchida kupa mutengo wako.", user_data['sender'], phone_id)
        return {'step': 'quote_followup_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_offer_details_shona(prompt, user_data, phone_id):
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
        'step': 'offer_response_shona',
        'user': user.to_dict()
    })
    send(
        "Chikumbiro chako chatumirwa kumaneja wekutengesa. Tichapindura mukati meawa imwe.\n\n"
        "Ndatenda nechipo chako!\n\n"
        "Chikwata chedu chichatarisa uye chichapindura munguva pfupi.\n\n"
        "Kunyange tichida kuve nemitengo inodhura, mitengo yedu inoratidza mhando, kuchengetedzeka, uye kuvimbika.\n\n"
        "Unoda here:\n"
        "1. Kuenderera kana chikumbiro chabvumirwa\n"
        "2. Taura nemunhu\n"
        "3. Chinja chikumbiro chako",
        user_data['sender'], phone_id
    )
    return {'step': 'offer_response_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_offer_response_shona(prompt, user_data, phone_id):
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
            'step': 'booking_details_shona',
            'user': user.to_dict()
        })
        send(
            "Mashoko akanaka! Chikumbiro chako chabvumirwa.\n\n"
            "Ngatitsanangure danho raitevera.\n\n"
            "Unoda here:\n"
            "1. Bhuka Ongororo yeSaiti\n"
            "2. Bhadhara Deposit\n"
            "3. Simbisa Zuva rekuchera",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_details_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Tiri kukubatanidza nemumiriri wevanhu...", user_data['sender'], phone_id)
        return {'step': 'human_agent_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details_shona',
            'user': user.to_dict()
        })
        send(
            "Ndapota tumira chikumbiro chako chakagadziridzwa muchimiro:\n\n"
            "- Ongororo yemvura: $_\n"
            "- Kuchera borehole: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sarudzo inoshanda (1-3).", user_data['sender'], phone_id)
        return {'step': 'offer_response_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_details_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info_shona',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Ndapota tipe zvinotevera ruzivo kuti tipedzise kubhuka kwako:\n\n"
            "- Zita rako rose:\n"
            "- Zuva raunoda (dd/mm/yyyy):\n"
            "- Kero yeSaiti: GPS kana kero\n"
            "- Nhamba yefoni:\n"
            "- Nzira yekubhadhara (Prepayment / Cash pasaiti):\n\n"
            "Nyora: Tumira",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Ndapota bata hofisi yedu pa077xxxxxxx kuti uronge kubhadhara deposit.", user_data['sender'], phone_id)
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("Mumiriri wedu achakubata kuti asimbise zuva rekuchera.", user_data['sender'], phone_id)
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sarudzo inoshanda (1-3).", user_data['sender'], phone_id)
        return {'step': 'booking_details_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_booking_info_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt.lower().strip() == "tumira":
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
            'step': 'booking_confirmation_shona',
            'user': user.to_dict()
        })
        booking_date = "25/05/2025"
        booking_time = "10:00 AM"
        send(
            "Ndatenda. Kubhuka kwako kwakabvumirwa, uye technician achakubata munguva pfupi.\n\n"
            f"Chirangaridzo: Ongororo yako yesaiti yakarongerwa mangwana.\n\n"
            f"Zuva: {booking_date}\n"
            f"Nguva: {booking_time}\n\n"
            "Tinotarisira kushanda newe!\n"
            "Unoda kugadzirisa zvakare? Pindura\n\n"
            "1. Hongu\n"
            "2. Kwete",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_confirmation_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota nyora 'Tumira' kuti usimbise kubhuka kwako.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_confirmation_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "2":
        send(
            "Zvakanaka! Kubhuka kwako kwekuchera borehole kwave kwakanyorwa.\n\n"
            "Zuva: China, 23 Chivabvu 2025\n"
            "Nguva yekutanga: 8:00 AM\n"
            "Nguva inotarisirwa: 5 maawa\n"
            "Chikwata: 4-5 MaTechnician\n\n"
            "Ita shuwa kuti pane nzira yekupinda pasaiti",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota bata timu yedu yerutsigiro kuti vagadzirise zvakare.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_check_project_status_menu_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'drilling_status_info_request_shona',
            'user': user.to_dict()
        })
    
        send(
            "Kutarisa mamiriro ako ekuchera borehole, ndapota tipe zvinotevera:\n\n"
            "- Zita rako rose rakashandiswa pakubhuka\n"
            "- Nhamba yereferensi kana Nhamba yefoni\n"
            "- Nzvimbo yekuchera (sarudzo)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'pump_status_info_request_shona',
            'user': user.to_dict()
        })
        send(
            "Kutarisa mamiriro ako ekuiswa kwepombi, ndapota tipe zvinotevera:\n\n"
            "- Zita rako rose rakashandiswa pakubhuka\n"
            "- Nhamba yereferensi kana Nhamba yefoni\n"
            "- Nzvimbo yekuiswa (sarudzo)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'human_agent_shona',
            'user': user.to_dict()
        })
        send("Ndapota mira uchichipa kubatanidza nemumwe wevashandi vedu.", user_data['sender'], phone_id)
        return {'step': 'human_agent_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        return handle_main_menu_shona("", user_data, phone_id)

    else:
        send("Sarudzo isiriyo. Ndapota sarudza 1, 2, 3, kana 4.", user_data['sender'], phone_id)
        return {'step': 'check_project_status_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_drilling_status_info_request_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Ndapota tipe zita rako rose uye nhamba yereferensi kana nhamba yefoni, pane mutsara wega wega.\n\n"
            "Muenzaniso:\n"
            "John Doe\nREF789123 kana 0779876543\nSarudzo: Bulawayo",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Hazvina Kupihwa"

    user.project_status_request = {
        'type': 'kuchera',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Ndatenda. Ndapota mira uchichipa tichitora mamiriro epurojekiti yako...", user_data['sender'], phone_id)

    send(
        f"Heino mamiriro epurojekiti yako yekuchera borehole:\n\n"
        f"Zita rePurojekiti: Borehole - {full_name}\n"
        f"Chikamu Chazvino: Kuchera Kuri Kuita\n"
        f"Danho Rinotevera: Kuisa Casing\n"
        f"Zuva Rinotarisirwa Kupedzwa: 10/06/2025\n\n"
        "Unoda here kugamuchira zviziviso paWhatsApp kana mamiriro achichinja?\nSarudzo: Hongu / Kwete",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'drilling_status_updates_opt_in_shona',
        'user': user.to_dict()
    })

    return {
        'step': 'drilling_status_updates_opt_in_shona',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_drilling_status_updates_opt_in_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['hongu', 'h']:
        send(
            "Zvakanaka! Uchatambira zviziviso paWhatsApp pese panochinja mamiriro ekuchera kwako.\n\n"
            "Ndatenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    elif response in ['kwete', 'k']:
        send(
            "Hazvina mhosva. Unogona kutarisa mamiriro chero nguva kana uchida.\n\n"
            "Ndatenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ndine urombo, handina kunzwisisa. Ndapota pindura neHongu kana Kwete.", user_data['sender'], phone_id)
        return {'step': 'drilling_status_updates_opt_in_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_pump_status_info_request_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Ndapota tipe zita rako rose uye nhamba yereferensi kana nhamba yefoni, pane mutsara wega wega.\n\n"
            "Muenzaniso:\n"
            "Jane Doe\nREF123456\nSarudzo: Harare",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Hazvina Kupihwa"

    user.project_status_request = {
        'type': 'pombi',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Ndatenda. Ndapota mira uchichipa tichitora mamiriro epurojekiti yako...", user_data['sender'], phone_id)

    send(
        f"Heino mamiriro epurojekiti yako yekuiswa kwepombi:\n\n"
        f"Zita rePurojekiti: Pombi - {full_name}\n"
        f"Chikamu Chazvino: Kuiswa Kwapedzwa\n"
        f"Danho Rinotevera: Kuongorora Kwekupedzisira\n"
        f"Zuva Rinotarisirwa Kuendeswa: 12/06/2025\n\n"
        "Unoda here kugamuchira zviziviso paWhatsApp kana mamiriro achichinja?\nSarudzo: Hongu / Kwete",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'pump_status_updates_opt_in_shona',
        'user': user.to_dict()
    })

    return {
        'step': 'pump_status_updates_opt_in_shona',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_quote_response_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    user.quote_data['details'] = prompt.strip()

    update_user_state(user_data['sender'], {
        'step': 'quote_followup_shona',
        'user': user.to_dict()
    })

    send(
        "Ndatenda! Tichakupai mutengo wakatarwa tichitarisa nzvimbo yako uye mashoko awakapa. ",
        user_data['sender'], phone_id
    )
    send(
        "Ungade:\n"
        "1. Kukumbira imwe quote\n"
        "2. Kudzokera kuMain Menu",
        user_data['sender'], phone_id
    )

    return {'step': 'quote_followup_shona', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pump_status_updates_opt_in_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['ehe', 'hongu']:
        send(
            "Zvakanaka! Uchatambira zvizere paWhatsApp kana mamiriro ebasa rako achichinja.\n\n"
            "Ndatokutendai nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    elif response in ['kwete', 'aiwa']:
        send(
            "Hazvina mhosva. Unogona kutarisa mamiriro ebasa chero nguva.\n\n"
            "Ndatokutendai nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ndakanganwa, handina kunzwisisa. Pindura uchiti Ehe kana Kwete.", user_data['sender'], phone_id)
        return {'step': 'pump_status_updates_opt_in_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    # No further step - end the flow
    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Mutengo unotsamira panzvimbo yako, kudzika kwepombi, uye mamiriro evhu. Ndokumbira utitumire nzvimbo yako pamwe nemashoko ekuti tinokwanisa sei kusvika panzvimbo yacho kuti tikupe mutengo wakakodzera.",
        "2": "Kazhinji zvinotora maawa 4–6 kana mazuva akati wandei, zvinoenderana nemamiriro epanzvimbo, rudzi rwe dombo, uye kuwanika kwenzvimbo yacho.",
        "3": "Kudzika kunosiyana nzvimbo nenzvimbo. Kazhinji kudzika kunosvika mamita anenge 40, asi borehole inogona kudzika kubva pamamita 40 kusvika 150 zvichibva pavhu remvura pasi pevhu.",
        "4": "Mumamwe matunhu, ungangoda rezinesi remvura. Tinogona kukubatsira pakunyorera rezinesi iri kana zvichidiwa.",
        "5": "Ehe, tinopa zvose pamwe chete kana zvakasiyana, zvinoenderana nezvaunoda.",
        "6": "Kana mutengi achida kuchera kune imwe nzvimbo zvakare, tinopa dhisikaundi.\n\nCherechedzo: Michina yekuongorora inobatsira kuona mafundo emvura ari pasi pevhu kana nzvimbo dzinounganidza mvura dzepasi pevhu. Asi haibviri kuyera huwandu hwemvura kana kumhanya kwayo. Saka kuchera borehole hakuvimbisi kuti mvura ichawanikwa 100%, sezvo mafundo aya angave akaoma, akanyorova, kana akanyorova zvishoma.",
        "7": "Tinoshandisa michina yepamusoro-soro yekuchera borehole inosanganisira rotary ne percussion drilling rigs, zvishandiso zveGPS, uye michina yekuongorora zvicherwa.",
        "8": "Kudzokera kuMenu reMibvunzo yeBorehole..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Ungada kuita zvipi:\n"
            "1. Kubvunza mimwe mibvunzo pamusoro peBorehole Drilling\n"
            "2. Kudzokera kuMenu Mukuru",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_followup_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndokumbira usarudze sarudzo yakakodzera (1–8).", user_data['sender'], phone_id)
        return {'step': 'faq_borehole_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole_followup_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Ndapota sarudza mubvunzo waunoda kubvunza pamusoro peBorehole Drilling:\n"
             "1. Mutengo\n"
             "2. Nguva inotora\n"
             "3. Kudzika kweborehole\n"
             "4. Rezinesi remvura\n"
             "5. Borehole drilling uye pump installation pamwe chete\n"
             "6. Dhisikaundi pakuchera pane imwe nzvimbo\n"
             "7. Michina inoshandiswa\n"
             "8. Kudzokera kuMenu reMibvunzo",
        "2": "Kudzokera kuMenu Mukuru...",
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "2":
            return {'step': 'faq_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
        else:
            return {'step': 'faq_borehole_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndokumbira usarudze sarudzo yakakodzera (1-2).", user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup_shona', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Mitengo inobva pane rudzi rwepombi yaunoda kuisa. Ndokumbira tizivise mhando yepombi yako kuti tikupa mutengo wakakodzera.",
        "2": "Kuisa pombi kunowanzotora maawa 2-4, zvinoenderana nemamiriro enzvimbo yako.",
        "3": "Tinopa mhando dzakasiyana dzepombi, kusanganisira pombi dzemagetsi nevasina magetsi.",
        "4": "Kana uine mimwe mibvunzo kana kuda rubatsiro rwemanyorero, ndapota taura nesu zvakananga.",
        "5": "Kudzokera kuMenu reMibvunzo...",
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "5":
            return {'step': 'faq_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
        else:
            send(
                "Unoda kuita zvinotevera:\n"
                "1. Kubvunza mimwe mibvunzo pamusoro pePump Installation\n"
                "2. Kudzokera kuMenu Mukuru",
                user_data['sender'], phone_id
            )
            return {'step': 'faq_pump_followup_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndokumbira usarudze sarudzo yakakodzera (1-5).", user_data['sender'], phone_id)
        return {'step': 'faq_pump_shona', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump_followup_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        # Ask another pump-related FAQ
        send(
            "Ndapota sarudza mubvunzo kubva kuPump Installation FAQs:\n"
            "1. Mutengo wekuisa pombi\n"
            "2. Nguva inotora kuisa pombi\n"
            "3. Mhando dzepombi dzatinopa\n"
            "4. Rubatsiro rwemanyorero\n"
            "5. Kudzokera kuMenu reMibvunzo",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        # Return to main menu
        send("Kudzokera kuMenu Mukuru...", user_data['sender'], phone_id)
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndokumbira usarudze sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup_shona', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_drilling_status_updates_opt_in_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['ehe', 'hongu']:
        send(
            "Zvakanaka! Uchatambira zvizere paWhatsApp kana mamiriro ebasa rako achichinja.\n\n"
            "Ndatokutendai nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    elif response in ['kwete', 'aiwa']:
        send(
            "Hazvina mhosva. Unogona kutarisa mamiriro ebasa chero nguva.\n\n"
            "Ndatokutendai nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ndakanganwa, handina kunzwisisa. Pindura uchiti Ehe kana Kwete.", user_data['sender'], phone_id)
        return {'step': 'drilling_status_updates_opt_in_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    # No further step - end the flow
    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_check_project_status_menu_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'drilling_status_info_request_shona',
            'user': user.to_dict()
        })
    
        send(
            "Kutarisa mamiriro ebasa rako rekuchera borehole, ndapota taura zvinotevera:\n\n"
            "- Zita rako rose rawakashandisa pakubhuka\n"
            "- Nhamba yereferensi yeprojekiti kana Nhamba yefoni\n"
            "- Nzvimbo yekuchera (sarudzo)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'pump_status_info_request_shona',
            'user': user.to_dict()
        })
        send(
            "Kutarisa mamiriro ebasa rako rekuisa pombi, ndapota taura zvinotevera:\n\n"
            "- Zita rako rose rawakashandisa pakubhuka\n"
            "- Nhamba yereferensi yeprojekiti kana Nhamba yefoni\n"
            "- Nzvimbo yekuisa (sarudzo)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'human_agent_shona',
            'user': user.to_dict()
        })
        send("Ndapota mira uchiri kukubatanidza kune mumwe wevashandi vedu.", user_data['sender'], phone_id)
        return {'step': 'human_agent_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        return handle_main_menu_shona("", user_data, phone_id)

    else:
        send("Sarudzo isiriyo. Sarudza 1, 2, 3, kana 4.", user_data['sender'], phone_id)
        return {'step': 'check_project_status_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_drilling_status_info_request_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Ndapota taura zita rako rose uye nhamba yereferensi kana nhamba yefoni, mumitsara yakasiyana.\n\n"
            "Muenzaniso:\n"
            "John Doe\nREF789123 kana 0779876543\nSarudzo: Bulawayo",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Hazvina Kupihwa"

    user.project_status_request = {
        'type': 'drilling',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Waita zvako. Ndapota mira uchiri kutora mamiriro ebasa rako...", user_data['sender'], phone_id)

    send(
        f"Heino mamiriro ebasa rako rekuchera borehole:\n\n"
        f"Zita reProjekiti: Borehole - {full_name}\n"
        f"Chikamu Chazvino: Kuchera Kuri Kuitika\n"
        f"Chinotevera: Kuisa Casing\n"
        f"Zuva Rekupedzisira: 10/06/2025\n\n"
        "Ungada here kugamuchira zvizere paWhatsApp kana mamiriro achichinja?\nSarudzo: Ehe / Kwete",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'drilling_status_updates_opt_in_shona',
        'user': user.to_dict()
    })

    return {
        'step': 'drilling_status_updates_opt_in_shona',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_pump_status_info_request_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Ndapota taura zita rako rose uye nhamba yereferensi kana nhamba yefoni, mumitsara yakasiyana.\n\n"
            "Muenzaniso:\n"
            "Jane Doe\nREF123456 kana 0771234567\nSarudzo: Harare",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Hazvina Kupihwa"

    user.project_status_request = {
        'type': 'pump',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Waita zvako. Ndapota mira uchiri kutora mamiriro ebasa rako...", user_data['sender'], phone_id)

    send(
        f"Heino mamiriro ebasa rako rekuisa pombi:\n\n"
        f"Zita reProjekiti: Pombi - {full_name}\n"
        f"Chikamu Chazvino: Kuiswa Kwapedzwa\n"
        f"Chinotevera: Kuongorora Kwekupedzisira\n"
        f"Zuva Rekupedzisira: 12/06/2025\n\n"
        "Ungada here kugamuchira zvizere paWhatsApp kana mamiriro achichinja?\nSarudzo: Ehe / Kwete",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'pump_status_updates_opt_in_shona',
        'user': user.to_dict()
    })

    return {
        'step': 'pump_status_updates_opt_in_shona',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def custom_question_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    # You can replace this with your real logic or integration with Gemini, etc.
    response = (
        "Tatambira mubvunzo wenyu. Tichakupindurai nekukurumidza.\n"
        "Kana muchida, dzokai kumenu huru nekutumira 0."
    )
    send(response, user_data['sender'], phone_id)
    return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_main_menu_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Request a quote
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote_shona',
            'user': user.to_dict()
        })
        send("ndapota taura nzvimbo yako (Guta/Dhorobha kana GPS coordinates) kuti titange.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Search Price Using Location
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote_shona',
            'user': user.to_dict()
        })
        send(
           "Kuti tikupe mutengo, ndapota taura nzvimbo yako (Guta/Dhorobha kana GPS coordinates):",
            user_data['sender'], phone_id
        )
        return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Check Project Status
        update_user_state(user_data['sender'], {
            'step': 'check_project_status_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Ndapota sarudza imwe yesarudzo:\n"
            "1. Tarisa mamiriro ekuchera borehole\n"
            "2. Tarisa mamiriro ekuisa pombi\n"
            "3. Taura nemunhu\n"
            "4. Menu huru",
            user_data['sender'], phone_id
        )
        return {'step': 'check_project_status_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        update_user_state(user_data['sender'], {
            'step': 'faq_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Ndapota sarudza chikamu chemibvunzo:\n\n"
            "1. Mibvunzo Inowanzo bvunzwa nezve Borehole Drilling\n"
            "2. Mibvunzo Inowanzo bvunzwa nezve Pump Installation\n"
            "3. Bvunza mumwe mubvunzo\n"
            "4. Taura nemunhu\n"
            "5. Menu huru",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Other Services
        update_user_state(user_data['sender'], {
            'step': 'other_services_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Kugamuchirwa kune mamwe masevhisi eBorehole. Ndeupi sevhisi yaunoda?\n"
            "1. Borehole Deepening\n"
            "2. Borehole Flushing\n"
            "3. PVC Casing Pipe Selection\n"
            "4. Dzokera kuMenu huru",
            user_data['sender'], phone_id
        )
        return {'step': 'other_services_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
        
    elif prompt == "6":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent_shona',
            'user': user.to_dict(),
            'original_prompt': prompt
        })
        return human_agent_shona(prompt, {
            'step': 'human_agent_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }, phone_id)
    
    else:
        send("Ndapota sarudza sarudzo inoshanda (1-6).", user_data['sender'], phone_id)
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def human_agent_shona(prompt, user_data, phone_id):
    customer_number = user_data['sender']
    
    send("Ndiri kukubatanidza kune mumwe wevashandi vedu...", customer_number, phone_id)
    
    agent_number = "+263719835124"
    agent_message = f"Mutengi mutsva kubva ku {customer_number}\nMharidzo: {prompt}"
    threading.Thread(target=send, args=(agent_message, agent_number, phone_id)).start()
    
    def send_fallback():
        user_data = get_user_state(customer_number)
        if user_data and user_data.get('step') in ['human_agent_shona', 'waiting_for_human_agent_response_shona']:
            send("Kana usati wafonerwa, unogona kutifonera pa +263719835124", customer_number, phone_id)
            send("Unoda here:\n1. Kudzokera kumenu huru\n2. Kuramba wakamirira", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'human_agent_followup_shona',
                'user': user_data.get('user', {}),
                'sender': customer_number
            })
    
    threading.Timer(10, send_fallback).start()
    
    update_user_state(customer_number, {
        'step': 'waiting_for_human_agent_response_shona',
        'user': user_data.get('user', {}),
        'sender': customer_number,
        'waiting_since': time.time()
    })
    
    return {'step': 'waiting_for_human_agent_response_shona', 'user': user_data.get('user', {}), 'sender': customer_number}


def notify_agent_shona(customer_number, prompt, agent_number, phone_id):
    agent_message = (
        f"👋 Chikumbiro chitsva chevatengi paWhatsApp\n\n"
        f"📱 Nhamba: {customer_number}\n"
        f"📩 Mharidzo: \"{prompt}\""
    )
    send(agent_message, agent_number, phone_id)

def handle_main_menu_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Kukumbira quotation
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote_shona',
            'user': user.to_dict()
        })
        send("ndapota isa nzvimbo yako (Guta/Dhorobha kana GPS coordinates) kuti titange.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Tsvaga Mutengo Uchishandisa Nzvimbo
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote_shona',
            'user': user.to_dict()
        })
        send(
           "Kuti tikupe mutengo, ndapota isa nzvimbo yako (Guta/Dhorobha kana GPS coordinates):",
            user_data['sender'], phone_id
        )
        return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Tarisa Mamiriro ePurojekiti
        update_user_state(user_data['sender'], {
            'step': 'check_project_status_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Ndapota sarudza sarudzo:\n"
            "1. Tarisa mamiriro ekuchera bhorehole\n"
            "2. Tarisa mamiriro ekuisa pombi\n"
            "3. Taura nemumiriri wevanhu\n"
            "4. Dzokera kuMenu Huru",
            user_data['sender'], phone_id
        )
        return {'step': 'check_project_status_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        update_user_state(user_data['sender'], {
            'step': 'faq_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Ndapota sarudza chikamu cheFAQ:\n\n"
            "1. FAQ dzeBorehole Drilling\n"
            "2. FAQ dzePump Installation\n"
            "3. Bvunza mubvunzo wakasiyana\n"
            "4. Taura nemumiriri wevanhu\n"
            "5. Dzokera kuMenu Huru",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Zvimwe Zvatinoita
        update_user_state(user_data['sender'], {
            'step': 'other_services_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Kugamuchirwa kune Zvimwe Zvatinobata Nezvemaborehole. Ndeupi sevhisi yaunoda?\n"
            "1. Borehole Deepening\n"
            "2. Borehole Flushing\n"
            "3. PVC Casing Pipe Selection\n"
            "4. Dzokera kuMenu Huru",
            user_data['sender'], phone_id
        )
        return {'step': 'other_services_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
        
    elif prompt == "6":  # Taura neMunhu
        update_user_state(user_data['sender'], {
            'step': 'human_agent_shona',
            'user': user.to_dict(),
            'original_prompt': prompt
        })
        return human_agent_shona(prompt, {
            'step': 'human_agent_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }, phone_id)
    
    else:
        send("Ndapota sarudza sarudzo inoshanda (1-6).", user_data['sender'], phone_id)
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def human_agent_shona(prompt, user_data, phone_id):
    customer_number = user_data['sender']
    
    # 1. Notify customer immediately
    send("Tiri kukubatanidza nemumiriri wevanhu...", customer_number, phone_id)
    
    # 2. Notify agent in background
    agent_number = "+263719835124"
    agent_message = f"Mutengi mutsva kubva ku {customer_number}\nMharidzo: {prompt}"
    threading.Thread(target=notify_agent_shona, args=(customer_number, prompt, agent_number, phone_id)).start()
    
    # 3. After 10 seconds, send fallback options
    def send_fallback():
        user_data = get_user_state(customer_number)
        if user_data and user_data.get('step') in ['human_agent_shona', 'waiting_for_human_agent_response_shona']:
            send("Kana musati maburitswa, mungatifonera pa +263719835124", customer_number, phone_id)
            send("Unoda here:\n1. Kudzokera kumenu huru\n2. Kuramba wakamirira", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'human_agent_followup_shona',
                'user': user_data.get('user', {}),
                'sender': customer_number
            })
    
    threading.Timer(10, send_fallback).start()
    
    # 4. Update state to waiting
    update_user_state(customer_number, {
        'step': 'waiting_for_human_agent_response_shona',
        'user': user_data.get('user', {}),
        'sender': customer_number,
        'waiting_since': time.time()
    })
    
    return {'step': 'waiting_for_human_agent_response_shona', 'user': user_data.get('user', {}), 'sender': customer_number}

def handle_enter_location_for_quote_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    # Check if we have a location object from WhatsApp
    if 'location' in user_data and 'latitude' in user_data['location'] and 'longitude' in user_data['location']:
        lat = user_data['location']['latitude']
        lng = user_data['location']['longitude']
        gps_coords = f"{lat},{lng}"
        location_name = reverse_geocode_location(gps_coords)
        
        if location_name:
            user.quote_data['location'] = location_name
            user.quote_data['gps_coords'] = gps_coords
            update_user_state(user_data['sender'], {
                'step': 'select_service_quote_shona',
                'user': user.to_dict()
            })
            send(
                f"Nzvimbo yaonekwa: {location_name.title()}\n\n"
                "Sarudza sevhisi:\n"
                "1. Ongororo yemvura\n"
                "2. Kuchera bhorehole\n"
                "3. Kuiswa kwepombi\n"
                "4. Kuchera maburi ekutengesa\n"
                "5. Borehole Deepening",
                user_data['sender'], phone_id
            )
            return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
        else:
            send("Hatina kukwanisa kuona nzvimbo yako. Ndapota nyora zita reguta/dhorobha rako.", user_data['sender'], phone_id)
            return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        # This is a text message with location name
        location_name = prompt.strip()
        user.quote_data['location'] = location_name.lower()
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote_shona',
            'user': user.to_dict()
        })
        send(
            "Sarudza sevhisi:\n"
            "1. Ongororo yemvura\n"
            "2. Kuchera bhorehole\n"
            "3. Kuiswa kwepombi\n"
            "4. Kuchera maburi ekutengesa\n"
            "5. Borehole Deepening",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_user_message_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    # Example: just echo the message or respond in Shona
    response = "Mharidzo yenyu yagamuchirwa. Tichakupindurai munguva pfupi."
    send(response, user_data['sender'], phone_id)
    return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_select_service_quote_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if not location:
        send("Ndapota taura nzvimbo yako kutanga usati wasarudza sevhisi.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    service_map = {
        "1": "Water Survey",
        "2": "Borehole Drilling",
        "3": "Pump Installation",
        "4": "Commercial Hole Drilling",
        "5": "Borehole Deepening"
    }

    selected_service = service_map.get(prompt.strip())

    if not selected_service:
        send("Sarudzo isiriyo. Ndapota pindura ne 1, 2, 3, 4 kana 5 kusarudza sevhisi.", user_data['sender'], phone_id)
        return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['service'] = selected_service

    if selected_service == "Kuiswa kwepombi":
        update_user_state(user_data['sender'], {
            'step': 'select_pump_option_shona',
            'user': user.to_dict()
        })
        message_lines = [f"💧 Sarudzo dzekuiswa kwepombi:\n"]
        for key, option in pump_installation_options.items():
            desc = option.get('description', 'Hapana tsananguro')
            message_lines.append(f"{key}. {desc}")
        send("\n".join(message_lines), user_data['sender'], phone_id)
        return {'step': 'select_pump_option_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    pricing_message = get_pricing_for_location_quotes_shona(location, selected_service)
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_shona',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'quote_followup_shona',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_select_pump_option_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Sarudzo isiriyo. Ndapota sarudza sarudzo inoshanda yekuiswa kwepombi (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_shona(location, "Kuiswa kwepombi", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_shona',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_shona',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_quote_followup_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt.strip() == "1":
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote_shona',
            'user': user.to_dict()
        })
        send(
            "Sarudza imwe sevhisi:\n"
            "1. Ongororo yemvura\n"
            "2. Kuchera bhorehole\n"
            "3. Kuiswa kwepombi\n"
            "4. Kuchera maburi ekutengesa\n"
            "5. Borehole Deepening",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "2":
        update_user_state(user_data['sender'], {
            'step': 'main_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Tingakubatsira sei nhasi?\n\n"
            "1. Kukumbira quotation\n"
            "2. Tsvaga Mutengo Uchishandisa Nzvimbo\n"
            "3. Tarisa Mamiriro ePurojekiti\n"
            "4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Chibhorani\n"
            "5. Zvimwe Zvatinoita\n"
            "6. Taura neMunhu\n\n"
            "Pindura nenhamba (semuenzaniso, 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details_shona',
            'user': user.to_dict()    
        })
        send(
            "Hongu! Unogona kugovera mutengo wako pazasi.\n\n",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sarudzo isiriyo. Pindura 1 kubvunza nezveimwe sevhisi kana 2 kudzokera kumenu huru kana 3 kana uchida kuita mutengo.", user_data['sender'], phone_id)
        return {'step': 'quote_followup_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_menu_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user']) 

    if prompt == "1":  # FAQ dzeBorehole Drilling
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole_shona',
            'user': user.to_dict()
        })
        send(
            "Heano mibvunzo inowanzo bvunzwa nezve kuchera bhorehole:\n\n"
            "1. Marii kuchera bhorehole?\n"
            "2. Zvinotora nguva yakareba sei kuchera bhorehole?\n"
            "3. Bhorehole rinoenda kudzika sei?\n"
            "4. Ndinoda mvumo here kuchera bhorehole?\n"
            "5. Munoita ongororo yemvura nekuchera panguva imwe chete here?\n"
            "6. Ko kana mukaita ongororo yemvura mukasawana mvura?\n"
            "7. Ndezvipi zvishandiso zvaunoshandisa?\n"
            "8. Dzokera kuFAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # FAQ dzePump Installation
        update_user_state(user_data['sender'], {
            'step': 'faq_pump_shona',
            'user': user.to_dict()
        })
        send(
            "Heano mibvunzo inowanzo bvunzwa nezve kuiswa kwepombi:\n\n"
            "1. Musiyano uripi pakati pepombi dzesolar nedzemagetsi?\n"
            "2. Mungaisa kana ndine zvinhu zvacho here?\n"
            "3. Zvinotora nguva yakareba sei kuiswa kwepombi?\n"
            "4. Ndinoda pombi yakakura sei?\n"
            "5. Munotengesa matangi nematanda here?\n"
            "6. Dzokera kuFAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Bvunza mubvunzo wakasiyana
        update_user_state(user_data['sender'], {
            'step': 'custom_question_shona',
            'user': user.to_dict()
        })
        send(
            "Ndapota nyora mubvunzo wako pazasi, uye tichaedza kukubatsira.\n",
            user_data['sender'], phone_id
        )
        return {'step': 'custom_question_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # Taura nemumiriri wevanhu
        update_user_state(user_data['sender'], {
            'step': 'human_agent_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        })
        send("Ndapota mira uchibatanidzwa nemumiriri...", user_data['sender'], phone_id)
        return {'step': 'human_agent_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Dzokera kuMenu Huru
        return handle_select_language("2", user_data, phone_id)

    else:
        send("Ndapota sarudza sarudzo inoshanda (1–5).", user_data['sender'], phone_id)
        return {'step': 'faq_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_check_project_status_menu_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'drilling_status_info_request_shona',
            'user': user.to_dict()
        })
    
        send(
            "Kutarisa mamiriro ekuchera bhorehole, ndapota taura zvinotevera:\n\n"
            "- Zita rako rose panguva yekubhuka\n"
            "- Nhamba yereferensi yepurojekiti kana nhamba yefoni\n"
            "- Nzvimbo yekuchera (sarudzo)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'pump_status_info_request_shona',
            'user': user.to_dict()
        })
        send(
            "Kutarisa mamiriro ekuiswa kwepombi, ndapota taura zvinotevera:\n\n"
            "- Zita rako rose panguva yekubhuka\n"
            "- Nhamba yereferensi yepurojekiti kana nhamba yefoni\n"
            "- Nzvimbo yekuiswa (sarudzo)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'human_agent_shona',
            'user': user.to_dict()
        })
        send("Ndapota mira uchibatanidzwa nemumwe wevashandi vedu.", user_data['sender'], phone_id)
        return {'step': 'human_agent_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        return handle_main_menu_shona("", user_data, phone_id)

    else:
        send("Sarudzo isiriyo. Ndapota sarudza 1, 2, 3, kana 4.", user_data['sender'], phone_id)
        return {'step': 'check_project_status_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_other_services_menu_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send(
            "Kutarisa kana bhorehole rako rinogona kudzika:\n"
            "Bhorehole rainge rakavharwa:\n"
            "1. Pamusoro chete, ne180mm kana pombi yakakura\n"
            "2. Kubva pamusoro kusvika pasi ne140mm kana pombi diki",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_deepening_casing_shona', 'user': user.to_dict()})
        return {'step': 'borehole_deepening_casing_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send(
            "Dambudziko rauri naro pabhorehole nderei?\n"
            "1. Bhorehole rakadonha\n"
            "2. Bhorehole rine mvura yakasviba",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_flushing_problem_shona', 'user': user.to_dict()})
        return {'step': 'borehole_flushing_problem_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "3":
        send(
            "Tinopa kuchera maborehole tichitevedza PVC casing pipe classes:\n"
            "1. Kirasi 6 - Yakajairika\n"
            "2. Kirasi 9 - Yakasimba\n"
            "3. Kirasi 10 - Yakasimba kwazvo\n"
            "Ndeipi yaunoda kutarisa?",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'pvc_casing_selection_shona', 'user': user.to_dict()})
        return {'step': 'pvc_casing_selection_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "4":
        update_user_state(user_data['sender'], {'step': 'main_menu_shona', 'user': user.to_dict()})
        send_main_menu_shona(user_data['sender'], phone_id)
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza sarudzo inoshanda (1-4).", user_data['sender'], phone_id)
        return {'step': 'other_services_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_main_menu_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Request a quote
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote_shona',
            'user': user.to_dict()
        })
        send("Ndapota isa nzvimbo yako (Guta/Dhorobha kana GPS coordinates) kuti titange.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Search Price Using Location
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote_shona',
            'user': user.to_dict()
        })
        send(
           "Kuti tikupe mutengo, ndapota isa nzvimbo yako (Guta/Dhorobha kana GPS coordinates):",
            user_data['sender'], phone_id
        )
        return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Check Project Status
        update_user_state(user_data['sender'], {
            'step': 'check_project_status_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Ndapota sarudza sarudzo:\n"
            "1. Tarisa mamiriro ekuchera chibhorani\n"
            "2. Tarisa mamiriro ekuisa pombi\n"
            "3. Taura nemumiriri wevanhu\n"
            "4. Dzokera kumenu huru",
            user_data['sender'], phone_id
        )
        return {'step': 'check_project_status_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        update_user_state(user_data['sender'], {
            'step': 'faq_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Ndapota sarudza chikamu chemibvunzo:\n\n"
            "1. Mibvunzo Inowanzo bvunzwa nezvekuchera chibhorani\n"
            "2. Mibvunzo Inowanzo bvunzwa nezvekuisa pombi\n"
            "3. Bvunza mubvunzo wakasiyana\n"
            "4. Taura nemumiriri wevanhu\n"
            "5. Dzokera kumenu huru",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Other Services
        update_user_state(user_data['sender'], {
            'step': 'other_services_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Kugamuchirwa kune mamwe masevhisi ekuchera chibhorani. Ndeipi sevhisi yaunoda?\n"
            "1. Kudzamisa chibhorani\n"
            "2. Kugeza chibhorani\n"
            "3. Kusarudza PVC casing pipe\n"
            "4. Dzokera kumenu huru",
            user_data['sender'], phone_id
        )
        return {'step': 'other_services_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
        
    elif prompt == "6":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent_shona',
            'user': user.to_dict(),
            'original_prompt': prompt
        })
        return human_agent_shona(prompt, {
            'step': 'human_agent_shona',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }, phone_id)
    
    else:
        send("Ndapota sarudza sarudzo inoshanda (1-6).", user_data['sender'], phone_id)
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def human_agent_shona(prompt, user_data, phone_id):
    customer_number = user_data['sender']
    
    send("Tiri kukubatanidza nemumiriri wevanhu...", customer_number, phone_id)
    
    agent_number = "+263719835124"
    agent_message = f"Chikumbiro chitsva kubva kumutengi {customer_number}\nMharidzo: {prompt}"
    threading.Thread(target=send, args=(agent_message, agent_number, phone_id)).start()
    
    def send_fallback():
        user_data = get_user_state(customer_number)
        if user_data and user_data.get('step') in ['human_agent_shona', 'waiting_for_human_agent_response_shona']:
            send("Kana usati wabatikana, unogona kutifonera pa +263719835124", customer_number, phone_id)
            send("Unoda here:\n1. Kudzokera kumenu huru\n2. Kuramba wakamirira", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'human_agent_followup_shona',
                'user': user_data.get('user', {}),
                'sender': customer_number
            })
    
    threading.Timer(10, send_fallback).start()
    
    update_user_state(customer_number, {
        'step': 'waiting_for_human_agent_response_shona',
        'user': user_data.get('user', {}),
        'sender': customer_number,
        'waiting_since': time.time()
    })
    
    return {'step': 'waiting_for_human_agent_response_shona', 'user': user_data.get('user', {}), 'sender': customer_number}

def handle_enter_location_for_quote_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if 'location' in user_data and 'latitude' in user_data['location'] and 'longitude' in user_data['location']:
        lat = user_data['location']['latitude']
        lng = user_data['location']['longitude']
        gps_coords = f"{lat},{lng}"
        location_name = reverse_geocode_location(gps_coords)
        
        if location_name:
            user.quote_data['location'] = location_name
            user.quote_data['gps_coords'] = gps_coords
            update_user_state(user_data['sender'], {
                'step': 'select_service_quote_shona',
                'user': user.to_dict()
            })
            send(
                f"Nzvimbo yaonekwa: {location_name.title()}\n\n"
                "Sarudza sevhisi:\n"
                "1. Ongororo yemvura\n"
                "2. Kuchera chibhorani\n"
                "3. Kuiswa kwepombi\n"
                "4. Kuchera maburi ekushandisa\n"
                "5. Kudzamisa chibhorani",
                user_data['sender'], phone_id
            )
            return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
        else:
            send("Hatina kukwanisa kuziva nzvimbo yako. Ndapota nyora zita reguta/dhorobha rako.", user_data['sender'], phone_id)
            return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        location_name = prompt.strip()
        user.quote_data['location'] = location_name.lower()
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote_shona',
            'user': user.to_dict()
        })
        send(
            "Sarudza sevhisi:\n"
            "1. Ongororo yemvura\n"
            "2. Kuchera chibhorani\n"
            "3. Kuiswa kwepombi\n"
            "4. Kuchera maburi ekushandisa\n"
            "5. Kudzamisa chibhorani",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_select_service_quote_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if not location:
        send("Ndapota taura nzvimbo yako kutanga usati wasarudza sevhisi.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    service_map = {
        "1": "Water Survey",
        "2": "Borehole Drilling",
        "3": "Pump Installation",
        "4": "Commercial Hole Drilling",
        "5": "Borehole Deepening"
    }

    selected_service = service_map.get(prompt.strip())

    if not selected_service:
        send("Sarudzo isiriyo. Ndapota pindura ne1, 2, 3, 4 kana 5 kusarudza sevhisi.", user_data['sender'], phone_id)
        return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['service'] = selected_service

    if selected_service == "Kuiswa kwepombi":
        update_user_state(user_data['sender'], {
            'step': 'select_pump_option_shona',
            'user': user.to_dict()
        })
        message_lines = [f"💧 Sarudzo dzekuiswa kwepombi:\n"]
        for key, option in pump_installation_options.items():
            desc = option.get('description', 'Hapana tsananguro')
            message_lines.append(f"{key}. {desc}")
        send("\n".join(message_lines), user_data['sender'], phone_id)
        return {'step': 'select_pump_option_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    pricing_message = get_pricing_for_location_quotes_shona(location, selected_service)
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_shona',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'quote_followup_shona',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_select_pump_option_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Sarudzo isiriyo. Ndapota sarudza sarudzo inoshanda yekuiswa kwepombi (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_shona(location, "Kuiswa kwepombi", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_shona',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_shona',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_quote_followup_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt.strip() == "1":
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote_shona',
            'user': user.to_dict()
        })
        send(
            "Sarudza imwe sevhisi:\n"
            "1. Ongororo yemvura\n"
            "2. Kuchera chibhorani\n"
            "3. Kuiswa kwepombi\n"
            "4. Kuchera maburi ekushandisa\n"
            "5. Kudzamisa chibhorani",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "2":
        update_user_state(user_data['sender'], {
            'step': 'main_menu_shona',
            'user': user.to_dict()
        })
        send(
            "Tinokubatsira sei nhasi?\n\n"
            "1. Kukumbira quotation\n"
            "2. Tsvaga Mutengo Uchishandisa Nzvimbo\n"
            "3. Tarisa Mamiriro ePurojekiti\n"
            "4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Kuchibhorani\n"
            "5. Zvimwe Zvatinoita\n"
            "6. Taura neMunhu\n\n"
            "Pindura nenhamba (semuenzaniso, 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details_shona',
            'user': user.to_dict()    
        })
        send(
            "Hongu! Unogona kutipa mutengo wako.\n\n",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sarudzo isiriyo. Pindura 1 kubvunza nezveimwe sevhisi kana 2 kudzokera kumenu huru kana 3 kana uchida kupa mutengo.", user_data['sender'], phone_id)
        return {'step': 'quote_followup_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_borehole_deepening_casing_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send("chibhorani rako rinokodzera kudzamiswa.\nNdapota isa nzvimbo yako (dhorobha, wadhi, growth point, kana GPS pin):",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'deepening_location_shona', 'user': user.to_dict()})
        return {'step': 'deepening_location_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send(
            "Tine hurombo, machibhorani akavharirwa kubva kumusoro kusvika pasi nemapombi madiki pane 180mm haakwanisi kudzamiswa.\n"
            "Sarudzo:\n"
            "1. Dzokera kune mamwe masevhisi\n"
            "2. Taura nerutsigiro",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'deepening_no_deepening_options_shona', 'user': user.to_dict()})
        return {'step': 'deepening_no_deepening_options_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza sarudzo inoshanda (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'borehole_deepening_casing_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_deepening_no_deepening_options_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        return handle_other_services_menu_shona("0", user_data, phone_id)

    elif choice == "2":
        send("Tiri kukubatanidza nerutsigiro...", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'human_agent_shona', 'user': user.to_dict()})
        return {'step': 'human_agent_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza sarudzo inoshanda (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_no_deepening_options_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_deepening_location_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.quote_data['location'] = location
    price = get_pricing_for_location_quotes_shona(location, "borehole_deepening")

    send(
        f"Mutengo wekudzamisa mu {location} unotanga kubva kuUSD {price} pamita.\n"
        "Unoda here:\n"
        "1. Simbisa & Bhuka Basa\n"
        "2. Dzokera kune mamwe masevhisi",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'deepening_booking_confirm_shona', 'user': user.to_dict()})
    return {'step': 'deepening_booking_confirm_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_deepening_booking_confirm_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Ndapota tipe zita rako rizere:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name_shona', 'user': user.to_dict()})
        return {'step': 'booking_full_name_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu_shona("0", user_data, phone_id)

    else:
        send("Ndapota sarudza sarudzo inoshanda (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_booking_confirm_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_borehole_flushing_problem_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send(
            "Unonzwa here dhayamita yechibhorani?\n"
            "1. 180mm kana kupfuura\n"
            "2. Pakati pe140mm ne180mm\n"
            "3. 140mm kana kushoma",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'flushing_collapsed_diameter_shona', 'user': user.to_dict()})
        return {'step': 'flushing_collapsed_diameter_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send("Ndapota isa nzvimbo yako kuti titarise mutengo:", user_data['sender'], phone_id)
        user.quote_data['flushing_type'] = 'dirty_water'
        update_user_state(user_data['sender'], {'step': 'flushing_location_shona', 'user': user.to_dict()})
        return {'step': 'flushing_location_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza sarudzo inoshanda (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'borehole_flushing_problem_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_flushing_collapsed_diameter_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    diameter_map = {
        "1": "180mm_or_larger",
        "2": "between_140_and_180mm",
        "3": "140mm_or_smaller"
    }

    diameter = diameter_map.get(choice)
    if not diameter:
        send("Ndapota sarudza sarudzo inoshanda (1-3).", user_data['sender'], phone_id)
        return {'step': 'flushing_collapsed_diameter_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['flushing_type'] = 'collapsed'
    user.quote_data['diameter'] = diameter

    if diameter == "180mm_or_larger":
        send("Tinogona kugeza chibhorani rako tichishandisa matanda ane drilling bit (zvinoshanda zviri nani).\nNdapota isa nzvimbo yako kuti titarise mutengo:",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'flushing_location_shona', 'user': user.to_dict()})
        return {'step': 'flushing_location_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif diameter == "between_140_and_180mm":
        send("Tinogona kugeza chibhorani nematanho, pasina drilling bit.\nNdapota isa nzvimbo yako kuti titarise mutengo:",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'flushing_location_shona', 'user': user.to_dict()})
        return {'step': 'flushing_location_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif diameter == "140mm_or_smaller":
        send("Tinogona kugeza chibhorani tichishandisa matanda chete (pasina drilling bit).\nNdapota isa nzvimbo yako kuti titarise mutengo:",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'flushing_location_shona', 'user': user.to_dict()})
        return {'step': 'flushing_location_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_flushing_location_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.quote_data['location'] = location
    flushing_type = user.quote_data.get('flushing_type')
    diameter = user.quote_data.get('diameter')
    price = get_pricing_for_other_services_shona(location, "borehole_flushing", {
        'flushing_type': flushing_type,
        'diameter': diameter
    })

    send(
        f"Mutengo wekugeza mu {location} unotanga kubva kuUSD {price}.\n"
        "Unoda here:\n"
        "1. Simbisa & Bhuka Basa\n"
        "2. Dzokera kune mamwe masevhisi",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'flushing_booking_confirm_shona', 'user': user.to_dict()})
    return {'step': 'flushing_booking_confirm_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_flushing_booking_confirm_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Ndapota tipe zita rako rizere:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name_shona', 'user': user.to_dict()})
        return {'step': 'booking_full_name_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu_shona("0", user_data, phone_id)

    else:
        send("Ndapota sarudza sarudzo inoshanda (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'flushing_booking_confirm_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_pvc_casing_selection_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()
    pvc_map = {
        "1": "Class 6 - Yakajairwa",
        "2": "Class 9 - Yakasimba",
        "3": "Class 10 - Yakasimba zvikuru"
    }

    casing_class = pvc_map.get(choice)
    if not casing_class:
        send("Ndapota sarudza sarudzo inoshanda (1-3).", user_data['sender'], phone_id)
        return {'step': 'pvc_casing_selection_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['pvc_casing_class'] = casing_class

    send(f"Mutengo we{casing_class} PVC casing unoenderana nenzvimbo yako.\nNdapota isa nzvimbo yako:",
         user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'pvc_casing_location_shona', 'user': user.to_dict()})
    return {'step': 'pvc_casing_location_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_pvc_casing_location_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.quote_data['location'] = location
    casing_class = user.quote_data.get('pvc_casing_class')
    price = get_pricing_for_other_services_shona(location, "pvc_casing", {'class': casing_class})

    send(
        f"Mutengo we{casing_class} PVC casing mu {location} iUSD {price}.\n"
        "Unoda here:\n"
        "1. Simbisa & Bhuka\n"
        "2. Dzokera kune mamwe masevhisi",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'pvc_casing_booking_confirm_shona', 'user': user.to_dict()})
    return {'step': 'pvc_casing_booking_confirm_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_pvc_casing_booking_confirm_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Ndapota tipe zita rako rizere:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name_shona', 'user': user.to_dict()})
        return {'step': 'booking_full_name_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu_shona("0", user_data, phone_id)

    else:
        send("Ndapota sarudza sarudzo inoshanda (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'pvc_casing_booking_confirm_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_collect_quote_details_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if 'location' not in user.quote_data:
        user.quote_data['location'] = prompt.strip()
        update_user_state(user_data['sender'], {
            'step': 'quote_response_shona',
            'user': user.to_dict()
        })
        send(
            "Ndatenda. Zvino taura chigadzirwa chauri kuda, kana mamwe mashoko ane chekuita nebasa rauri kuda kuti tikwanise kukupa mutengo wakakodzera.",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_response_shona', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(
            "Ndapota nyora nzvimbo yako yakajeka (Guta, kanzuru kana GPS).",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_quote_details_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def quote_response_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    user.quote_data['details'] = prompt.strip()

    # Simulate sending the quote request (e.g. storing in DB or notifying team)
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_shona',
        'user': user.to_dict()
    })

    send(
        "Ndatenda! Tichakupai mutengo wakatarwa tichitarisa nzvimbo yako uye mashoko awakapa. ",
        user_data['sender'], phone_id
    )
    send(
        "Ungade:\n"
        "1. Kukumbira imwe quote\n"
        "2. Kudzokera kuMain Menu",
        user_data['sender'], phone_id
    )

    return {'step': 'quote_followup_shona', 'user': user.to_dict(), 'sender': user_data['sender']}


def quote_followup_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send(
            "Sarudza sevhisi yaunoda:\n"
            "1. Water survey\n"
            "2. Borehole drilling\n"
            "3. Pump installation\n"
            "4. Commercial hole drilling\n"
            "5. Borehole Deepening",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza 1 kana 2.", user_data['sender'], phone_id)
        return {'step': 'quote_followup_shona', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_full_name_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    full_name = prompt.strip()
    user.booking_data['full_name'] = full_name
    send("Ndapota tipe nhamba yako yefoni:", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_phone_shona', 'user': user.to_dict()})
    return {'step': 'booking_phone_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_phone_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    phone = prompt.strip()
    user.booking_data['phone'] = phone
    send("Ndapota isa nzvimbo yako chaiyo/kero kana kugovera GPS pin yako:", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_location_shona', 'user': user.to_dict()})
    return {'step': 'booking_location_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_location_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.booking_data['location'] = location
    send("Ndapota isa zuva raunoda kubhukira (semuenzaniso, 2024-10-15):", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_date_shona', 'user': user.to_dict()})
    return {'step': 'booking_date_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_date_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    booking_date = prompt.strip()
    user.booking_data['date'] = booking_date
    send("Kana uine zvimwe zvaunoda kutaura, ndapota zvisa izvozvi. Kana zvisina, nyora 'Hapana':", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_notes_shona', 'user': user.to_dict()})
    return {'step': 'booking_notes_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_notes_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    notes = prompt.strip()
    user.booking_data['notes'] = notes if notes.lower() != 'hapana' else ''
    booking_confirmation_number = save_booking(user.booking_data)

    send(
        f"Tatenda {user.booking_data['full_name']}! Bhuku rako rasimbiswa.\n"
        f"Reference Nhamba: {booking_confirmation_number}\n"
        "Timu yedu ichakubata munguva pfupi.\n"
        "Nyora 'menu' kudzokera kumenu huru.",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'main_menu_shona', 'user': user.to_dict()})
    return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_other_services_menu_shona(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send(
            "Kuti titarise kana chibhorani rako richikwanisa kudzamiswa:\n"
            "chibhorani racho rakavharirwa:\n"
            "1. Pamusoro chete, ne180mm kana kupfuura dhayamita pipe\n"
            "2. Kubva kumusoro kusvika pasi ne140mm kana kushoma dhayamita pipe",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_deepening_casing_shona', 'user': user.to_dict()})
        return {'step': 'borehole_deepening_casing_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send(
            "Dambudziko ripi rine chibhorani rako?\n"
            "1. chibhorani Rakapunzika\n"
            "2. chibhorani Rine Mvura Yakasviba",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_flushing_problem_shona', 'user': user.to_dict()})
        return {'step': 'borehole_flushing_problem_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "3":
        send(
            "Tinopa kuchera machibhorani achitevedza PVC casing pipe makirasi:\n"
            "1. Class 6 - Yakajairwa\n"
            "2. Class 9 - Yakasimba\n"
            "3. Class 10 - Yakasimba zvikuru\n"
            "Ndeipi yaunoda kutarisa?",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'pvc_casing_selection_shona', 'user': user.to_dict()})
        return {'step': 'pvc_casing_selection_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "4":
        update_user_state(user_data['sender'], {'step': 'main_menu_shona', 'user': user.to_dict()})
        send_main_menu_shona(user_data['sender'], phone_id)
        return {'step': 'main_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza sarudzo inoshanda (1-4).", user_data['sender'], phone_id)
        return {'step': 'other_services_menu_shona', 'user': user.to_dict(), 'sender': user_data['sender']}

def send_main_menu_shona(phone_number, phone_id):
    menu_text = (
        "Tinokubatsira sei nhasi?\n\n"
        "1. Kukumbira quotation\n"
        "2. Tsvaga Mutengo Uchishandisa Nzvimbo\n"
        "3. Tarisa Mamiriro ePurojekiti\n"
        "4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Kuchibhorani\n"
        "5. Zvimwe Zvatinoita\n"
        "6. Taura neMunhu\n\n"
        "Pindura nenhamba (semuenzaniso, 1)"
    )
    send(menu_text, phone_number, phone_id)


#-----------------------------------------------------NDEBELE-------------------------------------------------------------------------

location_pricing_ndebele = {
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
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 30
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

pump_installation_options_ndebele = {
    "1": {
        "description": "I-solar ye-DC (ngqo kusolar AKUKHO inverter) - Nginethangi kanye nestendi yetangi",
        "price": 1640
    },
    "2": {
        "description": "I-solar ye-DC (ngqo kusolar AKUKHO inverter) - Anginalutho",
        "price": 2550
    },
    "3": {
        "description": "I-solar ye-DC (ngqo kusolar AKUKHO inverter) - Umsebenzi kuphela",
        "price": 200
    },
    "4": {
        "description": "I-AC electric (ZESA noma i-solar inverter) - Lungisa futhi unikeze",
        "price": 1900
    },
    "5": {
        "description": "I-AC electric (ZESA noma i-solar inverter) - Umsebenzi kuphela",
        "price": 170
    },
    "6": {
        "description": "I-AC electric (ZESA noma i-solar inverter) - Nginethangi kanye nestendi yetangi",
        "price": 950
    }
}


def get_pricing_for_location_quotes_ndebele(location, service_type, pump_option_selected=None):
    location_key = location.strip().lower()
    service_key = service_type.strip().title()  # Normalize e.g. "Pump Installation"

    # Handle Pump Installation separately
    if service_key == "Pump Installation":
        if pump_option_selected is None:            
            message_lines = [f"💧 Izinketho Zokufaka I-Pump:\n"]
            for key, option in pump_installation_options.items():
                desc = option.get('description', 'Akukho ncazelo')
                message_lines.append(f"{key}. {desc}")
            return "\n".join(message_lines)
        else:
            option = pump_installation_options.get(pump_option_selected)
            if not option:
                return "Uxolo, inketho yokufaka i-pump ayilungile."
            desc = option.get('description', 'Akukho ncazelo')
            price = option.get('price', 'Akutholakali')
            message = f"💧 Intengo yenketho {pump_option_selected}:\n{desc}\nIntengo: ${price}\n"
            message += "\nUngathanda uk:\n1. Buzela intengo yenye inkonzo\n2. Buyela kumenyu eyinhloko\n3. Nika intengo"
            return message

    # Rest of the function remains the same...
    loc_data = location_pricing.get(location_key)
    if not loc_data:
        return "Uxolo, intengo ayitholakali kule ndawo."

    price = loc_data.get(service_key)
    if not price:
        return f"Uxolo, intengo ye-{service_key} ayitholakali e-{location.title()}."

    # Format complex pricing dicts nicely
    if isinstance(price, dict):
        included_depth = price.get("included_depth_m", "Akutholakali")
        extra_rate = price.get("extra_per_m", "Akutholakali")

        classes = {k: v for k, v in price.items() if k.startswith("class")}
        message_lines = [f"Intengo ye-{service_key} e-{location.title()}:"]
        for cls, amt in classes.items():
            message_lines.append(f"- {cls.title()}: ${amt}")
        message_lines.append(f"- Ifaka ubude kuze kufike ku-{included_depth}m")
        message_lines.append(f"- Intengo eyengeziwe: ${extra_rate}/m ngemva kobude obufakiwe\n")
        message_lines.append("Ungathanda uk:\n1. Buzela intengo yenye inkonzo\n2. Buyela kumenyu eyinhloko\n3. Nika intengo")
        return "\n".join(message_lines)

    # Flat rate or per meter pricing
    unit = "ngemitha ngayinye" if service_key in ["Commercial Hole Drilling", "Borehole Deepening"] else "intengo esisodwa"
    return (f"{service_key} e-{location.title()}: ${price} {unit}\n\n"
            "Ungathanda uk:\n1. Buzela intengo yenye inkonzo\n2. Buyela kumenyu eyinhloko\n3. Nika intengo")


def handle_collect_quote_details_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    responses = prompt.split('\n')
    if len(responses) >= 4:
        user.quote_data.update({
            'location': responses[0].strip(),
            'depth': responses[1].strip(),
            'purpose': responses[2].strip(),
            'water_survey': responses[3].strip(),
            'casing_type': responses[5].strip() if len(responses) > 5 else "Akuzange kuchazwe"
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
            'step': 'quote_response_ndebele',
            'user': user.to_dict()
        })
        estimate = "Class 6: Inanela engu-$2500\nIhlanganisa ukubhoboza, PVC casing engu-140mm"
        send(
            f"Siyabonga! Ngokusekelwe kulokho onikezileyo:\n\n"
            f"{estimate}\n\n"
            f"Qaphela: I-double casing iyakhokhwa ngokwehlukile uma kudingeka, ngemvume yakho\n\n"
            f"Ungathanda ukwenza lokhu:\n"
            f"1. Nikeza inani lakho?\n"
            f"2. Bhukha i-Site Survey\n"
            f"3. Bhukha i-Borehole Drilling\n"
            f"4. Khuluma loMmeli womuntu",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_response_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela unikeze lonke ulwazi oludingakalayo (okungenani imigqa emi-4).", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_user_message_ndebele(prompt, user_data, phone_id):
    if user_data.get('step') == 'human_agent_followup_ndebele':
        if prompt.strip() == '1':
            # Return to main menu
            update_user_state(user_data['sender'], {
                'step': 'main_menu_ndebele',
                'user': user_data['user']
            })
            send_main_menu(user_data['sender'], phone_id)
        elif prompt.strip() == '2':
            # Continue waiting
            send("Sizolokhu sizama ukukuxhumanisa. Siyabonga ngokubekezela kwakho.", user_data['sender'], phone_id)
            update_user_state(user_data['sender'], {
                'step': 'waiting_for_human_agent_response_ndebele',
                'user': user_data['user']
            })
        else:
            send("Sicela ukhethe u-1 noma u-2", user_data['sender'], phone_id)
    
    return user_data


def human_agent_followup_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        return handle_select_language("1", user_data, phone_id)

    elif prompt == "2":
        send("Kulungile. Uxolo ukubuza uma udinga okunye.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela uphendule ngo-1 ukuya kumenyu oyinhloko noma u-2 uhlale lapha.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_main_menu_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Request a quote
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote_ndebele',
            'user': user.to_dict()
        })
        send("Sicela ufake indawo yakho (Idolobha/Itawuni noma ama-GPS coordinates) ukuze siqale.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Search Price Using Location
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote_ndebele',
            'user': user.to_dict()
        })
        send(
            "Ukuze sikutholele intengo, sicela ufake indawo yakho (Idolobha/Itawuni noma ama-GPS coordinates):",
            user_data['sender'], phone_id
        )
        return {'step': 'enter_location_for_quote_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Check Project Status
        update_user_state(user_data['sender'], {
            'step': 'check_project_status_menu_ndebele',
            'user': user.to_dict()
        })
        send(
            "Sicela ukhethe okuthile:\n"
            "1. Bheka isimo sokubha ibhorehole\n"
            "2. Bheka isimo sokufakwa kwepompi\n"
            "3. Khuluma nomuntu\n"
            "4. Ibhodle elikhulu",
            user_data['sender'], phone_id
        )
        return {'step': 'check_project_status_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        update_user_state(user_data['sender'], {
            'step': 'faq_menu_ndebele',
            'user': user.to_dict()
        })
        send(
            "Sicela ukhethe isigaba semibuzo:\n\n"
            "1. Imibuzo Evame Ukubuzwa Mayelana Nokubha Ibhorehole\n"
            "2. Imibuzo Evame Ukubuzwa Mayelana Nokufakwa Kwepompi\n"
            "3. Buza omunye umbuzo\n"
            "4. Khuluma nomuntu\n"
            "5. Ibhodle elikhulu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Other Services
        update_user_state(user_data['sender'], {
            'step': 'other_services_menu_ndebele',
            'user': user.to_dict()
        })
        send(
            "Wamukelekile kwezinye izinsiza zobhorehole. Yisiphi isevisi oyidingayo?\n"
            "1. Ukujulisa Ibhorehole\n"
            "2. Ukuhlanza Ibhorehole\n"
            "3. Ukukhetha I-PVC Casing Pipe\n"
            "4. Buyela Ebhodleni Elikhulu",
            user_data['sender'], phone_id
        )
        return {'step': 'other_services_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
        
    elif prompt == "6":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent_ndebele',
            'user': user.to_dict(),
            'original_prompt': prompt
        })
        return human_agent_ndebele(prompt, {
            'step': 'human_agent_ndebele',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }, phone_id)
    
    else:
        send("Sicela ukhethe okulungile (1-6).", user_data['sender'], phone_id)
        return {'step': 'main_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_quote_response_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Offer price
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details_ndebele',
            'user': user.to_dict()
        })
        send(
            "Kulungile! Unganikezela ngamanani owaphakamisayo ngezansi.\n\n"
            "Sicela uphendule ulandele le fomethi:\n\n"
            "- Ukuhlolwa kwamanzi: $_\n"
            "- Ukubhoboza umthombo: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "2":  # Book site survey
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info_ndebele',
            'user': user.to_dict()
        })
        send(
            "Kuhle! Sicela unikeze imininingwane elandelayo ukuze uqedele ukubhukha kwakho:\n\n"
            "- Igama lakho eliphelele:\n"
            "- Usuku olukhethayo (dd/mm/yyyy):\n"
            "- Ikheli lesayithi: GPS noma ikheli:\n"
            "- Inombolo yefoni:\n"
            "- Indlela yokukhokha (Prepayment / Cash at site):\n\n"
            "Thayipha: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "3":  # Book for Drilling
        send("I-ejenti yethu izokuthinta ukuze uqedele ukubhukha kokubhoboza.", user_data['sender'], phone_id)
        return {'step': 'main_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "4":  # Human Agent
        send("Siyakuxhumanisa nommeli womuntu... sicela ulinde.", user_data['sender'], phone_id)
        return {'step': 'human_agent_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        send("Sicela ukhethe inketho evumelekileyo (1-4).", user_data['sender'], phone_id)
        return {'step': 'quote_response_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}



def human_agent_ndebele(prompt, user_data, phone_id):
    customer_number = user_data['sender']
    
    # 1. Notify customer immediately
    send("Ukuxhumanisa nomuntu...", customer_number, phone_id)
    
    # 2. Notify agent in background
    agent_number = "+263719835124"
    agent_message = f"Isicelo esisha somthengi esivela ku-{customer_number}\nUmlayezo: {prompt}"
    threading.Thread(target=send, args=(agent_message, agent_number, phone_id)).start()
    
    # 3. After 10 seconds, send fallback options
    def send_fallback():
        user_data = get_user_state(customer_number)
        if user_data and user_data.get('step') in ['human_agent_ndebele', 'waiting_for_human_agent_response_ndebele']:
            send("Uma ungakaxhunyaniswa, ungasifonela ku-+263719835124", customer_number, phone_id)
            send("Ungathanda:\n1. Buyela ebhodleni elikhulu\n2. Lindela okwengeziwe", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'human_agent_followup_ndebele',
                'user': user_data.get('user', {}),
                'sender': customer_number
            })
    
    threading.Timer(10, send_fallback).start()
    
    # 4. Update state to waiting
    update_user_state(customer_number, {
        'step': 'waiting_for_human_agent_response_ndebele',
        'user': user_data.get('user', {}),
        'sender': customer_number,
        'waiting_since': time.time()
    })
    
    return {'step': 'waiting_for_human_agent_response_ndebele', 'user': user_data.get('user', {}), 'sender': customer_number}

def handle_enter_location_for_quote_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if 'location' in user_data and 'latitude' in user_data['location'] and 'longitude' in user_data['location']:
        lat = user_data['location']['latitude']
        lng = user_data['location']['longitude']
        gps_coords = f"{lat},{lng}"
        location_name = reverse_geocode_location(gps_coords)
        
        if location_name:
            user.quote_data['location'] = location_name
            user.quote_data['gps_coords'] = gps_coords
            update_user_state(user_data['sender'], {
                'step': 'select_service_quote_ndebele',
                'user': user.to_dict()
            })
            send(
                f"Indawo itholakele: {location_name.title()}\n\n"
                "Manje khetha isevisi:\n"
                "1. Ukuhlola amanzi\n"
                "2. Ukubha ibhorehole\n"
                "3. Ukufaka ipompi\n"
                "4. Ukubha imbobo yezohwebo\n"
                "5. Ukujulisa ibhorehole",
                user_data['sender'], phone_id
            )
            return {'step': 'select_service_quote_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
        else:
            send("Asikwazanga ukukhomba indawo yakho. Sicela uthayiphe igama ledolobha/letawuni ngesandla.", user_data['sender'], phone_id)
            return {'step': 'enter_location_for_quote_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        location_name = prompt.strip()
        user.quote_data['location'] = location_name.lower()
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote_ndebele',
            'user': user.to_dict()
        })
        send(
            "Manje khetha isevisi:\n"
            "1. Ukuhlola amanzi\n"
            "2. Ukubha ibhorehole\n"
            "3. Ukufaka ipompi\n"
            "4. Ukubha imbobo yezohwebo\n"
            "5. Ukujulisa ibhorehole",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_select_service_quote_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if not location:
        send("Sicela ufake indawo yakho kuqala ngaphambi kokukhetha isevisi.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    service_map = {
        "1": "Water Survey",
        "2": "Borehole Drilling",
        "3": "Pump Installation",
        "4": "Commercial Hole Drilling",
        "5": "Borehole Deepening"
    }

    selected_service = service_map.get(prompt.strip())

    if not selected_service:
        send("Okungalungile. Sicela uphendule ngo-1, 2, 3, 4 noma 5 ukukhetha isevisi.", user_data['sender'], phone_id)
        return {'step': 'select_service_quote_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['service'] = selected_service

    if selected_service == "Ukufaka ipompi":
        update_user_state(user_data['sender'], {
            'step': 'select_pump_option_ndebele',
            'user': user.to_dict()
        })
        message_lines = [f"💧 Izinketho Zokufaka Ipompi:\n"]
        for key, option in pump_installation_options.items():
            desc = option.get('description', 'No description')
            message_lines.append(f"{key}. {desc}")
        send("\n".join(message_lines), user_data['sender'], phone_id)
        return {'step': 'select_pump_option_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    pricing_message = get_pricing_for_location_quotes_ndebele(location, selected_service)
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_quote_followup_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt.strip() == "1":
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote_ndebele',
            'user': user.to_dict()
        })
        send(
            "Khetha enye isevisi:\n"
            "1. Ukuhlola amanzi\n"
            "2. Ukubha ibhorehole\n"
            "3. Ukufaka ipompi\n"
            "4. Ukubha imbobo yezohwebo\n"
            "5. Ukujulisa ibhorehole",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "2":
        update_user_state(user_data['sender'], {
            'step': 'main_menu_ndebele',
            'user': user.to_dict()
        })
        send(
            "Singakusiza njani namuhla?\n\n"
            "1. Cela isiphakamiso\n"
            "2. Phanda Intengo Ngokusebenzisa Indawo\n"
            "3. Bheka Isimo Sephrojekthi\n"
            "4. Imibuzo Evame Ukubuzwa noma Funda Ngokuqhuba Ibhorehole\n"
            "5. Eminye Imisebenzi\n"
            "6. Khuluma Nomuntu\n\n"
            "Sicela uphendule ngenombolo (umzekeliso: 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details_ndebele',
            'user': user.to_dict()    
        })
        send(
            "Kulungile! Ungabelana ngentengo yakho engezansi.\n\n",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Okungalungile. Phendula ngo-1 ukubuza ngenye isevisi noma u-2 ukubuyela ebhodleni elikhulu noma u-3 uma ufuna ukwenza isiphakamiso sentengo.", user_data['sender'], phone_id)
        return {'step': 'quote_followup_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_select_pump_option_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Okungalungile. Sicela ukhethe inketho elungile yokufaka ipompi (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_ndebele(location, "Ukufaka ipompi", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_check_project_status_menu_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'drilling_status_info_request_ndebele',
            'user': user.to_dict()
        })
    
        send(
            "Ukubheka isimo sakho sokubha ibhorehole, sicela unikeze okulandelayo:\n\n"
            "- Igama eliphelele elisetshenzisiwe ngesikhathi sokubhuka\n"
            "- Inombolo Yereferensi Yephrojekthi noma Inombolo Yocingo\n"
            "- Indawo Yokubha (okungathandeki)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request_ndebele',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'pump_status_info_request_ndebele',
            'user': user.to_dict()
        })
        send(
            "Ukubheka isimo sakho sokufakwa kwepompi, sicela unikeze okulandelayo:\n\n"
            "- Igama eliphelele elisetshenzisiwe ngesikhathi sokubhuka\n"
            "- Inombolo Yereferensi Yephrojekthi noma Inombolo Yocingo\n"
            "- Indawo Yokufakwa (okungathandeki)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request_ndebele',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'human_agent_ndebele',
            'user': user.to_dict()
        })
        send("Sicela ulinde ngenkathi ngikuxhumanisa nomunye wethimba lethu lokusekela.", user_data['sender'], phone_id)
        return {'step': 'human_agent_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        return handle_main_menu_ndebele("", user_data, phone_id)

    else:
        send("Okungalungile. Sicela ukhethe u-1, 2, 3, noma 4.", user_data['sender'], phone_id)
        return {'step': 'check_project_status_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_drilling_status_info_request_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Sicela unikeze okungenani igama lakho eliphelele kanye nenombolo yereferensi noma inombolo yocingo, ngomugqa omusha ngamunye.\n\n"
            "Isibonelo:\n"
            "John Doe\nREF789123 noma 0779876543\nOkungathandeki: Bulawayo",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request_ndebele',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Akunikezwe"

    user.project_status_request = {
        'type': 'drilling',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Ngiyabonga. Sicela ulinde ngenkathi sithola isimo sephrojekthi yakho...", user_data['sender'], phone_id)

    send(
        f"Nansi isimo sephrojekthi yakho yokubha ibhorehole:\n\n"
        f"Igama Lephrojekthi: Ibhorehole - {full_name}\n"
        f"Isigaba Samanje: Ukubha Kuyaqhubeka\n"
        f"Okulandelayo: Ukufaka i-casing\n"
        f"Usuku Lokugcwaliseka Olulindelekile: 10/06/2025\n\n"
        "Ungathatha izibuyekezo ze-WhatsApp lapho isimo sishintsha?\nIzinketho: Yebo / Cha",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'drilling_status_updates_opt_in_ndebele',
        'user': user.to_dict()
    })

    return {
        'step': 'drilling_status_updates_opt_in_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_drilling_status_updates_opt_in_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yebo', 'ye', 'y']:
        send(
            "Kuhle! Manje uzothola izibuyekezo ze-WhatsApp noma nini lapho isimo sokubha ibhorehole sakho sishintsha.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    elif response in ['cha', 'ch', 'n']:
        send(
            "Akunankinga. Ungahlola isimo futhi kamuva uma kudingeka.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ngiyaxolisa, angikwazanga ukukuqonda. Sicela uphendule ngo-Yebo noma Cha.", user_data['sender'], phone_id)
        return {'step': 'drilling_status_updates_opt_in_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_pump_status_info_request_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Sicela unikeze okungenani igama lakho eliphelele kanye nenombolo yereferensi noma inombolo yocingo, ngomugqa omusha ngamunye.\n\n"
            "Isibonelo:\n"
            "Jane Doe\nREF123456\nOkungathandeki: Harare",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request_ndebele',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Akunikezwe"

    user.project_status_request = {
        'type': 'pump',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Ngiyabonga. Sicela ulinde ngenkathi sithola isimo sephrojekthi yakho...", user_data['sender'], phone_id)

    send(
        f"Nansi isimo sephrojekthi yakho yokufakwa kwepompi:\n\n"
        f"Igama Lephrojekthi: Ipompi - {full_name}\n"
        f"Isigaba Samanje: Ukufakwa Kuqediwe\n"
        f"Okulandelayo: Ukuhlolwa Kokugcina\n"
        f"Usuku Lokudluliswa Olulindelekile: 12/06/2025\n\n"
        "Ungathatha izibuyekezo ze-WhatsApp lapho isimo sishintsha?\nIzinketho: Yebo / Cha",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'pump_status_updates_opt_in_ndebele',
        'user': user.to_dict()
    })

    return {
        'step': 'pump_status_updates_opt_in_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_pump_status_updates_opt_in_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yebo', 'ye', 'y']:
        send(
            "Kuhle! Manje uzothola izibuyekezo ze-WhatsApp noma nini lapho isimo sokufakwa kwepompi sakho sishintsha.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    elif response in ['cha', 'ch', 'n']:
        send(
            "Akunankinga. Ungahlola isimo futhi kamuva uma kudingeka.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ngiyaxolisa, angikwazanga ukukuqonda. Sicela uphendule ngo-Yebo noma Cha.", user_data['sender'], phone_id)
        return {'step': 'pump_status_updates_opt_in_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_menu_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user']) 

    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole_ndebele',
            'user': user.to_dict()
        })
        send(
            "Nawa imibuzo evame ukubuzwa mayelana nokubha ibhorehole:\n\n"
            "1. Ibiza malini ukubha ibhorehole?\n"
            "2. Kuthatha isikhathi esingakanani ukubha ibhorehole?\n"
            "3. Ijulile kangakanani ibhorehole yami?\n"
            "4. Ngidinga imvume yokubha ibhorehole?\n"
            "5. Niya hlola amanzi nibha ngasikhathi sinye?\n"
            "6. Yini uma nihlola amanzi ningatholi lutho?\n"
            "7. Yiziphi izinto enizisebenzisayo?\n"
            "8. Buyela Kumenyu Yemibuzo",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Pump Installation FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_pump_ndebele',
            'user': user.to_dict()
        })
        send(
            "Nawa imibuzo evame ukubuzwa mayelana nokufakwa kwepompi:\n\n"
            "1. Umehluko uphi phakathi kwepompi yelanga neyagesi?\n"
            "2. Ungayifaka uma senginazo izinto ezidingekayo?\n"
            "3. Kuthatha isikhathi esingakanani ukufaka ipompi?\n"
            "4. Ngidinga ipompi engakanani?\n"
            "5. Nikhipha amathangi nezindlu zethangi?\n"
            "6. Buyela Kumenyu Yemibuzo",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Ask a different question
        update_user_state(user_data['sender'], {
            'step': 'custom_question_ndebele',
            'user': user.to_dict()
        })
        send(
            "Sicela uthayiphe umbuzo wakho ngezansi, futhi sizozama ukukusiza.\n",
            user_data['sender'], phone_id
        )
        return {'step': 'custom_question_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent_ndebele',
            'user': user.to_dict(),
            'sender': user_data['sender']
        })
        send("Sicela ulinde ngenkathi ngikuxhumanisa nomuntu...", user_data['sender'], phone_id)
        return {'step': 'human_agent_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Back to Main Menu
        return handle_main_menu_ndebele("", user_data, phone_id)

    else:
        send("Sicela ukhethe okulungile (1–5).", user_data['sender'], phone_id)
        return {'step': 'faq_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_borehole_followup_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send(
            "Sicela ukhethe umbuzo:\n\n"
            "1. Ibiza malini ukubha ibhorehole?\n"
            "2. Kuthatha isikhathi esingakanani ukubha ibhorehole?\n"
            "3. Ijulile kangakanani ibhorehole yami?\n"
            "4. Ngidinga imvume yokubha ibhorehole?\n"
            "5. Niya hlola amanzi nibha ngasikhathi sinye?\n"
            "6. Yini uma nihlola amanzi ningatholi lutho?\n"
            "7. Yiziphi izinto enizisebenzisayo?\n"
            "8. Buyela Kumenyu Yemibuzo",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_main_menu_ndebele("", user_data, phone_id)

    else:
        send("Sicela ukhethe u-1 ukubuza omunye umbuzo noma u-2 ukubuyela ebhodleni elikhulu.", user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Amaphampu e-solar asebenzisa amandla elanga futhi afanele izindawo ezingelazibane. Amaphampu e-electric axhomeke ku-ZESA, angabiza kancane ekuqaleni kodwa adinga amandla kagesi aqhubekayo.",
        "2": "Yebo! Silephakheji lomsebenzi kuphela nxa usulezinto zonke ezidingekayo.",
        "3": "Ukufakwa kwepampu kuthatha usuku olulodwa kuphela uma izinto sezilungile futhi indawo ifinyeleleka kalula.",
        "4": "Usayizi wepampu uncika kudinga kwakho kwamanzi kanye lobujula be-borehole. Sizokuhlola ukuze sikunikeze okungcono.",
        "5": "Yebo, sinikezela ngamathangi, ama-tank stands, kanye lezinye izinto ezifanele ukufakwa kwepampu.",
        "6": "Sibuyela kuFAQ Menu..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)

        if prompt == "6":
            return {'step': 'faq_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Ungathanda:\n"
            "1. Ukubuza omunye umbuzo kuPump Installation FAQs\n"
            "2. Ukubuyela kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump_followup_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efaneleyo (1–6).", user_data['sender'], phone_id)
        return {'step': 'faq_pump_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump_followup_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send(
            "Sicela ukhethe umbuzo:\n\n"
            "1. Kuyini umehluko phakathi kwepampu ye-solar leye-electric?\n"
            "2. Lingayifaka yini nxa sengilalezinto zonke?\n"
            "3. Kuthatha isikhathi esingakanani ukufaka ipampu?\n"
            "4. Ngidinga ipampu enkulu kangakanani?\n"
            "5. Linikezela ngamathangi kanye lezindawo zokuwabeka yini?\n"
            "6. Buyela kuFAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("3", user_data, phone_id)

    else:
        send("Sicela ukhethe 1 ukuze ubuze omunye umbuzo noma 2 ukubuyela kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}




def send_main_menu_ndebele(phone_number, phone_id):
    menu_text = (
        "Singakusiza njani namuhla?\n\n"
        "1. Cela isiphakamiso\n"
        "2. Phanda Intengo Ngokusebenzisa Indawo\n"
        "3. Bheka Isimo Sephrojekthi\n"
        "4. Imibuzo Evame Ukubuzwa noma Funda Ngokuqhuba Ibhorehole\n"
        "5. Eminye Imisebenzi\n"
        "6. Khuluma Nomuntu\n\n"
        "Phendula ngenombolo (umzekeliso: 1)"
    )
    send(menu_text, phone_number, phone_id)



def handle_select_pump_option_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Inketho engavumelekile. Sicela ukhethe inketho efanele yokufaka iphampu (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_ndebele(location, "Pump Installation", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }




def handle_pump_status_info_request_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Sicela unikeze okungenani igama lakho eliphelele kanye nenombolo yereferensi noma inombolo yocingo, ngomugqa omusha ngamunye.\n\n"
            "Isibonelo:\n"
            "Jane Doe\nREF123456\nOkungathandeki: Harare",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request_ndebele',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Ayikho"

    user.project_status_request = {
        'type': 'pump',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Ngiyabonga. Sicela ulinde njengoba sithola isimo sephrojekthi yakho...", user_data['sender'], phone_id)

    send(
        f"Nansi isimo sephrojekthi yakho yokufaka iphampu:\n\n"
        f"Igama lephrojekthi: Iphampu - {full_name}\n"
        f"Isigaba samanje: Kuqediwe ukufakwa\n"
        f"Okulandelayo: Ukuhlolwa kokugcina\n"
        f"Usuku olulindeleke ukunikezwa: 12/06/2025\n\n"
        "Ungathanda ukuthola izibuyekezo ze-WhatsApp lapho isimo sishintsha?\nIzinketho: Yebo / Cha",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'pump_status_updates_opt_in_ndebele',
        'user': user.to_dict()
    })

    return {
        'step': 'pump_status_updates_opt_in_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_pump_status_updates_opt_in_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yebo', 'ye', 'y']:
        send(
            "Kuhle! Uzothola izibuyekezo ze-WhatsApp njalo lapho isimo sokubhula ibhorehole sakho sishintsha.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    elif response in ['cha', 'ch', 'n']:
        send(
            "Akunankinga. Ungahlola isimo futhi kamuva uma kudingeka.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ngiyaxolisa, angikwazanga ukuqonda lokho. Sicela uphendule ngo-Yebo noma Cha.", user_data['sender'], phone_id)
        return {'step': 'pump_status_updates_opt_in_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_borehole_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Intengo incike endaweni, ejuleni, kanye nezimo zomhlabathi. Sicela usithumelele indawo yakho kanye nemininingwane yokufinyelela ukuze sikunikeze isilinganiso.",
        "2": "Ngokuvamile amahora angu-4–6 noma kuze kufike ezinsukwini ezimbalwa, kuncike ezimweni zendawo, uhlobo lwedwala, nokufinyeleleka.",
        "3": "Ubujiya buyahluka ngendawo. Ubujiya obujwayelekile bungamamitha angu-40, kodwa amabhorehole angavela kumamitha angu-40 kuya kwayi-150 kuncike kuthebula lwamanzi angaphansi komhlaba.",
        "4": "Kwezinye izindawo, kungadingeka imvume yamanzi. Singakusiza ngesicelo uma kunesidingo.",
        "5": "Yebo, sinikela kokubili njengephakathi noma ngokwahlukana, kuncike okukhethwa wena.",
        "6": "Uma umthengi efuna ukubhula endaweni yesibili, sinikela ngesaphulelo.\n\nQaphela: Imishini yokuhlola ithola ukuhlukana komhlaba okuthwala amanzi noma amaphoyinti wokuhlangana kwemifudlana yangaphansi komhlaba. Kodwa, ayikwazi ukukala inani noma ijubane lamanzi. Ngakho-ke, ukubhula ibhorehole akunasiqinisekiso esingu-100% sokuthola amanzi, njengoba ukuhlukana kungaba komile, kunomswakama, noma kunamanzi.",
        "7": "Sisebenzisa imishini yokubhula ye-rotary ne-percussion, amathuluzi e-GPS, nemishini yokuhlola imininingwane yomhlaba.",
        "8": "Ibuyela kumenyu yemibuzo..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Ungathanda:\n"
            "1. Buza omunye umbuzo kumibuzo ejwayelekile yokubhula ibhorehole\n"
            "2. Buyela ebhodini enkulu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_followup_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efanele (1–8).", user_data['sender'], phone_id)
        return {'step': 'faq_borehole_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_select_service_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    services = {
        "1": "Water survey",
        "2": "Borehole drilling",
        "3": "Pump installation",
        "4": "Commercial hole drilling",
        "5": "Borehole Deepening",
    }
    if prompt in services:
        user.quote_data['service'] = services[prompt]
        update_user_state(user_data['sender'], {
            'step': 'collect_quote_details_ndebele',
            'user': user.to_dict()
        })
        send(
            "Ukuze sikunike isilinganiso, sicela uphendule lokhu okulandelayo:\n\n"
            "1. Indawo okuyo (Idolobha/Idolobhana noma i-GPS):\n",
            user_data['sender'], phone_id
        )
        return {'step': 'handle_select_service_quote_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ukhethe inketho evumelekileyo (1-5).", user_data['sender'], phone_id)
        return {'step': 'select_service_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_select_pump_option_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Inketho engavumelekile. Sicela ukhethe inketho efanele yokufakwa kwepompi (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_ndebele(location, "Ukufakwa kwepompi", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_other_services_menu_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send(
            "Ukuhlola uma ibhorehole yakho ingajuliswa:\n"
            "Ingabe ibhorehole yakho yayinamapayipi:\n"
            "1. Kuphela esiqongweni, ngepayipi elingama-180mm noma elikhulu\n"
            "2. Ukusuka esiqongweni kuya ezansi ngepayipi elingama-140mm noma elincane",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_deepening_casing_ndebele', 'user': user.to_dict()})
        return {'step': 'borehole_deepening_casing_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send(
            "Iyiphi inkinga ebhoreholeni yakho?\n"
            "1. Ibhorehole ewohlokile\n"
            "2. Ibhorehole enamanzi angcolile",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_flushing_problem_ndebele', 'user': user.to_dict()})
        return {'step': 'borehole_flushing_problem_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "3":
        send(
            "Sinikela ngokubha amabhorehole ngokulandela amakilasi amapayipi e-PVC:\n"
            "1. Ikilasi 6 – Okujwayelekile\n"
            "2. Ikilasi 9 – Okunamandla\n"
            "3. Ikilasi 10 – Okunamandla kakhulu\n"
            "Ufuna ukuhlola eyiphi?",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'pvc_casing_selection_ndebele', 'user': user.to_dict()})
        return {'step': 'pvc_casing_selection_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "4":
        update_user_state(user_data['sender'], {'step': 'main_menu_ndebele', 'user': user.to_dict()})
        send_main_menu_ndebele(user_data['sender'], phone_id)
        return {'step': 'main_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efanele (1-4).", user_data['sender'], phone_id)
        return {'step': 'other_services_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def send_main_menu_ndebele(phone_number, phone_id):
    menu_text = (
        "Singakusiza njani lamuhla?\n\n"
        "1. Cela isiphakamiso\n"
        "2. Phanda Intengo Ngokusebenzisa Indawo\n"
        "3. Bheka Isimo Sephrojekthi\n"
        "4. Imibuzo Evame Ukubuzwa noma Funda Ngokuqhuba Ibhorehole\n"
        "5. Eminye Imisebenzi\n"
        "6. Khuluma Nomuntu\n\n"
        "Phendula ngenombolo (umzekeliso: 1)"
    )
    send(menu_text, phone_number, phone_id)

def handle_borehole_deepening_casing_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send("Ibhorehole yakho iyafaneleka ukujuliseka.\nSicela ufake indawo yakho (idolobha, i-ward, i-growth point, noma i-GPS pin):",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'deepening_location_ndebele', 'user': user.to_dict()})
        return {'step': 'deepening_location_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send(
            "Ngeshwa, amabhorehole anamapayipi angaphansi kwama-180mm awakwazi ukujuliseka.\n"
            "Izinketho:\n"
            "1. Buyela kwezinye izinsiza\n"
            "2. Khuluma nosizo",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'deepening_no_deepening_options_ndebele', 'user': user.to_dict()})
        return {'step': 'deepening_no_deepening_options_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efanele (1 noma 2).", user_data['sender'], phone_id)
        return {'step': 'borehole_deepening_casing_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_deepening_no_deepening_options_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        return handle_other_services_menu_ndebele("0", user_data, phone_id)

    elif choice == "2":
        send("Sikuxhumanisa nosizo...", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'human_agent_ndebele', 'user': user.to_dict()})
        return {'step': 'human_agent_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efanele (1 noma 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_no_deepening_options_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_booking_confirm_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Sicela unikeze igama lakho eliphelele:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name_ndebele', 'user': user.to_dict()})
        return {'step': 'booking_full_name_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu_ndebele("0", user_data, phone_id)

    else:
        send("Sicela ukhethe inketho efanele (1 noma 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_booking_confirm_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


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
            "4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Chibhorani\n"
            "5. Zvimwe Zvatinoita\n"
            "6. Taura neMunhu\n\n"
            "Pindura nenhamba (semuenzaniso, 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":
        user.language = "Ndebele"
        update_user_state(user_data['sender'], {
            'step': 'main_menu_ndebele',
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
        return {'step': 'main_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        send("Please select a valid language option (1 for English, 2 for Shona, 3 for Ndebele).", user_data['sender'], phone_id)
        return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}




def faq_borehole_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Intengo incike endaweni, ejulini, kanye nezimo zenhlabathi. Sicela usithumelele indawo yakho nemininingwane ukuze sikunikeze isilinganiso.",
        "2": "Ngokuvamile amahora angu-4–6 noma kuze kube izinsuku ezimbalwa, kuncike ezimweni zendawo, uhlobo lwedwala, nokufinyeleleka.",
        "3": "Ubujiya buyahluka ngendawo. Ubujiya obujwayelekile bungamamitha angu-40, kodwa amabhorehole angaba phakathi kwama-40 kuya kuma-150 amamitha kuncike kuthebula lwamanzi angaphansi komhlaba.",
        "4": "Kwezinye izindawo, kungadingeka imvume yamanzi. Singakusiza ngesicelo uma kunesidingo.",
        "5": "Yebo, sinikela kokubili njengephakathi noma ngokwehlukana, kuncike okukhethwa ngumthengi.",
        "6": "Uma umthengi efuna ukubha endaweni yesibili, sinikela ngesaphulelo.\n\nQaphela: Amamishini okuhlola athola ukuqhekeka komhlaba okuphethe amanzi noma izindawo zokuhlangana kwemifudlana yangaphansi komhlaba. Kodwa awalinganisi inani noma ijubane lamanzi. Ngakho-ke, ukubha ibhorehole akunasiqinisekiso esingu-100% sokuthola amanzi, ngoba ukuqhekeka kungase kube komile, kunomswakama, noma kunamanzi.",
        "7": "Sisebenzisa amamishini okubha aqondile nama-percussion drilling rigs, amathuluzi e-GPS, nemishini yokuhlola iminerali.",
        "8": "Buyela kumenyu wemibuzo..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Ungathanda:\n"
            "1. Ukubuza omunye umbuzo mayelana nokubha ibhorehole\n"
            "2. Ukubuyela kumenyu eyinhloko",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_followup_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efanele (1–8).", user_data['sender'], phone_id)
        return {'step': 'faq_borehole_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}




def handle_select_pump_option_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Inketho engavumelekile. Sicela ukhethe inketho efanele yokufaka iphampu (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_ndebele(location, "Ukufaka iphampu", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_other_services_menu_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send(
            "Ukubheka ukuthi ibhorehole yakho ingajuliswa:\n"
            "Ingabe ibhorehole yakho yayinama-pipe:\n"
            "1. Kuphela esiqongweni, nge-pipe enobubanzi obungu-180mm noma obukhulu\n"
            "2. Ukusuka esiqongweni kuya ezansi nge-pipe enobubanzi obungu-140mm noma obuncane",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_deepening_casing_ndebele', 'user': user.to_dict()})
        return {'step': 'borehole_deepening_casing_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send(
            "Iyiphi inkinga ebhoreholeni yakho?\n"
            "1. Ibhorehole elicwile\n"
            "2. Ibhorehole elinamanzi angcolile",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_flushing_problem_ndebele', 'user': user.to_dict()})
        return {'step': 'borehole_flushing_problem_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "3":
        send(
            "Sinikela ngokubha amabhorehole ngokulandela ama-PVC casing pipe classes:\n"
            "1. I-Class 6 – Okujwayelekile\n"
            "2. I-Class 9 – Okunamandla kakhulu\n"
            "3. I-Class 10 – Okunamandla kakhulu kunakho konke\n"
            "Ufuna ukubheka iphi?",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'pvc_casing_selection_ndebele', 'user': user.to_dict()})
        return {'step': 'pvc_casing_selection_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "4":
        update_user_state(user_data['sender'], {'step': 'main_menu_ndebele', 'user': user.to_dict()})
        send_main_menu_ndebele(user_data['sender'], phone_id)
        return {'step': 'main_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efanele (1-4).", user_data['sender'], phone_id)
        return {'step': 'other_services_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def send_main_menu_ndebele(phone_number, phone_id):
    menu_text = (
        "Singakusiza njani lamuhla?\n\n"
        "1. Cela isiphakamiso\n"
        "2. Phanda Intengo Ngokusebenzisa Indawo\n"
        "3. Bheka Isimo Sephrojekthi\n"
        "4. Imibuzo Evame Ukubuzwa noma Funda Ngokuqhuba Ibhorehole\n"
        "5. Eminye Imisebenzi\n"
        "6. Khuluma Nomuntu\n\n"
        "Phendula ngenombolo (umzekeliso: 1)"
    )
    send(menu_text, phone_number, phone_id)


def handle_deepening_no_deepening_options_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        return handle_other_services_menu_ndebele("0", user_data, phone_id)

    elif choice == "2":
        send("Sikuxhumanisa nosizo...", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'human_agent_ndebele', 'user': user.to_dict()})
        return {'step': 'human_agent_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efanele (1 noma 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_no_deepening_options_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_deepening_location_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()

    user.quote_data['location'] = location

    price = get_pricing_for_location_quotes_ndebele(location, "borehole_deepening")

    send(
        f"Intengo yokujulisa ebhoreholeni e-{location} iqala kusuka ku-USD {price} ngemitha.\n"
        "Ungathanda:\n"
        "1. Ukuqinisekisa & Ukubhukisha Umsebenzi\n"
        "2. Emuva kwezinye izinsiza",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'deepening_booking_confirm_ndebele', 'user': user.to_dict()})
    return {'step': 'deepening_booking_confirm_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


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
            "4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Chibhorani\n"
            "5. Zvimwe Zvatinoita\n"
            "6. Taura neMunhu\n\n"
            "Pindura nenhamba (semuenzaniso, 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":
        user.language = "Ndebele"
        update_user_state(user_data['sender'], {
            'step': 'main_menu_ndebele',
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
        return {'step': 'main_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        send("Please select a valid language option (1 for English, 2 for Shona, 3 for Ndebele).", user_data['sender'], phone_id)
        return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}





def handle_select_pump_option_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Inketho engavumelekile. Sicela ukhethe inketho evumelekile yokufaka ipompi (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_ndebele(location, "Ukufaka ipompi", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }



def handle_pump_status_info_request_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Sicela unikeze okungenani igama lakho eliphelele kanye nenombolo yesiphakamiso noma inombolo yocingo, ngomugqa omusha ngamunye.\n\n"
            "Isibonelo:\n"
            "Jane Doe\nREF123456\nOkungakho: Harare",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request_ndebele',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Ayikho"

    user.project_status_request = {
        'type': 'pump',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Ngiyabonga. Sicela ulinde ngenkathi sithola isimo sephrojekthi yakho...", user_data['sender'], phone_id)

    send(
        f"Nansi isimo sephrojekthi yakho yokufaka ipompi:\n\n"
        f"Igama Lephrojekthi: Ipompi - {full_name}\n"
        f"Isigaba Samanje: Ukufaka Kuqediwe\n"
        f"Isinyathelo Esilandelayo: Ukuhlolwa Kokugcina\n"
        f"Usuku Olulindelekile Lokunikezwa: 12/06/2025\n\n"
        "Ungathanda ukuthola izibuyekezo nge-WhatsApp lapho isimo sishintsha?\nIzinketho: Yebo / Cha",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'pump_status_updates_opt_in_ndebele',
        'user': user.to_dict()
    })

    return {
        'step': 'pump_status_updates_opt_in_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_pump_status_updates_opt_in_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yes', 'y', 'yebo']:
        send(
            "Kuhle! Manje uzothola izibuyekezo nge-WhatsApp noma nini lapho isimo sokufaka ipompi sakho sishintsha.\n\n"
            "Siyabonga ngokusebenzisa inkonzo yethu.",
            user_data['sender'], phone_id
        )
    elif response in ['no', 'n', 'cha']:
        send(
            "Akunankinga. Ungakwazi ukubheka isimo futhi kamuva uma kudingeka.\n\n"
            "Siyabonga ngokusebenzisa inkonzo yethu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ngiyaxolisa, angikwazanga ukukuqonda. Sicela uphendule ngo-Yebo noma Cha.", user_data['sender'], phone_id)
        return {'step': 'pump_status_updates_opt_in_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_faq_menu_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user']) 

    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole_ndebele',
            'user': user.to_dict()
        })
        send(
            "Nawa imibuzo evame ukubuzwa mayelana nokuqhakha ibhorehole:\n\n"
            "1. Ibiza malini ukuqhakha ibhorehole?\n"
            "2. Kuthatha isikhathi esingakanani ukuqhakha ibhorehole?\n"
            "3. Ijulile kangakanani ibhorehole yami?\n"
            "4. Ngidinga imvume yokuqhakha ibhorehole?\n"
            "5. Ngabe niyahlola amanzi bese niqhakha ibhorehole ngasikhathi sinye?\n"
            "6. Kuthiwani uma nihlola amanzi bese ningatholi?\n"
            "7. Yiziphi izinto zokusebenza enizisebenzisayo?\n"
            "8. Emuva Kumenyu Wemibuzo",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Pump Installation FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_pump_ndebele',
            'user': user.to_dict()
        })
        send(
            "Nawa imibuzo evame ukubuzwa mayelana nokufaka ipompi:\n\n"
            "1. Umehluko uphi phakathi kwepompi yelanga neyagesi?\n"
            "2. Ngabe ningayifaka uma senginazo zonke izinto ezidingekayo?\n"
            "3. Kuthatha isikhathi esingakanani ukufaka ipompi?\n"
            "4. Ngidinga usayizi bani wepompi?\n"
            "5. Ngabe niletha amathangi nezindlu zamathangi?\n"
            "6. Emuva Kumenyu Wemibuzo",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Ask a different question
        update_user_state(user_data['sender'], {
            'step': 'custom_question_ndebele',
            'user': user.to_dict()
        })
        send(
            "Sicela uthayiphe umbuzo wakho ngezansi, futhi sizozama ukukusiza.\n",
            user_data['sender'], phone_id
        )
        return {'step': 'custom_question_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent_ndebele',
            'user': user.to_dict(),
            'sender': user_data['sender']
        })
        send("Sicela ulinde ngenkathi sikuxhumanisa nomuntu...", user_data['sender'], phone_id)
        return {'step': 'human_agent_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Back to Main Menu
        return handle_select_language("3", user_data, phone_id)

    else:
        send("Sicela ukhethe inketho evumelekile (1–5).", user_data['sender'], phone_id)
        return {'step': 'faq_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}




def custom_question_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if not prompt.strip():
        send("Sicela uthayiphe umbuzo wakho.", user_data['sender'], phone_id)
        return {'step': 'custom_question_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Gemini prompt template
    system_prompt = (
        "Uyisisekelesi esilusizo se-SpeedGo, inkampani yokubha amabhorehole nokufaka amapompi eZimbabwe. "
        "Uzophendula kuphela imibuzo ephathelene nesevisi ye-SpeedGo, intengo, izinqubo, noma ukusekelwa kwabathengi. "
        "Uma umbuzo womthengi ungaluhlobene ne-SpeedGo, mazise ngobumnene ukuthi ungakwazi ukusiza ngezinto eziphathelene ne-SpeedGo kuphela."
    )

    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content([system_prompt, prompt])

        answer = response.text.strip() if hasattr(response, "text") else "Ngiyaxolisa, angikwazanga ukukuphendula okwamanje."

    except Exception as e:
        answer = "Uxolo, kube nenkinga ngesikhathi sikuphendula. Sicela uzame futhi emuva kwesikhathi."
        print(f"[Gemini error] {e}")

    send(answer, user_data['sender'], phone_id)

    send(
        "Ungathanda:\n"
        "1. Buza omunye umbuzo\n"
        "2. Buyela kumenyu eyinhloko",
        user_data['sender'], phone_id
    )

    return {'step': 'custom_question_followup_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def custom_question_followup_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send("Sicela uthayiphe umbuzo wakho olandelayo.", user_data['sender'], phone_id)
        return {'step': 'custom_question_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("3", user_data, phone_id)

    else:
        send("Sicela uphendule ngo-1 ukuze ubuze omunye umbuzo noma u-2 ukuze ubuyele kumenyu eyinhloko.", user_data['sender'], phone_id)
        return {'step': 'custom_question_followup_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_select_pump_option_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Inketho engavumelekile. Sicela ukhethe inketho efanele yokufakwa kwepompi (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_ndebele(location, "Ukufakwa kwepompi", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }




def handle_pump_status_info_request_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Sicela unikeze okungenani igama lakho eligcwele kanye nenombolo yereferensi noma inombolo yocingo, ngomugqa omusha.\n\n"
            "Isibonelo:\n"
            "Jane Doe\nREF123456\nOkungahleliwe: Harare",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request_ndebele',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Ayikho"

    user.project_status_request = {
        'type': 'pump',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Ngiyabonga. Sicela ulinde njengoba sithola isimo sakho...", user_data['sender'], phone_id)

    send(
        f"Nansi isimo sakho somsebenzi wokufaka ipompi:\n\n"
        f"Igama lomsebenzi: Ipompi - {full_name}\n"
        f"Isigaba samanje: Kuqediwe ukufakwa\n"
        f"Isinyathelo esilandelayo: Ukuhlolwa kokugcina\n"
        f"Usuku olulindeleke ukunikezwa: 12/06/2025\n\n"
        "Ungathanda ukuthola izibuyekezo nge-WhatsApp uma isimo sishintsha?\nIzinketho: Yebo / Cha",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'pump_status_updates_opt_in_ndebele',
        'user': user.to_dict()
    })

    return {
        'step': 'pump_status_updates_opt_in_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_pump_status_updates_opt_in_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yebo', 'y']:
        send(
            "Kuhle! Uzothola izibuyekezo nge-WhatsApp noma nini lapho isimo sesikhundla sakho sesikhundla sishintsha.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    elif response in ['cha', 'c']:
        send(
            "Akunankinga. Ungahlola isimo futhi kamuva uma udinga.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ngiyaxolisa, angikwazanga ukuqonda lokho. Sicela uphendule ngo-Yebo noma Cha.", user_data['sender'], phone_id)
        return {'step': 'pump_status_updates_opt_in_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_select_pump_option_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Inketho engalungile. Sicela ukhethe inketho efanele yokufaka ipompi (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_ndebele(location, "Ukufaka ipompi", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_other_services_menu_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send(
            "Ukubheka ukuthi ibhorehole lakho lingajuliswa:\n"
            "Ibhorehole lakho lalifakwe i-casing:\n"
            "1. Kuphela esiqongweni, ngepayipi elingama-180mm noma elikhulu\n"
            "2. Kusukela esiqongweni kuya phansi ngepayipi elingama-140mm noma elincane",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_deepening_casing_ndebele', 'user': user.to_dict()})
        return {'step': 'borehole_deepening_casing_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send(
            "Iyiphi inkinga ebhoreholeni lakho?\n"
            "1. Ibhorehole elicwile\n"
            "2. Ibhorehole elinamanzi angcolile",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_flushing_problem_ndebele', 'user': user.to_dict()})
        return {'step': 'borehole_flushing_problem_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "3":
        send(
            "Sinikezela ngokubha amabhorehole alandela amakilasi e-PVC casing pipe:\n"
            "1. Ikilasi 6 – Okujwayelekile\n"
            "2. Ikilasi 9 – Okunamandla\n"
            "3. Ikilasi 10 – Okunamandla kakhulu\n"
            "Ufuna ukubheka iphi?",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'pvc_casing_selection_ndebele', 'user': user.to_dict()})
        return {'step': 'pvc_casing_selection_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "4":
        update_user_state(user_data['sender'], {'step': 'main_menu_ndebele', 'user': user.to_dict()})
        send_main_menu_ndebele(user_data['sender'], phone_id)
        return {'step': 'main_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efanele (1-4).", user_data['sender'], phone_id)
        return {'step': 'other_services_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def send_main_menu_ndebele(phone_number, phone_id):
    menu_text = (
        "Singakusiza njani namuhla?\n\n"
        "1. Cela isiphakamiso\n"
        "2. Phanda Intengo Ngokusebenzisa Indawo\n"
        "3. Bheka Isimo Sephrojekthi\n"
        "4. Imibuzo Evame Ukubuzwa noma Funda Ngokuqhuba Ibhorehole\n"
        "5. Eminye Imisebenzi\n"
        "6. Khuluma Nomuntu\n\n"
        "Sicela uphendule ngenombolo (isib. 1)"
    )
    send(menu_text, phone_number, phone_id)



def send_main_menu_ndebele(phone_number, phone_id):
    menu_text = (
        "Singakusiza njani lamuhla?\n\n"
        "1. Cela isiphakamiso\n"
        "2. Phanda Intengo Ngokusebenzisa Indawo\n"
        "3. Bheka Isimo Sephrojekthi\n"
        "4. Imibuzo Evame Ukubuzwa noma Funda Ngokuqhuba Ibhorehole\n"
        "5. Eminye Imisebenzi\n"
        "6. Khuluma Nomuntu\n\n"
        "Phendula ngenombolo (umzekeliso: 1)"
    )
    send(menu_text, phone_number, phone_id)





def handle_select_pump_option_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Inketho engavumelekile. Sicela ukhethe inketho evumelekile yokufakwa kwepompi (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_ndebele(location, "Ukufakwa kwepompi", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_select_pump_option_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Inketho engalungile. Khetha inketho efanele yokufaka iphampu (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_ndebele(location, "Ukufaka iphampu", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_collect_offer_details_ndebele(prompt, user_data, phone_id):
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
        'step': 'offer_response_ndebele',
        'user': user.to_dict()
    })
    send(
        "Isicelo sakho sithunyelwe kumphathi wethu wezintengiso. Sizophendula phakathi nehora.\n\n"
        "Siyabonga ngesiphakamiso sakho!\n\n"
        "Ithimba lethu lizosibuyekeza futhi liphendule maduzane.\n\n"
        "Nakuba sizama ukuba ngentengo ephansi, amanani ethu abonisa izinga, ukuphepha nokuthembeka.\n\n"
        "Ungathanda:\n"
        "1. Ukuqhubeka uma isiphakamiso samukelwe\n"
        "2. Ukhulume nomuntu\n"
        "3. Hlela isiphakamiso sakho",
        user_data['sender'], phone_id
    )
    return {'step': 'offer_response_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_offer_response_ndebele(prompt, user_data, phone_id):
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
            'step': 'booking_details_ndebele',
            'user': user.to_dict()
        })
        send(
            "Izindaba ezinhle! Isiphakamiso sakho samukelwe.\n\n"
            "Masigqinise isinyathelo sakho esilandelayo.\n\n"
            "Ungathanda:\n"
            "1. Bhalisa Ukuhlolwa Kwendawo\n"
            "2. Khokha Idiphozithi\n"
            "3. Qinisekisa Usuku Lokubha",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_details_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Ukuxhunywa nomuntu siqu...", user_data['sender'], phone_id)
        return {'step': 'human_agent_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details_ndebele',
            'user': user.to_dict()
        })
        send(
            "Phendula ngesiphakamiso sakho esibuyekeziwe ngefomethi:\n\n"
            "- Ukuhlola Amanzi: $_\n"
            "- Ukubha Ibhorehole: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Khetha inketho efanele (1-3).", user_data['sender'], phone_id)
        return {'step': 'offer_response_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_details_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info_ndebele',
            'user': user.to_dict()
        })
        send(
            "Kuhle! Sicela unikeze ulwazi olulandelayo ukuze uqedele ukubhuka kwakho:\n\n"
            "- Igama eliphelele:\n"
            "- Usuku Oluthandekayo (dd/mm/yyyy):\n"
            "- Ikheli Lendawo: GPS noma ikheli\n"
            "- Inombolo Yocingo:\n"
            "- Indlela Yokukhokha (Ukukhokha kuqala / Imali endaweni):\n\n"
            "Thayipha: Thumela",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Sicela uxhumane nehhovisi lethu ngo-077xxxxxxx ukuhlela inkokhelo yediphozithi.", user_data['sender'], phone_id)
        return {'step': 'main_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("Umphathi wethu uzokuxhumana nawe ukuze aqinisekise usuku lokubha.", user_data['sender'], phone_id)
        return {'step': 'main_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Khetha inketho efanele (1-3).", user_data['sender'], phone_id)
        return {'step': 'booking_details_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_pvc_casing_selection_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    casing_options = {
        "1": "Class 6",
        "2": "Class 9",
        "3": "Class 10",
        "4": "Double Casing"
    }

    selected_casing = casing_options.get(prompt)
    if selected_casing:
        user.quote_data['casing_type'] = selected_casing
        update_user_state(user_data['sender'], {
            'step': 'quote_summary_ndebele',
            'user': user.to_dict()
        })
        send(
            f"Ukwakha kwePVC okukhethiwe: {selected_casing}.\n\n"
            f"Ngiyabonga! Sizokunikeza isilinganiso ngokuya ngemininingwane oyinikezileyo.\n\n"
            f"1. Nikeza inani lakho?\n"
            f"2. Bhukha i-Site Survey\n"
            f"3. Bhukha i-Drilling\n"
            f"4. Khuluma nommeli womuntu",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_summary_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(
            "Sicela ukhethe inketho evumelekileyo yePVC casing:\n"
            "1. Class 6\n"
            "2. Class 9\n"
            "3. Class 10\n"
            "4. Double Casing",
            user_data['sender'], phone_id
        )
        return {'step': 'pvc_casing_selection_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_collect_booking_info_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt.lower().strip() == "thumela":
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
            'step': 'booking_confirmation_ndebele',
            'user': user.to_dict()
        })
        booking_date = "25/05/2025"
        booking_time = "10:00 AM"
        send(
            "Siyabonga. Ukubhuka kwakho kokuhlola kwendawo kuvunyiwe, futhi uchwepheshe uzokuxhumana nawe maduzane.\n\n"
            f"Isikhumbuzo: Ukuhlola kwakho kwendawo kuhlelwe kusasa.\n\n"
            f"Usuku: {booking_date}\n"
            f"Isikhathi: {booking_time}\n\n"
            "Sijabulile ukusebenza nawe!\n"
            "Udinga ukuhlela kabusha? Phendula\n\n"
            "1. Yebo\n"
            "2. Cha",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_confirmation_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela uthayiphe 'Thumela' ukuze uqinisekise ukubhuka kwakho.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_confirmation_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "2":
        send(
            "Kuhle! Isikhathi sakho sokubha ibhorehole manje sibhukiwe.\n\n"
            "Usuku: Thursday, 23 May 2025\n"
            "Isikhathi Sokuqala: 8:00 AM\n"
            "Isikhathi Esilindelekile: 5 hrs\n"
            "Ithimba: Ochwepheshe abangu-4-5\n\n"
            "Qiniseka ukuthi kukhona indlela yokufinyelela endaweni",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela uxhumane nethimba lethu lokusekela ukuze uhlele kabusha.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}





def handle_select_pump_option_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Inketho engavumelekile. Sicela ukhethe inketho efanele yokufaka ipompi (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes_ndebele(location, "Ukufaka ipompi", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }



def handle_pump_status_info_request_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Sicela unikeze okungenani igama lakho eliphelele kanye nenombolo yereferensi noma inombolo yocingo, ngomugqa omusha ngamunye.\n\n"
            "Isibonelo:\n"
            "Jane Doe\nREF123456\nOkungakho: Harare",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request_ndebele',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Akunikezwe"

    user.project_status_request = {
        'type': 'pump',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Ngiyabonga. Sicela ulinde ngenkathi sithola isimo sephrojekthi yakho...", user_data['sender'], phone_id)

    send(
        f"Nansi isimo sephrojekthi yakho yokufaka ipompi:\n\n"
        f"Igama lephrojekthi: Ipompi - {full_name}\n"
        f"Isigaba samanje: Ukufaka kuqediwe\n"
        f"Isinyathelo esilandelayo: Ukuhlola kokugcina\n"
        f"Usuku olulindeleke ukunikezwa: 12/06/2025\n\n"
        "Ungathatha ukuthola izibuyekezo ze-WhatsApp lapho isimo sishintsha?\nIzinketho: Yebo / Cha",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'pump_status_updates_opt_in_ndebele',
        'user': user.to_dict()
    })

    return {
        'step': 'pump_status_updates_opt_in_ndebele',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_pump_status_updates_opt_in_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yebo', 'ye', 'y']:
        send(
            "Kuhle! Uzothola izibuyekezo ze-WhatsApp njalo lapho isimo sokufaka ipompi lakho sishintsha.\n\n"
            "Siyabonga ngokusebenzisa inkonzo yethu.",
            user_data['sender'], phone_id
        )
    elif response in ['cha', 'ch', 'n']:
        send(
            "Akunankinga. Ungakubheka isimo futhi kamuva uma kudingeka.\n\n"
            "Siyabonga ngokusebenzisa inkonzo yethu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ngiyaxolisa, angikwazanga ukuqonda lokho. Sicela uphendule nge-Yebo noma Cha.", user_data['sender'], phone_id)
        return {'step': 'pump_status_updates_opt_in_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_other_services_menu_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send(
            "Ukubheka ukuthi ibhorehole lakho lingajulwa yini:\n"
            "Ibhehole lakho lalifakwe i-casing:\n"
            "1. Kuphela esiqongweni, ngepayipi elingama-180mm noma likhulu\n"
            "2. Kusukela esiqongweni kuya ezansi ngepayipi elingama-140mm noma elincane",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_deepening_casing_ndebele', 'user': user.to_dict()})
        return {'step': 'borehole_deepening_casing_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send(
            "Iyiphi inkinga ebhoreholeni lakho?\n"
            "1. Ibhorehole elicwile\n"
            "2. Ibhorehole elinamanzi angcolile",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_flushing_problem_ndebele', 'user': user.to_dict()})
        return {'step': 'borehole_flushing_problem_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "3":
        send(
            "Sinikezela ngokubha amabhorehole ngokulandela amakilasi amapayipi e-PVC casing:\n"
            "1. Ikilasi 6 - Okujwayelekile\n"
            "2. Ikilasi 9 - Okunamandla kakhulu\n"
            "3. Ikilasi 10 - Okunamandla kakhulu\n"
            "Ungathanda ukubheka eliphi?",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'pvc_casing_selection_ndebele', 'user': user.to_dict()})
        return {'step': 'pvc_casing_selection_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "4":
        update_user_state(user_data['sender'], {'step': 'main_menu_ndebele', 'user': user.to_dict()})
        send_main_menu_ndebele(user_data['sender'], phone_id)
        return {'step': 'main_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efanele (1-4).", user_data['sender'], phone_id)
        return {'step': 'other_services_menu_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

def send_main_menu_ndebele(phone_number, phone_id):
    menu_text = (
        "Singakusiza njani namuhla?\n\n"
        "1. Cela isiphakamiso\n"
        "2. Phanda Intengo Ngokusebenzisa Indawo\n"
        "3. Bheka Isimo Sephrojekthi\n"
        "4. Imibuzo Evame Ukubuzwa noma Funda Ngokuqhuba Ibhorehole\n"
        "5. Eminye Imisebenzi\n"
        "6. Khuluma Nomuntu\n\n"
        "Phendula ngenombolo (umzekeliso: 1)"
    )
    send(menu_text, phone_number, phone_id)


def handle_deepening_no_deepening_options_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        return handle_other_services_menu_ndebele("0", user_data, phone_id)

    elif choice == "2":
        send("Sikuxhumanisa nabasekeli...", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'human_agent_ndebele', 'user': user.to_dict()})
        return {'step': 'human_agent_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efanele (1 noma 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_no_deepening_options_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_borehole_flushing_problem_ndebele(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send(
            "Uyayazi ububanzi bebhorehole?\n"
            "1. Ama-180mm noma amakhulu\n"
            "2. Phakathi kwama-140mm nama-180mm\n"
            "3. Ama-140mm noma amancane",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'flushing_collapsed_diameter_ndebele', 'user': user.to_dict()})
        return {'step': 'flushing_collapsed_diameter_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send("Sicela ufake indawo yakho ukubheka intengo:", user_data['sender'], phone_id)
        user.quote_data['flushing_type'] = 'dirty_water'
        update_user_state(user_data['sender'], {'step': 'flushing_location_ndebele', 'user': user.to_dict()})
        return {'step': 'flushing_location_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efanele (1 noma 2).", user_data['sender'], phone_id)
        return {'step': 'borehole_flushing_problem_ndebele', 'user': user.to_dict(), 'sender': user_data['sender']}


# Action mapping
action_mapping = {
    "welcome": handle_welcome,
    "select_language": handle_select_language,
    "main_menu": handle_main_menu,
    "enter_location_for_quote": handle_enter_location_for_quote,
    "select_service_quote": handle_select_service_quote,
    "select_service": handle_select_service,
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
    
    "main_menu_shona": handle_main_menu_shona,
    "enter_location_for_quote_shona": handle_enter_location_for_quote_shona,
    "select_service_quote_shona": handle_select_service_quote_shona,
    "select_service_shona": handle_select_service_shona,
    "select_pump_option_shona": handle_select_pump_option_shona,
    "quote_followup_shona": handle_quote_followup_shona,
    "collect_quote_details_shona": handle_collect_quote_details_shona,
    "quote_response_shona": handle_quote_response_shona,
    "collect_offer_details_shona": handle_collect_offer_details_shona,
    "offer_response_shona": handle_offer_response_shona,
    "booking_details_shona": handle_booking_details_shona,
    "collect_booking_info_shona": handle_collect_booking_info_shona,
    "booking_confirmation_shona": handle_booking_confirmation_shona,
    "faq_menu_shona": faq_menu_shona,
    "faq_borehole_shona": faq_borehole_shona,
    "faq_pump_shona": faq_pump_shona,
    "faq_borehole_followup_shona": faq_borehole_followup_shona,
    "faq_pump_followup_shona": faq_pump_followup_shona,
    "check_project_status_menu_shona": handle_check_project_status_menu_shona,
    "drilling_status_info_request_shona": handle_drilling_status_info_request_shona,
    "pump_status_info_request_shona": handle_pump_status_info_request_shona,
    "pump_status_updates_opt_in_shona": handle_pump_status_updates_opt_in_shona,
    "drilling_status_updates_opt_in_shona": handle_drilling_status_updates_opt_in_shona,
    "custom_question_shona": custom_question_shona,
    "custom_question_followup_shona": custom_question_followup_shona,
    "human_agent_shona": human_agent_shona,
    "waiting_for_human_agent_response_shona": handle_user_message_shona,
    "human_agent_followup_shona": handle_user_message_shona,
    "other_services_menu_shona": handle_other_services_menu_shona,
    "borehole_deepening_casing_shona": handle_borehole_deepening_casing_shona,
    "borehole_flushing_problem_shona": handle_borehole_flushing_problem_shona,
    "pvc_casing_selection_shona": handle_pvc_casing_selection_shona,
    "deepening_location_shona": handle_deepening_location_shona,

    "main_menu_ndebele": handle_main_menu_ndebele,
    "enter_location_for_quote_ndebele": handle_enter_location_for_quote_ndebele,
    "select_service_quote_ndebele": handle_select_service_quote_ndebele,
    "select_service_ndebele": handle_select_service_ndebele,
    "select_pump_option_ndebele": handle_select_pump_option_ndebele,
    "quote_followup_ndebele": handle_quote_followup_ndebele,
    "collect_quote_details_ndebele": handle_collect_quote_details_ndebele,
    "quote_response_ndebele": handle_quote_response_ndebele,
    "collect_offer_details_ndebele": handle_collect_offer_details_ndebele,
    "offer_response_ndebele": handle_offer_response_ndebele,
    "booking_details_ndebele": handle_booking_details_ndebele,
    "collect_booking_info_ndebele": handle_collect_booking_info_ndebele,
    "booking_confirmation_ndebele": handle_booking_confirmation_ndebele,
    "faq_menu_ndebele": faq_menu_ndebele,
    "faq_borehole_ndebele": faq_borehole_ndebele,
    "faq_pump_ndebele": faq_pump_ndebele,
    "faq_borehole_followup_ndebele": faq_borehole_followup_ndebele,
    "faq_pump_followup_ndebele": faq_pump_followup_ndebele,
    "check_project_status_menu_ndebele": handle_check_project_status_menu_ndebele,
    "drilling_status_info_request_ndebele": handle_drilling_status_info_request_ndebele,
    "pump_status_info_request_ndebele": handle_pump_status_info_request_ndebele,
    "pump_status_updates_opt_in_ndebele": handle_pump_status_updates_opt_in_ndebele,
    "drilling_status_updates_opt_in_ndebele": handle_drilling_status_updates_opt_in_ndebele,
    "custom_question_ndebele": custom_question_ndebele,
    "custom_question_followup_ndebele": custom_question_followup_ndebele,
    "human_agent_ndebele": human_agent_ndebele,
    "waiting_for_human_agent_response_ndebele": handle_user_message_ndebele,
    "human_agent_followup_ndebele": handle_user_message_ndebele,
    "other_services_menu_ndebele": handle_other_services_menu_ndebele,
    "borehole_deepening_casing_ndebele": handle_borehole_deepening_casing_ndebele,
    "borehole_flushing_problem_ndebele": handle_borehole_flushing_problem_ndebele,
    "pvc_casing_selection_ndebele": handle_pvc_casing_selection_ndebele,
    "deepening_location_ndebele": handle_deepening_location_ndebele

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

                else:
                    # Unsupported message type
                    logging.warning(f"Unsupported message type: {msg_type}")
                    send("Please send a text message or share your location using the 📍 button.", sender, phone_id)

        except Exception as e:
            logging.error(f"Error processing webhook: {e}", exc_info=True)

        return jsonify({"status": "ok"}), 200

def message_handler(prompt, sender, phone_id, message):
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

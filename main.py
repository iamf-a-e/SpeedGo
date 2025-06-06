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
        send("Please enter your location (City/Town or GPS coordinates) to get started.", user_data['sender'], phone_id)
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
            'user': user.to_dict()
        })
        send("Connecting you to a human agent...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        send("Please select a valid option (1-6).", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}


def human_agent(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    customer_number = user_data['sender']
    customer_name = user.name if hasattr(user, "name") and user.name else "Unknown"
    agent_number = "+263719835124"

    # Notify the customer immediately
    send(
        "Thank you. Please hold while I connect you to a SpeedGo representative...",
        customer_number, phone_id
    )

    # Notify the agent immediately
    agent_message = (
        f"👋 A customer would like to talk to you on WhatsApp.\n\n"
        f"📱 Customer Number: {customer_number}\n"
        f"🙋 Name: {customer_name}\n"
        f"📩 Last Message: \"{prompt}\""
    )
    send(agent_message, agent_number, phone_id)

    # Store state with timestamp to track elapsed time
    update_user_state(customer_number, {
        'step': 'waiting_for_human_agent_response',
        'user': user.to_dict(),
        'sender': customer_number,
        'agent_prompt_time': time.time()
    })

    return {'step': 'handle_user_message', 'user': user.to_dict(), 'sender': customer_number}


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
        

def handle_user_message(message, user_data, phone_id):
    state = user_data.get('step')
    customer_number = user_data['sender']

    if state == 'waiting_for_human_agent_response':
        prompt_time = user_data.get('agent_prompt_time', 0)
        elapsed = time.time() - prompt_time

        if elapsed >= 10:
            # Send fallback prompt
            send(
                "Alternatively, you can message or call us directly at {agent_number}}.",
                customer_number, phone_id
            )
            send(
                "Would you like to return to the main menu?\n1. Yes\n2. No",
                customer_number, phone_id
            )

            # Update state to wait for user's Yes/No reply
            update_user_state(customer_number, {
                'step': 'human_agent_followup',
                'user': user_data['user'],
                'sender': customer_number
            })

            return {'step': 'human_agent_followup', 'user': user_data['user'], 'sender': customer_number}
        else:
            # Still waiting, do not send fallback yet
            # Optionally, you can just wait or remind user to hold on
            return user_data  # or send "Please hold..." message

    elif state == 'human_agent_followup':
        # Handle user's Yes/No answer here
        if message.strip() == '1':  # User wants main menu
            send("Returning you to the main menu...", customer_number, phone_id)
            # Reset state to main menu step (example)
            update_user_state(customer_number, {
                'step': 'main_menu',
                'user': user_data['user'],
                'sender': customer_number
            })
            # Show main menu
            send_main_menu(customer_number, phone_id)
            return {'step': 'main_menu', 'user': user_data['user'], 'sender': customer_number}

        elif message.strip() == '2':  # User says No
            send("Thank you! Have a good day.", customer_number, phone_id)
            # Optionally clear or end session
            update_user_state(customer_number, {
                'step': 'end',
                'user': user_data['user'],
                'sender': customer_number
            })
            return {'step': 'end', 'user': user_data['user'], 'sender': customer_number}
        else:
            send("Please reply with 1 for Yes or 2 for No.", customer_number, phone_id)
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

#--------------------------------------------------------SHONA-------------------------------------------------------------------------

def handle_main_menu2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":  # Kukumbira quotation
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote2',
            'user': user.to_dict()
        })
        send("Ndapota nyora nzvimbo yako (Guta/Kanzuru kana GPS coordinates) kuti titange.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Tsvaga Mutengo Uchishandisa Nzvimbo
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote2',
            'user': user.to_dict()
        })
        send(
            "Kuti tikuratidze mutengo, ndapota nyora nzvimbo yako (Guta/Kanzuru kana GPS coordinates):",
            user_data['sender'], phone_id
        )
        return {'step': 'enter_location_for_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Tarisa Mamiriro ePurojekiti
        update_user_state(user_data['sender'], {
            'step': 'check_project_status_menu2',
            'user': user.to_dict()
        })
        send(
            "Ndapota sarudza zvaunoda kuita:\n"
            "1. Tarisa mamiriro ekuchera chibhorani\n"
            "2. Tarisa mamiriro ekuiswa kwepombi\n"
            "3. Taura nemumiriri\n"
            "4. Dzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'check_project_status_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # FAQs kana kudzidza nezve kuborehole
        update_user_state(user_data['sender'], {
            'step': 'faq_menu2',
            'user': user.to_dict()
        })
        send(
            "Ndapota sarudza chikamu cheMibvunzo:\n\n"
            "1. Mibvunzo nezve Kuchera Chibhorani\n"
            "2. Mibvunzo nezve Kuisa Pombi\n"
            "3. Bvunza imwe mibvunzo\n"
            "4. Taura nemumiriri\n"
            "5. Dzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Zvimwe Zvatinoita
        update_user_state(user_data['sender'], {
            'step': 'other_services_menu2',
            'user': user.to_dict()
        })
        send(
            "Mauya kuZvimwe Zvatinoita zveChibhorani. Ndeipi sevhisi yaunoda?\n"
            "1. Kuchera zvakadzika chibhorani chako\n"
            "2. Kubvisa tsvina muChibhorani (Flushing)\n"
            "3. Kusarudza PVC Casing Pipe\n"
            "4. Dzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'other_services_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "6":  # Taura nemunhu
        update_user_state(user_data['sender'], {
            'step': 'human_agent2',
            'user': user.to_dict()
        })
        send("Tiri kukubatanidza nemumiriri...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza sarudzo iripo (1 kusvika 6).", user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}


def human_agent2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    customer_number = user_data['sender']
    customer_name = user.name if hasattr(user, "name") and user.name else "Asingazivikanwe"
    agent_number = "+263719835124"

    # Notify the customer immediately
    send(
        "Tatenda. Ndapota mirira ndichikubatanidza nemumiriri weSpeedGo...",
        customer_number, phone_id
    )

    # Notify the agent immediately
    agent_message = (
        f"👋 Mutengi anoda kutaura newe paWhatsApp.\n\n"
        f"📱 Nhamba yemutengi: {customer_number}\n"
        f"🙋 Zita: {customer_name}\n"
        f"📩 Mharidzo Yekupedzisira: \"{prompt}\""
    )
    send(agent_message, agent_number, phone_id)

    # Store state with timestamp to track elapsed time
    update_user_state(customer_number, {
        'step': 'waiting_for_human_agent_response2',
        'user': user.to_dict(),
        'sender': customer_number,
        'agent_prompt_time': time.time()
    })

    return {'step': 'handle_user_message2', 'user': user.to_dict(), 'sender': customer_number}


def notify_agent2(customer_number, prompt, agent_number, phone_id):
    agent_message = (
        f"👋 Kumbiro kutsva kubva kumutengi paWhatsApp\n\n"
        f"📱 Nhamba: {customer_number}\n"
        f"📩 Mharidzo: \"{prompt}\""
    )
    send(agent_message, agent_number, phone_id)


def send_fallback_option2(customer_number, phone_id):
    # Check if still waiting
    user_data = get_user_state(customer_number)
    if user_data and user_data.get('step') == 'waiting_for_human_agent_response2':
        send("Kana zvikatadza kubatana, unogona kutifonera pa +263719835124", customer_number, phone_id)
        send("Ungade kuita sei:\n1. Dzokera ku main menu\n2. Pedzisa hurukuro", customer_number, phone_id)
        update_user_state(customer_number, {
            'step': 'human_agent_followup2',
            'user': user_data.get('user', {}),
            'sender': customer_number
        })


def send_fallback_option2(customer_number, phone_id):
    # Check if user is still waiting
    user_data = get_user_state(customer_number)
    if user_data.get('step') == 'waiting_for_human_agent_response2':
        send(
            "Kana zvikatadza, unogonawo kutitumira meseji kana kutifonera pa +263719835124.",
            customer_number, phone_id
        )
        send(
            "Ungade kudzokera ku menyu huru here?\n1. Ehe\n2. Kwete",
            customer_number, phone_id
        )
        update_user_state(customer_number, {
            'step': 'human_agent_followup2',
            'user': user_data.get('user', {}),
            'sender': customer_number
        })


def handle_user_message2(message, user_data, phone_id):
    state = user_data.get('step')
    customer_number = user_data['sender']

    if state == 'waiting_for_human_agent_response2':
        prompt_time = user_data.get('agent_prompt_time', 0)
        elapsed = time.time() - prompt_time

        if elapsed >= 10:
            # Send fallback prompt
            send(
                "Kana zvikatadza, unogonawo kutitumira meseji kana kutifonera pa +263719835124.",
                customer_number, phone_id
            )
            send(
                "Ungade kudzokera ku menyu huru here?\n1. Ehe\n2. Kwete",
                customer_number, phone_id
            )

            # Update state to wait for user's Yes/No reply
            update_user_state(customer_number, {
                'step': 'human_agent_followup2',
                'user': user_data['user'],
                'sender': customer_number
            })

            return {'step': 'human_agent_followup2', 'user': user_data['user'], 'sender': customer_number}
        else:
            # Still waiting, do not send fallback yet
            return user_data  # optionally notify user to wait

    elif state == 'human_agent_followup2':
        if message.strip() == '1':  # User wants main menu
            send("Kudzosera kumenyu huru...", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'main_menu2',
                'user': user_data['user'],
                'sender': customer_number
            })
            send_main_menu(customer_number, phone_id)
            return {'step': 'main_menu2', 'user': user_data['user'], 'sender': customer_number}

        elif message.strip() == '2':  # User says No
            send("Tatenda! Ivai nezuva rakanaka.", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'end',
                'user': user_data['user'],
                'sender': customer_number
            })
            return {'step': 'end', 'user': user_data['user'], 'sender': customer_number}

        else:
            send("Ndapota pindura ne 1 kuti zvinge zviri 'Ehe' kana 2 kuti zvinge zviri 'Kwete'.", customer_number, phone_id)
            return user_data


def human_agent_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        return handle_select_language("1", user_data, phone_id)

    elif prompt == "2":
        send("Zvakanaka. Inzwa wakasununguka kubvunza kana paine chaunoda rubatsiro nacho.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota pindura ne 1 kuti udzokere ku menyu huru kana 2 kuti urambe uri pano.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_menu2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user']) 

    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole2',
            'user': user.to_dict()
        })
        send(
            "Mibvunzo inowanzo bvunzwa nezve kuchera maburi emvura:\n\n"
            "1. Kuchera buri remvura kunodhura zvakadini?\n"
            "2. Zvinotora nguva yakareba sei kuchera buri?\n"
            "3. Buri rangu richadzika zvakadii?\n"
            "4. Ndinoda here mvumo yekuchera buri?\n"
            "5. Munokwanisa kuita water survey pamwe chete nekuchera?\n"
            "6. Ko kana pakaitwa water survey musingawani mvura?\n"
            "7. Munoshandisa michina ipi pakuchera?\n"
            "8. Dzokera ku FAQ menyu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole2', 'user': user.to_dict(), 'sender': user_data['sender']}


    elif prompt == "2":  # Pump Installation FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_pump2',
            'user': user.to_dict()
        })
        send(
            "Mibvunzo inowanzo bvunzwa nezvekuisa mapombi:\n\n"
            "1. Chii chinosiyanisa mapombi ezuva nemagetsi?\n"
            "2. Munokwanisa kuisa kana ndine zvinhu zvacho kare?\n"
            "3. Zvinotora nguva yakareba sei kuisa pombi?\n"
            "4. Ndinoda pombi yakakura sei?\n"
            "5. Munopa matanki uye zvimire zvematanki here?\n"
            "6. Dzokera ku FAQ menyu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Ask a different question
        update_user_state(user_data['sender'], {
            'step': 'custom_question2',
            'user': user.to_dict()
        })
        send(
            "Ndapota nyora mubvunzo wako pasi, tichaedza napose patinogona kukubatsira.\n",
            user_data['sender'], phone_id
        )
        return {'step': 'custom_question2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent2',
            'user': user.to_dict(),
            'sender': user_data['sender']
        })
        send("Ndapota chimbomira ndichikubatanidza nemumiriri wedu...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Back to Main Menu
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Ndapota sarudza chisarudzo chiri pakati pe 1 kusvika ku 5.", user_data['sender'], phone_id)
        return {'step': 'faq_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}


def custom_question2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if not prompt.strip():
        send("Ndapota nyora mubvunzo wako.", user_data['sender'], phone_id)
        return {'step': 'custom_question2', 'user': user.to_dict(), 'sender': user_data['sender']}

    system_prompt = (
        "You are a helpful assistant for SpeedGo, a borehole drilling and pump installation company in Zimbabwe. "
        "You will only answer questions related to SpeedGo's services, pricing, processes, or customer support. "
        "If the user's question is unrelated to SpeedGo, politely let them know that you can only assist with SpeedGo-related topics."
    )

    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content([system_prompt, prompt])

        answer = response.text.strip() if hasattr(response, "text") else "Ndine urombo, handikwanise kukupindura pari zvino."

    except Exception as e:
        answer = "Ndine urombo, pane chakanganisika pakupindura mubvunzo wako. Ndapota edzazve gare gare."
        print(f"[Gemini error] {e}")

    send(answer, user_data['sender'], phone_id)

    send(
        "Ungade:\n"
        "1. Kubvunza rimwe mubvunzo\n"
        "2. Kudzokera ku Menyu Huru",
        user_data['sender'], phone_id
    )

    return {'step': 'custom_question_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


def custom_question_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send("Ndapota nyora mubvunzo wako unotevera.", user_data['sender'], phone_id)
        return {'step': 'custom_question2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Ndapota pindura ne 1 kuti ubvunze imwe mibvunzo kana 2 kuti udzokere kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'custom_question_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_borehole2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Mutengo unobva panzvimbo yenyu, kudzika kwekutemera, uye ivhu riripo. Ndapota tumirai nzvimbo yenyu uye mashandisirwo emugwagwa kuti tigokupai mutengo wakanyatsokodzera.",
        "2": "Kazhinji zvinotora maawa 4 kusvika ku6 kana mazuva akati kuti, zvichienderana nemamiriro enzvimbo, dombo riripo, uye kuti nzvimbo yacho inosvikika sei.",
        "3": "Kudzika kunosiyana nenzvimbo. Pakati pezinga, tinotema pa40 metres, asi dzimwe borehole dzinogona kusvika ku150 metres zvichienderana nemvura iri pasi pevhu.",
        "4": "Dzimwe nzvimbo dzinoda mvumo yekuchera. Tinogona kukubatsirai kuwana mvumo iyi kana ichidiwa.",
        "5": "Ehe, tinoita survey nemuchera panguva imwe chete kana zvakasiyana, zvinoenderana nezvamunoda.",
        "6": "Kana mutengi achida kuchera pane imwe nzvimbo zvakare, tinopa kuderedzwa kwemutengo.\n\nCherechedzo: Makina eSurvey anotarisa mapatya ane mvura iri pasi pevhu kana kupindirana kwemvura iri pasi pevhu. Asi haana kugona kuyera huwandu hwemvura. Saka kuchera borehole hakune vimbiso ye100% yekuwana mvura, nekuti mapatya aya angava akaoma, ane unyoro kana ane mvura.",
        "7": "Tinoshandisa michina yepamusoro-soro ye rotary ne percussion rigs, GPS tools, uye survey yegeology.",
        "8": "Kudzokera kuFAQ Menu..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Ungada:\n"
            "1. Kubvunza imwe mibvunzo yeBorehole Drilling FAQs\n"
            "2. Kudzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza chisarudzo chiri pakati pe 1 kusvika ku 8.", user_data['sender'], phone_id)
        return {'step': 'faq_borehole2', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_borehole_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send(
            "Ndapota sarudza mubvunzo:\n\n"
            "1. Kuchera borehole kunodhura marii?\n"
            "2. Zvinotora nguva yakareba sei kuchera borehole?\n"
            "3. Borehole yangu ichadzika kusvika papi?\n"
            "4. Ndinoda mvumo here kuti nditsemure borehole?\n"
            "5. Munotanga survey nemuchera panguva imwe chete here?\n"
            "6. Ko kana survey ikaona kusina mvura?\n"
            "7. Munoshandisa michina ipi?\n"
            "8. Dzokera kuFAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Ndapota sarudza 1 kuti ubvunze imwe mibvunzo kana 2 kudzokera kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Mapombi ezuva anoshandisa simba rezuva uye akakodzera nzvimbo dzisina magetsi. Mapombi emagetsi anoshandisa grid yemagetsi, uye anowanzodhura zvishoma pakutanga asi anoda magetsi.",
        "2": "Ehe! Tinopa mapakeji ebasa chete kana mune zvinhu zvamunenge matotenga.",
        "3": "Kuiswa kunowanzotora zuva rimwe chete kana zvinhu zvese zvagadzirira uye nzvimbo ichisvikika.",
        "4": "Saizi yepombi inobva pamaitiro enyu emvura uye kudzika kwe borehole. Tinogona kuuya tichiongorora nzvimbo yenyu kuti tikupei zano rakanakisisa.",
        "5": "Ehe, tinotengesa mapakeji akakwana anosanganisira matangi emvura, ma tank stands uye mapaipi ese anodiwa.",
        "6": "Kudzokera kuFAQ Menu..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)

        if prompt == "6":
            return {'step': 'faq_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Ungada:\n"
            "1. Kubvunza imwe mibvunzo yePump Installation FAQs\n"
            "2. Kudzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza chisarudzo chiri pakati pe 1 kusvika ku 6.", user_data['sender'], phone_id)
        return {'step': 'faq_pump2', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send(
            "Ndapota sarudza mubvunzo:\n\n"
            "1. Ndezvipi zvakasiyana pakati pemapombi ezuva nemagetsi?\n"
            "2. Munogona kuisa kana ndatotenga zvinhu zvacho?\n"
            "3. Kuiswa kwepombi kunotora nguva yakareba sei?\n"
            "4. Ndinoda pombi ine saizi ipi?\n"
            "5. Munotengesawo matangi nematank stands here?\n"
            "6. Dzokera kuFAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Ndapota sarudza 1 kuti ubvunze imwe mibvunzo kana 2 kudzokera kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_enter_location_for_quote2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if 'location' in user_data and 'latitude' in user_data['location'] and 'longitude' in user_data['location']:
        lat = user_data['location']['latitude']
        lng = user_data['location']['longitude']
        gps_coords2 = f"{lat},{lng}"
        location_name2 = reverse_geocode_location2(gps_coords2)

        if location_name2:
            user.quote_data['location'] = location_name2
            user.quote_data['gps_coords'] = gps_coords2
            update_user_state(user_data['sender'], {
                'step': 'select_service_quote2',
                'user': user.to_dict()
            })
            send(
                f"Nzvimbo yawanikwa: {location_name2.title()}\n\n"
                "Zvino sarudza sevhisi yaunoda:\n"
                "1. Water survey\n"
                "2. Kuchera borehole\n"
                "3. Kuiswa kwepombi\n"
                "4. Kuchera bhora rezvekutengeserana\n"
                "5. Kuchinjwa/kudzika zvakare kwe borehole",
                user_data['sender'], phone_id
            )
            return {'step': 'select_service_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}
        else:
            send("Hatina kukwanisa kuona nzvimbo yenyu. Ndapota nyora zita reguta/kanzvimbo nemaoko.", user_data['sender'], phone_id)
            return {'step': 'enter_location_for_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        location_name = prompt.strip()
        user.quote_data['location'] = location_name.lower()
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote2',
            'user': user.to_dict()
        })
        send(
            "Zvino sarudza sevhisi yaunoda:\n"
            "1. Water survey\n"
            "2. Kuchera borehole\n"
            "3. Kuiswa kwepombi\n"
            "4. Kuchera bhora rezvekutengeserana\n"
            "5. Kuchinjwa/kudzika zvakare kwe borehole",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_select_service2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    services = {
        "1": "Water survey",
        "2": "Kuchera borehole",
        "3": "Kuiswa kwepombi",
        "4": "Kuchera bhora rezvekutengeserana",
        "5": "Kudzika zvakare kwe borehole",
    }
    if prompt in services:
        user.quote_data['service'] = services[prompt]
        update_user_state(user_data['sender'], {
            'step': 'collect_quote_details2',
            'user': user.to_dict()
        })
        send(
            "Kuti tikukwanisire mutengo wenguva pfupi, ndapota pindura zvinotevera:\n\n"
            "1. Nzvimbo yenyu (Guta/Kanzvimbo kana GPS):",
            user_data['sender'], phone_id
        )
        return {'step': 'handle_select_service_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sevhisi yakakodzera (1-5).", user_data['sender'], phone_id)
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
            'casing_type': responses[5].strip() if len(responses) > 5 else "Hazvina kutsanangurwa"
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
        estimate = "Class 6: Mutengo Wakafungidzirwa: $2500\nInosanganisira kuchera, PVC casing 140mm"
        send(
            f"Maita basa! Zvichibva pane zvamunotaura:\n\n"
            f"{estimate}\n\n"
            f"Cherekedza: Mari yekuisa kaviri casing inobhadharwa zvakawanda kana zvichidikanwa, uye pachibvumirano chemutengi\n\n"
            f"Ungada here:\n"
            f"1. Kupa mutengo wako?\n"
            f"2. Kuronga kuongorora saiti\n"
            f"3. Kuronga kuchera borehole\n"
            f"4. Kutaura nemumiriri munhu",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_response2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota nyora ruzivo rwese rwakumbirwa (anenge mitsara mina).", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_quote_response2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Offer price
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details2',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Unogona kutumira mitengo yako pazasi.\n\n"
            "Ndapota pindura nemutengo wako uchishandisa fomati:\n\n"
            "- Kuongorora mvura: $_\n"
            "- Kuchera borehole: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":  # Book site survey
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info2',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Ndapota nyora zvinotevera kuti tipedze kurongwa kwako:\n\n"
            "- Zita rizere:\n"
            "- Zuva raunoda (dd/mm/yyyy):\n"
            "- Kero yesaiti: GPS kana kero chaiyo\n"
            "- Nhamba yefoni:\n"
            "- Nzira yekubhadhara (Prepayment / Mari panzvimbo):\n\n"
            "Nyora: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Book for a Drilling
        send("Mumiriri wedu achakubata kuti apedze kurongwa kwekuchera borehole.", user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":  # Human Agent
        send("Tiri kukubatanidza nemumiriri munhu...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sarudzo yakakodzera (1-4).", user_data['sender'], phone_id)
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
        "Chikumbiro chako chatumirwa kumaneja wekutengesa. Tichapindura mukati meawa rimwe.\n\n"
        "Maita basa nekuvimbika kwenyu!\n\n"
        "Chikwata chedu chichachiongorora uye chichapindura munguva pfupi.\n\n"
        "Kunyangwe tichiedza kukupa mutengo wakachipa, mitengo yedu inoenderana nehunhu, kuchengeteka, uye kuvimbika.\n\n"
        "Ungada here:\n"
        "1. Kuenderera kana mutengo wako uchibvumirwa\n"
        "2. Kutaura nemunhu\n"
        "3. Kugadzirisa mutengo wako",
        user_data['sender'], phone_id
    )
    return {'step': 'offer_response2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_offer_response2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    quote_id = user.quote_data.get('quote_id')
    if prompt == "1":  # Kubvuma chipo (simulated)
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
            "Nhau dzakanaka! Chipo chako chagamuchirwa.\n\n"
            "Ngatibvumiraneyi nezvokutevera.\n\n"
            "Ungade kuita:\n"
            "1. Kuronga Kuongorora Nzvimbo\n"
            "2. Kubhadhara Mari Yekuchengetedza\n"
            "3. Kusimbisa Zuva Rekuchera Mvura",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_details2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Tiri kukuendesa kumumiriri wemunhu...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details2',
            'user': user.to_dict()
        })
        send(
            "Ndapota pindura nekunyora chipo chako chachinjwa mukutevedzana kwe:\n\n"
            "- Kuongorora Mvura: $_\n"
            "- Kuchera Mvura: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sarudzo iripo (1-3).", user_data['sender'], phone_id)
        return {'step': 'offer_response2', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_details2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Kuronga Kuongorora Nzvimbo
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info2',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Ndapota ipa ruzivo runotevera kuti tiite hurongwa hwako:\n\n"
            "- Zita Rizere:\n"
            "- Zuva Rawasarudza (dd/mm/yyyy):\n"
            "- Kero yeNzvimbo: GPS kana kero chaiyo\n"
            "- Nhamba dzeRunhare:\n"
            "- Nzira Yekubhadhara (Kubhadhara Pamberi / Mari Panzvimbo):\n\n"
            "Nyora: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":  # Kubhadhara Mari Yekuchengetedza
        send("Ndapota bata hofisi yedu pa0719835124 kuti uronge kubhadhara mari yekuchengetedza.", user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Kusimbisa Zuva Rekuchera Mvura
        send("Mumiriri wedu achakubata kuti asimbise zuva rekuchera mvura.", user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sarudzo iripo (1-3).", user_data['sender'], phone_id)
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
            "Tatenda. Kurongwa kwako kwekuongorora kwasimbiswa, uye tekinoroji achakubata munguva pfupi.\n\n"
            f"Rangarira: Kuongorora kwenzvimbo yako kwakatarwa kusvikira mangwana.\n\n"
            f"Zuva: {booking_date}\n"
            f"Nguva: {booking_time}\n\n"
            "Tinotarisira kushanda newe!\n"
            "Unoda kuchinja zuva here? Nyora\n\n"
            "1. Ehe\n"
            "2. Kwete",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_confirmation2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota nyora 'Submit' kuti usimbise kurongwa kwako.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_confirmation2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "2":  # No reschedule needed
        send(
            "Zvakanaka! Ruzivo rwenyu rwekukorobha borehole rwabhuka.\n\n"
            "Zuva: China, 23 Chivabvu 2025\n"
            "Nguva Yekutanga: 8:00 AM\n"
            "Nguva Inotarisirwa: maawa 5\n"
            "Chikwata: Vashandi 4-5\n\n"
            "Iva nechokwadi chekuti nzvimbo yacho iri nyore kusvika",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndokumbira utaure nevanhu vanobatsira kuti uchinje zuva.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_select_service_quote2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if not location:
        send("Ndokumbira utaure nzvimbo yako kutanga usati wasarudza sevhisi.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}

    service_map = {
        "1": "Kuongorora Mvura",
        "2": "Kukorobha Borehole",
        "3": "Kuisa Pampu",
        "4": "Kukorobha Bhorehole Rekutengeserana",
        "5": "Kudzika Borehole"
    }

    selected_service = service_map.get(prompt.strip())

    if not selected_service:
        send("Sarudzo isiriyo. Ndokumbira upindure ne1, 2, 3, 4 kana 5 kusarudza sevhisi.", user_data['sender'], phone_id)
        return {'step': 'select_service_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Store selected service
    user.quote_data['service'] = selected_service

    # Handle Pump Installation separately as it has options
    if selected_service == "Kuisa Pampu":
        update_user_state(user_data['sender'], {
            'step': 'select_pump_option2',
            'user': user.to_dict()
        })
        message_lines = [f"💧 Sarudzo dzeKuisa Pampu:\n"]
        for key, option in pump_installation_options.items():
            desc = option.get('description', 'Hapana tsananguro')
            message_lines.append(f"{key}. {desc}")
        send("\n".join(message_lines), user_data['sender'], phone_id)
        return {'step': 'select_pump_option2', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Get pricing for other services
    pricing_message = get_pricing_for_location_quotes(location, selected_service)
    
    # Ask if user wants to return to main menu or choose another service
    update_user_state(user_data['sender'], {
        'step': 'quote_followup2',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'quote_followup2',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_other_services_menu2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Borehole Deepening casing question
        send(
            "Kuti tione kana borehole yako inogona kudzika:\n"
            "Borehole yakaiswa casing here:\n"
            "1. Pamusoro chete, ne pombi ine dhayamita 180mm kana kukura\n"
            "2. Kubva pamusoro kusvika pasi nepombi ine dhayamita 140mm kana diki",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_deepening_casing2', 'user': user.to_dict()})
        return {'step': 'borehole_deepening_casing2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        # Borehole Flushing problem type
        send(
            "Chii chiri dambudziko neborehole yako?\n"
            "1. Borehole yakawira pasi\n"
            "2. Mvura yakasviba borehole",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_flushing_problem2', 'user': user.to_dict()})
        return {'step': 'borehole_flushing_problem2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "3":
        # PVC casing class selection
        send(
            "Tinopa maborehole ane PVC casing pipe makirasi:\n"
            "1. Kirasi 6 – Yakajairika\n"
            "2. Kirasi 9 – Yakasimba\n"
            "3. Kirasi 10 – Yakasimba Kwazvo\n"
            "Ndeipi yaungada kuongorora?",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'pvc_casing_selection2', 'user': user.to_dict()})
        return {'step': 'pvc_casing_selection2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "4":
        # Back to main menu
        update_user_state(user_data['sender'], {'step': 'main_menu2', 'user': user.to_dict()})
        send_main_menu2(user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndokumbira usarudze sarudzo yakakodzera (1-4).", user_data['sender'], phone_id)
        return {'step': 'other_services_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}


def send_main_menu2(phone_number, phone_id):
    menu_text = (
        "Tinokubatsirai sei nhasi?\n\n"
        "1. Kumbira mutengo\n"
        "2. Tsvaga Mutengo Uchishandisa Nzvimbo\n"
        "3. Tarisa Mamiriro eProjekiti\n"
        "4. Mibvunzo Inowanzo Bvunzwa kana Dzidza Nezve Kubhuroka Mvura\n"
        "5. Mamwe Mabasa\n"
        "6. Taura neMumiriri Wemunhu\n\n"
        "Ndapota pindura nenhamba (semuenzaniso, 1)"
    )
    send(menu_text, phone_number, phone_id)
    

def handle_borehole_deepening_casing2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Only at top, qualifies for deepening
        send("Bhuroka rako rinokodzera kuwedzerwa kudzika.\nNdapota nyora nzvimbo yako (guta, ward, growth point, kana GPS pin):",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'deepening_location2', 'user': user.to_dict()})
        return {'step': 'deepening_location2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        # Top to bottom with smaller pipe - no deepening
        send(
            "Zvinosuruvarisa, maburoka ane pombi diki kupfuura 180mm kubva kumusoro kusvika pasi haagoni kuwedzerwa kudzika.\n"
            "Sarudzo:\n"
            "1. Dzokera kuMamwe Mabasa\n"
            "2. Taura neRutsigiro",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'deepening_no_deepening_options2', 'user': user.to_dict()})
        return {'step': 'deepening_no_deepening_options2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'borehole_deepening_casing2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_no_deepening_options2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Back to Other Services menu
        return handle_other_services_menu2("0", user_data, phone_id)  # or send menu prompt directly

    elif choice == "2":
        send("Tiri kukubatanidza nerutsigiro...", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'human_agent2', 'user': user.to_dict()})
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_no_deepening_options2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_location2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()

    # Save location for deepening request
    user.quote_data['location'] = location

    # Fetch pricing from backend (you must implement this function)
    price = get_pricing_for_location_quotes(location, "borehole_deepening")

    send(
        f"Mutengo wekuwedzera kudzika mu{location} unotangira paUSD {price} pamita.\n"
        "Ungada here:\n"
        "1. Simbisa & Ronga Basa\n"
        "2. Dzokera kuMamwe Mabasa",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'deepening_booking_confirm2', 'user': user.to_dict()})
    return {'step': 'deepening_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_booking_confirm2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Start booking details collection
        user.booking_data = {}
        send("Ndapota nyora zita rako rizere:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name2', 'user': user.to_dict()})
        return {'step': 'booking_full_name2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        # Back to other services menu
        return other_services_menu2("0", user_data, phone_id)

    else:
        send("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_borehole_flushing_problem2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Collapsed Borehole
        send(
            "Unoziva dhayamita yebhuroka here?\n"
            "1. 180mm kana kupfuura\n"
            "2. Pakati pe140mm ne180mm\n"
            "3. 140mm kana pasi",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'flushing_collapsed_diameter2', 'user': user.to_dict()})
        return {'step': 'flushing_collapsed_diameter2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        # Dirty Water Borehole
        send("Ndapota nyora nzvimbo yako kuti titarise mutengo:", user_data['sender'], phone_id)
        user.quote_data['flushing_type'] = 'dirty_water'
        update_user_state(user_data['sender'], {'step': 'flushing_location2', 'user': user.to_dict()})
        return {'step': 'flushing_location2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'borehole_flushing_problem2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_flushing_collapsed_diameter2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()
    diameter_map = {
        "1": "180mm_or_larger",
        "2": "between_140_and_180mm",
        "3": "140mm_or_smaller"
    }

    diameter = diameter_map.get(choice)
    if not diameter:
        send("Ndapota sarudza sarudzo yakakodzera (1-3).", user_data['sender'], phone_id)
        return {'step': 'flushing_collapsed_diameter2', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['flushing_type'] = 'collapsed'
    user.quote_data['diameter'] = diameter

    if diameter == "180mm_or_larger":
        send("Tinogona kugezesa borehole yako tichishandisa madziro ane drilling bit (zvinobudirira zvikuru).\nNdapota nyora nzvimbo yako kuti tione mutengo:",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'flushing_location2', 'user': user.to_dict()})
        return {'step': 'flushing_location2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif diameter == "between_140_and_180mm":
        send("Tinogona kugezesa borehole tichishandisa madziro, pasina drilling bit.\nNdapota nyora nzvimbo yako kuti tione mutengo:",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'flushing_location2', 'user': user.to_dict()})
        return {'step': 'flushing_location2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif diameter == "140mm_or_smaller":
        send("Tinogona kugezesa borehole tichishandisa madziro chete (pasina drilling bit).\nNdapota nyora nzvimbo yako kuti tione mutengo:",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'flushing_location2', 'user': user.to_dict()})
        return {'step': 'flushing_location2', 'user': user.to_dict(), 'sender': user_data['sender']}


def calculate_borehole_drilling_price2(location, drilling_class, actual_depth_m):
    drilling_info = location_pricing[location]["Borehole Drilling"]
    base_price = drilling_info[drilling_class]
    included_depth = drilling_info["included_depth_m"]
    extra_per_m = drilling_info["extra_per_m"]

    if actual_depth_m <= included_depth:
        return base_price

    extra_depth = actual_depth_m - included_depth
    extra_cost = extra_depth * extra_per_m
    return base_price + extra_cost


def handle_flushing_location2(prompt, user_data, phone_id):
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
        f"Mutengo wekugezesa borehole munzvimbo ye {location} unotangira pa USD {price}.\n"
        "Ungada here:\n"
        "1. Kusimbisa & Kurodha Basa\n"
        "2. Kudzokera kuMamwe Mabasa",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'flushing_booking_confirm2', 'user': user.to_dict()})
    return {'step': 'flushing_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_flushing_booking_confirm2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Ndapota nyora zita rako rizere:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name2', 'user': user.to_dict()})
        return {'step': 'booking_full_name2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu2("0", user_data, phone_id)

    else:
        send("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'flushing_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pvc_casing_selection2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()
    pvc_map = {
        "1": "Class 6 – Standard",
        "2": "Class 9 – Stronger",
        "3": "Class 10 – Strongest"
    }

    casing_class = pvc_map.get(choice)
    if not casing_class:
        send("Ndapota sarudza sarudzo yakakodzera (1-3).", user_data['sender'], phone_id)
        return {'step': 'pvc_casing_selection2', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['pvc_casing_class'] = casing_class

    send(f"Mutengo we {casing_class} PVC casing unotsamira panzvimbo yako.\nNdapota nyora nzvimbo yako:",
         user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'pvc_casing_location2', 'user': user.to_dict()})
    return {'step': 'pvc_casing_location2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pvc_casing_location2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.quote_data['location'] = location

    casing_class = user.quote_data.get('pvc_casing_class')

    price = get_pricing_for_other_services(location, "pvc_casing", {'class': casing_class})

    send(
        f"Mutengo we {casing_class} PVC casing munzvimbo ye {location} uri USD {price}.\n"
        "Ungada here:\n"
        "1. Kusimbisa & Kurodha\n"
        "2. Kudzokera kuMamwe Mabasa",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'pvc_casing_booking_confirm2', 'user': user.to_dict()})
    return {'step': 'pvc_casing_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pvc_casing_booking_confirm2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Ndokumbirawo upe zita rako rizere:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name2', 'user': user.to_dict()})
        return {'step': 'booking_full_name2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu2("0", user_data, phone_id)

    else:
        send("Ndokumbirawo usarudze sarudzo chaiyo (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'pvc_casing_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_full_name2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    full_name = prompt.strip()
    user.booking_data['full_name'] = full_name
    send("Ndokumbirawo upe nhamba yako yefoni:", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_phone2', 'user': user.to_dict()})
    return {'step': 'booking_phone2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_phon2e(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    phone = prompt.strip()
    user.booking_data['phone'] = phone
    send("Ndokumbirawo nyora nzvimbo yako chaiyo/kero kana kuti tumira GPS pin yako:", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_location2', 'user': user.to_dict()})
    return {'step': 'booking_location2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_location2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.booking_data['location'] = location
    send("Ndokumbirawo nyora zuva raunoda kusungira basa (semuenzaniso, 2024-10-15):", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_date2', 'user': user.to_dict()})
    return {'step': 'booking_date2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_date2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    booking_date = prompt.strip()
    user.booking_data['date'] = booking_date
    send("Kana uine zvimwe zvinyorwa kana zvikumbiro, nyora zvino. Kana usina, nyora 'Kwete':", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_notes2', 'user': user.to_dict()})
    return {'step': 'booking_notes2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_notes2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    notes = prompt.strip()
    user.booking_data['notes'] = notes if notes.lower() != 'no' else ''
    
    # At this point, save booking to database or call booking API
    booking_confirmation_number = save_booking(user.booking_data)  # You must implement save_booking

    send(
        f"Tinotenda {user.booking_data['full_name']}! Kusungirwa kwako kwasimbiswa.\n"
        f"Reference yeBooking: {booking_confirmation_number}\n"
        "Chikwata chedu chichakutaurira munguva pfupi.\n"
        "Nyora 'menu' kudzokera kumenyu huru.",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'main_menu2', 'user': user.to_dict()})
    return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pump_status_info_request2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Ndokumbirawo upe zita rako rizere uye reference number kana nhamba yefoni, imwe neimwe mutsara mutsva.\n\n"
            "Muenzaniso:\n"
            "Jane Doe\nREF123456\nZvingasarudzwa: Harare",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request2',
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

    send("Tinotenda. Ndapota mirira apo tiri kutora ruzivo nezve chimiro cheprojekiti yako...", user_data['sender'], phone_id)

    send(
        f"Heano mamiriro eprojekiti yako yepombi:\n\n"
        f"Zita rePurojekiti: Pombi - {full_name}\n"
        f"Chikamu Chazvino: Kuisa Kwapedzwa\n"
        f"Nhanho Inotevera: Kuongorora kwekupedzisira\n"
        f"Nguva Yekupedzisira Kuunza: 12/06/2025\n\n"
        "Ungade kugamuchira zviziviso paWhatsApp kana chimiro chako chachinja here?\nSarudzo: Ehe / Kwete",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'pump_status_updates_opt_in2',
        'user': user.to_dict()
    })

    return {
        'step': 'pump_status_updates_opt_in2',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_pump_status_updates_opt_in2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yes', 'y', 'ehe']:
        send(
            "Zvakanaka! Iwe zvino uchagamuchira zviziviso paWhatsApp pese paanochinja chimiro chekuvaka borehole yako.\n\n"
            "Tinotenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    elif response in ['no', 'n', 'kwete']:
        send(
            "Hazvina basa. Unogona kugara uchitarisa chimiro zvakare kana zvichidikanwa.\n\n"
            "Tinotenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ndine urombo, handina kunzwisisa. Ndokumbirawo upindure neEhe kana Kwete.", user_data['sender'], phone_id)
        return {'step': 'pump_status_updates_opt_in2', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_drilling_status_updates_opt_in2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yes', 'y']:
        send(
            "Zvakanaka! Iwe zvino unozogamuchira WhatsApp zvinovandudzwa pese panoshanduka mamiriro ekuchera borehole yako.\n\n"
            "Tatenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    elif response in ['no', 'n']:
        send(
            "Hazvina mhosva. Unogona kugara uchiongorora mamiriro zvakare gare gare kana zvichidikanwa.\n\n"
            "Tatenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ndine urombo, handina kunzwisisa. Ndokumbira upindure neEhe kana Kwete.", user_data['sender'], phone_id)
        return {'step': 'drilling_status_updates_opt_in2', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_check_project_status_menu2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'drilling_status_info_request2',
            'user': user.to_dict()
        })

        send(
            "Kuti utarise mamiriro echero borehole yako, ndapota upe zvinotevera:\n\n"
            "- Zita rakazara rawakashandisa pakuodha\n"
            "- Nhamba yereferensi yeprojekiti kana Nhamba yefoni\n"
            "- Nzvimbo yekuchera (zvingasarudzwa)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request2',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'pump_status_info_request2',
            'user': user.to_dict()
        })
        send(
            "Kuti utarise mamiriro ekuisirwa pombi yako, ndapota upe zvinotevera:\n\n"
            "- Zita rakazara rawakashandisa pakuodha\n"
            "- Nhamba yereferensi yeprojekiti kana Nhamba yefoni\n"
            "- Nzvimbo yekuisa pombi (zvingasarudzwa)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request2',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'human_agent2',
            'user': user.to_dict()
        })
        send("Ndokumbira mirira ndichakubatanidza kune mumwe wevashandi vedu vekutsigira.", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        return handle_main_menu2("", user_data, phone_id)

    else:
        send("Sarudzo isiriyo. Ndokumbira usarudze 1, 2, 3, kana 4.", user_data['sender'], phone_id)
        return {'step': 'check_project_status_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_drilling_status_info_request2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Ndapota ipa zita rako rakazara uye nhamba yereferensi kana nhamba yefoni, rimwe pamsara mutsva.\n\n"
            "Muenzaniso:\n"
            "John Doe\nREF789123 kana 0779876543\nZvingasarudzwa: Bulawayo",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request2',
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

    send("Tatenda. Ndokumbira mirira tichitsvaga mamiriro eprojekiti yako...", user_data['sender'], phone_id)

    send(
        f"Heino mamiriro eprojekiti yako yekuchera borehole:\n\n"
        f"Zita reprojekiti: Borehole - {full_name}\n"
        f"Chikamu Chazvino: Kuchera Kurikuitwa\n"
        f"Chinotevera: Kuiswa kweCasing\n"
        f"Zuva Rekupedzisa Rakatarwa: 10/06/2025\n\n"
        "Ungade here kugamuchira WhatsApp zvinovandudzwa kana mamiriro achichinja?\nSarudzo: Ehe / Kwete",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'drilling_status_updates_opt_in2',
        'user': user.to_dict()
    })

    return {
        'step': 'drilling_status_updates_opt_in2',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_select_pump_option2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if prompt.strip() not in pump_installation_options:
        send("Sarudzo isiriyo. Ndokumbira usarudze sarudzo yemhando yepombi yekuisa (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option2', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes(location, "Pump Installation", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup2',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)
    
    return {
        'step': 'quote_followup2',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_quote_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt.strip() == "1":
        # Stay in quote flow, show services again
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote2',
            'user': user.to_dict()
        })
        send(
            "Sarudza imwe sevhisi:\n"
            "1. Kuongorora kwemvura\n"
            "2. Kuchera borehole\n"
            "3. Kuisa pombi\n"
            "4. Kuchera borehole rekutengeserana\n"
            "5. Kuomesa borehole",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "2":
        # Go back to main menu
        update_user_state(user_data['sender'], {
            'step': 'main_menu2',
            'user': user.to_dict()
        })
        send(
            "Tinokubatsirei nhasi?\n\n"
            "1. Kumbira mutengo\n"
            "2. Tsvaga Mutengo Uchishandisa Nzvimbo\n"
            "3. Tarisa Mamiriro eProjekiti\n"
            "4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Kuchera Borehole\n"
            "5. Dzimwe sevhisi\n"
            "6. Taura nemumwe Mushandi Wedu\n\n"
            "Ndokumbira upindure nenhamba (semuenzaniso, 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "3":
        # Offer price
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details2',
            'user': user.to_dict()    
        })
        send(
            "Zvakanaka! Unogona kugovera mutengo waunofunga pazasi.\n\n",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sarudzo isiriyo. Pindura 1 kuti ubvunze nezveshumiro imwe, 2 kudzokera kumenu huru, kana 3 kana uchida kupa mutengo.", user_data['sender'], phone_id)
        return {'step': 'quote_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


#---------------------------------------------------NDEBELE-----------------------------------------------------------------
def handle_main_menu3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":  # Request a quote
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote3',
            'user': user.to_dict()
        })
        send("Sicela ufake indawo yakho (Idolobha/Idolobhana noma i-GPS) ukuze siqale.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Search Price Using Location
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote3',
            'user': user.to_dict()
        })
        send(
            "Ukuze sikunikeze intengo, sicela ufake indawo yakho (Idolobha/Idolobhana noma i-GPS):",
            user_data['sender'], phone_id
        )
        return {'step': 'enter_location_for_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Check Project Status
        update_user_state(user_data['sender'], {
            'step': 'check_project_status_menu3',
            'user': user.to_dict()
        })
        send(
            "Sicela ukhethe inketho:\n"
            "1. Bheka isimo sokumba iborehole\n"
            "2. Bheka isimo sokufaka iphampu\n"
            "3. Khuluma lomuntu osebenza lapha\n"
            "4. Buyela kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'check_project_status_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # FAQ
        update_user_state(user_data['sender'], {
            'step': 'faq_menu3',
            'user': user.to_dict()
        })
        send(
            "Sicela ukhethe isigaba se-FAQ:\n\n"
            "1. Imibuzo yeBorehole Drilling\n"
            "2. Imibuzo yePump Installation\n"
            "3. Buza olunye umbuzo\n"
            "4. Khuluma lomuntu osebenza lapha\n"
            "5. Buyela kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Other Services
        update_user_state(user_data['sender'], {
            'step': 'other_services_menu3',
            'user': user.to_dict()
        })
        send(
            "Siyakwamukela kwezinye izinsiza zeBorehole. Yiziphi ofuna ukuzithola?\n"
            "1. Ukwandisa ukujula kweBorehole\n"
            "2. Ukugeza iBorehole (Flushing)\n"
            "3. Ukukhetha amapayipi ePVC casing\n"
            "4. Buyela kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'other_services_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "6":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent3',
            'user': user.to_dict()
        })
        send("Siyakuxhumanisa lomsebenzi wabantu...", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efaneleyo (1-6).", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}


def human_agent3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    customer_number = user_data['sender']
    customer_name = user.name if hasattr(user, "name") and user.name else "Unknown"
    agent_number = "+263719835124"

    # Notify the customer immediately
    send(
        "Siyabonga. Sicela ulinde ngenkathi sixhumanisa wena lommeleli we-SpeedGo...",
        customer_number, phone_id
    )

    # Notify the agent
    agent_message = (
        f"👋 Kukhona ikhasimende elifuna ukukhuluma lawe ku-WhatsApp.\n\n"
        f"📱 Inombolo yekhasimende: {customer_number}\n"
        f"🙋 Ibizo: {customer_name}\n"
        f"📩 Umlayezo wokugcina: \"{prompt}\""
    )
    send(agent_message, agent_number, phone_id)

    update_user_state(customer_number, {
        'step': 'waiting_for_human_agent_response3',
        'user': user.to_dict(),
        'sender': customer_number,
        'agent_prompt_time': time.time()
    })

    return {'step': 'handle_user_message3', 'user': user.to_dict(), 'sender': customer_number}


def notify_agent3(customer_number, prompt, agent_number, phone_id):
    agent_message = (
        f"👋 Isicelo esisha sekhasimende ku-WhatsApp\n\n"
        f"📱 Inombolo: {customer_number}\n"
        f"📩 Umlayezo: \"{prompt}\""
    )
    send(agent_message, agent_number, phone_id)


def send_fallback_option3(customer_number, phone_id):
    user_data = get_user_state(customer_number)
    if user_data and user_data.get('step') == 'waiting_for_human_agent_response3':
        send("Nxa ungathanda, ungaxhumana nathi ngqo ku-+263719835124.", customer_number, phone_id)
        send("Ungathanda ukubuyela kuMain Menu?\n1. Yebo\n2. Hatshi", customer_number, phone_id)
        update_user_state(customer_number, {
            'step': 'human_agent_followup3',
            'user': user_data.get('user', {}),
            'sender': customer_number
        })


def handle_user_message3(message, user_data, phone_id):
    state = user_data.get('step')
    customer_number = user_data['sender']

    if state == 'waiting_for_human_agent_response3':
        prompt_time = user_data.get('agent_prompt_time', 0)
        elapsed = time.time() - prompt_time

        if elapsed >= 10:
            send(
                "Ungathanda, ungathumela umlayezo noma usifonele ngqo ku-+263719835124.",
                customer_number, phone_id
            )
            send(
                "Ungathanda ukubuyela kuMain Menu?\n1. Yebo\n2. Hatshi",
                customer_number, phone_id
            )
            update_user_state(customer_number, {
                'step': 'human_agent_followup3',
                'user': user_data['user'],
                'sender': customer_number
            })
            return {'step': 'human_agent_followup3', 'user': user_data['user'], 'sender': customer_number}
        else:
            return user_data

    elif state == 'human_agent_followup3':
        if message.strip() == '1':
            send("Sibuyisela wena kuMain Menu...", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'main_menu3',
                'user': user_data['user'],
                'sender': customer_number
            })
            send_main_menu3(customer_number, phone_id)
            return {'step': 'main_menu3', 'user': user_data['user'], 'sender': customer_number}

        elif message.strip() == '2':
            send("Siyabonga! Usuku oluhle kuwe.", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'end',
                'user': user_data['user'],
                'sender': customer_number
            })
            return {'step': 'end', 'user': user_data['user'], 'sender': customer_number}
        else:
            send("Sicela uphendule ngo 1 (Yebo) kumbe 2 (Hatshi).", customer_number, phone_id)
            return user_data


def human_agent_followup3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        return handle_select_language("1", user_data, phone_id)

    elif prompt == "2":
        send("Kulungile. Zizwe ukhululekile ukubuza nxa udinga olunye usizo.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela uphendule ngo 1 ukuze ubuyele kuMain Menu noma ngo 2 ukuhlala lapha.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_menu3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole3',
            'user': user.to_dict()
        })
        send(
            "Nansi imibuzo evame ukubuzwa mayelana lokumba iBorehole:\n\n"
            "1. Kubiza malini ukumba iBorehole?\n"
            "2. Kuthatha isikhathi esingakanani ukumba iBorehole?\n"
            "3. I-Borehole yami izakujula kangakanani?\n"
            "4. Ngidinga imvumo yini ukuze ngimbwe iBorehole?\n"
            "5. Lenza ukuhlolwa kwamanzi kanye lokumba ngesikhathi esisodwa yini?\n"
            "6. Kwenzakalani nxa lingathola amanzi ngesikhathi sokuhlola?\n"
            "7. Yiziphi izinsiza ezisetshenziswa?\n"
            "8. Buyela kuFAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Pump Installation FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_pump3',
            'user': user.to_dict()
        })
        send(
            "Nansi imibuzo evamile mayelana lokufakwa kwepampu:\n\n"
            "1. Kuyini okuhlukanisayo phakathi kwepampu yeSolar leye-Electric?\n"
            "2. Lingayifaka yini nxa sengilalezinto zonke?\n"
            "3. Kuthatha isikhathi esingakanani ukufaka ipampu?\n"
            "4. Ngidinga ipampu enjani?\n"
            "5. Linikezela ngamathangi kanye lezindawo zokuwabeka yini?\n"
            "6. Buyela kuFAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Ask a different question
        update_user_state(user_data['sender'], {
            'step': 'custom_question3',
            'user': user.to_dict()
        })
        send(
            "Sicela bhala umbuzo wakho ngezansi, sizazama ukukusiza kangcono.\n",
            user_data['sender'], phone_id
        )
        return {'step': 'custom_question3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent3',
            'user': user.to_dict(),
            'sender': user_data['sender']
        })
        send("Sicela ulinde ngenkathi sixhumanisa lawe lommeleli...", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Back to Main Menu
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Sicela ukhethe inketho efaneleyo (1–5).", user_data['sender'], phone_id)
        return {'step': 'faq_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}


def custom_question3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if not prompt.strip():
        send("Sicela ubhale umbuzo wakho.", user_data['sender'], phone_id)
        return {'step': 'custom_question3', 'user': user.to_dict(), 'sender': user_data['sender']}

    system_prompt = (
        "You are a helpful assistant for SpeedGo, a borehole drilling and pump installation company in Zimbabwe. "
        "You will only answer questions related to SpeedGo's services, pricing, processes, or customer support. "
        "If the user's question is unrelated to SpeedGo, politely let them know that you can only assist with SpeedGo-related topics."
    )

    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content([system_prompt, prompt])
        answer = response.text.strip() if hasattr(response, "text") else "Uxolo, angikwazanga ukuphendula okwamanje."
    except Exception as e:
        answer = "Uxolo, kube lephutha ekuphenduleni umbuzo wakho. Zama futhi emuva kwesikhatshana."
        print(f"[Gemini error] {e}")

    send(answer, user_data['sender'], phone_id)

    send(
        "Ungathanda:\n"
        "1. Ukubuza omunye umbuzo\n"
        "2. Ukubuyela kuMain Menu",
        user_data['sender'], phone_id
    )

    return {'step': 'custom_question_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}


def custom_question_followup3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send("Sicela ubhale omunye umbuzo wakho.", user_data['sender'], phone_id)
        return {'step': 'custom_question3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Sicela uphendule ngo-1 ukuze ubuze omunye umbuzo noma ngo-2 ukubuyela kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'custom_question_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_borehole3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Intengo incike endaweni okuyo, ukujula, kanye lomhlaba. Sicela usithumele indawo yakho kanye lokuthi singafinyelela njani lapho ukuze sikunikeze isiphakamiso esifaneleyo.",
        "2": "Ngokuvamile kuthatha amahora angu-4 kuya kwangu-6, kodwa kungadlulela ezinsukwini ezimbalwa kuye ngokuthi indawo injani.",
        "3": "Ukujula kwe-borehole kuyahluka. Okuvamile ku-40m, kodwa kungafika ku-150m kuye ngokujula kwamanzi angaphansi komhlaba.",
        "4": "Kwezinye izindawo, imvumo iyadingeka. Siyakwazi ukukusiza ukuyifaka.",
        "5": "Yebo, senza kokubili ndawonye noma ngokwahlukana kuya ngokuthanda kwakho.",
        "6": "Uma ungatholi amanzi endaweni yokuqala, siyakwazi ukumba kwenye indawo ngesaphulelo.\n\nQaphela: Imitshina yokuhlola ayilinganisi inani lamanzi, ingaveza indawo ezinamanzi kuphela. Ngalokho, asikho isiqinisekiso sokuthi amanzi azokhishwa.",
        "7": "Sisebenzisa izinsiza zokumba ezisezingeni eliphezulu (rotary le percussion rigs), amathuluzi e-GPS, kanye lemitshina yokuhlola umhlaba.",
        "8": "Sibuyela kuFAQ Menu..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Ungathanda:\n"
            "1. Ukubuza omunye umbuzo ku-Borehole Drilling FAQs\n"
            "2. Ukubuyela kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efaneleyo (1–8).", user_data['sender'], phone_id)
        return {'step': 'faq_borehole3', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_borehole_followup3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send(
            "Sicela ukhethe umbuzo:\n\n"
            "1. Kubiza malini ukumba iBorehole?\n"
            "2. Kuthatha isikhathi esingakanani ukumba iBorehole?\n"
            "3. I-Borehole yami izakuba yinde kangakanani?\n"
            "4. Ngidinga imvumo yini ukuze ngimbwe iBorehole?\n"
            "5. Lenza ukuhlolwa kwamanzi kanye lokumba ngesikhathi esisodwa yini?\n"
            "6. Kwenzakalani nxa lingatholi amanzi?\n"
            "7. Yiziphi izinsiza ezisetshenziswa?\n"
            "8. Buyela kuFAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Sicela ukhethe 1 ukuze ubuze omunye umbuzo noma 2 ukubuyela kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump3(prompt, user_data, phone_id):
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
            return {'step': 'faq_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Ungathanda:\n"
            "1. Ukubuza omunye umbuzo kuPump Installation FAQs\n"
            "2. Ukubuyela kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efaneleyo (1–6).", user_data['sender'], phone_id)
        return {'step': 'faq_pump3', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump_followup3(prompt, user_data, phone_id):
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
        return {'step': 'faq_pump3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Sicela ukhethe 1 ukuze ubuze omunye umbuzo noma 2 ukubuyela kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_enter_location_for_quote3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    
    if 'location' in user_data and 'latitude' in user_data['location'] and 'longitude' in user_data['location']:
        lat = user_data['location']['latitude']
        lng = user_data['location']['longitude']
        gps_coords3 = f"{lat},{lng}"
        location_name3 = reverse_geocode_location3(gps_coords)

        if location_name3:
            user.quote_data['location'] = location_name3
            user.quote_data['gps_coords'] = gps_coords3
            update_user_state(user_data['sender'], {
                'step': 'select_service_quote3',
                'user': user.to_dict()
            })
            send(
                f"Indawo etholakele: {location_name3.title()}\n\n"
                "Sicela ukhethe inkonzo ofunayo:\n"
                "1. Ukuhlolwa kwamanzi\n"
                "2. Ukumba iBorehole\n"
                "3. Ukufakwa kwepampu\n"
                "4. Ukumba umgodi wezentengiselwano\n"
                "5. Ukwelula iBorehole (Deepening)",
                user_data['sender'], phone_id
            )
            return {'step': 'select_service_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}
        else:
            send("Asikwazanga ukuhlonza indawo yakho. Sicela bhala igama ledolobho/lindawo yakho ngesandla.", user_data['sender'], phone_id)
            return {'step': 'enter_location_for_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        location_name = prompt.strip()
        user.quote_data['location'] = location_name.lower()
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote3',
            'user': user.to_dict()
        })
        send(
            "Sicela ukhethe inkonzo ofunayo:\n"
            "1. Ukuhlolwa kwamanzi\n"
            "2. Ukumba iBorehole\n"
            "3. Ukufakwa kwepampu\n"
            "4. Ukumba umgodi wezentengiselwano\n"
            "5. Ukwelula iBorehole (Deepening)",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_select_service3(prompt, user_data, phone_id):
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
            'step': 'collect_quote_details3',
            'user': user.to_dict()
        })
        send(
            "Ukuthi sikunikeze inani elilinganiselweyo, sicela uphendule okulandelayo:\n\n"
            "1. Indawo okuyo (Idolobho/lok GPS):\n",
            user_data['sender'], phone_id
        )
        return {'step': 'handle_select_service_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ukhethe inketho efaneleyo (1–5).", user_data['sender'], phone_id)
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
            'step': 'quote_response3',
            'user': user.to_dict()
        })
        estimate = "Class 6: Estimated Cost: $2500\nIncludes drilling, PVC casing 140mm"
        send(
            f"Siyabonga! Ngokusekelwe kulokho osikhiphile:\n\n"
            f"{estimate}\n\n"
            f"Qaphela: Uma kudingeka casing kabili, lokhu kuzongezwa njengesindleko esengezelelweyo ngemvumo yakho.\n\n"
            f"Ungathanda:\n"
            f"1. Ukunikeza inani lakho?\n"
            f"2. Ukubhukha Ukuhlolwa Kwendawo\n"
            f"3. Ukubhukha Ukumba\n"
            f"4. Ukukhuluma Lomuntu Wenkampani",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_response3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela uphephe konke okufunekayo (okungenani imigqa engu-4).", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_quote_response3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details3',
            'user': user.to_dict()
        })
        send(
            "Kulungile! Ungabelana ngezintengo ozicabangayo ngezansi.\n\n"
            "Sicela uphendule ngendlela engezansi:\n\n"
            "- Ukuhlolwa kwamanzi: $_\n"
            "- Ukumba iBorehole: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info3',
            'user': user.to_dict()
        })
        send(
            "Kuhle! Sicela unikeze ulwazi olulandelayo ukuze siqedele ukubhuka kwakho:\n\n"
            "- Igama eliphelele:\n"
            "- Usuku olukhethwayo (dd/mm/yyyy):\n"
            "- Ikheli lendawo: GPS noma ikheli\n"
            "- Inombolo yefoni:\n"
            "- Indlela yokukhokha (Prepayment / Cash lapho endaweni):\n\n"
            "Bhala: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":
        send("Umuntu wethu uzokuthinta ukuze aqedele ukubhuka kokumba.", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        send("Sikuxhumanisa lomsebenzi weSpeedGo...", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efaneleyo (1–4).", user_data['sender'], phone_id)
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
        "Isiphakamiso sakho sesithunyelwe kumphathi wezokuthengisa. Sizokuphendula kungakapheli ihora eli-1.\n\n"
        "Siyabonga ngesiphakamiso sakho!\n\n"
        "Iqembu lethu lizasibuyekeza likuphendule ngokushesha.\n\n"
        "Intengo yethu ikhombisa ikhwalithi, ukuphepha, leqiniso.\n\n"
        "Ungathanda:\n"
        "1. Qhubeka uma isiphakamiso samukelwe\n"
        "2. Khuluma lomuntu\n"
        "3. Lungisa isiphakamiso sakho",
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
            "Izindaba ezinhle! Isiphakamiso sakho samukelwe.\n\n"
            "Asiqinisekise igxathu elilandelayo.\n\n"
            "Ungathanda:\n"
            "1. Bhuka Ukuhlolwa Kwendawo\n"
            "2. Khokha iDeposit\n"
            "3. Qinisekisa Usuku Lokumba",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_details3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        send("Sikuxhumanisa lomsebenzi weSpeedGo...", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details3',
            'user': user.to_dict()
        })
        send(
            "Sicela uphendule ngesiphakamiso esilungisiwe ngendlela engezansi:\n\n"
            "- Ukuhlolwa kwamanzi: $_\n"
            "- Ukumba iBorehole: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efaneleyo (1–3).", user_data['sender'], phone_id)
        return {'step': 'offer_response3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_details3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info3',
            'user': user.to_dict()
        })
        send(
            "Kuhle! Sicela unikeze ulwazi olulandelayo ukuze siqedele ukubhuka kwakho:\n\n"
            "- Igama eliphelele:\n"
            "- Usuku olukhethwayo (dd/mm/yyyy):\n"
            "- Ikheli lendawo: GPS noma ikheli\n"
            "- Inombolo yefoni:\n"
            "- Indlela yokukhokha (Prepayment / Cash lapho):\n\n"
            "Bhala: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        send("Sicela uthinte ihhovisi lethu ku-077xxxxxxx ukuze uhlele inkokhelo yeDeposit.", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":
        send("Umsebenzi wethu uzokuthinta ukuze aqinisekise usuku lokumba.", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efaneleyo (1–3).", user_data['sender'], phone_id)
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
            "Siyabonga. Ukuqokwa kwakho sekugunyaziwe, futhi uchwepheshe uzokuthinta maduze.\n\n"
            f"Isikhumbuzo: Ukuhlolwa kwendawo kuhlelwe kusasa.\n\n"
            f"Usuku: {booking_date}\n"
            f"Isikhathi: {booking_time}\n\n"
            "Silindele ukusebenza lawe!\n"
            "Udinga ukulungisa isikhathi?\n\n"
            "1. Yebo\n"
            "2. Hatshi",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_confirmation3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ubhale 'Submit' ukuze uqinisekise ukubhuka kwakho.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_confirmation3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "2":
        send(
            "Kuhle! Ukuqokwa kwakho kokumba iborehole sekubhukiwe.\n\n"
            "Usuku: ULwesine, 23 May 2025\n"
            "Isikhathi sokuqala: 8:00 AM\n"
            "Isikhathi esilindelekileyo: amahora ama-5\n"
            "Iqembu: Osebenza abangu-4 kuya ku-5\n\n"
            "Qinisekisa ukuthi indawo iyafinyeleleka.",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela uxhumane neqembu lethu ukuze ulungise isikhathi sokuhlolwa.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_select_service_quote3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')

    if not location:
        send("Sicela uqale unikeze indawo yakho ngaphambi kokukhetha insiza.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}

    service_map = {
        "1": "Water Survey",
        "2": "Borehole Drilling",
        "3": "Pump Installation",
        "4": "Commercial Hole Drilling",
        "5": "Borehole Deepening"
    }

    selected_service = service_map.get(prompt.strip())

    if not selected_service:
        send("Inketho engavumelekile. Sicela uphendule ngo-1, 2, 3, 4 noma 5 ukukhetha insiza.", user_data['sender'], phone_id)
        return {'step': 'select_service_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['service'] = selected_service

    if selected_service == "Pump Installation":
        update_user_state(user_data['sender'], {
            'step': 'select_pump_option3',
            'user': user.to_dict()
        })
        message_lines = [f"💧 Izinketho Zokufaka iPump:\n"]
        for key, option in pump_installation_options3.items():
            desc = option.get('description', 'Akukho incazelo')
            message_lines.append(f"{key}. {desc}")
        send("\n".join(message_lines), user_data['sender'], phone_id)
        return {'step': 'select_pump_option3', 'user': user.to_dict(), 'sender': user_data['sender']}

    pricing_message = get_pricing_for_location_quotes(location, selected_service)

    update_user_state(user_data['sender'], {
        'step': 'quote_followup3',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'quote_followup3',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_other_services_menu3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send(
            "Ukuze sihlolisise ukuthi iborehole yakho ingajuliswa yini:\n"
            "Ingabe iborehole yafakelwa amapayipi:\n"
            "1. Phezulu kuphela, ngepayipi elingange-180mm noma elikhulu\n"
            "2. Kusukela phezulu kuye ezansi, ngepayipi elingange-140mm noma elincane",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_deepening_casing3', 'user': user.to_dict()})
        return {'step': 'borehole_deepening_casing3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send(
            "Iyiphi inkinga ngeborehole yakho?\n"
            "1. Iborehole eye yabhidlika\n"
            "2. Amanzi angcolile ephuma eborehole",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_flushing_problem3', 'user': user.to_dict()})
        return {'step': 'borehole_flushing_problem3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "3":
        send(
            "Sihlinzeka ngokumba iBorehole sisebenzisa amapayipi ePVC alandelayo:\n"
            "1. Class 6 – Ejwayelekile\n"
            "2. Class 9 – Eqinile\n"
            "3. Class 10 – Eqine kakhulu\n"
            "Ungathanda ukubona yiphi?",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'pvc_casing_selection3', 'user': user.to_dict()})
        return {'step': 'pvc_casing_selection3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "4":
        update_user_state(user_data['sender'], {'step': 'main_menu3', 'user': user.to_dict()})
        send_main_menu3(user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efaneleyo (1–4).", user_data['sender'], phone_id)
        return {'step': 'other_services_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}


def send_main_menu3(phone_number, phone_id):
    menu_text = (
        "Singakusiza njani lamuhla?\n\n"
        "1. Cela isilinganiso sentengo\n"
        "2. Phendla intengo ngokusebenzisa indawo\n"
        "3. Hlola isimo sephrojekthi\n"
        "4. Imibuzo evame ukubuzwa noma funda ngokumba iborehole\n"
        "5. Ezinye izinsiza\n"
        "6. Khuluma lomuntu\n\n"
        "Sicela uphendule ngenombolo (isb. 1)"
    )
    send(menu_text, phone_number, phone_id)


def handle_borehole_deepening_casing3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send("Iborehole yakho iyafaneleka ukuba ijuliswe.\nSicela ufake indawo yakho (idolobha, i-ward, i-growth point, noma i-GPS pin):",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'deepening_location3', 'user': user.to_dict()})
        return {'step': 'deepening_location3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send(
            "Ngokudabukisayo, ama-borehole afakwe amapayipi avela phezulu aze phansi ngepayipi elincane kune-180mm awakwazi ukujuliswa.\n"
            "Izinketho:\n"
            "1. Buyela kwezinye izinsiza\n"
            "2. Khuluma nethimba elisekelayo",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'deepening_no_deepening_options3', 'user': user.to_dict()})
        return {'step': 'deepening_no_deepening_options3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe inketho efaneleyo (1 noma 2).", user_data['sender'], phone_id)
        return {'step': 'borehole_deepening_casing3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_no_deepening_options3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        return handle_other_services_menu3("0", user_data, phone_id)
    elif choice == "2":
        send("Sizakuxhumanisa lethimba elisekelayo...", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'human_agent3', 'user': user.to_dict()})
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ukhethe inketho efaneleyo (1 noma 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_no_deepening_options3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_location3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.quote_data['location'] = location
    price = get_pricing_for_location_quotes(location, "borehole_deepening")

    send(
        f"Intengo yokujulisa e-{location} iqala ku-USD {price} nge-meter.\n"
        "Ungathanda:\n"
        "1. Ukuqinisekisa lokubhuka umsebenzi\n"
        "2. Buyela kwezinye izinsiza",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'deepening_booking_confirm3', 'user': user.to_dict()})
    return {'step': 'deepening_booking_confirm3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_booking_confirm3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Sicela unikeze igama lakho eliphelele:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name3', 'user': user.to_dict()})
        return {'step': 'booking_full_name3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif choice == "2":
        return other_services_menu3("0", user_data, phone_id)
    else:
        send("Sicela ukhethe inketho efaneleyo (1 noma 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_booking_confirm3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_borehole_flushing_problem3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send(
            "Uyakwazi ububanzi be-borehole yakho?\n"
            "1. 180mm noma okukhulu\n"
            "2. Phakathi kuka-140mm no-180mm\n"
            "3. 140mm noma okuncane",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'flushing_collapsed_diameter3', 'user': user.to_dict()})
        return {'step': 'flushing_collapsed_diameter3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif choice == "2":
        send("Sicela ufake indawo yakho ukuze sihlolise intengo:", user_data['sender'], phone_id)
        user.quote_data['flushing_type'] = 'dirty_water'
        update_user_state(user_data['sender'], {'step': 'flushing_location3', 'user': user.to_dict()})
        return {'step': 'flushing_location3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ukhethe inketho efaneleyo (1 noma 2).", user_data['sender'], phone_id)
        return {'step': 'borehole_flushing_problem3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_flushing_collapsed_diameter3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()
    diameter_map = {
        "1": "180mm_or_larger",
        "2": "between_140_and_180mm",
        "3": "140mm_or_smaller"
    }

    diameter = diameter_map.get(choice)
    if not diameter:
        send("Sicela ukhethe inketho efaneleyo (1-3).", user_data['sender'], phone_id)
        return {'step': 'flushing_collapsed_diameter3', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['flushing_type'] = 'collapsed'
    user.quote_data['diameter'] = diameter

    if diameter == "180mm_or_larger":
        send("Singakwazi ukuhlanza i-borehole yakho sisebenzisa ama-rods kanye ne-drilling bit (kusebenza kangcono).\nSicela ufake indawo yakho ukuze sihlolise intengo:",
             user_data['sender'], phone_id)
    elif diameter == "between_140_and_180mm":
        send("Singakwazi ukuhlanza i-borehole sisebenzisa ama-rods kuphela, ngaphandle kwe-drilling bit.\nSicela ufake indawo yakho ukuze sihlolise intengo:",
             user_data['sender'], phone_id)
    elif diameter == "140mm_or_smaller":
        send("Sisebenzisa ama-rods kuphela ngaphandle kwe-drilling bit ukuhlanza i-borehole.\nSicela ufake indawo yakho ukuze sihlolise intengo:",
             user_data['sender'], phone_id)

    update_user_state(user_data['sender'], {'step': 'flushing_location3', 'user': user.to_dict()})
    return {'step': 'flushing_location3', 'user': user.to_dict(), 'sender': user_data['sender']}


def calculate_borehole_drilling_price3(location, drilling_class, actual_depth_m):
    drilling_info = location_pricing3[location]["Borehole Drilling"]
    base_price = drilling_info[drilling_class]
    included_depth = drilling_info["included_depth_m"]
    extra_per_m = drilling_info["extra_per_m"]

    if actual_depth_m <= included_depth:
        return base_price

    extra_depth = actual_depth_m - included_depth
    extra_cost = extra_depth * extra_per_m
    return base_price + extra_cost


def handle_flushing_location3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.quote_data['location'] = location

    flushing_type = user.quote_data.get('flushing_type')
    diameter = user.quote_data.get('diameter')

    price = get_pricing_for_other_services3(location, "borehole_flushing", {
        'flushing_type': flushing_type,
        'diameter': diameter
    })

    send(
        f"Intengo yokugeza iborehole e-{location} iqala ku-USD {price}.\n"
        "Ungathanda:\n"
        "1. Ukuqinisekisa & Bhuka Umsebenzi\n"
        "2. Buyela Kwezinye Izinsiza",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'flushing_booking_confirm3', 'user': user.to_dict()})
    return {'step': 'flushing_booking_confirm3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_flushing_booking_confirm3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Sicela unikeze igama lakho eliphelele:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name3', 'user': user.to_dict()})
        return {'step': 'booking_full_name3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu3("0", user_data, phone_id)

    else:
        send("Sicela ukhethe inketho efaneleyo (1 noma 2).", user_data['sender'], phone_id)
        return {'step': 'flushing_booking_confirm3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pvc_casing_selection3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()
    pvc_map = {
        "1": "Class 6 – Ejwayelekile",
        "2": "Class 9 – Eqinile",
        "3": "Class 10 – Eqinile kakhulu"
    }

    casing_class = pvc_map.get(choice)
    if not casing_class:
        send("Sicela ukhethe inketho efaneleyo (1-3).", user_data['sender'], phone_id)
        return {'step': 'pvc_casing_selection3', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['pvc_casing_class'] = casing_class

    send(f"Intengo ye-{casing_class} PVC casing ixhomeke endaweni okuyo.\nSicela ufake indawo yakho:",
         user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'pvc_casing_location3', 'user': user.to_dict()})
    return {'step': 'pvc_casing_location3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pvc_casing_location3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.quote_data['location'] = location

    casing_class = user.quote_data.get('pvc_casing_class')

    price = get_pricing_for_other_services3(location, "pvc_casing", {'class': casing_class})

    send(
        f"Intengo ye-{casing_class} PVC casing e-{location} i-USD {price}.\n"
        "Ungathanda:\n"
        "1. Ukuqinisekisa & Bhuka\n"
        "2. Buyela Kwezinye Izinsiza",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'pvc_casing_booking_confirm3', 'user': user.to_dict()})
    return {'step': 'pvc_casing_booking_confirm3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pvc_casing_booking_confirm3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Sicela unikeze igama lakho eliphelele:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name3', 'user': user.to_dict()})
        return {'step': 'booking_full_name3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu3("0", user_data, phone_id)

    else:
        send("Sicela ukhethe inketho efaneleyo (1 noma 2).", user_data['sender'], phone_id)
        return {'step': 'pvc_casing_booking_confirm3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_full_name3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    full_name = prompt.strip()
    user.booking_data['full_name'] = full_name
    send("Sicela unikeze inombolo yakho yocingo:", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_phone3', 'user': user.to_dict()})
    return {'step': 'booking_phone3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_phone3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    phone = prompt.strip()
    user.booking_data['phone'] = phone
    send("Sicela ufake indawo yakho noma idilesi ngokuphelele, noma wabelane nge-GPS pin yakho:", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_location3', 'user': user.to_dict()})
    return {'step': 'booking_location3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_location3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.booking_data['location'] = location
    send("Sicela ufake usuku olufunayo lokubhuka (isb: 2024-10-15):", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_date3', 'user': user.to_dict()})
    return {'step': 'booking_date3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_date3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    booking_date = prompt.strip()
    user.booking_data['date'] = booking_date
    send("Uma unama-notes noma izicelo ezikhethekileyo, sicela uzifake manje. Noma bhala 'Hatshi':", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_notes3', 'user': user.to_dict()})
    return {'step': 'booking_notes3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_notes3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    notes = prompt.strip()
    user.booking_data['notes'] = notes if notes.lower() != 'hatshi' else ''

    booking_confirmation_number = save_booking(user.booking_data)

    send(
        f"Siyabonga {user.booking_data['full_name']}! Ukubhuka kwakho kuqinisekisiwe.\n"
        f"Inombolo Yokubhaliswa: {booking_confirmation_number}\n"
        "Iqembu lethu lizokuthinta kungekudala.\n"
        "Bhala 'menu' ukuze ubuyele emenyu enkulu.",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'main_menu3', 'user': user.to_dict()})
    return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pump_status_info_request3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Sicela unikeze okungenani igama lakho eliphelele kanye nenombolo yesithenjwa noma inombolo yefoni, ngakunye kulayini ohlukile.\n\n"
            "Isibonelo:\n"
            "Jane Doe\nREF123456\nKuyakhethwa: eHarare",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request3',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Akukho okunikeziwe"

    user.project_status_request3 = {
        'type': 'pump',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Siyabonga. Sicela ulinde sithathe isimo sephrojekthi yakho...", user_data['sender'], phone_id)

    send(
        f"Nansi imininingwane yephrojekthi yakho yokufakwa kwepompo:\n\n"
        f"Igama Lephrojekthi: Pompo - {full_name}\n"
        f"Isiteji Samanje: Ukufakwa Kuqediwe\n"
        f"Isinyathelo Esilandelayo: Ukuhlolwa Kokugcina\n"
        f"Usuku Lokudluliselwa: 12/06/2025\n\n"
        "Ungathanda ukuthola izibuyekezo ze-WhatsApp uma isimo sishintsha?\nIzinketho: Yebo / Hatshi",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'pump_status_updates_opt_in3',
        'user': user.to_dict()
    })

    return {
        'step': 'pump_status_updates_opt_in3',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_pump_status_updates_opt_in3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yebo', 'yes', 'y']:
        send(
            "Kuhle! Uzothola izibuyekezo ze-WhatsApp njalo uma isimo sephrojekthi yakho sishintsha.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    elif response in ['hatshi', 'no', 'n']:
        send(
            "Kulungile. Ungahlola isimo futhi noma kunini uma kudingeka.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    else:
        send("Uxolo, angiqondanga. Sicela uphendule ngo 'Yebo' noma 'Hatshi'.", user_data['sender'], phone_id)
        return {'step': 'pump_status_updates_opt_in3', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_drilling_status_updates_opt_in3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yes', 'y', 'yebo']:
        send(
            "Kuhle! Uzothola izibuyekezo ze-WhatsApp njalo uma isimo sokugawula ibhodi lishintsha.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    elif response in ['no', 'n', 'hatshi']:
        send(
            "Akusikho inkinga. Ungahlola isimo futhi noma kunini uma kudingeka.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    else:
        send("Uxolo, angiqondanga lokho. Sicela uphendule ngo 'Yebo' noma 'Hatshi'.", user_data['sender'], phone_id)
        return {'step': 'drilling_status_updates_opt_in3', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_check_project_status_menu3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'drilling_status_info_request3',
            'user': user.to_dict()
        })

        send(
            "Ukuze uhlolisise isimo sokugawula ibhodi lakho, sicela unikeze imininingwane elandelayo:\n\n"
            "- Igama eligcwele olalisebenzisa ngesikhathi ubhuka\n"
            "- Inombolo yesithenjwa sephrojekthi noma inombolo yefoni\n"
            "- Indawo yephrojekthi yokugawula (uyazikhethela)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request3',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'pump_status_info_request3',
            'user': user.to_dict()
        })
        send(
            "Ukuze uhlolisise isimo sokufakwa kwepompo yakho, sicela unikeze okulandelayo:\n\n"
            "- Igama eligcwele olalisebenzisa ngesikhathi ubhuka\n"
            "- Inombolo yesithenjwa sephrojekthi noma inombolo yefoni\n"
            "- Indawo yephrojekthi yokufakwa (uyazikhethela)",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request3',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'human_agent3',
            'user': user.to_dict()
        })
        send("Sicela ulinde ngenkathi sikuxhumanisa nelunga leqembu lethu lokusekela.", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        return handle_main_menu3("", user_data, phone_id)

    else:
        send("Inketho engavumelekile. Sicela ukhethe u-1, 2, 3, noma u-4.", user_data['sender'], phone_id)
        return {'step': 'check_project_status_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_drilling_status_info_request3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Sicela unikeze okungenani igama lakho eligcwele kanye lenombolo yesithenjwa noma inombolo yefoni, okuhleliwe umugqa ngamunye.\n\n"
            "Isibonelo:\n"
            "John Dube\nREF789123 noma 0779876543\nOzithandayo: Bulawayo",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request3',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Akukhonjwanga"

    user.project_status_request3 = {
        'type': 'drilling',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Siyabonga. Sicela ulinde njengoba silanda ulwazi lwephrojekthi yakho...", user_data['sender'], phone_id)

    send(
        f"Nansi inkcazelo yephrojekthi yakho yokugawula ibhodi:\n\n"
        f"Igama lePhrojekthi: Borehole - {full_name}\n"
        f"Isigaba Samanje: Ukuqhafaza Kuyaqhubeka\n"
        f"Isinyathelo Esilandelayo: Casing\n"
        f"Usuku Olulindelwe Lokuphela: 10/06/2025\n\n"
        "Ungathanda ukuthola izaziso ze-WhatsApp uma isimo sishintsha?\nKhetha: Yebo / Hatshi",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {
        'step': 'drilling_status_updates_opt_in3',
        'user': user.to_dict()
    })

    return {
        'step': 'drilling_status_updates_opt_in3',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_select_pump_option3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')

    if prompt.strip() not in pump_installation_options3:
        send("Inketho engavumelekile. Sicela ukhethe inketho yokufakwa kwepompo engu-1 kuze kube ngu-6.", user_data['sender'], phone_id)
        return {'step': 'select_pump_option3', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['pump_option'] = prompt.strip()
    pricing_message = get_pricing_for_location_quotes(location, "Pump Installation", prompt.strip())

    update_user_state(user_data['sender'], {
        'step': 'quote_followup3',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'quote_followup3',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_quote_followup3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt.strip() == "1":
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote3',
            'user': user.to_dict()
        })
        send(
            "Khetha olunye usizo:\n"
            "1. Ucwaningo lwamanzi\n"
            "2. Ukugawula ibhodi\n"
            "3. Ukufakwa kwepompo\n"
            "4. Ukugawula iCommercial hole\n"
            "5. Ukunwetshelwa kwebhodi",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "2":
        update_user_state(user_data['sender'], {
            'step': 'main_menu3',
            'user': user.to_dict()
        })
        send(
            "Singakusiza njani lamuhla?\n\n"
            "1. Cela isiphakamiso\n"
            "2. Phanda Intengo Ngokusebenzisa Indawo\n"
            "3. Bheka Isimo Sephrojekthi\n"
            "4. Imibuzo Evame Ukubuzwa noma Funda Ngokuqhuba Ibhorehole\n"
            "5. Eminye Imisebenzi\n"
            "6. Khuluma Nomuntu\n\n"
            "Sicela uphendule ngenombolo (isibonelo: 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details3',
            'user': user.to_dict()
        })
        send("Kulungile! Ungabelana ngenani ofuna ukulikhokha ngezansi.\n\n", user_data['sender'], phone_id)
        return {'step': 'collect_offer_details3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Inketho engavumelekile. Phendula ngo-1 ukuze ubuze ngenye insiza, ngo-2 ukuze ubuyele kumenu enkulu, noma ngo-3 ukuze unikeze inani lakho.", user_data['sender'], phone_id)
        return {'step': 'quote_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}


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
        "main_menu2": handle_main_menu2,
    "enter_location_for_quote2": handle_enter_location_for_quote2,
    "select_service_quote2": handle_select_service_quote2,
    "select_service2": handle_select_service2,
    "select_pump_option2": handle_select_pump_option2,
    "quote_followup2": handle_quote_followup2,   
    "collect_quote_details2": handle_collect_quote_details2,
    "quote_response2": handle_quote_response2,
    "collect_offer_details2": handle_collect_offer_details2,
    "quote_followup2": handle_quote_followup2,
    "offer_response2": handle_offer_response2,
    "booking_details2": handle_booking_details2,
    "collect_booking_info2": handle_collect_booking_info2,
    "booking_confirmation2": handle_booking_confirmation2,
    "faq_menu2": faq_menu2,
    "faq_borehole2": faq_borehole2,
    "faq_pump2": faq_pump2,
    "faq_borehole_followup2": faq_borehole_followup2,
    "faq_pump_followup2": faq_pump_followup2,
    "check_project_status_menu2": handle_check_project_status_menu2,
    "drilling_status_info_request2": handle_drilling_status_info_request2,
    "pump_status_info_request2": handle_pump_status_info_request2,
    "pump_status_updates_opt_in2": handle_pump_status_updates_opt_in2,
    "drilling_status_updates_opt_in2": handle_drilling_status_updates_opt_in2,
    "custom_question2": custom_question2,
    "custom_question_followup2": custom_question_followup2,
    "human_agent2": human_agent2,
    "waiting_for_human_agent_response2": handle_user_message2,
    "human_agent_followup2": handle_user_message2,   
    "other_services_menu2": handle_other_services_menu2,
    "borehole_deepening_casing2": handle_borehole_deepening_casing2,
    "borehole_flushing_problem2": handle_borehole_flushing_problem2,
    "pvc_casing_selection2": handle_pvc_casing_selection2,
    "deepening_location2": handle_deepening_location2,
    "human_agent2": lambda prompt, user_data, phone_id: (
        send("Maneja anoona nezvevatengi achakufonera munguva pfupi.", user_data['sender'], phone_id)
        or {'step': 'main_menu2', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
    ),
        "main_menu3": handle_main_menu3,
    "enter_location_for_quote3": handle_enter_location_for_quote3,
    "select_service_quote3": handle_select_service_quote3,
    "select_service3": handle_select_service3,
    "select_pump_option3": handle_select_pump_option3,
    "quote_followup3": handle_quote_followup3,   
    "collect_quote_details3": handle_collect_quote_details3,
    "quote_response3": handle_quote_response3,
    "collect_offer_details3": handle_collect_offer_details3,
    "quote_followup3": handle_quote_followup3,
    "offer_response3": handle_offer_response3,
    "booking_details3": handle_booking_details3,
    "collect_booking_info3": handle_collect_booking_info3,
    "booking_confirmation3": handle_booking_confirmation3,
    "faq_menu3": faq_menu3,
    "faq_borehole3": faq_borehole3,
    "faq_pump3": faq_pump3,
    "faq_borehole_followup3": faq_borehole_followup3,
    "faq_pump_followup3": faq_pump_followup3,
    "check_project_status_menu3": handle_check_project_status_menu3,
    "drilling_status_info_request3": handle_drilling_status_info_request3,
    "pump_status_info_request3": handle_pump_status_info_request3,
    "pump_status_updates_opt_in3": handle_pump_status_updates_opt_in3,
    "drilling_status_updates_opt_in3": handle_drilling_status_updates_opt_in3,
    "custom_question3": custom_question3,
    "custom_question_followup3": custom_question_followup3,
    "human_agent3": human_agent3,
    "waiting_for_human_agent_response3": handle_user_message3,
    "human_agent_followup3": handle_user_message3,   
    "other_services_menu3": handle_other_services_menu3,
    "borehole_deepening_casing3": handle_borehole_deepening_casing3,
    "borehole_flushing_problem3": handle_borehole_flushing_problem3,
    "pvc_casing_selection3": handle_pvc_casing_selection3,
    "deepening_location3": handle_deepening_location3,
    "human_agent3": lambda prompt, user_data, phone_id: (
        send("Umsebenzi wabantu uzakuxhumana lawe ngokushesha", user_data['sender'], phone_id)
        or {'step': 'main_menu3', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
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

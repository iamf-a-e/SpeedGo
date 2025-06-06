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

# Language dictionaries
LANGUAGES = {
    "English": {
        "welcome": "Hi there! Welcome to SpeedGo Services for borehole drilling in Zimbabwe. We provide reliable borehole drilling and water solutions across Zimbabwe.\n\nChoose your preferred language:\n1. English\n2. Shona\n3. Ndebele",
        "main_menu": "How can we help you today?\n\n1. Request a quote\n2. Search Price Using Location\n3. Check Project Status\n4. FAQs or Learn About Borehole Drilling\n5. Other services\n6. Talk to a Human Agent\n\nPlease reply with a number (e.g., 1)",
        "enter_location": "Please enter your location (City/Town or GPS coordinates) to get started.",
        "location_detected": "Location detected: {}\n\nNow select the service:\n1. Water survey\n2. Borehole drilling\n3. Pump installation\n4. Commercial hole drilling\n5. Borehole Deepening",
        "location_not_found": "We couldn't identify your location. Please type your city/town name manually.",
        "agent_connect": "Thank you. Please hold while I connect you to a SpeedGo representative...",
        "agent_notification": "👋 A customer would like to talk to you on WhatsApp.\n\n📱 Customer Number: {customer_number}\n🙋 Name: {customer_name}\n📩 Last Message: \"{prompt}\"",
        "new_request": "👋 New customer request on WhatsApp\n\n📱 Number: {customer_number}\n📩 Message: \"{prompt}\"",
        "fallback_option": "Alternatively, you can contact us directly at {agent_number}",
        "followup_question": "Would you like to:\n1. Return to main menu\n2. End conversation",
        "return_menu": "Returning you to the main menu...",
        "goodbye": "Thank you! Have a good day.",
        "invalid_option": "Please reply with 1 for Yes or 2 for No.",
        "still_waiting": "Please hold, we're still connecting you...",
        "human_agent_followup": {
            "invalid_option": "Please reply with 1 for Main Menu or 2 to stay here.",
            "stay_here": "Okay. Feel free to ask if you need anything else.",
        },
        "faq_menu": {
            "invalid_option": "Please select a valid option (1–5).",
            "borehole_faqs": (
                "Here are the most common questions about borehole drilling:\n\n",
                "1. How much does borehole drilling cost?\n",
                "2. How long does it take to drill a borehole?\n",
                "3. How deep will my borehole be?\n",
                "4. Do I need permission to drill a borehole?\n",
                "5. Do you do a water survey and drilling at the same time?\n",
                "6. What if you do a water survey and find no water?\n",
                "7. What equipment do you use?\n",
                "8. Back to FAQ Menu",
            )


    },
    
    "Shona": {
        "welcome": "Mhoro! Tigamuchire kuSpeedGo Services yekuchera maburi emvura muZimbabwe. Tinopa maburi emvura anovimbika nemhinduro dzemvura muZimbabwe yose.\n\nSarudza mutauro waunofarira:\n1. Chirungu\n2. Shona\n3. Ndebele",
        "main_menu": "Tinokubatsirai sei nhasi?\n\n1. Kukumbira quotation\n2. Tsvaga Mutengo Uchishandisa Nzvimbo\n3. Tarisa Mamiriro ePurojekiti\n4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Kuborehole\n5. Zvimwe Zvatinoita\n6. Taura neMunhu\n\nPindura nenhamba (semuenzaniso, 1)",
        "enter_location": "Ndapota nyora nzvimbo yako (Guta/Kanzuru kana GPS coordinates) kuti titange.",
        "location_detected": "Nzvimbo yawanikwa: {}\n\nZvino sarudza sevhisi yaunoda:\n1. Water survey\n2. Kuchera borehole\n3. Kuiswa kwepombi\n4. Kuchera bhora rezvekutengeserana\n5. Kuchinjwa/kudzika zvakare kwe borehole",
        "location_not_found": "Hatina kukwanisa kuona nzvimbo yenyu. Ndapota nyora zita reguta/kanzvimbo nemaoko."
    },
    
    "Ndebele": {
        "welcome": "Sawubona! Wamukelekile kwiSpeedGo Services yokumba amaBorehole eZimbabwe. Sinikeza ukumba kwamaBorehole okuthembekile kanye nezixazululo zamanzi kulo lonke iZimbabwe.\n\nKhetha ulimi oluthandayo:\n1. IsiNgisi\n2. IsiNdebele\n3. IsiShona",
        "main_menu": "Singakusiza njani lamuhla?\n\n1. Cela isiphakamiso\n2. Phanda Intengo Ngokusebenzisa Indawo\n3. Bheka Isimo Sephrojekthi\n4. Imibuzo Evame Ukubuzwa noma Funda Ngokuqhuba Ibhorehole\n5. Eminye Imisebenzi\n6. Khuluma Nomuntu\n\nPhendula ngenombolo (umzekeliso: 1)",
        "enter_location": "Sicela ufake indawo yakho (Idolobha/Idolobhana noma i-GPS) ukuze siqale.",
        "location_detected": "Indawo etholakele: {}\n\nSicela ukhethe inkonzo ofunayo:\n1. Ukuhlolwa kwamanzi\n2. Ukumba iBorehole\n3. Ukufakwa kwepampu\n4. Ukumba umgodi wezentengiselwano\n5. Ukwelula iBorehole (Deepening)",
        "location_not_found": "Asikwazanga ukuhlonza indawo yakho. Sicela bhala igama ledolobho/lindawo yakho ngesandla."
    }
}


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
        return "Beitbridge"
    elif -20.06 < lat < -19.95 and 31.54 < lng < 31.65:
        return "Nyika"
    elif -17.36 < lat < -17.25 and 31.28 < lng < 31.39:
        return "Bindura"
    elif -17.68 < lat < -17.57 and 27.29 < lng < 27.40:
        return "Binga"
    elif -19.58 < lat < -19.47 and 28.62 < lng < 28.73:
        return "Bubi"
    elif -19.33 < lat < -19.22 and 31.59 < lng < 31.70:
        return "Murambinda"
    elif -19.39 < lat < -19.28 and 31.38 < lng < 31.49:
        return "Buhera"
    elif -20.20 < lat < -20.09 and 28.51 < lng < 28.62:
        return "Bulawayo"
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
    service_key = service_type.strip().title()

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

    loc_data = location_pricing.get(location_key)
    if not loc_data:
        return "Sorry, pricing not available for this location."

    price = loc_data.get(service_key)
    if not price:
        return f"Sorry, pricing for {service_key} not found in {location.title()}."

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

    unit = "per meter" if service_key in ["Commercial Hole Drilling", "Borehole Deepening"] else "flat rate"
    return (f"{service_key} in {location.title()}: ${price} {unit}\n\n"
            "Would you like to:\n1. Ask pricing for another service\n2. Return to Main Menu\n3. Offer Price")

# State handlers
def handle_welcome(prompt, user_data, phone_id):
    send(LANGUAGES["English"]["welcome"], user_data['sender'], phone_id)
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
        send(LANGUAGES["English"]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "2":
        user.language = "Shona"
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES["Shona"]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":
        user.language = "Ndebele"
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES["Ndebele"]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        send("Please select a valid language option (1 for English, 2 for Shona, 3 for Ndebele).", user_data['sender'], phone_id)
        return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_main_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    if prompt == "1":  # Request a quote
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["enter_location"], user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Search Price Using Location
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["enter_location"], user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}
    
   
def human_agent_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt == "1":
        return handle_select_language("1", user_data, phone_id)
    elif prompt == "2":
        send(get_message(lang, "human_agent.exit_message"), user_data['sender'], phone_id)
        return {'step': 'human_agent_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(get_message(lang, "human_agent.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'human_agent_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole',
            'user': user.to_dict()
        })
        send(get_message(lang, "faq.borehole.menu"), user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":  # Pump Installation FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_pump',
            'user': user.to_dict()
        })
        send(get_message(lang, "faq.pump.menu"), user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Ask a different question
        update_user_state(user_data['sender'], {
            'step': 'custom_question',
            'user': user.to_dict()
        })
        send(get_message(lang, "faq.custom_question"), user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent',
            'user': user.to_dict(),
            'sender': user_data['sender']
        })
        send(get_message(lang, "human_agent_connect"), user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "5":  # Back to Main Menu
        return handle_select_language("1", user_data, phone_id)
    else:
        send(get_message(lang, "faq.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

def custom_question(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if not prompt.strip():
        send(get_message(lang, "custom_question.empty_prompt"), user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}

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
    send(get_message(lang, "custom_question.response_followup"), user_data['sender'], phone_id)
    return {'step': 'custom_question_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def custom_question_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt == "1":
        send(get_message(lang, "custom_question.next_question"), user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)
    else:
        send(get_message(lang, "custom_question.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'custom_question_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt in get_message(lang, "faq.borehole.responses"):
        send(get_message(lang, f"faq.borehole.responses.{prompt}"), user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
        
        send(get_message(lang, "faq.borehole.followup"), user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(get_message(lang, "faq.borehole.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt == "1":
        send(get_message(lang, "faq.borehole.menu"), user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)
    else:
        send(get_message(lang, "custom_question.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_pump(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt in get_message(lang, "faq.pump.responses"):
        send(get_message(lang, f"faq.pump.responses.{prompt}"), user_data['sender'], phone_id)
        if prompt == "6":
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
        
        send(get_message(lang, "faq.pump.followup"), user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(get_message(lang, "faq.pump.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_pump_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt == "1":
        send(get_message(lang, "faq.pump.menu"), user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)
    else:
        send(get_message(lang, "custom_question.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_enter_location_for_quote(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
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
                'step': 'select_service_quote',
                'user': user.to_dict()
            })
            send(LANGUAGES[lang]["location_detected"].format(location_name.title()), 
                 user_data['sender'], phone_id)
            return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}
        else:
            send(LANGUAGES[lang]["location_not_found"], user_data['sender'], phone_id)
            return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        # This is a text message with location name
        location_name = prompt.strip()
        user.quote_data['location'] = location_name.lower()
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["location_detected"].format(location_name.title()), 
             user_data['sender'], phone_id)
        return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

def human_agent(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    customer_number = user_data['sender']
    customer_name = user.name if hasattr(user, "name") and user.name else "Unknown"
    agent_number = "+263719835124"
    lang = get_user_language(user_data)

    # Notify the customer immediately
    send(LANGUAGES[lang]['agent_connect'], customer_number, phone_id)

    # Notify the agent immediately
    agent_message = LANGUAGES[lang]['agent_notification'].format(
        customer_number=customer_number,
        customer_name=customer_name,
        prompt=prompt
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

def notify_agent(customer_number, prompt, agent_number, phone_id, lang='en'):
    agent_message = LANGUAGES[lang]['new_request'].format(
        customer_number=customer_number,
        prompt=prompt
    )
    send(agent_message, agent_number, phone_id)

def send_fallback_option(customer_number, phone_id, user_data):
    # Check if still waiting
    user_data = get_user_state(customer_number)
    if user_data and user_data.get('step') == 'waiting_for_human_agent_response':
        lang = get_user_language(user_data)
        send(LANGUAGES[lang]['fallback_option'].format(agent_number="+263719835124"), 
             customer_number, phone_id)
        send(LANGUAGES[lang]['followup_question'], customer_number, phone_id)
        update_user_state(customer_number, {
            'step': 'human_agent_followup',
            'user': user_data.get('user', {}),
            'sender': customer_number
        })

def handle_user_message(message, user_data, phone_id):
    state = user_data.get('step')
    customer_number = user_data['sender']
    lang = get_user_language(user_data)

    if state == 'waiting_for_human_agent_response':
        prompt_time = user_data.get('agent_prompt_time', 0)
        elapsed = time.time() - prompt_time

        if elapsed >= 10:
            # Send fallback prompt
            send(LANGUAGES[lang]['fallback_option'].format(agent_number="+263719835124"), 
                 customer_number, phone_id)
            send(LANGUAGES[lang]['followup_question'], customer_number, phone_id)

            # Update state to wait for user's Yes/No reply
            update_user_state(customer_number, {
                'step': 'human_agent_followup',
                'user': user_data['user'],
                'sender': customer_number
            })

            return {'step': 'human_agent_followup', 'user': user_data['user'], 'sender': customer_number}
        else:
            # Still waiting, remind user to hold on
            send(LANGUAGES[lang]['still_waiting'], customer_number, phone_id)
            return user_data

    elif state == 'human_agent_followup':
        # Handle user's Yes/No answer here
        if message.strip() == '1':  # User wants main menu
            send(LANGUAGES[lang]['return_menu'], customer_number, phone_id)
            # Reset state to main menu step
            update_user_state(customer_number, {
                'step': 'main_menu',
                'user': user_data['user'],
                'sender': customer_number
            })
            # Show main menu (assuming send_main_menu also supports languages)
            send_main_menu(customer_number, phone_id, lang)
            return {'step': 'main_menu', 'user': user_data['user'], 'sender': customer_number}

        elif message.strip() == '2':  # User says No
            send(LANGUAGES[lang]['goodbye'], customer_number, phone_id)
            # Optionally clear or end session
            update_user_state(customer_number, {
                'step': 'end',
                'user': user_data['user'],
                'sender': customer_number
            })
            return {'step': 'end', 'user': user_data['user'], 'sender': customer_number}
        else:
            send(LANGUAGES[lang]['invalid_option'], customer_number, phone_id)
            return user_data

def human_agent_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'

    if prompt == "1":
        return handle_select_language("1", user_data, phone_id)
    elif prompt == "2":
        send(get_message(lang, 'human_agent_followup', 'stay_here'), user_data['sender'], phone_id)
        return {'step': 'human_agent_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(get_message(lang, 'human_agent_followup', 'invalid_option'), user_data['sender'], phone_id)
        return {'step': 'human_agent_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'

    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole',
            'user': user.to_dict()
        })
        send(get_message(lang, 'faq_menu', 'borehole_faqs'), user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Pump Installation FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_pump',
            'user': user.to_dict()
        })
        send(get_message(lang, 'faq_menu', 'pump_faqs'), user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Ask a different question
        update_user_state(user_data['sender'], {
            'step': 'custom_question',
            'user': user.to_dict()
        })
        send(get_message(lang, 'faq_menu', 'custom_question'), user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent',
            'user': user.to_dict(),
            'sender': user_data['sender']
        })
        send(get_message(lang, 'faq_menu', 'connecting_agent'), user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Back to Main Menu
        return handle_select_language("1", user_data, phone_id)

    else:
        send(get_message(lang, 'faq_menu', 'invalid_option'), user_data['sender'], phone_id)
        return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

def custom_question(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'

    if not prompt.strip():
        send(get_message(lang, 'custom_question', 'empty_prompt'), user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}

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
    send(get_message(lang, 'custom_question', 'follow_up'), user_data['sender'], phone_id)
    return {'step': 'custom_question_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def custom_question_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'

    if prompt == "1":
        send(get_message(lang, 'custom_question', 'next_question'), user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)
    else:
        send("Please reply 1 to ask another question or 2 to return to the main menu.", user_data['sender'], phone_id)
        return {'step': 'custom_question_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'
    responses = get_message(lang, 'faq_borehole', 'responses')

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(get_message(lang, 'faq_borehole', 'follow_up'), user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(get_message(lang, 'faq_borehole', 'invalid_option'), user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'

    if prompt == "1":
        send(get_message(lang, 'faq_menu', 'borehole_faqs'), user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)
    else:
        send(get_message(lang, 'faq_borehole_followup', 'invalid_option'), user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_pump(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'
    responses = get_message(lang, 'faq_pump', 'responses')

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "6":
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(get_message(lang, 'faq_pump', 'follow_up'), user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(get_message(lang, 'faq_pump', 'invalid_option'), user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_pump_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'

    if prompt == "1":
        send(get_message(lang, 'faq_menu', 'pump_faqs'), user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)
    else:
        send(get_message(lang, 'faq_pump_followup', 'invalid_option'), user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_select_service_quote(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
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

    user.quote_data['service'] = selected_service

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

    pricing_message = get_pricing_for_location_quotes(location, selected_service)
    
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

# Flask app setup
app = Flask(__name__)

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        
        if mode and token:
            if mode == 'subscribe' and token == os.environ.get("VERIFY_TOKEN"):
                return challenge, 200
        return 'Verification failed', 403

    if request.method == 'POST':
        data = request.get_json()
        
        if data.get('object') == 'whatsapp_business_account':
            entries = data.get('entry', [])
            for entry in entries:
                changes = entry.get('changes', [])
                for change in changes:
                    value = change.get('value', {})
                    messages = value.get('messages', [])
                    for message in messages:
                        phone_number = message.get('from')
                        user_data = get_user_state(phone_number)
                        current_step = user_data.get('step', 'welcome')
                        
                        # Handle location messages
                        if message.get('type') == 'location':
                            user_data['location'] = message['location']
                            handler = globals().get(f'handle_{current_step}')
                            if handler:
                                handler("", user_data, phone_id)
                            continue
                            
                        # Handle text messages
                        if message.get('type') == 'text':
                            text = message['text'].get('body', '').strip()
                            handler = globals().get(f'handle_{current_step}')
                            if handler:
                                handler(text, user_data, phone_id)
        return 'OK', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

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
        "location_not_found": "We couldn't identify your location. Please type your city/town name manually."
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

# Pricing dictionaries (same as before)
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
    # ... (rest of pricing dictionaries remain the same)
}

pump_installation_options = {
    "1": {
        "description": "D.C solar (direct solar NO inverter) - I have tank and tank stand",
        "price": 1640
    },
    # ... (rest of pump options remain the same)
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
    
    # ... (rest of main menu handling remains similar but with language support)

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

# ... (rest of the handlers remain similar but with language support)

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



def handle_select_pump_option(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    location = user.quote_data.get('location')
    
    if not location:
        send("Please provide your location first before selecting a service.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

    if prompt not in pump_installation_options:
        message_lines = ["Invalid option. Please select a valid pump installation option:"]
        for key, option in pump_installation_options.items():
            desc = option.get('description', 'No description')
            message_lines.append(f"{key}. {desc}")
        send("\n".join(message_lines), user_data['sender'], phone_id)
        return {'step': 'select_pump_option', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['pump_option'] = prompt
    pricing_message = get_pricing_for_location_quotes(location, "Pump Installation", prompt)
    
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
    lang = user.language
    
    if prompt == "1":  # Ask pricing for another service
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["location_detected"].format(user.quote_data['location'].title()), 
             user_data['sender'], phone_id)
        return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "2":  # Return to Main Menu
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "3":  # Offer Price
        # Save the offer data
        user.offer_data = {
            'location': user.quote_data.get('location'),
            'service': user.quote_data.get('service'),
            'pump_option': user.quote_data.get('pump_option'),
            'timestamp': datetime.now().isoformat()
        }
        
        update_user_state(user_data['sender'], {
            'step': 'confirm_offer',
            'user': user.to_dict()
        })
        
        # Format the offer message
        service = user.quote_data.get('service')
        location = user.quote_data.get('location', '').title()
        message = f"📌 Offer Summary ({location}):\n"
        message += f"Service: {service}\n"
        
        if service == "Pump Installation":
            option = pump_installation_options.get(user.quote_data.get('pump_option', ''))
            if option:
                message += f"Option: {option.get('description')}\n"
                message += f"Price: ${option.get('price')}\n"
        else:
            pricing = get_pricing_for_location_quotes(location.lower(), service)
            message += f"Pricing: {pricing.split('\n')[0]}\n"
        
        message += "\nWould you like to:\n1. Confirm this offer\n2. Modify request\n3. Cancel"
        
        send(message, user_data['sender'], phone_id)
        return {'step': 'confirm_offer', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        send("Invalid option. Please reply with 1, 2 or 3.", user_data['sender'], phone_id)
        return {'step': 'quote_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_confirm_offer(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    if prompt == "1":  # Confirm offer
        # Save the booking
        booking_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        user.booking_data = {
            'booking_id': booking_id,
            'status': 'pending',
            'details': user.offer_data,
            'timestamp': datetime.now().isoformat()
        }
        
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        
        # Send confirmation to user
        confirmation_msg = (f"✅ Booking Confirmed!\n"
                          f"Reference: {booking_id}\n"
                          f"Location: {user.offer_data.get('location', '').title()}\n"
                          f"Service: {user.offer_data.get('service')}\n\n"
                          f"An agent will contact you shortly.")
        send(confirmation_msg, user_data['sender'], phone_id)
        
        # Send notification to owner
        owner_msg = (f"📢 New Booking!\n"
                    f"From: {user_data['sender']}\n"
                    f"Ref: {booking_id}\n"
                    f"Location: {user.offer_data.get('location', '').title()}\n"
                    f"Service: {user.offer_data.get('service')}")
        send(owner_msg, owner_phone, phone_id)
        
        send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "2":  # Modify request
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["enter_location"], user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "3":  # Cancel
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send("Offer cancelled. Let us know if you need anything else.", user_data['sender'], phone_id)
        send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        send("Invalid option. Please reply with 1, 2 or 3.", user_data['sender'], phone_id)
        return {'step': 'confirm_offer', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_check_project_status(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    if not user.booking_data:
        send("You don't have any active bookings. Would you like to request a new quote?", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    status_msg = (f"📋 Booking Status\n"
                 f"Reference: {user.booking_data.get('booking_id')}\n"
                 f"Status: {user.booking_data.get('status', 'pending').title()}\n"
                 f"Location: {user.booking_data.get('details', {}).get('location', '').title()}\n"
                 f"Service: {user.booking_data.get('details', {}).get('service')}\n\n"
                 f"Last updated: {datetime.fromisoformat(user.booking_data.get('timestamp')).strftime('%Y-%m-%d %H:%M')}")
    
    send(status_msg, user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {
        'step': 'main_menu',
        'user': user.to_dict()
    })
    send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
    return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_faqs(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    faqs = {
        "English": [
            "1. How long does borehole drilling take?",
            "2. What's the average depth for a borehole?",
            "3. Do I need a water survey first?",
            "4. What maintenance is required?",
            "5. Return to Main Menu"
        ],
        "Shona": [
            "1. Zvinotora nguva yakareba sei kuchera borehole?",
            "2. Ndeapi marefu avhareji eborehole?",
            "3. Ndinoda kuongororwa kwemvura kutanga here?",
            "4. Ndezvei zvinodiwa kugadzirisa?",
            "5. Dzokera kuMain Menu"
        ],
        "Ndebele": [
            "1. Kuthathela isikhathi esingakanani ukubha i-borehole?",
            "2. Ujule ophakathi nendawo lwe-borehole?",
            "3. Ngidinga ukuhlolwa kwamanzi kuqala?",
            "4. Yiziphi izinto ezidingekayo zokugcina?",
            "5. Buyela ku-Main Menu"
        ]
    }
    
    update_user_state(user_data['sender'], {
        'step': 'handle_faq_selection',
        'user': user.to_dict()
    })
    
    send("\n".join(faqs[lang]), user_data['sender'], phone_id)
    return {'step': 'handle_faq_selection', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_faq_selection(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    faq_answers = {
        "English": {
            "1": "Borehole drilling typically takes 1-3 days depending on depth and ground conditions.",
            "2": "Average depth is 40-60 meters, but varies by location and water table.",
            "3": "Yes, a water survey helps determine the best location and depth for drilling.",
            "4": "Regular pump maintenance and occasional water quality testing are recommended."
        },
        "Shona": {
            "1": "Kuchera borehole kunowanzo torera mazuva 1-3 zvichienderana nekudzika uye mamiriro epasi.",
            "2": "Avhareji yekudzika ndeye 40-60 metres, asi inosiyana nenzvimbo uye tafura yemvura.",
            "3": "Hongu, kuongororwa kwemvura kunobatsira kuona nzvimbo yakanaka uye kudzika kwekuchera.",
            "4": "Kugadzirisa pombi nguva dzose uye kuyedza kunowanzoitwa kwemhando yemvura zvinokurudzirwa."
        },
        "Ndebele": {
            "1": "Ukubha i-borehole kuthatha usuku 1-3 kuya ngejule kanye nezimo zomhlabathi.",
            "2": "Ujule ophakathi nendawo ngu-40-60 metres, kodwa uyahluka ngendawo netafula yamanzi.",
            "3": "Yebo, ukuhlolwa kwamanzi kusiza ukunquma indawo enhle nejule lokubha.",
            "4": "Ukugcinwa kwepump njalo kanye nokuhlolwa kwekhwalithi yamanzi kuyanconywa."
        }
    }
    
    if prompt == "5":
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    answer = faq_answers[lang].get(prompt)
    if answer:
        send(answer, user_data['sender'], phone_id)
        # Return to FAQs menu
        return handle_faqs("", user_data, phone_id)
    else:
        send("Invalid option. Please select a valid FAQ number.", user_data['sender'], phone_id)
        return {'step': 'handle_faq_selection', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_talk_to_agent(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    # Notify owner
    owner_msg = (f"👋 Agent Request\n"
                f"From: {user_data['sender']}\n"
                f"Language: {lang}\n"
                f"Current step: {user_data.get('step')}")
    send(owner_msg, owner_phone, phone_id)
    
    # Confirm to user
    confirmation_msg = {
        "English": "An agent will contact you shortly. Is there anything else we can help with?",
        "Shona": "Mumiririri achakubata munguva pfupi. Pane chimwe chatingakubatsire nacho here?",
        "Ndebele": "Ummeleli uzokuthinta kunge kungenzeka. Kukhona enye into esingakusiza ngayo?"
    }
    
    update_user_state(user_data['sender'], {
        'step': 'main_menu',
        'user': user.to_dict()
    })
    send(confirmation_msg[lang], user_data['sender'], phone_id)
    send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
    return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

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

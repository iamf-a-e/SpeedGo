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
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

# Upstash Redis setup
redis = Redis(
    url=os.environ["UPSTASH_REDIS_REST_URL"],
    token=os.environ["UPSTASH_REDIS_REST_TOKEN"]
)

# Enhanced Language dictionaries
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
        "invalid_option": "Please select a valid option.",
        "still_waiting": "Please hold, we're still connecting you...",
        "services": {
            "1": "Water survey",
            "2": "Borehole drilling",
            "3": "Pump installation",
            "4": "Commercial hole drilling",
            "5": "Borehole Deepening"
        },
        "faq": {
            "menu": "Here are the most common questions:\n\n1. Borehole Drilling FAQs\n2. Pump Installation FAQs\n3. Ask a different question\n4. Human agent\n5. Back to Main Menu",
            "borehole": {
                "menu": "Here are the most common questions about borehole drilling:\n\n1. How much does borehole drilling cost?\n2. How long does it take to drill a borehole?\n3. How deep will my borehole be?\n4. Do I need permission to drill a borehole?\n5. Do you do a water survey and drilling at the same time?\n6. What if you do a water survey and find no water?\n7. What equipment do you use?\n8. Back to FAQ Menu",
                "responses": {
                    "1": "The cost depends on your location, depth, and soil conditions. Please send us your location and site access details for a personalized quote.",
                    "2": "Typically 4-6 hours or up to several days, depending on site conditions, rock type, and accessibility.",
                    "3": "Depth varies by area. The standard depth is around 40 meters, but boreholes can range from 40 to 150 meters depending on the underground water table.",
                    "4": "In some areas, a water permit may be required. We can assist you with the application if necessary.",
                    "5": "Yes, we offer both as a combined package or separately, depending on your preference.",
                    "6": "If the client wishes to drill at a second point, we offer a discount.\n\nNote: Survey machines detect underground water-bearing fractures or convergence points of underground streams. However, they do not measure the volume or flow rate of water. Therefore, borehole drilling carries no 100% guarantee of hitting water, as the fractures could be dry, moist, or wet.",
                    "7": "We use professional-grade rotary and percussion drilling rigs, GPS tools, and geological survey equipment.",
                    "8": "Returning to FAQ Menu..."
                },
                "followup": "Would you like to:\n1. Ask another question from Borehole Drilling FAQs\n2. Return to Main Menu"
            },
            "pump": {
                "menu": "Here are common questions about pump installation:\n\n1. What's the difference between solar and electric pumps?\n2. Can you install if I already have materials?\n3. How long does pump installation take?\n4. What pump size do I need?\n5. Do you supply tanks and tank stands?\n6. Back to FAQ Menu",
                "responses": {
                    "1": "Solar pumps use energy from solar panels and are ideal for off-grid or remote areas. Electric pumps rely on the power grid and are typically more affordable upfront but depend on electricity availability.",
                    "2": "Yes! We offer labor-only packages if you already have the necessary materials.",
                    "3": "Installation usually takes one day, provided materials are ready and site access is clear.",
                    "4": "Pump size depends on your water needs and borehole depth. We can assess your site and recommend the best option.",
                    "5": "Yes, we supply complete packages including water tanks, tank stands, and all necessary plumbing fittings.",
                    "6": "Returning to FAQ Menu..."
                },
                "followup": "Would you like to:\n1. Ask another question from Pump Installation FAQs\n2. Return to Main Menu"
            },
            "custom_question": "Please type your question below, and we'll do our best to assist you.",
            "human_agent_connect": "Please hold while I connect you to a representative..."
        },
        "quote": {
            "intro": "Please tell us the location where you want the service.",
            "thank_you": "Thank you! We have received your request.\n\n{0}\n\nWhat would you like to do next?\n1. Offer your own price\n2. Book site survey\n3. Book drilling\n4. Talk to an agent",
            "select_another_service": "Select another service:\n1. Water survey\n2. Borehole drilling\n3. Pump installation\n4. Commercial hole drilling\n5. Borehole Deepening",
            "invalid_option": "Invalid option. Reply 1 to ask about another service or 2 to return to the main menu or 3 if you want to make a price offer."
        },
        "booking": {
            "confirmed": "Great! Your borehole drilling appointment is now booked.\n\nDate: {date}\nStart Time: 8:00 AM\nExpected Duration: 5 hrs\nTeam: 4-5 Technicians\n\nMake sure there is access to the site",
            "reschedule": "Please contact our support team to reschedule.",
            "confirmation": "Thank you {full_name}! Your booking is confirmed.\nBooking Reference: {reference}\nOur team will contact you soon.\nType 'menu' to return to the main menu."
        },
        "status": {
            "request": "To check your project status, please provide:\n- Full Name\n- Reference Number or Phone Number\n- Location (optional)",
            "retrieving": "Thank you. Please wait while we retrieve your project status...",
            "result": "Here is your project status:\n\nProject Name: {project_name}\nCurrent Stage: {stage}\nNext Step: {next_step}\nEstimated Completion: {completion_date}",
            "updates": "Would you like WhatsApp updates when your status changes?\n1. Yes\n2. No"
        }
    },
    "Shona": {
        "welcome": "Mhoro! Tigamuchire kuSpeedGo Services yekuchera maburi emvura muZimbabwe. Tinopa maburi emvura anovimbika nemhinduro dzemvura muZimbabwe yose.\n\nSarudza mutauro waunofarira:\n1. Chirungu\n2. Shona\n3. Ndebele",
        "main_menu": "Tinokubatsirai sei nhasi?\n\n1. Kukumbira quotation\n2. Tsvaga Mutengo Uchishandisa Nzvimbo\n3. Tarisa Mamiriro ePurojekiti\n4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Kuborehole\n5. Zvimwe Zvatinoita\n6. Taura neMunhu\n\nPindura nenhamba (semuenzaniso, 1)",
        # ... (other Shona translations)
    },
    "Ndebele": {
        "welcome": "Sawubona! Wamukelekile kwiSpeedGo Services yokumba amaBorehole eZimbabwe. Sinikeza ukumba kwamaBorehole okuthembekile kanye nezixazululo zamanzi kulo lonke iZimbabwe.\n\nKhetha ulimi oluthandayo:\n1. IsiNgisi\n2. IsiNdebele\n3. IsiShona",
        "main_menu": "Singakusiza njani lamuhla?\n\n1. Cela isiphakamiso\n2. Phanda Intengo Ngokusebenzisa Indawo\n3. Bheka Isimo Sephrojekthi\n4. Imibuzo Evame Ukubuzwa noma Funda Ngokuqhuba Ibhorehole\n5. Eminye Imisebenzi\n6. Khuluma Nomuntu\n\nPhendula ngenombolo (umzekeliso: 1)",
        # ... (other Ndebele translations)
    }
}

# User class with improved serialization
class User:
    def __init__(self, phone_number):
        self.phone_number = phone_number
        self.language = "English"
        self.quote_data = {}
        self.booking_data = {}
        self.offer_data = {}
        self.project_status_request = {}

    def to_dict(self):
        return {
            "phone_number": self.phone_number,
            "language": self.language,
            "quote_data": self.quote_data,
            "booking_data": self.booking_data,
            "offer_data": self.offer_data,
            "project_status_request": self.project_status_request
        }

    @classmethod
    def from_dict(cls, data):
        user = cls(data.get("phone_number", ""))
        user.language = data.get("language", "English")
        user.quote_data = data.get("quote_data", {})
        user.booking_data = data.get("booking_data", {})
        user.offer_data = data.get("offer_data", {})
        user.project_status_request = data.get("project_status_request", {})
        return user

# Helper functions
def get_user_state(phone_number):
    state = redis.get(phone_number)
    if not state:
        return {"step": "welcome", "sender": phone_number}
    return json.loads(state) if isinstance(state, str) else state

def update_user_state(phone_number, updates, ttl_seconds=3600):
    if not isinstance(updates, dict):
        updates = {}
    updates['phone_number'] = phone_number
    if 'sender' not in updates:
        updates['sender'] = phone_number
    redis.set(phone_number, json.dumps(updates), ex=ttl_seconds)

def send_message(text, recipient, phone_id):
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {
        'Authorization': f'Bearer {wa_token}',
        'Content-Type': 'application/json'
    }
    data = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": text}
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send message: {e}")
        return False

def get_message(language, category, key=None):
    lang_dict = LANGUAGES.get(language, LANGUAGES["English"])
    if not key:
        return lang_dict.get(category, "")
    parts = key.split('.')
    result = lang_dict
    for part in parts:
        result = result.get(part, {})
    return result if result else ""

def reverse_geocode_location(gps_coords):
    if not gps_coords or ',' not in gps_coords:
        return None

    try:
        lat_str, lng_str = gps_coords.strip().split(',')
        lat = float(lat_str.strip())
        lng = float(lng_str.strip())
    except ValueError:
        return None

    # Local mapping
    local_mapping = {
        (-22.27, -22.16, 29.94, 30.06): "Beitbridge",
        (-20.06, -19.95, 31.54, 31.65): "Nyika",
        (-17.36, -17.25, 31.28, 31.39): "Bindura",
        (-17.68, -17.57, 27.29, 27.40): "Binga",
        (-19.58, -19.47, 28.62, 28.73): "Bubi",
        (-19.33, -19.22, 31.59, 31.70): "Murambinda",
        (-19.39, -19.28, 31.38, 31.49): "Buhera",
        (-20.20, -20.09, 28.51, 28.62): "Bulawayo",
        (-19.691, -19.590, 31.103, 31.204): "Gutu",
        (-20.99, -20.88, 28.95, 29.06): "Gwanda",
        (-19.50, -19.39, 29.76, 29.87): "Gweru",
        (-17.88, -17.77, 31.00, 31.11): "Harare"
    }

    for (min_lat, max_lat, min_lng, max_lng), name in local_mapping.items():
        if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
            return name

    # Fallback to Google Maps API
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lng}&key={GOOGLE_MAPS_API_KEY}"
    try:
        response = requests.get(url)
        data = response.json()
        if data['status'] == 'OK':
            for result in data['results']:
                for component in result['address_components']:
                    if 'locality' in component['types'] or 'administrative_area_level_1' in component['types']:
                        return component['long_name']
            return data['results'][0]['formatted_address']
    except Exception as e:
        logging.error(f"Geocoding error: {e}")
    return None

# State handlers
def handle_welcome(prompt, user_data, phone_id):
    user = User.from_dict(user_data)
    send_message(LANGUAGES["English"]["welcome"], user.phone_number, phone_id)
    update_user_state(user.phone_number, {'step': 'select_language', 'user': user.to_dict()})
    return {'step': 'select_language', 'user': user.to_dict(), 'sender': user.phone_number}

def handle_select_language(prompt, user_data, phone_id):
    user = User.from_dict(user_data.get('user', {'phone_number': user_data['sender']}))
    
    lang_map = {"1": "English", "2": "Shona", "3": "Ndebele"}
    if prompt in lang_map:
        user.language = lang_map[prompt]
        update_user_state(user.phone_number, {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send_message(LANGUAGES[user.language]["main_menu"], user.phone_number, phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user.phone_number}
    
    send_message("Please select a valid language option (1 for English, 2 for Shona, 3 for Ndebele).", 
                user.phone_number, phone_id)
    return {'step': 'select_language', 'user': user.to_dict(), 'sender': user.phone_number}

def handle_main_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    menu_options = {
        "1": "enter_location_for_quote",
        "2": "enter_location_for_quote",  # Same as quote flow
        "3": "check_project_status_menu",
        "4": "faq_menu",
        "5": "other_services_menu",
        "6": "human_agent"
    }
    
    if prompt in menu_options:
        next_step = menu_options[prompt]
        update_user_state(user.phone_number, {
            'step': next_step,
            'user': user.to_dict()
        })
        
        if next_step == "enter_location_for_quote":
            send_message(LANGUAGES[lang]["enter_location"], user.phone_number, phone_id)
        elif next_step == "faq_menu":
            send_message(LANGUAGES[lang]["faq"]["menu"], user.phone_number, phone_id)
        elif next_step == "human_agent":
            send_message(LANGUAGES[lang]["agent_connect"], user.phone_number, phone_id)
            # Notify agent
            agent_message = LANGUAGES[lang]["new_request"].format(
                customer_number=user.phone_number,
                prompt="Requested human agent from main menu"
            )
            send_message(agent_message, owner_phone, phone_id)
            
        return {'step': next_step, 'user': user.to_dict(), 'sender': user.phone_number}
    
    send_message(LANGUAGES[lang]["invalid_option"], user.phone_number, phone_id)
    return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user.phone_number}

def handle_enter_location_for_quote(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    # Check for location attachment
    if 'location' in user_data and 'latitude' in user_data['location']:
        lat = user_data['location']['latitude']
        lng = user_data['location']['longitude']
        gps_coords = f"{lat},{lng}"
        location_name = reverse_geocode_location(gps_coords)
        
        if location_name:
            user.quote_data['location'] = location_name
            user.quote_data['gps_coords'] = gps_coords
            update_user_state(user.phone_number, {
                'step': 'select_service_quote',
                'user': user.to_dict()
            })
            send_message(LANGUAGES[lang]["location_detected"].format(location_name.title()), 
                       user.phone_number, phone_id)
            return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user.phone_number}
    
    # Handle text location input
    location_name = prompt.strip()
    if location_name:
        user.quote_data['location'] = location_name.lower()
        update_user_state(user.phone_number, {
            'step': 'select_service_quote',
            'user': user.to_dict()
        })
        send_message(LANGUAGES[lang]["location_detected"].format(location_name.title()), 
                   user.phone_number, phone_id)
        return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user.phone_number}
    
    send_message(LANGUAGES[lang]["location_not_found"], user.phone_number, phone_id)
    return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user.phone_number}

def handle_select_service_quote(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    service_map = {
        "1": "Water survey",
        "2": "Borehole drilling",
        "3": "Pump installation",
        "4": "Commercial hole drilling",
        "5": "Borehole Deepening"
    }
    
    if prompt in service_map:
        user.quote_data['service'] = service_map[prompt]
        location = user.quote_data.get('location', 'unknown location')
        
        if service_map[prompt] == "Pump installation":
            update_user_state(user.phone_number, {
                'step': 'select_pump_option',
                'user': user.to_dict()
            })
            # Show pump options
            pump_options = [
                "1. D.C solar (direct solar NO inverter) - I have tank and tank stand",
                "2. D.C solar (direct solar NO inverter) - I don't have anything",
                "3. D.C solar (direct solar NO inverter) - Labour only",
                "4. A.C electric (ZESA or solar inverter) - Fix and supply",
                "5. A.C electric (ZESA or solar inverter) - Labour only",
                "6. A.C electric (ZESA or solar inverter) - I have tank and tank stand"
            ]
            message = "💧 Pump Installation Options:\n" + "\n".join(pump_options)
            send_message(message, user.phone_number, phone_id)
            return {'step': 'select_pump_option', 'user': user.to_dict(), 'sender': user.phone_number}
        
        # For other services, show pricing
        pricing = get_pricing_for_service(location, service_map[prompt])
        message = f"💧 Pricing for {service_map[prompt]} in {location.title()}:\n{pricing}\n\n" + \
                 LANGUAGES[lang]["quote"]["thank_you"].format(f"Service: {service_map[prompt]}\nLocation: {location}")
        
        update_user_state(user.phone_number, {
            'step': 'quote_followup',
            'user': user.to_dict()
        })
        send_message(message, user.phone_number, phone_id)
        return {'step': 'quote_followup', 'user': user.to_dict(), 'sender': user.phone_number}
    
    send_message(LANGUAGES[lang]["invalid_option"], user.phone_number, phone_id)
    return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user.phone_number}

def handle_select_pump_option(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    pump_options = {
        "1": {"desc": "D.C solar (direct solar NO inverter) - I have tank and tank stand", "price": 1640},
        "2": {"desc": "D.C solar (direct solar NO inverter) - I don't have anything", "price": 2550},
        "3": {"desc": "D.C solar (direct solar NO inverter) - Labour only", "price": 200},
        "4": {"desc": "A.C electric (ZESA or solar inverter) - Fix and supply", "price": 1900},
        "5": {"desc": "A.C electric (ZESA or solar inverter) - Labour only", "price": 170},
        "6": {"desc": "A.C electric (ZESA or solar inverter) - I have tank and tank stand", "price": 950}
    }
    
    if prompt in pump_options:
        user.quote_data['pump_option'] = pump_options[prompt]
        location = user.quote_data.get('location', 'unknown location')
        message = f"💧 Pricing for pump installation in {location.title()}:\n" + \
                 f"{pump_options[prompt]['desc']}\nPrice: ${pump_options[prompt]['price']}\n\n" + \
                 LANGUAGES[lang]["quote"]["thank_you"].format(f"Pump Option: {pump_options[prompt]['desc']}\nLocation: {location}")
        
        update_user_state(user.phone_number, {
            'step': 'quote_followup',
            'user': user.to_dict()
        })
        send_message(message, user.phone_number, phone_id)
        return {'step': 'quote_followup', 'user': user.to_dict(), 'sender': user.phone_number}
    
    send_message(LANGUAGES[lang]["invalid_option"], user.phone_number, phone_id)
    return {'step': 'select_pump_option', 'user': user.to_dict(), 'sender': user.phone_number}

def handle_quote_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    if prompt == "1":  # Another service
        update_user_state(user.phone_number, {
            'step': 'select_service_quote',
            'user': user.to_dict()
        })
        send_message(LANGUAGES[lang]["quote"]["select_another_service"], user.phone_number, phone_id)
        return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user.phone_number}
    elif prompt == "2":  # Main menu
        update_user_state(user.phone_number, {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send_message(LANGUAGES[lang]["main_menu"], user.phone_number, phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user.phone_number}
    elif prompt == "3":  # Offer price
        update_user_state(user.phone_number, {
            'step': 'collect_offer_details',
            'user': user.to_dict()
        })
        send_message("Please enter your price offer:", user.phone_number, phone_id)
        return {'step': 'collect_offer_details', 'user': user.to_dict(), 'sender': user.phone_number}
    elif prompt == "4":  # Human agent
        send_message(LANGUAGES[lang]["agent_connect"], user.phone_number, phone_id)
        # Notify agent
        agent_message = LANGUAGES[lang]["new_request"].format(
            customer_number=user.phone_number,
            prompt="Requested human agent from quote followup"
        )
        send_message(agent_message, owner_phone, phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user.phone_number}
    
    send_message(LANGUAGES[lang]["quote"]["invalid_option"], user.phone_number, phone_id)
    return {'step': 'quote_followup', 'user': user.to_dict(), 'sender': user.phone_number}

def handle_collect_offer_details(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    try:
        offer = float(prompt.strip())
        user.offer_data['amount'] = offer
        user.offer_data['timestamp'] = datetime.now().isoformat()
        
        update_user_state(user.phone_number, {
            'step': 'offer_response',
            'user': user.to_dict()
        })
        
        send_message("Thank you for your offer! We'll review it and get back to you soon.", user.phone_number, phone_id)
        send_message(LANGUAGES[lang]["main_menu"], user.phone_number, phone_id)
        
        # Notify admin about the offer
        admin_msg = f"New price offer from {user.phone_number}:\nService: {user.quote_data.get('service', 'Unknown')}\nLocation: {user.quote_data.get('location', 'Unknown')}\nOffer: ${offer}"
        send_message(admin_msg, owner_phone, phone_id)
        
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user.phone_number}
    except ValueError:
        send_message("Please enter a valid number for your offer.", user.phone_number, phone_id)
        return {'step': 'collect_offer_details', 'user': user.to_dict(), 'sender': user.phone_number}

def handle_faq_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    if prompt == "1":  # Borehole FAQs
        update_user_state(user.phone_number, {
            'step': 'faq_borehole',
            'user': user.to_dict()
        })
        send_message(LANGUAGES[lang]["faq"]["borehole"]["menu"], user.phone_number, phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user.phone_number}
    elif prompt == "2":  # Pump FAQs
        update_user_state(user.phone_number, {
            'step': 'faq_pump',
            'user': user.to_dict()
        })
        send_message(LANGUAGES[lang]["faq"]["pump"]["menu"], user.phone_number, phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user.phone_number}
    elif prompt == "3":  # Custom question
        update_user_state(user.phone_number, {
            'step': 'custom_question',
            'user': user.to_dict()
        })
        send_message(LANGUAGES[lang]["faq"]["custom_question"], user.phone_number, phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user.phone_number}
    elif prompt == "4":  # Human agent
        send_message(LANGUAGES[lang]["agent_connect"], user.phone_number, phone_id)
        # Notify agent
        agent_message = LANGUAGES[lang]["new_request"].format(
            customer_number=user.phone_number,
            prompt="Requested human agent from FAQ menu"
        )
        send_message(agent_message, owner_phone, phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user.phone_number}
    elif prompt == "5":  # Main menu
        update_user_state(user.phone_number, {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send_message(LANGUAGES[lang]["main_menu"], user.phone_number, phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user.phone_number}
    
    send_message(LANGUAGES[lang]["invalid_option"], user.phone_number, phone_id)
    return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user.phone_number}

def handle_faq_borehole(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    responses = LANGUAGES[lang]["faq"]["borehole"]["responses"]
    
    if prompt in responses:
        send_message(responses[prompt], user.phone_number, phone_id)
        if prompt == "8":  # Back to FAQ menu
            update_user_state(user.phone_number, {
                'step': 'faq_menu',
                'user': user.to_dict()
            })
            send_message(LANGUAGES[lang]["faq"]["menu"], user.phone_number, phone_id)
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user.phone_number}
        
        # Show follow-up options
        send_message(LANGUAGES[lang]["faq"]["borehole"]["followup"], user.phone_number, phone_id)
        update_user_state(user.phone_number, {
            'step': 'faq_borehole_followup',
            'user': user.to_dict()
        })
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user.phone_number}
    
    send_message(LANGUAGES[lang]["invalid_option"], user.phone_number, phone_id)
    return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user.phone_number}

def handle_faq_borehole_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    if prompt == "1":  # Another question
        update_user_state(user.phone_number, {
            'step': 'faq_borehole',
            'user': user.to_dict()
        })
        send_message(LANGUAGES[lang]["faq"]["borehole"]["menu"], user.phone_number, phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user.phone_number}
    elif prompt == "2":  # Main menu
        update_user_state(user.phone_number, {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send_message(LANGUAGES[lang]["main_menu"], user.phone_number, phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user.phone_number}
    
    send_message(LANGUAGES[lang]["invalid_option"], user.phone_number, phone_id)
    return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user.phone_number}

def handle_faq_pump(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    responses = LANGUAGES[lang]["faq"]["pump"]["responses"]
    
    if prompt in responses:
        send_message(responses[prompt], user.phone_number, phone_id)
        if prompt == "6":  # Back to FAQ menu
            update_user_state(user.phone_number, {
                'step': 'faq_menu',
                'user': user.to_dict()
            })
            send_message(LANGUAGES[lang]["faq"]["menu"], user.phone_number, phone_id)
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user.phone_number}
        
        # Show follow-up options
        send_message(LANGUAGES[lang]["faq"]["pump"]["followup"], user.phone_number, phone_id)
        update_user_state(user.phone_number, {
            'step': 'faq_pump_followup',
            'user': user.to_dict()
        })
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user.phone_number}
    
    send_message(LANGUAGES[lang]["invalid_option"], user.phone_number, phone_id)
    return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user.phone_number}

def faq_pump_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "English"
    
    if prompt == "1":
        # Return to Pump FAQ menu
        update_user_state(user_data['sender'], {
            'step': 'faq_pump',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["faq"]["pump"]["menu"], user_data['sender'], phone_id)
        return {
            'step': 'faq_pump',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }
    elif prompt == "2":
        # Return to main menu
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
        return {
            'step': 'main_menu',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }
    else:
        send(LANGUAGES[lang]["invalid_option"], user_data['sender'], phone_id)
        return {
            'step': 'faq_pump_followup',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

def faq_pump(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "English"
    
    if prompt in LANGUAGES[lang]["faq"]["pump"]["responses"]:
        response = LANGUAGES[lang]["faq"]["pump"]["responses"][prompt]
        send(response, user_data['sender'], phone_id)
        
        if prompt == "6":  # Back to FAQ Menu option
            update_user_state(user_data['sender'], {
                'step': 'faq_menu',
                'user': user.to_dict()
            })
            send(LANGUAGES[lang]["faq"]["menu"], user_data['sender'], phone_id)
            return {
                'step': 'faq_menu',
                'user': user.to_dict(),
                'sender': user_data['sender']
            }
        else:
            # Show follow-up options
            update_user_state(user_data['sender'], {
                'step': 'faq_pump_followup',
                'user': user.to_dict()
            })
            send(LANGUAGES[lang]["faq"]["pump"]["followup"], user_data['sender'], phone_id)
            return {
                'step': 'faq_pump_followup',
                'user': user.to_dict(),
                'sender': user_data['sender']
            }
    else:
        send(LANGUAGES[lang]["faq"]["pump"]["invalid_option"], user_data['sender'], phone_id)
        return {
            'step': 'faq_pump',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

def faq_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "English"
    
    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["faq"]["borehole"]["menu"], user_data['sender'], phone_id)
        return {
            'step': 'faq_borehole',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }
    elif prompt == "2":  # Pump Installation FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_pump',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["faq"]["pump"]["menu"], user_data['sender'], phone_id)
        return {
            'step': 'faq_pump',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }
    elif prompt == "3":  # Ask a different question
        update_user_state(user_data['sender'], {
            'step': 'custom_question',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["faq"]["custom_question"], user_data['sender'], phone_id)
        return {
            'step': 'custom_question',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }
    elif prompt == "4":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["faq"]["human_agent_connect"], user_data['sender'], phone_id)
        return {
            'step': 'human_agent',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }
    elif prompt == "5":  # Back to Main Menu
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
        return {
            'step': 'main_menu',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }
    else:
        send(LANGUAGES[lang]["faq"]["invalid_option"], user_data['sender'], phone_id)
        return {
            'step': 'faq_menu',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

def custom_question(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'English'
    
    # Check for empty prompt
    if not prompt.strip():
        send(LANGUAGES[lang]["custom_question"]["empty_prompt"], user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}

    try:
        # Initialize Gemini API
        genai.configure(api_key=gen_api)
        model = genai.GenerativeModel("gemini-pro")
        
        # Create system prompt to keep responses focused
        system_prompt = (
            "You are a helpful assistant for SpeedGo, a borehole drilling and pump installation company in Zimbabwe. "
            "Only answer questions related to: borehole drilling, water surveys, pump installation, "
            "water solutions, or company services. For unrelated questions, politely decline to answer. "
            "Keep responses concise (1-2 paragraphs max) and in {lang} language."
        ).format(lang=lang)
        
        # Get response from Gemini
        response = model.generate_content([system_prompt, prompt])
        answer = response.text if hasattr(response, "text") else LANGUAGES[lang]["custom_question"]["error_response"]
        
    except Exception as e:
        logging.error(f"Gemini API error: {str(e)}")
        answer = LANGUAGES[lang]["custom_question"]["error_response"]

    # Send the answer
    send(answer, user_data['sender'], phone_id)
    
    # Ask follow-up question
    send(LANGUAGES[lang]["custom_question"]["follow_up"], user_data['sender'], phone_id)
    
    # Update state
    update_user_state(user_data['sender'], {
        'step': 'custom_question_followup',
        'user': user.to_dict()
    })
    
    return {'step': 'custom_question_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def custom_question_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'English'
    
    if prompt == "1":
        # Ask another question
        send(LANGUAGES[lang]["custom_question"]["next_question"], user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {
            'step': 'custom_question',
            'user': user.to_dict()
        })
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "2":
        # Return to main menu
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        # Invalid option
        send(LANGUAGES[lang]["custom_question"]["invalid_option"], user_data['sender'], phone_id)
        return {'step': 'custom_question_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'English'
    
    if prompt == "1":
        # Borehole FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["faq"]["borehole"]["menu"], user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "2":
        # Pump FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_pump',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["faq"]["pump"]["menu"], user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "3":
        # Custom question
        update_user_state(user_data['sender'], {
            'step': 'custom_question',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["faq"]["custom_question"], user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "4":
        # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["faq"]["human_agent_connect"], user_data['sender'], phone_id)
        
        # Notify agent
        notify_agent(
            user_data['sender'],
            "Customer requested human agent from FAQ menu",
            owner_phone,
            phone_id,
            lang
        )
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "5":
        # Main menu
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        # Invalid option
        send(LANGUAGES[lang]["faq"]["invalid_option"], user_data['sender'], phone_id)
        return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'English'
    responses = LANGUAGES[lang]["faq"]["borehole"]["responses"]
    
    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        
        if prompt == "8":  # Back to FAQ menu
            update_user_state(user_data['sender'], {
                'step': 'faq_menu',
                'user': user.to_dict()
            })
            send(LANGUAGES[lang]["faq"]["menu"], user_data['sender'], phone_id)
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
        
        # Ask follow-up
        send(LANGUAGES[lang]["faq"]["borehole"]["followup"], user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole_followup',
            'user': user.to_dict()
        })
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        # Invalid option
        send(LANGUAGES[lang]["faq"]["borehole"]["invalid_option"], user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'English'
    
    if prompt == "1":
        # Ask another borehole question
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["faq"]["borehole"]["menu"], user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "2":
        # Return to main menu
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        # Invalid option
        send(LANGUAGES[lang]["faq"]["borehole"]["invalid_option"], user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_pump(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'English'
    responses = LANGUAGES[lang]["faq"]["pump"]["responses"]
    
    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        
        if prompt == "6":  # Back to FAQ menu
            update_user_state(user_data['sender'], {
                'step': 'faq_menu',
                'user': user.to_dict()
            })
            send(LANGUAGES[lang]["faq"]["menu"], user_data['sender'], phone_id)
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
        
        # Ask follow-up
        send(LANGUAGES[lang]["faq"]["pump"]["followup"], user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {
            'step': 'faq_pump_followup',
            'user': user.to_dict()
        })
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        # Invalid option
        send(LANGUAGES[lang]["faq"]["pump"]["invalid_option"], user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_pump_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'English'
    
    if prompt == "1":
        # Ask another pump question
        update_user_state(user_data['sender'], {
            'step': 'faq_pump',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["faq"]["pump"]["menu"], user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "2":
        # Return to main menu
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        # Invalid option
        send(LANGUAGES[lang]["faq"]["pump"]["invalid_option"], user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def notify_agent(customer_number, message, agent_number, phone_id, lang='English'):
    """Notify the human agent about a customer request"""
    notification = LANGUAGES[lang]["agent_notification"].format(
        customer_number=customer_number,
        customer_name="Customer",  # Can be enhanced with user profile data
        prompt=message
    )
    send(notification, agent_number, phone_id)


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

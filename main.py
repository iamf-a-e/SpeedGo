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
import requests


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
            'step': 'enter_location_for_quote',
            'user': user.to_dict()
        })
        send("Please enter your location to get started.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Search Price Using Location
        update_user_state(user_data['sender'], {
            'step': 'get_pricing_for_location',
            'user': user.to_dict()
        })
        send(
           "To get you pricing, please enter your location (City/Town or GPS coordinates):",
            user_data['sender'], phone_id
        )
        return {'step': 'get_pricing_for_location', 'user': user.to_dict(), 'sender': user_data['sender']}
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
            'step': 'select_service',
            'user': user.to_dict()
        })
        send("Connecting you to a human agent...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}

    
    else:
        send("Please select a valid option (1-5).", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}


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

    # Attempt to get GPS coordinates (either from prompt or user_data)
    gps_coords = user_data.get('gps') or prompt.strip()

    # Convert GPS to location name using a mocked reverse geocoder
    location = reverse_geocode_location(gps_coords)

    if not location:
        send("Sorry, we couldn't detect your location. Please type your city name manually.", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'deepening_location_manual', 'user': user.to_dict()})
        return {'step': 'deepening_location_manual', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Save detected location
    user.quote_data['location'] = location

    # Fetch price
    price = get_pricing_for_location_quotes(location, "borehole_deepening")

    # Send price & ask for next step
    send(
        f"Deepening cost in {location.title()} starts from USD {price} per meter.\n"
        "Would you like to:\n"
        "1. Confirm & Book Job\n"
        "2. Back to Other Services",
        user_data['sender'], phone_id
    )

    update_user_state(user_data['sender'], {'step': 'deepening_booking_confirm', 'user': user.to_dict()})
    return {'step': 'deepening_booking_confirm', 'user': user.to_dict(), 'sender': user_data['sender']}



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
    if -21.1 < lat < -20.0 and 28.4 < lng < 29.0:
        return "Bulawayo"
    elif -22.22 < lat < -22.21 and 29.99 < lng < 30.01:
        return "Beitbridge Town"
    elif -20.01 < lat < -20.00 and 31.59 < lng < 31.60:
        return "Nyika Growth Point"
    elif -17.31 < lat < -17.30 and 31.33 < lng < 31.34:
        return "Bindura Town"
    elif -17.63 < lat < -17.62 and 27.34 < lng < 27.35:
        return "Binga Town"
    elif -19.53 < lat < -19.52 and 28.67 < lng < 28.68:
        return "Bubi Town/Centre"
    elif -19.28 < lat < -19.27 and 31.64 < lng < 31.65:
        return "Murambinda Town"
    elif -19.34 < lat < -19.33 and 31.43 < lng < 31.44:
        return "Buhera"
    elif -20.15 < lat < -20.14 and 28.56 < lng < 28.57:
        return "Bulawayo City/Town"
    elif -19.641 < lat < -19.640 and 31.153 < lng < 31.154:
        return "Gutu"
    elif -20.94 < lat < -20.93 and 29.00 < lng < 29.01:
        return "Gwanda"
    elif -19.45 < lat < -19.44 and 29.81 < lng < 29.82:
        return "Gweru"
    elif -17.83 < lat < -17.82 and 31.05 < lng < 31.06:
        return "Harare"

    # If not found locally, use Google Maps API
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lng}&key={AlzaSyCXDMMhg7FzP|ElKmrlkv1TqtD3HgHwW50}"

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


# Booking detail collection steps

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


def handle_enter_location_for_quote(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    # Save location
    user.quote_data['location'] = prompt.strip().lower()

    # Update state to wait for service selection
    update_user_state(user_data['sender'], {
        'step': 'select_service_quote',  # <- this is the key fix
        'user': user.to_dict()
    })

    # Prompt for service
    send(
        "Thanks! Now select the service:\n"
        "1. Water survey\n"
        "2. Borehole drilling\n"
        "3. Pump installation\n"
        "4. Commercial hole drilling\n"
        "5. Borehole Deepening",
        user_data['sender'], phone_id
    )

    return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}


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


def handle_user_message(message, user_data, phone_id):
    state = user_data.get('step')
    customer_number = user_data['sender']

    if state == 'waiting_for_human_agent_response':
        prompt_time = user_data.get('agent_prompt_time', 0)
        elapsed = time.time() - prompt_time

        if elapsed >= 10:
            # Send fallback prompt
            send(
                "Alternatively, you can message or call us directly at +263719835124.",
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




location_pricing = {
    "bulawayo": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 25
        },
        "Pump Installation": 0,
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "harare": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 2000,
            "class 9": 2300,
            "class 10": 2800,
            "included_depth_m": 40,
            "extra_per_m": 30
        },
        "Pump Installation": 0,
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    
}


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



def normalize_location(location_text):
    return location_text.strip().lower()


def get_pricing_for_location(location_input):
    location = normalize_location(location_input)
    services = location_pricing.get(location)

    if not services:
        return "Sorry, we don't have pricing for your location yet."

    pricing_lines = [f"{service}: {price}" for service, price in services.items()]
    return "Here are the prices for your area:\n" + "\n".join(pricing_lines)


def handle_get_pricing_for_location(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    # Normalize and fetch pricing info
    pricing_message = get_pricing_for_location(prompt)

    # Save the user's location
    user.quote_data['location'] = prompt

    # Update state (you can change next step as needed)
    update_user_state(user_data['sender'], {
        'step': 'collect_booking_info',  
        'user': user.to_dict()
    })

    # Send pricing message to user
    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'collect_booking_info',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }



def get_pricing_for_location_quotes(location_input, service_name):
    location = normalize_location(location_input)
    services = location_pricing.get(location)

    if not services:
        return f"Sorry, we don't have pricing for {location.title()} yet."

    service_name = service_name.strip().lower()

    for service, price in services.items():
        if service.lower() == service_name:
            if isinstance(price, dict):  # Handle Borehole Drilling (nested)
                class_6 = price.get("class 6", "N/A")
                class_9 = price.get("class 9", "N/A")
                class_10 = price.get("class 10", "N/A")
                included_depth = price.get("included_depth_m", "N/A")
                extra_per_m = price.get("extra_per_m", "N/A")
                return (
                    f"{service} Pricing in {location.title()}:\n"
                    f"- Class 6: ${class_6}\n"
                    f"- Class 9: ${class_9}\n"
                    f"- Class 10: ${class_10}\n"
                    f"- Includes depth up to {included_depth}m\n"
                    f"- Extra charge: ${extra_per_m}/m beyond included depth"
                )
            else:  # Flat price service
                return f"The price for {service} in {location.title()} is ${price}."

    return f"Sorry, we don't have pricing for '{service_name}' in {location.title()}."


def handle_get_pricing_for_location_quotes(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    service = prompt.strip()

    if not location:
        send("Please provide your location before selecting a service.", user_data['sender'], phone_id)
        return user_data

    pricing_message = get_pricing_for_location_quotes(location, service)
    user.quote_data['service'] = service

    update_user_state(user_data['sender'], {
        'step': 'collect_booking_info',
        'user': user.to_dict()
    })

    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'collect_booking_info',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_select_service_quote(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')

    if not location:
        send("Please provide your location first before selecting a service.", user_data['sender'], phone_id)
        return user_data

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
        return user_data

    # Store selected service
    user.quote_data['service'] = selected_service

    # Get pricing
    pricing_message = get_pricing_for_location_quotes(location, selected_service)

    # Ask if user wants to return to main menu or choose another service
    followup_message = (
        f"{pricing_message}\n\n"
        "Would you like to:\n"
        "1. Ask pricing for another service\n"
        "2. Return to Main Menu"
    )

    # Update user state to expect follow-up choice
    update_user_state(user_data['sender'], {
        'step': 'quote_followup',
        'user': user.to_dict()
    })

    send(followup_message, user_data['sender'], phone_id)

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
        return handle_select_language("0", user_data, phone_id)

    else:
        send("Invalid option. Reply 1 to ask about another service or 2 to return to the main menu.", user_data['sender'], phone_id)
        return {'step': 'quote_followup', 'user': user.to_dict(), 'sender': user_data['sender']}


#Shona

def handle_main_menu2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Request a quote
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote2',
            'user': user.to_dict()
        })
        send("Ndapota nyorai nzvimbo yamunogara kuti titange.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Search Price Using Location
        update_user_state(user_data['sender'], {
            'step': 'get_pricing_for_location2',
            'user': user.to_dict()
        })
        send(
           "Kuti tikwanise kukupai mitengo, ndapota nyora nzvimbo yamuri (Guta/Taundi kana GPS coordinates).",
            user_data['sender'], phone_id
        )
        return {'step': 'get_pricing_for_location2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Check Project Status
        update_user_state(user_data['sender'], {
            'step': 'check_project_status_menu2',
            'user': user.to_dict()
        })
        send(
            "Ndapota sarudza imwe yesarudzo idzi:\n"
            "1. Tarisa mamiriro ebasa rekuchera mugodhi\n"
            "2. Tarisa mamiriro ekuiswa kwepombi\n"
            "3. Kutaura nemumiriri wevanhu\n"
            "4. Main Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'check_project_status_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":
        update_user_state(user_data['sender'], {
            'step': 'faq_menu2',
            'user': user.to_dict()
        })
        send(
        "Ndapota sarudza chikamu cheMibvunzo Inowanzo bvunzwa (FAQ):\n\n"
            "1. Mibvunzo yeKuchera Mugodhi\n"
            "2. Mibvunzo yeKuiswa Kwepombi\n"
            "3. Bvunza mubvunzo wakasiyana\n"
            "4. Kutaura nemumiriri wevanhu\n"   
            "5. Main Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}


    elif prompt == "5":  # Other Services
        update_user_state(user_data['sender'], {
            'step': 'other_services_menu2',
            'user': user.to_dict()
        })
        send(
            "Ndeipi service yaunoda?\n"
            "1. Kuwedzera kudzika kweborehole\n"
            "2. Kubvisa tsvina muborehole (Borehole Flushing)\n"
            "3. Kusarudza PVC Casing Pipe\n"
            "4. Dzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'other_services_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

        

    elif prompt == "6":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'select_service2',
            'user': user.to_dict()
        })
        send("Tiri kukubatanidza nemumiriri wevanhu...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza chisarudzo chiri pakati pe1 ne5", user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_other_services_menu2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Mubvunzo we casing ye deepening
        send(
            "Kuti tione kana bhora renyu richigona kudzika zvakare:\n"
            "Rakaiswa mapaipi here:\n"
            "1. Pamusoro chete, nepaipi ine dhayamita ye 180mm kana kupfuura\n"
            "2. Kubva pamusoro kusvika pasi nepaipi ine dhayamita ye140mm kana pasi",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_deepening_casing2', 'user': user.to_dict()})
        return {'step': 'borehole_deepening_casing2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        # Rudzi rwe dambudziko rebhora
        send(
            "Chii chiri kunetsa nebhora renyu?\n"
            "1. Bhora rakaputsika\n"
            "2. Bhora rine mvura yakasviba",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_flushing_problem2', 'user': user.to_dict()})
        return {'step': 'borehole_flushing_problem2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "3":
        # Kusarudza PVC casing class
        send(
            "Tinopa kuchera tichishandisa mapaipi ePVC ane mapoka anotevera:\n"
            "1. Class 6 – Yakajairika\n"
            "2. Class 9 – Yakasimba\n"
            "3. Class 10 – Yakasimba zvikuru\n"
            "Mungada kuona mutengo weipi?",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'pvc_casing_selection2', 'user': user.to_dict()})
        return {'step': 'pvc_casing_selection2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "4":
        update_user_state(user_data['sender'], {'step': 'main_menu2', 'user': user.to_dict()})
        send_main_menu(user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza sarudzo yakakodzera (1-4).", user_data['sender'], phone_id)
        return {'step': 'other_services_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_borehole_deepening_casing2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Pamusoro chete - rinogona kudzika zvakare
        send("Bhora renyu rinokwanisa kudzika zvakare.\nNdapota nyora nzvimbo yenyu (guta, ward, growth point kana GPS pin):",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'deepening_location2', 'user': user.to_dict()})
        return {'step': 'deepening_location2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        # Top to bottom - harina kudzika zvakare
        send(
            "Zvine urombo, mabhorho akaiswa mapaipi kubva pamusoro kusvika pasi ane dhayamita isingasviki 180mm haagone kudzika zvakare.\n"
            "Sarudzo:\n"
            "1. Dzokera kuOther Services\n"
            "2. Taura neSupport",
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
        return handle_other_services_menu2("0", user_data, phone_id)

    elif choice == "2":
        send("Tirikukubatanidzai neSupport...", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'human_agent2', 'user': user.to_dict()})
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_no_deepening_options2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_location2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()

    user.quote_data['location'] = location

    price = get_pricing_for_location_quotes(location, "borehole_deepening")

    send(
        f"Mutengo wekudzika zvakare mu{location} unotangira pa USD {price} pamita.\n"
        "Munoda:\n"
        "1. Kusimbisa uye Bhuka Basa\n"
        "2. Dzokera kuOther Services",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'deepening_booking_confirm2', 'user': user.to_dict()})
    return {'step': 'deepening_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_deepening_booking_confirm2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Ndapota nyora zita renyu rizere:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name2', 'user': user.to_dict()})
        return {'step': 'booking_full_name2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return other_services_menu("0", user_data, phone_id)

    else:
        send("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_borehole_flushing_problem2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        send(
            "Munoziva here dhayamita yebhora?\n"
            "1. 180mm kana kupfuura\n"
            "2. Pakati pe140mm ne180mm\n"
            "3. 140mm kana pasi",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'flushing_collapsed_diameter2', 'user': user.to_dict()})
        return {'step': 'flushing_collapsed_diameter2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        send("Ndapota nyora nzvimbo yenyu kuti tiwane mutengo:", user_data['sender'], phone_id)
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
        send("Tinogona kugeza bhora renyu tichishandisa marodhi ane bit yekuchera (inoshanda zvakanyanya).\nNdapota nyora nzvimbo yenyu kuti tiwane mutengo:",
             user_data['sender'], phone_id)
    elif diameter == "between_140_and_180mm":
        send("Tinogona kugeza bhora tichishandisa marodhi, pasina bit yekuchera.\nNdapota nyora nzvimbo yenyu kuti tiwane mutengo:",
             user_data['sender'], phone_id)
    elif diameter == "140mm_or_smaller":
        send("Tinogona kugeza bhora tichishandisa marodhi chete (pasina bit yekuchera).\nNdapota nyora nzvimbo yenyu kuti tiwane mutengo:",
             user_data['sender'], phone_id)

    update_user_state(user_data['sender'], {'step': 'flushing_location2', 'user': user.to_dict()})
    return {'step': 'flushing_location2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_flushing_location2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.quote_data['location'] = location

    flushing_type = user.quote_data.get('flushing_type')
    diameter = user.quote_data.get('diameter')

    price = get_pricing_for_other_services(location, "borehole_flushing", {
        'flushing_type': flushing_type,
        'diameter': diameter
    })

    send(
        f"Mutengo wekuchenesa mu{location} unotangira pa USD {price}.\n"
        "Munoda:\n"
        "1. Kusimbisa uye Bhuka Basa\n"
        "2. Dzokera kuOther Services",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'flushing_booking_confirm2', 'user': user.to_dict()})
    return {'step': 'flushing_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_flushing_booking_confirm2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Ndapota nyora zita renyu rizere:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name2', 'user': user.to_dict()})
        return {'step': 'booking_full_name2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu("0", user_data, phone_id)

    else:
        send("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'flushing_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pvc_casing_selection2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()
    pvc_map = {
        "1": "Class 6 – Irinani",
        "2": "Class 9 – Yakasimba",
        "3": "Class 10 – Yakasimbisisa"
    }

    casing_class = pvc_map.get(choice)
    if not casing_class:
        send("Ndapota sarudza sarudzo yakakodzera (1-3).", user_data['sender'], phone_id)
        return {'step': 'pvc_casing_selection2', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['pvc_casing_class'] = casing_class

    send(f"Mutengo wePVC casing ye{casing_class} unoenderana nenzvimbo yako.\nNdapota nyora nzvimbo yako:",
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
        f"Mutengo wePVC casing ye{casing_class} munzvimbo ye{location} uri USD {price}.\n"
        "Ungade kuita zvinotevera:\n"
        "1. Simbisa & Bhuka\n"
        "2. Dzokera kuOther Services",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'pvc_casing_booking_confirm2', 'user': user.to_dict()})
    return {'step': 'pvc_casing_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pvc_casing_booking_confirm2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        user.booking_data = {}
        send("Ndapota nyora zita rako rizere:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name2', 'user': user.to_dict()})
        return {'step': 'booking_full_name2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu("0", user_data, phone_id)

    else:
        send("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'pvc_casing_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_full_name2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    full_name = prompt.strip()
    user.booking_data['full_name'] = full_name
    send("Ndapota nyora nhamba yako yefoni:", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_phone2', 'user': user.to_dict()})
    return {'step': 'booking_phone2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_phone2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    phone = prompt.strip()
    user.booking_data['phone'] = phone
    send("Ndapota nyora nzvimbo yako chaiyo/kero kana kugovera GPS pin yako:", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_location2', 'user': user.to_dict()})
    return {'step': 'booking_location2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_location2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.booking_data['location'] = location
    send("Ndapota nyora zuva raunoda kubhuka (semuenzaniso, 2024-10-15):", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_date2', 'user': user.to_dict()})
    return {'step': 'booking_date2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_date2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    booking_date = prompt.strip()
    user.booking_data['date'] = booking_date
    send("Kana uine zvinyorwa kana zvikumbiro zvakakosha, nyora zvino. Kana kwete, nyora 'Kwete':", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_notes2', 'user': user.to_dict()})
    return {'step': 'booking_notes2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_notes2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    notes = prompt.strip()
    user.booking_data['notes'] = notes if notes.lower() != 'kwete' else ''
    
    # At this point, save booking to database or call booking API
    booking_confirmation_number = save_booking(user.booking_data)  # You must implement save_booking

    send(
        f"Tinotenda {user.booking_data['full_name']}! Kubhuka kwako kwasimbiswa.\n"
        f"Booking Reference: {booking_confirmation_number}\n"
        "Chikwata chedu chichakubata munguva pfupi.\n"
        "Nyora 'menu' kudzokera kumenyu huru.",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'main_menu2', 'user': user.to_dict()})
    return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_check_project_status_menu2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'drilling_status_info_request2',
            'user': user.to_dict()
        })
    
        send(
            "Kuti muone mamiriro ebasa rekuchera borehole yenyu, ndapota ipai zvinotevera:\n\n"
            "- Zita rizere ramakashandisa pakubhuka\n"
            "- Nhamba yeReference kana Nhamba yefoni\n"
            "- Nzvimbo iri kuchererwa borehole (zvichida)",
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
            "Kuti muone mamiriro ekuiswa kwepombi yenyu, ndapota ipai zvinotevera:\n\n"
            "- Zita rizere ramakashandisa pakubhuka\n"
            "- Nhamba yeReference kana Nhamba yefoni\n"
            "- Nzvimbo yekuisa pombi (zvichida)",
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
        send("Rambai makabata makamirira kutaura nemunhu", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        return handle_main_menu2("", user_data, phone_id)

    else:
        send("Ndokumbirawo usarudze 1, 2, 3, kana 4.", user_data['sender'], phone_id)
        return {'step': 'check_project_status_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_drilling_status_info_request2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        # 👇 Only send this if the user's input is incomplete
        send(
            "Ndokumbirawo upe zita rako rizere pamwe nenhamba yekureva kana nhamba yefoni, imwe neimwe mutsara wayo.\n\n"
            "Muenzaniso:\n"
            "John Doe\nREF789123 kana 0779876543\nZvingasarudzwa: Bulawayo",
            user_data['sender'], phone_id
        )
        return {
            'step': 'drilling_status_info_request2',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    # ✅ Valid input: store and proceed
    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Not Provided"

    user.project_status_request2 = {
        'type': 'drilling',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Ndatenda. Ndokumbirawo mirira apo tiri kuwana mamiriro eprojekiti yako...", user_data['sender'], phone_id)

    send(
        f"Heano mamiriro eprojekiti yako yekuchera borehole:\n\n"
        f"Zita reProjekiti: Borehole - {full_name}\n"
        f"Chikamu Chazvino: Kuchera kuri Kufambira Mberi\n"
        f"Chinotevera: Kuisa Casing\n"
        f"Zuva Rakatarwa Rekupedzisa: 10/06/2025\n\n"
        "Ungada here kugamuchira zviziviso paWhatsApp kana mamiriro achichinja?\nSarudzo: Ehe / Kwete",
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


def handle_pump_status_info_request2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        # 👇 Only send this error message if the user input is incomplete
        send(
            "Ndokumbirawo upe zita rako rizere uye nhamba yerureferenzi kana nhamba yefoni, imwe neimwe mutsara mutsva.\n\n"
            "Muenzaniso:\n"
            "Jane Doe\nREF123456\nZvinokwanisika: Harare",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request2',
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
    send("Tatenda. Ndokumbirawo mirira tichiri kuwana ruzivo rwechirongwa chako...", user_data['sender'], phone_id)

    send(
        f"Pano pane mamiriro echirongwa chako chekuisa pampu:\n\n"
        f"Zita reChirongwa: Pampu - {full_name}\n"
        f"Chikamu Chazvino: Kuisa Kwapedzwa\n"
        f"Chinotevera: Kuongororwa kwekupedzisira\n"
        f"Zuva Rekuendesa: 12/06/2025\n\n"
        "Ungada here kugamuchira zviziviso paWhatsApp kana mamiriro achichinja?\nSarudzo: Ehe / Kwete",
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

    if response in ['hongu', 'h']:
        send(
            "Zvakanaka! Iye zvino uchagamuchira zviziviso paWhatsApp pese panochinja mamiriro eborehole drilling yako.\n\n"
            "Tatenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    elif response in ['kwete', 'k']:
        send(
            "Hazvina dambudziko. Unogona kugara uchiongorora mamiriro zvakare gare gare kana zvichidikanwa.\n\n"
            "Tatenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ndine urombo, handina kunzwisisa zvawataura. Ndapota pindura ne 'Ehe' kana 'Kwete'.", user_data['sender'], phone_id)
        return {'step': 'pump_status_updates_opt_in2', 'user': user.to_dict(), 'sender': user_data['sender']}

    # No further step – end the flow
    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_drilling_status_updates_opt_in2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['hongu', 'h']:
        send(
            "Zvakanaka! Iye zvino uchagamuchira zviziviso zveWhatsApp pese panochinja chimiro cheborehole drilling yako.\n\n"
            "Ndatenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    elif response in ['kwete', 'k']:
        send(
            "Hapana dambudziko. Unogona kugara uchitarisa chimiro zvakare gare gare kana zvichidiwa.\n\n"
            "Ndatenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    else:
        send("Ndine urombo, handina kunzwisisa zvawataura. Ndapota pindura ne 'Ehe' kana 'Kwete'.", user_data['sender'], phone_id)
        return {'step': 'drilling_status_updates_opt_in2', 'user': user.to_dict(), 'sender': user_data['sender']}

    # No further step – end the flow
    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_enter_location_for_quote2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    # Save location
    user.quote_data['location'] = prompt.strip().lower()

    # Update state to wait for service selection
    update_user_state(user_data['sender'], {
        'step': 'select_service_quote2',
        'user': user.to_dict()
    })

    # Prompt for service
    send(
        "Ndatenda! Zvino sarudza sevhisi:\n"
        "1. Kuongorora mvura\n"
        "2. Kuchera borehole\n"
        "3. Kuisa pombi\n"
        "4. Kuchera maborehole ekutengeserana\n"
        "5. Kukudza borehole",
        user_data['sender'], phone_id
    )

    return {'step': 'select_service_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}


def human_agent2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    customer_number = user_data['sender']
    customer_name = user.name if hasattr(user, "name") and user.name else "Asingazivikanwi"
    agent_number = "+263719835124"

    # Notify the customer immediately
    send(
        "Ndatenda. Ndapota mirira ndichakuendesa kumumiriri weSpeedGo...",
        customer_number, phone_id
    )

    # Notify the agent immediately
    agent_message = (
        f"👋 Mutengi anoda kukutaurira paWhatsApp.\n\n"
        f"📱 Nhamba yemutengi: {customer_number}\n"
        f"🙋 Zita: {customer_name}\n"
        f"📩 Mharidzo yekupedzisira: \"{prompt}\""
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

def handle_user_message2(message, user_data, phone_id):
    state = user_data.get('step')
    customer_number = user_data['sender']

    if state == 'waiting_for_human_agent_response2':
        prompt_time = user_data.get('agent_prompt_time', 0)
        elapsed = time.time() - prompt_time

        if elapsed >= 10:
            # Send fallback prompt
            send(
                "Kana zvikasadaro, unogona kutitumira meseji kana kutifonera pa +263719835124.",
                customer_number, phone_id
            )
            send(
                "Ungada kudzokera kumenu huru here?\n1. Ehe\n2. Kwete",
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
            # Optionally, you can just wait or remind user to hold on
            return user_data  # or send "Ndapota mirira..." message

    elif state == 'human_agent_followup2':
        # Handle user's Yes/No answer here
        if message.strip() == '1':  # User wants main menu
            send("Uri kudzoserwa kumenu huru...", customer_number, phone_id)
            # Reset state to main menu step (example)
            update_user_state(customer_number, {
                'step': 'main_menu2',
                'user': user_data['user'],
                'sender': customer_number
            })
            # Show main menu
            send_main_menu2(customer_number, phone_id)
            return {'step': 'main_menu2', 'user': user_data['user'], 'sender': customer_number}

        elif message.strip() == '2':  # User says No
            send("Ndatenda! Uve nezuva rakanaka.", customer_number, phone_id)
            # Optionally clear or end session
            update_user_state(customer_number, {
                'step': 'end',
                'user': user_data['user'],
                'sender': customer_number
            })
            return {'step': 'end', 'user': user_data['user'], 'sender': customer_number}
        else:
            send("Ndapota pindura ne 1 kuti Ehe kana 2 kuti Kwete.", customer_number, phone_id)
            return user_data


def human_agent_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        return handle_select_language2("1", user_data, phone_id)

    elif prompt == "2":
        send("Zvakanaka. Unogona kubvunza chero chaunoda.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota pindura ne 1 kuti Udzokere kumenu huru kana 2 kuti Urambe uripo pano.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_menu2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user']) 

    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole2',
            'user': user.to_dict()
        })
        send(
            "Mibvunzo inonyanya kubvunzwa pamusoro pekuchera maborehole:\n\n"
            "1. Kuchera borehole kunodhura zvakadii?\n"
            "2. Kuchera borehole kunotora nguva yakareba sei?\n"
            "3. Borehole yangu ichadzika zvakadii?\n"
            "4. Ndinoda mvumo here yekuchera borehole?\n"
            "5. Munenge moita ongororo yemvura pamwe nekuchera panguva imwe chete here?\n"
            "6. Ko kana maongororo yemvura ikaona pasina mvura?\n"
            "7. Munoshandisa zvishandiso zvipi?\n"
            "8. Dzokera kuMenu reFAQ",
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
            "1. Musiyano uripo pakati pemasolar nemagetsi ndeupi?\n"
            "2. Munogona kuisa mapombi kana ndatotenga zvinhu here?\n"
            "3. Kuisa pombi kunotora nguva yakareba sei?\n"
            "4. Ndeipi saizi yepombi yandinoda?\n"
            "5. Munopa matangi nemastendi here?\n"
            "6. Dzokera kuMenu reFAQ",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Ask a different question
        update_user_state(user_data['sender'], {
            'step': 'custom_question2',
            'user': user.to_dict()
        })
        send(
            "Ndapota nyora mubvunzo wako pazasi, tichaita zvose zvinobvira kukubatsira.\n",
            user_data['sender'], phone_id
        )
        return {'step': 'custom_question2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent2',
            'user': user.to_dict(),
            'sender': user_data['sender']
        })
        send("Ndapota mira ndichakubatanidza nemumiriri...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Back to Main Menu
        return handle_select_language2("1", user_data, phone_id)

    else:
        send("Ndapota sarudza sarudzo iri pakati pe (1–5).", user_data['sender'], phone_id)
        return {'step': 'faq_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

def custom_question2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    # Validate that prompt is not empty
    if not prompt.strip():
        send("Ndapota nyora mubvunzo wako.", user_data['sender'], phone_id)
        return {'step': 'custom_question2', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Gemini prompt template
    system_prompt = (
        "Iwe uri mubatsiri anoshanda weSpeedGo, kambani inoita maborehole nekumisikidza mapombi muZimbabwe. "
        "Unopindura mibvunzo chete inoenderana nemasevhisi eSpeedGo, mitengo, maitiro, kana rutsigiro rwevatengi. "
        "Kana mubvunzo usingaenderane neSpeedGo, taura zvine mutsindo kuti unokwanisa kubatsira chete nezve SpeedGo."
    )

    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content([system_prompt, prompt])

        answer = response.text.strip() if hasattr(response, "text") else "Ndine urombo, handingakupindure panguva ino."

    except Exception as e:
        answer = "Ndine urombo, pane chakakanganisika panguva yekugadzirisa mubvunzo wako. Ndokumbira uedze zvakare gare gare."
        print(f"[Gemini error] {e}")

    send(answer, user_data['sender'], phone_id)

    # Follow up options
    send(
        "Ungada kuita zvinotevera here:\n"
        "1. Bvunza imwe mibvunzo\n"
        "2. Dzokera kuMenu huru",
        user_data['sender'], phone_id
    )

    return {'step': 'custom_question_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


def custom_question_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send("Ndapota nyora mubvunzo wako unotevera.", user_data['sender'], phone_id)
        return {'step': 'custom_question2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language2("1", user_data, phone_id)

    else:
        send("Ndapota pindura ne 1 kuti ubvunze imwe mibvunzo kana 2 kuti udzokere kumenu huru.", user_data['sender'], phone_id)
        return {'step': 'custom_question_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}



def faq_borehole2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Mutengo unotsamira panzvimbo yako, kudzika kwebhobhoro uye rudzi rwevhu. Ndapota tumira nzvimbo yako uye ruzivo nezvekupinda munzvimbo iyi kuti tiwane mutengo wakakodzera.",
        "2": "Zvinotora maawa 4–6 kana mazuva mashoma zvichienderana nemamiriro enzvimbo, dombo, uye kuti nzvimbo inopinda sei.",
        "3": "Kudzika kunosiyana nenzvimbo. Pakazara, tinobaya kusvika pa40 meters asi zvinogona kusvika ku150 meters zvichienderana nemvura iri pasi pevhu.",
        "4": "Dzimwe nzvimbo dzinoda rezinesi remvura. Tinogona kukubatsira kunyorera kana zvichidikanwa.",
        "5": "Ehe, tinoita ongororo yemvura pamwe nekuboora panguva imwe chete kana zvichienderana nezvaunoda.",
        "6": "Kana muchida kuboora pane imwe nzvimbo zvakare, tinopa kuderedzwa kwemutengo. \n\nCherechedza: Muchina unoona mvura pasi pevhu unongoratidza nzvimbo dzine mukana wemvura asi hauna chivimbo chemvura iri kuitika ipapo. Saka hazvirevi kuti tinozotora mvura nguva dzose.",
        "7": "Tinoshandisa michina yepamusoro-soro yekuboora, maturusi eGPS uye zvishandiso zvekuongorora geology.",
        "8": "Kudzokera kuFAQ menyu..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Ungada kuita chii zvinotevera:\n"
            "1. Bvunza imwe mibvunzo yeBorehole Drilling FAQs\n"
            "2. Dzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza chisarudzo chiri pakati pe1 ne8.", user_data['sender'], phone_id)
        return {'step': 'faq_borehole2', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send(
            "Ndapota sarudza mubvunzo:\n\n"
            "1. Kuboora bhobhoro kunodhura zvakadini?\n"
            "2. Zvinotora nguva yakareba sei kuboora bhobhoro?\n"
            "3. Bhobhoro rangu richadzika zvakadii?\n"
            "4. Ndine mvumo here yekuboora bhobhoro?\n"
            "5. Munobatanidza ongororo yemvura nekuboora?\n"
            "6. Ko kana ongororo isina kuwana mvura?\n"
            "7. Munoshandisa midziyo ipi?\n"
            "8. Dzokera kuFAQ menyu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language2("1", user_data, phone_id)

    else:
        send("Ndapota sarudza 1 kubvunza imwe mibvunzo kana 2 kudzokera kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_pump2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Mapombi eSolar anoshandisa simba rezuva uye akakodzera nzvimbo dziri kure. Mapombi emagetsi anodhura zvishoma asi anotsamira paelekitirisi.",
        "2": "Ehe! Tinopa basa rekumisikidza chete kana iwe uine zvinhu zvose.",
        "3": "Kuiswa kwepombi kunotora zuva rimwe chete kana zvinhu zvose zviripo.",
        "4": "Saizi yepombi inotsamira pamvura yaunoda uye kudzika kwebhobhoro. Tinogona kutarisa nzvimbo yako uye kukurudzira.",
        "5": "Ehe, tinopa mapakeji akazara anosanganisira matangi emvura, zvimire, nezvimwe.",
        "6": "Kudzokera kuFAQ menyu..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)

        if prompt == "6":
            return {'step': 'faq_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Ungada kuita chii zvinotevera:\n"
            "1. Bvunza imwe mibvunzo yePump Installation FAQs\n"
            "2. Dzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza chisarudzo chiri pakati pe1 ne6.", user_data['sender'], phone_id)
        return {'step': 'faq_pump2', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send(
            "Ndapota sarudza mubvunzo:\n\n"
            "1. Musiyano uripo pakati peMapombi eSolar neMagetsi?\n"
            "2. Munogona kumisikidza kana ndine zvinhu zvangu?\n"
            "3. Zvinotora nguva yakareba sei kumisikidza pombi?\n"
            "4. Ndinoda saizi ipi yepombi?\n"
            "5. Munopa matangi nemazvikamu acho here?\n"
            "6. Dzokera kuFAQ menyu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language2("1", user_data, phone_id)

    else:
        send("Ndapota sarudza 1 kubvunza imwe mibvunzo kana 2 kudzokera kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_select_service2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    services = {
        "1": "Ongororo yemvura",
        "2": "Kuboora bhobhoro",
        "3": "Kuiswa kwepombi",
        "4": "Kuboora makomba emakambani",
        "5": "Kudzamisa bhobhoro",
    }
    if prompt in services:
        user.quote_data['service'] = services[prompt]
        update_user_state(user_data['sender'], {
            'step': 'collect_quote_details2',
            'user': user.to_dict()
        })
        send(
            "Kuti tikwanise kukupa fungidziro yemutengo, tapota pindura mibvunzo inotevera:\n\n"
            "1. Nzvimbo yenyu (Guta/Kero kana GPS):\n",
            user_data['sender'], phone_id
        )
        return {'step': 'handle_select_service_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sevhisi iri pakati pe1 kusvika ku5.", user_data['sender'], phone_id)
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
            'step': 'quote_response2',
            'user': user.to_dict()
        })
        estimate = "Class 6: Mari inofungidzirwa: $2500\nZvinobatanidza kuboora nePVC casing 140mm"
        send(
            f"Maita basa! Zvichienderana neruzivo rwamakatipa:\n\n"
            f"{estimate}\n\n"
            f"Cherechedzo: Kana kuchidikanwa casing yepiri, inobhadharwa zvakasiyana uye chete mushure mekusimbiswa nemutengi.\n\n"
            f"Ungada kuita chii zvinotevera:\n"
            f"1. Taura mutengo waunokwanisa\n"
            f"2. Bhuka Site Survey\n"
            f"3. Bhuka kuboora\n"
            f"4. Taura neMumiriri",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_response2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota ipa ruzivo rwese rwakumbirwa (kanokwana mitsetse mina).", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_quote_response2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Offer price
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details2',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Unogona kutumira mitengo yauri kukwanisa pazasi.\n\n"
            "Ndapota tumira nemafomati anotevera:\n\n"
            "- Ongororo yemvura: $____\n"
            "- Kuboora bhobhoro: $____",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Book site survey
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info2',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Ndapota ipa ruzivo runotevera kuti tipedze kunyoresa kwako:\n\n"
            "- Zita rizere:\n"
            "- Zuva raunoda (dd/mm/yyyy):\n"
            "- Kero yeNzvimbo kana GPS:\n"
            "- Nhamba yefoni:\n"
            "- Nzira yekubhadhara (Prepayment / Mari panzvimbo):\n\n"
            "Nyora: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Book for a Drilling
        send("Mumiriri wedu achakufonera kuti apedze kunyoresa kwekuboora.", user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # Human Agent
        send("Tirikukubatanidza nemumiriri wevanhu...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ndapota sarudza chisarudzo chiri pakati pe1 ne4.", user_data['sender'], phone_id)
        return {'step': 'quote_response2', 'user': user.to_dict(), 'sender': user_data['sender']}


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
            "Nhau dzakanaka! Mutengo wako wagamuchirwa.\n\n"
            "Ngatisimbise danho rinotevera.\n\n"
            "Ungada kuita chii:\n"
            "1. Bhuka Site Survey\n"
            "2. Bhadhara dhipoziti\n"
            "3. Simbisa zuva rekuboora",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_details2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Tirikukubatanidza nemumiriri wevanhu...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details2',
            'user': user.to_dict()
        })
        send(
            "Ndapota tumira mutengo wako wakagadziridzwa nemafomati anotevera:\n\n"
            "- Ongororo yemvura: $____\n"
            "- Kuboora bhobhoro: $____",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza chisarudzo chiri pakati pe1 ne3.", user_data['sender'], phone_id)
        return {'step': 'offer_response2', 'user': user.to_dict(), 'sender': user_data['sender']}

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
        "Chikumbiro chako chatumirwa kumaneja wedu wezvekutengesa. Tichapindura mukati meawa imwe chete.\n\n"
        "Tinotenda nechipo chako!\n\n"
        "Chikwata chedu chichachiongorora uye chipindure munguva pfupi.\n\n"
        "Kunyange tichiedza kupa mitengo inokwanisika, mitengo yedu inoratidza unhu, kuchengetedzeka, uye kuvimbika.\n\n"
        "Ungade kuita sei:\n"
        "1. Enderera mberi kana chipo chagamuchirwa\n"
        "2. Kutaura nemunhu\n"
        "3. Kuchinja chipo chako",
        user_data['sender'], phone_id
    )
    return {'step': 'offer_response2', 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_booking_details2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info2',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Ndapota ipa ruzivo runotevera kuti tipedze kunyoresa kwako:\n\n"
            "- Zita rizere:\n"
            "- Zuva raunoda (dd/mm/yyyy):\n"
            "- Kero yeNzvimbo kana GPS:\n"
            "- Nhamba yefoni:\n"
            "- Nzira yekubhadhara (Prepayment / Mari panzvimbo):\n\n"
            "Nyora: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Ndapota bata hofisi yedu pa 077xxxxxxx kuti muronge kubhadhara dhipoziti.", user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("Mumiriri wedu achakufonera kuti asimbise zuva rekuboora.", user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza chisarudzo chiri pakati pe1 ne3.", user_data['sender'], phone_id)
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
            "Tinotenda. Kunyoresa kwako kwatogamuchirwa uye mainjiniya achakuonana munguva pfupi.\n\n"
            f"Chiziviso: Site Survey yako yakarongwa kuitwa mangwana.\n\n"
            f"Zuva: {booking_date}\n"
            f"Nguva: {booking_time}\n\n"
            "Tiri kutarisira kushanda nemi!\n"
            "Munoda kuchinja zuva? Pindura:\n\n"
            "1. Ehe\n"
            "2. Kwete",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_confirmation2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota nyora 'Submit' kusimbisa kunyoresa kwako.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info2', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_confirmation2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "2":
        send(
            "Zvakanaka! Bhobhoro drilling yako yanyoreswa.\n\n"
            "Zuva: China, 23 Chivabvu 2025\n"
            "Nguva yekutanga: 8:00 AM\n"
            "Nguva inotarisirwa: maawa 5\n"
            "Chikwata: Mainjiniya 4-5\n\n"
            "Ita shuwa kuti nzvimbo inowanikwa zviri nyore",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota bata chikwata chedu chetsigiro kuti muchinje zuva.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation2', 'user': user.to_dict(), 'sender': user_data['sender']}



location_pricing2 = {
    "bulawayo": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 25
        },
        "Pump Installation": 0,
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "harare": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 2000,
            "class 9": 2300,
            "class 10": 2800,
            "included_depth_m": 40,
            "extra_per_m": 30
        },
        "Pump Installation": 0,
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    
}


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



def normalize_location2(location_text):
    return location_text.strip().lower()


def get_pricing_for_location2_shona(location_input):
    location = normalize_location(location_input)
    services = location_pricing.get(location)

    if not services:
        return "Tine urombo, hatina mitengo yenzvimbo yenyu pari zvino."

    pricing_lines = [f"{service}: {price}" for service, price in services.items()]
    return "Heano mitengo yenzvimbo yenyu:\n" + "\n".join(pricing_lines)


def handle_get_pricing_for_location2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    # Normalize and fetch pricing info
    pricing_message = get_pricing_for_location2(prompt)

    # Save the user's location
    user.quote_data['location'] = prompt

    # Update state (you can change next step as needed)
    update_user_state(user_data['sender'], {
        'step': 'collect_booking_info2',  
        'user': user.to_dict()
    })

    # Send pricing message to user
    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'collect_booking_info2',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }



def get_pricing_for_location_quotes2(location_input, service_name):
    location = normalize_location(location_input)
    services = location_pricing.get(location)

    if not services:
        return f"Tine urombo, hatina mitengo ye {location.title()} pari zvino."

    service_name = service_name.strip().lower()

    for service, price in services.items():
        if service.lower() == service_name:
            if isinstance(price, dict):  # Handle Borehole Drilling (nested)
                class_6 = price.get("class 6", "N/A")
                class_9 = price.get("class 9", "N/A")
                class_10 = price.get("class 10", "N/A")
                included_depth = price.get("Kudzika_kwakabatanidzwa_m", "N/A")
                extra_per_m = price.get("extra_per_m", "N/A")
                return (
                    f"{service} Pricing in {location.title()}:\n"
                    f"- Class 6: ${class_6}\n"
                    f"- Class 9: ${class_9}\n"
                    f"- Class 10: ${class_10}\n"
                    f"- Kusanganisisira kudzikiswa kunosvika {included_depth}m\n"
                    f"- Extra charge: ${extra_per_m}/m anopfurikidza atinoita"
                )
            else:  # Flat price service
                return f"Mutengo we {service} ku {location.title()} i ${price}."

    return f"Tine urombo, hatina mitengo ye '{service_name}' ku {location.title()}."


def handle_get_pricing_for_location_quotes2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    service = prompt.strip()

    if not location:
        send("Ndokumbirawo upe nzvimbo irikuda kuitwa basa.", user_data['sender'], phone_id)
        return user_data

    pricing_message = get_pricing_for_location_quotes2(location, service)
    user.quote_data['service'] = service

    update_user_state(user_data['sender'], {
        'step': 'collect_booking_info2',
        'user': user.to_dict()
    })

    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'collect_booking_info2',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_select_service_quote2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')

    if not location:
        send("Ndokumbirawo upe nzvimbo yako usati wasarudza sevhisi.", user_data['sender'], phone_id)
        return user_data

    service_map = {
        "1": "Kuongorora Mvura",
        "2": "Kubaya Borehole",
        "3": "Kuisa Pombi",
        "4": "Kubaya Maburi eBhizinesi",
        "5": "Kuwedzera Kudzika kweBorehole"
    }

    selected_service = service_map.get(prompt.strip())

    if not selected_service:
        send("Sarudzo haina kunaka. Ndapota pindura ne 1, 2, 3, 4 kana 5 kusarudza sevhisi.", user_data['sender'], phone_id)
        return user_data

    # Store selected service
    user.quote_data['service'] = selected_service

    # Get pricing
    pricing_message2 = get_pricing_for_location_quotes2(location, selected_service)

    # Ask if user wants to return to main menu or choose another service
    followup_message2 = (
        f"{pricing_message2}\n\n"
        "Ungada here:\n"
        "1. Kubvunza mutengo wese wese weimwe sevhisi\n"
        "2. Kudzokera kuMenu Huru"
    )
    # Update user state to expect follow-up choice
    update_user_state2(user_data['sender'], {
        'step': 'quote_followup2',
        'user': user.to_dict()
    })

    send(followup_message, user_data['sender'], phone_id)

    return {
        'step': 'quote_followup2',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }

def handle_quote_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt.strip() == "1":
        # Stay in quote flow, show services again
        update_user_state2(user_data['sender'], {
            'step': 'select_service_quote2',
            'user': user.to_dict()
        })
        send(
            "Sarudza sevhisi imwe:\n"
            "1. Kuongorora Mvura\n"
            "2. Kubaya Borehole\n"
            "3. Kuisa Pombi\n"
            "4. Kubaya Maburi eBhizinesi\n"
            "5. Kuwedzera Kudzika kweBorehole",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "2":
        # Go back to main menu
        update_user_state(user_data['sender'], {
            'step': 'main_menu2',
            'user': user.to_dict()
        })
        return handle_select_language2("0", user_data, phone_id)

    else:
        send(
            "Sarudzo haina kunaka. Pindura 1 kubvunza nezveimwe sevhisi kana 2 kudzokera kumenu huru.",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}



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
    text = prompt.strip().lower()

   
    if text in ["hi", "hey", "hie"]:
        user_state = {'step': 'handle_welcome', 'sender': sender}
        updated_state = get_action('handle_welcome', prompt, user_state, phone_id)
        update_user_state(sender, updated_state)
        return updated_state  # return something or None

    elif text in ["mhoro", "makadini", "maswera sei", "ko sei zvako", "hesi"]:
        user_state = {'step': 'handle_welcome2', 'sender': sender}
        updated_state = get_action('handle_welcome2', prompt, user_state, phone_id)
        update_user_state(sender, updated_state)
        return updated_state  # return something or None


    user_state = get_user_state(sender)
    user_state['sender'] = sender    
    next_state = get_action(user_state['step'], prompt, user_state, phone_id)
    update_user_state(sender, next_state)
    return next_state

    

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


    
# Action mapping
action_mapping = {
    "welcome": handle_welcome,
    "select_language": handle_select_language,
    "main_menu": handle_main_menu,
    "enter_location_for_quote": handle_enter_location_for_quote,  
    "select_service_quote": handle_select_service_quote, 
    "select_service": handle_select_service,
    "get_pricing_for_location": handle_get_pricing_for_location,
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
    "human_agent_followup": human_agent_followup,   
    "other_services_menu": handle_other_services_menu,
    "borehole_deepening_casing": handle_borehole_deepening_casing,
    "borehole_flushing_problem": handle_borehole_flushing_problem,
    "pvc_casing_selection": handle_pvc_casing_selection,
    "deepening_location": handle_deepening_location,
    "handle_deepening_location": handle_deepening_location,
    "reverse_geocode_location": reverse_geocode_location,
    "human_agent": lambda prompt, user_data, phone_id: (
        send("A human agent will contact you soon.", user_data['sender'], phone_id)
        or {'step': 'main_menu', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
    ),
    "main_menu2": handle_main_menu2,
    "enter_location_for_quote2": handle_enter_location_for_quote2,  
    "select_service_quote2": handle_select_service_quote2, 
    "select_service2": handle_select_service2,
    "get_pricing_for_location2": handle_get_pricing_for_location2,
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
    "drilling_status_updates_opt_in": handle_drilling_status_updates_opt_in2,
    "custom_question2": custom_question2,
    "custom_question_followup2": custom_question_followup2,
    "human_agent2": human_agent2,
    "human_agent_followup2": human_agent_followup2,
    "other_services_menu2": handle_other_services_menu2,
    "borehole_deepening_casing2": handle_borehole_deepening_casing2,
    "borehole_flushing_problem2": handle_borehole_flushing_problem2,
    "pvc_casing_selection2": handle_pvc_casing_selection2,
    "deepening_location2": handle_deepening_location2,   
    "human_agent2": lambda prompt, user_data, phone_id: (
        send("A human agent will contact you soon.", user_data['sender'], phone_id)
        or {'step': 'main_menu2', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
    ),
}



if __name__ == "__main__":
    app.run(debug=True, port=8000)

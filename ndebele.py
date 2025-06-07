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
        self.language = "Ndebele"
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
def get_user_state3(phone_number):
    state = redis.get(phone_number)
    if state is None:
        return {"step": "welcome", "sender": phone_number}
    if isinstance(state, str):
        return json.loads(state)
    return state

def update_user_state3(phone_number, updates, ttl_seconds=60):
    updates['phone_number'] = phone_number
    if 'sender' not in updates:
        updates['sender'] = phone_number
    redis.set(phone_number, json.dumps(updates), ex=ttl_seconds)

def send3(answer, sender, phone_id):
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

def reverse_geocode_location3(gps_coords):
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
location_pricing3 = {
    "beitbridge": {
        "Ukuhlolwa kwamanzi": 150,
        "Ukugawula kwembobo yomthombo": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Ukugawula kwembobo yezamabhizimusi": 80,
        "Ukwengezwa kobude bembobo": 30
    },
    "nyika": {
        "Ukuhlolwa kwamanzi": 150,
        "Ukugawula kwembobo yomthombo": {
            "class 6": 1050,
            "class 9": 1181.25,
            "class 10": 1312.5,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Ukugawula kwembobo yezamabhizimusi": 80,
        "Ukwengezwa kobude bembobo": 30
    },
    "bindura": {
        "Ukuhlolwa kwamanzi": 150,
        "Ukugawula kwembobo yomthombo": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Ukugawula kwembobo yezamabhizimusi": 80,
        "Ukwengezwa kobude bembobo": 30
    },
    "binga": {
        "Ukuhlolwa kwamanzi": 150,
        "Ukugawula kwembobo yomthombo": {
            "class 6": 1300,
            "class 9": 1462.5,
            "class 10": 1625,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Ukugawula kwembobo yezamabhizimusi": 80,
        "Ukwengezwa kobude bembobo": 30
    },
    "bubi": {
        "Ukuhlolwa kwamanzi": 150,
        "Ukugawula kwembobo yomthombo": {
            "class 6": 1200,
            "class 9": 1350,
            "class 10": 1500,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Ukugawula kwembobo yezamabhizimusi": 80,
        "Ukwengezwa kobude bembobo": 30
    },
    "murambinda": {
        "Ukuhlolwa kwamanzi": 150,
        "Ukugawula kwembobo yomthombo": {
            "class 6": 1050,
            "class 9": 1181.25,
            "class 10": 1312.5,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Ukugawula kwembobo yezamabhizimusi": 80,
        "Ukwengezwa kobude bembobo": 30
    },
    "buhera": {
        "Ukuhlolwa kwamanzi": 150,
        "Ukugawula kwembobo yomthombo": {
            "class 6": 1150,
            "class 9": 1293.75,
            "class 10": 1437.5,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Ukugawula kwembobo yezamabhizimusi": 80,
        "Ukwengezwa kobude bembobo": 30
    },
    "harare": {
        "Ukuhlolwa kwamanzi": 150,
        "Ukugawula kwembobo yomthombo": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 30
        },
        "Ukugawula kwembobo yezamabhizimusi": 80,
        "Ukwengezwa kobude bembobo": 30
    },
    "bulawayo": {
        "Ukuhlolwa kwamanzi": 150,
        "Ukugawula kwembobo yomthombo": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Ukugawula kwembobo yezamabhizimusi": 80,
        "Ukwengezwa kobude bembobo": 30
    }
}

pump_installation_options3 = {
    "1": {
        "description": "I-D.C solar (ilanga eliqondileyo ngaphandle kwe-inverter) - Ngilalo ithangi kanye lesitezi sakhona",
        "price": 1640
    },
    "2": {
        "description": "I-D.C solar (ilanga eliqondileyo ngaphandle kwe-inverter) - Angilalutho",
        "price": 2550
    },
    "3": {
        "description": "I-D.C solar (ilanga eliqondileyo ngaphandle kwe-inverter) - Umsebenzi kuphela",
        "price": 200
    },
    "4": {
        "description": "I-A.C electric (ZESA kumbe solar inverter) - Ukufaka lempahla konke",
        "price": 1900
    },
    "5": {
        "description": "I-A.C electric (ZESA kumbe solar inverter) - Umsebenzi kuphela",
        "price": 170
    },
    "6": {
        "description": "I-A.C electric (ZESA kumbe solar inverter) - Ngilalo ithangi kanye lesitezi sakhona",
        "price": 950
    }
}

def get_pricing_for_location_quotes3(location, service_type, pump_option_selected=None):
    location_key = location.strip().lower()
    service_key = service_type.strip().title()

    if service_key == "Pump Installation":
        if pump_option_selected is None:            
            message_lines = [f"💧 Okhetho lwefaka iphampu:\n"]
            for key, option in pump_installation_options3.items():
                desc = option.get('description', 'Akunachazamazwi')
                message_lines.append(f"{key}. {desc}")
            return "\n".join(message_lines)
        else:
            option = pump_installation_options3.get(pump_option_selected)
            if not option:
                return "Uxolo, okhetho olukhethiweyo lwefaka iphampu alulunganga."
            desc = option.get('description', 'Akunachazamazwi')
            price = option.get('price', 'N/A')
            message = f"💧 Intengo yenketho {pump_option_selected}:\n{desc}\nIntengo: ${price}\n"
            message += "\nUngathanda yini:\n1. Buza intengo yenye inkonzo\n2. Buyela kuMain Menu\n3. Nika Intengo Yakho"
            return message

    loc_data = location_pricing3.get(location_key)
    if not loc_data:
        return "Uxolo, asikabi lentengo yalendawo."

    price = loc_data.get(service_key)
    if not price:
        return f"Uxolo, intengo ye-{service_key} ayitholakali e-{location.title()}."

    if isinstance(price, dict):
        included_depth = price.get("included_depth_m", "N/A")
        extra_rate = price.get("extra_per_m", "N/A")

        classes = {k: v for k, v in price.items() if k.startswith("class")}
        message_lines = [f"Intengo ye-{service_key} e-{location.title()}:"]
        for cls, amt in classes.items():
            message_lines.append(f"- {cls.title()}: ${amt}")
        message_lines.append(f"- Ifaka ukujula okungafika ku-{included_depth}m")
        message_lines.append(f"- Inkokhelo eyengezwayo: ${extra_rate}/m ngaphezu kwalokho\n")
        message_lines.append("Ungathanda yini:\n1. Buza intengo yenye inkonzo\n2. Buyela kuMain Menu\n3. Nika Intengo Yakho")
        return "\n".join(message_lines)

    unit = "ngemitha" if service_key in ["Commercial Hole Drilling", "Borehole Deepening"] else "intengo eqinileyo"
    return (f"{service_key} e-{location.title()}: ${price} {unit}\n\n"
            "Ungathanda yini:\n1. Buza intengo yenye inkonzo\n2. Buyela kuMain Menu\n3. Nika Intengo Yakho")


def handle_welcome(prompt, user_data, phone_id):
    send(
        "Siyakwamukela ku-SpeedGo Services, inkampani yokugawula imithombo yamanzi eZimbabwe. "
        "Sinikezela ngezixazululo ezithembekileyo zokumba imithombo yamanzi kuyo yonke iZimbabwe.\n\n"
        "Khetha ulimi olukuthokozisayo:\n"
        "1. English\n"
        "2. Shona\n"
        "3. Ndebele",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'select_language3'})
    return {'step': 'select_language3', 'sender': user_data['sender']}


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
            "2. Bheka intengo usebenzisa indawo\n"
            "3. Hlola isimo sephrojekthi\n"
            "4. Imibuzo evame ukubuzwa noma funda ngoKumba Ibhorehole\n"
            "5. Ezinye izinsiza zethu\n"
            "6. Khuluma lomuntu\n\n"
            "Sicela uphendule ngenombolo (isb. 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Sicela ukhethe ulimi olusemthethweni (1 for English, 2 for Shona, 3 for Ndebele).", user_data['sender'], phone_id)
        return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}


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
        gps_coords = f"{lat},{lng}"
        location_name = reverse_geocode_location(gps_coords)

        if location_name:
            user.quote_data['location'] = location_name
            user.quote_data['gps_coords'] = gps_coords
            update_user_state(user_data['sender'], {
                'step': 'select_service_quote3',
                'user': user.to_dict()
            })
            send(
                f"Indawo etholakele: {location_name.title()}\n\n"
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

ndebele_blueprint = Blueprint('ndebele', __name__)

@ndebele_blueprint.route('/message', methods=['POST'])
def ndebele_message_handler():
    data = request.get_json()
    message = data.get('message')
    sender = data.get('sender')
    phone_id = data.get('phone_id')
    message_handler(message, sender, phone_id, {'type': 'text', 'text': {'body': message}})
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(debug=True, port=8000)

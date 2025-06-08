import os
import json
import logging
import requests
import random
import string
from datetime import datetime
from flask import Flask, request, jsonify, render_template, Blueprint
from upstash_redis import Redis
import google.generativeai as genai
import threading
import time
from utils import get_user_language, set_user_language, send_message, set_user_state, get_user_state, update_user_state
from utils import User

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


# State helpers
def get_user_state2(phone_number):
    state = redis.get(phone_number)
    if state is None:
        return {"step": "welcome2", "sender": phone_number}
    if isinstance(state, str):
        return json.loads(state)
    return state

def update_user_state2(phone_number, updates, ttl_seconds=60):
    updates['phone_number'] = phone_number
    if 'sender' not in updates:
        updates['sender'] = phone_number
    redis.set(phone_number, json.dumps(updates), ex=ttl_seconds)

def send2(answer, sender, phone_id):
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

def reverse_geocode_location2(gps_coords):
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
location_pricing2 = {
    "beitbridge": {
        "Ongororo Yemvura": 150,
        "Kuchera Chibhorani": {
            "kirasi 6": 1000,
            "kirasi 9": 1125,
            "kirasi 10": 1250,
            "hudzamu huri mubhadharo_m": 40,
            "wedzera pamita imwe_m": 27
        },
        "Kuchera Chibhorani cheBhizinesi": 80,
        "Kuwedzera Kudzika kweChibhorani": 30
    },
    "nyika": {
        "Ongororo Yemvura": 150,
        "Kuchera Chibhorani": {
            "kirasi 6": 1050,
            "kirasi 9": 1181.25,
            "kirasi 10": 1312.5,
            "hudzamu huri mubhadharo_m": 40,
            "wedzera pamita imwe_m": 27
        },
        "Kuchera Chibhorani cheBhizinesi": 80,
        "Kuwedzera Kudzika kweChibhorani": 30
    },
    "bindura": {
        "Ongororo Yemvura": 150,
        "Kuchera Chibhorani": {
            "kirasi 6": 1000,
            "kirasi 9": 1125,
            "kirasi 10": 1250,
            "hudzamu huri mubhadharo_m": 40,
            "wedzera pamita imwe_m": 27
        },
        "Kuchera Chibhorani cheBhizinesi": 80,
        "Kuwedzera Kudzika kweChibhorani": 30
    },
    "binga": {
        "Ongororo Yemvura": 150,
        "Kuchera Chibhorani": {
            "kirasi 6": 1300,
            "kirasi 9": 1462.5,
            "kirasi 10": 1625,
            "hudzamu huri mubhadharo_m": 40,
            "wedzera pamita imwe_m": 27
        },
        "Kuchera Chibhorani cheBhizinesi": 80,
        "Kuwedzera Kudzika kweChibhorani": 30
    },
    "bubi": {
        "Ongororo Yemvura": 150,
        "Kuchera Chibhorani": {
            "kirasi 6": 1200,
            "kirasi 9": 1350,
            "kirasi 10": 1500,
            "hudzamu huri mubhadharo_m": 40,
            "wedzera pamita imwe_m": 27
        },
        "Kuchera Chibhorani cheBhizinesi": 80,
        "Kuwedzera Kudzika kweChibhorani": 30
    },
    "murambinda": {
        "Ongororo Yemvura": 150,
        "Kuchera Chibhorani": {
            "kirasi 6": 1050,
            "kirasi 9": 1181.25,
            "kirasi 10": 1312.5,
            "hudzamu huri mubhadharo_m": 40,
            "wedzera pamita imwe_m": 27
        },
        "Kuchera Chibhorani cheBhizinesi": 80,
        "Kuwedzera Kudzika kweChibhorani": 30
    },
    "buhera": {
        "Ongororo Yemvura": 150,
        "Kuchera Chibhorani": {
            "kirasi 6": 1150,
            "kirasi 9": 1293.75,
            "kirasi 10": 1437.5,
            "hudzamu huri mubhadharo_m": 40,
            "wedzera pamita imwe_m": 27
        },
        "Kuchera Chibhorani cheBhizinesi": 80,
        "Kuwedzera Kudzika kweChibhorani": 30
    },
    "harare": {
        "Ongororo Yemvura": 150,
        "Kuchera Chibhorani": {
            "kirasi 6": 1000,
            "kirasi 9": 1125,
            "kirasi 10": 1250,
            "hudzamu huri mubhadharo_m": 40,
            "wedzera pamita imwe_m": 30
        },
        "Kuchera Chibhorani cheBhizinesi": 80,
        "Kuwedzera Kudzika kweChibhorani": 30
    },
    "bulawayo": {
        "Ongororo Yemvura": 150,
        "Kuchera Chibhorani": {
            "kirasi 6": 1000,
            "kirasi 9": 1125,
            "kirasi 10": 1250,
            "hudzamu huri mubhadharo_m": 40,
            "wedzera pamita imwe_m": 27
        },
        "Kuchera Chibhorani cheBhizinesi": 80,
        "Kuwedzera Kudzika kweChibhorani": 30
    }
}

pump_installation_options2 = {
    "1": {
        "description": "D.C solar (inoshanda nezuva chete, hapana inverter) - Ndine tangi netangi stand",
        "price": 1640
    },
    "2": {
        "description": "D.C solar (inoshanda nezuva chete, hapana inverter) - Handina chinhu zvachose",
        "price": 2550
    },
    "3": {
        "description": "D.C solar (inoshanda nezuva chete, hapana inverter) - Basa chete (labour)",
        "price": 200
    },
    "4": {
        "description": "A.C yemagetsi (ZESA kana solar inverter) - Kugadzirisa nekuunza zvinhu",
        "price": 1900
    },
    "5": {
        "description": "A.C yemagetsi (ZESA kana solar inverter) - Basa chete (labour)",
        "price": 170
    },
    "6": {
        "description": "A.C yemagetsi (ZESA kana solar inverter) - Ndine tangi netangi stand",
        "price": 950
    }
}


def get_pricing_for_location_quotes2(location, service_type, pump_option_selected=None):
    location_key = location.strip().lower()
    service_key = service_type.strip().title()  # Normalize e.g. "Pump Installation"

    # Handle Pump Installation separately
    if service_key == "Pump Installation":
        if pump_option_selected is None:            
            message_lines = [f"💧 Zvingasarudzwa zvekuisa pombi:\n"]
            for key, option in pump_installation_options.items():
                desc = option.get('description', 'Hapana tsananguro')
                message_lines.append(f"{key}. {desc}")
            return "\n".join(message_lines)
        else:
            option = pump_installation_options.get(pump_option_selected)
            if not option:
                return "Ndine urombo, sarudzo yamakasarudza yekuisa pombi haisi kushanda."
            desc = option.get('description', 'Hapana tsananguro')
            price = option.get('price', 'N/A')
            message = f"💧 Mutengo wesarudzo {pump_option_selected}:\n{desc}\nMutengo: ${price}\n"
            message += "\nMungadei kuita sei:\n1. Kubvunza mutengo webasa rimwe\n2. Dzokera kuMain Menu\n3. Taura mutengo wenyu"
            return message

    # Rest of the function remains the same...
    loc_data = location_pricing2.get(location_key)
    if not loc_data:
        return "Ndine urombo, hatina mitengo yenzvimbo iyi."

    price = loc_data2.get(service_key)
    if not price:
        return f"Ndine urombo, mutengo we{service_key} hauna kuwanikwa mu{location.title()}."

    # Format complex pricing dicts nicely
    if isinstance(price, dict):
        included_depth = price.get("included_depth_m", "N/A")
        extra_rate = price.get("extra_per_m", "N/A")

        classes = {k: v for k, v in price.items() if k.startswith("class")}
        message_lines = [f"Mitengo ye{service_key} mu{location.title()}:"]
        for cls, amt in classes.items():
            message_lines.append(f"- {cls.title()}: ${amt}")
        message_lines.append(f"- Inosanganisira kudzika kusvika pa{included_depth}m")
        message_lines.append(f"- Mari yekuwedzera: ${extra_rate}/m pakupfuura")
        message_lines.append("\nMungadei kuita sei:\n1. Kubvunza mutengo webasa rimwe\n2. Dzokera kuMain Menu\n3. Taura mutengo wenyu")
        return "\n".join(message_lines)

    # Flat rate or per meter pricing
    unit = "pamita imwe neimwe" if service_key in ["Commercial Hole Drilling", "Borehole Deepening"] else "mutengo wakazara"
    return (f"{service_key} mu{location.title()}: ${price} ({unit})\n\n"
            "Mungadei kuita sei:\n1. Kubvunza mutengo webasa rimwe\n2. Dzokera kuMain Menu\n3. Taura mutengo wenyu")


# State handlers
def handle_welcome2(prompt, user_data, phone_id):
    send2(
        "Mhoro! Mauya kuSpeedGo Services – nyanzvi dzekuchera chibhorani muZimbabwe. "
        "Tinopa mabasa akavimbika ekuchera chibhorani nemhinduro dzemvura munyika yese yeZimbabwe.\n\n"
        "Sarudza mutauro waunoda kushandisa:\n"
        "1. English\n"
        "2. Shona\n"
        "3. Ndebele",
        user_data['sender'], phone_id
    )
    update_user_state(user_data['sender'], {'step': 'select_language2'})
    return {'step': 'select_language2', 'sender': user_data['sender']}


def handle_select_language2(prompt, user_data, phone_id):
    user = User.from_dict(user_data.get('user', {'phone_number': user_data['sender']}))
    if prompt == "2":
        user.language = "Shona"
        update_user_state(user_data['sender'], {
            'step': 'main_menu2',
            'user': user.to_dict()
        }), ttl_seconds=3600)
        send2(
            "Tatenda!\n"
            "Tingakubatsirei nhasi?\n\n"
            "1. Kukumbira mutengo\n"
            "2. Tsvaga mutengo zvichienderana nenzvimbo\n"
            "3. Tarisa mamiriro epurojekiti\n"
            "4. Mibvunzo inowanzo bvunzwa kana kudzidza nezvekuchera chibhorani\n"
            "5. Mamwe mabasa atinoita\n"
            "6. Taura nemumiriri wedu\n\n"
            "Pindura nenhamba (semuenzaniso: 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        user.language = "Shona"
        update_user_state(user_data['sender'], {
            'step': 'main_menu2',
            'user': user.to_dict()
        })
        send2(
            "Tatenda!\n"
            "Tingakubatsirei sei nhasi?\n\n"
            "1. Kukumbira quotation\n"
            "2. Tsvaga mutengo zvichienderana nenzvimbo\n"
            "3. Tarisa mamiriro epurojekiti\n"
            "4. Mibvunzo inowanzo bvunzwa kana kudzidza nezvekuchera chibhorani\n"
            "5. Mamwe mabasa atinoita\n"
            "6. Taura nemumiriri\n\n"
            "Pindura nenhamba (semuenzaniso: 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":
        user.language = "Ndebele"
        update_user_state(user_data['sender'], {
            'step': 'main_menu3',
            'user': user.to_dict()
        })
        send2(
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
        send2("Ndapota sarudza mutauro wakakodzera (1 English, 2 Shona, 3 Ndebele).", user_data['sender'], phone_id)
        return {'step': 'select_language2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_main_menu2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":  # Kukumbira quotation
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote2',
            'user': user.to_dict()
        })
        send2("Ndapota nyora nzvimbo yako (Guta/Kanzuru kana GPS coordinates) kuti titange.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Tsvaga Mutengo Uchishandisa Nzvimbo
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote2',
            'user': user.to_dict()
        })
        send2(
            "Kuti tikuratidze mutengo, ndapota nyora nzvimbo yako (Guta/Kanzuru kana GPS coordinates):",
            user_data['sender'], phone_id
        )
        return {'step': 'enter_location_for_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Tarisa Mamiriro ePurojekiti
        update_user_state(user_data['sender'], {
            'step': 'check_project_status_menu2',
            'user': user.to_dict()
        })
        send2(
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
        send2(
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
        send2(
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
        send2("Tiri kukubatanidza nemumiriri...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send2("Ndapota sarudza sarudzo iripo (1 kusvika 6).", user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}


def human_agent2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    customer_number = user_data['sender']
    customer_name = user.name if hasattr(user, "name") and user.name else "Asingazivikanwe"
    agent_number = "+263719835124"

    # Notify the customer immediately
    send2(
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
    send2(agent_message, agent_number, phone_id)

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
    send2(agent_message, agent_number, phone_id)


def send_fallback_option2(customer_number, phone_id):
    # Check if still waiting
    user_data = get_user_state(customer_number)
    if user_data and user_data.get('step') == 'waiting_for_human_agent_response2':
        send2("Kana zvikatadza kubatana, unogona kutifonera pa +263719835124", customer_number, phone_id)
        send2("Ungade kuita sei:\n1. Dzokera ku main menu\n2. Pedzisa hurukuro", customer_number, phone_id)
        update_user_state(customer_number, {
            'step': 'human_agent_followup2',
            'user': user_data.get('user', {}),
            'sender': customer_number
        })


def send_fallback_option2(customer_number, phone_id):
    # Check if user is still waiting
    user_data = get_user_state(customer_number)
    if user_data.get('step') == 'waiting_for_human_agent_response2':
        send2(
            "Kana zvikatadza, unogonawo kutitumira meseji kana kutifonera pa +263719835124.",
            customer_number, phone_id
        )
        send2(
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
            send2(
                "Kana zvikatadza, unogonawo kutitumira meseji kana kutifonera pa +263719835124.",
                customer_number, phone_id
            )
            send2(
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
            send2("Kudzosera kumenyu huru...", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'main_menu2',
                'user': user_data['user'],
                'sender': customer_number
            })
            send_main_menu(customer_number, phone_id)
            return {'step': 'main_menu2', 'user': user_data['user'], 'sender': customer_number}

        elif message.strip() == '2':  # User says No
            send2("Tatenda! Ivai nezuva rakanaka.", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'end',
                'user': user_data['user'],
                'sender': customer_number
            })
            return {'step': 'end', 'user': user_data['user'], 'sender': customer_number}

        else:
            send2("Ndapota pindura ne 1 kuti zvinge zviri 'Ehe' kana 2 kuti zvinge zviri 'Kwete'.", customer_number, phone_id)
            return user_data


def human_agent_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        return handle_select_language2("1", user_data, phone_id)

    elif prompt == "2":
        send2("Zvakanaka. Inzwa wakasununguka kubvunza kana paine chaunoda rubatsiro nacho.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send2("Ndapota pindura ne 1 kuti udzokere ku menyu huru kana 2 kuti urambe uri pano.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_menu2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user']) 

    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole2',
            'user': user.to_dict()
        })
        send2(
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
        send2(
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
        send2(
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
        send2("Ndapota chimbomira ndichikubatanidza nemumiriri wedu...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Back to Main Menu
        return handle_select_language2("1", user_data, phone_id)

    else:
        send2("Ndapota sarudza chisarudzo chiri pakati pe 1 kusvika ku 5.", user_data['sender'], phone_id)
        return {'step': 'faq_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}


def custom_question2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if not prompt.strip():
        send2("Ndapota nyora mubvunzo wako.", user_data['sender'], phone_id)
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

    send2(answer, user_data['sender'], phone_id)

    send2(
        "Ungade:\n"
        "1. Kubvunza rimwe mubvunzo\n"
        "2. Kudzokera ku Menyu Huru",
        user_data['sender'], phone_id
    )

    return {'step': 'custom_question_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


def custom_question_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send2("Ndapota nyora mubvunzo wako unotevera.", user_data['sender'], phone_id)
        return {'step': 'custom_question2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language2("1", user_data, phone_id)

    else:
        send2("Ndapota pindura ne 1 kuti ubvunze imwe mibvunzo kana 2 kuti udzokere kuMain Menu.", user_data['sender'], phone_id)
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
        send2(responses[prompt], user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

        send2(
            "Ungada:\n"
            "1. Kubvunza imwe mibvunzo yeBorehole Drilling FAQs\n"
            "2. Kudzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send2("Ndapota sarudza chisarudzo chiri pakati pe 1 kusvika ku 8.", user_data['sender'], phone_id)
        return {'step': 'faq_borehole2', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_borehole_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send2(
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
        return handle_select_language2("1", user_data, phone_id)

    else:
        send2("Ndapota sarudza 1 kuti ubvunze imwe mibvunzo kana 2 kudzokera kuMain Menu.", user_data['sender'], phone_id)
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
        send2(responses[prompt], user_data['sender'], phone_id)

        if prompt == "6":
            return {'step': 'faq_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}

        send2(
            "Ungada:\n"
            "1. Kubvunza imwe mibvunzo yePump Installation FAQs\n"
            "2. Kudzokera kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send2("Ndapota sarudza chisarudzo chiri pakati pe 1 kusvika ku 6.", user_data['sender'], phone_id)
        return {'step': 'faq_pump2', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump_followup2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send2(
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
        return handle_select_language2("1", user_data, phone_id)

    else:
        send2("Ndapota sarudza 1 kuti ubvunze imwe mibvunzo kana 2 kudzokera kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_enter_location_for_quote2(prompt, user_data, phone_id):
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
                'step': 'select_service_quote2',
                'user': user.to_dict()
            })
            send2(
                f"Nzvimbo yawanikwa: {location_name.title()}\n\n"
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
            send2("Hatina kukwanisa kuona nzvimbo yenyu. Ndapota nyora zita reguta/kanzvimbo nemaoko.", user_data['sender'], phone_id)
            return {'step': 'enter_location_for_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        location_name = prompt.strip()
        user.quote_data['location'] = location_name.lower()
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote2',
            'user': user.to_dict()
        })
        send2(
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
        send2(
            "Kuti tikukwanisire mutengo wenguva pfupi, ndapota pindura zvinotevera:\n\n"
            "1. Nzvimbo yenyu (Guta/Kanzvimbo kana GPS):",
            user_data['sender'], phone_id
        )
        return {'step': 'handle_select_service_quote2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send2("Ndapota sarudza sevhisi yakakodzera (1-5).", user_data['sender'], phone_id)
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
        send2(
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
        send2("Ndapota nyora ruzivo rwese rwakumbirwa (anenge mitsara mina).", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_quote_response2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Offer price
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details2',
            'user': user.to_dict()
        })
        send2(
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
        send2(
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
        send2("Mumiriri wedu achakubata kuti apedze kurongwa kwekuchera borehole.", user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":  # Human Agent
        send2("Tiri kukubatanidza nemumiriri munhu...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send2("Ndapota sarudza sarudzo yakakodzera (1-4).", user_data['sender'], phone_id)
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
    send2(
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
        send2(
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
        send2("Tiri kukuendesa kumumiriri wemunhu...", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details2',
            'user': user.to_dict()
        })
        send2(
            "Ndapota pindura nekunyora chipo chako chachinjwa mukutevedzana kwe:\n\n"
            "- Kuongorora Mvura: $_\n"
            "- Kuchera Mvura: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send2("Ndapota sarudza sarudzo iripo (1-3).", user_data['sender'], phone_id)
        return {'step': 'offer_response2', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_details2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Kuronga Kuongorora Nzvimbo
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info2',
            'user': user.to_dict()
        })
        send2(
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
        send2("Ndapota bata hofisi yedu pa0719835124 kuti uronge kubhadhara mari yekuchengetedza.", user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Kusimbisa Zuva Rekuchera Mvura
        send2("Mumiriri wedu achakubata kuti asimbise zuva rekuchera mvura.", user_data['sender'], phone_id)
        return {'step': 'main_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send2("Ndapota sarudza sarudzo iripo (1-3).", user_data['sender'], phone_id)
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
        send2(
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
        send2("Ndapota nyora 'Submit' kuti usimbise kurongwa kwako.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_confirmation2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "2":  # No reschedule needed
        send2(
            "Zvakanaka! Ruzivo rwenyu rwekukorobha borehole rwabhuka.\n\n"
            "Zuva: China, 23 Chivabvu 2025\n"
            "Nguva Yekutanga: 8:00 AM\n"
            "Nguva Inotarisirwa: maawa 5\n"
            "Chikwata: Vashandi 4-5\n\n"
            "Iva nechokwadi chekuti nzvimbo yacho iri nyore kusvika",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome2', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send2("Ndokumbira utaure nevanhu vanobatsira kuti uchinje zuva.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_select_service_quote2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    
    if not location:
        send2("Ndokumbira utaure nzvimbo yako kutanga usati wasarudza sevhisi.", user_data['sender'], phone_id)
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
        send2("Sarudzo isiriyo. Ndokumbira upindure ne1, 2, 3, 4 kana 5 kusarudza sevhisi.", user_data['sender'], phone_id)
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
        send2("\n".join(message_lines), user_data['sender'], phone_id)
        return {'step': 'select_pump_option2', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Get pricing for other services
    pricing_message = get_pricing_for_location_quotes(location, selected_service)
    
    # Ask if user wants to return to main menu or choose another service
    update_user_state(user_data['sender'], {
        'step': 'quote_followup2',
        'user': user.to_dict()
    })
    send2(pricing_message, user_data['sender'], phone_id)

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
        send2(
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
        send2(
            "Chii chiri dambudziko neborehole yako?\n"
            "1. Borehole yakawira pasi\n"
            "2. Mvura yakasviba borehole",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'borehole_flushing_problem2', 'user': user.to_dict()})
        return {'step': 'borehole_flushing_problem2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "3":
        # PVC casing class selection
        send2(
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
        send2("Ndokumbira usarudze sarudzo yakakodzera (1-4).", user_data['sender'], phone_id)
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
    send2(menu_text, phone_number, phone_id)
    

def handle_borehole_deepening_casing2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Only at top, qualifies for deepening
        send2("Bhuroka rako rinokodzera kuwedzerwa kudzika.\nNdapota nyora nzvimbo yako (guta, ward, growth point, kana GPS pin):",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'deepening_location2', 'user': user.to_dict()})
        return {'step': 'deepening_location2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        # Top to bottom with smaller pipe - no deepening
        send2(
            "Zvinosuruvarisa, maburoka ane pombi diki kupfuura 180mm kubva kumusoro kusvika pasi haagoni kuwedzerwa kudzika.\n"
            "Sarudzo:\n"
            "1. Dzokera kuMamwe Mabasa\n"
            "2. Taura neRutsigiro",
            user_data['sender'], phone_id
        )
        update_user_state(user_data['sender'], {'step': 'deepening_no_deepening_options2', 'user': user.to_dict()})
        return {'step': 'deepening_no_deepening_options2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send2("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'borehole_deepening_casing2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_no_deepening_options2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Back to Other Services menu
        return handle_other_services_menu2("0", user_data, phone_id)  # or send menu prompt directly

    elif choice == "2":
        send2("Tiri kukubatanidza nerutsigiro...", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'human_agent2', 'user': user.to_dict()})
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send2("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_no_deepening_options2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_deepening_location2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()

    # Save location for deepening request
    user.quote_data['location'] = location

    # Fetch pricing from backend (you must implement this function)
    price = get_pricing_for_location_quotes(location, "borehole_deepening")

    send2(
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
        send2("Ndapota nyora zita rako rizere:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name2', 'user': user.to_dict()})
        return {'step': 'booking_full_name2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        # Back to other services menu
        return other_services_menu2("0", user_data, phone_id)

    else:
        send2("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'deepening_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_borehole_flushing_problem2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    choice = prompt.strip()

    if choice == "1":
        # Collapsed Borehole
        send2(
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
        send2("Ndapota nyora nzvimbo yako kuti titarise mutengo:", user_data['sender'], phone_id)
        user.quote_data['flushing_type'] = 'dirty_water'
        update_user_state(user_data['sender'], {'step': 'flushing_location2', 'user': user.to_dict()})
        return {'step': 'flushing_location2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send2("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
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
        send2("Ndapota sarudza sarudzo yakakodzera (1-3).", user_data['sender'], phone_id)
        return {'step': 'flushing_collapsed_diameter2', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['flushing_type'] = 'collapsed'
    user.quote_data['diameter'] = diameter

    if diameter == "180mm_or_larger":
        send2("Tinogona kugezesa borehole yako tichishandisa madziro ane drilling bit (zvinobudirira zvikuru).\nNdapota nyora nzvimbo yako kuti tione mutengo:",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'flushing_location2', 'user': user.to_dict()})
        return {'step': 'flushing_location2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif diameter == "between_140_and_180mm":
        send2("Tinogona kugezesa borehole tichishandisa madziro, pasina drilling bit.\nNdapota nyora nzvimbo yako kuti tione mutengo:",
             user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'flushing_location2', 'user': user.to_dict()})
        return {'step': 'flushing_location2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif diameter == "140mm_or_smaller":
        send2("Tinogona kugezesa borehole tichishandisa madziro chete (pasina drilling bit).\nNdapota nyora nzvimbo yako kuti tione mutengo:",
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

    send2(
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
        send2("Ndapota nyora zita rako rizere:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name2', 'user': user.to_dict()})
        return {'step': 'booking_full_name2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu2("0", user_data, phone_id)

    else:
        send2("Ndapota sarudza sarudzo yakakodzera (1 kana 2).", user_data['sender'], phone_id)
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
        send2("Ndapota sarudza sarudzo yakakodzera (1-3).", user_data['sender'], phone_id)
        return {'step': 'pvc_casing_selection2', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['pvc_casing_class'] = casing_class

    send2(f"Mutengo we {casing_class} PVC casing unotsamira panzvimbo yako.\nNdapota nyora nzvimbo yako:",
         user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'pvc_casing_location2', 'user': user.to_dict()})
    return {'step': 'pvc_casing_location2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pvc_casing_location2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.quote_data['location'] = location

    casing_class = user.quote_data.get('pvc_casing_class')

    price = get_pricing_for_other_services(location, "pvc_casing", {'class': casing_class})

    send2(
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
        send2("Ndokumbirawo upe zita rako rizere:", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'booking_full_name2', 'user': user.to_dict()})
        return {'step': 'booking_full_name2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif choice == "2":
        return handle_other_services_menu2("0", user_data, phone_id)

    else:
        send2("Ndokumbirawo usarudze sarudzo chaiyo (1 kana 2).", user_data['sender'], phone_id)
        return {'step': 'pvc_casing_booking_confirm2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_full_name2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    full_name = prompt.strip()
    user.booking_data['full_name'] = full_name
    send2("Ndokumbirawo upe nhamba yako yefoni:", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_phone2', 'user': user.to_dict()})
    return {'step': 'booking_phone2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_phon2e(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    phone = prompt.strip()
    user.booking_data['phone'] = phone
    send2("Ndokumbirawo nyora nzvimbo yako chaiyo/kero kana kuti tumira GPS pin yako:", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_location2', 'user': user.to_dict()})
    return {'step': 'booking_location2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_location2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.booking_data['location'] = location
    send2("Ndokumbirawo nyora zuva raunoda kusungira basa (semuenzaniso, 2024-10-15):", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_date2', 'user': user.to_dict()})
    return {'step': 'booking_date2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_date2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    booking_date = prompt.strip()
    user.booking_data['date'] = booking_date
    send2("Kana uine zvimwe zvinyorwa kana zvikumbiro, nyora zvino. Kana usina, nyora 'Kwete':", user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'booking_notes2', 'user': user.to_dict()})
    return {'step': 'booking_notes2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_notes2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    notes = prompt.strip()
    user.booking_data['notes'] = notes if notes.lower() != 'no' else ''
    
    # At this point, save booking to database or call booking API
    booking_confirmation_number = save_booking(user.booking_data)  # You must implement save_booking

    send2(
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
        send2(
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

    send2("Tinotenda. Ndapota mirira apo tiri kutora ruzivo nezve chimiro cheprojekiti yako...", user_data['sender'], phone_id)

    send2(
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
        send2(
            "Zvakanaka! Iwe zvino uchagamuchira zviziviso paWhatsApp pese paanochinja chimiro chekuvaka borehole yako.\n\n"
            "Tinotenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    elif response in ['no', 'n', 'kwete']:
        send2(
            "Hazvina basa. Unogona kugara uchitarisa chimiro zvakare kana zvichidikanwa.\n\n"
            "Tinotenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    else:
        send2("Ndine urombo, handina kunzwisisa. Ndokumbirawo upindure neEhe kana Kwete.", user_data['sender'], phone_id)
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
        send2(
            "Zvakanaka! Iwe zvino unozogamuchira WhatsApp zvinovandudzwa pese panoshanduka mamiriro ekuchera borehole yako.\n\n"
            "Tatenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    elif response in ['no', 'n']:
        send2(
            "Hazvina mhosva. Unogona kugara uchiongorora mamiriro zvakare gare gare kana zvichidikanwa.\n\n"
            "Tatenda nekushandisa sevhisi yedu.",
            user_data['sender'], phone_id
        )
    else:
        send2("Ndine urombo, handina kunzwisisa. Ndokumbira upindure neEhe kana Kwete.", user_data['sender'], phone_id)
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

        send2(
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
        send2(
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
        send2("Ndokumbira mirira ndichakubatanidza kune mumwe wevashandi vedu vekutsigira.", user_data['sender'], phone_id)
        return {'step': 'human_agent2', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        return handle_main_menu2("", user_data, phone_id)

    else:
        send2("Sarudzo isiriyo. Ndokumbira usarudze 1, 2, 3, kana 4.", user_data['sender'], phone_id)
        return {'step': 'check_project_status_menu2', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_drilling_status_info_request2(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send2(
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

    send2("Tatenda. Ndokumbira mirira tichitsvaga mamiriro eprojekiti yako...", user_data['sender'], phone_id)

    send2(
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
        send2("Sarudzo isiriyo. Ndokumbira usarudze sarudzo yemhando yepombi yekuisa (1-6).", user_data['sender'], phone_id)
        return {'step': 'select_pump_option2', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    user.quote_data['pump_option'] = prompt.strip()
    
    pricing_message = get_pricing_for_location_quotes(location, "Pump Installation", prompt.strip())
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup2',
        'user': user.to_dict()
    })
    send2(pricing_message, user_data['sender'], phone_id)
    
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
        send2(
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
        send2(
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
        send2(
            "Zvakanaka! Unogona kugovera mutengo waunofunga pazasi.\n\n",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details2', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send2("Sarudzo isiriyo. Pindura 1 kuti ubvunze nezveshumiro imwe, 2 kudzokera kumenu huru, kana 3 kana uchida kupa mutengo.", user_data['sender'], phone_id)
        return {'step': 'quote_followup2', 'user': user.to_dict(), 'sender': user_data['sender']}


# Action mapping
action_mapping = {
    "welcome2": handle_welcome2,
    "select_language2": handle_select_language2,
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
        send2("Maneja anoona nezvevatengi achakufonera munguva pfupi.", user_data['sender'], phone_id)
        or {'step': 'main_menu2', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
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
                    send2("Ndapota tumira meseji yakanyorwa kana kugovera nzvimbo yako uchishandisa bhatani 📍.", sender, phone_id)

        except Exception as e:
            logging.error(f"Error processing webhook: {e}", exc_info=True)

        return jsonify({"status": "ok"}), 200

def message_handler2(prompt, sender, phone_id, message):
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
    step = user_data.get('step', 'welcome2')
    next_state = get_action(step, prompt, user_data, phone_id)
    update_user_state(sender, next_state)

def get_action2(current_state, prompt, user_data, phone_id):
    handler = action_mapping.get(current_state, handle_welcome2)
    return handler(prompt, user_data, phone_id)


shona_blueprint = Blueprint('shona', __name__)

@shona_blueprint.route('/message', methods=['POST'])
def shona_message_handler():
    data = request.get_json()
    message = data.get('message')
    sender = data.get('sender')
    phone_id = data.get('phone_id')
    message_handler(message, sender, phone_id, {'type': 'text', 'text': {'body': message}})
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(debug=True, port=8000)

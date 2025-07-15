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
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
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

def update_user_state(phone_number, updates):
    updates['phone_number'] = phone_number
    if 'sender' not in updates:
        updates['sender'] = phone_number
    redis.set(phone_number, json.dumps(updates))

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
            'step': 'main_menu3',
            'user': user.to_dict()
        })
        send(
            "Thank you!\n"
            "How can we help you today?\n\n"
            "1. Request a quote\n"
            "2. Search Price Using Location\n"
            "3. Check Project Status\n"
            "4. FAQs or Learn About Borehole Drilling\n"        
            "5. Talk to a Human Agent\n\n"
            "Please reply with a number (e.g., 1)",
            user_data['sender'], phone_id
        )

        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please reply 1 to continue in English.", user_data['sender'], phone_id)
        return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_main_menu3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Request a quote
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote3',
            'user': user.to_dict()
        })
        send("Sicela ufake indawo yakho ukuze siqale.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Search Price Using Location
        update_user_state(user_data['sender'], {
            'step': 'get_pricing_for_location3',
            'user': user.to_dict()
        })
        send(
           "Ukuze sikunike intengo, sicela ufake indawo yakho (Idolobho/Ikhodi ye-GPS):",
            user_data['sender'], phone_id
        )
        return {'step': 'get_pricing_for_location3', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "3":  # Check Project Status
        update_user_state(user_data['sender'], {
            'step': 'check_project_status_menu3',
            'user': user.to_dict()
        })
        send(
            "Sicela ukhethe inketho:\n"
            "1. Hlola isimo sokugwetywa kwamanzi\n"
            "2. Hlola isimo sokufakelwa kwepomp\n"
            "3. Khuluma lomuntu osebenzayo\n"
            "4. Imenyu enkulu",
            user_data['sender'], phone_id
        )
        return {'step': 'check_project_status_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        update_user_state(user_data['sender'], {
            'step': 'faq_menu3',
            'user': user.to_dict()
        })
        send(
            "Sicela ukhethe isigaba se-FAQ:\n\n"
            "1. Imibuzo evame ukubuzwa nge-Borehole Drilling\n"
            "2. Imibuzo evame ukubuzwa nge-Pump Installation\n"
            "3. Buza omunye umbuzo\n"
            "4. Khuluma lomuntu osebenzayo\n"
            "5. Imenyu enkulu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'select_service3',
            'user': user.to_dict()
        })
        send("Siyaxhumanisa nawe lomunye wabasebenzi bethu...", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        send("Sicela ukhethe inketho evumelekileyo (1-5).", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_check_project_status_menu3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'drilling_status_info_request3',
            'user': user.to_dict()
        })
    
        send(
            "Ukuze uhlolisisise isimo sokugwetywa kwamanzi, sicela unikeze imininingwane elandelayo:\n\n"
            "- Ibizo lakho eliphelele elasetshenziswa ngesikhathi sokubhuka\n"
            "- Inombolo yesithenjwa yephrojekthi noma Inombolo yefoni\n"
            "- Indawo yokugwetywa (ongakukhetha)",
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
            "Ukuze uhlolisisise isimo sokufakelwa kwepomp, sicela unikeze imininingwane elandelayo:\n\n"
            "- Ibizo lakho eliphelele elasetshenziswa ngesikhathi sokubhuka\n"
            "- Inombolo yesithenjwa yephrojekthi noma Inombolo yefoni\n"
            "- Indawo yokufakelwa (ongakukhetha)",
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
        send("Sicela ulinde ngenkathi sixhumanisa nawe nomunye wabasebenzi bethu bokusekela.", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        return handle_main_menu3("", user_data, phone_id)

    else:
        send("Inketho engalunganga. Sicela ukhethe 1, 2, 3, noma 4.", user_data['sender'], phone_id)
        return {'step': 'check_project_status_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_drilling_status_info_request3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Sicela unikeze okungenani igama lakho eligcweleyo kanye lenombolo yereferensi noma inombolo yefoni, ngayinye ilandelayo umugqa omutsha.\n\n"
            "Umzekeliso:\n"
            "John Dube\nREF789123 noma 0779876543\nOngakukhetha: Bulawayo",
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

    user.project_status_request = {
        'type': 'drilling',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Siyabonga. Sicela ulinde sizama ukuthola ulwazi ngephrojekthi yakho...", user_data['sender'], phone_id)

    send(
        f"Nansi inhlolovo yephrojekthi yakho yokubhoboza umthombo wamanzi:\n\n"
        f"Igama lephrojekthi: Borehole - {full_name}\n"
        f"Isigaba samanje: Ukuqhubeka kwebhobholo\n"
        f"Isinyathelo esilandelayo: Ukufaka casing\n"
        f"Usuku olulindelwe lokuqeda: 10/06/2025\n\n"
        "Ungathanda ukuthola izibuyekezo ku-WhatsApp uma isimo sephrojekthi siguquka?\nKhetha: Yebo / Hatshi",
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


def handle_pump_status_info_request3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

    if len(lines) < 2:
        send(
            "Sicela unikeze okungenani igama lakho eligcweleyo kanye lenombolo yereferensi noma inombolo yefoni, ngayinye ilandelayo umugqa omutsha.\n\n"
            "Umzekeliso:\n"
            "Jane Dube\nREF123456\nOngakukhetha: Harare",
            user_data['sender'], phone_id
        )
        return {
            'step': 'pump_status_info_request3',
            'user': user.to_dict(),
            'sender': user_data['sender']
        }

    full_name = lines[0]
    reference = lines[1]
    location = lines[2] if len(lines) >= 3 else "Akukhonjwanga"

    user.project_status_request = {
        'type': 'pump',
        'full_name': full_name,
        'reference': reference,
        'location': location
    }

    send("Siyabonga. Sicela ulinde sizama ukuthola ulwazi lwephrojekthi yakho...", user_data['sender'], phone_id)

    send(
        f"Nansi inhlolovo yephrojekthi yakho yokufakwa kwepompo:\n\n"
        f"Igama lephrojekthi: Pump - {full_name}\n"
        f"Isigaba samanje: Ukufakwa sekuqediwe\n"
        f"Isinyathelo esilandelayo: Ukuhlolwa kokugcina\n"
        f"Usuku olulindelwe lokunikezwa: 12/06/2025\n\n"
        "Ungathanda ukuthola izibuyekezo ku-WhatsApp uma isimo siguquka?\nKhetha: Yebo / Hatshi",
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

    if response in ['yes', 'y', 'yebo']:
        send(
            "Kuhle kakhulu! Uzathola izibuyekezo ku-WhatsApp nxa isimo sephrojekthi yakho yokufaka ipompo siguquka.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    elif response in ['no', 'n', 'hatshi']:
        send(
            "Kulungile. Ungabuza njalo isimo sephrojekthi yakho ngesikhathi esilandelayo.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    else:
        send("Uxolo, asikuzwisisanga. Sicela uphendule ngo *Yebo* kumbe *Hatshi*.", user_data['sender'], phone_id)
        return {'step': 'pump_status_updates_opt_in3', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}



def handle_drilling_status_updates_opt_in3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()

    if response in ['yes', 'y']:
        send(
            "Kuhle! Uzaziswa ngeWhatsApp nxa isimo seprojekthi yakho yokugwaza umthombo sishintsha.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    elif response in ['no', 'n']:
        send(
            "Kulungile. Ungahlola isimo sakho futhi ngesikhathi esizayo nxa kudingeka.\n\n"
            "Siyabonga ngokusebenzisa insiza yethu.",
            user_data['sender'], phone_id
        )
    else:
        send("Uxolo, angizwanga kahle. Ngicela uphendule ngo *Yebo* kumbe *Hatshi*.", user_data['sender'], phone_id)
        return {'step': 'drilling_status_updates_opt_in3', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {
        'step': None,
        'user': user.to_dict()
    })

    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_enter_location_for_quote3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    user.quote_data['location'] = prompt.strip().lower()

    update_user_state(user_data['sender'], {
        'step': 'select_service_quote3',
        'user': user.to_dict()
    })

    send(
        "Siyabonga! Khathesi khetha insiza ofunayo:\n"
        "1. Ukuhlolwa kwamanzi (Water survey)\n"
        "2. Ukugwazwa komthombo (Borehole drilling)\n"
        "3. Ukufakelwa kwepampu (Pump installation)\n"
        "4. Ukugwazwa komthombo wokuthengisa (Commercial hole drilling)\n"
        "5. Ukwenyuselwa kwamanzi kumthombo (Borehole Deepening)",
        user_data['sender'], phone_id
    )

    return {'step': 'select_service_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}


def human_agent3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    customer_number = user_data['sender']
    customer_name = user.name if hasattr(user, "name") and user.name else "Unknown"
    agent_number = "+263719835124"

    send(
        "Siyabonga. Ngicela ulinde ngikuxhumanise loMmeli weSpeedGo...",
        customer_number, phone_id
    )

    agent_message = (
        f"👋 Umthengi ufuna ukukhuluma lawe kuWhatsApp.\n\n"
        f"📱 Inombolo yomthengi: {customer_number}\n"
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


def handle_user_message3(message, user_data, phone_id):
    state = user_data.get('step')
    customer_number = user_data['sender']

    if state == 'waiting_for_human_agent_response3':
        prompt_time = user_data.get('agent_prompt_time', 0)
        elapsed = time.time() - prompt_time

        if elapsed >= 10:
            send(
                "Nxa ufuna, ungathumela umlayezo kumbe usifonele ku +263719835124.",
                customer_number, phone_id
            )
            send(
                "Ufuna ukubuyela kuMain Menu?\n1. Yebo\n2. Hatshi",
                customer_number, phone_id
            )

            update_user_state(customer_number, {
                'step': 'human_agent_followup3',
                'user': user_data['user'],
                'sender': customer_number
            })

            return {'step': 'human_agent_followup3', 'user': user_data['user'], 'sender': customer_number}
        else:
            return user_data  # still waiting

    elif state == 'human_agent_followup3':
        if message.strip() == '1':
            send("Ngiyabuyisela kuMain Menu...", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'main_menu3',
                'user': user_data['user'],
                'sender': customer_number
            })
            send_main_menu3(customer_number, phone_id)
            return {'step': 'main_menu3', 'user': user_data['user'], 'sender': customer_number}

        elif message.strip() == '2':
            send("Siyabonga! Ube losuku oluhle.", customer_number, phone_id)
            update_user_state(customer_number, {
                'step': 'end3',
                'user': user_data['user'],
                'sender': customer_number
            })
            return {'step': 'end3', 'user': user_data['user'], 'sender': customer_number}
        else:
            send("Ngicela uphendule ngo 1 ku *Yebo* kumbe 2 ku *Hatshi*.", customer_number, phone_id)
            return user_data


def human_agent_followup3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        return handle_select_language("1", user_data, phone_id)

    elif prompt == "2":
        send("Kulungile. Zizwe ukhululekile ukubuza nxa udinga olunye usizo.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ngicela uphendule ngo 1 ukuze ubuyele kuMain Menu kumbe 2 ukuze uhlale lapha.", user_data['sender'], phone_id)
        return {'step': 'human_agent_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_menu3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user']) 

    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole3',
            'user': user.to_dict()
        })
        send(
            "Nansi imibuzo evame ukubuzwa mayelana lokugwazwa komthombo:\n\n"
            "1. Kubiza malini ukugwaza umthombo?\n"
            "2. Kudinga isikhathi esingakanani ukugwaza umthombo?\n"
            "3. Umthombo wami uzabe unjani ubude?\n"
            "4. Ngidinga imvumo yini ukugwaza umthombo?\n"
            "5. Lingawenzi ndawonye yini ukuhlola amanzi lokugwaza?\n"
            "6. Kwenzenjani nxa sihlola kodwa singatholi amanzi?\n"
            "7. Lisisebenzisa siphi isixhobo?\n"
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
            "Nansi imibuzo evamileyo mayelana lokufakwa kwepampu:\n\n"
            "1. Kuyini ukuhlukana kwepampu yeSolar lepampu yagesi?\n"
            "2. Lingafaka yini nxa sengilazo izinto?\n"
            "3. Kudinga isikhathi esingakanani ukufaka ipampu?\n"
            "4. Ngidinga ipampu enjani ngobukhulu?\n"
            "5. Liyanikela ngezinqolobane zamanzi lama-stand?\n"
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
            "Ngicela ubhale umbuzo wakho ngezansi, sizazama ukukusiza.\n",
            user_data['sender'], phone_id
        )
        return {'step': 'custom_question3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent3',
            'user': user.to_dict(),
            'sender': user_data['sender']
        })
        send("Ngicela ulinde ngikuxhumanise loMmeli...", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Back to Main Menu
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Ngicela ukhethe inketho evumelekileyo (1–5).", user_data['sender'], phone_id)
        return {'step': 'faq_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}


def custom_question3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    # Qinisekisa ukuthi umbuzo awulambuleki
    if not prompt.strip():
        send("Ngiyacela bhala umbuzo wakho.", user_data['sender'], phone_id)
        return {'step': 'custom_question3', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Gemini prompt template
    system_prompt = (
        "You are a helpful assistant for SpeedGo, a borehole drilling and pump installation company in Zimbabwe. "
        "You will only answer questions related to SpeedGo's services, pricing, processes, or customer support. "
        "If the user's question is unrelated to SpeedGo, politely let them know that you can only assist with SpeedGo-related topics."
    )

    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content([system_prompt, prompt])

        answer = response.text.strip() if hasattr(response, "text") else "Ngiyaxolisa, angikwazi ukupha impendulo khathesi."

    except Exception as e:
        answer = "Uxolo, kube lodubo ekucubunguleni umbuzo wakho. Zama njalo futhi ngemva kwesikhatshana."
        print(f"[Gemini error] {e}")

    send(answer, user_data['sender'], phone_id)

    # Follow up options
    send(
        "Ungathanda ukwenza lokhu:\n"
        "1. Buza omunye umbuzo\n"
        "2. Buyela kuMain Menu",
        user_data['sender'], phone_id
    )

    return {'step': 'custom_question_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}


def custom_question_followup3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send("Ngiyacela bhala umbuzo wakho olandelayo.", user_data['sender'], phone_id)
        return {'step': 'custom_question3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Ngiyacela uphendule ngo 1 ukubhala omunye umbuzo noma 2 ukubuyela kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'custom_question_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_borehole3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Intengo ixhomeke endaweni okuyo, ukujula, lehlobo lomhlabathi. Sicela usithumele indawo yakho kanye lolwazi lokungena endaweni ukuze sikunikeze ikhotheshini.",
        "2": "Ngokuvamile kuthatha amahora angu-4–6 kumbe izinsuku ezimbalwa, kuye ngezimo zendawo, uhlobo lwamatshe kanye lokungena kalula.",
        "3": "Ukujula kwe-borehole kwehluka ngokwendawo. Okujwayelekileyo yiku 40 metres, kodwa kungafika ku 150 metres kuye nge-water table.",
        "4": "Kwezinye izindawo, kudingeka imvumo yamanzi. Singakusiza ukuyifaka uma kudingeka.",
        "5": "Yebo, sinikeza zombili njengephakeji elihlangene kumbe ngokwahlukeneyo, kuye ngokuthanda kwakho.",
        "6": "Uma iklayenti lifuna ukumba kwenye indawo, sinikeza isaphulelo.\n\nQaphela: Amathuluzi e-survey athola ama-fracture aphathelane lamanzi aphansi komhlaba, kodwa awalinganisi ivolumu noma ukugeleza kwamanzi. Ngakho-ke, ukumba i-borehole akusikuphi isiqiniseko sokuthola amanzi.",
        "7": "Sisebenzisa imishini yokumba ephakeme, ama-GPS tools kanye lamathuluzi e-geological survey.",
        "8": "Sibuyela kuFAQ Menu..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Ungathanda:\n"
            "1. Buza omunye umbuzo kuBorehole Drilling FAQs\n"
            "2. Buyela kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ngiyacela ukhethe inketho evumelekileyo (1–8).", user_data['sender'], phone_id)
        return {'step': 'faq_borehole3', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_borehole_followup3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send(
            "Ngiyacela khetha umbuzo:\n\n"
            "1. Kubiza malini ukumba i-borehole?\n"
            "2. Kuthatha isikhathi esingakanani ukumba i-borehole?\n"
            "3. I-borehole yami izakujula kangakanani?\n"
            "4. Ngidinga imvumo yini ukuze ngimbe i-borehole?\n"
            "5. Liyenza yini i-survey lamanzi ngesikhathi sokumba?\n"
            "6. Kwenzakalani nxa i-survey yamanzi ingatholi amanzi?\n"
            "7. Lisebenzisa miphi imishini?\n"
            "8. Buyela kuFAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_borehole3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Ngiyacela khetha 1 ukuze ubuze omunye umbuzo kumbe 2 ukuze ubuyele kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    responses = {
        "1": "Ama-solar pump asebenzisa amandla avela kuma-solar panel, afanelekile ezindaweni ezikude ezingelalugesi. Ama-electric pump asebenzisa ugesi futhi avame ukuba angabizi ekuqaleni kodwa axhomeke ekutholakaleni kukagesi.",
        "2": "Yebo! Sinikeza iphakheji yokufaka kuphela uma usulalezinto ezidingakalayo.",
        "3": "Ukufakwa kwepompo kuvamise ukuthatha usuku olulodwa uma izinto sezilungile futhi indawo ifinyeleleka kahle.",
        "4": "Usayizi wepompo uxhomeke ekudingeni kwakho kwamanzi lokujula kwe-borehole. Singabheka indawo yakho sikweluleke ngeyona engcono.",
        "5": "Yebo, sinikeza ama-package aphelele afaka amathangi amanzi, ama-tank stands kanye lamafitting adingakalayo.",
        "6": "Sibuyela kuFAQ Menu..."
    }

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)

        if prompt == "6":
            return {'step': 'faq_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(
            "Ungathanda:\n"
            "1. Buza omunye umbuzo kuPump Installation FAQs\n"
            "2. Buyela kuMain Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send("Ngiyacela khetha inketho evumelekileyo (1–6).", user_data['sender'], phone_id)
        return {'step': 'faq_pump3', 'user': user.to_dict(), 'sender': user_data['sender']}


def faq_pump_followup3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt == "1":
        send(
            "Ngiyacela khetha umbuzo:\n\n"
            "1. Kuyini umehluko phakathi kwe-solar le-electric pumps?\n"
            "2. Lingafaka yini uma sengilezinto zonke?\n"
            "3. Kuthatha isikhathi esingakanani ukufaka i-pump?\n"
            "4. Ngidinga usayizi bani we-pump?\n"
            "5. Liyanikezani amathangi lamanqamu?\n"
            "6. Buyela kuFAQ Menu",
            user_data['sender'], phone_id
        )
        return {'step': 'faq_pump3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)

    else:
        send("Ngiyacela khetha 1 ukuze ubuze omunye umbuzo kumbe 2 ukuze ubuyele kuMain Menu.", user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_select_service3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    services = {
        "1": "Ukuhlola amanzi",
        "2": "Ukumba i-borehole",
        "3": "Ukufaka ipompo",
        "4": "Ukumba emabhizinisini",
        "5": "Ukujula kwe-borehole",
    }
    if prompt in services:
        user.quote_data['service'] = services[prompt]
        update_user_state(user_data['sender'], {
            'step': 'collect_quote_details3',
            'user': user.to_dict()
        })
        send(
            "Ukuze sikunikeze intengo esheshayo, ngiyacela uphendule imibuzo elandelayo:\n\n"
            "1. Indawo yakho (idolobha/lilokhu use GPS):\n",
            user_data['sender'], phone_id
        )
        return {'step': 'handle_select_service_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ngiyacela ukhethe insiza evumelekileyo (1-5).", user_data['sender'], phone_id)
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
            'casing_type': responses[5].strip() if len(responses) > 5 else "Akucaciswanga"
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
            'step': 'quote_response3',
            'user': user.to_dict()
        })
        estimate = "Ikilasi 6: Intengo Elinganisiwe: $2500\nIfaka ukumba, i-PVC casing engu-140mm"
        send(
            f"Siyabonga! Ngokusekelwe kulwazi lwakho:\n\n"
            f"{estimate}\n\n"
            f"Qaphela: Izindleko zokufaka amacasing amabili zikhokhelwa ngokwengeziwe uma kudingeka, futhi ngemvume yeklayenti\n\n"
            f"Ungathanda ukwenza okulandelayo:\n"
            f"1. Ukunikela intengo yakho?\n"
            f"2. Ukuhlela ukuhlolwa kwesiza\n"
            f"3. Ukuhlela ukumba\n"
            f"4. Ukukhuluma lomuntu oqeqeshiweyo",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_response3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ngiyacela unikeze yonke imininingwane efunwayo (okungenani imigqa emine).", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_quote_response3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Offer price
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details3',
            'user': user.to_dict()
        })
        send(
            "Kulungile! Ungabelana ngamanani owaphakamisayo ngezansi.\n\n"
            "Ngiyacela uphendule ngenani lakho ngendlela elandelayo:\n\n"
            "- Ukuhlola Amanzi: $_\n"
            "- Ukumba i-Borehole: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":  # Book site survey
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info3',
            'user': user.to_dict()
        })
        send(
            "Kuhle! Ngiyacela unikeze imininingwane elandelayo ukuze uqedele ukubhukha kwakho:\n\n"
            "- Igama Eligcwele:\n"
            "- Usuku Olukhethiweyo (dd/mm/yyyy):\n"
            "- Ikheli Lesiza: GPS noma ikheli\n"
            "- Inombolo Yeselula:\n"
            "- Indlela Yokukhokha (Ukukhokha kuqala / Imali esizeni):\n\n"
            "Thayipha: Thumela",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Book for a Drilling
        send("Ummeleli wethu uzokuthinta ukuze uqedele ukubhukha kokumba.", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":  # Human Agent
        send("Sikuxhumanisa nomuntu oqeqeshiweyo manje...", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ngiyacela ukhethe inketho evumelekile (1-4).", user_data['sender'], phone_id)
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
        "Isicelo sakho sithunyelwe kumphathi wethu wezokuthengisa. Sizophendula kungakapheli ihora eli-1.\n\n"
        "Siyabonga ngenani lakho!\n\n"
        "Ithimba lethu lizolicubungula futhi liphendule maduzane.\n\n"
        "Nakuba sizama ukuba namanani afikelelekayo, amanani ethu akhombisa ikhwalithi, ukuphepha, kanye nokuthembeka.\n\n"
        "Ungathanda ukwenza okulandelayo:\n"
        "1. Qhubeka uma inani lakho lamukelwe\n"
        "2. Khuluma nomuntu\n"
        "3. Buyekeza inani lakho",
        user_data['sender'], phone_id
    )
    return {'step': 'offer_response3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_offer_response3(prompt, user_data, phone_id):
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
            'step': 'booking_details3',
            'user': user.to_dict()
        })
        send(
            "Izindaba ezimnandi! Inani lakho lamukelwe.\n\n"
            "Masibone isinyathelo sakho esilandelayo.\n\n"
            "Ungathanda:\n"
            "1. Ukubhukha Ukuhlola Isiza\n"
            "2. Ukukhokha Idiphozi\n"
            "3. Ukuqinisekisa Usuku Lokumba",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_details3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Sikuxhumanisa nomuntu oqeqeshiweyo manje...", user_data['sender'], phone_id)
        return {'step': 'human_agent3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details3',
            'user': user.to_dict()
        })
        send(
            "Ngiyacela uphendule ngenani olilungisile ngendlela elandelayo:\n\n"
            "- Ukuhlola Amanzi: $_\n"
            "- Ukumba i-Borehole: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ngiyacela ukhethe inketho efaneleyo (1-3).", user_data['sender'], phone_id)
        return {'step': 'offer_response3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_details3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":  # Book site survey
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info3',
            'user': user.to_dict()
        })
        send(
            "Kuhle! Ngiyacela unikeze imininingwane elandelayo ukuze uqedele ukubhukha kwakho:\n\n"
            "- Igama Eligcwele:\n"
            "- Usuku Olukhethiweyo (dd/mm/yyyy):\n"
            "- Ikheli Lesiza: GPS noma ikheli\n"
            "- Inombolo Yeselula:\n"
            "- Indlela Yokukhokha (Ukukhokha kuqala / Imali esizeni):\n\n"
            "Thayipha: Thumela",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":  # Pay Deposit
        send("Ngiyacela uxhumane nehhovisi lethu ku-077xxxxxxx ukuze uhlele ukukhokha idiphozi.", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Confirm Drilling Date
        send("Ummeleli wethu uzokuthinta ukuqinisekisa usuku lokumba.", user_data['sender'], phone_id)
        return {'step': 'main_menu3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ngiyacela ukhethe inketho efaneleyo (1-3).", user_data['sender'], phone_id)
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
            "Ngiyabonga. Ukuhlela kwakho sekugunyazwe, futhi uchwepheshe uzokuthinta maduze.\n\n"
            f"Isikhumbuzo: Ukuhlolwa kwesiza kwakho kuhlelwe kusasa.\n\n"
            f"Usuku: {booking_date}\n"
            f"Isikhathi: {booking_time}\n\n"
            "Silindele ukusebenza nawe!\n"
            "Ufuna ukushintsha isikhathi? Phendula\n\n"
            "1. Yebo\n"
            "2. Cha",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_confirmation3', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ngiyacela thayipha 'Thumela' ukuze uqinisekise ukubhukha kwakho.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info3', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_booking_confirmation3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "2":  # Akudingi ukushintshwa kwesikhathi
        send(
            "Kuhle! Ukuhlela kwakho kokumba i-borehole sekubhukhiwe.\n\n"
            "Usuku: Lwesine, 23 Meyi 2025\n"
            "Isikhathi sokuqala: 8:00 AM\n"
            "Isikhathi esilindelekile: amahora ama-5\n"
            "Iqembu: Ochwepheshe abayisi-4 kuya kwezi-5\n\n"
            "Qinisekisa ukuthi kukhona indlela yokungena esizeni",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ngiyacela uxhumane nethimba lethu lokusekela ukuze ushintshe isikhathi.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation3', 'user': user.to_dict(), 'sender': user_data['sender']}


location_pricing = {
    "bulawayo": {
        "Ukuhlola Amanzi": 150,
        "Ukumba i-Borehole": {
            "iklasi 6": 1000,
            "iklasi 9": 1125,
            "iklasi 10": 1250,
            "ubude obufakiwe_m": 40,
            "okungeziwe_ngayinye_m": 25
        },
        "Ukufakwa kwePompo": 0,
        "Ukumba Imigodi Yezentengiso": 80,
        "Ukujulisa i-Borehole": 30
    },
    "harare": {
        "Ukuhlola Amanzi": 150,
        "Ukumba i-Borehole": {
            "iklasi 6": 2000,
            "iklasi 9": 2300,
            "iklasi 10": 2800,
            "ubude obufakiwe_m": 40,
            "okungeziwe_ngayinye_m": 30
        },
        "Ukufakwa kwePompo": 0,
        "Ukumba Imigodi Yezentengiso": 80,
        "Ukujulisa i-Borehole": 30
    },
}


def calculate_borehole_drilling_price3(location, drilling_class, actual_depth_m):
    drilling_info = location_pricing[location]["Borehole Drilling"]
    base_price = drilling_info[drilling_class]
    included_depth = drilling_info["included_depth_m"]
    extra_per_m = drilling_info["extra_per_m"]

    if actual_depth_m <= included_depth:
        return base_price

    extra_depth = actual_depth_m - included_depth
    extra_cost = extra_depth * extra_per_m
    return base_price + extra_cost



def normalize_location3(location_text):
    return location_text.strip().lower()


def get_pricing_for_location3(location_input):
    location = normalize_location(location_input)
    services = location_pricing.get(location)

    if not services:
        return "Uxolo, asinawo amanani asemthethweni endaweni yakho okwamanje."

    pricing_lines = [f"{service}: {price}" for service, price in services.items()]
    return "Lawa ngamaxabiso endawo yakho:\n" + "\n".join(pricing_lines)


def handle_get_pricing_for_location3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    # Normalize and fetch pricing info
    pricing_message = get_pricing_for_location3(prompt)

    # Save the user's location
    user.quote_data['location'] = prompt

    # Update state (you can change next step as needed)
    update_user_state(user_data['sender'], {
        'step': 'collect_booking_info3',  
        'user': user.to_dict()
    })

    # Send pricing message to user
    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'collect_booking_info3',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def get_pricing_for_location_quotes3(location_input, service_name):
    location = normalize_location(location_input)
    services = location_pricing.get(location)

    if not services:
        return f"Uxolo, asinawo amanani e-{location.title()} okwamanje."

    service_name = service_name.strip().lower()

    for service, price in services.items():
        if service.lower() == service_name:
            if isinstance(price, dict):  # Handle Borehole Drilling (nested)
                class_6 = price.get("iklasi 6", "Ayikho")
                class_9 = price.get("iklasi 9", "Ayikho")
                class_10 = price.get("iklasi 10", "Ayikho")
                included_depth = price.get("ubude obufakiwe_m", "Ayikho")
                extra_per_m = price.get("okungeziwe_ngayinye_m", "Ayikho")
                return (
                    f"IXabiso le-{service} e-{location.title()}:\n"
                    f"- Iklasi 6: ${class_6}\n"
                    f"- Iklasi 9: ${class_9}\n"
                    f"- Iklasi 10: ${class_10}\n"
                    f"- Kubandakanya ubude obufika ku-{included_depth}m\n"
                    f"- Intlawulo eyongezelelweyo: ${extra_per_m}/m ngaphezu kobude obufakiwe"
                )
            else:  # Flat price service
                return f"Ixabiso le-{service} e-{location.title()} lingu-${price}."

    return f"Uxolo, asinawo amanani e '{service_name}' e-{location.title()}."


def handle_get_pricing_for_location_quotes3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')
    service = prompt.strip()

    if not location:
        send("Ngiyacela, unginike indawo yakho kuqala ngaphambi kokukhetha insiza.", user_data['sender'], phone_id)
        return user_data

    pricing_message = get_pricing_for_location_quotes3(location, service)
    user.quote_data['service'] = service

    update_user_state(user_data['sender'], {
        'step': 'collect_booking_info3',
        'user': user.to_dict()
    })

    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'collect_booking_info3',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_select_service_quote3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = user.quote_data.get('location')

    if not location:
        send("Ngiyacela, unginike indawo yakho kuqala ngaphambi kokukhetha insiza.", user_data['sender'], phone_id)
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
        send("Inketho ongayikhetha ayisebenzi. Sicela uphendule ngo 1, 2, 3, 4 noma 5 ukukhetha insiza.", user_data['sender'], phone_id)
        return user_data

    # Store selected service
    user.quote_data['service'] = selected_service

    # Get pricing
    pricing_message = get_pricing_for_location_quotes3(location, selected_service)

    # Ask if user wants to return to main menu or choose another service
    followup_message = (
        f"{pricing_message}\n\n"
        "Ungathanda ukwenzenjani:\n"
        "1. Buza amanani ngeminye insiza\n"
        "2. Buyela kwimenyu enkulu"
    )

    # Update user state to expect follow-up choice
    update_user_state(user_data['sender'], {
        'step': 'quote_followup3',
        'user': user.to_dict()
    })

    send(followup_message, user_data['sender'], phone_id)

    return {
        'step': 'quote_followup3',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_quote_followup3(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])

    if prompt.strip() == "1":
        # Stay in quote flow, show services again
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote3',
            'user': user.to_dict()
        })
        send(
            "Khetha enye insiza:\n"
            "1. Ukuhlola amanzi\n"
            "2. Ukumba umgodi wamanzi\n"
            "3. Ukufaka ipompo\n"
            "4. Ukumba umgodi wezentengiso\n"
            "5. Ukwandisa umgodi wamanzi",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service_quote3', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt.strip() == "2":
        # Go back to main menu
        update_user_state(user_data['sender'], {
            'step': 'main_menu3',
            'user': user.to_dict()
        })
        return handle_select_language("0", user_data, phone_id)

    else:
        send(
            "Inketho ongayikhetha ayisebenzi. Phendula ngo 1 ukuze ubuze ngenye insiza noma ngo 2 ukubuyela kwimenyu enkulu.",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_followup3', 'user': user.to_dict(), 'sender': user_data['sender']}



def get_action3(current_state, prompt, user_data, phone_id):
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

   
    if text in ["sawubona", "heyi", "salibonani"]:
        user_state = {'step': 'handle_welcome', 'sender': sender}
        updated_state = get_action('handle_welcome', prompt, user_state, phone_id)
        update_user_state(sender, updated_state)
        return updated_state  # return something or None


    user_state = get_user_state(sender)
    user_state['sender'] = sender    
    next_state = get_action(user_state['step'], prompt, user_state, phone_id)
    update_user_state(sender, next_state)

    
    
# Action mapping
action_mapping = {
    "welcome3": handle_welcome3,
    "select_language3": handle_select_language3,
    "main_menu3": handle_main_menu3,
    "enter_location_for_quote3": handle_enter_location_for_quote3,  
    "select_service_quote3": handle_select_service_quote3, 
    "select_service3": handle_select_service3,
    "get_pricing_for_location3": handle_get_pricing_for_location3,
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
    "human_agent_followup3": human_agent_followup3,   
    "human_agent3": lambda prompt, user_data, phone_id: (
        send("A human agent will contact you soon.", user_data['sender'], phone_id)
        or {'step': 'main_menu3', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
    ),
}

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

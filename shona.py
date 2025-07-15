import os
import json
import logging
import requests
import random
import string
from datetime import datetime
from upstash_redis import Redis

logging.basicConfig(level=logging.INFO)

wa_token = os.environ.get("WA_TOKEN")
phone_id = os.environ.get("PHONE_ID")
redis = Redis(
    url=os.environ["UPSTASH_REDIS_REST_URL"],
    token=os.environ["UPSTASH_REDIS_REST_TOKEN"]
)

class User:
    def __init__(self, phone_number):
        self.phone_number = phone_number
        self.language = "Shona"
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
        user.language = data.get("language", "Shona")
        user.quote_data = data.get("quote_data", {})
        user.booking_data = data.get("booking_data", {})
        user.offer_data = data.get("offer_data", {})
        return user

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


def handle_select_language(prompt, user_data, phone_id):
    user = User.from_dict(user_data.get('user', {'phone_number': user_data['sender']}))
    if prompt == "2":
        user.language = "Shona"
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(
            "Tatenda!\n"
            "Tinokubatsirai sei nhasi?\n\n"
            "1. Kukumbira quotation\n"
            "2. Bhuka Site Visit\n"
            "3. Tarisa Project Status\n"
            "4. Dzidza nezve Kuchera Bhodhoro\n"
            "5. Taura neMunhu\n\n"
            "Pindura nenhamba (semuenzaniso, 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota pindura ne1 kuti urambe uchishandisa chiShona.", user_data['sender'], phone_id)
        return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_main_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'select_service',
            'user': user.to_dict()
        })
        send(
            "Tatenda!\n"
            "Sarudza sevhisi yaunoda:\n"
            "1. Kuchera bhodhoro\n"
            "2. Kuisa pombi yebhodhoro\n"
            "3. Kuvaka pond yemvura\n"
            "4. Kuvaka weir dam",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info',
            'user': user.to_dict()
        })
        send(
            "Kubhuka site visit, ndapota ipa zvinotevera:\n"
            "- Zita rizere:\n"
            "- Zuva raunoda (dd/mm/yyyy):\n"
            "- Kero yesaiti:\n"
            "- Nhamba yefoni:\n"
            "- Nzira yekubhadhara (Prepayment / Cash paSaiti):\n\n"
            "Nyora 'Submit' kuti usimbise booking.",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("Chikamu ichi chichauya munguva pfupi. Bata agent yenyu kuti muwane mamiriro epurojekiti.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":
        send(
            "Tinopa:\n"
            "- Kuchera bhodhoro\n"
            "- Kuisa pombi yebhodhoro\n"
            "- Kuvaka pond nemadhamu eWeir\n"
            "Bata isu kuti uwane ruzivo rwakadzama!", user_data['sender'], phone_id
        )
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "5":
        send("Tiri kukubatanidza neagent chaiye...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sarudzo iri pakati pa1-5.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_select_service(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    services = {
        "1": "Kuchera bhodhoro",
        "2": "Kuisa pombi yebhodhoro",
        "3": "Kuvaka pond yemvura",
        "4": "Kuvaka weir dam"
    }
    if prompt in services:
        user.quote_data['service'] = services[prompt]
        update_user_state(user_data['sender'], {
            'step': 'collect_quote_details',
            'user': user.to_dict()
        })
        send(
            "Kuti tikupai mutengo, tapota pindurai izvi:\n\n"
            "1. Nzvimbo yenyu (guta/kero kana GPS):\n"
            "2. Kudzika kwamunoda (kana muchiziva):\n"
            "3. Chinangwa (Kumba / Kurima / Factory):\n"
            "4. Makaita water survey here? (Ehe kana Kwete)\n"
            "5. Kana muchida deepening, nyorai 'Deepening'\n"
            "6. PVC pipe casing: Class 6, Class 9 kana Class 10\n\n"
            "Pindurai mumutsara woga woga.",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_quote_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sevhisi pakati pa1-4.", user_data['sender'], phone_id)
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
            'casing_type': responses[5].strip() if len(responses) > 5 else "Hazvataurwa"
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
            'step': 'quote_response',
            'user': user.to_dict()
        })
        estimate = "Class 6: Mutengo Unofungidzirwa: $2500\nZvinobatanidza kuchera, PVC casing 140mm"
        send(
            f"Tatenda! Zvichienderana nezvamakapa:\n\n"
            f"{estimate}\n\n"
            f"Ziva: Double casing inobhadharwa semari yekuwedzera kana zvichidikanwa uye pakubvumirana nemutengi\n\n"
            f"Mungada:\n"
            f"1. Kupa mutengo wenyu?\n"
            f"2. Bhuka Site Survey\n"
            f"3. Bhuka Kuchera\n"
            f"4. Taura ne Munhu",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_response', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota ipa ruzivo rwese rwakumbirwa (kanokwana 4 lines).", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_quote_response(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Nyorai mutengo wenyu muchitevedza fomati:\n\n"
            "- Water Survey: $_\n"
            "- Kuchera Bhodhoro: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Ipa ruzivo urwu kuti booking yako ipedzwe:\n\n"
            "- Zita rizere:\n"
            "- Zuva raunoda (dd/mm/yyyy):\n"
            "- Kero yesaiti kana GPS\n"
            "- Nhamba yefoni:\n"
            "- Nzira yekubhadhara (Prepayment / Cash paSaiti):\n\n"
            "Nyora: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("Agent wedu achakubata kubvumirana kuchera.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":
        send("Tiri kukubatanidza neagent chaiye...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sarudzo pakati pa1-4.", user_data['sender'], phone_id)
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
        "Chikumbiro chako chatumirwa kune maneja wedu. Tichakupindura muawa rimwe.\n\n"
        "Tatenda nemutengo wawakapa!\n\n"
        "Chikwata chedu chichachiongorora nokukupindura.\n\n"
        "Sevhisi yedu inotora mutengo wakakodzera, mhando, uye kuchengetedzeka.\n\n"
        "Mungada:\n"
        "1. Kupfuurira kana mutengo wabvumirwa\n"
        "2. Taura neMunhu\n"
        "3. Chinja mutengo",
        user_data['sender'], phone_id
    )
    return {'step': 'offer_response', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_offer_response(prompt, user_data, phone_id):
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
            'step': 'booking_details',
            'user': user.to_dict()
        })
        send(
            "Nhau dzakanaka! Mutengo wawakapa wabvumirwa.\n\n"
            "Chikamu chinotevera ndechekusimbisa:\n\n"
            "1. Bhuka Site Survey\n"
            "2. Bhadhara deposit\n"
            "3. Simbisa zuva rekuchera",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Tiri kukubatanidza neagent chaiye...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details',
            'user': user.to_dict()
        })
        send(
            "Nyorai zvakare mutengo wenyu muchitevedza fomati:\n\n"
            "- Water Survey: $_\n"
            "- Kuchera Bhodhoro: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza sarudzo pakati pa1-3.", user_data['sender'], phone_id)
        return {'step': 'offer_response', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_details(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info',
            'user': user.to_dict()
        })
        send(
            "Zvakanaka! Ipa ruzivo urwu kuti booking yako ipedzwe:\n\n"
            "- Zita rizere:\n"
            "- Zuva raunoda (dd/mm/yyyy):\n"
            "- Kero yesaiti kana GPS\n"
            "- Nhamba yefoni:\n"
            "- Nzira yekubhadhara (Prepayment / Cash paSaiti):\n\n"
            "Nyora: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Bata hofisi yedu pa 077xxxxxxx kuti muronge kubhadhara deposit.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("Agent wedu achakubata kusimbisa zuva rekuchera.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota sarudza pakati pa1-3.", user_data['sender'], phone_id)
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
            "Tatenda. Bhuku rako ratambirwa, technician achakufonera munguva pfupi.\n\n"
            f"Chiyeuchidzo: Site survey yako yakarongwa mangwana.\n\n"
            f"Zuva: {booking_date}\n"
            f"Nguva: {booking_time}\n\n"
            "Tinotarisira kushanda nemi!\n"
            "Unoda kuchinja here? Pindura\n\n"
            "1. Ehe\n"
            "2. Kwete",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_confirmation', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Ndapota nyora 'Submit' kuti usimbise booking yako.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_confirmation(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "2":
        send(
            "Zvakanaka! Bhuku rako rekuchera bhodhoro raitwa.\n\n"
            "Zuva: China, 23 Chivabvu 2025\n"
            "Nguva: 8:00 AM\n"
            "Inotora: 5hrs\n"
            "Chikwata: 4-5 Matekiniki\n\n"
            "Iva nechokwadi chekuti nzvimbo inowanikwa.",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Bata support yedu kuti uchinje zuva.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation', 'user': user.to_dict(), 'sender': user_data['sender']}

action_mapping = {
    "main_menu": handle_main_menu,
    "select_service": handle_select_service,
    "collect_quote_details": handle_collect_quote_details,
    "quote_response": handle_quote_response,
    "collect_offer_details": handle_collect_offer_details,
    "offer_response": handle_offer_response,
    "booking_details": handle_booking_details,
    "collect_booking_info": handle_collect_booking_info,
    "booking_confirmation": handle_booking_confirmation,
    "human_agent": lambda prompt, user_data, phone_id: (
        send("Agent chaiye achakubata munguva pfupi.", user_data['sender'], phone_id)
        or {'step': 'main_menu', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
    ),
}

def get_action(current_state, prompt, user_data, phone_id):
    handler = action_mapping.get(current_state, handle_main_menu)
    return handler(prompt, user_data, phone_id)

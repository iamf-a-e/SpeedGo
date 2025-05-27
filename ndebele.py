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
        user.language = data.get("language", "Ndebele")
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
    if prompt == "3":
        user.language = "Ndebele"
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(
            "Siyabonga!\n"
            "Singakusiza njani lamuhla?\n\n"
            "1. Cela ikhotheshini\n"
            "2. Bhuka Uvakatjho Lwendawo\n"
            "3. Hlola Isimo Sephrojekthi\n"
            "4. Funda Ngokucubungula Amanzi\n"
            "5. Khuluma Lomuntu\n\n"
            "Phendula ngenombolo (umzekeliso: 1)",
            user_data['sender'], phone_id
        )
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela uphendule ngo-1 ukuqhubeka ngesiNdebele.", user_data['sender'], phone_id)
        return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_main_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'select_service',
            'user': user.to_dict()
        })
        send(
            "Siyabonga!\n"
            "Khetha insiza oyidingayo:\n"
            "1. Ukucubungula amanzi (borehole drilling)\n"
            "2. Ukufakwa kwepompi yeborehole\n"
            "3. Ukwakhiwa kwepond yamanzi\n"
            "4. Ukwakhiwa kweweir dam",
            user_data['sender'], phone_id
        )
        return {'step': 'select_service', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info',
            'user': user.to_dict()
        })
        send(
            "Ukuze ubhuke uvakatjho, sicela unikeze okulandelayo:\n"
            "- Igama eliphelele:\n"
            "- Usuku olufisayo (dd/mm/yyyy):\n"
            "- Ikheli lendawo:\n"
            "- Inombolo yocingo:\n"
            "- Indlela yokukhokha (Prepayment / Imali endaweni):\n\n"
            "Bhala 'Submit' ukuqinisekisa ukubhuka.",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("Lesi sici sizafika maduzane. Xhumana ne-agent yakho ukuthola isimo sephrojekthi.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":
        send(
            "Sinikeza:\n"
            "- Ukucubungula amanzi\n"
            "- Ukufakwa kwepompi yeborehole\n"
            "- Ukwakhiwa kwepond kanye leweir dam\n"
            "Xhumana nathi ukuthola ulwazi oluthe xaxa!", user_data['sender'], phone_id
        )
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "5":
        send("Sizakuxhumanisa lomuntu okwamanje...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ukhethe inketho phakathi kuka-1-5.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_select_service(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    services = {
        "1": "Ukucubungula amanzi",
        "2": "Ukufakwa kwepompi yeborehole",
        "3": "Ukwakhiwa kwepond yamanzi",
        "4": "Ukwakhiwa kweweir dam"
    }
    if prompt in services:
        user.quote_data['service'] = services[prompt]
        update_user_state(user_data['sender'], {
            'step': 'collect_quote_details',
            'user': user.to_dict()
        })
        send(
            "Ukuze sikunikeze inani eliqondileyo, phendula okulandelayo:\n\n"
            "1. Indawo okuyo (Idolobho/Ikheli noma GPS):\n"
            "2. Ukujula okudingayo (uma wazi):\n"
            "3. Inhloso (Ekhaya / Ezolimo / Ezimbonini):\n"
            "4. Sewenze ucwaningo lwamanzi? (Yebo noma Cha)\n"
            "5. Uma udinga ukujula (deepening), bhala 'Deepening'\n"
            "6. PVC pipe casing: Class 6, Class 9 noma Class 10\n\n"
            "Phendula ngamunye emgqeni wayo.",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_quote_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ukhethe insiza phakathi kuka-1-4.", user_data['sender'], phone_id)
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
            'casing_type': responses[5].strip() if len(responses) > 5 else "Akutshiwanga"
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
        estimate = "Class 6: Inani elilinganisiwe: $2500\nKufaka ukucubungula, PVC casing 140mm"
        send(
            f"Siyabonga! Ngokusekelwe kulwazi olunikiweyo:\n\n"
            f"{estimate}\n\n"
            f"Qaphela: Izindleko ze-double casing zikhokhelwa njengenani elengezelelweyo uma kudingeka, ngemvumo yeklayenti\n\n"
            f"Ungathanda:\n"
            f"1. Ukunikeza inani lakho?\n"
            f"2. Bhuka iSite Survey\n"
            f"3. Bhuka Ukucubungula\n"
            f"4. Khuluma lomuntu",
            user_data['sender'], phone_id
        )
        return {'step': 'quote_response', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela unikeze lonke ulwazi oluceliwe (okungenani imigqa emi-4).", user_data['sender'], phone_id)
        return {'step': 'collect_quote_details', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_quote_response(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details',
            'user': user.to_dict()
        })
        send(
            "Kulungile! Bhala inani lakho ngendlela elandelayo:\n\n"
            "- Ucwaningo lwamanzi: $_\n"
            "- Ukucubungula amanzi: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info',
            'user': user.to_dict()
        })
        send(
            "Kulungile! Nikeza ulwazi olulandelayo ukuqedela ukubhuka:\n\n"
            "- Igama eliphelele:\n"
            "- Usuku olufisayo (dd/mm/yyyy):\n"
            "- Ikheli lendawo noma GPS\n"
            "- Inombolo yocingo:\n"
            "- Indlela yokukhokha (Prepayment / Imali endaweni):\n\n"
            "Bhala: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("I-agent yethu izokuthinta ukuqedela ukubhuka kokucubungula.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":
        send("Sizakuxhumanisa lomuntu okwamanje...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ukhethe inketho phakathi kuka-1-4.", user_data['sender'], phone_id)
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
        "Isicelo sakho sithunyelwe kumphathi wethu wezokuthengisa. Sizakuphendula kungakapheli ihora.\n\n"
        "Siyabonga ngenani lakho!\n\n"
        "Iqembu lethu lizalihlola likuphendule maduze.\n\n"
        "Amanani ethu asekelwe kwikhwalithi, ukuphepha, lokwethembeka.\n\n"
        "Ungathanda:\n"
        "1. Qhubeka uma inani lamukelwe\n"
        "2. Khuluma lomuntu\n"
        "3. Lungisa inani lakho",
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
            "Izindaba ezinhle! Inani lakho lamukelwe.\n\n"
            "Ake siqinisekise okuzolandela:\n\n"
            "1. Bhuka iSite Survey\n"
            "2. Khokha idiphozithi\n"
            "3. Qinisekisa usuku lokucubungula",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Sizakuxhumanisa lomuntu okwamanje...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        update_user_state(user_data['sender'], {
            'step': 'collect_offer_details',
            'user': user.to_dict()
        })
        send(
            "Bhala kabusha inani lakho ngendlela elandelayo:\n\n"
            "- Ucwaningo lwamanzi: $_\n"
            "- Ukucubungula amanzi: $_",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_offer_details', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela uphendule phakathi kuka-1-3.", user_data['sender'], phone_id)
        return {'step': 'offer_response', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_details(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "1":
        update_user_state(user_data['sender'], {
            'step': 'collect_booking_info',
            'user': user.to_dict()
        })
        send(
            "Kulungile! Nikeza ulwazi oludingekayo ukuqedela ukubhuka:\n\n"
            "- Igama eliphelele:\n"
            "- Usuku olufisayo (dd/mm/yyyy):\n"
            "- Ikheli lendawo noma GPS\n"
            "- Inombolo yocingo:\n"
            "- Indlela yokukhokha (Prepayment / Imali endaweni):\n\n"
            "Bhala: Submit",
            user_data['sender'], phone_id
        )
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        send("Xhumana lehhovisi lethu ku-077xxxxxxx ukuze ukhokhe idiphozithi.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":
        send("I-agent yethu izakuthinta ukuqinisekisa usuku lokucubungula.", user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Sicela ukhethe phakathi kuka-1-3.", user_data['sender'], phone_id)
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
            "Siyabonga. Ukubhuka kwakho kugunyaziwe, uchwepheshe uzokuthinta maduze.\n\n"
            f"Isikhumbuzo: Ukuhlolwa kwendawo kuhlelwe kusasa.\n\n"
            f"Usuku: {booking_date}\n"
            f"Isikhathi: {booking_time}\n\n"
            "Sibheke phambili ukusebenza lawe!\n"
            "Udinga ukuhlela kabusha? Phendula\n\n"
            "1. Yebo\n"
            "2. Cha",
            user_data['sender'], phone_id
        )
        return {'step': 'booking_confirmation', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Bhala 'Submit' ukuqinisekisa ukubhuka kwakho.", user_data['sender'], phone_id)
        return {'step': 'collect_booking_info', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_booking_confirmation(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    if prompt == "2":
        send(
            "Kuhle! Ukubhuka kwakho kokucubungula amanzi sekulungisiwe.\n\n"
            "Usuku: ULwesine, 23 May 2025\n"
            "Isikhathi: 8:00 AM\n"
            "Kulindeleke kuthathe: amahora ama-5\n"
            "Iqembu: 4-5 Ochwepheshe\n\n"
            "Qinisekisa ukuthi indawo iyatholakala.",
            user_data['sender'], phone_id
        )
        return {'step': 'welcome', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Xhumana nethimba lethu ukuze uhlele kabusha usuku.", user_data['sender'], phone_id)
        return {'step': 'booking_confirmation', 'user': user.to_dict(), 'sender': user_data['sender']}

action_mapping = {
    "welcome": handle_welcome,
    "select_language": handle_select_language,
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
        send("Umuntu uzokuthinta maduze.", user_data['sender'], phone_id)
        or {'step': 'main_menu', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
    ),
}

def get_action(current_state, prompt, user_data, phone_id):
    handler = action_mapping.get(current_state, handle_welcome)
    return handler(prompt, user_data, phone_id)

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

# Configure logging
logging.basicConfig(level=logging.INFO)

class SpeedGoWhatsAppBot:
    def __init__(self):
        # Initialize environment variables
        self.wa_token = os.environ.get("WA_TOKEN")
        self.phone_id = os.environ.get("PHONE_ID")
        self.gen_api = os.environ.get("GEN_API")
        self.owner_phone = os.environ.get("OWNER_PHONE")
        self.GOOGLE_MAPS_API_KEY = "AlzaSyCXDMMhg7FzP|ElKmrlkv1TqtD3HgHwW50"
        
        # Initialize Redis
        self.redis = Redis(
            url=os.environ["UPSTASH_REDIS_REST_URL"],
            token=os.environ["UPSTASH_REDIS_REST_TOKEN"]
        )
        
        # Initialize pricing data
        self.location_pricing = self._initialize_location_pricing()
        self.pump_installation_options = self._initialize_pump_options()
        
        # Initialize action mapping
        self.action_mapping = self._initialize_action_mapping()
        
        # Initialize Flask app
        self.app = Flask(__name__)
        self._setup_routes()
        
        # Configure Google Gemini
        if self.gen_api:
            genai.configure(api_key=self.gen_api)

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

    def _initialize_location_pricing(self):
        return {
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
            # ... (other locations with same structure)
        }

    def _initialize_pump_options(self):
        return {
            "1": {
                "description": "D.C solar (inoshanda nezuva chete, hapana inverter) - Ndine tangi netangi stand",
                "price": 1640
            },
            # ... (other pump options)
        }

    def _initialize_action_mapping(self):
        return {
            "welcome": self.handle_welcome,
            "select_language": self.handle_select_language,
            "main_menu2": self.handle_main_menu2,
            "enter_location_for_quote2": self.handle_enter_location_for_quote2,
            # ... (all other action mappings)
        }

    def _setup_routes(self):
        @self.app.route("/", methods=["GET", "POST"])
        def index():
            return render_template("connected.html")

        @self.app.route("/webhook", methods=["GET", "POST"])
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
                            self.message_handler(prompt, sender, phone_id, message)
                        
                        elif msg_type == "location":
                            gps_coords = f"{message['location']['latitude']},{message['location']['longitude']}"
                            logging.info(f"Location from {sender}: {gps_coords}")
                            self.message_handler(gps_coords, sender, phone_id, message)

                        else:
                            logging.warning(f"Unsupported message type: {msg_type}")
                            self.send("Please send a text message or share your location using the 📍 button.", sender, phone_id)

                except Exception as e:
                    logging.error(f"Error processing webhook: {e}", exc_info=True)

                return jsonify({"status": "ok"}), 200

    # Core bot functionality methods
    def get_user_state(self, phone_number):
        state = self.redis.get(phone_number)
        if state is None:
            return {"step": "welcome", "sender": phone_number}
        if isinstance(state, str):
            return json.loads(state)
        return state

    def update_user_state(self, phone_number, updates, ttl_seconds=60):
        updates['phone_number'] = phone_number
        if 'sender' not in updates:
            updates['sender'] = phone_number
        self.redis.set(phone_number, json.dumps(updates), ex=ttl_seconds)

    def send(self, answer, sender, phone_id):
        url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
        headers = {
            'Authorization': f'Bearer {self.wa_token}',
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

    def reverse_geocode_location(self, gps_coords):
        """Converts GPS coordinates to a city using local logic or Google Maps API"""
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
        # ... (other location checks)
        
        # Google Maps API fallback
        url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lng}&key={self.GOOGLE_MAPS_API_KEY}"
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

    def get_pricing_for_location_quotes(self, location, service_type, pump_option_selected=None):
        location_key = location.strip().lower()
        service_key = service_type.strip().title()

        if service_key == "Pump Installation":
            if pump_option_selected is None:            
                message_lines = [f"💧 Zvingasarudzwa zvekuisa pombi:\n"]
                for key, option in self.pump_installation_options.items():
                    desc = option.get('description', 'Hapana tsananguro')
                    message_lines.append(f"{key}. {desc}")
                return "\n".join(message_lines)
            else:
                option = self.pump_installation_options.get(pump_option_selected)
                if not option:
                    return "Ndine urombo, sarudzo yamakasarudza yekuisa pombi haisi kushanda."
                desc = option.get('description', 'Hapana tsananguro')
                price = option.get('price', 'N/A')
                message = f"💧 Mutengo wesarudzo {pump_option_selected}:\n{desc}\nMutengo: ${price}\n"
                message += "\nMungadei kuita sei:\n1. Kubvunza mutengo webasa rimwe\n2. Dzokera kuMain Menu\n3. Taura mutengo wenyu"
                return message

        loc_data = self.location_pricing.get(location_key)
        if not loc_data:
            return "Ndine urombo, hatina mitengo yenzvimbo iyi."

        price = loc_data.get(service_key)
        if not price:
            return f"Ndine urombo, mutengo we{service_key} hauna kuwanikwa mu{location.title()}."

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

        unit = "pamita imwe neimwe" if service_key in ["Commercial Hole Drilling", "Borehole Deepening"] else "mutengo wakazara"
        return (f"{service_key} mu{location.title()}: ${price} ({unit})\n\n"
                "Mungadei kuita sei:\n1. Kubvunza mutengo webasa rimwe\n2. Dzokera kuMain Menu\n3. Taura mutengo wenyu")

    # State handlers
    def handle_welcome(self, prompt, user_data, phone_id):
        self.send(
            "Mhoro! Mauya kuSpeedGo Services – nyanzvi dzekuchera chibhorani muZimbabwe. "
            "Tinopa mabasa akavimbika ekuchera chibhorani nemhinduro dzemvura munyika yese yeZimbabwe.\n\n"
            "Sarudza mutauro waunoda kushandisa:\n"
            "1. English\n"
            "2. Shona\n"
            "3. Ndebele",
            user_data['sender'], phone_id
        )
        self.update_user_state(user_data['sender'], {'step': 'select_language'})
        return {'step': 'select_language', 'sender': user_data['sender']}

    def handle_select_language(self, prompt, user_data, phone_id):
        user = self.User.from_dict(user_data.get('user', {'phone_number': user_data['sender']}))
        if prompt == "1":
            user.language = "English"
            self.update_user_state(user_data['sender'], {
                'step': 'main_menu',
                'user': user.to_dict()
            })
            self.send(
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
            return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

        elif prompt == "2":
            user.language = "Shona"
            self.update_user_state(user_data['sender'], {
                'step': 'main_menu2',
                'user': user.to_dict()
            })
            self.send(
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
            self.update_user_state(user_data['sender'], {
                'step': 'main_menu3',
                'user': user.to_dict()
            })
            self.send(
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
            self.send("Ndapota sarudza mutauro wakakodzera (1 English, 2 Shona, 3 Ndebele).", user_data['sender'], phone_id)
            return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}

    # ... (all other handler methods)

    def message_handler(self, prompt, sender, phone_id, message):
        user_data = self.get_user_state(sender)
        user_data['sender'] = sender

        if message.get("type") == "location":
            location = message.get("location", {})
            if "latitude" in location and "longitude" in location:
                user_data["location"] = {
                    "latitude": location["latitude"],
                    "longitude": location["longitude"]
                }
                prompt = f"{location['latitude']},{location['longitude']}"
            else:
                prompt = ""

        if 'user' not in user_data:
            user_data['user'] = self.User(sender).to_dict()

        step = user_data.get('step', 'welcome')
        next_state = self.get_action(step, prompt, user_data, phone_id)
        self.update_user_state(sender, next_state)

    def get_action(self, current_state, prompt, user_data, phone_id):
        handler = self.action_mapping.get(current_state, self.handle_welcome)
        return handler(prompt, user_data, phone_id)

    def run(self, debug=True, port=8000):
        self.app.run(debug=debug, port=port)

if __name__ == "__main__":
    bot = SpeedGoWhatsAppBot()
    bot.run()

import os
import json
from upstash_redis import Redis
import requests
import random
import logging


# Upstash Redis setup
redis = Redis(
    url=os.environ["UPSTASH_REDIS_REST_URL"],
    token=os.environ["UPSTASH_REDIS_REST_TOKEN"]
)



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



def get_user_state(phone_number):
    state = redis.get(phone_number)
    if state is None:
        return {"step": "welcome", "sender": phone_number}
    if isinstance(state, bytes):
        state = state.decode("utf-8")
    return json.loads(state)


def update_user_state(phone_number, updates, ttl_seconds=3600):  # 1 hour
    updates['phone_number'] = phone_number
    if 'sender' not in updates:
        updates['sender'] = phone_number
    redis.set(phone_number, json.dumps(updates), ex=ttl_seconds)


def send_message(answer, sender, phone_id):
    wa_token = os.environ.get("WA_TOKEN")
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

def get_user_language(phone_number):
    user_data = get_user_state(phone_number)
    if user_data and 'language' in user_data:
        return user_data['language']
    return None

def set_user_language(phone_number, language):
    user_data = get_user_state(phone_number) or {}
    user_data['language'] = language
    update_user_state(phone_number, user_data)

def set_user_state(phone_number, state_data, ttl_seconds=3600):
    redis.set(phone_number, json.dumps(state_data), ex=ttl_seconds)



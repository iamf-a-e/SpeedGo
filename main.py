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
            "5. Talk to a Human Agent\n\n"
            "Please reply with a number (e.g., 1)",
            user_data['sender'], phone_id
        )

        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please reply 1 to continue in English.", user_data['sender'], phone_id)
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


    elif prompt == "5":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'select_service',
            'user': user.to_dict()
        })
        send("Connecting you to a human agent...", user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send("Please select a valid option (1-5).", user_data['sender'], phone_id)
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


    user_state = get_user_state(sender)
    user_state['sender'] = sender    
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
    "human_agent": lambda prompt, user_data, phone_id: (
        send("A human agent will contact you soon.", user_data['sender'], phone_id)
        or {'step': 'main_menu', 'user': user_data.get('user', {}), 'sender': user_data['sender']}
    ),
}



if __name__ == "__main__":
    app.run(debug=True, port=8000)

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

# Language dictionaries
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
        "invalid_option": "Please reply with 1 for Yes or 2 for No.",
        "still_waiting": "Please hold, we're still connecting you...",
        "human_agent_followup": {
            "invalid_option": "Please reply with 1 for Main Menu or 2 to stay here.",
            "stay_here": "Okay. Feel free to ask if you need anything else.",
        },
        "faq_menu": {
            "invalid_option": "Please select a valid option (1–5).",
            "borehole_faqs": (
                "Here are the most common questions about borehole drilling:\n\n"
                "1. How much does borehole drilling cost?\n"
                "2. How long does it take to drill a borehole?\n"
                "3. How deep will my borehole be?\n"
                "4. Do I need permission to drill a borehole?\n"
                "5. Do you do a water survey and drilling at the same time?\n"
                "6. What if you do a water survey and find no water?\n"
                "7. What equipment do you use?\n"
                "8. Back to FAQ Menu"
            ),
        
                "pump_faqs": (
                "Here are common questions about pump installation:\n\n"
                "1. What's the difference between solar and electric pumps?\n"
                "2. Can you install if I already have materials?\n"
                "3. How long does pump installation take?\n"
                "4. What pump size do I need?\n"
                "5. Do you supply tanks and tank stands?\n"
                "6. Back to FAQ Menu"
            ),
            "custom_question": "Please type your question below, and we'll do our best to assist you.\n",
            "connecting_agent": "Please hold while I connect you to a representative..."
        },
            "custom_question": {
            "empty_prompt": "Please type your question.",
            "follow_up": (
                "Would you like to:\n"
                "1. Ask another question\n"
                "2. Return to Main Menu"
            ),
            "next_question": "Please type your next question.",
            "response_followup": "Would you like to:\n1. Ask another question\n2. Return to Main Menu",
            "invalid_option": "Please reply 1 to ask another question or 2 to return to the main menu."
        },
            "faq_borehole": {
            "responses": {
                "1": "The cost depends on your location, depth, and soil conditions. Please send us your location and site access details for a personalized quote.",
                "2": "Typically 4–6 hours or up to several days, depending on site conditions, rock type, and accessibility.",
                "3": "Depth varies by area. The standard depth is around 40 meters, but boreholes can range from 40 to 150 meters depending on the underground water table.",
                "4": "In some areas, a water permit may be required. We can assist you with the application if necessary.",
                "5": "Yes, we offer both as a combined package or separately, depending on your preference.",
                "6": "If the client wishes to drill at a second point, we offer a discount.\n\nNote: Survey machines detect underground water-bearing fractures or convergence points of underground streams. However, they do not measure the volume or flow rate of water. Therefore, borehole drilling carries no 100% guarantee of hitting water, as the fractures could be dry, moist, or wet.",
                "7": "We use professional-grade rotary and percussion drilling rigs, GPS tools, and geological survey equipment.",
                "8": "Returning to FAQ Menu...",
            
            "follow_up": (
                "Would you like to:\n"
                "1. Ask another question from Borehole Drilling FAQs\n"
                "2. Return to Main Menu"
            ),
            "invalid_option": "Please choose a valid option (1–8)."
                    },
            },
            
            "faq_pump": {
            "responses": {
                "1": "Solar pumps use energy from solar panels and are ideal for off-grid or remote areas. Electric pumps rely on the power grid and are typically more affordable upfront but depend on electricity availability.",
                "2": "Yes! We offer labor-only packages if you already have the necessary materials.",
                "3": "Installation usually takes one day, provided materials are ready and site access is clear.",
                "4": "Pump size depends on your water needs and borehole depth. We can assess your site and recommend the best option.",
                "5": "Yes, we supply complete packages including water tanks, tank stands, and all necessary plumbing fittings.",
                "6": "Returning to FAQ Menu..."
                },
                "follow_up": (
                "Would you like to:\n"
                "1. Ask another question from Pump Installation FAQs\n"
                "2. Return to Main Menu"
            ),
            "invalid_option": "Please choose a valid option (1–6)."
        },
        "human_agent": {
            "exit_message": "Okay. Feel free to ask if you need anything else.",
            "invalid_option": "Please reply with 1 for Main Menu or 2 to stay here."
        },
            "faq": {
            "borehole": {
                "menu": "Here are the most common questions about borehole drilling:\n\n1. How much does borehole drilling cost?\n2. How long does it take to drill a borehole?\n3. How deep will my borehole be?\n4. Do I need permission to drill a borehole?\n5. Do you do a water survey and drilling at the same time?\n6. What if you do a water survey and find no water?\n7. What equipment do you use?\n8. Back to FAQ Menu",
                "responses": {
                    "1": "The cost depends on your location, depth, and soil conditions. Please send us your location and site access details for a personalized quote.",
                    "2": "Typically 4–6 hours or up to several days, depending on site conditions, rock type, and accessibility.",
                    "3": "Depth varies by area. The standard depth is around 40 meters, but boreholes can range from 40 to 150 meters depending on the underground water table.",
                    "4": "In some areas, a water permit may be required. We can assist you with the application if necessary.",
                    "5": "Yes, we offer both as a combined package or separately, depending on your preference.",
                    "6": "If the client wishes to drill at a second point, we offer a discount.\n\nNote: Survey machines detect underground water-bearing fractures or convergence points of underground streams. However, they do not measure the volume or flow rate of water. Therefore, borehole drilling carries no 100% guarantee of hitting water, as the fractures could be dry, moist, or wet.",
                    "7": "We use professional-grade rotary and percussion drilling rigs, GPS tools, and geological survey equipment.",
                    "8": "Returning to FAQ Menu..."
                },
                "followup": "Would you like to:\n1. Ask another question from Borehole Drilling FAQs\n2. Return to Main Menu",
                "invalid_option": "Please choose a valid option (1–8)."
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
                "followup": "Would you like to:\n1. Ask another question from Pump Installation FAQs\n2. Return to Main Menu",
                "invalid_option": "Please choose a valid option (1–6)."
            },
            "custom_question": "Please type your question below, and we'll do our best to assist you.\n",
            "menu": "Here are the most common questions:\n\n1. Borehole Drilling FAQs\n2. Pump Installation FAQs\n3. Ask a different question\n4. Human agent\n5. Back to Main Menu",
            "invalid_option": "Please select a valid option (1–5).",
            "human_agent_connect": "Please hold while I connect you to a representative..."
    },
        "quote_intro": "Please tell us the location where you want the service.",
        "quote_thank_you": "Thank you! We have received your request.\n\n{0}\n\nWhat would you like to do next?\n1. Offer your own price\n2. Book site survey\n3. Book drilling\n4. Talk to an agent",
        "select_valid_service": "Please select a valid option (1-5).",
        "select_valid_option": "Please select a valid option (1-4).",
        "agent_connect": "Please wait while we connect you to a human agent...",
        "booking_confirmed": "Great! Your borehole drilling appointment is now booked.\n\n"
                             "Date: Thursday, 23 May 2025\n"
                             "Start Time: 8:00 AM\n"
                             "Expected Duration: 5 hrs\n"
                             "Team: 4-5 Technicians\n\n"
                             "Make sure there is access to the site",
        "reschedule_message": "Please contact our support team to reschedule.",
        "main_menu": "How can we help you today?\n\n"
                     "1. Request a quote\n"
                     "2. Search Price Using Location\n"
                     "3. Check Project Status\n"
                     "4. FAQs or Learn About Borehole Drilling\n"
                     "5. Other services\n"
                     "6. Talk to a Human Agent\n\n"
                     "Please reply with a number (e.g., 1)",
        "invalid_option_1_2": "Please select a valid option (1 or 2).",
        "invalid_option_1_3": "Please select a valid option (1-3).",
        "invalid_option_1_4": "Please select a valid option (1-4).",
        "borehole_casing_q": "To check if your borehole can be deepened:\n"
                             "Was the borehole cased:\n"
                             "1. Only at the top, with 180mm or larger diameter pipe\n"
                             "2. Top to bottom with 140mm or smaller diameter pipe",
        "deepening_qualified": "Your borehole qualifies for deepening.\nPlease enter your location (town, ward, growth point, or GPS pin):",
        "deepening_not_possible": "Unfortunately, boreholes cased from top to bottom with pipes smaller than 180mm cannot be deepened.\n"
                                  "Options:\n"
                                  "1. Back to Other Services\n"
                                  "2. Talk to Support",
        "deepening_cost_prompt": "Deepening cost in {location} starts from USD {price} per meter.\n"
                                 "Would you like to:\n"
                                 "1. Confirm & Book Job\n"
                                 "2. Back to Other Services",
        "booking_name_prompt": "Please provide your full name:",
        "flush_problem_prompt": "What is the problem with your borehole?\n"
                                "1. Collapsed Borehole\n"
                                "2. Dirty Water Borehole",
        "flush_diameter_prompt": "Do you know the borehole diameter?\n"
                                 "1. 180mm or larger\n"
                                 "2. Between 140mm and 180mm\n"
                                 "3. 140mm or smaller",
        "flush_dirty_location": "Please enter your location to check the price:",
        "flush_180mm": "We can flush your borehole using rods with a drilling bit (more effective).\nPlease enter your location to check the price:",
        "flush_140_180mm": "We can flush borehole with rods, no drilling bit.\nPlease enter your location to check the price:",
        "flush_below_140mm": "We can flush the borehole using rods only (without drilling bit).\nPlease enter your location to check the price:",
        "support_connecting": "Connecting you to support...",
        "pvc_classes": "We offer drilling boreholes following PVC casing pipe classes:\n"
                       "1. Class 6 – Standard\n"
                       "2. Class 9 – Stronger\n"
                       "3. Class 10 – Strongest\n"
                       "Which one would you like to check?",
        "quote_intro": "Please tell us the location where you want the service.",
        "quote_thank_you": "Thank you! We have received your request.\n\n{0}\n\nWhat would you like to do next?\n1. Offer your own price\n2. Book site survey\n3. Book drilling\n4. Talk to an agent",
        "select_valid_service": "Please select a valid option (1-5).",
        "select_valid_option": "Please select a valid option (1-4).",
        "agent_connect": "Please wait while we connect you to a human agent...",
        "flushing_cost": "Flushing cost in {location} starts from USD {price}.\nWould you like to:\n1. Confirm & Book Job\n2. Back to Other Services",
        "pvc_casing_price": "Price for {casing_class} PVC casing in {location} is USD {price}.\nWould you like to:\n1. Confirm & Book\n2. Back to Other Services",
        "provide_full_name": "Please provide your full name:",
        "provide_phone": "Please provide your phone number:",
        "provide_location": "Please enter your exact location/address or share your GPS pin:",
        "provide_booking_date": "Please enter your preferred booking date (e.g., 2024-10-15):",
        "provide_notes": "If you have any notes or special requests, please enter them now. Otherwise, type 'No':",
        "booking_confirmation": "Thank you {full_name}! Your booking is confirmed.\nBooking Reference: {reference}\nOur team will contact you soon.\nType 'menu' to return to the main menu.",
        "invalid_option": "Please select a valid option (1 or 2).",
        "pump_status_request": "Please provide at least your full name and reference number or phone number, each on a new line.\n\nExample:\nJane Doe\nREF123456\nOptional: Harare",
        "retrieving_status": "Thank you. Please wait while we retrieve your project status...",
        "project_status": "Here is your pump installation project status:\n\nProject Name: Pump - {full_name}\nCurrent Stage: Installation Completed\nNext Step: Final Inspection\nEstimated Hand-Over: {handover_date}\n\nWould you like WhatsApp updates when your status changes?\nOptions: Yes / No",
        "pump_updates_yes": "Great! You'll now receive WhatsApp updates whenever your borehole drilling status changes.\n\nThank you for using our service.",
        "pump_updates_no": "No problem. You can always check the status again later if needed.\n\nThank you for using our service.",
        "pump_updates_invalid": "Sorry, I didn't understand that. Please reply with Yes or No.",
        "check_status_menu_options": {
            "1": "To check your borehole drilling status, please provide the following:\n\n- Full Name used during booking\n- Project Reference Number or Phone Number\n- Drilling Site Location (optional)",
            "2": "To check your pump installation status, please provide the following:\n\n- Full Name used during booking\n- Project Reference Number or Phone Number\n- Installation Site Location (optional)",
            "3": "Please hold while I connect you to one of our support team members.",
            "invalid": "Invalid option. Please select 1, 2, 3, or 4."
        },
        "main_menu_prompt": (
            "How can we help you today?\n\n"
            "1. Request a quote\n"
            "2. Search Price Using Location\n"
            "3. Check Project Status\n"
            "4. FAQs or Learn About Borehole Drilling\n"
            "5. Other services\n"
            "6. Talk to a Human Agent\n\n"
            "Please reply with a number (e.g., 1)"
        ),
        "drilling_status_request_incomplete": (
            "Please provide at least your full name and reference number or phone number, each on a new line.\n\n"
            "Example:\nJohn Doe\nREF789123 or 0779876543\nOptional: Bulawayo"
        ),
        "drilling_status_retrieving": "Thank you. Please wait while we retrieve your project status...",
        "drilling_status_result": (
            "Here is your borehole drilling project status:\n\n"
            "Project Name: Borehole - {full_name}\n"
            "Current Stage: Drilling In Progress\n"
            "Next Step: Casing\n"
            "Estimated Completion Date: 10/06/2025\n\n"
            "Would you like WhatsApp updates when the status changes?\nOptions: Yes / No"
        ),
        "invalid_pump_option": "Invalid option. Please select a valid pump installation option (1-6).",
        "quote_select_another_service": (
            "Select another service:\n"
            "1. Water survey\n"
            "2. Borehole drilling\n"
            "3. Pump installation\n"
            "4. Commercial hole drilling\n"
            "5. Borehole Deepening"
        ),
        "quote_invalid_option": "Invalid option. Reply 1 to ask about another service or 2 to return to the main menu or 3 if you want to make a price offer."


        },
    
    "Shona": {
        "welcome": "Mhoro! Tigamuchire kuSpeedGo Services yekuchera maburi emvura muZimbabwe. Tinopa maburi emvura anovimbika nemhinduro dzemvura muZimbabwe yose.\n\nSarudza mutauro waunofarira:\n1. Chirungu\n2. Shona\n3. Ndebele",
        "main_menu": "Tinokubatsirai sei nhasi?\n\n1. Kukumbira quotation\n2. Tsvaga Mutengo Uchishandisa Nzvimbo\n3. Tarisa Mamiriro ePurojekiti\n4. Mibvunzo Inowanzo bvunzwa kana Dzidza Nezve Kuborehole\n5. Zvimwe Zvatinoita\n6. Taura neMunhu\n\nPindura nenhamba (semuenzaniso, 1)",
        "enter_location": "Ndapota nyora nzvimbo yako (Guta/Kanzuru kana GPS coordinates) kuti titange.",
        "location_detected": "Nzvimbo yawanikwa: {}\n\nZvino sarudza sevhisi yaunoda:\n1. Water survey\n2. Kuchera borehole\n3. Kuiswa kwepombi\n4. Kuchera bhora rezvekutengeserana\n5. Kuchinjwa/kudzika zvakare kwe borehole",
        "location_not_found": "Hatina kukwanisa kuona nzvimbo yenyu. Ndapota nyora zita reguta/kanzvimbo nemaoko.",
        "agent_connect": "Ndatenda. Ndapota mira ndichikubatanidza nemumiriri weSpeedGo...",
        "agent_notification": "👋 Mutengi anoda kutaura newe paWhatsApp.\n\n📱 Nhamba yeMutengi: {customer_number}\n🙋 Zita: {customer_name}\n📩 Mharidzo yekupedzisira: \"{prompt}\"",
        "new_request": "👋 Chikumbiro chitsva chemutengi paWhatsApp\n\n📱 Nhamba: {customer_number}\n📩 Mharidzo: \"{prompt}\"",
        "human_agent_followup": {
            "invalid_option": "Pindura ne1 kuti Main Menu kana 2 kuti ugare pano.",
            "stay_here": "Zvakanaka. Sununguka kubvunza kana uine chimwe chaunoda."
        },
        "faq_menu": {
            "invalid_option": "Sarudza sarudzo inoshanda (1–5).",
            "borehole_faqs": (
                "Heano mibvunzo inowanzo bvunzwa nezvekuchera mabhorehole:\n\n"
                "1. Marii kuchera borehole?\n"
                "2. Zvinotora nguva yakareba sei kuchera borehole?\n"
                "3. Borehole yangu ichadzika sei?\n"
                "4. Ndinoda mvumo here kuchera borehole?\n"
                "5. Munoona mvura uye mochera panguva imwe chete here?\n"
                "6. Ko kana mukaona mvura uye mukashaya mvura?\n"
                "7. Mishandisi yenyu ndeipi?\n"
                "8. Dzokera kuFAQ Menu"
            ),
        
                "pump_faqs": (
                "Heano mibvunzo inowanzo bvunzwa nezvekuisa mapombi:\n\n"
                "1. Musiyano uripi pakati pemapombi ezuva nemagetsi?\n"
                "2. Munogona here kuisa kana ndine zvinhu zvacho?\n"
                "3. Zvinotora nguva yakareba sei kuisa pombi?\n"
                "4. Pombi yakakura sei yandinoda?\n"
                "5. Munopa matangi nematangi stands here?\n"
                "6. Dzokera kuFAQ Menu"
            ),
                "custom_question": "Ndapota nyora mubvunzo wako pazasi, uye tichaita nepandinogona kukubatsira.\n",
                "connecting_agent": "Ndapota mira ndichikubatanidza nemumiriri..."
        },
        "custom_question": {
            "empty_prompt": "Ndapota nyora mubvunzo wako.",
            "follow_up": (
                "Ungada here:\n"
                "1. Kubvunza mumwe mubvunzo\n"
                "2. Kudzokera kuMain Menu"
            ),
            "next_question": "Ndapota nyora mubvunzo wako unotevera.",
            "response_followup": "Ungada here:\n1. Kubvunza mumwe mubvunzo\n2. Kudzokera kuMain Menu",
            "invalid_option": "Pindura ne1 kuti ubvunze mumwe mubvunzo kana 2 kuti udzokere kumenu huru."
        },
            "faq_borehole": {
            "responses": {
                "1": "Mari inoenderana nenzvimbo yako, kudzika, uye mamiriro evhu. Ndapota titumire nzvimbo yako uye ruzivo rwekuwana nzvimbo kuti tikupe mutengo wako.",
                "2": "Kazhinji maawa 4–6 kana kusvika mazuva akati wandei, zvichienderana nemamiriro enzvimbo, rudzi rwedombo, uye kuwanikwa kwenzvimbo.",
                "3": "Kudzika kunosiyana nenzvimbo. Kudzika kwakajairwa kunosvika mamita makumi mana, asi mabhorehole anogona kubva pamamita makumi mana kusvika zana nemakumi mashanu zvichienderana netafura yemvura yepasi pevhu.",
                "4": "Mune dzimwe nzvimbo, mvumo yemvura inogona kudikanwa. Tinogona kukubatsira nechikumbiro kana zvichidikanwa.",
                "5": "Hongu, tinopa ese ari maviri semubatanidzwa kana zvakasiyana, zvichienderana nezvaunoda.",
                "6": "Kana mutengi achida kuchera panzvimbo yechipiri, tinopa discount.\n\nCherechedza: Michina yekuongorora inoona mitswe inotakura mvura yepasi pevhu kana nzvimbo dzinopindirana dzemvura pasi pevhu. Zvisinei, haipime huwandu kana kuyerera kwemvura. Saka kuchera borehole hakuna vimbiso yekuti muchawana mvura, sezvo mitswe ingave yakaoma, yakanyorova, kana ine mvura.",
                "7": "Tinoshandisa midziyo yehunyanzvi yekuchera uye percussion drilling rigs, GPS maturusi, uye midziyo yekuongorora geological.",
                "8": "Ndiri kudzokera kuFAQ Menu..."
            },
            "follow_up": (
                "Ungada here:\n"
                "1. Kubvunza mumwe mubvunzo kubva kuBorehole Drilling FAQs\n"
                "2. Kudzokera kuMain Menu"
            ),
            "invalid_option": "Sarudza sarudzo inoshanda (1–8)."
        },
            "faq_pump": {
            "responses": {
                "1": "Mapombi ezuva anoshandisa simba remapaneru ezuva uye akanakira nzvimbo dzisina magetsi kana dziri kure. Mapombi emagetsi anovimba nemagetsi uye anowanzo kuve akachipa pakutanga asi anoenderana nekuwanikwa kwemagetsi.",
                "2": "Hongu! Tinopa mapakeji ebasa chete kana uine zvinhu zvinodiwa.",
                "3": "Kuiswa kunowanzo torera zuva rimwe, chero zvinhu zvagadzirira uye nzvimbo yakavhurika.",
                "4": "Saizi yepombi inoenderana nezvaunoda uye nekudzika kweborehole. Tinogona kuongorora nzvimbo yako uye kukurudzira sarudzo yakanaka.",
                "5": "Hongu, tinopa mapakeji akazara anosanganisira matangi emvura, matangi stands, uye zvese zvinodiwa zvepombi.",
                "6": "Ndiri kudzokera kuFAQ Menu..."
            },
            "follow_up": (
                "Ungada here:\n"
                "1. Kubvunza mumwe mubvunzo kubva kuPump Installation FAQs\n"
                "2. Kudzokera kuMain Menu"
            ),
            "invalid_option": "Sarudza sarudzo inoshanda (1–6)."
        },
            "human_agent": {
            "exit_message": "Zvakanaka. Sununguka kubvunza kana uine chimwe chaunoda.",
            "invalid_option": "Pindura ne1 kuti Main Menu kana 2 kuti ugare pano."
        },
        "faq": {
            "borehole": {
                "menu": "Heano mibvunzo inowanzo bvunzwa nezvekuchera mabhorehole:\n\n1. Marii kuchera borehole?\n2. Zvinotora nguva yakareba sei kuchera borehole?\n3. Borehole yangu ichadzika sei?\n4. Ndinoda mvumo here kuchera borehole?\n5. Munoona mvura uye mochera panguva imwe chete here?\n6. Ko kana mukaona mvura uye mukashaya mvura?\n7. Mishandisi yenyu ndeipi?\n8. Dzokera kuFAQ Menu",
                "responses": {
                    "1": "Mari inoenderana nenzvimbo yako, kudzika, uye mamiriro evhu. Ndapota titumire nzvimbo yako uye ruzivo rwekuwana nzvimbo kuti tikupe mutengo wako.",
                    "2": "Kazhinji maawa 4–6 kana kusvika mazuva akati wandei, zvichienderana nemamiriro enzvimbo, rudzi rwedombo, uye kuwanikwa kwenzvimbo.",
                    "3": "Kudzika kunosiyana nenzvimbo. Kudzika kwakajairwa kunosvika mamita makumi mana, asi mabhorehole anogona kubva pamamita makumi mana kusvika zana nemakumi mashanu zvichienderana netafura yemvura yepasi pevhu.",
                    "4": "Mune dzimwe nzvimbo, mvumo yemvura inogona kudikanwa. Tinogona kukubatsira nechikumbiro kana zvichidikanwa.",
                    "5": "Hongu, tinopa ese ari maviri semubatanidzwa kana zvakasiyana, zvichienderana nezvaunoda.",
                    "6": "Kana mutengi achida kuchera panzvimbo yechipiri, tinopa discount.\n\nCherechedza: Michina yekuongorora inoona mitswe inotakura mvura yepasi pevhu kana nzvimbo dzinopindirana dzemvura pasi pevhu. Zvisinei, haipime huwandu kana kuyerera kwemvura. Saka kuchera borehole hakuna vimbiso yekuti muchawana mvura, sezvo mitswe ingave yakaoma, yakanyorova, kana ine mvura.",
                    "7": "Tinoshandisa midziyo yehunyanzvi yekuchera uye percussion drilling rigs, GPS maturusi, uye midziyo yekuongorora geological.",
                    "8": "Ndiri kudzokera kuFAQ Menu..."
                },
                "followup": "Ungada here:\n1. Kubvunza mumwe mubvunzo kubva kuBorehole Drilling FAQs\n2. Kudzokera kuMain Menu",
                "invalid_option": "Sarudza sarudzo inoshanda (1–8).",
       
                "pump": {
                "menu": "Heano mibvunzo inowanzo bvunzwa nezvekuisa mapombi:\n\n1. Musiyano uripi pakati pemapombi ezuva nemagetsi?\n2. Munogona here kuisa kana ndine zvinhu zvacho?\n3. Zvinotora nguva yakareba sei kuisa pombi?\n4. Pombi yakakura sei yandinoda?\n5. Munopa matangi nematangi stands here?\n6. Dzokera kuFAQ Menu",
                "responses": {
                    "1": "Mapombi ezuva anoshandisa simba remapaneru ezuva uye akanakira nzvimbo dzisina magetsi kana dziri kure. Mapombi emagetsi anovimba nemagetsi uye anowanzo kuve akachipa pakutanga asi anoenderana nekuwanikwa kwemagetsi.",
                    "2": "Hongu! Tinopa mapakeji ebasa chete kana uine zvinhu zvinodiwa.",
                    "3": "Kuiswa kunowanzo torera zuva rimwe, chero zvinhu zvagadzirira uye nzvimbo yakavhurika.",
                    "4": "Saizi yepombi inoenderana nezvaunoda uye nekudzika kweborehole. Tinogona kuongorora nzvimbo yako uye kukurudzira sarudzo yakanaka.",
                    "5": "Hongu, tinopa mapakeji akazara anosanganisira matangi emvura, matangi stands, uye zvese zvinodiwa zvepombi.",
                    "6": "Ndiri kudzokera kuFAQ Menu..."
                    },
                    "followup": "Ungada here:\n1. Kubvunza mumwe mubvunzo kubva kuPump Installation FAQs\n2. Kudzokera kuMain Menu",
                    "invalid_option": "Sarudza sarudzo inoshanda (1–6)."
                    },
                    "custom_question": "Ndapota nyora mubvunzo wako pazasi, uye tichaita nepandinogona kukubatsira.\n",
                    "menu": "Heano mibvunzo inowanzo bvunzwa:\n\n1. Borehole Drilling FAQs\n2. Pump Installation FAQs\n3. Bvunza mumwe mubvunzo\n4. Mumiriri wevanhu\n5. Dzokera kuMain Menu",
                    "invalid_option": "Sarudza sarudzo inoshanda (1–5)."
                    },
                    "human_agent_connect": "Ndapota mira ndichikubatanidza nemumiriri..."
                },
        "quote_intro": "Ndokumbirawo mutiudze nzvimbo yamunoda kuitirwa basa iri.",
        "quote_thank_you": "Tatenda! Tagamuchira chikumbiro chenyu.\n\n{0}\n\nMungade kuita chii zvino?\n1. Taurai mari yamunoda kubhadhara\n2. Bhuka kuongorora nzvimbo\n3. Bhuka kuchera\n4. Taura nemumiriri",
        "select_valid_service": "Ndapota sarudzai chisarudzo chiri pakati pe1 kusvika ku5.",
        "select_valid_option": "Ndapota sarudzai chisarudzo chiri pakati pe1 kusvika ku4.",
        "agent_connect": "Ndokumbirawo mirai tichikubatanidzai nemumiriri...",
        "booking_confirmed": "Zvakanaka! Basa rekuvhuvhura borehole rako rabhukidzwa.\n\n"
                             "Zuva: China, 23 Chivabvu 2025\n"
                             "Nguva: 8:00 AM\n"
                             "Inotora: maawa mashanu\n"
                             "Chikwata: Vanhu 4-5\n\n"
                             "Ndokumbira uve nechokwadi chekuti nzvimbo yakavhurika",
        "reschedule_message": "Ndokumbira ubate rutsigiro rwedu kuti tigadzirise rimwe zuva.",
        "main_menu": "Tinokubatsira sei nhasi?\n\n"
                     "1. Kumbira mutengo\n"
                     "2. Tarisa mutengo zvichienderana nenzvimbo\n"
                     "3. Tarisa mafambiro ebasa\n"
                     "4. FAQs kana Dzidza nezve Borehole\n"
                     "5. Mamwe masevhisi\n"
                     "6. Taura neMumiriri\n\n"
                     "Ndokumbira upindure nenhamba (semuenzaniso: 1)",
        "invalid_option_1_2": "Ndokumbira usarudze sarudzo iripo (1 kana 2).",
        "invalid_option_1_3": "Ndokumbira usarudze sarudzo iripo (1-3).",
        "invalid_option_1_4": "Ndokumbira usarudze sarudzo iripo (1-4).",
        "borehole_casing_q": "Kutarisa kana borehole yako ichigona kudzika:\n"
                             "Yakaiswa pipe sei:\n"
                             "1. Pakutanga chete ne 180mm kana kupfuura\n"
                             "2. Kubva pamusoro kusvika pasi ne140mm kana pasi",
        "deepening_qualified": "Borehole yako inokodzera kudzika.\nNdokumbira nyora nzvimbo yako (guta, ward, kana GPS pin):",
        "deepening_not_possible": "Nehurombo, boreholes dzakaiswa mapombi madiki kubva pamusoro kusvika pasi hadzigoni kudzika.\n"
                                  "Sarudza:\n"
                                  "1. Dzokera kuMamwe Masevhisi\n"
                                  "2. Taura neSupport",
        "deepening_cost_prompt": "Mutengo wekuwedzera kudzika mu{location} unotanga paUSD {price} pamita.\n"
                                 "Ungade:\n"
                                 "1. Simbisa uye Bhuka Basa\n"
                                 "2. Dzokera kuMamwe Masevhisi",
        "booking_name_prompt": "Ndokumbira nyora zita rako rizere:",
        "flush_problem_prompt": "Chii chiri kunetsa ne borehole yako?\n"
                                "1. Borehole yakaputsika\n"
                                "2. Mvura ine tsvina",
        "flush_diameter_prompt": "Unoziva diameter ye borehole yako here?\n"
                                 "1. 180mm kana kupfuura\n"
                                 "2. Pakati pe140mm ne180mm\n"
                                 "3. 140mm kana pasi",
        "flush_dirty_location": "Ndokumbira nyora nzvimbo yako kuti titarise mutengo:",
        "flush_180mm": "Tinogona kushandisa tsvimbo nebiti. Ndokumbira nyora nzvimbo yako:",
        "flush_140_180mm": "Tinoshandisa tsvimbo pasina biti. Nyora nzvimbo yako:",
        "flush_below_140mm": "Tinoshandisa tsvimbo chete. Nyora nzvimbo yako:",
        "support_connecting": "Tiri kukubatanidza ne support...",
        "pvc_classes": "Tinopa mabasa ePVC casing pipe:\n"
                       "1. Class 6 – Standard\n"
                       "2. Class 9 – Yakasimba\n"
                       "3. Class 10 – Yakasimba zvikuru\n"
                       "Ndeipi yaunoda kuona?",
        "quote_intro": "Ndokumbirawo mutiudze nzvimbo yamunoda kuitirwa basa iri.",
        "quote_thank_you": "Tatenda! Tagamuchira chikumbiro chenyu.\n\n{0}\n\nMungade kuita chii zvino?\n1. Taurai mari yamunoda kubhadhara\n2. Bhuka kuongorora nzvimbo\n3. Bhuka kuchera\n4. Taura nemumiriri",
        "select_valid_service": "Ndapota sarudzai chisarudzo chiri pakati pe1 kusvika ku5.",
        "select_valid_option": "Ndapota sarudzai chisarudzo chiri pakati pe1 kusvika ku4.",
        "agent_connect": "Ndokumbirawo mirai tichikubatanidzai nemumiriri...",
        "flushing_cost": "Mutengo wekugezesa mu {location} unotangira pa USD {price}.\nMungade:\n1. Kusimbisa & Bhuka Basa\n2. Dzokera kune Mamwe Mabasa",
        "pvc_casing_price": "Mutengo we {casing_class} PVC casing mu {location} uri USD {price}.\nMungade:\n1. Kusimbisa & Bhuka\n2. Dzokera kune Mamwe Mabasa",
        "provide_full_name": "Ndapota nyora zita renyu rizere:",
        "provide_phone": "Ndapota nyora nhamba yenyu yefoni:",
        "provide_location": "Ndapota nyora kero yenyu chaiyo kana mugovane GPS pin yenyu:",
        "provide_booking_date": "Ndapota nyora zuva ramunoda kuti tibhuke (semuenzaniso, 2024-10-15):",
        "provide_notes": "Kana muine zvimwe zvamunoda kuti tizive, ndapota nyorai izvozvi. Kana zvisina, nyorai 'Kwete':",
        "booking_confirmation": "Tatenda {full_name}! Bhuking yenyu yasimbiswa.\nReference: {reference}\nChikwata chedu chichakubatai munguva pfupi.\nNyora 'menu' kudzokera kumenu huru.",
        "invalid_option": "Ndapota sarudzai chisarudzo chiri pakati pe1 kana 2.",
        "pump_status_request": "Ndapota nyora zita renyu rizere uye nhamba yerefreshi kana nhamba yefoni, imwe neimwe pamutsara mutsva.\n\nMuenzaniso:\nJane Doe\nREF123456\nOptional: Harare",
        "retrieving_status": "Tatenda. Ndokumbirawo mirai tichitsvaga mamiriro ebasa renyu...",
        "project_status": "Hezvino mamiriro ebasa renyu rekuisa pombi:\n\nZita reProject: Pombi - {full_name}\nChikamu Chiripo: Kuisa Kwapedzwa\nChinotevera: Kuongorora kwekupedzisira\nZuva Rekuendesa: {handover_date}\n\nMungade kugamuchira zvigadziriso zveWhatsApp kana mamiriro achinja?\nSarudzo: Ehe / Kwete",
        "pump_updates_yes": "Zvakanaka! Iye zvino uchagamuchira zviziviso zveWhatsApp pese panoshanduka mamiriro ekuchera borehole yako.\n\nNdatenda nekushandisa sevhisi yedu.",
        "pump_updates_no": "Hazvina basa. Unogona kugara uchitarisa mamiriro zvakare kana zvichidiwa.\n\nNdatenda nekushandisa sevhisi yedu.",
        "pump_updates_invalid": "Ndine urombo, handina kunzwisisa. Ndapota pindura neEhe kana Kwete.",
        "check_status_menu_options": {
            "1": "Kuti utarise mamiriro ekuchera borehole yako, ndapota ipa zvinotevera:\n\n- Zita rakazara rawakashandisa pakubhuka\n- Nhamba yekureferensi yeprojekiti kana Nhamba yefoni\n- Nzvimbo yekuchera (zvingasarudzwa)",
            "2": "Kuti utarise mamiriro ekuisa pombi, ndapota ipa zvinotevera:\n\n- Zita rakazara rawakashandisa pakubhuka\n- Nhamba yekureferensi yeprojekiti kana Nhamba yefoni\n- Nzvimbo yekuisa pombi (zvingasarudzwa)",
            "3": "Ndapota mirira ndichikubatanidza nemumwe wevashandi vedu vekutsigira.",
            "invalid": "Sarudzo isiriyo. Ndapota sarudza 1, 2, 3, kana 4."
        },
        "main_menu_prompt": (
            "Tinogona kukubatsira sei nhasi?\n\n"
            "1. Kumbira mutengo\n"
            "2. Tsvaga mutengo uchishandisa nzvimbo\n"
            "3. Tarisa mamiriro eprojekiti\n"
            "4. FAQs kana Dzidza nezveBorehole Drilling\n"
            "5. Dzimwe sevhisi\n"
            "6. Taura nemunhu\n\n"
            "Ndapota pindura nenhamba (semuenzaniso, 1)"
        ),
        "drilling_status_request_incomplete": (
            "Ndapota ipa zita rako rizere uye nhamba yekureferensi kana nhamba yefoni, imwe neimwe mutsara mutsva.\n\n"
            "Muenzaniso:\nJohn Doe\nREF789123 kana 0779876543\nZvingasarudzwa: Bulawayo"
        ),
        "drilling_status_retrieving": "Ndatenda. Ndapota mirira tichitsvaga mamiriro eprojekiti yako...",
        "drilling_status_result": (
            "Heano mamiriro eprojekiti yako yekuchera borehole:\n\n"
            "Zita reProjekiti: Borehole - {full_name}\n"
            "Chikamu Chazvino: Kuchera Kwiri Kuitika\n"
            "Chinotevera: Kuisa Casing\n"
            "Zuva Rekupedza Rinotarisirwa: 10/06/2025\n\n"
            "Ungada here kugamuchira zviziviso zveWhatsApp kana mamiriro achichinja?\nSarudzo: Ehe / Kwete"
        ),
        "invalid_pump_option": "Sarudzo isiriyo. Ndapota sarudza sarudzo yakakodzera yekuisa pombi (1-6).",
        "quote_select_another_service": (
            "Sarudza imwe sevhisi:\n"
            "1. Kuongorora mvura\n"
            "2. Kuchera borehole\n"
            "3. Kuisa pombi\n"
            "4. Kuchera bhora rekutengesa\n"
            "5. Kuwedzera kudzika kweborehole"
        ),
        "quote_invalid_option": "Sarudzo isiriyo. Pindura 1 kuti ubvunze nezveimwe sevhisi kana 2 kudzokera kumenu huru kana 3 kana uchida kupa mutengo."

    },
    
    "Ndebele": {
        "welcome": "Sawubona! Wamukelekile kwiSpeedGo Services yokumba amaBorehole eZimbabwe. Sinikeza ukumba kwamaBorehole okuthembekile kanye nezixazululo zamanzi kulo lonke iZimbabwe.\n\nKhetha ulimi oluthandayo:\n1. IsiNgisi\n2. IsiNdebele\n3. IsiShona",
        "main_menu": "Singakusiza njani lamuhla?\n\n1. Cela isiphakamiso\n2. Phanda Intengo Ngokusebenzisa Indawo\n3. Bheka Isimo Sephrojekthi\n4. Imibuzo Evame Ukubuzwa noma Funda Ngokuqhuba Ibhorehole\n5. Eminye Imisebenzi\n6. Khuluma Nomuntu\n\nPhendula ngenombolo (umzekeliso: 1)",
        "enter_location": "Sicela ufake indawo yakho (Idolobha/Idolobhana noma i-GPS) ukuze siqale.",
        "location_detected": "Indawo etholakele: {}\n\nSicela ukhethe inkonzo ofunayo:\n1. Ukuhlolwa kwamanzi\n2. Ukumba iBorehole\n3. Ukufakwa kwepampu\n4. Ukumba umgodi wezentengiselwano\n5. Ukwelula iBorehole (Deepening)",
        "location_not_found": "Asikwazanga ukuhlonza indawo yakho. Sicela bhala igama ledolobho/lindawo yakho ngesandla.",
        "fallback_option": "Neimwe nzira, unogona kutibata zvakananga pa {agent_number}",
        "followup_question": "Ungada here:\n1. Kudzokera kumenu huru\n2. Kupedza hurukuro",
        "return_menu": "Ndiri kukudzosera kumenu huru...",
        "goodbye": "Ndatenda! Iva nezuva rakanaka.",
        "invalid_option": "Pindura ne1 kuti Hongu kana 2 kuti Kwete.",
        "still_waiting": "Ndapota mira, tichiri kukubatanidza...",
        "human_agent_followup": {
            "invalid_option": "Phendula ngo-1 ukuze uthi Main Menu noma ngo-2 ukuze uhlale lapha.",
            "stay_here": "Kulungile. Zizwe ukhululekile ukubuza uma unokuthile okudingayo."
        },
        "faq_menu": {
            "invalid_option": "Khetha inketho evumelekile (1–5).",
            "borehole_faqs": (
                "Nazi imibuzo evame ukubuzwa mayelana nokumbiwa kwemigodi yamanzi:\n\n"
                "1. Kubiza malini ukumba umgodi wamanzi?\n"
                "2. Kuthatha isikhathi esingakanani ukumba umgodi wamanzi?\n"
                "3. Uzoba njani ubujulu bomgodi wami wamanzi?\n"
                "4. Ngidinga imvume yokumba umgodi wamanzi?\n"
                "5. Ngabe niyahlola amanzi bese nibamba ngesikhathi esisodwa?\n"
                "6. Kuthiwani uma nihlola amanzi bese ningenayo?\n"
                "7. Yiziphi izinto enizisebenzisayo?\n"
                "8. Buyela kumenyu yemibuzo"
            ),
            "pump_faqs": (
                "Nazi imibuzo evame ukubuzwa mayelana nokufakwa kwepompi:\n\n"
                "1. Umehluko uyini phakathi kwepompi yelanga neyogesi?\n"
                "2. Ngabe ningayifaka uma senginazo izinto ezidingekayo?\n"
                "3. Kuthatha isikhathi esingakanani ukufaka ipompi?\n"
                "4. Ngidinga ipompi enkulu kangakanani?\n"
                "5. Ngabe ninikeza amathangi nezinduku zamathangi?\n"
                "6. Buyela kumenyu yemibuzo"
            ),
            "custom_question": "Sicela uthayiphe umbuzo wakho ngezansi, futhi sizokwenza konke okusemandleni ethu ukukusiza.\n",
            "connecting_agent": "Sicela ulinde ngizokuxhumanisa nommeleli...",
        
            "custom_question": {
            "empty_prompt": "Sicela uthayiphe umbuzo wakho.",
            "follow_up": (
                "Ungathanda:\n"
                "1. Ukubuza omunye umbuzo\n"
                "2. Ukubuyela kumenyu eyinhloko"
            ),
            "next_question": "Sicela uthayiphe umbuzo wakho olandelayo.",
            "response_followup": "Ungathanda:\n1. Ukubuza omunye umbuzo\n2. Ukubuyela kumenyu eyinhloko",
            "invalid_option": "Phendula ngo-1 ukuze ubuze omunye umbuzo noma ngo-2 ukuze ubuyele kumenyu eyinhloko."
        },
            "faq_borehole": {
            "responses": {
                "1": "Intengo incike endaweni yakho, ekujuleni, nasezimeni zomhlabathi. Sicela usithumelele indawo yakho nolwazi lokufinyelela ukuze sikunikeze isilinganiso sakho.",
                "2": "Ngokuvamile amahora angu-4–6 noma kuze kufike ezinsukwini ezimbalwa, kuncike ezimeni zendawo, uhlobo lwedwala, nokufinyeleleka kwendawo.",
                "3": "Ubujulu buyahluka ngendawo. Ubujulu obujwayelekile buphakathi nemamitha angu-40, kodwa imigodi yamanzi ingavela kumamitha angu-40 kuya kwayi-150 kuncike kuthebula yamanzi angaphansi komhlaba.",
                "4": "Kwezinye izindawo, kungadingeka imvume yamanzi. Singakusiza ngesicelo uma kudingeka.",
                "5": "Yebo, sinikeza kokubili njengephakethe elihlanganisiwe noma ngokwehlukana, kuncike kulokho okufunayo.",
                "6": "Uma ikhasimende lifuna ukumba endaweni yesibili, sinikeza isaphulelo.\n\nQaphela: Imishini yokuhlola ithola imikhondo ephansi komhlaba ethwala amanzi noma izindawo ezihlangana zamanzi angaphansi komhlaba. Kodwa, ayilinganisi inani noma ijubane lamanzi. Ngakho-ke ukumba umgodi wamanzi akunasigqiniseko sokuthi uzothola amanzi, njengoba imikhondo ingaba yomile, imanzi noma inamanzi.",
                "7": "Sisebenzisa izinsimbi zokumba ezingochwepheshe kanye ne-percussion drilling rigs, amathuluzi e-GPS, namathuluzi okuhlola geological.",
            }
        }
    },
        "quote_intro": "Sicela usitshele indawo ofuna ukwenza insiza kuyo.",
        "quote_thank_you": "Siyabonga! Sikumukele isicelo sakho.\n\n{0}\n\nUfuna ukwenzani okulandelayo?\n1. Nikeza intengo yakho\n2. Bhuka ukuhlolwa kwendawo\n3. Bhuka ukugawula\n4. Khuluma nommeli",
        "select_valid_service": "Sicela ukhethe inketho efaneleyo (1-5).",
        "select_valid_option": "Sicela ukhethe inketho efaneleyo (1-4).",
        "agent_connect": "Sicela ulinde njengoba sixhumanisa nommeli...",
                "booking_confirmed": "Kuhle! Umsebenzi wakho wokugawula umthombo ubhukhiwe.\n\n"
                             "Usuku: ULwesine, 23 Meyi 2025\n"
                             "Isikhathi: 8:00 AM\n"
                             "Ubude: amahora amahlanu\n"
                             "Iqembu: Abasebenzi abangu-4 kuya ku-5\n\n"
                             "Qinisekisa ukuthi indawo iyafinyeleleka",
        "reschedule_message": "Sicela uxhumane nethimba lethu ukulungisa usuku.",
        "main_menu": "Singakusiza ngani namhlanje?\n\n"
                     "1. Cela inani\n"
                     "2. Hlola intengo ngokwendawo\n"
                     "3. Hlola isimo sephrojekthi\n"
                     "4. Imibuzo evamile noma Funda ngokuqhubekisela phambili umthombo\n"
                     "5. Amanye amasevisi\n"
                     "6. Khuluma nomuntu ongumsizi\n\n"
                     "Sicela uphendule ngenombolo (isb: 1)",
        "invalid_option_1_2": "Sicela ukhethe inketho evumelekile (1 noma 2).",
        "invalid_option_1_3": "Sicela ukhethe inketho evumelekile (1-3).",
        "invalid_option_1_4": "Sicela ukhethe inketho evumelekile (1-4).",
        "borehole_casing_q": "Ukuhlola uma umthombo wakho ungagawulwa:\n"
                             "Ngabe wawufakwe ipayipi:\n"
                             "1. Phezulu kuphela, ngepayipi le-180mm noma elikhulu\n"
                             "2. Kusukela phezulu kuya phansi ngepayipi le-140mm noma elincane",
        "deepening_qualified": "Umthombo wakho uyakufanelekela ukugawulwa.\nSicela ufake indawo yakho:",
        "deepening_not_possible": "Uxolo, imithombo efakwe amapayipi amancane kusukela phezulu kuya phansi ayikwazi ukugawulwa.\n"
                                  "Izinketho:\n"
                                  "1. Buyela kwezinye izinsizakalo\n"
                                  "2. Xhumana nethimba",
        "deepening_cost_prompt": "Izindleko zokugawula e{location} ziqala ku-USD {price} nge-mitha.\n"
                                 "Ungathanda:\n"
                                 "1. Qinisekisa & Bhukha Umsebenzi\n"
                                 "2. Buyela kwezinye izinsizakalo",
        "booking_name_prompt": "Sicela unikeze igama lakho eligcwele:",
        "flush_problem_prompt": "Iyini inkinga yomthombo wakho?\n"
                                "1. Umthombo owadilikayo\n"
                                "2. Amanzi angcolile",
        "flush_diameter_prompt": "Uyakwazi ububanzi bomthombo wakho?\n"
                                 "1. 180mm noma ngaphezulu\n"
                                 "2. Phakathi kuka-140mm no-180mm\n"
                                 "3. 140mm noma ngaphansi",
        "flush_dirty_location": "Sicela ufake indawo yakho ukuze sibheke intengo:",
        "flush_180mm": "Siyakwazi ukusebenzisa izinduku ne-drill bit. Sicela ufake indawo:",
        "flush_140_180mm": "Sisebenzisa izinduku kuphela ngaphandle kwe-drill bit. Sicela ufake indawo:",
        "flush_below_140mm": "Izinduku kuphela. Sicela ufake indawo:",
        "support_connecting": "Siyakuxhumanisa nosizo...",
        "pvc_classes": "Sinikezela ngensiza yePVC casing:\n"
                       "1. Class 6 – Ejwayelekile\n"
                       "2. Class 9 – Eqinile\n"
                       "3. Class 10 – Eqinile kakhulu\n"
                       "Yikuphi ofuna ukukuhlola?",
        "quote_intro": "Sicela usitshele indawo ofuna ukwenza insiza kuyo.",
        "quote_thank_you": "Siyabonga! Sikumukele isicelo sakho.\n\n{0}\n\nUfuna ukwenzani okulandelayo?\n1. Nikeza intengo yakho\n2. Bhuka ukuhlolwa kwendawo\n3. Bhuka ukugawula\n4. Khuluma nommeli",
        "select_valid_service": "Sicela ukhethe inketho efaneleyo (1-5).",
        "select_valid_option": "Sicela ukhethe inketho efaneleyo (1-4).",
        "agent_connect": "Sicela ulinde njengoba sixhumanisa nommeli...",
        "flushing_cost": "Izindleko zokugeza e {location} ziqala ku-USD {price}.\nUngathanda:\n1. Qinisekisa & Bhuka Umsebenzi\n2. Buyela Kwezinye Izinzuzo",
        "pvc_casing_price": "Intengo ye {casing_class} PVC casing e {location} yi-USD {price}.\nUngathanda:\n1. Qinisekisa & Bhuka\n2. Buyela Kwezinye Izinzuzo",
        "provide_full_name": "Sicela unikeze igama lakho eliphelele:",
        "provide_phone": "Sicela unikeze inombolo yakho yocingo:",
        "provide_location": "Sicela ufake indawo yakho eqondile noma wabelane nge-GPS pin yakho:",
        "provide_booking_date": "Sicela ufake usuku oluthandayo lokubhuka (isb., 2024-10-15):",
        "provide_notes": "Uma uneminye imiyalezo noma izicelo ezikhethekile, sicela ufake manje. Uma kungenjalo, bhala 'Cha':",
        "booking_confirmation": "Siyabonga {full_name}! Ukubhuka kwakho kuqinisekisiwe.\nIreferensi Yokubhuka: {reference}\nIthimba lethu lizokuthinta maduze.\nThayipha 'menu' ukuze ubuyele kumenyu enkulu.",
        "invalid_option": "Sicela ukhethe inketho efaneleyo (1 noma 2).",
        "pump_status_request": "Sicela unikeze okungenani igama lakho eliphelele nenombolo yerefreshi noma inombolo yocingo, ngakunye kumugqa omusha.\n\nIsibonelo:\nJane Doe\nREF123456\nOptional: Harare",
        "retrieving_status": "Siyabonga. Sicela ulinde njengoba sithola isimo sephrojekthi yakho...",
        "project_status": "Nansi isimo sephrojekthi yakho yokufaka ipompo:\n\nIgama lephrojekthi: Ipompo - {full_name}\nIsigaba Samanje: Ukufakwa Kuqediwe\nIsinyathelo Esilandelayo: Ukuhlolwa Kokugcina\nUsuku Olulinganiselwe Lokudluliselwa: {handover_date}\n\nUngathanda ukuthola izibuyekezo ze-WhatsApp uma isimo sakho sishintsha?\nIzinketho: Yebo / Cha",
        "pump_updates_yes": "Kulungile! Uzathola izaziso zeWhatsApp njalo lapho isimo sokumba borehole sakho sishintsha.\n\nNgiyabonga ngokusebenzisa insiza yethu.",
        "pump_updates_no": "Akukho inkinga. Ungahlola isimo futhi uma kudingeka.\n\nNgiyabonga ngokusebenzisa insiza yethu.",
        "pump_updates_invalid": "Uxolo, angiqondi kahle. Sicela uphendule ngo Yebo noma Cha.",
        "check_status_menu_options": {
            "1": "Ukuze ubheke isimo sokumba borehole yakho, sicela unikeze okulandelayo:\n\n- Igama eligcwele olisebenzise ngesikhathi sokubhuka\n- Inombolo yeReferensi yephrojekthi noma Inombolo yefoni\n- Indawo yokumba (uyazikhethela)",
            "2": "Ukuze ubheke isimo sokufaka ipampu, sicela unikeze okulandelayo:\n\n- Igama eligcwele olisebenzise ngesikhathi sokubhuka\n- Inombolo yeReferensi yephrojekthi noma Inombolo yefoni\n- Indawo yokufaka ipampu (uyazikhethela)",
            "3": "Sicela linda ngixhume nawe nomunye wamaphoyisa ethu osekelayo.",
            "invalid": "Inketho engalungile. Sicela ukhethe 1, 2, 3, noma 4."
        },
        "main_menu_prompt": (
            "Singakusiza njani namuhla?\n\n"
            "1. Cela intengo\n"
            "2. Sesha intengo usebenzisa indawo\n"
            "3. Bheka isimo sephrojekthi\n"
            "4. FAQs noma Funda ngeBorehole Drilling\n"
            "5. Ezinye izinsiza\n"
            "6. Khuluma nomuntu\n\n"
            "Sicela uphendule ngenombolo (isibonelo, 1)"
        ),
        "drilling_status_request_incomplete": (
            "Sicela unikeze igama lakho eligcwele nenombolo yeReferensi noma inombolo yefoni, ngayinye emugqeni ohlukile.\n\n"
            "Isibonelo:\nJohn Doe\nREF789123 noma 0779876543\nUkuzikhethela: Bulawayo"
        ),
        "drilling_status_retrieving": "Ngiyabonga. Sicela ulinde ngithole isimo sephrojekthi yakho...",
        "drilling_status_result": (
            "Nansi isimo sephrojekthi yakho yokumba borehole:\n\n"
            "Igama lePhrojekthi: Borehole - {full_name}\n"
            "Isigaba Samanje: Ukumba Kuqhubeka\n"
            "Isinyathelo Esilandelayo: Ukufaka iCasing\n"
            "Usuku Lokuphela Olulindelekile: 10/06/2025\n\n"
            "Ungathanda ukuthola izaziso zeWhatsApp uma isimo sishintsha?\nIzinketho: Yebo / Cha"
        ),
        "invalid_pump_option": "Inketho engalungile. Sicela ukhethe inketho efanele yokufaka ipampu (1-6).",
        "quote_select_another_service": (
            "Khetha enye insiza:\n"
            "1. Ukuhlola amanzi\n"
            "2. Ukumba borehole\n"
            "3. Ukufaka ipampu\n"
            "4. Ukumba indawo yokuthengisa\n"
            "5. Ukwandisa ukujula kweborehole"
        ),
        "quote_invalid_option": "Inketho engalungile. Phendula 1 ukuze ubuze ngenye insiza noma 2 ukuze ubuyele kumenyu enkulu noma 3 uma ufuna ukwenza isiphakamiso sentengo."

    }
}


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
    if -22.27 < lat < -22.16 and 29.94 < lng < 30.06:
        return "Beitbridge"
    elif -20.06 < lat < -19.95 and 31.54 < lng < 31.65:
        return "Nyika"
    elif -17.36 < lat < -17.25 and 31.28 < lng < 31.39:
        return "Bindura"
    elif -17.68 < lat < -17.57 and 27.29 < lng < 27.40:
        return "Binga"
    elif -19.58 < lat < -19.47 and 28.62 < lng < 28.73:
        return "Bubi"
    elif -19.33 < lat < -19.22 and 31.59 < lng < 31.70:
        return "Murambinda"
    elif -19.39 < lat < -19.28 and 31.38 < lng < 31.49:
        return "Buhera"
    elif -20.20 < lat < -20.09 and 28.51 < lng < 28.62:
        return "Bulawayo"
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


location_pricing = {
    "beitbridge": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
        "nyika": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1050,
            "class 9": 1181.25,
            "class 10": 1312.5,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "bindura": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "binga": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1300,
            "class 9": 1462.5,
            "class 10": 1625,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "bubi": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1200,
            "class 9": 1350,
            "class 10": 1500,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "murambinda": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1050,
            "class 9": 1181.25,
            "class 10": 1312.5,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "buhera": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1150,
            "class 9": 1293.75,
            "class 10": 1437.5,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "harare": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 30
        },       
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    },
    "bulawayo": {
        "Water Survey": 150,
        "Borehole Drilling": {
            "class 6": 1000,
            "class 9": 1125,
            "class 10": 1250,
            "included_depth_m": 40,
            "extra_per_m": 27
        },
        "Commercial Hole Drilling": 80,
        "Borehole Deepening": 30
    }
}

pump_installation_options = {
    "1": {
        "description": "D.C solar (direct solar NO inverter) - I have tank and tank stand",
        "price": 1640
    },
        "2": {
        "description": "D.C solar (direct solar NO inverter) - I don't have anything",
        "price": 2550
    },
    "3": {
        "description": "D.C solar (direct solar NO inverter) - Labour only",
        "price": 200
    },
    "4": {
        "description": "A.C electric (ZESA or solar inverter) - Fix and supply",
        "price": 1900
    },
    "5": {
        "description": "A.C electric (ZESA or solar inverter) - Labour only",
        "price": 170
    },
    "6": {
        "description": "A.C electric (ZESA or solar inverter) - I have tank and tank stand",
        "price": 950
    }
}

def get_pricing_for_location_quotes(location, service_type, pump_option_selected=None):
    location_key = location.strip().lower()
    service_key = service_type.strip().title()

    if service_key == "Pump Installation":
        if pump_option_selected is None:            
            message_lines = [f"💧 Pump Installation Options:\n"]
            for key, option in pump_installation_options.items():
                desc = option.get('description', 'No description')
                message_lines.append(f"{key}. {desc}")
            return "\n".join(message_lines)
        else:
            option = pump_installation_options.get(pump_option_selected)
            if not option:
                return "Sorry, invalid Pump Installation option selected."
            desc = option.get('description', 'No description')
            price = option.get('price', 'N/A')
            message = f"💧 Pricing for option {pump_option_selected}:\n{desc}\nPrice: ${price}\n"
            message += "\nWould you like to:\n1. Ask pricing for another service\n2. Return to Main Menu\n3. Offer Price"
            return message

    loc_data = location_pricing.get(location_key)
    if not loc_data:
        return "Sorry, pricing not available for this location."

    price = loc_data.get(service_key)
    if not price:
        return f"Sorry, pricing for {service_key} not found in {location.title()}."

    if isinstance(price, dict):
        included_depth = price.get("included_depth_m", "N/A")
        extra_rate = price.get("extra_per_m", "N/A")

        classes = {k: v for k, v in price.items() if k.startswith("class")}
        message_lines = [f"{service_key} Pricing in {location.title()}:"]
        for cls, amt in classes.items():
            message_lines.append(f"- {cls.title()}: ${amt}")
        message_lines.append(f"- Includes depth up to {included_depth}m")
        message_lines.append(f"- Extra charge: ${extra_rate}/m beyond included depth\n")
        message_lines.append("Would you like to:\n1. Ask pricing for another service\n2. Return to Main Menu\n3. Offer Price")
        return "\n".join(message_lines)

    unit = "per meter" if service_key in ["Commercial Hole Drilling", "Borehole Deepening"] else "flat rate"
    return (f"{service_key} in {location.title()}: ${price} {unit}\n\n"
            "Would you like to:\n1. Ask pricing for another service\n2. Return to Main Menu\n3. Offer Price")

# State handlers
def handle_welcome(prompt, user_data, phone_id):
    send(LANGUAGES["English"]["welcome"], user_data['sender'], phone_id)
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
        send(LANGUAGES["English"]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    elif prompt == "2":
        user.language = "Shona"
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES["Shona"]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":
        user.language = "Ndebele"
        update_user_state(user_data['sender'], {
            'step': 'main_menu',
            'user': user.to_dict()
        })
        send(LANGUAGES["Ndebele"]["main_menu"], user_data['sender'], phone_id)
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    
    else:
        send("Please select a valid language option (1 for English, 2 for Shona, 3 for Ndebele).", user_data['sender'], phone_id)
        return {'step': 'select_language', 'user': user.to_dict(), 'sender': user_data['sender']}

def handle_main_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    if prompt == "1":  # Request a quote
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["enter_location"], user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Search Price Using Location
        update_user_state(user_data['sender'], {
            'step': 'enter_location_for_quote',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["enter_location"], user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}
    
   
def human_agent_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt == "1":
        return handle_select_language("1", user_data, phone_id)
    elif prompt == "2":
        send(get_message(lang, "human_agent.exit_message"), user_data['sender'], phone_id)
        return {'step': 'human_agent_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(get_message(lang, "human_agent.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'human_agent_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole',
            'user': user.to_dict()
        })
        send(get_message(lang, "faq.borehole.menu"), user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":  # Pump Installation FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_pump',
            'user': user.to_dict()
        })
        send(get_message(lang, "faq.pump.menu"), user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "3":  # Ask a different question
        update_user_state(user_data['sender'], {
            'step': 'custom_question',
            'user': user.to_dict()
        })
        send(get_message(lang, "faq.custom_question"), user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "4":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent',
            'user': user.to_dict(),
            'sender': user_data['sender']
        })
        send(get_message(lang, "human_agent_connect"), user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "5":  # Back to Main Menu
        return handle_select_language("1", user_data, phone_id)
    else:
        send(get_message(lang, "faq.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

def custom_question(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if not prompt.strip():
        send(get_message(lang, "custom_question.empty_prompt"), user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}

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
    send(get_message(lang, "custom_question.response_followup"), user_data['sender'], phone_id)
    return {'step': 'custom_question_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def custom_question_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt == "1":
        send(get_message(lang, "custom_question.next_question"), user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)
    else:
        send(get_message(lang, "custom_question.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'custom_question_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt in get_message(lang, "faq.borehole.responses"):
        send(get_message(lang, f"faq.borehole.responses.{prompt}"), user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
        
        send(get_message(lang, "faq.borehole.followup"), user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(get_message(lang, "faq.borehole.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt == "1":
        send(get_message(lang, "faq.borehole.menu"), user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)
    else:
        send(get_message(lang, "custom_question.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_pump(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt in get_message(lang, "faq.pump.responses"):
        send(get_message(lang, f"faq.pump.responses.{prompt}"), user_data['sender'], phone_id)
        if prompt == "6":
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
        
        send(get_message(lang, "faq.pump.followup"), user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(get_message(lang, "faq.pump.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_pump_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language or "english"

    if prompt == "1":
        send(get_message(lang, "faq.pump.menu"), user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)
    else:
        send(get_message(lang, "custom_question.invalid_option"), user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_enter_location_for_quote(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    
    # Check if we have a location object from WhatsApp
    if 'location' in user_data and 'latitude' in user_data['location'] and 'longitude' in user_data['location']:
        lat = user_data['location']['latitude']
        lng = user_data['location']['longitude']
        gps_coords = f"{lat},{lng}"
        location_name = reverse_geocode_location(gps_coords)
        
        if location_name:
            user.quote_data['location'] = location_name
            user.quote_data['gps_coords'] = gps_coords
            update_user_state(user_data['sender'], {
                'step': 'select_service_quote',
                'user': user.to_dict()
            })
            send(LANGUAGES[lang]["location_detected"].format(location_name.title()), 
                 user_data['sender'], phone_id)
            return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}
        else:
            send(LANGUAGES[lang]["location_not_found"], user_data['sender'], phone_id)
            return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        # This is a text message with location name
        location_name = prompt.strip()
        user.quote_data['location'] = location_name.lower()
        update_user_state(user_data['sender'], {
            'step': 'select_service_quote',
            'user': user.to_dict()
        })
        send(LANGUAGES[lang]["location_detected"].format(location_name.title()), 
             user_data['sender'], phone_id)
        return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

def human_agent(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    customer_number = user_data['sender']
    customer_name = user.name if hasattr(user, "name") and user.name else "Unknown"
    agent_number = "+263719835124"
    lang = get_user_language(user_data)

    # Notify the customer immediately
    send(LANGUAGES[lang]['agent_connect'], customer_number, phone_id)

    # Notify the agent immediately
    agent_message = LANGUAGES[lang]['agent_notification'].format(
        customer_number=customer_number,
        customer_name=customer_name,
        prompt=prompt
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

def notify_agent(customer_number, prompt, agent_number, phone_id, lang='en'):
    agent_message = LANGUAGES[lang]['new_request'].format(
        customer_number=customer_number,
        prompt=prompt
    )
    send(agent_message, agent_number, phone_id)

def send_fallback_option(customer_number, phone_id, user_data):
    # Check if still waiting
    user_data = get_user_state(customer_number)
    if user_data and user_data.get('step') == 'waiting_for_human_agent_response':
        lang = get_user_language(user_data)
        send(LANGUAGES[lang]['fallback_option'].format(agent_number="+263719835124"), 
             customer_number, phone_id)
        send(LANGUAGES[lang]['followup_question'], customer_number, phone_id)
        update_user_state(customer_number, {
            'step': 'human_agent_followup',
            'user': user_data.get('user', {}),
            'sender': customer_number
        })

def handle_user_message(message, user_data, phone_id):
    state = user_data.get('step')
    customer_number = user_data['sender']
    lang = get_user_language(user_data)

    if state == 'waiting_for_human_agent_response':
        prompt_time = user_data.get('agent_prompt_time', 0)
        elapsed = time.time() - prompt_time

        if elapsed >= 10:
            # Send fallback prompt
            send(LANGUAGES[lang]['fallback_option'].format(agent_number="+263719835124"), 
                 customer_number, phone_id)
            send(LANGUAGES[lang]['followup_question'], customer_number, phone_id)

            # Update state to wait for user's Yes/No reply
            update_user_state(customer_number, {
                'step': 'human_agent_followup',
                'user': user_data['user'],
                'sender': customer_number
            })

            return {'step': 'human_agent_followup', 'user': user_data['user'], 'sender': customer_number}
        else:
            # Still waiting, remind user to hold on
            send(LANGUAGES[lang]['still_waiting'], customer_number, phone_id)
            return user_data

    elif state == 'human_agent_followup':
        # Handle user's Yes/No answer here
        if message.strip() == '1':  # User wants main menu
            send(LANGUAGES[lang]['return_menu'], customer_number, phone_id)
            # Reset state to main menu step
            update_user_state(customer_number, {
                'step': 'main_menu',
                'user': user_data['user'],
                'sender': customer_number
            })
            # Show main menu (assuming send_main_menu also supports languages)
            send_main_menu(customer_number, phone_id, lang)
            return {'step': 'main_menu', 'user': user_data['user'], 'sender': customer_number}

        elif message.strip() == '2':  # User says No
            send(LANGUAGES[lang]['goodbye'], customer_number, phone_id)
            # Optionally clear or end session
            update_user_state(customer_number, {
                'step': 'end',
                'user': user_data['user'],
                'sender': customer_number
            })
            return {'step': 'end', 'user': user_data['user'], 'sender': customer_number}
        else:
            send(LANGUAGES[lang]['invalid_option'], customer_number, phone_id)
            return user_data

def human_agent_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'

    if prompt == "1":
        return handle_select_language("1", user_data, phone_id)
    elif prompt == "2":
        send(get_message(lang, 'human_agent_followup', 'stay_here'), user_data['sender'], phone_id)
        return {'step': 'human_agent_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(get_message(lang, 'human_agent_followup', 'invalid_option'), user_data['sender'], phone_id)
        return {'step': 'human_agent_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'

    if prompt == "1":  # Borehole Drilling FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_borehole',
            'user': user.to_dict()
        })
        send(get_message(lang, 'faq_menu', 'borehole_faqs'), user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":  # Pump Installation FAQs
        update_user_state(user_data['sender'], {
            'step': 'faq_pump',
            'user': user.to_dict()
        })
        send(get_message(lang, 'faq_menu', 'pump_faqs'), user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":  # Ask a different question
        update_user_state(user_data['sender'], {
            'step': 'custom_question',
            'user': user.to_dict()
        })
        send(get_message(lang, 'faq_menu', 'custom_question'), user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":  # Human agent
        update_user_state(user_data['sender'], {
            'step': 'human_agent',
            'user': user.to_dict(),
            'sender': user_data['sender']
        })
        send(get_message(lang, 'faq_menu', 'connecting_agent'), user_data['sender'], phone_id)
        return {'step': 'human_agent', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "5":  # Back to Main Menu
        return handle_select_language("1", user_data, phone_id)

    else:
        send(get_message(lang, 'faq_menu', 'invalid_option'), user_data['sender'], phone_id)
        return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

def custom_question(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'

    if not prompt.strip():
        send(get_message(lang, 'custom_question', 'empty_prompt'), user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}

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
    send(get_message(lang, 'custom_question', 'follow_up'), user_data['sender'], phone_id)
    return {'step': 'custom_question_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def custom_question_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'

    if prompt == "1":
        send(get_message(lang, 'custom_question', 'next_question'), user_data['sender'], phone_id)
        return {'step': 'custom_question', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)
    else:
        send("Please reply 1 to ask another question or 2 to return to the main menu.", user_data['sender'], phone_id)
        return {'step': 'custom_question_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'
    responses = get_message(lang, 'faq_borehole', 'responses')

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "8":
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(get_message(lang, 'faq_borehole', 'follow_up'), user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(get_message(lang, 'faq_borehole', 'invalid_option'), user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_borehole_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'

    if prompt == "1":
        send(get_message(lang, 'faq_menu', 'borehole_faqs'), user_data['sender'], phone_id)
        return {'step': 'faq_borehole', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)
    else:
        send(get_message(lang, 'faq_borehole_followup', 'invalid_option'), user_data['sender'], phone_id)
        return {'step': 'faq_borehole_followup', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_pump(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'
    responses = get_message(lang, 'faq_pump', 'responses')

    if prompt in responses:
        send(responses[prompt], user_data['sender'], phone_id)
        if prompt == "6":
            return {'step': 'faq_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

        send(get_message(lang, 'faq_pump', 'follow_up'), user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(get_message(lang, 'faq_pump', 'invalid_option'), user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}

def faq_pump_followup(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language if hasattr(user, 'language') else 'en'

    if prompt == "1":
        send(get_message(lang, 'faq_menu', 'pump_faqs'), user_data['sender'], phone_id)
        return {'step': 'faq_pump', 'user': user.to_dict(), 'sender': user_data['sender']}
    elif prompt == "2":
        return handle_select_language("1", user_data, phone_id)
    else:
        send(get_message(lang, 'faq_pump_followup', 'invalid_option'), user_data['sender'], phone_id)
        return {'step': 'faq_pump_followup', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_select_service_quote(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user.language
    location = user.quote_data.get('location')
    
    if not location:
        send("Please provide your location first before selecting a service.", user_data['sender'], phone_id)
        return {'step': 'enter_location_for_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

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
        return {'step': 'select_service_quote', 'user': user.to_dict(), 'sender': user_data['sender']}

    user.quote_data['service'] = selected_service

    if selected_service == "Pump Installation":
        update_user_state(user_data['sender'], {
            'step': 'select_pump_option',
            'user': user.to_dict()
        })
        message_lines = [f"💧 Pump Installation Options:\n"]
        for key, option in pump_installation_options.items():
            desc = option.get('description', 'No description')
            message_lines.append(f"{key}. {desc}")
        send("\n".join(message_lines), user_data['sender'], phone_id)
        return {'step': 'select_pump_option', 'user': user.to_dict(), 'sender': user_data['sender']}

    pricing_message = get_pricing_for_location_quotes(location, selected_service)
    
    update_user_state(user_data['sender'], {
        'step': 'quote_followup',
        'user': user.to_dict()
    })
    send(pricing_message, user_data['sender'], phone_id)

    return {
        'step': 'quote_followup',
        'user': user.to_dict(),
        'sender': user_data['sender']
    }


def handle_service_flow(prompt, user_data, phone_id):
    user = user_data['user']
    lang = user.get('language', 'en')

    services = {
        "1": "Water survey",
        "2": "Borehole drilling",
        "3": "Pump installation",
        "4": "Commercial hole drilling",
        "5": "Borehole Deepening",
    }

    step = user_data.get('step', 'select_service')

    if step == 'select_service':
        if prompt in services:
            user['quote_data'] = {"service": services[prompt]}
            user_data.update({'step': 'collect_quote_details', 'user': user})
            send(LANGUAGES[lang]["quote_intro"], user_data['sender'], phone_id)
        else:
            send(LANGUAGES[lang]["select_valid_service"], user_data['sender'], phone_id)

    elif step == 'collect_quote_details':
        user['quote_data']['location'] = prompt
        user_data.update({'step': 'quote_response', 'user': user})

        quote_summary = f"Service: {user['quote_data'].get('service')}\nLocation: {user['quote_data'].get('location')}"
        message = LANGUAGES[lang]["quote_thank_you"].format(quote_summary)
        send(message, user_data['sender'], phone_id)

    elif step == 'quote_response':
        if prompt == "1":
            user_data.update({'step': 'enter_offer_price', 'user': user})
            send("How much are you willing to offer?", user_data['sender'], phone_id)
        elif prompt == "2":
            user_data.update({'step': 'book_site_survey', 'user': user})
            send("Please share the date you’d like us to come for a survey.", user_data['sender'], phone_id)
        elif prompt == "3":
            user_data.update({'step': 'book_drilling', 'user': user})
            send("Please share the date you'd like us to drill.", user_data['sender'], phone_id)
        elif prompt == "4":
            send(LANGUAGES[lang]["agent_connect"], user_data['sender'], phone_id)
            user_data.update({'step': 'human_agent', 'user': user})
        else:
            send(LANGUAGES[lang]["select_valid_option"], user_data['sender'], phone_id)

    elif step == 'enter_offer_price':
        user['quote_data']['offer_price'] = prompt
        send("Thank you! We've noted your offer. We'll get back to you soon.", user_data['sender'], phone_id)
        user_data.update({'step': 'done', 'user': user})

    elif step == 'book_site_survey':
        user['quote_data']['survey_date'] = prompt
        send("Thanks! We've booked your site survey. We’ll confirm shortly.", user_data['sender'], phone_id)
        user_data.update({'step': 'done', 'user': user})

    elif step == 'book_drilling':
        user['quote_data']['drill_date'] = prompt
        send("Thank you! We've noted your drilling date. Our team will follow up.", user_data['sender'], phone_id)
        user_data.update({'step': 'done', 'user': user})

    elif step == 'human_agent':
        send("An agent will join the chat shortly.", user_data['sender'], phone_id)

    return user_data




def handle_pump_status_updates_opt_in(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()
    lang = user_data.get('lang', 'en')

    yes_responses = {'en': ['yes', 'y'], 'sn': ['ehe', 'y'], 'nd': ['yebo', 'y']}
    no_responses = {'en': ['no', 'n'], 'sn': ['kwete', 'k'], 'nd': ['cha', 'c']}

    if response in yes_responses.get(lang, ['yes', 'y']):
        send(get_lang_text(user_data, 'pump_updates_yes'), user_data['sender'], phone_id)
    elif response in no_responses.get(lang, ['no', 'n']):
        send(get_lang_text(user_data, 'pump_updates_no'), user_data['sender'], phone_id)
    else:
        send(get_lang_text(user_data, 'pump_updates_invalid'), user_data['sender'], phone_id)
        return {'step': 'pump_status_updates_opt_in', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {'step': None, 'user': user.to_dict()})
    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_drilling_status_updates_opt_in(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    response = prompt.strip().lower()
    lang = user_data.get('lang', 'en')

    yes_responses = {'en': ['yes', 'y'], 'sn': ['ehe', 'y'], 'nd': ['yebo', 'y']}
    no_responses = {'en': ['no', 'n'], 'sn': ['kwete', 'k'], 'nd': ['cha', 'c']}

    if response in yes_responses.get(lang, ['yes', 'y']):
        send(get_lang_text(user_data, 'pump_updates_yes'), user_data['sender'], phone_id)
    elif response in no_responses.get(lang, ['no', 'n']):
        send(get_lang_text(user_data, 'pump_updates_no'), user_data['sender'], phone_id)
    else:
        send(get_lang_text(user_data, 'pump_updates_invalid'), user_data['sender'], phone_id)
        return {'step': 'drilling_status_updates_opt_in', 'user': user.to_dict(), 'sender': user_data['sender']}

    update_user_state(user_data['sender'], {'step': None, 'user': user.to_dict()})
    return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_check_project_status_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user_data.get('lang', 'en')

    options = get_lang_text(user_data, 'check_status_menu_options')

    if prompt == "1":
        update_user_state(user_data['sender'], {'step': 'drilling_status_info_request', 'user': user.to_dict()})
        send(options["1"], user_data['sender'], phone_id)
        return {'step': 'drilling_status_info_request', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        update_user_state(user_data['sender'], {'step': 'pump_status_info_request', 'user': user.to_dict()})
        send(options["2"], user_data['sender'], phone_id)
        return {'step': 'pump_status_info_request', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":
        send(options["3"], user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': None, 'user': user.to_dict()})
        return {'step': None, 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "4":
        # Return to main menu
        send(get_lang_text(user_data, 'main_menu_prompt'), user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'main_menu', 'user': user.to_dict()})
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}
    else:
        send(options.get("invalid", "Invalid option. Please try again."), user_data['sender'], phone_id)
        return {'step': 'check_project_status_menu', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_drilling_status_info_request(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user_data.get('lang', 'en')

    # We expect at least two lines: full name and ref number or phone number
    lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]
    if len(lines) < 2:
        send(get_lang_text(user_data, 'drilling_status_request_incomplete'), user_data['sender'], phone_id)
        return {'step': 'drilling_status_info_request', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Here you'd lookup project info in database using lines[0], lines[1] (and optional lines[2])
    # Dummy response:
    full_name = lines[0]
    # After lookup, respond with status and ask opt-in for updates
    send(get_lang_text(user_data, 'drilling_status_retrieving'), user_data['sender'], phone_id)
    import time; time.sleep(1)  # simulate delay

    send(get_lang_text(user_data, 'drilling_status_result', full_name=full_name), user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'drilling_status_updates_opt_in', 'user': user.to_dict()})

    return {'step': 'drilling_status_updates_opt_in', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_pump_installation_option(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user_data.get('lang', 'en')

    valid_options = {"1", "2", "3", "4", "5", "6"}
    if prompt not in valid_options:
        send(get_lang_text(user_data, 'invalid_pump_option'), user_data['sender'], phone_id)
        return {'step': 'pump_installation_option', 'user': user.to_dict(), 'sender': user_data['sender']}

    # Process selection, e.g., send pricing or next steps
    # For demo, just send a confirmation
    send(f"Pump installation option {prompt} selected.", user_data['sender'], phone_id)

    # Then maybe return to main menu or another step
    send(get_lang_text(user_data, 'main_menu_prompt'), user_data['sender'], phone_id)
    update_user_state(user_data['sender'], {'step': 'main_menu', 'user': user.to_dict()})
    return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}


def handle_quote_menu(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    lang = user_data.get('lang', 'en')

    if prompt == "1":
        send(get_lang_text(user_data, 'quote_select_another_service'), user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'quote_select_service', 'user': user.to_dict()})
        return {'step': 'quote_select_service', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "2":
        send(get_lang_text(user_data, 'main_menu_prompt'), user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'main_menu', 'user': user.to_dict()})
        return {'step': 'main_menu', 'user': user.to_dict(), 'sender': user_data['sender']}

    elif prompt == "3":
        send("Please provide your price offer for the service.", user_data['sender'], phone_id)
        update_user_state(user_data['sender'], {'step': 'quote_price_offer', 'user': user.to_dict()})
        return {'step': 'quote_price_offer', 'user': user.to_dict(), 'sender': user_data['sender']}

    else:
        send(get_lang_text(user_data, 'quote_invalid_option'), user_data['sender'], phone_id)
        return {'step': 'quote_menu', 'user': user.to_dict(), 'sender': user_data['sender']}


def get_lang_text(user, key, **kwargs):
    lang = user.language or 'english'
    template = LANGUAGES.get(lang, LANGUAGES['english']).get(key, '')
    if subkey:
        text = lang_dict.get(key, {}).get(subkey, "")
    else:
        text = lang_dict.get(key, "")
    if kwargs:
        return text.format(**kwargs)
    return text


def handle_flushing_location(prompt, user_data, phone_id):
    user = User.from_dict(user_data['user'])
    location = prompt.strip()
    user.quote_data['location'] = location

    flushing_type = user.quote_data.get('flushing_type')
    diameter = user.quote_data.get('diameter')

    price = get_pricing_for_other_services(location, "borehole_flushing", {
        'flushing_type': flushing_type,
        'diameter': diameter
    })

    message = get_lang_text(user, 'flushing_cost', location=location, price=price)
    send(message, user_data['sender'], phone_id)

    update_user_state(user_data['sender'], {'step': 'flushing_booking_confirm', 'user': user.to_dict()})
    return {'step': 'flushing_booking_confirm', 'user': user.to_dict(), 'sender': user_data['sender']}




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

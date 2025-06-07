
from flask import Flask, request, jsonify
from english import handle_welcome as handle_welcome_en, handle_select_language as handle_select_language_en, get_user_state as get_user_state_en, update_user_state as update_user_state_en
from shona import handle_welcome2, handle_select_language2, get_user_state2, update_user_state2
from ndebele import handle_welcome as handle_welcome_nd, handle_select_language as handle_select_language_nd, get_user_state3, update_user_state3

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    sender = data['entry'][0]['changes'][0]['value']['messages'][0]['from']
    prompt = data['entry'][0]['changes'][0]['value']['messages'][0]['text']['body']

    # Use English Redis for global state
    user_state = get_user_state_en(sender)
    step = user_state.get("step", "welcome")

    if step == "welcome":
        return jsonify(handle_welcome_en(prompt, user_state, user_state.get("phone_id", "PHONE_ID")))
    elif step == "select_language":
        return jsonify(handle_select_language_en(prompt, user_state, user_state.get("phone_id", "PHONE_ID")))
    elif step == "select_language2":
        return jsonify(handle_select_language2(prompt, user_state, user_state.get("phone_id", "PHONE_ID")))
    elif step == "select_language3":
        return jsonify(handle_select_language_nd(prompt, user_state, user_state.get("phone_id", "PHONE_ID")))
    elif step.startswith("main_menu2") or "2" in step:
        from shona import handle_main_menu2
        return jsonify(handle_main_menu2(prompt, user_state, user_state.get("phone_id", "PHONE_ID")))
    elif step.startswith("main_menu3") or "3" in step:
        from ndebele import handle_main_menu3
        return jsonify(handle_main_menu3(prompt, user_state, user_state.get("phone_id", "PHONE_ID")))
    else:
        from english import handle_main_menu
        return jsonify(handle_main_menu(prompt, user_state, user_state.get("phone_id", "PHONE_ID")))

if __name__ == '__main__':
    app.run(debug=True)

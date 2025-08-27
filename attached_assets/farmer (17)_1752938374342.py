import logging
import time
from collections import deque

logger = logging.getLogger(__name__)

# Placeholder for existing farmer.py code.  Replace this with the actual code.
# ... (rest of farmer.py code, assuming it contains a loop processing SOCF data) ...

# Example of how object detection might be handled in farmer.py
def process_socf_data(data):
    # ... (SOCF data processing logic) ...
    obj_type = "Cow"  # Example object type
    code = "12345"  # Example code
    level = "High"  # Example level
    loc = "Barn"  # Example location
    status = "Detected"  # Example status

    logger.info(f"Found {obj_type} - Code: {code}, Level: {level}, Location: {loc}, Status: {status}")

    # Add to web app's scanned objects queue
    try:
        from web_app import add_to_queue
        object_data = {
            'type': obj_type,
            'code': code,
            'level': level,
            'location': loc,
            'status': status,
            'time': time.strftime('%H:%M:%S'),
            'id': str(uuid.uuid4())
        }
        add_to_queue(object_data)
        logger.info(f"Successfully added object to web queue: {object_data}")
    except Exception as e:
        logger.error(f"Failed to add object to web queue: {str(e)}")



def handle_object_detection(code, level, loc, is_occupied, config):
    # ... other code ...

    # 3. Level 2+ Dragon Soul Caverns (only if not occupied)
    if code == 20100106 and level >= 2 and not is_occupied and config.get('discord', {}).get('dragon_soul_level2plus_webhook_url'):
        from discord_webhook import DiscordWebhook # Assuming this import is needed
        dragon_soul_webhook = DiscordWebhook(config.get('discord', {}).get('dragon_soul_level2plus_webhook_url'))
        dragon_soul_webhook.send_object_log(
            f"Dragon Soul Cavern (Level {level})",
            code,
            level,
            loc,
            'Available',
            ""
        )
    # ... rest of handle_object_detection function ...


# ... (rest of farmer.py code) ...


# Dummy web_app.py (replace with your actual web app)
from flask import Flask, jsonify
import threading

app = Flask(__name__)
app.scanned_objects = deque(maxlen=100) #Example queue size
lock = threading.Lock() # Add a lock for thread safety

@app.route('/status')
def get_status():
    with lock: # Acquire lock before accessing the queue
        return jsonify({'scanned_objects': list(app.scanned_objects)})

def add_to_queue(object_data):
    with lock: # Acquire lock before adding to the queue
        app.scanned_objects.appendleft(object_data)

if __name__ == '__main__':
    app.run(debug=True)
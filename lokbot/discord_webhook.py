import json
import httpx
from loguru import logger


class DiscordWebhook:

    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.client = httpx.Client()

    def send_message(self, content, embed=None, update_type=None):
        """
        Send a message to Discord webhook and web interface
        """
        # Send to web interface if update_type is provided
        if update_type and hasattr(app, 'add_bot_update'):
            from web_app import add_bot_update
            add_bot_update(update_type, update_type.title(), content)

        payload = {"content": content}

        if embed:
            payload["embeds"] = [embed]

        logger.info(f"Sending Discord webhook to {self.webhook_url}")

        try:
            response = self.client.post(self.webhook_url, json=payload, timeout=10.0)

            if response.status_code != 204:
                logger.error(
                    f"Failed to send Discord webhook: {response.status_code} {response.text}"
                )
                return False

            logger.info("Discord webhook sent successfully")
            return True

        except Exception as e:
            logger.error(f"Exception while sending Discord webhook: {str(e)}")
            return False

    def send_object_log(self,
                        obj_type,
                        code,
                        level,
                        location,
                        status,
                        occupied_info=""):
        """
        Send formatted object log to Discord
        """
        # Set color based on status
        if "Available" in status:
            color = 0x00FF00  # Green color
        else:
            color = 0xFF0000  # Red color for occupied

        # Set title and thumbnail based on type
        if "Crystal Mine" in obj_type:
            title = "**Crystal Mine Found!**"
            thumbnail_url = "https://media.discordapp.net/attachments/1351881630825840725/1352589455177027635/crystal_mine.png"
        elif "Dragon Soul Cavern" in obj_type:
            title = "**Dragon Soul Cavern Found!**"
            thumbnail_url = "https://media.discordapp.net/attachments/1351881630825840725/1352589526786379776/dragon_soul.png"
        else:
            title = "Resource Found"

        embed = {
            "title": title,
            "description": f"**Type:** {obj_type}",
            "color":
            color,
            "thumbnail": {
                "url": thumbnail_url
            },
            "fields": [{
                "name": "Code",
                "value": str(code),
                "inline": True
            }, {
                "name": "Level",
                "value": str(level),
                "inline": True
            }, {
                "name": "Location",
                "value": str(location),
                "inline": True
            }, {
                "name": "Status",
                "value": status,
                "inline": True
            }]
        }

        if occupied_info:
            embed[
                "description"] = f"**Occupied Information:**\n{occupied_info}"

        return self.send_message("", embed)

    def send_all_resources(self,
                           obj_type,
                           code,
                           level,
                           location,
                           status,
                           occupied_info=""):
        """
        Send all resources to a separate webhook regardless of type or level
        """
        # Set color based on status
        if "Available" in status:
            color = 0x00FF00  # Green color
        else:
            color = 0xFF0000  # Red color for occupied

        # Set title and thumbnail based on type
        if "Crystal Mine" in obj_type:
            title = "**Crystal Mine Found!**"
            thumbnail_url = "https://media.discordapp.net/attachments/1349663748339531837/1350496588614602752/crystal_mine.png"
        elif "Dragon Soul Cavern" in obj_type:
            title = "**Dragon Soul Cavern Found!**"
            thumbnail_url = "https://media.discordapp.net/attachments/1349663748339531837/1350496589139148810/dragon_soul.png"
        else:
            title = "Resource Found"

        embed = {
            "title": title,
            "description": f"**Type:** {obj_type}",
            "color":
            color,
            "thumbnail": {
                "url": thumbnail_url
            },
            "fields": [{
                "name": "Code",
                "value": str(code),
                "inline": True
            }, {
                "name": "Level",
                "value": str(level),
                "inline": True
            }, {
                "name": "Location",
                "value": str(location),
                "inline": True
            }, {
                "name": "Status",
                "value": status,
                "inline": True
            }]
        }

        if occupied_info:
            embed[
                "description"] = f"**Occupied Information:**\n{occupied_info}"

        return self.send_message("", embed)
import json
import logging
import time
from typing import Optional, Dict, Any
import requests
import os
from datetime import datetime

logger = logging.getLogger(__name__)

class DiscordWebhook:
    """Simple Discord webhook client with rate limiting and improved error handling"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.last_send_time = 0
        self.min_interval = 2.0  # Minimum 2 seconds between messages

    def send_message(self, content: str, embed: Optional[Dict[str, Any]] = None) -> bool:
        """Send a message to Discord with rate limiting"""
        # Also send to web app if available
        try:
            import os
            user_id = os.getenv('LOKBOT_USER_ID', 'web_user')
            instance_id = os.getenv('LOKBOT_INSTANCE_ID')
            account_name = os.getenv('LOKBOT_ACCOUNT_NAME')
            
            # Try to find and use the notification function
            try:
                import sys

                # Try to get the web_app module if it's available
                if 'web_app' in sys.modules:
                    web_app = sys.modules['web_app']
                    if hasattr(web_app, 'add_notification'):
                        # Parse content to determine notification type
                        content_lower = content.lower()
                        if "rally joined" in content_lower or "joined rally" in content_lower:
                            web_app.add_notification(user_id, "rally_join", "Rally Joined", content, account_name=account_name, instance_id=instance_id)
                        elif "rally started" in content_lower or "started rally" in content_lower:
                            web_app.add_notification(user_id, "rally_start", "Rally Started", content, account_name=account_name, instance_id=instance_id)
                        elif "gathering" in content_lower and "started" in content_lower:
                            web_app.add_notification(user_id, "gathering", "Gathering Started", content, account_name=account_name, instance_id=instance_id)
                        elif "crystal mine" in content_lower:
                            web_app.add_notification(user_id, "crystal_mine", "Crystal Mine Found", content, account_name=account_name, instance_id=instance_id)
                        elif "dragon soul" in content_lower:
                            web_app.add_notification(user_id, "dragon_soul", "Dragon Soul Found", content, account_name=account_name, instance_id=instance_id)
                        elif "monster attack" in content_lower:
                            web_app.add_notification(user_id, "monster_attack", "Monster Attack", content, account_name=account_name, instance_id=instance_id)
                        else:
                            web_app.add_notification(user_id, "bot_update", "Bot Update", content, account_name=account_name, instance_id=instance_id)
            except Exception as import_error:
                # Fallback: try to write to a shared file that web app can read
                try:
                    import json
                    from datetime import datetime

                    notification = {
                        'user_id': user_id,
                        'type': 'discord_message',
                        'title': 'Bot Update',
                        'message': content,
                        'timestamp': datetime.now().isoformat()
                    }

                    # Write to a notifications file
                    os.makedirs('data', exist_ok=True)
                    with open(f'data/notifications_{user_id}.json', 'a') as f:
                        f.write(json.dumps(notification) + '\n')
                except Exception:
                    pass  # If all else fails, just continue

        except Exception as e:
            # Don't let web app notification failures affect Discord sending
            pass

        if not self.webhook_url:
            logger.warning("No webhook URL provided")
            return False

        # Rate limiting: Wait if needed to respect the minimum interval
        now = time.time()
        time_since_last = now - self.last_send_time
        if time_since_last < self.min_interval:
            time.sleep(self.min_interval - time_since_last)

        # Limit message length to prevent Discord API issues
        if len(content) > 2000:
            logger.warning(f"Message too long ({len(content)} chars), truncating to 2000 chars")
            content = content[:1997] + "..."

        # Prepare payload
        payload = {"content": content}
        if embed:
            payload["embeds"] = [embed]

        # Send with retries
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )

                if response.status_code == 429:  # Rate limited
                    retry_after = 5
                    try:
                        retry_after = response.json().get('retry_after', retry_delay)
                    except Exception:
                        pass

                    logger.warning(f"Rate limited by Discord. Retrying after {retry_after} seconds")
                    time.sleep(retry_after)
                    continue

                if response.status_code >= 400:
                    if response.status_code == 404:
                        logger.warning(f"Discord webhook not found (404) - webhook may be invalid or deleted")
                    else:
                        logger.error(f"Discord webhook error {response.status_code}: {response.text}")
                    return False

                # Success
                self.last_send_time = time.time()
                return True

            except Exception as e:
                logger.error(f"Failed to send Discord webhook: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    return False

        return False

    def send_object_log(self, object_type: str, code: int, level: int, loc: list, 
                         status: str, occupied_info: str = "") -> bool:
        """Send formatted object log to Discord"""
        try:
            message = f"**{object_type}**\n"
            message += f"**Code:** {code}\n"
            message += f"**Level:** {level}\n" 
            message += f"**Location:** {loc}\n"
            message += f"**Status:** {status}\n"

            if occupied_info:
                message += f"**Details:**\n{occupied_info}"

            return self.send_message(message)
        except Exception as e:
            logger.error(f"Error formatting object log: {str(e)}")
            return False

    def send_chat_message(self, sender: str, message: str, channel: str) -> bool:
        """Send in-game chat message notification"""
        try:
            # Format a simple message to avoid Discord API issues
            formatted_message = f"**{sender}** ({channel}): {message}"
            return self.send_message(formatted_message)
        except Exception as e:
            logger.error(f"Error sending chat notification: {str(e)}")
            return False

    def send_status_update(self, status_updates: dict) -> bool:
        """Send bot status update notification"""
        try:
            status_text = "🤖 Bot Status Update:\n\n"
            for system, status in status_updates.items():
                status_text += f"**{system}**: {status}\n"

            return self.send_message(status_text)
        except Exception as e:
            logger.error(f"Error sending status update: {str(e)}")
            return False

    def send_rally_join(self, monster_name: str, monster_level: int, troops_sent: int, troop_type: str, user_id: str = None) -> bool:
        """Send rally join notification in simplified format"""
        try:
            # Map monster codes to correct names if monster_name is a number
            monster_names = {
                "20700506": "Spartoi",
                "20200205": "Magdar", 
                "20200301": "Kratt",
                "20200201": "Deathkar"
            }
            # If monster_name is a monster code string, get the proper name
            if str(monster_name) in monster_names:
                monster_name = monster_names[str(monster_name)]

            # Keep message very simple and short to avoid Discord issues
            if user_id:
                message = f"User <@{user_id}> - Rally Joined - {monster_name} - Level {monster_level}, Troops sent {troops_sent} {troop_type}"
            else:
                message = f"Rally Joined - {monster_name} - Level {monster_level}, Troops sent {troops_sent} {troop_type}"

            return self.send_message(message)
        except Exception as e:
            logger.error(f"Error formatting rally join notification: {str(e)}")
            return False

    def get_troop_name(self, troop_code):
        """Get troop name from troop code using the assets/troop.json data"""
        import json
        import os
        from pathlib import Path

        try:
            troop_file = Path(__file__).parent / "assets" / "troop.json"
            with open(troop_file, 'r') as f:
                troops = json.load(f)
                for troop in troops:
                    if troop.get('code') == troop_code:
                        return troop.get('name', 'Unknown').title()
        except Exception as e:
            print(f"Error loading troop data: {e}")
        return 'Unknown'

    def get_troop_tier(self, troop_code):
        """Get troop tier from troop code"""
        if not troop_code:
            return "Unknown"

        tier_map = {
            1: "T1",
            2: "T2", 
            3: "T3",
            4: "T4",
            5: "T5",
            6: "T6"
        }

        try:
            # Extract tier from code (last digit)
            tier = int(str(troop_code)[-1])
            return tier_map.get(tier, "Unknown")
        except:
            return "Unknown"

    def send_rally_started(self, monster_name, level, march_troops, troop_type=""):
        """Send notification when rally is started"""
        total_troops = sum(troop.get('amount', 0) for troop in march_troops)

        # Get name of first troop type being sent
        troop_name = "Unknown"
        if march_troops and len(march_troops) > 0:
            first_troop = march_troops[0]
            troop_code = first_troop.get('code')
            troop_name = self.get_troop_name(troop_code)
            troop_type = self.get_troop_tier(troop_code)

        message = f"Rally Started - {monster_name} - Level {level} - {total_troops} {troop_name} {troop_type}"
        return self.send_message(message)

def send_rally_to_discord_by_code(embed, code, config=None):
    """Send a rally message to Discord"""
    try:
        if config is None:
            config = ConfigHelper.load_config()

        webhook_url = config.get('discord', {}).get('rally_webhook_url')
        if not webhook_url:
            logger.debug("Rally webhook URL not configured")
            return

        if embed is None:
            logger.warning("Embed is None")
            return

        payload = {"embeds": [embed]}

        # Use the 'requests' module to send the POST request
        response = requests.post(webhook_url, json=payload)
        if response.status_code == 204:
            logger.debug("Rally message sent to Discord successfully")
        else:
            logger.warning(f"Failed to send rally message to Discord: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending rally message to Discord: {str(e)}")

def send_notification_to_web(user_id, notification_type, title, message):
    """Send notification to web interface"""
    try:
        import requests
        notification_data = {
            'user_id': user_id,
            'type': notification_type,
            'title': title,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }

        # Try to send to web app notification endpoint
        try:
            if notification_type == 'gathering':
                requests.post('http://localhost:5000/api/gathering_notification', 
                            json=notification_data, timeout=1)
            else:
                requests.post('http://localhost:5000/api/object_notification', 
                            json=notification_data, timeout=1)
        except requests.exceptions.RequestException:
            # Web app might not be running, just log it
            logger.debug(f"Could not send web notification for {user_id}: {message}")

        # Also write to file as backup
        try:
            notification_file = f'data/notifications_{user_id}.json'
            with open(notification_file, 'a') as f:
                import json
                f.write(json.dumps(notification_data) + '\n')
        except:
            pass

    except Exception as e:
        logger.debug(f"Error sending web notification: {str(e)}")
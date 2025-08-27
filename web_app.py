import os
import json
import subprocess
import threading
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import requests
import os
from urllib.parse import urlencode
from lokbot.client import LokBotApi
from lokbot.config_helper import ConfigHelper
import lokbot.util
import queue
import time
import schedule
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import uuid
from functools import wraps

# Replit environment setup
def setup_replit_environment():
    """Setup environment for Replit deployment"""
    # Create necessary directories
    os.makedirs('data', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)

    # Ensure users.txt exists
    if not os.path.exists('users.txt'):
        with open('users.txt', 'w') as f:
            f.write('admin:admin123:10\n')

    # Check for required environment variables
    required_vars = ['LOK_EMAIL', 'LOK_PASSWORD']
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        print(f"⚠️  Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set these in the Replit Secrets tab")

    return len(missing_vars) == 0

# Initialize Replit environment
setup_replit_environment()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Bot processes dictionary to track running instances
bot_processes = {}

# Notification system
notification_queues = {}  # user_id -> queue
notifications_history = {}  # user_id -> {account_name: list of notifications}
account_notifications = {}  # user_id -> {account_name: notification_queue}

# Status cache variables
statusCache = None
lastStatusUpdate = 0
isRefreshing = False

# Scheduling system
scheduler = BackgroundScheduler()
scheduled_tasks = {}  # task_id -> task_info
maintenance_mode = {'enabled': False, 'message': 'System under maintenance', 'scheduled_end': None}

# Temporary test accounts system
temp_test_accounts = {}  # test_id -> {created_at, expires_at, active_sessions}

def cleanup_old_notifications():
    """Clean up notifications older than 7 days to prevent memory bloat"""
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
        cutoff_timestamp = cutoff_date.isoformat()

        cleaned_count = 0
        for user_id, user_notifications in notifications_history.items():
            for account_name, notifications in user_notifications.items():
                original_count = len(notifications)
                # Keep only notifications from the last 7 days
                notifications_history[user_id][account_name] = [
                    n for n in notifications 
                    if n.get('timestamp', '') > cutoff_timestamp
                ]
                cleaned_count += original_count - len(notifications_history[user_id][account_name])

        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} old notifications (older than 7 days)")
    except Exception as e:
        logger.error(f"Error during notification cleanup: {str(e)}")

# Initialize scheduler
scheduler.start()

# Schedule notification cleanup to run every 6 hours
scheduler.add_job(
    cleanup_old_notifications,
    'interval',
    hours=6,
    id='cleanup_notifications',
    replace_existing=True
)

# User management file
USER_FILE = "users.txt"
USER_INSTANCES_FILE = "user_instances.txt"

# Login history tracking
login_history = {}  # user_id -> list of login records
active_sessions = {}  # session_id -> session info

def load_users():
    """Load users from file"""
    users = {}
    try:
        if os.path.exists(USER_FILE):
            with open(USER_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split(':')
                        if len(parts) >= 3:
                            username, password, max_instances = parts[0], parts[1], int(parts[2])
                            # Default role assignment
                            role = 'user'
                            start_date = None
                            end_date = None
                            created_date = None

                            if len(parts) >= 4:
                                role = parts[3]
                            elif username == 'admin':
                                role = 'super_admin'  # Legacy admin becomes super_admin

                            # Handle optional dates (format: username:password:max_instances:role:start_date:end_date:created_date)
                            if len(parts) >= 5 and parts[4]:
                                start_date = parts[4]
                            if len(parts) >= 6 and parts[5]:
                                end_date = parts[5]
                            if len(parts) >= 7 and parts[6]:
                                created_date = parts[6]
                            elif not created_date:
                                created_date = datetime.now().isoformat()

                            users[username] = {
                                'password': password,
                                'max_instances': max_instances,
                                'role': role,
                                'start_date': start_date,
                                'end_date': end_date,
                                'created_date': created_date
                            }
    except Exception as e:
        logger.error(f"Error loading users: {str(e)}")
    return users

def load_user_instances():
    """Load user instances from file"""
    instances = {}
    try:
        # Ensure the file exists
        if not os.path.exists(USER_INSTANCES_FILE):
            logger.info(f"Creating new user instances file: {USER_INSTANCES_FILE}")
            with open(USER_INSTANCES_FILE, 'w') as f:
                f.write("# User Instance Management File\n")
                f.write("# Format: username:instance_name:start_date:end_date:created_date:status\n")
            return instances

        with open(USER_INSTANCES_FILE, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split(':')
                    if len(parts) >= 6:
                        username, instance_name, start_date, end_date, created_date, status = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]

                        if username not in instances:
                            instances[username] = []

                        instances[username].append({
                            'instance_name': instance_name,
                            'start_date': start_date,
                            'end_date': end_date,
                            'created_date': created_date,
                            'status': status
                        })
                    else:
                        logger.warning(f"Invalid line format in {USER_INSTANCES_FILE} at line {line_num}: {line}")

        logger.debug(f"Loaded instances for {len(instances)} users from {USER_INSTANCES_FILE}")
    except Exception as e:
        logger.error(f"Error loading user instances: {str(e)}")
    return instances

def save_user_instances(instances):
    """Save user instances to file"""
    try:
        with open(USER_INSTANCES_FILE, 'w') as f:
            f.write("# User Instance Management File\n")
            f.write("# Format: username:instance_name:start_date:end_date:created_date:status\n")
            for username, user_instances in instances.items():
                for instance in user_instances:
                    f.write(f"{username}:{instance['instance_name']}:{instance['start_date']}:{instance['end_date']}:{instance['created_date']}:{instance['status']}\n")
    except Exception as e:
        logger.error(f"Error saving user instances: {str(e)}")

def get_user_active_instances(username):
    """Get active instances for a user based on current date"""
    instances = load_user_instances()
    user_instances = instances.get(username, [])
    current_date = datetime.now().date()

    active_instances = []
    for instance in user_instances:
        if instance['status'] != 'active':
            continue

        try:
            start_date = datetime.fromisoformat(instance['start_date']).date()
            end_date = datetime.fromisoformat(instance['end_date']).date()

            if start_date <= current_date <= end_date:
                active_instances.append(instance)
        except:
            continue

    return active_instances

def get_user_max_instances_from_active(username):
    """Get maximum instances allowed based on active instance purchases"""
    # For admin and super admin, return unlimited
    if is_admin(username):
        return 999

    # For temp test accounts, return 1
    if is_temp_test_account(username):
        return 1

    # Get active instances
    active_instances = get_user_active_instances(username)

    # If user has active instance purchases, count them
    if active_instances:
        # Each active instance purchase allows 1 bot instance
        total_instances = len(active_instances)
        return total_instances

    # If no active instances, check legacy max_instances from user file
    users = load_users()
    user = users.get(username)
    if user:
        return user['max_instances']
    return 0

def is_user_account_active(username):
    """Check if user account is within valid date range"""
    users = load_users()
    user = users.get(username)

    if not user:
        return False

    # Admin accounts are always active
    if user.get('role') in ['admin', 'super_admin']:
        return True

    # Temp test accounts have their own validation
    if is_temp_test_account(username):
        return validate_temp_test_account(username)

    current_date = datetime.now().date()

    # Check start date
    if user.get('start_date'):
        try:
            start_date = datetime.fromisoformat(user['start_date']).date()
            if current_date < start_date:
                return False
        except:
            pass

    # Check end date
    if user.get('end_date'):
        try:
            end_date = datetime.fromisoformat(user['end_date']).date()
            if current_date > end_date:
                return False
        except:
            pass

    return True

def get_user_account_status(username):
    """Get detailed account status information"""
    users = load_users()
    user = users.get(username)

    if not user:
        return {'status': 'not_found'}

    current_date = datetime.now().date()
    status = 'active'
    days_remaining = None

    # Check if account is expired or not yet active
    if user.get('start_date'):
        try:
            start_date = datetime.fromisoformat(user['start_date']).date()
            if current_date < start_date:
                status = 'not_started'
                days_remaining = (start_date - current_date).days
        except:
            pass

    if user.get('end_date'):
        try:
            end_date = datetime.fromisoformat(user['end_date']).date()
            if current_date > end_date:
                status = 'expired'
            elif status == 'active':
                days_remaining = (end_date - current_date).days
        except:
            pass

    return {
        'status': status,
        'start_date': user.get('start_date'),
        'end_date': user.get('end_date'),
        'created_date': user.get('created_date'),
        'days_remaining': days_remaining,
        'role': user.get('role', 'user'),
        'max_instances': user.get('max_instances', 1)
    }

def get_user_role(username):
    """Get user role"""
    # Temporary test accounts are always 'test_user'
    if is_temp_test_account(username):
        return 'test_user'

    users = load_users()
    user = users.get(username)
    if user:
        return user.get('role', 'user')
    return 'user'

def is_admin(username):
    """Check if user has admin privileges"""
    role = get_user_role(username)
    return role in ['admin', 'super_admin']

def is_super_admin(username):
    """Check if user has super admin privileges"""
    role = get_user_role(username)
    return role == 'super_admin'

def authenticate_user(username, password):
    """Authenticate user against users file"""
    # Check if it's a temporary test account
    if is_temp_test_account(username):
        # For test accounts, password should be the test_id itself
        if password == username and validate_temp_test_account(username):
            # Increment usage count
            temp_test_accounts[username]['used_count'] += 1
            return True
        return False

    # Regular user authentication
    users = load_users()
    user = users.get(username)
    if user and user['password'] == password:
        # Check if account is within valid date range
        if not is_user_account_active(username):
            return False
        return True
    return False

def get_user_max_instances(username):
    """Get maximum instances allowed for a user"""
    # Use new instance management system
    return get_user_max_instances_from_active(username)

def load_user_config_assignments():
    """Load user config assignments from file"""
    assignments = {}
    try:
        if os.path.exists("user_config_assignments.txt"):
            with open("user_config_assignments.txt", 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split(':')
                        if len(parts) == 2:
                            username, config_file = parts[0].strip(), parts[1].strip()
                            assignments[username] = config_file
    except Exception as e:
        logger.error(f"Error loading user config assignments: {str(e)}")
    return assignments

def has_config_access(username, config_file):
    """Check if a user has access to a specific config file"""
    # Load user config assignments
    assignments = load_user_config_assignments()

    logger.debug(f"Config access check: user={username}, file={config_file}")

    # Admin has access to all config files
    if username == 'admin':
        logger.debug(f"Admin user {username} granted access to {config_file}")
        return True

    # config.json is accessible to everyone
    if config_file == 'config.json':
        logger.debug(f"User {username} granted access to global config.json")
        return True

    # Check if user has a specific config file assigned
    if username in assignments:
        assigned_configs = assignments[username]
        # Split comma-separated config files and check if requested file is in the list
        allowed_configs = [config.strip() for config in assigned_configs.split(',')]
        logger.debug(f"User {username} has assigned configs: {allowed_configs}")

        if config_file in allowed_configs:
            logger.debug(f"User {username} has explicit access to {config_file}")
            return True
        # Also allow access to example configs for reference
        if config_file == 'config.example.json':
            logger.debug(f"User {username} granted access to example config")
            return True
        # Allow users to create new files following naming conventions
        if (config_file.startswith(f"{username}_") and config_file.endswith('.json')) or \
           (config_file.startswith('config_') and config_file.endswith('.json')) or \
           (config_file.endswith(f"_{username}.json")):
            logger.write(f"User {username} granted access to new/user-specific config {config_file}")
            return True

        logger.debug(f"User {username} denied access to {config_file} (not in assigned configs)")
        return False

    # Fallback to old logic for users not in assignments file
    logger.debug(f"User {username} not in assignments file, using fallback logic")
    global_configs = ['config.json', 'config.example.json']

    # Allow access to global config files
    if config_file in global_configs:
        logger.debug(f"User {username} granted access to global config {config_file}")
        return True

    # Allow access to user-specific config files (including new ones)
    if (config_file.startswith(f"{username}_") and config_file.endswith('.json')) or \
       (config_file.startswith('config_') and username in config_file) or \
       (config_file.endswith(f"_{username}.json")):
        logger.debug(f"User {username} granted access to user-specific config {config_file}")
        return True

    logger.debug(f"User {username} denied access to {config_file} (no matching rules)")
    return False

def restart_bot_on_auth_failure(user_id, instance_id):
    """Restart bot automatically when authentication fails"""
    try:
        if instance_id in bot_processes:
            # Get bot details before stopping
            bot_data = bot_processes[instance_id]
            account_name = bot_data['name']
            token = bot_data['token']
            config_file = bot_data.get('config_file', 'config.json')

            # Stop the failed process
            process = bot_data["process"]
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

            del bot_processes[instance_id]

            # Wait a moment before restarting
            import time
            time.sleep(5)

            # Restart with fresh authentication and complete initialization
            env = os.environ.copy()
            env["LOKBOT_USER_ID"] = user_id
            env["LOKBOT_CONFIG"] = config_file

            # Re-authenticate to get fresh token with complete initialization
            try:
                from lokbot.client import LokBotApi
                email = os.getenv('LOK_EMAIL')
                password = os.getenv('LOK_PASSWORD')

                if email and password:
                    api = LokBotApi(None, {}, skip_jwt=True)

                    # Step 1: Complete authentication flow
                    logger.info(f"Bot restart: Attempting authentication for {account_name}")
                    auth_result = api.auth_login(email, password)
                    if not auth_result.get('result'):
                        logger.error(f"Bot restart: Login failed for {account_name}")
                        raise Exception("Login failed during restart")

                    fresh_token = auth_result.get('token')
                    if not fresh_token:
                        raise Exception("No token received during restart")

                    logger.info(f"Bot restart: Authentication successful for {account_name}")

                    # Step 2: Call auth_connect for proper session establishment
                    api.token = fresh_token
                    api.opener.headers['X-Access-Token'] = fresh_token

                    logger.info(f"Bot restart: Attempting connection for {account_name}")
                    connect_result = api.auth_connect()
                    if connect_result.get('result'):
                        if connect_result.get('token'):
                            fresh_token = connect_result.get('token')
                            logger.info(f"Bot restart: Updated token received for {account_name}")
                        logger.info(f"Bot restart: Successfully connected for {account_name}")
                    else:
                        logger.error(f"Bot restart: Connection failed for {account_name}")
                        raise Exception("Connection failed during restart")

                    # Step 3: Complete kingdom initialization sequence (like the farmer does)
                    logger.info(f"Bot restart: Initializing kingdom session for {account_name}")

                    # Set device info
                    api.auth_set_device_info({
                        "build": "global",
                        "OS": "Windows 10",
                        "country": "USA",
                        "language": "English",
                        "bundle": "",
                        "version": "1.1694.152.229",
                        "platform": "web",
                        "pushId": ""
                    })

                    # Enter kingdom to complete initialization
                    kingdom_enter = api.kingdom_enter()
                    if not kingdom_enter.get('result'):
                        logger.error(f"Bot restart: Kingdom enter failed for {account_name}")
                        raise Exception("Kingdom enter failed during restart")

                    # Get world and alliance info for chat logs
                    world_id = kingdom_enter.get("kingdom", {}).get("worldId")
                    alliance_id = kingdom_enter.get("kingdom", {}).get("allianceId")

                    # Initialize chat logs
                    if world_id:
                        api.chat_logs(f'w{world_id}')
                    if alliance_id:
                        api.chat_logs(f'a{alliance_id}')

                    logger.info(f"Bot restart: Kingdom initialization complete for {account_name}")

                    # Start new process with fresh token
                    new_process = subprocess.Popen(
                        ["python", "-m", "lokbot", fresh_token],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        env=env,
                        bufsize=1,
                        universal_newlines=True
                    )

                    # Update bot processes with new instance
                    bot_processes[instance_id] = {
                        "process": new_process,
                        "token": fresh_token,
                        "config_path": bot_data['config_path'],
                        "config_file": config_file,
                        "start_time": datetime.now(),
                        "user_id": user_id,
                        "name": f"{account_name} (Restarted)"
                    }

                    add_notification(user_id, "bot_restart", "Bot Restarted", 
                                   f"Bot {account_name} automatically restarted with fresh authentication and kingdom initialization")
                    logger.info(f"Successfully restarted bot {instance_id} for user {user_id} with complete initialization")
                    return True

            except Exception as e:
                logger.error(f"Failed to restart bot {instance_id}: {str(e)}")
                add_notification(user_id, "error", "Restart Failed", 
                               f"Could not restart bot {account_name}: {str(e)}")

    except Exception as e:
        logger.error(f"Error in restart_bot_on_auth_failure: {str(e)}")

    return False

def add_notification(user_id, notification_type, title, message, timestamp=None, account_name=None, instance_id=None):
    """Add a notification for a specific user and optionally for a specific account/instance"""
    try:
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        # Robust instance identification system
        if instance_id is None or account_name is None:
            # Try to get instance from current process context
            current_instance_id, current_account_name = get_current_bot_instance()
            if current_instance_id:
                instance_id = instance_id or current_instance_id
                account_name = account_name or current_account_name

        # Validate and set instance information
        if instance_id and instance_id in bot_processes:
            # Use existing instance data
            target_instance = bot_processes[instance_id]
            if not account_name:
                account_name = target_instance.get('name', f'Instance {instance_id.split("_")[-1]}')
        elif instance_id and instance_id != "general":
            # Instance ID provided but not found in active processes
            # This could be a recently stopped instance, use provided data
            if not account_name:
                account_name = f'Instance {instance_id.split("_")[-1]}'
        else:
            # Fallback to system/general notifications
            account_name = account_name or "General"
            instance_id = instance_id or "general"

        # Increment daily counter FIRST to ensure consistent numbering
        count = None
        if notification_type in ['rally_join', 'rally_start', 'monster_attack', 'gathering']:
            count = increment_daily_counter(user_id, notification_type)
        elif notification_type in ['crystal_mine', 'dragon_soul', 'object_scan']:
            count = increment_daily_counter(user_id, 'object_scan')

        # Update title to include daily count and instance info for these types
        instance_suffix = f" ({account_name})" if account_name != "General" else ""

        if notification_type == 'rally_join' and count:
            title = f"⚔️ Rally Joined (#{count} today){instance_suffix}"
        elif notification_type == 'rally_start' and count:
            title = f"🏴 Rally Started (#{count} today){instance_suffix}"
        elif notification_type == 'rally_alert':
            title = f"🚨 New Rally Available{instance_suffix}"
        elif notification_type == 'monster_attack' and count:
            title = f"👹 Monster Attack (#{count} today){instance_suffix}"
        elif notification_type == 'gathering' and count:
            title = f"🚛 Gathering Started (#{count} today){instance_suffix}"
        elif notification_type in ['crystal_mine', 'dragon_soul', 'object_scan'] and count:
            title = f"📢 Object Found (#{count} today){instance_suffix}"
        elif instance_suffix and notification_type not in ['bot_start', 'bot_stop']:
            title = f"{title}{instance_suffix}"

        # Create notification with unique ID including instance info for proper separation
        notification_id = f"{user_id}_{instance_id}_{notification_type}_{int(time.time() * 1000000)}"
        notification = {
            'type': notification_type,
            'title': title,
            'message': message,
            'timestamp': timestamp,
            'account_name': account_name,
            'instance_id': instance_id,
            'id': notification_id,
            'count': count  # Include count for reference
        }

        # Initialize user notification history structure
        if user_id not in notifications_history:
            notifications_history[user_id] = {}

        if account_name not in notifications_history[user_id]:
            notifications_history[user_id][account_name] = []

        # Enhanced duplicate check - consider instance separation
        current_time = datetime.now(timezone.utc)
        account_history = notifications_history[user_id][account_name]

        # Check for duplicates in the last 30 seconds for the same instance
        is_duplicate = False
        for existing_notif in account_history[-10:]:  # Check last 10 for better duplicate detection
            try:
                existing_time = datetime.fromisoformat(existing_notif['timestamp'].replace('Z', '+00:00'))
                time_diff = abs((current_time - existing_time).total_seconds())

                # More precise duplicate detection including instance_id
                if (time_diff < 30 and 
                    existing_notif['message'] == message and 
                    existing_notif['type'] == notification_type and
                    existing_notif.get('instance_id') == instance_id):
                    is_duplicate = True
                    break
            except:
                continue

        if not is_duplicate:
            # Add notification to history
            notifications_history[user_id][account_name].append(notification)

            # Keep only last 150 notifications per account (increased for better history with multiple instances)
            if len(notifications_history[user_id][account_name]) > 150:
                notifications_history[user_id][account_name] = notifications_history[user_id][account_name][-150:]

            # Add to real-time queue
            if user_id in notification_queues:
                try:
                    notification_queues[user_id].put_nowait(notification)
                except queue.Full:
                    # If queue is full, remove oldest and add new
                    try:
                        notification_queues[user_id].get_nowait()
                        notification_queues[user_id].put_nowait(notification)
                    except queue.Empty:
                        pass

            logger.info(f"Added notification for user {user_id} instance {instance_id} ({account_name}): {title}")
        else:
            logger.debug(f"Skipped duplicate notification for user {user_id} instance {instance_id} ({account_name}): {title}")

    except Exception as e:
        logger.error(f"Error adding notification for user {user_id}: {str(e)}")

def get_current_bot_instance():
    """Get the current bot instance ID and account name from the running process context"""
    try:
        import os
        import threading

        user_id = os.getenv('LOKBOT_USER_ID', 'web_user')

        # First try to get from environment variable set by the bot process
        instance_id_env = os.getenv('LOKBOT_INSTANCE_ID')
        account_name_env = os.getenv('LOKBOT_ACCOUNT_NAME')

        if instance_id_env:
            # Use environment variables set when starting the bot process
            if instance_id_env in bot_processes:
                proc_data = bot_processes[instance_id_env]
                account_name = account_name_env or proc_data.get('name', f'Instance {instance_id_env.split("_")[-1]}')
                return instance_id_env, account_name
            else:
                # Instance might have stopped, but we still have the env vars
                account_name = account_name_env or f'Instance {instance_id_env.split("_")[-1]}'
                return instance_id_env, account_name

        # Fallback: try to match by PID
        current_pid = os.getpid()
        for proc_id, proc_data in bot_processes.items():
            try:
                if proc_data["process"].pid == current_pid and proc_id.startswith(user_id):
                    account_name = proc_data.get('name', f'Instance {proc_id.split("_")[-1]}')
                    return proc_id, account_name
            except (AttributeError, ProcessLookupError):
                continue

        # Last resort: check if we're in a farmer thread context
        thread_name = threading.current_thread().name
        if 'farmer' in thread_name.lower() or 'bot' in thread_name.lower():
            # Try to find any active instance for this user
            for proc_id, proc_data in bot_processes.items():
                if proc_id.startswith(user_id) and proc_data["process"].poll() is None:
                    account_name = proc_data.get('name', f'Instance {proc_id.split("_")[-1]}')
                    return proc_id, account_name

    except Exception as e:
        logger.debug(f"Could not determine bot instance: {e}")

    return None, None

def add_bot_update(user_id, update_type, title, message):
    """Add a bot status update notification"""
    instance_id, account_name = get_current_bot_instance()
    add_notification(user_id, update_type, title, message, account_name=account_name, instance_id=instance_id)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'authenticated' not in session:
            return jsonify({'error': 'Not authenticated'}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'authenticated' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/notifications')
def notifications():
    if 'authenticated' not in session:
        return redirect(url_for('login'))
    return render_template('notifications.html')

@app.route('/manifest.json')
def manifest():
    """Serve PWA manifest"""
    return app.send_static_file('manifest.json')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Capture enhanced user session details
        user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        user_agent = request.headers.get('User-Agent', 'Unknown')
        login_time = datetime.now().isoformat()

        # Extract additional details from headers
        accept_language = request.headers.get('Accept-Language', 'Unknown')
        accept_encoding = request.headers.get('Accept-Encoding', 'Unknown')
        referer = request.headers.get('Referer', 'Direct')
        connection_type = request.headers.get('Connection', 'Unknown')

        # Determine device type from user agent
        device_type = 'Unknown'
        if 'Mobile' in user_agent or 'Android' in user_agent or 'iPhone' in user_agent:
            device_type = 'Mobile'
        elif 'iPad' in user_agent or 'Tablet' in user_agent:
            device_type = 'Tablet'
        elif 'Windows' in user_agent or 'Macintosh' in user_agent or 'Linux' in user_agent:
            device_type = 'Desktop'

        # Extract browser information
        browser = 'Unknown'
        if 'Chrome' in user_agent:
            browser = 'Chrome'
        elif 'Firefox' in user_agent:
            browser = 'Firefox'
        elif 'Safari' in user_agent and 'Chrome' not in user_agent:
            browser = 'Safari'
        elif 'Edge' in user_agent:
            browser = 'Edge'

        if authenticate_user(username, password):
            session['authenticated'] = True
            session['user_id'] = username
            session['username'] = username
            session['login_ip'] = user_ip
            session['login_time'] = login_time
            session['user_agent'] = user_agent
            session['device_type'] = device_type
            session['browser'] = browser
            session['accept_language'] = accept_language
            session['login_method'] = 'web_form'

            # Get user role
            user_role = get_user_role(username)
            session['user_role'] = user_role

            # Log successful login with enhanced details
            logger.info(f"Successful login - User: {username} ({user_role}), IP: {user_ip}, Device: {device_type}, Browser: {browser}, Time: {login_time}")

            # Track login history with enhanced data
            if username not in login_history:
                login_history[username] = []

            login_record = {
                'login_time': login_time,
                'ip_address': user_ip,
                'user_agent': user_agent,
                'device_type': device_type,
                'browser': browser,
                'accept_language': accept_language,
                'accept_encoding': accept_encoding,
                'referer': referer,
                'connection_type': connection_type,
                'login_method': 'web_form',
                'user_role': user_role,
                'session_id': session.get('session_id', str(uuid.uuid4())),
                'status': 'active',
                'country': 'Unknown',  # Could be enhanced with GeoIP lookup
                'timezone': 'Unknown'   # Could be captured from client-side
            }

            login_history[username].append(login_record)

            # Keep only last 100 login records per user for enhanced tracking
            if len(login_history[username]) > 100:
                login_history[username] = login_history[username][-100:]

            # Track active session with enhanced data
            session_id = login_record['session_id']
            session['session_id'] = session_id
            active_sessions[session_id] = {
                'username': username,
                'user_role': user_role,
                'login_time': login_time,
                'ip_address': user_ip,
                'user_agent': user_agent,
                'device_type': device_type,
                'browser': browser,
                'last_activity': login_time,
                'page_views': 1,
                'actions_performed': 0
            }

            # Track session for temporary test accounts
            if is_temp_test_account(username):
                temp_test_accounts[username]['active_sessions'].add(session_id)

            # Add login notification
            add_notification(username, "login", "Successful Login", 
                           f"Logged in from {device_type} ({browser}) at IP: {user_ip}")

            return redirect(url_for('index'))
        else:
            # Enhanced failed login logging
            logger.warning(f"Failed login attempt - Username: {username}, IP: {user_ip}, Device: {device_type}, Browser: {browser}, Time: {login_time}")

            # Track failed login attempts (for security monitoring)
            failed_login_key = f"failed_{user_ip}_{username}"
            if failed_login_key not in login_history:
                login_history[failed_login_key] = []

            login_history[failed_login_key].append({
                'attempt_time': login_time,
                'ip_address': user_ip,
                'username_attempted': username,
                'user_agent': user_agent,
                'device_type': device_type,
                'browser': browser,
                'status': 'failed'
            })

            return render_template('login.html', error='Invalid credentials')

    return render_template('login.html')

@app.route('/logout')
def logout():
    # Log logout with session details
    username = session.get('username', 'Unknown')
    user_id = session.get('user_id', 'Unknown')
    login_ip = session.get('login_ip', 'Unknown')
    login_time = session.get('login_time', 'Unknown')
    logout_time = datetime.now().isoformat()

    # Calculate session duration
    session_duration = "Unknown"
    if login_time != 'Unknown':
        try:
            login_dt = datetime.fromisoformat(login_time)
            logout_dt = datetime.fromisoformat(logout_time)
            duration = logout_dt - login_dt
            session_duration = str(duration).split('.')[0]  # Remove microseconds
        except:
            pass

    logger.info(f"User logout - User: {username}, IP: {login_ip}, Login: {login_time}, Logout: {logout_time}, Duration: {session_duration}")

    # Update session history
    session_id = session.get('session_id')
    if session_id and session_id in active_sessions:
        # Remove from temp test account tracking
        if is_temp_test_account(user_id) and user_id in temp_test_accounts:
            temp_test_accounts[user_id]['active_sessions'].discard(session_id)
        del active_sessions[session_id]

    # Update login history to mark session as ended
    if username in login_history:
        for record in reversed(login_history[username]):
            if record.get('session_id') == session_id and record.get('status') == 'active':
                record['logout_time'] = logout_time
                record['session_duration'] = session_duration
                record['status'] = 'ended'
                break

    # Clear user-specific caches
    if user_id in notification_queues:
        del notification_queues[user_id]

    # Clear any status cache related to this user
    global statusCache, lastStatusUpdate
    statusCache = None
    lastStatusUpdate = 0

    session.clear()
    return redirect(url_for('login'))

@app.route('/health')
def health_check():
    """Health check endpoint for Replit"""
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time(),
        'service': 'LokBot Web App'
    }), 200

@app.route('/api/notifications/stream')
@login_required
def notification_stream():
    user_id = session['user_id']
    user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
    logger.info(f"Starting notification stream for user: {user_id} from IP: {user_ip}")

    def event_stream():
        # Create a queue for this user if it doesn't exist
        if user_id not in notification_queues:
            notification_queues[user_id] = queue.Queue(maxsize=25)
            logger.info(f"Created new notification queue for user: {user_id}")

        q = notification_queues[user_id]
        connection_id = f"{user_id}_{int(time.time())}"

        try:
            # Send initial connection message with shorter retry interval
            yield f"retry: 5000\n"
            yield f"data: {json.dumps({'type': 'connected', 'message': f'Connected to notification stream', 'connection_id': connection_id})}\n\n"

            heartbeat_counter = 0
            while True:
                try:
                    # Use shorter timeout to prevent worker timeout
                    notification = q.get(timeout=10)
                    logger.debug(f"Sending notification to user {user_id}: {notification}")
                    yield f"data: {json.dumps(notification)}\n\n"
                    heartbeat_counter = 0
                except queue.Empty:
                    # Send heartbeat more frequently to keep connection alive
                    heartbeat_counter += 1
                    yield f"data: {json.dumps({'type': 'heartbeat', 'count': heartbeat_counter})}\n\n"

                    # Close connection after 5 heartbeats (50 seconds) to prevent worker timeout
                    if heartbeat_counter > 5:
                        logger.info(f"Closing notification stream for user {user_id} to prevent timeout")
                        break
                except GeneratorExit:
                    break
                except Exception as e:
                    logger.error(f"Error in notification stream for user {user_id}: {str(e)}")
                    break
        except Exception as e:
            logger.error(f"Error in event_stream generator for user {user_id}: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Connection error'})}\n\n"

    response = Response(event_stream(), mimetype="text/event-stream")
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['Connection'] = 'keep-alive'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Cache-Control'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['X-Accel-Buffering'] = 'no'  # Disable nginx buffering

    # Cleanup old queues periodically
    import threading
    def cleanup_old_queues():
        for uid in list(notification_queues.keys()):
            if notification_queues[uid].qsize() == 0:
                # Check if queue has been inactive - implement your logic here
                pass

    return response

@app.route('/api/notifications/history')
@login_required
def get_notification_history():
    """Get notification history for the current user, organized by account"""
    if 'authenticated' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    user_id = session['user_id']
    selected_account = request.args.get('account', 'all')

    logger.info(f"Loading notification history for user {user_id}, account filter: {selected_account}")

    # Check for notifications from file (fallback method)
    try:
        notification_file = f'data/notifications_{user_id}.json'
        if os.path.exists(notification_file):
            file_notifications = []
            with open(notification_file, 'r') as f:
                for line in f:
                    try:
                        notification = json.loads(line.strip())
                        if notification.get('user_id') == user_id:
                            file_notifications.append({
                                'type': notification['type'],
                                'title': notification['title'],
                                'message': notification['message'],
                                'timestamp': notification['timestamp'],
                                'account_name': notification.get('account_name', 'General'),
                                'id': notification.get('id', f"migrated_{int(time.time() * 1000000)}")
                            })
                    except:
                        continue

            # Migrate old notifications to new structure
            if user_id not in notifications_history:
                notifications_history[user_id] = {}

            for notification in file_notifications:
                account_name = notification.get('account_name', 'General')
                if account_name not in notifications_history[user_id]:
                    notifications_history[user_id][account_name] = []

                # Check for duplicates before adding (more precise check)
                existing = any(
                    n.get('message') == notification['message'] and 
                    n.get('type') == notification['type'] and 
                    abs((datetime.fromisoformat(n['timestamp'].replace('Z', '+00:00')) - 
                         datetime.fromisoformat(notification['timestamp'].replace('Z', '+00:00'))).total_seconds()) < 1
                    for n in notifications_history[user_id][account_name]
                )

                if not existing:
                    notifications_history[user_id][account_name].append(notification)

            # Clean up the file after reading
            try:
                os.remove(notification_file)
            except:
                pass
            logger.info(f"Migrated {len(file_notifications)} notifications from file for user {user_id}")
    except Exception as e:
        logger.debug(f"Error processing notification file: {str(e)}")

    # Get user's notification history (new structure)
    user_history = notifications_history.get(user_id, {})
    logger.info(f"User {user_id} has notifications in {len(user_history)} accounts: {list(user_history.keys())}")

    # Get available accounts (sorted for consistency)
    available_accounts = sorted(list(user_history.keys()))

    # Add current active bot instances to available accounts
    for proc_id, proc_data in bot_processes.items():
        if proc_id.startswith(user_id) and proc_data["process"].poll() is None:
            account_name = proc_data.get('name', f'Instance {proc_id}')
            if account_name not in available_accounts:
                available_accounts.append(account_name)

    # Sort available accounts (General first, then alphabetically)
    available_accounts.sort(key=lambda x: (x != 'General', x))

    # If no notifications exist, create a test notification to verify the system works
    if not user_history:
        logger.info(f"No notifications found for user {user_id}, creating test notification")
        test_notification = {
            'type': 'bot_start',
            'title': 'Welcome to HelenA QuantumRaid Bot',
            'message': 'Your notification system is working! Bot activities will appear here.',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'account_name': 'General',
            'id': f"welcome_{user_id}_{int(time.time() * 1000000)}"
        }

        if user_id not in notifications_history:
            notifications_history[user_id] = {}
        if 'General' not in notifications_history[user_id]:
            notifications_history[user_id]['General'] = []
        notifications_history[user_id]['General'].append(test_notification)

        user_history = notifications_history[user_id]
        available_accounts = ['General']

    # Filter notifications based on selected account
    today = datetime.now().date()

    if selected_account == 'all':
        # Combine all notifications from all accounts
        all_notifications = []
        for account_name, notifications in user_history.items():
            for notification in notifications:
                # Filter by current date
                try:
                    notification_date = datetime.fromisoformat(notification['timestamp'].replace('Z', '+00:00')).date()
                    if notification_date == today:
                        # Ensure notification has account_name
                        notification_copy = notification.copy()
                        notification_copy['account_name'] = account_name
                        all_notifications.append(notification_copy)
                except:
                    continue

        # Sort by timestamp (newest first) with proper datetime parsing
        def parse_timestamp(notif):
            try:
                timestamp_str = notif['timestamp']
                if timestamp_str.endswith('Z'):
                    timestamp_str = timestamp_str[:-1] + '+00:00'
                elif '+' not in timestamp_str and 'T' in timestamp_str:
                    timestamp_str += '+00:00'
                return datetime.fromisoformat(timestamp_str)
            except:
                return datetime.min.replace(tzinfo=timezone.utc)

        all_notifications.sort(key=parse_timestamp, reverse=True)

        logger.info(f"Returning {len(all_notifications)} notifications for user {user_id} (all accounts, today only)")
        return jsonify({
            'notifications': all_notifications[:100],  # Top 100 most recent notifications
            'available_accounts': available_accounts,
            'selected_account': selected_account
        })
    else:
        # Return notifications for specific account
        account_notifications = user_history.get(selected_account, [])

        # Filter by current date
        today_notifications = []
        for notification in account_notifications:
            try:
                notification_date = datetime.fromisoformat(notification['timestamp'].replace('Z', '+00:00')).date()
                if notification_date == today:
                    today_notifications.append(notification)
            except:
                continue

        # Sort by timestamp (newest first)
        def parse_timestamp(notif):
            try:
                timestamp_str = notif['timestamp']
                if timestamp_str.endswith('Z'):
                    timestamp_str = timestamp_str[:-1] + '+00:00'
                elif '+' not in timestamp_str and 'T' in timestamp_str:
                    timestamp_str += '+00:00'
                return datetime.fromisoformat(timestamp_str)
            except:
                return datetime.min.replace(tzinfo=timezone.utc)

        today_notifications.sort(key=parse_timestamp, reverse=True)

        logger.info(f"Returning {len(today_notifications)} notifications for user {user_id} account {selected_account} (today only)")
        return jsonify({
            'notifications': today_notifications[:50],  # Top 50 notifications for this account
            'available_accounts': available_accounts,
            'selected_account': selected_account
        })

@app.route('/api/config_files')
@login_required
def get_config_files():
    """Get list of available configuration files for the current user"""
    try:
        user_id = session['user_id']
        username = session.get('username', user_id)
        config_files = []

        # Load user config assignments
        assignments = load_user_config_assignments()

        # Admin can access all config files
        if username == 'admin':
            for file in os.listdir('.'):
                if file.endswith('.json') and os.path.isfile(file):
                    config_files.append(file)
        else:
            # Check if user has specific config files assigned
            if username in assignments:
                assigned_configs = assignments[username]
                # Handle comma-separated config files
                config_list = [config.strip() for config in assigned_configs.split(',')]
                for config_file in config_list:
                    if os.path.exists(config_file):
                        config_files.append(config_file)
            # Also allow access to example config for reference
            if os.path.exists('config.example.json') and 'config.example.json' not in config_files:
                config_files.append('config.example.json')

            else:
                # Fallback to old logic for users not in assignments file
                global_configs = ['config.json', 'config.example.json']

                for file in os.listdir('.'):
                    if file.endswith('.json') and os.path.isfile(file):
                        if has_config_access(username, file):
                            config_files.append(file)

        # Remove duplicates and sort
        config_files = sorted(list(set(config_files)))

        return jsonify({'config_files': config_files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/summary', methods=['POST'])
@login_required
def get_config_summary():
    """Get a summary of enabled features for bot startup confirmation"""
    try:
        data = request.json
        selected_config = data.get('config_file', 'config.json')
        username = session.get('username', session['user_id'])

        # Check if user has access to this config file
        if not has_config_access(username, selected_config):
            return jsonify({'error': 'Access denied to this config file'}), 403

        # Load the selected config file
        if not os.path.exists(selected_config):
            return jsonify({'error': f'Config file {selected_config} not found'}), 404

        with open(selected_config, 'r') as f:
            config = json.load(f)

        # Extract enabled features
        summary = {
            'config_file': selected_config,
            'enabled_features': {},
            'rally_settings': {},
            'object_scanning': {},
            'jobs_and_threads': {},
            'other_features': {}
        }

        # Rally settings
        rally_config = config.get('rally', {})
        rally_join = rally_config.get('join', {})
        rally_start = rally_config.get('start', {})

        if rally_join.get('enabled', False):
            summary['rally_settings']['rally_join'] = {
                'enabled': True,
                'max_marches': rally_join.get('numMarch', 8),
                'max_distance': rally_join.get('max_rally_distance', 500),
                'monsters_count': len(rally_join.get('targets', []))
            }

        if rally_start.get('enabled', False):
            summary['rally_settings']['rally_start'] = {
                'enabled': True,
                'max_marches': rally_start.get('numMarch', 6),
                'max_distance': rally_start.get('max_rally_distance', 500),
                'monsters_count': len(rally_start.get('targets', []))
            }

        # Object scanning (SOCF thread)
        main_config = config.get('main', {})
        jobs = main_config.get('jobs', [])

        for job in jobs:
            if job.get('name') == 'socf_thread' and job.get('enabled', False):
                kwargs = job.get('kwargs', {})
                targets = kwargs.get('targets', [])

                enabled_objects = []
                for target in targets:
                    if target.get('enabled', False):
                        enabled_objects.append({
                            'name': target.get('name', f"Object {target.get('code', 'Unknown')}"),
                            'code': target.get('code'),
                            'levels': target.get('level', [])
                        })

                summary['object_scanning'] = {
                    'enabled': True,
                    'radius': kwargs.get('radius', 16),
                    'total_objects': len(targets),
                    'enabled_objects': enabled_objects,
                    'share_to_channels': kwargs.get('share_to', {}).get('chat_channels', [])
                }
                break

        # Normal monster attack
        normal_monsters = main_config.get('normal_monsters', {})
        if normal_monsters.get('enabled', False):
            summary['other_features']['normal_monsters'] = {
                'enabled': True,
                'max_distance': normal_monsters.get('max_distance', 200),
                'monsters_count': len(normal_monsters.get('targets', []))
            }

        # Skills
        skills = main_config.get('skills', {})
        if skills.get('enabled', False):
            enabled_skills = [skill for skill in skills.get('skills', []) if skill.get('enabled', False)]
            summary['other_features']['skills'] = {
                'enabled': True,
                'enabled_skills_count': len(enabled_skills)
            }

        # Treasure
        treasure = main_config.get('treasure', {})
        if treasure.get('enabled', False):
            summary['other_features']['treasure'] = {
                'enabled': True,
                'page': treasure.get('page', 1)
            }

        # Buff management
        buff_management = config.get('buff_management', {})
        if buff_management.get('enabled', False):
            enabled_buffs = [buff for buff in buff_management.get('buffs', []) if buff.get('enabled', False)]
            summary['other_features']['buff_management'] = {
                'enabled': True,
                'enabled_buffs_count': len(enabled_buffs)
            }

        # Jobs summary
        enabled_jobs = [job for job in jobs if job.get('enabled', False)]
        summary['jobs_and_threads']['jobs'] = {
            'total': len(jobs),
            'enabled': len(enabled_jobs),
            'enabled_list': [job.get('name', 'Unknown') for job in enabled_jobs]
        }

        # Threads summary
        threads = main_config.get('threads', [])
        enabled_threads = [thread for thread in threads if thread.get('enabled', False)]
        summary['jobs_and_threads']['threads'] = {
            'total': len(threads),
            'enabled': len(enabled_threads),
            'enabled_list': [thread.get('name', 'Unknown') for thread in enabled_threads]
        }

        # Discord settings
        discord_config = config.get('discord', {})
        if discord_config.get('enabled', False):
            summary['other_features']['discord'] = {
                'enabled': True,
                'webhooks_configured': len([url for url in [
                    discord_config.get('webhook_url'),
                    discord_config.get('rally_webhook_url'),
                    discord_config.get('gathering_webhook_url'),
                    discord_config.get('monster_webhook_url')
                ] if url])
            }

        return jsonify({'success': True, 'summary': summary})

    except Exception as e:
        logger.error(f"Error generating config summary: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/start_bot', methods=['POST'])
@login_required
def start_bot():
    data = request.json
    user_id = session['user_id']

    # Get user's maximum allowed instances
    username = session.get('username', user_id)
    max_instances = get_user_max_instances(username)

    # Count existing instances
    existing_instances = [proc_id for proc_id in bot_processes if proc_id.startswith(user_id) and bot_processes[proc_id]["process"].poll() is None]
    instance_count = len(existing_instances)

    if instance_count >= max_instances:
        return jsonify({'error': f'Maximum of {max_instances} bot instance(s) allowed for user {username}'}), 400

    try:
        email = data.get('email') or os.getenv('LOK_EMAIL')
        password = data.get('password') or os.getenv('LOK_PASSWORD')
        token = data.get('token')
        selected_config = data.get('config_file', 'config.json')  # Default to config.json if not specified
        auth_method = data.get('auth_method', 'env')  # Get auth method from request
        auto_stop_duration = data.get('auto_stop_duration')  # in minutes

        if not token and (not email or not password):
            return jsonify({'error': 'Authentication credentials required'}), 400

        # If no token provided, authenticate with provided credentials
        if not token:
            try:
                api = LokBotApi(None, {}, skip_jwt=True)

                # Step 1: Email/password authentication (same as Discord bot)
                logger.info(f"User {user_id}: Attempting authentication...")
                auth_result = api.auth_login(email, password)

                if not auth_result.get('result'):
                    logger.error(f"Authentication failed for user {user_id}")
                    if 'err' in auth_result:
                        logger.error(f"Error: {auth_result['err']}")
                    return jsonify({'error': 'Email/password authentication failed'}), 400

                token = auth_result.get('token')
                if not token:
                    return jsonify({'error': 'No token received from authentication'}), 400

                logger.info(f"User {user_id}: Authentication successful, token received (length: {len(token)})")

                # Step 2: Always call auth_connect to establish proper session (exactly like Discord bot)
                api.token = token
                api.opener.headers['X-Access-Token'] = token

                logger.info(f"User {user_id}: Attempting connection to game server...")
                connect_result = api.auth_connect()
                if connect_result.get('result'):
                    # Update token if auth_connect returns a new one (same as Discord bot)
                    if connect_result.get('token'):
                        token = connect_result.get('token')
                        logger.info(f"User {user_id}: Updated token received from auth_connect")
                    logger.info(f"User {user_id}: Successfully connected to game server")
                else:
                    logger.error(f"User {user_id}: Failed to establish game connection")
                    return jsonify({'error': 'Failed to establish game connection'}), 400

            except Exception as e:
                logger.error(f"Authentication failed: {str(e)}")
                return jsonify({'error': f'Authentication failed: {str(e)}'}), 400

        # Generate unique instance ID using timestamp to avoid collisions
        import time
        timestamp = int(time.time() * 1000)  # milliseconds for uniqueness
        instance_id = f"{user_id}_{timestamp}"

        # Double-check uniqueness
        while instance_id in bot_processes:
            time.sleep(0.001)  # Wait 1ms
            timestamp = int(time.time() * 1000)
            instance_id = f"{user_id}_{timestamp}"

        # Generate account name with proper numbering
        account_name = data.get('account_name', f'Instance {instance_count + 1}')

        # Set the current config in ConfigHelper FIRST (same as Discord bot)
        ConfigHelper.set_current_config(selected_config)

        # Create user config based on selected config file
        config_path = f"data/config_{user_id}.json"

        # Load the selected config file as template
        if os.path.exists(selected_config):
            with open(selected_config, "r") as f:
                config_data = json.load(f)
        else:
            return jsonify({'error': f'Selected config file {selected_config} not found'}), 400

        # Update config with user ID
        if "discord" not in config_data:
            config_data["discord"] = {}
        config_data["discord"]["user_id"] = user_id

        # Ensure rally configurations exist
        if "rally" not in config_data:
            config_data["rally"] = {}

        if "join" not in config_data["rally"]:
            config_data["rally"]["join"] = {
                "enabled": False,
                "numMarch": 8,
                "level_based_troops": True,
                "targets": []
            }

        if "start" not in config_data["rally"]:
            config_data["rally"]["start"] = {
                "enabled": False,
                "numMarch": 6,
                "level_based_troops": True,
                "targets": []
            }

        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2)

        # Note: The farmer will use socf_thread_with_recovery for automatic re-initialization
            # Start the bot process with proper environment variables
        env = os.environ.copy()
        env["LOKBOT_USER_ID"] = user_id
        env["LOKBOT_CONFIG"] = selected_config  # Set the selected config file
        env["LOKBOT_INSTANCE_ID"] = instance_id  # Set the instance ID for notification tracking
        env["LOKBOT_ACCOUNT_NAME"] = account_name  # Set the account name

        # Ensure the bot process can identify itself properly
        logger.info(f"Setting environment variables: USER_ID={user_id}, INSTANCE_ID={instance_id}, ACCOUNT_NAME={account_name}")

        # Set the current config in ConfigHelper (same as Discord bot)
        ConfigHelper.set_current_config(selected_config)

        # Log the start attempt
        logger.info(f"Starting bot for user {user_id} with config {selected_config}")

        try:
            process = subprocess.Popen(
                ["python", "-m", "lokbot", token],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Combine stderr with stdout
                text=True,
                env=env,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )

            # Start a thread to monitor and log output to console
            def log_output(bot_process):
                try:
                    for line in iter(bot_process.stdout.readline, ''):
                        if line.strip():
                            logger.info(f"[{account_name}] {line.strip()}")

                            # Parse log lines for notifications with better pattern matching
                            line_lower = line.lower()
                            line_content = line.strip()

                            # Skip ANSI color code lines and system log messages
                            if "[0m" in line_content or "sent to discord" in line_lower or "sent to web app" in line_lower:
                                continue

                            # Handle authentication and connection errors with auto-restart
                            if "not_online" in line_lower or "noauthexception" in line_lower or "notOnlineException" in line_content:
                                add_notification(user_id, "error", "Authentication Error", 
                                               "Bot lost connection - attempting automatic restart...")
                                # Trigger automatic restart on authentication failure
                                threading.Thread(target=restart_bot_on_auth_failure, args=[user_id, instance_id], daemon=True).start()
                                continue
                            elif "failed to join rally" in line_lower and "not_online" in line_content:
                                add_notification(user_id, "warning", "Rally Join Failed", 
                                               "Rally join failed - bot needs to reconnect")
                                continue

                            # Only capture the actual game event messages, not the log confirmations
                            # Gathering notifications - look for the specific emoji message
                            if "🚛 gathering march started!" in line_lower:
                                # Extract just the clean message part
                                if "🚛" in line_content:
                                    clean_message = line_content.split("🚛")[1].strip() if "🚛" in line_content else line_content
                                    clean_message = "🚛 " + clean_message
                                    add_notification(user_id, "gathering", "Gathering Started", clean_message, account_name=account_name, instance_id=instance_id)

                            # Rally notifications
                            elif "rally joined" in line_lower and "🔥" in line_content:
                                add_notification(user_id, "rally_join", "Rally Joined", line_content, account_name=account_name, instance_id=instance_id)
                            elif "rally started" in line_lower and "🏴" in line_content:
                                add_notification(user_id, "rally_start", "Rally Started", line_content, account_name=account_name, instance_id=instance_id)

                            # Resource findings - only capture the formatted messages
                            elif "crystal mine found!" in line_lower and "📢" in line_content:
                                add_notification(user_id, "crystal_mine", "Crystal Mine Found", line_content, account_name=account_name, instance_id=instance_id)
                            elif "dragon soul found!" in line_lower and "📢" in line_content:
                                add_notification(user_id, "dragon_soul", "Dragon Soul Found", line_content, account_name=account_name, instance_id=instance_id)

                            # Monster attacks
                            elif ("monster attack" in line_lower and "started" in line_lower) and "👹" in line_content:
                                add_notification(user_id, "monster_attack", "Monster Attack Started", line_content, account_name=account_name, instance_id=instance_id)

                            # Crystal limit detection with auto-termination
                            elif "exceed_crystal_daily_quota" in line_content:
                                # Send bold notification about crystal limit
                                add_notification(user_id, "error", "🚨 Crystal Limit Reached", 
                                               "**Your Daily crystal limit is over, Please stop the bot**", account_name=account_name, instance_id=instance_id)

                                # Auto-terminate the bot process
                                try:
                                    logger.info(f"Crystal limit reached for {account_name}, auto-terminating bot...")
                                    if instance_id in bot_processes:
                                        process = bot_processes[instance_id]["process"]
                                        if process.poll() is None:
                                            process.terminate()
                                            try:
                                                process.wait(timeout=5)
                                            except subprocess.TimeoutExpired:
                                                process.kill()
                                                process.wait()
                                        del bot_processes[instance_id]
                                        add_notification(user_id, "bot_stop", "Bot Auto-Stopped", 
                                                       f"Bot {account_name} automatically stopped due to crystal limit", account_name=account_name, instance_id=instance_id)
                                except Exception as e:
                                    logger.error(f"Error auto-terminating bot {instance_id}: {str(e)}")
                                continue
                            # Enhanced error detection including token issues
                            elif any(token_error in line_lower for token_error in ["no_auth", "noauth", "401", "unauthorized", "token"]) and "error" in line_lower:
                                add_notification(user_id, "error", "Token Error", 
                                               "Authentication token issue detected - attempting restart...", account_name=account_name, instance_id=instance_id)
                                threading.Thread(target=restart_bot_on_auth_failure, args=[user_id, instance_id], daemon=True).start()
                                continue
                            elif "error" in line_lower and not any(x in line_lower for x in ["debug", "info", "lokbot"]):
                                add_notification(user_id, "error", "Bot Error", line_content, account_name=account_name, instance_id=instance_id)
                            elif "failed" in line_lower and not any(x in line_lower for x in ["debug", "info", "lokbot"]):
                                add_notification(user_id, "warning", "Bot Warning", line_content, account_name=account_name, instance_id=instance_id)

                except Exception as e:
                    logger.error(f"Error reading output from {account_name}: {str(e)}")

            import threading
            log_thread = threading.Thread(target=log_output, args=(process,), daemon=True)
            log_thread.start()

            # Give the process a moment to start
            import time
            time.sleep(2)

            # Check if process is still running
            if process.poll() is not None:
                # Process has already terminated
                stdout, stderr = process.communicate()
                error_msg = f"Bot process failed to start. Exit code: {process.returncode}. Output: {stdout}"
                logger.error(error_msg)
                return jsonify({'error': error_msg}), 500

            # Add auto-stop functionality
            auto_stop_time = None
            if auto_stop_duration:
                auto_stop_duration = int(auto_stop_duration)
                auto_stop_time = datetime.now() + timedelta(minutes=auto_stop_duration)

                def auto_stop_bot_task(instance_id):
                    try:
                        if instance_id in bot_processes:
                            process = bot_processes[instance_id]["process"]

                            if process.poll() is None:
                                process.terminate()
                                try:
                                    process.wait(timeout=5)
                                except subprocess.TimeoutExpired:
                                    process.kill()
                                    process.wait()

                            del bot_processes[instance_id]
                            add_notification(user_id, "bot_stop", "Bot Auto-Stopped", 
                                           f"Bot {account_name} auto-stopped after {auto_stop_duration} minutes.")
                            logger.info(f"Bot {account_name} auto-stopped after {auto_stop_duration} minutes.")
                    except Exception as e:
                        logger.error(f"Error during auto-stop for bot {instance_id}: {e}")

                # Schedule the auto-stop task
                timer = threading.Timer(auto_stop_duration * 60, auto_stop_bot_task, args=[instance_id])
                timer.daemon = True
                timer.start()

            bot_processes[instance_id] = {
                "process": process,
                "token": token,
                "config_path": config_path,
                "config_file": selected_config,
                "start_time": datetime.now(),
                "user_id": user_id,
                "name": account_name,
                "auto_stop_time": auto_stop_time,
                "auto_stop_duration": auto_stop_duration,
            }

            logger.info(f"Bot started successfully for user {user_id} as instance {instance_id}. Active instances for user: {len([p for p in bot_processes if p.startswith(user_id) and bot_processes[p]['process'].poll() is None])}")
            add_notification(user_id, "bot_start", "Bot Started", f"Bot started successfully with config {selected_config}", account_name=account_name, instance_id=instance_id)

            # Clear status cache to force refresh
            global statusCache, lastStatusUpdate
            statusCache = None
            lastStatusUpdate = 0

        except Exception as e:
            logger.error(f"Exception starting bot process: {str(e)}")
            add_notification(user_id, "error", "Bot Start Failed", f"Failed to start bot: {str(e)}")
            return jsonify({'error': f'Failed to start bot process: {str(e)}'}), 500

        return jsonify({
            'success': True,
            'message': f'Bot {account_name} started successfully with config {selected_config}',
            'instance_id': instance_id
        })

    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop_bot', methods=['POST'])
@login_required
def stop_bot():
    data = request.json
    instance_ids = data.get('instance_ids', [])
    user_id = session['user_id']
    username = session.get('username', user_id)

    # Clear status cache FIRST to ensure fresh data
    global statusCache, lastStatusUpdate, isRefreshing
    statusCache = None
    lastStatusUpdate = 0
    isRefreshing = False

    logger.info(f"Force clearing status cache for bot stop operation")

    stopped_count = 0
    failed_stops = []

    for instance_id in instance_ids:
        if instance_id in bot_processes:
            # Check if user can stop this instance
            can_stop = False

            # Regular users can only stop their own instances
            if instance_id.startswith(user_id):
                can_stop = True

            # Admins can stop any instance
            if is_admin(username):
                can_stop = True

            if can_stop:
                try:
                    process = bot_processes[instance_id]["process"]
                    instance_owner = bot_processes[instance_id].get("user_id", "unknown")
                    account_name = bot_processes[instance_id].get('name', instance_id)

                    logger.info(f"Stopping bot instance {instance_id} for user {username}")

                    # Check if process is still running before attempting to stop
                    if process.poll() is None:
                        # First attempt: graceful termination
                        process.terminate()

                        # Wait longer for graceful shutdown
                        try:
                            process.wait(timeout=10)
                            logger.info(f"Process {instance_id} terminated gracefully")
                        except subprocess.TimeoutExpired:
                            logger.warning(f"Process {instance_id} didn't terminate gracefully, forcing kill")
                            # Force kill if graceful termination fails
                            process.kill()
                            try:
                                process.wait(timeout=5)
                                logger.info(f"Process {instance_id} force killed successfully")
                            except subprocess.TimeoutExpired:
                                logger.error(f"Failed to kill process {instance_id}")
                                failed_stops.append(instance_id)
                                continue
                    else:
                        logger.info(f"Process {instance_id} was already terminated")

                    # Verify process is actually stopped
                    if process.poll() is not None:
                        # Process is definitely stopped, safe to remove
                        del bot_processes[instance_id]
                        stopped_count += 1

                        # Notify the instance owner
                        if instance_owner != "unknown":
                            add_notification(instance_owner, "bot_stop", "Bot Stopped", 
                                           f"Bot instance {account_name} was stopped", account_name=account_name, instance_id=instance_id)

                        # If admin stopped someone else's bot, log it
                        if is_admin(username) and instance_owner != user_id:
                            logger.info(f"Admin {username} stopped bot instance {instance_id} owned by {instance_owner}")
                    else:
                        logger.error(f"Process {instance_id} still running after stop attempts")
                        failed_stops.append(instance_id)

                except Exception as e:
                    logger.error(f"Error stopping bot instance {instance_id}: {str(e)}")
                    failed_stops.append(instance_id)
        else:
            logger.warning(f"Instance {instance_id} not found in bot_processes")

    if stopped_count > 0:
        add_notification(user_id, "bot_stop", "Bot Stopped", f"Stopped {stopped_count} bot instance(s)")

    # Prepare response message
    message = f'Stopped {stopped_count} instance(s)'
    if failed_stops:
        message += f', failed to stop {len(failed_stops)} instance(s)'

    return jsonify({
        'success': True,
        'message': message,
        'stopped_count': stopped_count,
        'failed_stops': failed_stops,
        'force_refresh': True  # Signal frontend to refresh immediately
    })

@app.route('/api/status')
@login_required
def get_status():
    user_id = session['user_id']
    username = session.get('username', user_id)

    # Validate session integrity
    if not user_id or not username:
        session.clear()
        return jsonify({'error': 'Invalid session'}), 401

    # Clean up dead processes with better validation and logging
    dead_processes = []
    for proc_id in list(bot_processes.keys()):
        try:
            process = bot_processes[proc_id]["process"]
            exit_code = process.poll()
            if exit_code is not None:
                dead_processes.append(proc_id)
                logger.info(f"Found dead process {proc_id} with exit code {exit_code}")

                # Ensure process resources are cleaned up
                try:
                    process.stdout.close() if process.stdout else None
                    process.stderr.close() if process.stderr else None
                except:
                    pass
        except Exception as e:
            logger.error(f"Error checking process {proc_id}: {str(e)}")
            dead_processes.append(proc_id)

    # Remove dead processes immediately
    for proc_id in dead_processes:
        if proc_id in bot_processes:
            proc_data = bot_processes[proc_id]
            owner = proc_data.get('user_id', 'unknown')
            account_name = proc_data.get('name', proc_id)
            logger.info(f"Cleaning up dead process {proc_id} ({account_name}) owned by {owner}")

            # Add notification for unexpected process death
            if owner != 'unknown':
                add_notification(owner, "bot_stop", "Bot Stopped", 
                               f"Bot {account_name} stopped unexpectedly", account_name=account_name)

            del bot_processes[proc_id]

    # Get user's active processes with strict validation
    user_processes = []
    all_processes = []  # For admin view

    for proc_id, proc_data in bot_processes.items():
        try:
            process = proc_data["process"]
            # Double-check that process is actually running
            if process.poll() is None:
                # Extract username from stored user_id (more reliable than parsing proc_id)
                instance_username = proc_data.get('user_id', 'unknown')

                process_info = {
                    'instance_id': proc_id,
                    'name': proc_data.get('name', f'Instance {proc_id}'),
                    'start_time': proc_data['start_time'].isoformat(),
                    'status': 'running',
                    'config_file': proc_data.get('config_file', 'config.json'),
                    'username': instance_username,
                    'validated': True,
                    'current_marches': proc_data.get('current_marches', 0),
                    'march_limit': proc_data.get('march_limit', 0),
                    'march_size': proc_data.get('march_size', 0),
                    'last_march_update': proc_data.get('last_march_update', 0)
                }

                # Add auto-stop information if available
                if proc_data.get('auto_stop_time'):
                    process_info['auto_stop_time'] = proc_data['auto_stop_time'].isoformat()
                    process_info['auto_stop_duration'] = proc_data.get('auto_stop_duration')

                    # Calculate remaining time with proper timezone handling
                    auto_stop_time = proc_data['auto_stop_time']
                    if auto_stop_time.tzinfo is None:
                        auto_stop_time = auto_stop_time.replace(tzinfo=timezone.utc)

                    remaining = auto_stop_time - datetime.now(timezone.utc)
                    if remaining.total_seconds() > 0:
                        process_info['remaining_minutes'] = int(remaining.total_seconds() / 60)
                    else:
                        process_info['remaining_minutes'] = 0

                # Add to all processes list (always, for admin view)
                all_processes.append(process_info)

                # Add to user processes if it belongs to current user (exact match)
                if instance_username == user_id:
                    user_processes.append(process_info)
                    logger.debug(f"Added user process {proc_id} for user {user_id}")

        except Exception as e:
            logger.error(f"Error processing bot process {proc_id}: {str(e)}")
            continue

    total_active = len(all_processes)
    logger.debug(f"Status check: User {user_id} has {len(user_processes)} instances, total active: {total_active}")

    response_data = {
        'user_processes': user_processes,
        'total_active': total_active
    }

    # If admin, include all processes
    if is_admin(username):
        response_data['all_processes'] = all_processes

    return jsonify(response_data)

@app.route('/api/config/delete', methods=['DELETE'])
@login_required
def delete_config():
    """Delete a configuration file"""
    try:
        data = request.json
        config_file = data.get('config_file')
        username = session.get('username', session['user_id'])

        if not config_file:
            return jsonify({'error': 'Config file name required'}), 400

        # Check if user has access to this config file
        if not has_config_access(username, config_file):
            return jsonify({'error': 'Access denied to this config file'}), 403

        # Protect essential config files
        protected_files = ['config.json', 'config.example.json']
        if config_file in protected_files:
            return jsonify({'error': 'Cannot delete essential config files'}), 403

        # Check if file exists
        if not os.path.exists(config_file):
            return jsonify({'error': f'Config file {config_file} not found'}), 404

        # Delete the file
        os.remove(config_file)
        logger.info(f"Config file {config_file} deleted by user {username}")

        return jsonify({'success': True, 'message': f'Config file {config_file} deleted successfully'})

    except Exception as e:
        logger.error(f"Error deleting config file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/rename', methods=['POST'])
@login_required
def rename_config():
    """Rename a configuration file"""
    try:
        data = request.json
        current_name = data.get('current_name')
        new_name = data.get('new_name')
        username = session.get('username', session['user_id'])

        if not current_name or not new_name:
            return jsonify({'error': 'Current name and new name are required'}), 400

        # Check if user has access to the current config file
        if not has_config_access(username, current_name):
            return jsonify({'error': 'Access denied to this config file'}), 403

        # Protect essential config files
        protected_files = ['config.json', 'config.example.json']
        if current_name in protected_files:
            return jsonify({'error': 'Cannot rename essential config files'}), 403

        # Check if current file exists
        if not os.path.exists(current_name):
            return jsonify({'error': f'Config file {current_name} not found'}), 404

        # Validate new filename (allow spaces and most characters)
        import re
        invalid_chars = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
        if invalid_chars.search(new_name):
            return jsonify({'error': 'Invalid filename. Cannot contain: < > : " / \\ | ? * or control characters.'}), 400

        # Check if new file already exists
        if os.path.exists(new_name) and current_name != new_name:
            # If it exists, we'll overwrite it as the frontend already asked for confirmation
            pass

        # Rename the file
        os.rename(current_name, new_name)
        logger.info(f"Config file {current_name} renamed to {new_name} by user {username}")

        # Update user config assignments if applicable
        try:
            assignments = load_user_config_assignments()

            # Update assignments for this user
            if username in assignments:
                current_configs = assignments[username].split(',')
                # Replace the old filename with new filename
                updated_configs = []
                for config in current_configs:
                    config = config.strip()
                    if config == current_name:
                        updated_configs.append(new_name)
                    else:
                        updated_configs.append(config)
                assignments[username] = ','.join(updated_configs)

                # Save updated assignments
                with open("user_config_assignments.txt", 'w') as f:
                    for user, config_files in assignments.items():
                        f.write(f"{user}:{config_files}\n")

                logger.info(f"Updated user config assignments for {username}")
        except Exception as assignment_error:
            logger.warning(f"Failed to update config assignments after rename: {assignment_error}")
            # Don't fail the rename operation for assignment errors

        return jsonify({'success': True, 'message': f'Config file renamed to {new_name} successfully'})

    except Exception as e:
        logger.error(f"Error renaming config file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['GET', 'POST', 'PUT'])
@login_required
def handle_config():
    user_id = session['user_id']
    username = session.get('username', user_id)

    if request.method == 'GET':
        try:
            # Get selected config file from request or use default
            selected_config = request.args.get('config_file', 'config.json')

            # Debug logging
            logger.info(f"Config access request: user={username}, config_file={selected_config}")

            # Load user config assignments for debugging
            assignments = load_user_config_assignments()
            logger.info(f"User assignments: {assignments.get(username, 'No assignments found')}")

            # Check if user has access to this config file
            if not has_config_access(username, selected_config):
                logger.warning(f"Access denied for user {username} to config file {selected_config}")
                return jsonify({
                    'error': f'Access denied to config file {selected_config}',
                    'available_configs': assignments.get(username, 'No configs assigned'),
                    'help': 'Contact admin to assign config access'
                }), 403

            # Load the selected config file
            if os.path.exists(selected_config):
                with open(selected_config, 'r') as f:
                    config = json.load(f)
                logger.info(f"Successfully loaded config {selected_config} for user {username}")
            else:
                logger.error(f"Config file {selected_config} not found")
                return jsonify({'error': f'Config file {selected_config} not found'}), 404

            return jsonify(config)
        except Exception as e:
            logger.error(f"Error in handle_config: {str(e)}")
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST' or request.method == 'PUT':
        try:
            data = request.json
            if not data:
                return jsonify({'error': 'No JSON data provided'}), 400

            config = data.get('config', {})
            selected_config = data.get('config_file', 'config.json')
            timestamp = data.get('timestamp')  # Handle retry timestamp

            # Validate config data
            if not config or not isinstance(config, dict):
                logger.error(f"Invalid config data received: {type(config)}")
                return jsonify({'error': 'Invalid configuration data provided'}), 400

            # Validate filename
            if not selected_config or not selected_config.endswith('.json'):
                return jsonify({'error': 'Invalid config filename'}), 400

            logger.info(f"Saving config file {selected_config} for user {username} (timestamp: {timestamp})")

            # Ensure essential structure exists in config
            if 'main' not in config:
                config['main'] = {}
            if 'rally' not in config:
                config['rally'] = {}
            if 'discord' not in config:
                config['discord'] = {}

            # Create a backup filename for safety
            backup_config = f"{selected_config}.backup"

            # Save config with atomic write operation
            temp_filename = f"{selected_config}.tmp"
            try:
                with open(temp_filename, 'w') as f:
                    json.dump(config, f, indent=2, sort_keys=False, ensure_ascii=False)
                    f.flush()  # Ensure data is written to disk
                    os.fsync(f.fileno())  # Force write to disk

                # Move temp file to final location (atomic operation)
                if os.path.exists(selected_config):
                    os.rename(selected_config, backup_config)
                os.rename(temp_filename, selected_config)

                # Verify the file was written correctly
                with open(selected_config, 'r') as f:
                    saved_config = json.load(f)
                    if not saved_config:
                        raise ValueError("Saved config is empty")

                # Remove backup if verification successful
                if os.path.exists(backup_config):
                    os.remove(backup_config)

            except Exception as save_error:
                # Restore from backup if save failed
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)
                if os.path.exists(backup_config) and not os.path.exists(selected_config):
                    os.rename(backup_config, selected_config)
                raise save_error

            # Auto-assign the newly created config file to the user
            try:
                assignments = load_user_config_assignments()
                if username not in assignments:
                    assignments[username] = selected_config
                else:
                    # Append to existing assignments (comma-separated)
                    existing_configs = assignments[username]
                    if selected_config not in existing_configs:
                        assignments[username] = f"{existing_configs},{selected_config}"

                # Save the updated assignments
                with open("user_config_assignments.txt", 'w') as f:
                    for user, config_files in assignments.items():
                        f.write(f"{user}:{config_files}\n")
            except Exception as assignment_error:
                logger.warning(f"Failed to update user assignments: {assignment_error}")
                # Don't fail the request for assignment errors

            logger.info(f"Successfully saved config file {selected_config}")
            return jsonify({'success': True, 'message': f'Configuration saved to {selected_config}'})

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return jsonify({'error': 'Invalid JSON in configuration data'}), 400
        except Exception as e:
            logger.error(f"Error saving config: {str(e)}")
            return jsonify({'error': f'Failed to save configuration: {str(e)}'}), 500

@app.route('/api/rally_config', methods=['POST'])
@login_required
def update_rally_config():
    data = request.json
    user_id = session['user_id']
    config_file = f"data/config_{user_id}.json"

    try:
        # Load existing config
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
        else:
            with open('config.json', 'r') as f:
                config = json.load(f)

        # Update rally configuration
        rally_type = data.get('rally_type')  # 'join' or 'start'

        if rally_type not in ['join', 'start']:
            return jsonify({'error': 'Invalid rally type'}), 400

        if 'rally' not in config:
            config['rally'] = {}

        if rally_type not in config['rally']:
            config['rally'][rally_type] = {
                'enabled': False,
                'numMarch': 8 if rally_type == 'join' else 6,
                'level_based_troops': True,
                'targets': []
            }

        # Update specific fields
        if 'enabled' in data:
            config['rally'][rally_type]['enabled'] = data['enabled']

        if 'numMarch' in data:
            config['rally'][rally_type]['numMarch'] = data['numMarch']

        if 'level_based_troops' in data:
            config['rally'][rally_type]['level_based_troops'] = data['level_based_troops']

        if 'targets' in data:
            config['rally'][rally_type]['targets'] = data['targets']

        # Save config
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)

        return jsonify({'success': True, 'message': f'Rally {rally_type} configuration updated'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Daily counters for notifications
daily_counters = {}  # user_id -> {date: {gathering: count, rally_join: count, etc}}
user_notifications = {}

def get_daily_counter(user_id, counter_type):
    """Get daily counter for a specific notification type"""
    today = datetime.now().date().isoformat()

    if user_id not in daily_counters:
        daily_counters[user_id] = {}

    if today not in daily_counters[user_id]:
        daily_counters[user_id][today] = {}

    return daily_counters[user_id][today].get(counter_type, 0)

def increment_daily_counter(user_id, counter_type):
    """Increment daily counter for a specific notification type"""
    today = datetime.now().date().isoformat()

    if user_id not in daily_counters:
        daily_counters[user_id] = {}

    if today not in daily_counters[user_id]:
        daily_counters[user_id][today] = {}

    daily_counters[user_id][today][counter_type] = daily_counters[user_id][today].get(counter_type, 0) + 1
    return daily_counters[user_id][today][counter_type]

@app.route('/api/object_notification', methods=['POST'])
def object_notification():
    try:
        data = request.get_json()
        user_id = data.get('user_id', 'web_user')
        instance_id = data.get('instance_id')  # Accept instance_id from the request
        account_name = data.get('account_name')  # Accept account_name from the request

        # Validate and generate proper instance information
        if not instance_id or instance_id == 'unknown':
            # Generate a proper instance ID based on existing patterns
            import time
            timestamp = int(time.time() * 1000)
            instance_id = f"{user_id}_{timestamp}"

        if not account_name or account_name in ['Unknown Instance', 'Bot Instance']:
            # Generate a proper account name
            existing_instances = [proc_id for proc_id in bot_processes if proc_id.startswith(user_id)]
            instance_number = len(existing_instances) + 1
            account_name = f"Bot Instance {instance_number}"

        logger.info(f"Received object notification for user_id: {user_id}, instance: {instance_id}, account: {account_name}")

        # Determine notification type based on object type
        object_name = data.get('object_name', '')
        if 'Crystal Mine' in object_name:
            notification_type = 'crystal_mine'
            title = "Crystal Mine Found"
        elif 'Dragon Soul' in object_name:
            notification_type = 'dragon_soul'
            title = "Dragon Soul Found"
        else:
            notification_type = 'object_scan'
            title = "Object Found"

        # Add to notification system with validated instance information
        add_notification(user_id, notification_type, title, data.get('formatted_message', 'Object found'), 
                        account_name=account_name, instance_id=instance_id)

        logger.info(f"Added notification for user {user_id} instance {instance_id} ({account_name}): {title}")
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error in object_notification: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/gathering_notification', methods=['POST'])
def gathering_notification():
    try:
        data = request.get_json()
        user_id = data.get('user_id', 'web_user')
        instance_id = data.get('instance_id')  # Accept instance_id from the request
        account_name = data.get('account_name')  # Accept account_name from the request

        # Validate and generate proper instance information
        if not instance_id or instance_id == 'unknown':
            # Generate a proper instance ID based on existing patterns
            import time
            timestamp = int(time.time() * 1000)
            instance_id = f"{user_id}_{timestamp}"

        if not account_name or account_name in ['Unknown Instance', 'Bot Instance']:
            # Generate a proper account name
            existing_instances = [proc_id for proc_id in bot_processes if proc_id.startswith(user_id)]
            instance_number = len(existing_instances) + 1
            account_name = f"Bot Instance {instance_number}"

        logger.info(f"Received gathering notification for user_id: {user_id}, instance: {instance_id}, account: {account_name}")

        # Add to notification system with validated instance information
        add_notification(user_id, "gathering", "Gathering Started", data.get('formatted_message', 'Gathering march started'),
                        account_name=account_name, instance_id=instance_id)

        logger.info(f"Added gathering notification for user {user_id} instance {instance_id} ({account_name})")
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error in gathering_notification: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/rally_notification', methods=['POST'])
def rally_notification():
    try:
        data = request.get_json()
        user_id = data.get('user_id', 'web_user')
        notification_type = data.get('notification_type', 'rally_join')
        instance_id = data.get('instance_id')  # Accept instance_id from the request
        account_name = data.get('account_name')  # Accept account_name from the request

        # Validate and generate proper instance information
        if not instance_id or instance_id == 'unknown':
            # Generate a proper instance ID based on existing patterns
            import time
            timestamp = int(time.time() * 1000)
            instance_id = f"{user_id}_{timestamp}"

        if not account_name or account_name in ['Unknown Instance', 'Bot Instance']:
            # Generate a proper account name
            existing_instances = [proc_id for proc_id in bot_processes if proc_id.startswith(user_id)]
            instance_number = len(existing_instances) + 1
            account_name = f"Bot Instance {instance_number}"

        logger.info(f"Received rally notification for user_id: {user_id}, type: {notification_type}, instance: {instance_id}, account: {account_name}")

        # Determine title based on notification type
        if notification_type == 'rally_join':
            title = "Rally Joined"
        elif notification_type == 'rally_start':
            title = "Rally Started"
        elif notification_type == 'rally_alert':
            title = "New Rally Available"
        else:
            title = "Rally Activity"

        # Add to notification system with validated instance information
        add_notification(user_id, notification_type, title, data.get('formatted_message', 'Rally activity'),
                        account_name=account_name, instance_id=instance_id)

        logger.info(f"Added rally notification for user {user_id} instance {instance_id} ({account_name}): {title}")
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error in rally_notification: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/crystal_limit_notification', methods=['POST'])
def crystal_limit_notification():
    try:
        data = request.get_json()
        user_id = data.get('user_id', 'web_user')
        instance_id = data.get('instance_id')
        account_name = data.get('account_name', 'Bot Instance')
        message = data.get('message', 'Crystal limit reached')

        logger.info(f"Received crystal limit notification for user_id: {user_id}, instance: {instance_id}")

        # Add to notification system with instance information
        add_notification(user_id, "error", "🚨 Crystal Limit Reached", message,
                        account_name=account_name, instance_id=instance_id)

        logger.info(f"Added crystal limit notification for user {user_id} instance {instance_id}")
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error in crystal_limit_notification: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/user_info')
@login_required
def get_user_info():
    """Get current user information"""
    username = session.get('username', 'unknown')
    max_instances = get_user_max_instances(username)
    timezone = session.get('timezone', 'UTC')
    user_role = get_user_role(username)

    response_data = {
        'username': username,
        'max_instances': max_instances,
        'timezone': timezone,
        'role': user_role,
        'is_admin': is_admin(username),
        'is_super_admin': is_super_admin(username)
    }

    # Both admin and super_admin can see basic session info, but super_admin gets more details
    if is_admin(username):
        login_ip = session.get('login_ip', 'Unknown')
        login_time = session.get('login_time', 'Unknown')
        user_agent = session.get('user_agent', 'Unknown')
        device_type = session.get('device_type', 'Unknown')
        browser = session.get('browser', 'Unknown')

        # Calculate session duration
        session_duration = "Unknown"
        if login_time != 'Unknown':
            try:
                login_dt = datetime.fromisoformat(login_time)
                current_dt = datetime.now()
                duration = current_dt - login_dt
                session_duration = str(duration).split('.')[0]  # Remove microseconds
            except:
                pass

        response_data.update({
            'login_time': login_time,
            'device_type': device_type,
            'browser': browser,
            'session_duration': session_duration
        })

        # Only super admin can see IP addresses and sensitive details
        if is_super_admin(username):
            response_data.update({
                'login_ip': login_ip,
                'user_agent': user_agent,
                'accept_language': session.get('accept_language', 'Unknown'),
                'login_method': session.get('login_method', 'Unknown')
            })

    return jsonify(response_data)

@app.route('/api/user_timezone', methods=['GET', 'POST'])
@login_required
def handle_user_timezone():
    """Get or set user timezone preference"""
    if request.method == 'GET':
        timezone = session.get('timezone', 'UTC')
        return jsonify({'timezone': timezone})

    elif request.method == 'POST':
        data = request.json
        timezone = data.get('timezone', 'UTC')
        session['timezone'] = timezone
        return jsonify({'success': True, 'timezone': timezone})

@app.route('/api/users', methods=['GET', 'POST'])
@login_required
def manage_users():
    """Manage users (admin+ only)"""
    username = session.get('username')
    if not is_admin(username):
        return jsonify({'error': 'Admin access required'}), 403

    if request.method == 'GET':
        users = load_users()
        user_instances = load_user_instances()
        user_list = []
        current_user_role = get_user_role(username)

        for user, data in users.items():
            user_role = data.get('role', 'user')

            # Hide super admin users from regular admins
            if user_role == 'super_admin' and current_user_role != 'super_admin':
                continue

            account_status = get_user_account_status(user)

            # Get user instances
            instances = user_instances.get(user, [])
            active_instances = get_user_active_instances(user)

            user_info = {
                'username': user,
                'max_instances': data['max_instances'],
                'role': user_role,
                'start_date': data.get('start_date'),
                'end_date': data.get('end_date'),
                'created_date': data.get('created_date'),
                'account_status': account_status['status'],
                'days_remaining': account_status['days_remaining'],
                'instances': instances,
                'active_instances': len(active_instances),
                'total_instances': len(instances)
            }
            user_list.append(user_info)
        return jsonify({'users': user_list})

    elif request.method == 'POST':
        data = request.json
        action = data.get('action', 'add')  # Default to 'add' if no action specified

        if action == 'add':
            new_username = data.get('username')
            new_password = data.get('password', 'defaultpass123')
            max_instances = data.get('max_instances', 1)
            new_role = data.get('role', 'user')
            start_date = data.get('start_date', '')
            end_date = data.get('end_date', '')

            if not new_username:
                return jsonify({'error': 'Username required'}), 400

            # Only super admin can create admin/super_admin users
            if new_role in ['admin', 'super_admin'] and not is_super_admin(username):
                return jsonify({'error': 'Super admin access required to create admin users'}), 403

            # Check if user already exists
            users = load_users()
            if new_username in users:
                return jsonify({'error': 'User already exists'}), 400

            # Validate dates if provided
            if start_date:
                try:
                    datetime.fromisoformat(start_date)
                except ValueError:
                    return jsonify({'error': 'Invalid start date format. Use YYYY-MM-DD'}), 400

            if end_date:
                try:
                    datetime.fromisoformat(end_date)
                except ValueError:
                    return jsonify({'error': 'Invalid end date format. Use YYYY-MM-DD'}), 400

            if start_date and end_date:
                try:
                    start_dt = datetime.fromisoformat(start_date)
                    end_dt = datetime.fromisoformat(end_date)
                    if start_dt >= end_dt:
                        return jsonify({'error': 'End date must be after start date'}), 400
                except ValueError:
                    return jsonify({'error': 'Invalid date format'}), 400

            # Add user to file
            try:
                created_date = datetime.now().isoformat()
                with open(USER_FILE, 'a') as f:
                    f.write(f"\n{new_username}:{new_password}:{max_instances}:{new_role}:{start_date}:{end_date}:{created_date}")
                return jsonify({'success': True, 'message': 'User added successfully'})
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        elif action == 'update':
            target_username = data.get('username')
            new_max_instances = data.get('max_instances')
            new_start_date = data.get('start_date', '')
            new_end_date = data.get('end_date', '')

            if not target_username:
                return jsonify({'error': 'Username required'}), 400

            # Validate dates if provided
            if new_start_date:
                try:
                    datetime.fromisoformat(new_start_date)
                except ValueError:
                    return jsonify({'error': 'Invalid start date format. Use YYYY-MM-DD'}), 400

            if new_end_date:
                try:
                    datetime.fromisoformat(new_end_date)
                except ValueError:
                    return jsonify({'error': 'Invalid end date format. Use YYYY-MM-DD'}), 400

            if new_start_date and new_end_date:
                try:
                    start_dt = datetime.fromisoformat(new_start_date)
                    end_dt = datetime.fromisoformat(new_end_date)
                    if start_dt >= end_dt:
                        return jsonify({'error': 'End date must be after start date'}), 400
                except ValueError:
                    return jsonify({'error': 'Invalid date format'}), 400

            # Update user in file
            try:
                users = load_users()
                if target_username not in users:
                    return jsonify({'error': 'User not found'}), 404

                if new_max_instances is not None:
                    users[target_username]['max_instances'] = int(new_max_instances)

                if new_start_date is not None:
                    users[target_username]['start_date'] = new_start_date

                if new_end_date is not None:
                    users[target_username]['end_date'] = new_end_date

                # Rewrite file
                with open(USER_FILE, 'w') as f:
                    f.write("# User Management File\n")
                    f.write("# Format: username:password:max_instances:role:start_date:end_date:created_date\n")
                    for user, user_data in users.items():
                        start_date = user_data.get('start_date', '')
                        end_date = user_data.get('end_date', '')
                        created_date = user_data.get('created_date', '')
                        role = user_data.get('role', 'user')
                        f.write(f"{user}:{user_data['password']}:{user_data['max_instances']}:{role}:{start_date}:{end_date}:{created_date}\n")

                return jsonify({'success': True, 'message': 'User updated successfully'})
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        elif action == 'delete':
            target_username = data.get('username')

            if not target_username:
                return jsonify({'error': 'Username required'}), 400

            if target_username == 'admin':
                return jsonify({'error': 'Cannot delete admin user'}), 400

            # Remove user from file
            try:
                users = load_users()
                if target_username not in users:
                    return jsonify({'error': 'User not found'}), 404

                del users[target_username]

                # Rewrite file
                with open(USER_FILE, 'w') as f:
                    f.write("# User Management File\n")
                    f.write("# Format: username:password:max_instances\n")
                    for user, data in users.items():
                        f.write(f"{user}:{data['password']}:{data['max_instances']}\n")

                return jsonify({'success': True, 'message': 'User deleted successfully'})
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        return jsonify({'error': 'Invalid action'}), 400

@app.route('/api/admin/user_activity_monitor')
@login_required
def admin_user_activity_monitor():
    """Admin endpoint for monitoring user activities and notifications"""
    username = session.get('username')
    if not is_admin(username):
        return jsonify({'error': 'Admin access required'}), 403

    try:
        # Get all users
        users = load_users()
        user_activities = {}

        # Collect activity data for each user
        for user_id in users.keys():
            # Get daily counters
            today = datetime.now().date().isoformat()
            user_daily_counters = daily_counters.get(user_id, {}).get(today, {})

            # Get notification history (organized by account)
            user_notification_history = notifications_history.get(user_id, {})

            # Flatten all notifications from all accounts for this user
            all_user_notifications = []
            for account_name, notifications in user_notification_history.items():
                all_user_notifications.extend(notifications)

            # Get active bot instances
            user_instances = [
                {
                    'instance_id': proc_id,
                    'name': proc_data['name'],
                    'start_time': proc_data['start_time'].isoformat(),
                    'config_file': proc_data.get('config_file', 'config.json')
                }
                for proc_id, proc_data in bot_processes.items()
                if proc_id.startswith(user_id) and proc_data["process"].poll() is None
            ]

            # Calculate weekly/monthly totals
            week_ago = datetime.now() - timedelta(days=7)
            month_ago = datetime.now() - timedelta(days=30)

            weekly_stats = {'rally_join': 0, 'rally_start': 0, 'gathering': 0, 'monster_attack': 0, 'object_scan': 0}
            monthly_stats = {'rally_join': 0, 'rally_start': 0, 'gathering': 0, 'monster_attack': 0, 'object_scan': 0}

            for notification in all_user_notifications:
                try:
                    notif_time = datetime.fromisoformat(notification['timestamp'].replace('Z', '+00:00'))
                    notif_type = notification.get('type', '')

                    if notif_time >= week_ago and notif_type in weekly_stats:
                        weekly_stats[notif_type] += 1
                    if notif_time >= month_ago and notif_type in monthly_stats:
                        monthly_stats[notif_type] += 1
                except:
                    continue

            user_activities[user_id] = {
                'user_info': {
                    'username': user_id,
                    'max_instances': users[user_id]['max_instances'],
                    'role': users[user_id].get('role', 'user')
                },
                'daily_counters': user_daily_counters,
                'weekly_stats': weekly_stats,
                'monthly_stats': monthly_stats,
                'active_instances': len(user_instances),
                'instances': user_instances,
                'total_notifications': len(all_user_notifications),
                'recent_notifications': sorted(all_user_notifications, key=lambda x: x.get('timestamp', ''), reverse=True)[:10],
                'last_activity': sorted(all_user_notifications, key=lambda x: x.get('timestamp', ''), reverse=True)[0]['timestamp'] if all_user_notifications else None
            }

        # Generate summary statistics
        summary = {
            'total_users': len(users),
            'active_users_today': len([u for u in user_activities.values() if u['daily_counters']]),
            'total_active_instances': sum(len(data['instances']) for data in user_activities.values()),
            'total_notifications_today': sum(sum(u['daily_counters'].values()) for u in user_activities.values()),
            'most_active_user': max(user_activities.keys(), key=lambda u: sum(user_activities[u]['daily_counters'].values())) if user_activities else None,
            'last_updated': datetime.now().isoformat()
        }

        return jsonify({
            'user_activities': user_activities,
            'summary': summary
        })

    except Exception as e:
        logger.error(f"Error in user activity monitor: {str(e)}")
        return jsonify({'error': 'Failed to load user activity data'}), 500

@app.route('/api/admin/session_monitor')
@login_required
def admin_session_monitor():
    """Super admin only endpoint for detailed session monitoring"""
    username = session.get('username')
    if not is_super_admin(username):
        return jsonify({'error': 'Super admin access required'}), 403

    try:
        # Get detailed session information for all users
        session_list = []

        # Process active sessions
        for session_id, session_data in active_sessions.items():
            if session_data.get('username') and not session_data.get('username', '').startswith('failed_'):
                session_info = {
                    'session_id': session_id,
                    'username': session_data.get('username', 'Unknown'),
                    'login_time': session_data.get('login_time', 'Unknown'),
                    'last_activity': session_data.get('last_activity', session_data.get('login_time', 'Unknown')),
                    'ip_address': session_data.get('ip_address', 'Unknown'),
                    'device_type': session_data.get('device_type', 'Unknown'),
                    'browser': session_data.get('browser', 'Unknown'),
                    'user_role': session_data.get('user_role', 'user'),
                    'status': 'active'
                }
                session_list.append(session_info)

        # Also include recent login history data
        recent_logins = []
        for user, login_records in login_history.items():
            if not user.startswith('failed_'):
                for record in login_records[-5:]:  # Last 5 logins per user
                    login_info = {
                        'username': user,
                        'login_time': record.get('login_time', 'Unknown'),
                        'ip_address': record.get('ip_address', 'Unknown'),
                        'device_type': record.get('device_type', 'Unknown'),
                        'browser': record.get('browser', 'Unknown'),
                        'user_role': record.get('user_role', 'user'),
                        'session_duration': record.get('session_duration', 'Unknown'),
                        'status': record.get('status', 'ended')
                    }
                    recent_logins.append(login_info)

        # Sort by login time (most recent first)
        recent_logins.sort(key=lambda x: x.get('login_time', ''), reverse=True)

        # Security analytics
        failed_attempts = {}
        unique_ips_today = set()
        security_summary = {
            'failed_login_attempts_today': 0,
            'unique_ips_today': 0,
            'suspicious_activity': []
        }

        today = datetime.now().date()
        for key, attempts in login_history.items():
            if key.startswith('failed_'):
                failed_attempts[key] = attempts
                for attempt in attempts:
                    try:
                        attempt_date = datetime.fromisoformat(attempt['attempt_time']).date()
                        if attempt_date == today:
                            security_summary['failed_login_attempts_today'] += 1
                            unique_ips_today.add(attempt['ip_address'])

                            # Flag suspicious activity (more than 3 failed attempts from same IP)
                            ip_attempts = len([a for a in attempts if a['ip_address'] == attempt['ip_address']])
                            if ip_attempts > 3:
                                security_summary['suspicious_activity'].append({
                                    'ip': attempt['ip_address'],
                                    'attempts': ip_attempts,
                                    'last_attempt': attempt['attempt_time']
                                })
                    except:
                        continue

        security_summary['unique_ips_today'] = len(unique_ips_today)

        return jsonify({
            'sessions': session_list,
            'recent_logins': recent_logins[-20:],  # Last 20 logins
            'failed_attempts': failed_attempts,
            'security_summary': security_summary,
            'summary': {
                'total_active_sessions': len(session_list),
                'total_users_with_history': len([u for u in login_history.keys() if not u.startswith('failed_')]),
                'failed_attempts_today': security_summary['failed_login_attempts_today'],
                'unique_ips_today': security_summary['unique_ips_today'],
                'last_updated': datetime.now().isoformat()
            }
        })

    except Exception as e:
        logger.error(f"Error in session monitor: {str(e)}")
        return jsonify({'error': 'Failed to load session data'}), 500

@app.route('/api/temp_test_accounts', methods=['GET', 'POST', 'DELETE'])
@login_required
def manage_temp_test_accounts():
    """Manage temporary test accounts (admin only)"""
    username = session.get('username')
    if not is_admin(username):
        return jsonify({'error': 'Admin access required'}), 403

    if request.method == 'GET':
        # Return list of active test accounts
        current_time = datetime.now()
        active_accounts = []

        for test_id, data in temp_test_accounts.items():
            remaining_hours = (data['expires_at'] - current_time).total_seconds() / 3600
            if remaining_hours > 0:
                # Count active instances
                active_instances = sum(1 for proc_id in bot_processes 
                                     if proc_id.startswith(test_id) and bot_processes[proc_id]["process"].poll() is None)

                active_accounts.append({
                    'test_id': test_id,
                    'created_at': data['created_at'].isoformat(),
                    'expires_at': data['expires_at'].isoformat(),
                    'remaining_hours': round(remaining_hours, 2),
                    'used_count': data['used_count'],
                    'active_instances': active_instances,
                    'active_sessions': len(data['active_sessions'])
                })

        return jsonify({'test_accounts': active_accounts})

    elif request.method == 'POST':
        # Create new test account
        try:
            test_id, expires_at = create_temp_test_account()
            return jsonify({
                'success': True,
                'test_id': test_id,
                'password': test_id,  # Password is the same as test_id
                'expires_at': expires_at.isoformat(),
                'message': f'Test account {test_id} created successfully. Expires in 4 hours.'
            })
        except Exception as e:
            logger.error(f"Error creating test account: {str(e)}")
            return jsonify({'error': str(e)}), 500

    elif request.method == 'DELETE':
        # Delete specific test account
        data = request.json
        test_id = data.get('test_id')

        if not test_id or test_id not in temp_test_accounts:
            return jsonify({'error': 'Test account not found'}), 404

        try:
            cleanup_expired_test_account(test_id)
            return jsonify({'success': True, 'message': f'Test account {test_id} deleted successfully'})
        except Exception as e:
            logger.error(f"Error deleting test account {test_id}: {str(e)}")
            return jsonify({'error': str(e)}), 500

@app.route('/api/march_status_update', methods=['POST'])
def march_status_update():
    """Receive march status updates from bot instances"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        instance_id = data.get('instance_id')

        if not user_id or not instance_id:
            return jsonify({'error': 'Missing user_id or instance_id'}), 400

        # Update bot process data with march information
        if instance_id in bot_processes:
            bot_processes[instance_id].update({
                'current_marches': data.get('current_marches', 0),
                'march_limit': data.get('march_limit', 0),
                'march_size': data.get('march_size', 0),
                'last_march_update': data.get('timestamp', time.time())
            })

        # Clear status cache to force refresh
        global statusCache, lastStatusUpdate
        statusCache = None
        lastStatusUpdate = 0

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"Error updating march status: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<username>/reset_password', methods=['POST'])
@login_required
def reset_user_password(username):
    """Reset user password (admin only)"""
    current_username = session.get('username')
    if not is_admin(current_username):
        return jsonify({'error': 'Admin access required'}), 403

    try:
        data = request.json
        new_password = data.get('new_password')

        if not new_password:
            return jsonify({'error': 'New password is required'}), 400

        if len(new_password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters long'}), 400

        users = load_users()
        if username not in users:
            return jsonify({'error': 'User not found'}), 404

        # Update password
        users[username]['password'] = new_password

        # Rewrite file
        with open(USER_FILE, 'w') as f:
            f.write("# User Management File\n")
            f.write("# Format: username:password:max_instances:role:start_date:end_date:created_date\n")
            for user, user_data in users.items():
                start_date = user_data.get('start_date', '')
                end_date = user_data.get('end_date', '')
                created_date = user_data.get('created_date', '')
                role = user_data.get('role', 'user')
                f.write(f"{user}:{user_data['password']}:{user_data['max_instances']}:{role}:{start_date}:{end_date}:{created_date}\n")

        logger.info(f"Password reset for user {username} by admin {current_username}")
        return jsonify({'success': True, 'message': f'Password reset successfully for user {username}'})

    except Exception as e:
        logger.error(f"Error resetting password for user {username}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<username>', methods=['PUT', 'DELETE'])
@login_required
def manage_user_by_username(username):
    """Manage specific user by username (admin only)"""
    current_username = session.get('username')
    if current_username != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    if request.method == 'PUT':
        data = request.json
        new_max_instances = data.get('max_instances')

        if new_max_instances is None:
            return jsonify({'error': 'max_instances required'}), 400

        try:
            users = load_users()
            if username not in users:
                return jsonify({'error': 'User not found'}), 404

            users[username]['max_instances'] = int(new_max_instances)

            # Rewrite file
            with open(USER_FILE, 'w') as f:
                f.write("# User Management File\n")
                f.write("# Format: username:password:max_instances\n")
                for user, data in users.items():
                    f.write(f"{user}:{data['password']}:{data['max_instances']}\n")

            return jsonify({'success': True, 'message': 'User updated successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'DELETE':
        if username == 'admin':
            return jsonify({'error': 'Cannot delete admin user'}), 400

        try:
            users = load_users()
            if username not in users:
                return jsonify({'error': 'User not found'}), 404

            del users[username]

            # Rewrite file
            with open(USER_FILE, 'w') as f:
                f.write("# User Management File\n")
                f.write("# Format: username:password:max_instances\n")
                for user, data in users.items():
                    f.write(f"{user}:{data['password']}:{data['max_instances']}\n")

            return jsonify({'success': True, 'message': 'User deleted successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/user_instances/<username>', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def manage_user_instances(username):
    """Manage user instances (admin only)"""
    current_username = session.get('username')
    if not is_admin(current_username):
        return jsonify({'error': 'Admin access required'}), 403

    if request.method == 'GET':
        try:
            instances = load_user_instances()
            user_instances = instances.get(username, [])
            logger.info(f"Loaded {len(user_instances)} instances for user {username}")
            return jsonify({'instances': user_instances})
        except Exception as e:
            logger.error(f"Error loading instances for user {username}: {str(e)}")
            return jsonify({'error': f'Failed to load instances: {str(e)}'}), 500

    elif request.method == 'POST':
        # Add new instance
        data = request.json
        instance_name = data.get('instance_name')
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        if not all([instance_name, start_date, end_date]):
            return jsonify({'error': 'instance_name, start_date, and end_date are required'}), 400

        # Validate dates
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            if start_dt >= end_dt:
                return jsonify({'error': 'End date must be after start date'}), 400
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS'}), 400

        try:
            instances = load_user_instances()

            if username not in instances:
                instances[username] = []

            new_instance = {
                'instance_name': instance_name,
                'start_date': start_date,
                'end_date': end_date,
                'created_date': datetime.now().isoformat(),
                'status': 'active'
            }

            instances[username].append(new_instance)
            save_user_instances(instances)

            return jsonify({'success': True, 'message': 'Instance added successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'PUT':
        # Update instance
        data = request.json
        instance_index = data.get('instance_index')
        instance_name = data.get('instance_name')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        status = data.get('status', 'active')

        if instance_index is None:
            return jsonify({'error': 'instance_index is required'}), 400

        try:
            instances = load_user_instances()

            if username not in instances or instance_index >= len(instances[username]):
                return jsonify({'error': 'Instance not found'}), 404

            if instance_name:
                instances[username][instance_index]['instance_name'] = instance_name
            if start_date:
                instances[username][instance_index]['start_date'] = start_date
            if end_date:
                instances[username][instance_index]['end_date'] = end_date
            if status:
                instances[username][instance_index]['status'] = status

            save_user_instances(instances)

            return jsonify({'success': True, 'message': 'Instance updated successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'DELETE':
        # Delete instance
        data = request.json
        instance_index = data.get('instance_index')

        if instance_index is None:
            return jsonify({'error': 'instance_index is required'}), 400

        try:
            instances = load_user_instances()

            if username not in instances or instance_index >= len(instances[username]):
                return jsonify({'error': 'Instance not found'}), 404

            del instances[username][instance_index]

            if not instances[username]:
                del instances[username]

            save_user_instances(instances)

            return jsonify({'success': True, 'message': 'Instance deleted successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/login_history')
@login_required
def get_login_history():
    """Get login history for admin only"""
    username = session.get('username')

    if username != 'admin':
        return jsonify({'error': 'Admin access required to view login history'}), 403

    # Only admin can see detailed login history with IP addresses and user agents
    return jsonify({
        'login_history': login_history,
        'active_sessions': active_sessions
    })

@app.route('/api/daily_counters')
def get_daily_counters():
    """Get daily counters for current user"""
    if 'authenticated' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    user_id = session['user_id']
    today = datetime.now().date().isoformat()

    counters = {
        'gathering': get_daily_counter(user_id, 'gathering'),
        'rally_join': get_daily_counter(user_id, 'rally_join'),
        'rally_start': get_daily_counter(user_id, 'rally_start'),
        'monster_attack': get_daily_counter(user_id, 'monster_attack'),
        'object_scan': get_daily_counter(user_id, 'object_scan'),
        'crystal_mine': get_daily_counter(user_id, 'crystal_mine'),
        'dragon_soul': get_daily_counter(user_id, 'dragon_soul')
    }

    return jsonify({'counters': counters, 'date': today})

@app.route('/api/notifications/stats')
@login_required
def get_notification_stats():
    """Get notification statistics for current user"""
    user_id = session['user_id']

    try:
        user_notifications = notifications_history.get(user_id, {})

        # Calculate statistics
        total_notifications = sum(len(notifications) for notifications in user_notifications.values())
        total_accounts = len(user_notifications)

        # Today's notifications
        today = datetime.now().date()
        today_notifications = 0
        for account_notifications in user_notifications.values():
            for notification in account_notifications:
                try:
                    notification_date = datetime.fromisoformat(notification['timestamp'].replace('Z', '+00:00')).date()
                    if notification_date == today:
                        today_notifications += 1
                except:
                    continue

        # Account breakdown
        account_stats = {}
        for account_name, notifications in user_notifications.items():
            today_count = 0
            for notification in notifications:
                try:
                    notification_date = datetime.fromisoformat(notification['timestamp'].replace('Z', '+00:00')).date()
                    if notification_date == today:
                        today_count += 1
                except:
                    continue

            account_stats[account_name] = {
                'total': len(notifications),
                'today': today_count
            }

        return jsonify({
            'total_notifications': total_notifications,
            'today_notifications': today_notifications,
            'total_accounts': total_accounts,
            'account_stats': account_stats,
            'queue_size': notification_queues.get(user_id, queue.Queue()).qsize() if user_id in notification_queues else 0
        })

    except Exception as e:
        logger.error(f"Error getting notification stats for user {user_id}: {str(e)}")
        return jsonify({'error': 'Failed to get notification statistics'}), 500



@app.route('/api/march_status')
@login_required
def get_march_status():
    """Get active bot status for all running bot instances with real march data"""
    user_id = session['user_id']
    username = session.get('username', user_id)

    try:
        active_bots_list = []

        # Clean up dead processes first
        dead_processes = []
        for proc_id in list(bot_processes.keys()):
            try:
                process = bot_processes[proc_id]["process"]
                if process.poll() is not None:  # Process has ended
                    dead_processes.append(proc_id)
            except Exception:
                dead_processes.append(proc_id)

        for proc_id in dead_processes:
            if proc_id in bot_processes:
                del bot_processes[proc_id]

        # Get cached march status data if available
        march_status_cache = getattr(app, 'march_status_cache', {})

        # Get active bot instances
        for proc_id, proc_data in bot_processes.items():
            try:
                process = proc_data["process"]
                instance_username = proc_data.get('user_id', 'unknown')

                # Only include user's own instances (unless admin viewing all)
                if not (instance_username == user_id or is_admin(username)):
                    continue

                # Verify process is actually running
                if process.poll() is None:
                    account_name = proc_data.get('name', f'Instance {proc_id.split("_")[-1]}')
                    config_file = proc_data.get('config_file', 'config.json')

                    # Get cached march data if available
                    cached_data = march_status_cache.get(proc_id, {})
                    current_marches = cached_data.get('current_marches', 0)
                    cached_max_marches = cached_data.get('max_marches', 0)
                    last_updated = cached_data.get('last_updated', time.time())

                    # Always try to get max marches from config file for accurate data
                    max_marches = 8  # Default fallback
                    config_source = 'default'

                    try:
                        if os.path.exists(config_file):
                            with open(config_file, 'r') as f:
                                config = json.load(f)

                                # Get max marches from different configuration sources
                                march_limits = []

                                # Check rally join config
                                rally_join_marches = config.get('rally', {}).get('join', {}).get('numMarch', 0)
                                if rally_join_marches > 0:
                                    march_limits.append(rally_join_marches)

                                # Check rally start config
                                rally_start_marches = config.get('rally', {}).get('start', {}).get('numMarch', 0)
                                if rally_start_marches > 0:
                                    march_limits.append(rally_start_marches)

                                # Check object scanning max marches
                                object_scanning_marches = config.get('main', {}).get('object_scanning', {}).get('max_marches', 0)
                                if object_scanning_marches > 0:
                                    march_limits.append(object_scanning_marches)

                                # Check socf_thread job for object scanning
                                for job in config.get('main', {}).get('jobs', []):
                                    if job.get('name') == 'socf_thread' and job.get('enabled', False):
                                        job_marches = job.get('kwargs', {}).get('max_marches', 0)
                                        if job_marches > 0:
                                            march_limits.append(job_marches)

                                # Use the highest configured march limit
                                if march_limits:
                                    max_marches = max(march_limits)
                                    config_source = config_file
                                else:
                                    # Fallback to cached value if available
                                    if cached_max_marches > 0:
                                        max_marches = cached_max_marches
                                        config_source = 'cached'

                    except Exception as e:
                        logger.debug(f"Could not read config {config_file}: {str(e)}")
                        # Use cached value as fallback
                        if cached_max_marches > 0:
                            max_marches = cached_max_marches
                            config_source = 'cached'

                    active_bots_list.append({
                        'account_name': account_name,
                        'max_marches': max_marches,
                        'current_marches': current_marches,
                        'percentage': round((current_marches / max_marches * 100), 1) if max_marches > 0 else 0,
                        'instance_id': proc_id,
                        'username': instance_username,
                        'config_file': config_file,
                        'config_source': config_source,
                        'status': 'running',
                        'last_updated': last_updated,
                        'internal_queue': cached_data.get('internal_queue', 0),
                        'api_march_count': cached_data.get('api_march_count', 0),
                        'active_tasks': cached_data.get('active_tasks', 0)
                    })

            except Exception as e:
                logger.error(f"Error processing bot instance {proc_id}: {str(e)}")
                continue

        return jsonify({
            'success': True,
            'march_status': active_bots_list,
            'total_active': len(active_bots_list)
        })

    except Exception as e:
        logger.error(f"Error getting bot status for user {user_id}: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to load bot status',
            'march_status': []
        })

@app.route('/api/notifications/clear', methods=['POST'])
@login_required
def clear_notifications():
    """Clear all notifications for the current user"""
    user_id = session['user_id']

    try:
        # Clear notifications history
        if user_id in notifications_history:
            notifications_history[user_id] = {}

        # Clear notification queue
        if user_id in notification_queues:
            try:
                while not notification_queues[user_id].empty():
                    notification_queues[user_id].get_nowait()
            except:
                pass

        # Clear daily counters (optional - user might want to keep these)
        # if user_id in daily_counters:
        #     daily_counters[user_id] = {}

        return jsonify({'success': True, 'message': 'All notifications cleared successfully'})
    except Exception as e:
        logger.error(f"Error clearing notifications for user {user_id}: {str(e)}")
        return jsonify({'error': 'Failed to clear notifications'}), 500

@app.route('/api/notifications/clear_instance', methods=['POST'])
@login_required
def clear_instance_notifications():
    """Clear notifications for a specific instance/account"""
    user_id = session['user_id']
    data = request.json
    account_name = data.get('account_name')

    if not account_name:
        return jsonify({'error': 'Account name is required'}), 400

    try:
        # Clear notifications history for specific account
        if user_id in notifications_history and account_name in notifications_history[user_id]:
            del notifications_history[user_id][account_name]

        # Clear notification queue items for this account
        if user_id in notification_queues:
            try:
                # Create a new queue with notifications that don't belong to this account
                old_queue = notification_queues[user_id]
                new_queue = queue.Queue(maxsize=25)

                temp_notifications = []
                while not old_queue.empty():
                    try:
                        notification = old_queue.get_nowait()
                        if notification.get('account_name') != account_name:
                            temp_notifications.append(notification)
                    except queue.Empty:
                        break

                # Put back the notifications that don't belong to the cleared account
                for notification in temp_notifications:
                    try:
                        new_queue.put_nowait(notification)
                    except queue.Full:
                        break

                notification_queues[user_id] = new_queue
            except Exception as e:
                logger.warning(f"Error filtering notification queue: {str(e)}")

        logger.info(f"Cleared notifications for user {user_id} account {account_name}")
        return jsonify({'success': True, 'message': f'Notifications cleared for {account_name}'})
    except Exception as e:
        logger.error(f"Error clearing instance notifications for user {user_id} account {account_name}: {str(e)}")
        return jsonify({'error': 'Failed to clear instance notifications'}), 500

@app.route('/api/config/monsters', methods=['GET', 'POST'])
@login_required
def handle_monsters_config():
    """Manage monster configurations for rally join/start"""
    user_id = session['user_id']
    config_file = f"data/config_{user_id}.json"

    if request.method == 'GET':
        try:
            config = ConfigHelper.load_config()
            monsters = {
                'rally_join': config.get('rally', {}).get('join', {}).get('targets', []),
                'rally_start': config.get('rally', {}).get('start', {}).get('targets', [])
            }
            return jsonify(monsters)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            data = request.json
            rally_type = data.get('rally_type')  # 'join' or 'start'
            monsters = data.get('monsters', [])

            config = ConfigHelper.load_config()

            if 'rally' not in config:
                config['rally'] = {}

            if rally_type not in config['rally']:
                config['rally'][rally_type] = {
                    'enabled': False,
                    'numMarch': 8 if rally_type == 'join' else 6,
                    'level_based_troops': True,
                    'targets': []
                }

            config['rally'][rally_type]['targets'] = monsters

            success = ConfigHelper.save_config(config, config_file)
            if success:
                return jsonify({'success': True, 'message': f'Updated {rally_type} monsters'})
            else:
                return jsonify({'error': 'Failed to save configuration'}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/config/objects', methods=['GET', 'POST'])
@login_required
def handle_objects_config():
    """Manage object scanning configurations"""
    user_id = session['user_id']
    config_file = f"data/config_{user_id}.json"

    if request.method == 'GET':
        try:
            config = ConfigHelper.load_config()

            # Get objects from socf_thread job
            objects = []
            for job in config.get('main', {}).get('jobs', []):
                if job.get('name') == 'socf_thread':
                    objects = job.get('kwargs', {}).get('targets', [])
                    break

            return jsonify({'objects': objects})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            data = request.json
            objects = data.get('objects', [])

            config = ConfigHelper.load_config()

            # Update socf_thread job targets
            for job in config.get('main', {}).get('jobs', []):
                if job.get('name') == 'socf_thread':
                    if 'kwargs' not in job:
                        job['kwargs'] = {}
                    job['kwargs']['targets'] = objects
                    break

            success = ConfigHelper.save_config(config, config_file)
            if success:
                return jsonify({'success': True, 'message': 'Updated object targets'})
            else:
                return jsonify({'error': 'Failed to save configuration'}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/config/troops', methods=['GET', 'POST'])
@login_required
def handle_troops_config():
    """Manage troop configurations"""
    user_id = session['user_id']
    config_file = f"data/config_{user_id}.json"

    if request.method == 'GET':
        try:
            config = ConfigHelper.load_config()

            # Get predefined troops from assets
            troop_types = [
                {"code": 50100301, "name": "Scout (Tier 1 Cavalry)"},
                {"code": 50100302, "name": "Horseman (Tier 2 Cavalry)"},
                {"code": 50100303, "name": "Heavy Cavalry (Tier 3 Cavalry)"},
                {"code": 50100304, "name": "Iron Cavalry (Tier 4 Cavalry)"},
                {"code": 50100305, "name": "Dragoon (Tier 5 Cavalry)"},
                {"code": 50100306, "name": "Marauder (Tier 6 Cavalry)"},
                {"code": 50100201, "name": "Bowman (Tier 1 Ranged)"},
                {"code": 50100202, "name": "Hunter (Tier 2 Ranged)"},
                {"code": 50100203, "name": "Ranger (Tier 3 Ranged)"},
                {"code": 50100204, "name": "Crossbowman (Tier 4 Ranged)"},
                {"code": 50100205, "name": "Longbowman (Tier 5 Ranged)"},
                {"code": 50100206, "name": "Stealth Archer (Tier 6 Ranged)"},
                {"code": 50100101, "name": "Spearman (Tier 1 Infantry)"},
                {"code": 50100102, "name": "Swordsman (Tier 2 Infantry)"},
                {"code": 50100103, "name": "Pikeman (Tier 3 Infantry)"},
                {"code": 50100104, "name": "Royal Guardsman (Tier 4 Infantry)"},
                {"code": 50100105, "name": "Cataphract (Tier 5 Infantry)"},
                {"code": 50100106, "name": "Immortal (Tier 6 Infantry)"}
            ]

            common_troops = config.get('main', {}).get('normal_monsters', {}).get('common_troops', [])

            return jsonify({
                'available_troops': troop_types,
                'common_troops': common_troops
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            data = request.json
            common_troops = data.get('common_troops', [])

            config = ConfigHelper.load_config()

            if 'main' not in config:
                config['main'] = {}
            if 'normal_monsters' not in config['main']:
                config['main']['normal_monsters'] = {}

            config['main']['normal_monsters']['common_troops'] = common_troops

            success = ConfigHelper.save_config(config, config_file)
            if success:
                return jsonify({'success': True, 'message': 'Updated troop settings'})
            else:
                return jsonify({'error': 'Failed to save configuration'}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/config/presets')
def get_config_presets():
    """Get predefined monster and object presets"""
    if 'authenticated' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    presets = {
        'monsters': [
            {"code": 20200201, "name": "Deathkar"},
            {"code": 20200202, "name": "Green Dragon"},
            {"code": 20200203, "name": "Red Dragon"},
            {"code": 20200204, "name": "Gold Dragon"},
            {"code": 20200101, "name": "Orc"},
            {"code": 20200102, "name": "Skeleton"},
            {"code": 20200103, "name": "Golem"},
            {"code": 20200104, "name": "Treasure Goblin"}
        ],
        'objects': [
            {"code": 20100101, "name": "Farm"},
            {"code": 20100102, "name": "Gold Mine"},
            {"code": 20100103, "name": "Lumber Camp"},
            {"code": 20100104, "name": "Quarry"},
            {"code": 20100105, "name": "Crystal Mine"},
            {"code": 20100106, "name": "Dragon Soul Cavern"}
        ]
    }

    return jsonify(presets)

@app.route('/api/config/common_troops', methods=['GET', 'POST'])
@login_required
def handle_common_troops_config():
    """Manage common troops configurations"""
    user_id = session['user_id']
    username = session.get('username', user_id)

    if request.method == 'GET':
        try:
            # Get selected config file from request or use default
            selected_config = request.args.get('config_file', 'config.json')

            # Check if user has access to this config file
            if not has_config_access(username, selected_config):
                return jsonify({'error': 'Access denied to this config file'}), 403

            # Load the selected config file
            if os.path.exists(selected_config):
                with open(selected_config, 'r') as f:
                    config = json.load(f)
            else:
                return jsonify({'error': f'Config file {selected_config} not found'}), 404

            # Get common troops from config
            common_troops = config.get('main', {}).get('normal_monsters', {}).get('common_troops', [])

            return jsonify({'troops': common_troops})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            data = request.json
            troops = data.get('troops', [])
            selected_config = data.get('config_file', 'config.json')

            # Check if user has access to this config file
            if not has_config_access(username, selected_config):
                return jsonify({'error': 'Access denied to this config file'}), 403

            # Ensure the config file exists
            if not os.path.exists(selected_config):
                return jsonify({'error': f'Config file {selected_config} not found'}), 404

            # Load config
            with open(selected_config, 'r') as f:
                config = json.load(f)

            # Update common troops
            if 'main' not in config:
                config['main'] = {}
            if 'normal_monsters' not in config['main']:
                config['main']['normal_monsters'] = {}

            config['main']['normal_monsters']['common_troops'] = troops

            # Save config
            with open(selected_config, 'w') as f:
                json.dump(config, f, indent=2, sort_keys=False, separators=(',', ': '))

            return jsonify({'success': True, 'message': 'Common troops updated successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/config/alliance_farmer', methods=['POST'])
@login_required
def update_alliance_farmer_config():
    """Update alliance farmer individual feature settings"""
    try:
        data = request.json
        feature_name = data.get('feature_name')
        enabled = data.get('enabled', False)
        selected_config = data.get('config_file', 'config.json')
        username = session.get('username', session['user_id'])

        # Check if user has access to this config file
        if not has_config_access(username, selected_config):
            return jsonify({'error': 'Access denied to this config file'}), 403

        # Load config
        if os.path.exists(selected_config):
            with open(selected_config, 'r') as f:
                config = json.load(f)
        else:
            return jsonify({'error': f'Config file {selected_config} not found'}), 404

        # Find alliance_farmer job
        alliance_job = None
        for job in config.get('main', {}).get('jobs', []):
            if job.get('name') == 'alliance_farmer':
                alliance_job = job
                break

        if not alliance_job:
            return jsonify({'error': 'Alliance farmer job not found'}), 404

        # Ensure kwargs exists
        if 'kwargs' not in alliance_job:
            alliance_job['kwargs'] = {}

        # Update specific feature
        if feature_name == 'gift_claim':
            alliance_job['kwargs']['gift_claim'] = enabled
        elif feature_name == 'help_all':
            alliance_job['kwargs']['help_all'] = enabled
        elif feature_name == 'research_donate':
            alliance_job['kwargs']['research_donate'] = enabled
        elif feature_name == 'shop_auto_buy':
            if enabled:
                alliance_job['kwargs']['shop_auto_buy_item_code_list'] = alliance_job['kwargs'].get('shop_auto_buy_item_code_list', [10101008])
            else:
                alliance_job['kwargs']['shop_auto_buy_item_code_list'] = []
        else:
            return jsonify({'error': 'Invalid feature name'}), 400

        # Save config
        with open(selected_config, 'w') as f:
            json.dump(config, f, indent=2)

        return jsonify({'success': True, 'message': f'Alliance farmer {feature_name} updated successfully'})

    except Exception as e:
        logger.error(f"Error updating alliance farmer config: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/socf_objects', methods=['GET', 'POST'])
def handle_socf_objects_config():
    """Manage socf_thread objects configuration"""
    if 'authenticated' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    user_id = session['user_id']
    username = session.get('username', user_id)

    if request.method == 'GET':
        try:
            # Get selected config file from request or use default
            selected_config = request.args.get('config_file', 'config.json')

            # Check if user has access to this config file
            if not has_config_access(username, selected_config):
                return jsonify({'error': 'Access denied to this config file'}), 403

            # Load the selected config file
            if os.path.exists(selected_config):
                with open(selected_config, 'r') as f:
                    config = json.load(f)
            else:
                return jsonify({'error': f'Config file {selected_config} not found'}), 404

            # Get objects from socf_thread job
            socf_objects = []
            socf_enabled = False
            socf_radius = 16

            for job in config.get('main', {}).get('jobs', []):
                if job.get('name') == 'socf_thread':
                    socf_objects = job.get('kwargs', {}).get('targets', [])
                    socf_enabled = job.get('enabled', False)
                    socf_radius = job.get('kwargs', {}).get('radius', 16)
                    break

            return jsonify({
                'objects': socf_objects,
                'enabled': socf_enabled,
                'radius': socf_radius
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            data = request.json
            objects = data.get('objects', [])
            enabled = data.get('enabled', False)
            radius = data.get('radius', 16)
            selected_config = data.get('config_file', 'config.json')

            # Check if user has access to this config file
            if not has_config_access(username, selected_config):
                return jsonify({'error': 'Access denied to this config file'}), 403

            # Ensure the config file exists
            if not os.path.exists(selected_config):
                return jsonify({'error': f'Config file {selected_config} not found'}), 404

            # Load config
            with open(selected_config, 'r') as f:
                config = json.load(f)

            # Update socf_thread job targets
            socf_job_found = False
            for job in config.get('main', {}).get('jobs', []):
                if job.get('name') == 'socf_thread':
                    if 'kwargs' not in job:
                        job['kwargs'] = {}
                    job['kwargs']['targets'] = objects
                    job['kwargs']['radius'] = radius
                    job['enabled'] = enabled
                    socf_job_found = True
                    break

            # If socf_thread job doesn't exist, create it
            if not socf_job_found:
                if 'main' not in config:
                    config['main'] = {}
                if 'jobs' not in config['main']:
                    config['main']['jobs'] = []

                config['main']['jobs'].append({
                    "name": "socf_thread",
                    "enabled": enabled,
                    "interval": {"start": 1, "end": 1},
                    "kwargs": {
                        "targets": objects,
                        "radius": radius,
                        "share_to": {
                            "chat_channels": [0, 0]
                        }
                    }
                })

            # Save config
            with open(selected_config, 'w') as f:
                json.dump(config, f, indent=2, sort_keys=False, separators=(',', ': '))

            return jsonify({'success': True, 'message': 'Updated socf_thread objects'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/simple-config')
def simple_config():
    """Route for simplified configuration interface"""
    if 'authenticated' not in session:
        return redirect(url_for('login'))
    return render_template('simple_config.html')

@app.route('/api/simple_config', methods=['GET', 'POST'])
@login_required
def handle_simple_config():
    """Handle simplified configuration data"""
    user_id = session['user_id']
    username = session.get('username', user_id)

    if request.method == 'GET':
        try:
            # Get the current config file
            selected_config = request.args.get('config_file', 'config.json')

            # Check if user has access to this config file
            if not has_config_access(username, selected_config):
                return jsonify({'error': 'Access denied to this config file'}), 403

            # Load the selected config file
            if os.path.exists(selected_config):
                with open(selected_config, 'r') as f:
                    config = json.load(f)
            else:
                return jsonify({'error': f'Config file {selected_config} not found'}), 404

            # Return the full config for the simple config page to work with
            return jsonify(config)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            data = request.json
            config_type = data.get('config_type')
            config_data = data.get('config')
            selected_config = data.get('config_file', 'config.json')

            # Check if user has access to this config file
            if not has_config_access(username, selected_config):
                return jsonify({'error': 'Access denied to this config file'}), 403

            # Load existing config
            if os.path.exists(selected_config):
                with open(selected_config, 'r') as f:
                    full_config = json.load(f)
            else:
                full_config = {}

            # Update the relevant section based on config_type
            if config_type == 'rally-join':
                if 'rally' not in full_config:
                    full_config['rally'] = {}
                full_config['rally']['join'] = config_data

            elif config_type == 'rally-start':
                if 'rally' not in full_config:
                    full_config['rally'] = {}
                full_config['rally']['start'] = config_data

            elif config_type == 'monster-attack':
                if 'main' not in full_config:
                    full_config['main'] = {}
                full_config['main']['normal_monsters'] = config_data

            # Save the updated config
            with open(selected_config, 'w') as f:
                json.dump(full_config, f, indent=2)

            return jsonify({'success': True, 'message': f'{config_type} configuration updated successfully'})

        except Exception as e:
            logger.error(f"Error saving simple config: {str(e)}")
            return jsonify({'error': str(e)}), 500

@app.route('/api/schedule/tasks', methods=['GET', 'POST'])
def handle_scheduled_tasks():
    """Manage scheduled tasks"""
    if 'authenticated' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    user_id = session['user_id']

    if request.method == 'GET':
        user_tasks = {k: v for k, v in scheduled_tasks.items() if v.get('user_id') == user_id}
        return jsonify({'tasks': user_tasks})

    elif request.method == 'POST':
        try:
            data = request.json
            task_type = data.get('task_type')  # 'start_bot', 'stop_bot', 'config_change', 'maintenance'
            schedule_time = data.get('schedule_time')  # ISO format or cron expression
            task_data = data.get('task_data', {})
            task_name = data.get('task_name', f'{task_type}_{int(time.time())}')

            task_id = f"{user_id}_{task_name}"

            # Parse schedule time
            if 'cron' in data:
                # Cron expression
                trigger = CronTrigger.from_crontab(data['cron'])
            else:
                # One-time scheduled task
                schedule_dt = datetime.fromisoformat(schedule_time.replace('Z', '+00:00'))
                trigger = 'date'

            # Add job to scheduler
            if task_type == 'start_bot':
                job = scheduler.add_job(
                    execute_scheduled_start_bot,
                    trigger=trigger,
                    args=[user_id, task_data],
                    id=task_id,
                    replace_existing=True
                )
            elif task_type == 'stop_bot':
                job = scheduler.add_job(
                    execute_scheduled_stop_bot,
                    trigger=trigger,
                    args=[user_id, task_data],
                    id=task_id,
                    replace_existing=True
                )
            elif task_type == 'config_change':
                job = scheduler.add_job(
                    execute_scheduled_config_change,
                    trigger=trigger,
                    args=[user_id, task_data],
                    id=task_id,
                    replace_existing=True
                )
            elif task_type == 'maintenance':
                job = scheduler.add_job(
                    execute_maintenance_mode,
                    trigger=trigger,
                    args=[task_data],
                    id=task_id,
                    replace_existing=True
                )

            # Store task info
            scheduled_tasks[task_id] = {
                'user_id': user_id,
                'task_type': task_type,
                'task_name': task_name,
                'schedule_time': schedule_time,
                'task_data': task_data,
                'created_at': datetime.now().isoformat(),
                'status': 'scheduled'
            }

            return jsonify({'success': True, 'task_id': task_id, 'message': 'Task scheduled successfully'})

        except Exception as e:
            logger.error(f"Error scheduling task: {str(e)}")
            return jsonify({'error': str(e)}), 500

@app.route('/api/schedule/tasks/<task_id>', methods=['DELETE'])
def delete_scheduled_task(task_id):
    """Delete a scheduled task"""
    if 'authenticated' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    user_id = session['user_id']

    if task_id not in scheduled_tasks or scheduled_tasks[task_id].get('user_id') != user_id:
        return jsonify({'error': 'Task not found'}), 404

    try:
        # Remove from scheduler
        scheduler.remove_job(task_id)
        # Remove from our tracking
        del scheduled_tasks[task_id]

        return jsonify({'success': True, 'message': 'Task deleted successfully'})
    except Exception as e:
        logger.error(f"Error deleting scheduled task: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/maintenance', methods=['GET', 'POST'])
def handle_maintenance_mode():
    """Manage maintenance mode"""
    if 'authenticated' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    if request.method == 'GET':
        return jsonify(maintenance_mode)

    elif request.method == 'POST':
        try:
            data = request.json
            action = data.get('action')  # 'enable', 'disable', 'schedule'

            if action == 'enable':
                maintenance_mode['enabled'] = True
                maintenance_mode['message'] = data.get('message', 'System under maintenance')
                # Stop all running bots
                for proc_id in list(bot_processes.keys()):
                    process = bot_processes[proc_id]["process"]
                    if process.poll() is None:
                        process.terminate()

                add_notification('system', 'maintenance', 'Maintenance Mode Enabled', maintenance_mode['message'])

            elif action == 'disable':
                maintenance_mode['enabled'] = False
                maintenance_mode['scheduled_end'] = None
                add_notification('system', 'maintenance', 'Maintenance Mode Disabled', 'System is back online')

            elif action == 'schedule':
                end_time = data.get('end_time')
                if end_time:
                    maintenance_mode['scheduled_end'] = end_time
                    # Schedule maintenance mode disable
                    scheduler.add_job(
                        lambda: handle_maintenance_mode_end(),
                        'date',
                        run_date=datetime.fromisoformat(end_time.replace('Z', '+00:00')),
                        id='maintenance_end',
                        replace_existing=True
                    )

            return jsonify({'success': True, 'maintenance_mode': maintenance_mode})

        except Exception as e:
            logger.error(f"Error managing maintenance mode: {str(e)}")
            return jsonify({'error': str(e)}), 500

def execute_scheduled_start_bot(user_id, task_data):
    """Execute scheduled bot start"""
    try:
        # Implementation similar to start_bot endpoint but automated
        add_notification(user_id, 'scheduled_task', 'Scheduled Bot Start', f"Automated bot start executed")
        logger.info(f"Executed scheduled bot start for user {user_id}")
    except Exception as e:
        logger.error(f"Error in scheduled bot start: {str(e)}")

def execute_scheduled_stop_bot(user_id, task_data):
    """Execute scheduled bot stop"""
    try:
        # Stop user's bots
        stopped_count = 0
        for proc_id in list(bot_processes.keys()):
            if proc_id.startswith(user_id):
                process = bot_processes[proc_id]["process"]
                if process.poll() is None:
                    process.terminate()
                    stopped_count += 1
                del bot_processes[proc_id]

        add_notification(user_id, 'scheduled_task', 'Scheduled Bot Stop', f"Stopped {stopped_count} bot instance(s)")
        logger.info(f"Executed scheduled bot stop for user {user_id}")
    except Exception as e:
        logger.error(f"Error in scheduled bot stop: {str(e)}")

def execute_scheduled_config_change(user_id, task_data):
    """Execute scheduled configuration change"""
    try:
        config_file = task_data.get('config_file', 'config.json')
        config_changes = task_data.get('config_changes', {})

        # Load and update config
        config = ConfigHelper.load_config()
        config.update(config_changes)
        ConfigHelper.save_config(config, config_file)

        add_notification(user_id, 'scheduled_task', 'Scheduled Config Change', f"Configuration updated automatically")
        logger.info(f"Executed scheduled config change for user {user_id}")
    except Exception as e:
        logger.error(f"Error in scheduled config change: {str(e)}")

def execute_maintenance_mode(task_data):
    """Execute maintenance mode"""
    try:
        maintenance_mode['enabled'] = True
        maintenance_mode['message'] = task_data.get('message', 'Scheduled maintenance')

        # Stop all bots
        for proc_id in list(bot_processes.keys()):
            process = bot_processes[proc_id]["process"]
            if process.poll() is None:
                process.terminate()

        add_notification('system', 'maintenance', 'Scheduled Maintenance', maintenance_mode['message'])
        logger.info("Executed scheduled maintenance mode")
    except Exception as e:
        logger.error(f"Error in scheduled maintenance: {str(e)}")

def handle_maintenance_mode_end():
    """Handle end of scheduled maintenance"""
    maintenance_mode['enabled'] = False
    maintenance_mode['scheduled_end'] = None
    add_notification('system', 'maintenance', 'Maintenance Complete', 'Scheduled maintenance has ended')

def create_temp_test_account():
    """Create a temporary test account that expires in 4 hours"""
    import uuid

    test_id = f"test_{uuid.uuid4().hex[:8]}"
    current_time = datetime.now()
    expires_at = current_time + timedelta(hours=4)

    temp_test_accounts[test_id] = {
        'created_at': current_time,
        'expires_at': expires_at,
        'active_sessions': set(),
        'used_count': 0
    }

    # Auto-assign specific config files to test accounts
    test_config_files = [
        "Nodes Finder.json",
        "Auto Rally CVC.json", 
        "Auto Monster Attack.json"
    ]

    try:
        # Load existing assignments
        assignments = load_user_config_assignments()

        # Assign the test config files to this test account
        assignments[test_id] = ",".join(test_config_files)

        # Save the updated assignments
        with open("user_config_assignments.txt", 'w') as f:
            for user, config_files in assignments.items():
                f.write(f"{user}:{config_files}\n")

        logger.info(f"Auto-assigned config files to test account {test_id}: {test_config_files}")

    except Exception as e:
        logger.error(f"Failed to auto-assign config files to test account {test_id}: {str(e)}")

    # Schedule automatic cleanup
    scheduler.add_job(
        cleanup_expired_test_account,
        'date',
        run_date=expires_at,
        args=[test_id],
        id=f'cleanup_test_{test_id}',
        replace_existing=True
    )

    logger.info(f"Created temporary test account {test_id} that expires at {expires_at}")
    return test_id, expires_at

def cleanup_expired_test_account(test_id):
    """Clean up expired test account and stop all its instances"""
    try:
        if test_id not in temp_test_accounts:
            return

        test_data = temp_test_accounts[test_id]

        # Stop all bot instances for this test account
        instances_to_stop = []
        for proc_id in list(bot_processes.keys()):
            if proc_id.startswith(test_id):
                instances_to_stop.append(proc_id)

        for proc_id in instances_to_stop:
            try:
                process = bot_processes[proc_id]["process"]
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                del bot_processes[proc_id]
                logger.info(f"Stopped bot instance {proc_id} for expired test account {test_id}")
            except Exception as e:
                logger.error(f"Error stopping bot instance {proc_id}: {str(e)}")

        # Clear active sessions
        for session_id in list(active_sessions.keys()):
            if active_sessions[session_id].get('username') == test_id:
                del active_sessions[session_id]

        # Clear login history
        if test_id in login_history:
            del login_history[test_id]

        # Clear notifications
        if test_id in notifications_history:
            del notifications_history[test_id]
        if test_id in notification_queues:
            del notification_queues[test_id]

        # Remove config assignments for this test account
        try:
            assignments = load_user_config_assignments()
            if test_id in assignments:
                del assignments[test_id]

                # Save the updated assignments
                with open("user_config_assignments.txt", 'w') as f:
                    for user, config_files in assignments.items():
                        f.write(f"{user}:{config_files}\n")

                logger.info(f"Removed config assignments for expired test account {test_id}")
        except Exception as e:
            logger.error(f"Error removing config assignments for test account {test_id}: {str(e)}")

        # Remove from temp accounts
        del temp_test_accounts[test_id]

        logger.info(f"Cleaned up expired test account {test_id} and stopped {len(instances_to_stop)} instances")

    except Exception as e:
        logger.error(f"Error cleaning up test account {test_id}: {str(e)}")

def is_temp_test_account(username):
    """Check if username is a temporary test account"""
    return username.startswith('test_') and username in temp_test_accounts

def validate_temp_test_account(username):
    """Validate temporary test account and check if it's still valid"""
    if not is_temp_test_account(username):
        return False

    if username not in temp_test_accounts:
        return False

    test_data = temp_test_accounts[username]
    current_time = datetime.now()

    if current_time >= test_data['expires_at']:
        # Account expired, clean it up
        cleanup_expired_test_account(username)
        return False

    return True

@app.route('/favicon.ico')
def favicon():
    # Return a simple SVG favicon
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
        <rect width="32" height="32" fill="#00ff88"/>
        <path d="M8 8h16v16H8z" fill="white"/>
        <circle cx="12" cy="16" r="2" fill="#00ff88"/>
        <circle cx="20" cy="16" r="2" fill="#00ff88"/>
    </svg>'''
    return Response(svg, mimetype='image/svg+xml')

if __name__ == '__main__':
    # Ensure data directory exists
    os.makedirs('data', exist_ok=True)

    # Production configuration
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    app.run(host='0.0.0.0', port=port, debug=debug_mode, threaded=True)
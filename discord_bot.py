import discord
from discord import app_commands
from typing import Optional
import json
import os
import logging
import subprocess
from lokbot.config_helper import ConfigHelper

# Note: This bot provides multiple commands for configuration, 
# but the recommended way to configure is through the unified
# /config setup command which includes all features.

from lokbot.discord_commands import RallyConfigCommands
import asyncio
from dotenv import load_dotenv
from lokbot.util import decode_jwt
import logging
import psutil
import http.server
import threading
import platform

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Bot processes dictionary to track running instances
bot_processes = {}

# Discord bot setup
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def is_admin(interaction: discord.Interaction):
    # Allow all users
    return True


def get_valid_token():
    """Get valid token through email auth"""
    email = os.getenv('LOK_EMAIL')
    password = os.getenv('LOK_PASSWORD')

    if not email or not password:
        logger.error("LOK_EMAIL and LOK_PASSWORD must be set in environment")
        return None

    try:
        from lokbot.client import LokBotApi
        api = LokBotApi(None, {}, skip_jwt=True)  # No token needed for initial auth
        auth_result = api.auth_login(email, password)

        if not auth_result.get('result'):
            logger.error("Login failed with provided credentials")
            return None

        token = auth_result.get('token')

        # Get user ID from token
        import lokbot.util
        _id = lokbot.util.decode_jwt(token).get('_id')

        # Save token to file
        with open(f"data/{_id}.token", "w") as f:
            f.write(token)

        return token
    except Exception as e:
        logger.error(f"Error getting token: {str(e)}")
        return None

# Configuration is now unified - no need for config choices

@tree.command(name="run", description="Start the Rayna")
@app_commands.describe(config_file="Select configuration file to use")
async def start_bot(interaction: discord.Interaction, config_file: str = None):
    if not is_admin(interaction):
        await interaction.response.send_message("Only administrators can use this command!", ephemeral=True)
        return

    # Get list of available config files
    config_files = [f for f in os.listdir('.') if f.endswith('.json')]

    # Create config selection view
    view = discord.ui.View(timeout=300)
    config_select = discord.ui.Select(
        placeholder="Select a configuration file",
        options=[discord.SelectOption(label=f"{file}", value=file) for file in config_files]
    )

    # Add a lock to prevent race conditions
    async def process_command():
        user_id = str(interaction.user.id)
        instance_count = sum(1 for proc_id in bot_processes if proc_id.startswith(user_id) and bot_processes[proc_id]["process"].poll() is None)

        if instance_count >= 3:  # Limit to 3 accounts per user
            await interaction.response.send_message(
                "You have reached the maximum limit of 3 bot instances. Please stop one first with `/stop`",
                ephemeral=True)
            return

        # Generate unique instance ID
        instance_id = f"{user_id}_{instance_count + 1}"

        try:
            # Try to defer the response, with a timeout handling
            try:
                await interaction.response.defer(ephemeral=True)
                interaction_valid = True
            except discord.errors.NotFound:
                logger.warning(f"Interaction expired for user {user_id} before deferring")
                return
            except Exception as e:
                logger.error(f"Error deferring interaction: {str(e)}")
                return

            from lokbot.client import LokBotApi
            email = os.getenv('LOK_EMAIL')
            password = os.getenv('LOK_PASSWORD')

            if not email or not password:
                await interaction.followup.send("Please set LOK_EMAIL and LOK_PASSWORD in Secrets", ephemeral=True)
                return

            # Initialize API and authenticate with timeout handling
            try:
                # Add a timeout to API calls
                api = LokBotApi(None, {}, skip_jwt=True)  # No token needed for initial auth
                logger.info(f"User {user_id}: Attempting authentication...")
                auth_result = api.auth_login(email, password)

                if not auth_result.get('result'):
                    await interaction.followup.send("Login failed. Check your credentials.", ephemeral=True)
                    logger.error(f"\n=== Authentication Failed for user {user_id} ===")
                    if 'err' in auth_result:
                        logger.error(f"Error: {auth_result['err']}")
                    return

                token = auth_result.get('token')
                if not token:
                    await interaction.followup.send("No token received from authentication", ephemeral=True)
                    return

                logger.info(f"\n=== Authentication Successful for user {user_id} ===")
                logger.info(f"Token received (length: {len(token) if token else 0})")
            except Exception as e:
                logger.error(f"Authentication error for user {user_id}: {str(e)}")
                await interaction.followup.send(f"Authentication error: {str(e)}", ephemeral=True)
                return

            # We've already deferred above, so we don't need to do it again
            # Just set the interaction_valid flag
            interaction_valid = True

        # Start the bot in a subprocess
            try:
                # Always use main config as the source
                source_config_path = "config.json"  # Default config
                logger.info(f"User {user_id}: Using main config")

                # Create a config for this user or use existing one
                config_path = f"data/config_{user_id}.json"

                # Check if user already has a configuration
                if os.path.exists(config_path):
                    logger.info(f"User {user_id}: Using existing user config")
                    with open(config_path, "r") as f:
                        config_data = json.load(f)
                else:
                    logger.info(f"User {user_id}: Creating new config from main template")
                    with open(source_config_path, "r") as f:
                        config_data = json.load(f)

                # Add captcha solver config if not present
                if "captcha_solver_config" not in config_data:
                    config_data["captcha_solver_config"] = {"ttshitu": {"username": "", "password": ""}}

                # Store Discord user ID in config for notifications
                if "discord" not in config_data:
                    config_data["discord"] = {}
                config_data["discord"]["user_id"] = user_id

                # Ensure rally configurations exist
                if "rally" not in config_data:
                    config_data["rally"] = {}

                # Ensure join and start configurations exist with default values
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

                # Migration: Move legacy rally_join to rally.join if it exists
                if "rally_join" in config_data:
                    config_data["rally"]["join"] = config_data["rally_join"]
                    del config_data["rally_join"]
                    logger.info(f"User {user_id}: Migrated rally_join to rally.join")

                # Migration: Move legacy rally_start to rally.start if it exists
                if "rally_start" in config_data:
                    config_data["rally"]["start"] = config_data["rally_start"]
                    del config_data["rally_start"]
                    logger.info(f"User {user_id}: Migrated rally_start to rally.start")

                with open(config_path, "w") as f:
                    json.dump(config_data, f)

                # Log the token length for debugging (without revealing the actual token)
                logger.info(f"User {user_id}: Starting bot with token length: {len(token)}")

                # Validate token format more thoroughly
                if not token.strip() or len(token) < 50:  # Most JWT tokens are longer
                    if interaction_valid:
                        await interaction.followup.send("Token appears to be invalid (too short). Please check your token and try again.", ephemeral=True)
                    return

                logger.info(f"User {user_id}: Starting subprocess...")
                # Set environment variables for the subprocess to prevent conflicts
                env = os.environ.copy()
                env["LOKBOT_USER_ID"] = user_id

                process = subprocess.Popen(["python", "-m", "lokbot", token],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              text=True,
                              env=env)

                instance_name = interaction.options.get("instance_name") #Added instance_name
                instance_name = instance_name or f"Instance {instance_count + 1}"
                bot_processes[instance_id] = {
                    "process": process,
                    "token": token,
                    "config_path": config_path,
                    "start_time": discord.utils.utcnow(),
                    "user_id": user_id,
                    "name": instance_name
                }

                # Send confirmation if interaction is still valid
                if interaction_valid:
                    await interaction.followup.send(f"LokBot started successfully! Check your DMs for status updates.",
                                                   ephemeral=True)

                # Start log monitoring
                asyncio.create_task(monitor_logs(interaction.user, process))

            except Exception as e:
                logger.error(f"Error starting bot for user {user_id}: {str(e)}")
                if interaction_valid:
                    await interaction.followup.send(f"Error starting bot: {str(e)}",
                                                   ephemeral=True)

        except Exception as e:
            logger.error(f"Error in command processing for user {user_id}: {str(e)}")
            try:
                if interaction_valid:
                    await interaction.followup.send(f"Error: {str(e)}",
                                                  ephemeral=True)
            except:
                pass

    # Run the command processing asynchronously
    asyncio.create_task(process_command())


@tree.command(name="stop", description="Stop your running LokBot")
async def stop_bot(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    user_processes = [proc_id for proc_id in bot_processes if proc_id.startswith(user_id)]

    if not user_processes:
        await interaction.response.send_message(
            "You don't have a bot running!", ephemeral=True)
        return

    try:
        # Create selection view
        view = discord.ui.View(timeout=300)

        # Add select menu for instances
        select = discord.ui.Select(
            placeholder="Select instance to stop",
            min_values=1,
            max_values=len(user_processes)
        )

        # Add stop all button
        stop_all = discord.ui.Button(
            label="Stop All Instances",
            style=discord.ButtonStyle.danger,
            custom_id="stop_all"
        )

        # Add options for each running instance
        for proc_id in user_processes:
            process = bot_processes[proc_id]["process"]
            if process.poll() is None:  # Only add running processes
                instance_name = bot_processes[proc_id].get('name', proc_id)
                select.add_option(label=instance_name, value=proc_id)

        async def select_callback(select_interaction):
            selected_procs = select_interaction.data["values"]
            stopped_count = 0

            for proc_id in selected_procs:
                if proc_id in bot_processes:
                    process = bot_processes[proc_id]["process"]
                    logger.info(f"Attempting to stop process ID: {proc_id}, type: {type(process)}")

                    if isinstance(process, threading.Thread):
                        logger.info(f"Process is a Thread with name: {process.name}")
                        if process.is_alive():
                            logger.info("Thread alive, attempting to terminate")
                            # Try to get farmer instance
                            try:
                                farmer = process._target.__self__
                                logger.info(f"Got farmer instance: {farmer}")
                                if hasattr(farmer, 'terminate'):
                                    logger.info("Setting terminate flag on farmer")
                                    farmer.terminate = True
                            except Exception as e:
                                logger.error(f"Error accessing farmer: {str(e)}")

                            process.join(timeout=5)
                            logger.info(f"After join, thread is alive: {process.is_alive()}")
                    else:
                        logger.info("Process is a subprocess")
                        if process.poll() is None:  # Process is still running
                            logger.info("Subprocess still running, attempting to terminate")
                            process.terminate()
                            try:
                                process.wait(timeout=5)  # Wait for process to terminate
                                logger.info("Process terminated successfully")
                            except subprocess.TimeoutExpired:
                                logger.warning("Process termination timed out, forcing kill")
                                process.kill()  # Force kill if needed
                                process.wait()  # Make sure process is gone

                    if process.poll() is None:
                        logger.error(f"Failed to stop process {proc_id}")
                    else:
                        stopped_count += 1
                        del bot_processes[proc_id]

            await select_interaction.response.send_message(
                f"Stopped {stopped_count} selected instance(s) successfully",
                ephemeral=True
            )

        async def stop_all_callback(button_interaction):
            stopped_count = 0
            for proc_id in user_processes:
                if proc_id in bot_processes:
                    process = bot_processes[proc_id]["process"]
                    logger.info(f"Attempting to stop process ID: {proc_id}, type: {type(process)}")

                    if isinstance(process, threading.Thread):
                        logger.info(f"Process is a Thread with name: {process.name}")
                        if process.is_alive():
                            logger.info("Thread alive, attempting to terminate")
                            # Try to get farmer instance
                            try:
                                farmer = process._target.__self__
                                logger.info(f"Got farmer instance: {farmer}")
                                if hasattr(farmer, 'terminate'):
                                    logger.info("Setting terminate flag on farmer")
                                    farmer.terminate = True
                            except Exception as e:
                                logger.error(f"Error accessing farmer: {str(e)}")

                            process.join(timeout=5)
                            logger.info(f"After join, thread is alive: {process.is_alive()}")
                    else:
                        logger.info("Process is a subprocess")
                        if process.poll() is None:  # Process is still running
                            logger.info("Subprocess still running, attempting to terminate")
                            process.terminate()
                            try:
                                process.wait(timeout=5)  # Wait for process to terminate
                                logger.info("Process terminated successfully")
                            except subprocess.TimeoutExpired:
                                logger.warning("Process termination timed out, forcing kill")
                                process.kill()  # Force kill if needed
                                process.wait()  # Make sure process is gone

                    if process.poll() is None:
                        logger.error(f"Failed to stop process {proc_id}")
                    else:
                        stopped_count += 1
                        del bot_processes[proc_id]

            await button_interaction.response.send_message(
                f"Stopped all {stopped_count} instance(s) successfully",
                ephemeral=True
            )

        select.callback = select_callback
        stop_all.callback = stop_all_callback

        view.add_item(select)
        view.add_item(stop_all)

        await interaction.response.send_message(
            "Select instances to stop:",
            view=view,
            ephemeral=True
        )

    except Exception as e:
        logger.error(f"Error stopping bot: {str(e)}")
        if interaction_valid:
            await interaction.followup.send(f"Error stopping bot: {str(e)}",
                                            ephemeral=True)


@tree.command(name="status", description="Check if your LokBot is running")
async def status(interaction: discord.Interaction):
    user_id = str(interaction.user.id)

    try:
        # Use defer but handle if interaction expired
        try:
            await interaction.response.defer(ephemeral=True)
            interaction_valid = True
        except discord.errors.NotFound:
            # Interaction already timed out
            interaction_valid = False
            return

        # Count active processes
        active_processes = 0
        for proc_id in list(bot_processes.keys()):
            process = bot_processes[proc_id]["process"]
            if process.poll() is None:  # Process is still running
                active_processes += 1
            else:
                # Clean up ended processes
                del bot_processes[proc_id]

        # Get user's processes
        user_processes = [proc_id for proc_id in bot_processes if proc_id.startswith(user_id)]

        if user_processes:
            active_user_processes = []
            for proc_id in user_processes:
                process = bot_processes[proc_id]["process"]
                if process.poll() is None:  # Process is still running
                    active_user_processes.append(proc_id)
                else:
                    del bot_processes[proc_id]

            if active_user_processes:
                instances = "\n".join([f"• {bot_processes[proc_id]['name']}" for proc_id in active_user_processes])
                await interaction.followup.send(
                    f"Your active LokBot instances:\n{instances}\n\nTotal active bots: {active_processes}",
                    ephemeral=True)
            else:
                await interaction.followup.send(
                    f"All your LokBot processes have ended. There are {active_processes} active bot(s) in total.",
                    ephemeral=True)
        else:
            await interaction.followup.send(
                f"You don't have any LokBot running. There are {active_processes} active bot(s) in total.",
                ephemeral=True)
    except Exception as e:
        logger.error(f"Error checking status: {str(e)}")
        if interaction_valid:
            await interaction.followup.send(f"Error checking status: {str(e)}",
                                            ephemeral=True)


async def monitor_logs(user, process):
    """Monitor bot status and display only essential status updates"""
    user_id = str(user.id)
    try:
        # Add error handling for sending DMs
        try:
            await user.send("✅ Your LokBot is starting up...")
        except discord.errors.Forbidden:
            logger.warning(f"Cannot send DM to user {user_id} - DMs might be disabled")
            return
        except Exception as e:
            logger.error(f"Error sending initial message to user {user_id}: {str(e)}")
            return

        auth_error_detected = False
        startup_complete = False
        output_buffer = []
        critical_error_count = 0

        # Set subprocess pipes to non-blocking mode
        import fcntl
        import os

        # Set stdout to non-blocking
        stdout_fd = process.stdout.fileno()
        fl = fcntl.fcntl(stdout_fd, fcntl.F_GETFL)
        fcntl.fcntl(stdout_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        # Set stderr to non-blocking
        stderr_fd = process.stderr.fileno()
        fl = fcntl.fcntl(stderr_fd, fcntl.F_GETFL)
        fcntl.fcntl(stderr_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        # Add timeout for startup to prevent hanging
        start_time = discord.utils.utcnow()
        timeout = 300  # 5 minutes timeout

        while True:
            # Check for timeout during startup
            if not startup_complete:
                elapsed = (discord.utils.utcnow() - start_time).total_seconds()
                if elapsed > timeout:
                    logger.warning(f"Startup timeout for user {user_id} after {elapsed} seconds")
                    try:
                        await user.send("❌ LokBot startup timed out. The process is still running but not responding as expected.")
                    except:
                        pass
                    break

            # Check if process has ended
            if process.poll() is not None:
                # Process ended - check if we have an error message
                if not startup_complete and output_buffer:
                    error_message = "❌ LokBot failed to start properly. Possible issues:\n"
                    error_message += "- Invalid or expired token\n"
                    error_message += "- API connection problems\n"
                    error_message += "- Server authentication issues\n\n"
                    error_message += "Check the logs for details and try again with a new token."
                    try:
                        await user.send(error_message)
                    except:
                        logger.error(f"Failed to send error message to user {user_id}")
                # Notify when the process has ended
                try:
                    await user.send("❌ Your LokBot has stopped running.")
                except:
                    pass
                break

            # Try to read output without blocking
            try:
                output = process.stdout.readline()
                if output:
                    stripped_output = output.strip()
                    logger.info(f"User {user_id} LokBot Output: {stripped_output}")

                    # Store recent outputs for error analysis
                    output_buffer.append(stripped_output)
                    if len(output_buffer) > 10:  # Keep only the last 10 messages
                        output_buffer.pop(0)

                    # Check for successful startup
                    if "kingdom/enter" in stripped_output and "result\": true" in stripped_output:
                        if not startup_complete:
                            startup_complete = True
                            try:
                                await user.send("✅ LokBot has successfully connected to the game server!")
                            except:
                                logger.error(f"Failed to send success message to user {user_id}")
            except (BlockingIOError, IOError):
                # No data available right now, continue
                pass
            except Exception as e:
                logger.error(f"Error processing stdout for user {user_id}: {str(e)}")

            # Try to read errors without blocking
            try:
                error = process.stderr.readline()
                if error:
                    stripped_error = error.strip()
                    logger.error(f"User {user_id} LokBot Error: {stripped_error}")

                    # Detect auth errors
                    if "NoAuthException" in stripped_error or "auth/connect" in stripped_error:
                        auth_error_detected = True
                        # Send auth error message
                        try:
                            await user.send("❌ Authentication failed! Your token appears to be invalid or expired. Please get a new token and try again.")
                        except:
                            pass
                        return

                    # Only send critical errors to Discord (limit to prevent spam)
                    if "CRITICAL" in stripped_error or "ERROR" in stripped_error or "FATAL" in stripped_error:
                        critical_error_count += 1
                        if critical_error_count <= 3:  # Limit to 3 critical errors
                            try:
                                # Extract the actual error message for better clarity
                                error_message = "❌ Critical error detected: "
                                if "CRITICAL" in stripped_error:
                                    error_message += stripped_error.split("CRITICAL")[-1].strip()
                                elif "ERROR" in stripped_error:
                                    error_message += stripped_error.split("ERROR")[-1].strip()
                                elif "FATAL" in stripped_error:
                                    error_message += stripped_error.split("FATAL")[-1].strip()
                                else:
                                    error_message += "Check logs for details."

                                await user.send(error_message[:1900] + "..." if len(error_message) > 1900 else error_message)
                            except discord.errors.HTTPException as e:
                                logger.error(f"Failed to send Discord error message to user {user_id}: {str(e)}")
            except (BlockingIOError, IOError):
                # No data available right now, continue
                pass
            except Exception as e:
                logger.error(f"Error processing stderr for user {user_id}: {str(e)}")

            # Wait a bit before checking again
            await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"Error in status monitoring for user {user_id}: {str(e)}")
        try:
            await user.send("❌ Error monitoring LokBot status. Check server logs for details.")
        except:
            logger.error(f"Failed to send error message to user {user_id}")


@tree.command(name="login_with_token", description="Start the bot using a token")
@app_commands.describe(
    token="Your bot token",
    account_name="Optional name for this bot account"
)
async def login_with_token(interaction: discord.Interaction, token: str, account_name: str = None):
    """Start bot with token and optional config file"""
    if not is_admin(interaction):
        await interaction.response.send_message("Only administrators can use this command!", ephemeral=True)
        return

    # Get list of available config files
    config_files = [f for f in os.listdir('.') if f.endswith('.json')]

    # Create config selection view
    view = discord.ui.View(timeout=300)
    config_select = discord.ui.Select(
        placeholder="Select a configuration file",
        options=[discord.SelectOption(label=f"{file}", value=file) for file in config_files]
    )

    async def config_select_callback(select_interaction):
        selected_file = select_interaction.data["values"][0]
        ConfigHelper.set_current_config(selected_file)
        await start_bot_with_token(select_interaction, token, selected_file, account_name)

    config_select.callback = config_select_callback
    view.add_item(config_select)

    await interaction.response.send_message(
        "Please select a configuration file to use:",
        view=view,
        ephemeral=True
    )

async def start_bot_with_token(interaction, token, config_file=None, account_name=None):
    """Start bot with token and optional config file

    Args:
        token: Authentication token
        config_file: Optional config file to use (e.g. config_1.json)
        account_name: Optional name for this bot account
    """
    if not is_admin(interaction):
        await interaction.response.send_message("Only administrators can use this command!", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    instance_count = sum(1 for proc_id in bot_processes if proc_id.startswith(user_id) and bot_processes[proc_id]["process"].poll() is None)

    if instance_count >= 3:  # Limit to 3 accounts per user
        await interaction.response.send_message(
            "You have reached the maximum limit of 3 bot instances. Please stop one first with `/stop`",
            ephemeral=True)
        return

    # Generate unique instance ID
    instance_id = f"{user_id}_{instance_count + 1}"

    try:
        await interaction.response.defer(ephemeral=True)
        interaction_valid = True

        # Validate token format
        if not token.strip() or len(token) < 50:  # Most JWT tokens are longer
            if interaction_valid:
                await interaction.followup.send("Token appears to be invalid (too short). Please check your token and try again.", ephemeral=True)
            return

        # Always use the main config as a template
        source_config_path = "config.json"
        logger.info(f"User {user_id}: Using main config as template")

        # Create a config for this user or use existing one
        config_path = f"data/config_{user_id}.json"

        # Check if user already has a configuration
        if os.path.exists(config_path):
            logger.info(f"User {user_id}: Using existing user config")
            with open(config_path, "r") as f:
                config_data = json.load(f)
        else:
            logger.info(f"User {user_id}: Creating new config from main template")
            with open(source_config_path, "r") as f:
                config_data = json.load(f)

        # Add captcha solver config if not present
        if "captcha_solver_config" not in config_data:
            config_data["captcha_solver_config"] = {"ttshitu": {"username": "", "password": ""}}

        # Store Discord user ID in config for notifications
        if "discord" not in config_data:
            config_data["discord"] = {}
        config_data["discord"]["user_id"] = user_id

        # Ensure rally configurations exist in the unified structure
        if "rally" not in config_data:
            config_data["rally"] = {}

        # Ensure join and start configurations exist with default values
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

        # Migration: Move legacy rally_join to rally.join if it exists
        if "rally_join" in config_data:
            config_data["rally"]["join"] = config_data["rally_join"]
            del config_data["rally_join"]
            logger.info(f"User {user_id}: Migrated rally_join to rally.join")

        # Migration: Move legacy rally_start to rally.start if it exists
        if "rally_start" in config_data:
            config_data["rally"]["start"] = config_data["rally_start"]
            del config_data["rally_start"]
            logger.info(f"User {user_id}: Migrated rally_start to rally.start")

        with open(config_path, "w") as f:
            json.dump(config_data, f)

        # Log the token length for debugging (without revealing the actual token)
        logger.info(f"Starting bot with token length: {len(token)}")

        # Set environment variables for the subprocess to prevent conflicts
        env = os.environ.copy()
        env["LOKBOT_USER_ID"] = user_id
        # Always ensure config file is set
        config_file = config_file or "config.json"
        env["LOKBOT_CONFIG"] = config_file
        logger.info(f"Starting instance with config file: {config_file}")
        ConfigHelper.set_current_config(config_file)
        os.environ["LOKBOT_CONFIG"] = config_file  # Set in current process too

        process = subprocess.Popen(["python", "-m", "lokbot", token],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  text=True,
                                  env=env)

        account_name = account_name or f"Instance {instance_count + 1}" #Renamed instance_name to account_name
        bot_processes[instance_id] = {
            "process": process,
            "token": token,
            "config_path": config_path,
            "start_time": discord.utils.utcnow(),
            "user_id": user_id,
            "name": account_name
        }

        # Send confirmation if interaction is still valid
        if interaction_valid:
            await interaction.followup.send(f"LokBot started successfully! Check your DMs for status updates.",
                                            ephemeral=True)

        # Start log monitoring
        asyncio.create_task(monitor_logs(interaction.user, process))

    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        if interaction_valid:
            await interaction.followup.send(f"Error starting bot: {str(e)}",
                                            ephemeral=True)


@tree.command(name="login_with_email", description="Start the bot using email and password")
@app_commands.describe(
    email="Your email address", 
    password="Your password",
    account_name="Optional name for this bot account"
)
async def login_with_email(discord.Interaction, email: str, password: str, account_name: str = None):
    """Start bot with email/password and optional config file"""
    if not is_admin(interaction):
        await interaction.response.send_message("Only administrators can use this command!", ephemeral=True)
        return

    # Get list of available config files
    config_files = [f for f in os.listdir('.') if f.endswith('.json')]

    # Create config selection view
    view = discord.ui.View(timeout=300)
    config_select = discord.ui.Select(
        placeholder="Select a configuration file",
        options=[discord.SelectOption(label=f"{file}", value=file) for file in config_files]
    )

    async def config_select_callback(select_interaction):
        selected_file = select_interaction.data["values"][0]
        ConfigHelper.set_current_config(selected_file)
        await start_bot_with_email(select_interaction, email, password, account_name, selected_file)

    config_select.callback = config_select_callback
    view.add_item(config_select)

    await interaction.response.send_message(
        "Please select a configuration file to use:",
        view=view,
        ephemeral=True
    )

async def start_bot_with_email(interaction, email, password, account_name, config_file=None):
    """Start bot with email/password and optional config file

    Args:
        email: Login email
        password: Login password  
        account_name: Optional name for this instance
        config_file: Optional config file to use (e.g. config_1.json)
    """
    if not is_admin(interaction):
        await interaction.response.send_message("Only administrators can use this command!", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    instance_count = sum(1 for proc_id in bot_processes if proc_id.startswith(user_id) and bot_processes[proc_id]["process"].poll() is None)

    if instance_count >= 3:  # Limit to 3 accounts per user
        await interaction.response.send_message(
            "You have reached the maximum limit of 3 bot instances. Please stop one first with `/stop`",
            ephemeral=True)
        return

    # Generate unique instance ID
    instance_id = f"{user_id}_{instance_count + 1}"

    try:
        await interaction.response.defer(ephemeral=True)
        interaction_valid = True

        #Validate email format
        if not email or '@' not in email:
            if interaction_valid:
                await interaction.followup.send("Please provide a valid email address.", ephemeral=True)
            return

        # Validate password
        if not password or len(password) < 4:
            if interaction_valid:
                await interaction.followup.send("Please provide a valid password (minimum 4 characters).", ephemeral=True)
            return

        # Get token using email and password
        try:
            from lokbot.client import LokBotApi
            api = LokBotApi(None, {}, skip_jwt=True)  # No token needed for initial auth
            logger.info(f"Attempting login with email: {email}")
            auth_result = api.auth_login(email, password)

            if not auth_result.get('result'):
                if interaction_valid:
                    error_msg = auth_result.get('err', 'Unknown error')
                    await interaction.followup.send(f"Login failed: {error_msg}", ephemeral=True)
                return

            token = auth_result.get('token')
            if not token:
                if interaction_valid:
                    await interaction.followup.send("No token received from authentication", ephemeral=True)
                return

            logger.info(f"Successfully obtained token (length: {len(token)})")

            # Always use the main config as a template
            source_config_path = "config.json"
            logger.info(f"User {user_id}: Using main config as template")

            # Create a config for this user or use existing one
            config_path = f"data/config_{user_id}.json"

            # Check if user already has a configuration
            if os.path.exists(config_path):
                logger.info(f"User {user_id}: Using existing user config")
                with open(config_path, "r") as f:
                    config_data = json.load(f)
            else:
                logger.info(f"User {user_id}: Creating new config from main template")
                with open(source_config_path, "r") as f:
                    config_data = json.load(f)

            # Add captcha solver config if not present
            if "captcha_solver_config" not in config_data:
                config_data["captcha_solver_config"] = {"ttshitu": {"username": "", "password": ""}}

            # Store Discord user ID in config for notifications
            if "discord" not in config_data:
                config_data["discord"] = {}
            config_data["discord"]["user_id"] = user_id

            # Ensure rally configurations exist in the unified structure
            if "rally" not in config_data:
                config_data["rally"] = {}

            # Ensure join and start configurations exist with default values
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

            # Migration: Move legacy rally_join to rally.join if it exists
            if "rally_join" in config_data:
                config_data["rally"]["join"] = config_data["rally_join"]
                del config_data["rally_join"]
                logger.info(f"User {user_id}: Migrated rally_jointo rally.join")

            # Migration: Move legacy rally_start to rally.start if it exists
            if "rally_start" in config_data:
                config_data["rally"]["start"] = config_data["rally_start"]
                del config_data["rally_start"]
                logger.info(f"User {user_id}: Migrated rally_start to rally.start")

            with open(config_path, "w") as f:
                json.dump(config_data, f)

            # Get user ID from token and save token to file
            _id = decode_jwt(token).get('_id')
            if _id:
                with open(f"data/{_id}.token", "w") as f:
                    f.write(token)
                logger.info(f"Saved token to data/{_id}.token")

            # Start the bot with the obtained token
            try:
                # Set environment variables for the subprocess to prevent conflicts
                env = os.environ.copy()
                env["LOKBOT_USER_ID"] = user_id
                # Always ensure config file is set
                config_file = config_file or "config.json"
                env["LOKBOT_CONFIG"] = config_file
                logger.info(f"Starting instance with config file: {config_file}")
                ConfigHelper.set_current_config(config_file)
                os.environ["LOKBOT_CONFIG"] = config_file  # Set in current process too

                process = subprocess.Popen(["python", "-m", "lokbot", token],
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE,
                                      text=True,
                                      env=env)

                account_name = account_name or f"Instance {instance_count + 1}" #Renamed instance_name to account_name
                bot_processes[instance_id] = {
                    "process": process,
                    "token": token,
                    "config_path": config_path,
                    "start_time": discord.utils.utcnow(),
                    "user_id": user_id,
                    "name": account_name
                }

                # Send confirmation if interaction is still valid
                if interaction_valid:
                    await interaction.followup.send(f"Successfully logged in and started LokBot! Check your DMs for status updates.",
                                                    ephemeral=True)

                # Start log monitoring
                asyncio.create_task(monitor_logs(interaction.user, process))

            except Exception as e:
                logger.error(f"Error starting bot aftersuccessful authentication: {str(e)}")
                if interaction_valid:
                    await interaction.followup.send(f"Error starting bot: {str(e)}", ephemeral=True)
                return

        except Exception as e:
            logger.error(f"Error authenticating with email/password: {str(e)}")
            if interaction_valid:
                await interaction.followup.send(f"Error authenticating: {str(e)}", ephemeral=True)
            return

    except Exception as e:
        logger.error(f"Error in login_with_email command: {str(e)}")
        if interaction_valid:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)


@tree.command(name="alt", description="Alternate command to stop your running LokBot")
async def alt_stopbot(interaction: discord.Interaction):
    """This is an alternate command that implements the stop functionality"""
    if not is_admin(interaction):
        await interaction.response.send_message("Only administrators can use this command!", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    if user_id not in bot_processes:
        await interaction.response.send_message(
            "You don't have a bot running!", ephemeral=True)
        return

    try:
        # Try to defer, but handle the case if interaction has already expired
        try:
            await interaction.response.defer(ephemeral=True)
            interaction_valid = True
        except discord.errors.NotFound:
            # Interaction already timed out or doesn't exist
            interaction_valid = False

        # Terminate the process
        process = bot_processes[user_id]["process"]
        logger.info(f"Attempting to stop process ID: {user_id}, type: {type(process)}")

        if isinstance(process, threading.Thread):
            logger.info(f"Process is a Thread with name: {process.name}")
            if process.is_alive():
                logger.info("Thread alive, attempting to terminate")
                # Try to get farmer instance
                try:
                    farmer = process._target.__self__
                    logger.info(f"Got farmer instance: {farmer}")
                    if hasattr(farmer, 'terminate'):
                        logger.info("Setting terminate flag on farmer")
                        farmer.terminate = True
                except Exception as e:
                    logger.error(f"Error accessing farmer: {str(e)}")

                process.join(timeout=5)
                logger.info(f"After join, thread is alive: {process.is_alive()}")
        else:
            logger.info("Process is a subprocess")
            if process.poll() is None:  # Process is still running
                logger.info("Subprocess still running, attempting to terminate")
                process.terminate()
                try:
                    process.wait(timeout=5)  # Wait for process to terminate
                    logger.info("Process terminated successfully")
                except subprocess.TimeoutExpired:
                    logger.warning("Process termination timed out, forcing kill")
                    process.kill()  # Force kill if needed
                    process.wait()  # Make sure process is gone

        # Send confirmation only if interaction is still valid
        if interaction_valid:
            await interaction.followup.send("LokBot stopped successfully",
                                            ephemeral=True)

        # Clean up
        del bot_processes[user_id]

    except Exception as e:
        logger.error(f"Error stopping bot: {str(e)}")
        if interaction_valid:
            await interaction.followup.send(f"Error stopping bot: {str(e)}",
                                            ephemeral=True)


# Import user-friendly commands with error handling
try:
    from lokbot.user_friendly_commands import UserFriendlyCommands, ConfigHelper
    # Register user-friendly commands
    user_friendly_commands = UserFriendlyCommands()
except Exception as e:
    logger.error(f"Error importing user-friendly commands: {str(e)}")
    # Fallback to empty class if import fails
    class UserFriendlyCommands(app_commands.Group):
        def __init__(self):
            super().__init__(name="config", description="User-friendly configuration commands")
            self.add_command(self.toggle_rally_config)
            self.add_command(self.toggle_job)
            self.add_command(self.toggle_thread)
            self.add_command(self.toggle_feature)

        async def toggle_rally_config(self, interaction: discord.Interaction, config_section: str):
            """Toggle the enabled state of a rally configuration (join or start)"""
            await toggle_rally_config(interaction, f"rally.{config_section}")

        @app_commands.command(name="toggle_job", description="Toggle a job on or off")
        @app_commands.describe(job_name="The name of the job to toggle")
        @app_commands.choices(job_name=[
            app_commands.Choice(name="Hospital Recover", value="hospital_recover"),
            app_commands.Choice(name="Wall Repair", value="wall_repair"),
            app_commands.Choice(name="Alliance Farmer", value="alliance_farmer"),
            app_commands.Choice(name="Mail Claim", value="mail_claim"),
            app_commands.Choice(name="Caravan Farmer", value="caravan_farmer"),
            app_commands.Choice(name="Use Resource Items", value="use_resource_in_item_list"),
            app_commands.Choice(name="VIP Chest Claim", value="vip_chest_claim"),
            app_commands.Choice(name="Harvester", value="harvester"),
            app_commands.Choice(name="SOCF Thread", value="socf_thread")
        ])
        async def toggle_job(self, interaction: discord.Interaction, job_name: str):
            """Toggle a job on or off"""
            await toggle_rally_config(interaction, f"jobs.{job_name}")

        @app_commands.command(name="toggle_thread", description="Toggle a thread on or off")
        @app_commands.describe(thread_name="The name of the thread to toggle")
        @app_commands.choices(thread_name=[
            app_commands.Choice(name="Free Chest Farmer", value="free_chest_farmer_thread"),
            app_commands.Choice(name="Quest Monitor", value="quest_monitor_thread"),
            app_commands.Choice(name="Building Farmer", value="building_farmer_thread"),
            app_commands.Choice(name="Academy Farmer", value="academy_farmer_thread"),
            app_commands.Choice(name="Train Troop", value="train_troop_thread")
        ])
        async def toggle_thread(self, interaction: discord.Interaction, thread_name: str):
            """Toggle a thread on or off"""
            await toggle_rally_config(interaction, f"threads.{thread_name}")

        @app_commands.command(name="toggle_feature", description="Toggle a feature on or off")
        @app_commands.describe(feature_name="The name of the feature to toggle")
        @app_commands.choices(feature_name=[
            app_commands.Choice(name="Object Scanning", value="object_scanning"),
            app_commands.Choice(name="Discord Notifications", value="notify_discord"),
            app_commands.Choice(name="Resource Gathering", value="enable_gathering"),
            app_commands.Choice(name="Monster Attack", value="enable_monster_attack"),
            app_commands.Choice(name="Discord Integration", value="discord")
        ])
        async def toggle_feature(self, interaction: discord.Interaction, feature_name: str):
            """Toggle a feature on or off"""
            await toggle_rally_config(interaction, f"features.{feature_name}")

    # Create a separate function that can be called from multiple commands
    async def toggle_rally_config(interaction, config_section):
        """Helper function to toggle configuration settings"""
        config_file = f"data/config_{str(interaction.user.id)}.json"
        try:
            # Load the configuration
            with open(config_file, "r") as f:
                config = json.load(f)

            # Parse the config section path (e.g., rally.join, features.discord, etc.)
            parts = config_section.split('.')

            # Handle different toggle types based on the path
            if len(parts) == 2:
                section, feature = parts

                # Handle rally toggles in the new structure
                if section == "rally":
                    rally_type = feature  # join or start

                    # Ensure rally section exists
                    if "rally" not in config:
                        config["rally"] = {}

                    # Ensure the specific rally section exists
                    if rally_type not in config["rally"]:
                        config["rally"][rally_type] = {"enabled": False, "numMarch": 6, "targets": [], "level_based_troops": False}

                    # Get current state
                    current_state = False
                    # Check toggles first for consistency
                    if "toggles" in config and "features" in config["toggles"] and f"rally_{rally_type}" in config["toggles"]["features"]:
                        current_state = config["toggles"]["features"][f"rally_{rally_type}"]
                    else:
                        current_state = config["rally"][rally_type].get("enabled", False)

                    # Sync both locations to ensure consistency
                    config["rally"][rally_type]["enabled"] = current_state

                    # Show confirmation dialog
                    confirm_view = discord.ui.View(timeout=60)

                    yes_button = discord.ui.Button(
                        label=f"Yes, {'disable' if current_state else 'enable'} it",
                        style=discord.ButtonStyle.danger if current_state else discord.ButtonStyle.success,
                        custom_id="confirm_toggle"
                    )
                    confirm_view.add_item(yes_button)

                    no_button = discord.ui.Button(
                        label="No, keep current setting",
                        style=discord.ButtonStyle.secondary,
                        custom_id="cancel_toggle"
                    )
                    confirm_view.add_item(no_button)

                    # Define callback for confirmation
                    async def confirm_callback(button_interaction):
                        if button_interaction.data["custom_id"] == "confirm_toggle":
                            # Toggle the enabled state
                            config["rally"][rally_type]["enabled"] = not current_state
                            new_state = config["rally"][rally_type]["enabled"]

                            # Also update the toggles structure for compatibility
                            if "toggles" not in config:
                                config["toggles"] = {"features": {}}
                            if "features" not in config["toggles"]:
                                config["toggles"]["features"] = {}

                            config["toggles"]["features"][f"rally_{rally_type}"] = new_state

                            logger.info(f"Updating rally {rally_type} enabled state to: {new_state}")

                            # Save the updated configuration
                            with open(config_file, "w") as f:
                                json.dump(config, f, indent=2)

                            await button_interaction.response.edit_message(
                                content=f"Rally {rally_type.capitalize()} {'enabled' if new_state else 'disabled'}!",
                                view=None
                            )
                        else:
                            # User cancelled
                            await button_interaction.response.edit_message(
                                content=f"No changes made. Rally {rally_type.capitalize()} remains {'enabled' if current_state else 'disabled'}.",
                                view=None
                            )

                    # Register callbacks
                    for button in confirm_view.children:
                        button.callback = confirm_callback

                    # Send confirmation message
                    await interaction.response.send_message(
                        f"Rally {rally_type.capitalize()} is currently {'enabled' if current_state else 'disabled'}. Do you want to {'disable' if current_state else 'enable'} it?",
                        view=confirm_view,
                        ephemeral=True
                    )

                # Handle job toggles
                elif section == "jobs":
                    # Ensure jobs section exists in main and toggles
                    if "main" not in config:
                        config["main"] = {"jobs": []}

                    # Find the job in the main.jobs array
                    job_found = False
                    for job in config.get("main", {}).get("jobs", []):
                        if job.get("name") == feature:
                            job["enabled"] = not job.get("enabled", False)
                            new_state = job["enabled"]
                            job_found = True
                            break

                    # If job not found, add it
                    if not job_found:
                        # Create a default job structure
                        new_job = {
                            "name": feature,
                            "enabled": True,
                            "interval": {"start": 120, "end": 200}
                        }
                        config["main"].setdefault("jobs", []).append(new_job)
                        new_state = True

                    # Update toggles structure
                    if "toggles" not in config:
                        config["toggles"] = {"jobs": {}}
                    if "jobs" not in config["toggles"]:
                        config["toggles"]["jobs"] = {}

                    config["toggles"]["jobs"][feature] = new_state

                    logger.info(f"Updating job {feature} enabled state to: {new_state}")

                    # Save the updated configuration
                    with open(config_file, "w") as f:
                        json.dump(config, f, indent=2)

                    await interaction.response.send_message(
                        f"Job {feature} {'enabled' if new_state else 'disabled'}!",
                        ephemeral=True
                    )

                # Handle thread toggles
                elif section == "threads":
                    # Ensure threads section exists
                    if "main" not in config:
                        config["main"] = {"threads": []}

                    # Find the thread in the main.threads array
                    thread_found = False
                    for thread in config.get("main", {}).get("threads", []):
                        if thread.get("name") == feature:
                            thread["enabled"] = not thread.get("enabled", False)
                            new_state = thread["enabled"]
                            thread_found = True
                            break

                    # If thread not found, add it
                    if not thread_found:
                        # Create a default thread structure
                        new_thread = {
                            "name": feature,
                            "enabled": True,
                            "kwargs": {}
                        }
                        config["main"].setdefault("threads", []).append(new_thread)
                        new_state = True

                    # Update toggles structure
                    if "toggles" not in config:
                        config["toggles"] = {"threads": {}}
                    if "threads" not in config["toggles"]:
                        config["toggles"]["threads"] = {}

                    config["toggles"]["threads"][feature] = new_state

                    logger.info(f"Updating thread {feature} enabled state to: {new_state}")

                    # Save the updated configuration
                    with open(config_file, "w") as f:
                        json.dump(config, f, indent=2)

                    await interaction.response.send_message(
                        f"Thread {feature} {'enabled' if new_state else 'disabled'}!",
                        ephemeral=True
                    )

                # Handle other feature toggles (object_scanning, notify_discord, etc.)
                elif section == "features":
                    # Handle specific features
                    if feature == "object_scanning":
                        # Ensure the object_scanning section exists
                        if "main" not in config:
                            config["main"] = {}
                        if "object_scanning" not in config["main"]:
                            config["main"]["object_scanning"] = {"enabled": False}

                        # Toggle feature
                        config["main"]["object_scanning"]["enabled"] = not config["main"]["object_scanning"].get("enabled", False)
                        new_state = config["main"]["object_scanning"]["enabled"]

                        # Update toggles structure
                        if "toggles" not in config:
                            config["toggles"] = {"features": {}}
                        if "features" not in config["toggles"]:
                            config["toggles"]["features"] = {}

                        config["toggles"]["features"]["object_scanning"] = new_state

                    elif feature == "notify_discord":
                        # Ensure the object_scanning section exists
                        if "main" not in config:
                            config["main"] = {}
                        if "object_scanning" not in config["main"]:
                            config["main"]["object_scanning"] = {"notify_discord": False}

                        # Toggle feature
                        config["main"]["object_scanning"]["notify_discord"] = not config["main"]["object_scanning"].get("notify_discord", False)
                        new_state = config["main"]["object_scanning"]["notify_discord"]

                        # Update toggles structure
                        if "toggles" not in config:
                            config["toggles"] = {"features": {}}
                        if "features" not in config["toggles"]:
                            config["toggles"]["features"] = {}

                        config["toggles"]["features"]["notify_discord"] = new_state

                    elif feature == "enable_gathering":
                        # Ensure the object_scanning section exists
                        if "main" not in config:
                            config["main"] = {}
                        if "object_scanning" not in config["main"]:
                            config["main"]["object_scanning"] = {"enable_gathering": False}

                        # Toggle feature
                        config["main"]["object_scanning"]["enable_gathering"] = not config["main"]["object_scanning"].get("enable_gathering", False)
                        new_state = config["main"]["object_scanning"]["enable_gathering"]

                        # Update toggles structure
                        if "toggles" not in config:
                            config["toggles"] = {"features": {}}
                        if "features" not in config["toggles"]:
                            config["toggles"]["features"] = {}

                        config["toggles"]["features"]["enable_gathering"] = new_state

                    elif feature == "enable_monster_attack":
                        # Ensure the object_scanning section exists
                        if "main" not in config:
                            config["main"] = {}
                        if "object_scanning" not in config["main"]:
                            config["main"]["object_scanning"] = {"enable_monster_attack": False}

                        # Toggle feature
                        config["main"]["object_scanning"]["enable_monster_attack"] = not config["main"]["object_scanning"].get("enable_monster_attack", False)
                        new_state = config["main"]["object_scanning"]["enable_monster_attack"]

                        # Update toggles structure
                        if "toggles" not in config:
                            config["toggles"] = {"features": {}}
                        if "features" not in config["toggles"]:
                            config["toggles"]["features"] = {}

                        config["toggles"]["features"]["enable_monster_attack"] = new_state

                    elif feature == "discord":
                        # Ensure the discord section exists
                        if "discord" not in config:
                            config["discord"] = {"enabled": False}

                        # Toggle feature
                        config["discord"]["enabled"] = not config["discord"].get("enabled", False)
                        new_state = config["discord"]["enabled"]

                        # Update toggles structure
                        if "toggles" not in config:
                            config["toggles"] = {"features": {}}
                        if "features" not in config["toggles"]:
                            config["toggles"]["features"] = {}

                        config["toggles"]["features"]["discord"] = new_state

                    else:
                        await interaction.response.send_message(
                            f"Unknown feature: {feature}",
                            ephemeral=True
                        )
                        return

                    logger.info(f"Updating feature {feature} enabled state to: {new_state}")

                    # Save the updated configuration
                    with open(config_file, "w") as f:
                        json.dump(config, f, indent=2)

                    await interaction.response.send_message(
                        f"Feature {feature} {'enabled' if new_state else 'disabled'}!",
                        ephemeral=True
                    )

                else:
                    # Unknown section
                    logger.warning(f"Unknown configuration section: {section}")
                    await interaction.response.send_message(
                        f"Error: Unknown configuration section: {section}",
                        ephemeral=True
                    )
            else:
                # Invalid config section format
                logger.warning(f"Unexpected config section format: {config_section}")
                await interaction.response.send_message(
                    f"Error: Unexpected configuration format. Please use the format section.feature (e.g., rally.join, features.discord)",
                    ephemeral=True
                )
        except Exception as e:
            logger.error(f"Error toggling config: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def toggle_rally_config(interaction, config_section):
        """Toggle rally configuration settings (rally.join, rally.start, features, etc.)

        This is a helper function for the user_friendly_commands module
        """
        try:
            if not is_admin(interaction):
                await interaction.response.send_message("Only administrators can use this command!", ephemeral=True)
                return

            # Get the current config
            config = ConfigHelper.load_config()

            # Parse the config section path (e.g., 'rally.join', 'rally.start', etc.)
            sections = config_section.split('.')

            if len(sections) != 2:
                await interaction.response.send_message(f"Invalid config section format: {config_section}", ephemeral=True)
                return

            section, key = sections

            # Handle different section types
            if section == "rally":
                # Rally join/start toggles
                if key not in ["join", "start"]:
                    await interaction.response.send_message(f"Invalid rally config key: {key}", ephemeral=True)
                    return

                # Get current state - first from toggles section for consistency
                current_state = False
                if "toggles" in config and "features" in config["toggles"] and f"rally_{key}" in config["toggles"]["features"]:
                    current_state = config["toggles"]["features"][f"rally_{key}"]
                elif "rally" in config and key in config["rally"]:
                    current_state = config["rally"][key].get("enabled", False)

                # Create confirmation view
                view = discord.ui.View(timeout=60)

                # Add toggle buttons with labels that show the current state
                toggle_button = discord.ui.Button(
                    label=f"{'Disable' if current_state else 'Enable'} Rally {key.capitalize()}",
                    style=discord.ButtonStyle.danger if current_state else discord.ButtonStyle.success,
                    custom_id="confirm_toggle"
                )
                view.add_item(toggle_button)

                cancel_button = discord.ui.Button(
                    label="Cancel",
                    style=discord.ButtonStyle.secondary,
                    custom_id="cancel"
                )
                view.add_item(cancel_button)

                # Define callback
                async def button_callback(button_interaction):
                    if button_interaction.data["custom_id"] == "confirm_toggle":
                        # Toggle the state
                        new_state = not current_state

                        # Update both in the rally section and toggles section
                        if "rally" not in config:
                            config["rally"] = {}
                        if key not in config["rally"]:
                            config["rally"][key] = {"enabled": new_state, "numMarch": 8 if key == "join" else 6, "targets": [], "level_based_troops": True}
                        else:
                            config["rally"][key]["enabled"] = new_state

                        # Update toggles section
                        if "toggles" not in config:
                            config["toggles"] = {"features": {}}
                        if "features" not in config["toggles"]:
                            config["toggles"]["features"] = {}
                        config["toggles"]["features"][f"rally_{key}"] = new_state

                        # Save config
                        ConfigHelper.save_config(config)

                        # Confirm to user
                        await button_interaction.response.edit_message(
                            content=f"Rally {key.capitalize()} has been {'enabled' if new_state else 'disabled'}",
                            view=None
                        )
                    else:
                        # User cancelled
                        await button_interaction.response.edit_message(
                            content=f"No changes made. Rally {key.capitalize()} remains {'enabled' if current_state else 'disabled'}.",
                            view=None
                        )

                # Register the callback
                for button in view.children:
                    button.callback = button_callback

                # Show the current state and confirm
                await interaction.response.send_message(
                    f"Rally {key.capitalize()} is currently {'enabled' if current_state else 'disabled'}. Do you want to change it?",
                    view=view,
                    ephemeral=True
                )

            elif section == "features":
                # Handle feature toggles
                valid_features = ["object_scanning", "notify_discord", "enable_gathering", "enable_monster_attack", "rally_join", "rally_start", "discord"]

                if key not in valid_features:
                    await interaction.response.send_message(f"Invalid feature: {key}", ephemeral=True)
                    return

                # Get current state from toggles section
                current_state = False
                if "toggles" in config and "features" in config["toggles"] and key in config["toggles"]["features"]:
                    current_state = config["toggles"]["features"][key]

                # Special handling for features in different locations
                if key == "object_scanning" or key == "notify_discord" or key == "enable_gathering" or key == "enable_monster_attack":
                    # These are in main.object_scanning
                    if "main" not in config:
                        config["main"] = {}
                    if "object_scanning" not in config["main"]:
                        config["main"]["object_scanning"] = {}

                    if key == "object_scanning":
                        current_state = config["main"]["object_scanning"].get("enabled", False)
                    else:
                        current_state = config["main"]["object_scanning"].get(key, False)
                elif key == "rally_join":
                    if "rally" in config and "join" in config["rally"]:
                        current_state = config["rally"]["join"].get("enabled", False)
                elif key == "rally_start":
                    if "rally" in config and "start" in config["rally"]:
                        current_state = config["rally"]["start"].get("enabled", False)
                elif key == "discord":
                    if "discord" in config:
                        current_state = config["discord"].get("enabled", False)

                # Create confirmation view
                view = discord.ui.View(timeout=60)

                # Add toggle buttons with labels that show the current state
                toggle_button = discord.ui.Button(
                    label=f"{'Disable' if current_state else 'Enable'} {key.replace('_', ' ').title()}",
                    style=discord.ButtonStyle.danger if current_state else discord.ButtonStyle.success,
                    custom_id="confirm_toggle"
                )
                view.add_item(toggle_button)

                cancel_button = discord.ui.Button(
                    label="Cancel",
                    style=discord.ButtonStyle.secondary,
                    custom_id="cancel"
                )
                view.add_item(cancel_button)

                # Define callback
                async def button_callback(button_interaction):
                    if button_interaction.data["custom_id"] == "confirm_toggle":
                        # Toggle the state
                        new_state = not current_state

                        # Update in toggles section
                        if "toggles" not in config:
                            config["toggles"] = {"features": {}}
                        if "features" not in config["toggles"]:
                            config["toggles"]["features"] = {}
                        config["toggles"]["features"][key] = new_state

                        # Update in the specific location
                        if key == "object_scanning" or key == "notify_discord" or key == "enable_gathering" or key == "enable_monster_attack":
                            if "main" not in config:
                                config["main"] = {}
                            if "object_scanning" not in config["main"]:
                                config["main"]["object_scanning"] = {}

                            if key == "object_scanning":
                                config["main"]["object_scanning"]["enabled"] = new_state
                            else:
                                config["main"]["object_scanning"][key] = new_state
                        elif key == "rally_join":
                            if "rally" not in config:
                                config["rally"] = {}
                            if "join" not in config["rally"]:
                                config["rally"]["join"] = {"enabled": new_state, "numMarch": 8, "targets": [], "level_based_troops": True}
                            else:
                                config["rally"]["join"]["enabled"] = new_state
                        elif key == "rally_start":
                            if "rally" not in config:
                                config["rally"] = {}
                            if "start" not in config["rally"]:
                                config["rally"]["start"] = {"enabled": new_state, "numMarch": 6, "targets": [], "level_based_troops": True}
                            else:
                                config["rally"]["start"]["enabled"] = new_state
                        elif key == "discord":
                            if "discord" not in config:
                                config["discord"] = {"enabled": new_state, "webhook_url": ""}
                            else:
                                config["discord"]["enabled"] = new_state

                        # Save config
                        ConfigHelper.save_config(config)

                        # Confirm to user
                        await button_interaction.response.edit_message(
                            content=f"{key.replace('_', ' ').title()} has been {'enabled' if new_state else 'disabled'}",
                            view=None
                        )
                    else:
                        # User cancelled
                        await button_interaction.response.edit_message(
                            content=f"No changes made. {key.replace('_', ' ').title()} remains {'enabled' if current_state else 'disabled'}.",
                            view=None
                        )

                # Register the callback
                for button in view.children:
                    button.callback = button_callback

                # Show the current state and confirm
                await interaction.response.send_message(
                    f"{key.replace('_', ' ').title()} is currently {'enabled' if current_state else 'disabled'}. Do you want to change it?",
                    view=view,
                    ephemeral=True
                )

            elif section == "jobs" or section == "threads":
                # Handle job/thread toggles
                if "main" not in config:
                    config["main"] = {}
                if section not in config["main"]:
                    config["main"][section] = []

                # Find the job/thread by name
                target_found = False
                current_state = False

                for item in config["main"][section]:
                    if item.get("name") == key:
                        target_found = True
                        current_state = item.get("enabled", False)
                        break

                # Also check toggles section for the current state
                if "toggles" in config and section in config["toggles"] and key in config["toggles"][section]:
                    current_state = config["toggles"][section][key]

                # Create confirmation view
                view = discord.ui.View(timeout=60)

                # Add toggle buttons with labels that show the current state
                toggle_button = discord.ui.Button(
                    label=f"{'Disable' if current_state else 'Enable'} {key.replace('_', ' ').title()}",
                    style=discord.ButtonStyle.danger if current_state else discord.ButtonStyle.success,
                    custom_id="confirm_toggle"
                )
                view.add_item(toggle_button)

                cancel_button = discord.ui.Button(
                    label="Cancel",
                    style=discord.ButtonStyle.secondary,
                    custom_id="cancel"
                )
                view.add_item(cancel_button)

                # Define callback
                async def button_callback(button_interaction):
                    if button_interaction.data["custom_id"] == "confirm_toggle":
                        # Toggle the state
                        new_state = not current_state

                        # Update in toggles section
                        if "toggles" not in config:
                            config["toggles"] = {}
                        if section not in config["toggles"]:
                            config["toggles"][section] = {}
                        config["toggles"][section][key] = new_state

                        # Update in main section
                        updated_in_main = False
                        for item in config["main"][section]:
                            if item.get("name") == key:
                                item["enabled"] = new_state
                                updated_in_main = True
                                break

                        # If not found in main section, add it
                        if not updated_in_main:
                            new_item = {"name": key, "enabled": new_state}
                            if section == "jobs":
                                new_item["interval"] = {"start": 120, "end": 180}
                            elif section == "threads":
                                new_item["kwargs"] = {}
                            config["main"][section].append(new_item)

                        # Save config
                        ConfigHelper.save_config(config)

                        # Confirm to user
                        await button_interaction.response.edit_message(
                            content=f"{section.capitalize()} '{key}' has been {'enabled' if new_state else 'disabled'}",
                            view=None
                        )
                    else:
                        # User cancelled
                        await button_interaction.response.edit_message(
                            content=f"No changes made. {section.capitalize()} '{key}' remains {'enabled' if current_state else 'disabled'}.",
                            view=None
                        )

                # Register the callback
                for button in view.children:
                    button.callback = button_callback

                # Show the current state and confirm
                await interaction.response.send_message(
                    f"{section.capitalize()} '{key}' is currently {'enabled' if current_state else 'disabled'}. Do you want to change it?",
                    view=view,
                    ephemeral=True
                )

            else:
                await interaction.response.send_message(f"Unknown config section: {section}", ephemeral=True)

        except Exception as e:
            logger.error(f"Error in toggle_rally_config: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            await interaction.response.send_message(f"Error toggling config: {str(e)}", ephemeral=True)

    user_friendly_commands = UserFriendlyCommands()

@tree.error
async def on_app_command_error(interaction, error):
    """Handle command errors gracefully"""
    logger.error(f"Command error in {interaction.command.name if interaction.command else 'unknown'}: {str(error)}")
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(f"Error executing command: {str(error)}", ephemeral=True)
        else:
            await interaction.followup.send(f"Error executing command: {str(error)}", ephemeral=True)
    except Exception as e:
        logger.error(f"Failed to send error response: {str(e)}")

from lokbot.normal_monsters_commands import NormalMonstersCommands
from lokbot.discord_commands import RallyConfigCommands
tree.add_command(user_friendly_commands)
tree.add_command(NormalMonstersCommands())
tree.add_command(RallyConfigCommands())

@client.event
async def on_ready():
    await tree.sync()
    logger.info(f"Discord bot is ready! Logged in as {client.user}")


def run_http_server():
    """Run an enhanced HTTP server."""

    class EnhancedHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/health':
                self.handle_health_check()
            else:
                self.handle_main_response()

        def do_HEAD(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()

        def handle_health_check(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK\n')
            logger.info("Health check successful")

        def handle_main_response(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()

            # Gather System information
            cpu_percent = psutil.cpu_percent()
            memory_percent = psutil.virtual_memory().percent
            os_name = platform.system()
            python_version = platform.python_version()

            response_message = f"LokBot is running\nCPU: {cpu_percent}%\nMemory: {memory_percent}%\nOS: {os_name}\nPython: {python_version}\n"
            self.wfile.write(response_message.encode('utf-8'))

            logger.info(f"HTTP request: {self.path}")

        def log_message(self, format, *args):
            logger.info(f"HTTP: {format % args}")

        def log_error(self, format, *args):
            logger.error(f"HTTP Error: {format % args}")

    port = int(os.environ.get('PORT', 10000))
    server_address = ('0.0.0.0', port)

    try:
        server = http.server.HTTPServer(server_address, EnhancedHTTPRequestHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        logger.info(f"HTTP server started on port {port}")
    except Exception as e:
        logger.critical(f"Failed to start HTTP server: {e}")


def run_discord_bot():
    # Get the token from environment variable
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        logger.error("Error: DISCORD_BOT_TOKEN not found in environment")
        logger.error("Please set DISCORD_BOT_TOKEN in Secrets (Tools > Secrets)")

        # Start HTTP server to keep the app alive even without token
        run_http_server()

        # Keep server running, checking for token periodically
        import time
        while True:
            time.sleep(60)
            # Check if token has been added
            new_token = os.getenv("DISCORD_BOT_TOKEN")
            if new_token:
                logger.info("DISCORD_BOT_TOKEN found! Attempting to restart...")
                try:
                    # Validate token format
                    if len(new_token) < 50:
                        logger.error("Invalid token format (too short)")
                        continue

                    client.run(new_token)
                    break
                except discord.errors.LoginFailure as e:
                    logger.error(f"Discord login failed: {str(e)}")
                except Exception as e:
                    logger.error(f"Failed to start bot with new token: {str(e)}")
                    logger.error("Please check if the token is valid and has the correct permissions")
            else:
                logger.info("HTTP server still alive, waiting for valid token...")
        return

    # Start HTTP server to keep the bot alive
    run_http_server()

    try:
        logger.info(f"Starting Discord bot at port {os.environ.get('PORT', 10000)}")

        # Run the Discord bot
        client.run(token)
    except Exception as e:
        logger.error(f"CRITICAL ERROR: Discord bot crashed: {str(e)}")
        # Print full exception details
        import traceback
        traceback.print_exc()

        # Keep the HTTP server running even if the bot crashes
        import time
        while True:
            time.sleep(60)
            logger.info("HTTP server still alive despite bot crash, waiting for restart...")


if __name__ == "__main__":
    run_discord_bot()
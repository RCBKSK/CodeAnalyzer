"""
Helper module for managing and displaying bot configurations in a user-friendly way
"""
import json
import os
import logging
import discord
from typing import Dict, Any, List, Optional, Tuple

# To run this code, you need to install the discord.py library:
# pip install discord.py

logger = logging.getLogger(__name__)

class ConfigHelper:
    """Helper class for displaying and modifying configurations in a user-friendly way"""

    current_config_file = "config.json"  # Track currently selected config file
    simplified_configs = {
        'rally_join': 'config_rally_join.json',
        'monster_attack': 'config_monster_attack.json',
        'gathering': 'config_gathering.json'
    }

    @staticmethod
    def set_current_config(config_file: str):
        """Set the current configuration file"""
        ConfigHelper.current_config_file = config_file
        logger.info(f"Set current config file to: {config_file}")

    @staticmethod
    def load_simplified_config(config_type: str) -> Optional[Dict[str, Any]]:
        """Load a simplified config file for specific feature"""
        if config_type in ConfigHelper.simplified_configs:
            config_file = ConfigHelper.simplified_configs[config_type]
            try:
                with open(config_file, 'r') as f:
                    return json.load(f)
            except FileNotFoundError:
                logger.warning(f"Simplified config file {config_file} not found, using defaults")
                return ConfigHelper._get_default_config(config_type)
        return None

    @staticmethod
    def _get_default_config(config_type: str) -> Dict[str, Any]:
        """Return default configuration for simplified config types"""
        defaults = {
            'rally_join': {
                "rally_join": {
                    "enabled": False,
                    "max_marches": 8,
                    "targets": []
                }
            },
            'monster_attack': {
                "monster_attack": {
                    "enabled": False,
                    "max_distance": 200,
                    "troops": [],
                    "targets": []
                }
            },
            'gathering': {
                "gathering": {
                    "enabled": True,
                    "max_marches": 10,
                    "max_distance": 250,
                    "targets": []
                }
            }
        }
        return defaults.get(config_type, {})

    @staticmethod
    def load_config(config_file=None) -> Dict[str, Any]:
        """Load configuration from file with error handling"""
        # Always prefer explicitly passed config file
        if config_file is not None:
            ConfigHelper.set_current_config(config_file)
        config_file = ConfigHelper.current_config_file
        logger.info(f"Loading config from: {config_file}")
        try:
            with open(config_file, "r") as f:
                loaded_config = json.load(f)
                # If numMarch is specified in the loaded config, use that value
                if 'rally' in loaded_config:
                    if 'join' in loaded_config['rally'] and loaded_config['rally']['join'].get('numMarch') is not None:
                        logger.info(f"Using numMarch={loaded_config['rally']['join']['numMarch']} from config for rally join")
                    if 'start' in loaded_config['rally'] and loaded_config['rally']['start'].get('numMarch') is not None:
                        logger.info(f"Using numMarch={loaded_config['rally']['start']['numMarch']} from config for rally start")
                return loaded_config
        except FileNotFoundError:
            logger.warning(f"Config file {config_file} not found, creating default")
            default_config = {
                "main": {
                    "jobs": [],
                    "threads": [],
                    "normal_monsters": {
                        "enabled": True,
                        "targets": [],
                        "max_distance": 200
                    },
                    "treasure": {
                        "page": 1
                    },
                    "skills": {
                        "enabled": True,
                        "skills": [
                            {"code": 10001, "enabled": True},
                            {"code": 10002, "enabled": True}
                        ]
                    },
                    "daily_free_package": {
                        "enabled": True
                    },
                    "object_scanning": {
                        "enabled": False,
                        "monster_attack": {
                            "enabled": False,
                            "targets": []
                        }
                    }
                },
                "rally": {
                    "join": {
                        "enabled": False,
                        "numMarch": None,  # Will be loaded from config file
                        "level_based_troops": True,
                        "targets": []
                    },
                    "start": {
                        "enabled": False,
                        "numMarch": None,  # Will be loaded from config file
                        "level_based_troops": True,
                        "targets": []
                    }
                },
                "discord": {
                    "enabled": True,
                    "webhook_url": ""
                }
            }
            with open(config_file, "w") as f:
                json.dump(default_config, f, indent=2, sort_keys=False, separators=(',', ': '))
            return default_config
        except json.JSONDecodeError:
            logger.error(f"Error parsing {config_file}, file may be corrupted")
            raise

    @staticmethod
    def save_config(config: Dict[str, Any], config_file=None) -> bool:
        """Save configuration to file with error handling and sync toggles structure"""
        # Always use current_config_file unless explicitly overridden
        config_file = config_file if config_file is not None else ConfigHelper.current_config_file
        logger.info(f"Saving config to: {config_file}")
        try:
            # Ensure toggles structure exists
            if "toggles" not in config:
                config["toggles"] = {"jobs": {}, "threads": {}, "features": {}}

            # Sync job toggles
            if "main" in config and "jobs" in config["main"]:
                for job in config["main"]["jobs"]:
                    job_name = job.get("name")
                    if job_name:
                        if "jobs" not in config["toggles"]:
                            config["toggles"]["jobs"] = {}
                        config["toggles"]["jobs"][job_name] = job.get("enabled", False)

                # Also sync from toggles to main jobs (bidirectional)
                if "jobs" in config["toggles"]:
                    for job_name, enabled in config["toggles"]["jobs"].items():
                        # Find the job in main.jobs
                        for job in config["main"]["jobs"]:
                            if job.get("name") == job_name:
                                job["enabled"] = enabled
                                break

            # Sync thread toggles
            if "main" in config and "threads" in config["main"]:
                for thread in config["main"]["threads"]:
                    thread_name = thread.get("name")
                    if thread_name:
                        if "threads" not in config["toggles"]:
                            config["toggles"]["threads"] = {}
                        config["toggles"]["threads"][thread_name] = thread.get("enabled", False)

                # Also sync from toggles to main threads (bidirectional)
                if "threads" in config["toggles"]:
                    for thread_name, enabled in config["toggles"]["threads"].items():
                        # Find the thread in main.threads
                        for thread in config["main"]["threads"]:
                            if thread.get("name") == thread_name:
                                thread["enabled"] = enabled
                                break

            # Sync feature toggles
            if "features" not in config["toggles"]:
                config["toggles"]["features"] = {}

            # Object scanning and monster attack
            if "main" in config and "object_scanning" in config["main"]:
                object_scanning = config["main"]["object_scanning"]
                config["toggles"]["features"]["object_scanning"] = object_scanning.get("enabled", False)
                config["toggles"]["features"]["enable_monster_attack"] = object_scanning.get("monster_attack", {}).get("enabled", False)

                # Bidirectional sync
                if "object_scanning" in config["toggles"]["features"]:
                    object_scanning["enabled"] = config["toggles"]["features"]["object_scanning"]
                if "enable_monster_attack" in config["toggles"]["features"]:
                    if "monster_attack" not in object_scanning:
                        object_scanning["monster_attack"] = {}
                    object_scanning["monster_attack"]["enabled"] = config["toggles"]["features"]["enable_monster_attack"]

            # Daily free package
            if "main" in config and "daily_free_package" in config["main"]:
                daily_package = config["main"]["daily_free_package"]
                config["toggles"]["features"]["daily_free_package"] = daily_package.get("enabled", False)

                # Bidirectional sync
                if "daily_free_package" in config["toggles"]["features"]:
                    daily_package["enabled"] = config["toggles"]["features"]["daily_free_package"]

            # Rally join/start
            if "rally" in config:
                if "join" in config["rally"]:
                    config["toggles"]["features"]["rally_join"] = config["rally"]["join"].get("enabled", False)
                    # Bidirectional sync
                    if "rally_join" in config["toggles"]["features"]:
                        config["rally"]["join"]["enabled"] = config["toggles"]["features"]["rally_join"]

                if "start" in config["rally"]:
                    config["toggles"]["features"]["rally_start"] = config["rally"]["start"].get("enabled", False)
                    # Bidirectional sync
                    if "rally_start" in config["toggles"]["features"]:
                        config["rally"]["start"]["enabled"] = config["toggles"]["features"]["rally_start"]

            # Discord
            if "discord" in config:
                config["toggles"]["features"]["discord"] = config.get("discord", {}).get("enabled", False)
                # Bidirectional sync
                if "discord" in config["toggles"]["features"]:
                    config["discord"]["enabled"] = config["toggles"]["features"]["discord"]

            # Save the file
            with open(config_file, "w") as f:
                json.dump(config, f, indent=2, sort_keys=False, separators=(',', ': '))
            return True
        except Exception as e:
            logger.error(f"Error saving config: {str(e)}")
            return False

    @staticmethod
    async def create_config_overview_embed(config: Dict[str, Any]) -> discord.Embed:
        """Create a simplified overview of all configurations"""
        embed = discord.Embed(
            title="📋 LokBot Configuration Overview",
            description="Welcome to the unified configuration interface! This is now the central place to manage all your bot settings.",
            color=discord.Color.blue()
        )

        # Main settings summary
        main_config = config.get('main', {})
        jobs = main_config.get('jobs', [])
        threads = main_config.get('threads', [])

        enabled_jobs = sum(1 for job in jobs if job.get('enabled', False))
        enabled_threads = sum(1 for thread in threads if thread.get('enabled', False))

        embed.add_field(
            name="📊 Status Summary",
            value=f"⚙️ **Jobs**: {enabled_jobs}/{len(jobs)} enabled\n"
                  f"🧵 **Threads**: {enabled_threads}/{len(threads)} enabled\n"
                  f"🔔 **Discord**: {'✅ Enabled' if config.get('discord', {}).get('enabled', False) else '❌ Disabled'}\n"
                  f"🎯 **Rally Join**: {'✅ Enabled' if config.get('rally', {}).get('join', {}).get('enabled', False) else '❌ Disabled'}\n"
                  f"⚔️ **Rally Start**: {'✅ Enabled' if config.get('rally', {}).get('start', {}).get('enabled', False) else '❌ Disabled'}",
            inline=False
        )

        return embed

    @staticmethod
    async def create_simplified_buttons() -> discord.ui.View:
        """Create a simplified button interface for configuration"""
        view = discord.ui.View(timeout=300)

        logger.info("Creating simplified buttons for config interface")

        # Main configuration categories with emoji prefixes for better visibility
        view.add_item(discord.ui.Button(
            label="⚙️ Game Settings",
            style=discord.ButtonStyle.primary,
            custom_id="simplified_game_settings"
        ))

        view.add_item(discord.ui.Button(
            label="🎯 Rally Join Settings",
            style=discord.ButtonStyle.primary,
            custom_id="simplified_rally_join"
        ))

        view.add_item(discord.ui.Button(
            label="⚔️ Rally Start Settings",
            style=discord.ButtonStyle.primary,
            custom_id="simplified_rally_start"
        ))

        view.add_item(discord.ui.Button(
            label="🔔 Discord Notifications",
            style=discord.ButtonStyle.primary,
            custom_id="simplified_discord"
        ))

        logger.info(f"Created view with {len(view.children)} buttons")
        return view

    @staticmethod
    def get_feature_explanation(feature_type: str) -> str:
        """Get a user-friendly explanation for different features"""
        explanations = {
            "rally_join": "Rally Join allows your bot to automatically join rallies that others start. "
                          "You can specify which monsters to join and how many troops to send.",

            "rally_start": "Rally Start allows your bot to automatically start rallies against monsters. "
                           "You can specify which monsters to target and set rally messages.",

            "jobs": "Jobs are periodic tasks that run at specified intervals. These include "
                    "resource gathering, hospital healing, and other maintenance tasks.",

            "threads": "Threads are continuous processes that run in the background. "
                       "These include building upgrades, research, and other ongoing activities.",

            "webhooks": "Discord webhooks allow the bot to send notifications to your Discord channels "
                        "for important events like rally notifications or resource discoveries.",

            "normal_monsters": "Normal Monsters refers to the automatic attacking of regular monsters on the map. "
                               "You can configure which monsters to target and the maximum distance for attacks.",

            "monster_attack": "Monster Attack, within Object Scanning, enables your bot to automatically attack "
                              "monsters detected through object scanning. This is separate from general normal monster attacks."
        }

        return explanations.get(feature_type, "No explanation available for this feature.")

    @staticmethod
    async def create_simplified_feature_view(feature_type: str, config: Optional[Dict[str, Any]] = None) -> Tuple[discord.Embed, discord.ui.View]:
        """Create a simplified view for a specific feature"""
        # Load config if not provided
        if config is None:
            config = ConfigHelper.load_config()

        # Get current state of the feature
        feature_enabled = False
        marches_count = 0
        target_count = 0
        max_distance = 0 # Initialize for normal_monsters

        if feature_type == "rally_join":
            # Check both places for consistency
            if "toggles" in config and "features" in config["toggles"] and "rally_join" in config["toggles"]["features"]:
                feature_enabled = config["toggles"]["features"]["rally_join"]
            elif "rally" in config and "join" in config["rally"]:
                feature_enabled = config["rally"]["join"].get("enabled", False)

            if "rally" in config and "join" in config["rally"]:
                marches_count = config["rally"]["join"].get("numMarch", 8)
                target_count = len(config["rally"]["join"].get("targets", []))

        elif feature_type == "rally_start":
            # Check both places for consistency
            if "toggles" in config and "features" in config["toggles"] and "rally_start" in config["toggles"]["features"]:
                feature_enabled = config["toggles"]["features"]["rally_start"]
            elif "rally" in config and "start" in config["rally"]:
                feature_enabled = config["rally"]["start"].get("enabled", False)

            if "rally" in config and "start" in config["rally"]:
                marches_count = config["rally"]["start"].get("numMarch", 6)
                target_count = len(config["rally"]["start"].get("targets", []))

        elif feature_type == "discord":
            # Check both places for consistency
            if "toggles" in config and "features" in config["toggles"] and "discord" in config["toggles"]["features"]:
                feature_enabled = config["toggles"]["features"]["discord"]
            elif "discord" in config:
                feature_enabled = config["discord"].get("enabled", False)

        elif feature_type == "normal_monsters":
            feature_enabled = config.get("main", {}).get("normal_monsters", {}).get("enabled", False)
            target_count = len(config.get("main", {}).get("normal_monsters", {}).get("targets", []))
            max_distance = config.get("main", {}).get("normal_monsters", {}).get("max_distance", 200)

        elif feature_type == "monster_attack":
            feature_enabled = config.get('main', {}).get('object_scanning', {}).get('monster_attack', {}).get('enabled', False)
            target_count = len(config.get('main', {}).get('object_scanning', {}).get('monster_attack', {}).get('targets', []))


        # Create embed based on feature type with current status
        title_map = {
            "game": "⚙️ Game Settings",
            "rally_join": "🎯 Rally Join",
            "rally_start": "⚔️ Rally Start",
            "discord": "🔔 Discord Notifications",
            "normal_monsters": "🧌 Normal Monsters",
            "monster_attack": "💥 Monster Attack (Object Scan)"
        }
        embed = discord.Embed(
            title=title_map.get(feature_type, "Unknown Feature Settings"),
            description=ConfigHelper.get_feature_explanation(feature_type),
            color=discord.Color.green()
        )

        # Add field with current status for rally features and discord
        if feature_type in ["rally_join", "rally_start"]:
            embed.add_field(
                name="Current Status",
                value=f"**Enabled:** {'✅ Yes' if feature_enabled else '❌ No'}\n"
                      f"**Max Marches:** {marches_count}\n"
                      f"**Configured Monsters:** {target_count}",
                inline=False
            )
        elif feature_type == "discord":
            webhook_url = config.get("discord", {}).get("webhook_url", "")
            rally_webhook_url = config.get("discord", {}).get("rally_webhook_url", "")

            embed.add_field(
                name="Current Status",
                value=f"**Enabled:** {'✅ Yes' if feature_enabled else '❌ No'}\n"
                      f"**Main Webhook:** {'✅ Configured' if webhook_url else '❌ Not Configured'}\n"
                      f"**Rally Webhook:** {'✅ Configured' if rally_webhook_url else '❌ Not Configured'}",
                inline=False
            )
        elif feature_type == "game":
            # Get job and thread counts
            jobs = config.get("main", {}).get("jobs", [])
            threads = config.get("main", {}).get("threads", [])
            normal_monster_targets = len(config.get("main", {}).get("normal_monsters", {}).get("targets", []))

            enabled_jobs = sum(1 for job in jobs if job.get("enabled", False))
            enabled_threads = sum(1 for thread in threads if thread.get("enabled", False))

            embed.add_field(
                name="Current Status",
                value=f"**Jobs:** {enabled_jobs}/{len(jobs)} enabled\n"
                      f"**Threads:** {enabled_threads}/{len(threads)} enabled\n"
                      f"**Normal Monster Targets:** {normal_monster_targets}",
                inline=False
            )
        elif feature_type == "normal_monsters":
            embed.add_field(
                name="Current Status",
                value=f"**Enabled:** {'✅ Yes' if feature_enabled else '❌ No'}\n"
                      f"**Max Distance:** {max_distance}\n"
                      f"**Configured Monsters:** {target_count}",
                inline=False
            )
        elif feature_type == "monster_attack":
            embed.add_field(
                name="Current Status",
                value=f"**Enabled:** {'✅ Yes' if feature_enabled else '❌ No'}\n"
                      f"**Targets:** {target_count}",
                inline=False
            )


        # Create simplified button view with longer timeout
        view = discord.ui.View(timeout=600)  # Increased from 300 to 600 seconds

        # Add timeout callback
        async def on_timeout():
            logger.info(f"View for {feature_type} timed out")

        view.on_timeout = on_timeout

        if feature_type == "rally_join" or feature_type == "rally_start":
            view.add_item(discord.ui.Button(
                label=f"{'Disable' if feature_enabled else 'Enable'} Rally {'Join' if feature_type == 'rally_join' else 'Start'}",
                style=discord.ButtonStyle.danger if feature_enabled else discord.ButtonStyle.success,
                custom_id=f"simple_toggle_{feature_type}"
            ))

            view.add_item(discord.ui.Button(
                label=f"Configure Marches ({marches_count})",
                style=discord.ButtonStyle.primary,
                custom_id=f"simple_marches_{feature_type}"
            ))

            view.add_item(discord.ui.Button(
                label=f"Configure Monsters ({target_count})",
                style=discord.ButtonStyle.primary,
                custom_id=f"simple_monsters_{feature_type}"
            ))

            # Add a help button
            view.add_item(discord.ui.Button(
                label="❓ Help",
                style=discord.ButtonStyle.secondary,
                custom_id=f"help_{feature_type}"
            ))

        elif feature_type == "game":
            jobs = config.get("main", {}).get("jobs", [])
            threads = config.get("main", {}).get("threads", [])
            enabled_jobs = sum(1 for job in jobs if job.get("enabled", False))
            enabled_threads = sum(1 for thread in threads if thread.get("enabled", False))

            view.add_item(discord.ui.Button(
                label=f"Configure Jobs ({enabled_jobs}/{len(jobs)})",
                style=discord.ButtonStyle.primary,
                custom_id="simple_jobs"
            ))

            view.add_item(discord.ui.Button(
                label=f"Configure Threads ({enabled_threads}/{len(threads)})",
                style=discord.ButtonStyle.primary,
                custom_id="simple_threads"
            ))

            # Add a help button
            view.add_item(discord.ui.Button(
                label="❓ Help",
                style=discord.ButtonStyle.secondary,
                custom_id="help_game"
            ))

        elif feature_type == "discord":
            view.add_item(discord.ui.Button(
                label=f"{'Disable' if feature_enabled else 'Enable'} Discord Integration",
                style=discord.ButtonStyle.danger if feature_enabled else discord.ButtonStyle.success,
                custom_id="simple_toggle_discord"
            ))

            view.add_item(discord.ui.Button(
                label="Configure Webhooks",
                style=discord.ButtonStyle.primary,
                custom_id="simple_webhooks"
            ))

            # Add a help button
            view.add_item(discord.ui.Button(
                label="❓ Help",
                style=discord.ButtonStyle.secondary,
                custom_id="help_discord"
            ))
        elif feature_type == "normal_monsters":
            view.add_item(discord.ui.Button(
                label=f"{'Disable' if feature_enabled else 'Enable'} Normal Monsters",
                style=discord.ButtonStyle.danger if feature_enabled else discord.ButtonStyle.success,
                custom_id=f"simple_toggle_normal_monsters"
            ))
            view.add_item(discord.ui.Button(
                label=f"Configure Targets ({target_count})",
                style=discord.ButtonStyle.primary,
                custom_id=f"simple_targets_normal_monsters"
            ))
            view.add_item(discord.ui.Button(
                label=f"Configure Max Distance ({max_distance})",
                style=discord.ButtonStyle.primary,
                custom_id=f"simple_max_distance_normal_monsters"
            ))
            # Add a help button
            view.add_item(discord.ui.Button(
                label="❓ Help",
                style=discord.ButtonStyle.secondary,
                custom_id=f"help_normal_monsters"
            ))
        elif feature_type == "monster_attack":
            view.add_item(discord.ui.Button(
                label=f"{'Disable' if feature_enabled else 'Enable'} Monster Attack",
                style=discord.ButtonStyle.danger if feature_enabled else discord.ButtonStyle.success,
                custom_id=f"simple_toggle_monster_attack"
            ))
            view.add_item(discord.ui.Button(
                label=f"Configure Targets ({target_count})",
                style=discord.ButtonStyle.primary,
                custom_id=f"simple_targets_monster_attack"
            ))
            # Add a help button
            view.add_item(discord.ui.Button(
                label="❓ Help",
                style=discord.ButtonStyle.secondary,
                custom_id=f"help_monster_attack"
            ))


        # Add back button
        view.add_item(discord.ui.Button(
            label="Back to Overview",
            style=discord.ButtonStyle.secondary,
            custom_id="back_to_overview"
        ))

        return embed, view

    @staticmethod
    async def create_help_embed(feature_type: str) -> discord.Embed:
        """Create a help embed for different features"""
        if feature_type == "rally_join":
            embed = discord.Embed(
                title="🎯 Rally Join - Help",
                description="How to configure rally join settings",
                color=discord.Color.blue()
            )

            embed.add_field(
                name="What is Rally Join?",
                value="Rally Join allows your bot to automatically join rallies started by other players in your alliance.",
                inline=False
            )

            embed.add_field(
                name="Basic Settings",
                value="• **Toggle On/Off**: Enable or disable rally joining\n"
                      "• **Configure Marches**: Set how many marches to use (1-10)\n"
                      "• **Level Based Troops**: Send different troops based on monster level",
                inline=False
            )

            embed.add_field(
                name="Monster Configuration",
                value="• Each monster can have different troop compositions\n"
                      "• Set different troops for different monster levels\n"
                      "• Add predefined monsters or create custom ones",
                inline=False
            )

        elif feature_type == "rally_start":
            embed = discord.Embed(
                title="⚔️ Rally Start - Help",
                description="How to configure rally start settings",
                color=discord.Color.blue()
            )

            embed.add_field(
                name="What is Rally Start?",
                value="Rally Start allows your bot to automatically start rallies against monsters on the map.",
                inline=False
            )

            embed.add_field(
                name="Basic Settings",
                value="• **Toggle On/Off**: Enable or disable rally starting\n"
                      "• **Configure Marches**: Set how many marches to use (1-10)\n"
                      "• **Level Based Troops**: Send different troops based on monster level",
                inline=False
            )

            embed.add_field(
                name="Monster Configuration",
                value="• Set monsters to target when starting rallies\n"
                      "• Configure custom rally messages\n"
                      "• Set rally time for each monster type/level",
                inline=False
            )

        elif feature_type == "game":
            embed = discord.Embed(
                title="⚙️ Game Settings - Help",
                description="How to configure general game settings",
                color=discord.Color.blue()
            )

            embed.add_field(
                name="Jobs",
                value="Jobs are periodic tasks like:\n"
                      "• Hospital recovery\n"
                      "• Wall repair\n"
                      "• Resource harvesting\n"
                      "• Alliance activities",
                inline=False
            )

            embed.add_field(
                name="Threads",
                value="Threads are background processes like:\n"
                      "• Free chest farming\n"
                      "• Building upgrades\n"
                      "• Research management\n"
                      "• Troop training",
                inline=False
            )
        elif feature_type == "discord":
            embed = discord.Embed(
                title="🔔 Discord Notifications - Help",
                description="How to configure Discord notifications",
                color=discord.Color.blue()
            )

            embed.add_field(
                name="Discord Integration",
                value="Enable or disable all Discord notifications",
                inline=False
            )

            embed.add_field(
                name="Webhook Types",
                value="• **Main Webhook**: General notifications\n"
                      "• **Rally Webhook**: Rally notifications\n"
                      "• **Crystal Mine Webhook**: Crystal mine discoveries\n"
                      "• **Resource Webhooks**: Resource-related notifications",
                inline=False
            )

            embed.add_field(
                name="How to Create Webhooks",
                value="1. Go to your Discord server\n"
                      "2. Edit a channel > Integrations > Webhooks > New Webhook\n"
                      "3. Copy the webhook URL\n"
                      "4. Paste it in the configuration",
                inline=False
            )
        elif feature_type == "normal_monsters":
            embed = discord.Embed(
                title="🧌 Normal Monsters - Help",
                description="How to configure Normal Monster settings",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="What are Normal Monsters?",
                value="Normal Monsters are the standard monsters you encounter on the map.",
                inline=False
            )
            embed.add_field(
                name="Basic Settings",
                value="• **Toggle On/Off**: Enable or disable Normal Monster configuration\n"
                      "• **Configure Targets**: Set which monsters to target\n"
                      "• **Configure Max Distance**: Set the maximum distance to attack monsters",
                inline=False
            )
        elif feature_type == "monster_attack":
            embed = discord.Embed(
                title="⚔️ Monster Attack - Help",
                description="How to configure Monster Attack settings within Object Scanning",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="What is Monster Attack?",
                value="Monster Attack allows the bot to automatically attack monsters detected by object scanning.",
                inline=False
            )
            embed.add_field(
                name="Basic Settings",
                value="• **Toggle On/Off**: Enable or disable Monster Attack\n"
                      "• **Configure Targets**: Select specific monsters to target",
                inline=False
            )


        return embed

    @staticmethod
    def format_monster_info(monster_data: Dict[str, Any]) -> str:
        """Format monster information in a user-friendly way"""
        monster_name = monster_data.get('monster_name', 'Unknown Monster')
        monster_code = monster_data.get('monster_code', 'N/A')
        level_ranges = monster_data.get('level_ranges', [])

        level_info = []
        for lr in level_ranges:
            min_level = lr.get('min_level', 0)
            max_level = lr.get('max_level', 0)
            troops_count = len(lr.get('troops', []))
            level_info.append(f"  - Levels {min_level}-{max_level}: {troops_count} troop configurations")

        if not level_info:
            level_info_str = "  - No specific level configurations."
        else:
            level_info_str = "\n".join(level_info)

        return (
            f"**Monster Name:** {monster_name} (Code: {monster_code})\n"
            f"**Configured Levels:**\n{level_info_str}"
        )

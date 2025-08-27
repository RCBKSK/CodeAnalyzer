"""
Enhanced user-friendly Discord command implementations
"""
import discord
import json
import logging
import os
from typing import Dict, Any, List, Optional
from discord import app_commands
from lokbot.config_helper import ConfigHelper

logger = logging.getLogger(__name__)

class UserFriendlyCommands(app_commands.Group):
    """User-friendly commands implementation for Discord bot"""

    def __init__(self):
        super().__init__(name="config", description="User-friendly configuration commands")

    @app_commands.command(name="setup", description="Configure all bot settings in this single comprehensive interface")
    async def config_setup(self, interaction: discord.Interaction):
        """Main entry point for the unified configuration interface - the only command needed for all bot settings"""
        # Check permissions
        allowed_role_id = 508024195549102097
        has_permission = interaction.user.guild_permissions.administrator or any(role.id == allowed_role_id for role in interaction.user.roles)
        if not has_permission:
            await interaction.response.send_message("You need administrator permission or the required role to use this command!", ephemeral=True)
            return

        try:
            # Get list of available config files from root directory only
            config_files = []
            simplified_configs = []
            
            for file in os.listdir('.'):
                if file.endswith('.json') and os.path.isfile(file):
                    if file.startswith('config_') and file in ['config_rally_join.json', 'config_monster_attack.json', 'config_gathering.json']:
                        simplified_configs.append(file)
                    else:
                        config_files.append(file)
            
            # Sort configs - put simplified ones first
            all_configs = simplified_configs + config_files

            # Create config selection view  
            view = discord.ui.View(timeout=300)
            
            # Create options with better labels for simplified configs
            options = []
            for file in all_configs:
                if file == 'config_rally_join.json':
                    options.append(discord.SelectOption(label="🎯 Rally Join (Simplified)", value=file, description="Simple rally join settings only"))
                elif file == 'config_monster_attack.json':
                    options.append(discord.SelectOption(label="👾 Monster Attack (Simplified)", value=file, description="Simple monster attack settings only"))
                elif file == 'config_gathering.json':
                    options.append(discord.SelectOption(label="🌾 Gathering (Simplified)", value=file, description="Simple gathering settings only"))
                else:
                    options.append(discord.SelectOption(label=f"⚙️ {file}", value=file, description="Full configuration file"))
            
            config_select = discord.ui.Select(
                placeholder="Select a configuration type",
                options=options
            )

            async def config_select_callback(select_interaction):
                try:
                    selected_file = select_interaction.data["values"][0]

                    # Set selected config file in ConfigHelper and update all relevant components
                    ConfigHelper.set_current_config(selected_file)
                    logger.info(f"Switching to config file: {selected_file}")

                    # Load the selected config - don't store in 'updated_config'
                    config = ConfigHelper.load_config(selected_file)

                    # Store in environment and ensure all handlers know about the change
                    os.environ["LOKBOT_CONFIG"] = selected_file

                    # Update any active handlers or components that need the new config
                    if hasattr(self, 'rally_commands'):
                        self.rally_commands.current_config = selected_file

                    # Create overview embed with all settings
                    embed = await ConfigHelper.create_config_overview_embed(config)
                    embed.title = f"📋 LokBot Configuration Overview - {selected_file}"

                    # Create full config view with all buttons
                    config_view = discord.ui.View(timeout=300)

                    # Add all major category buttons
                    config_view.add_item(discord.ui.Button(label="⚙️ Game Settings", style=discord.ButtonStyle.primary, custom_id="game_settings"))
                    config_view.add_item(discord.ui.Button(label="🎯 Rally Join", style=discord.ButtonStyle.primary, custom_id="rally_join"))
                    config_view.add_item(discord.ui.Button(label="⚔️ Rally Start", style=discord.ButtonStyle.primary, custom_id="rally_start"))
                    config_view.add_item(discord.ui.Button(label="🔔 Discord Notifications", style=discord.ButtonStyle.primary, custom_id="discord"))
                    config_view.add_item(discord.ui.Button(label="🔍 Object Scanning", style=discord.ButtonStyle.primary, custom_id="object_scanning"))
                    config_view.add_item(discord.ui.Button(label="🌾 Resource Gathering", style=discord.ButtonStyle.success, custom_id="gathering"))
                    config_view.add_item(discord.ui.Button(label="👾 Monster Attack", style=discord.ButtonStyle.danger, custom_id="monster"))
                    config_view.add_item(discord.ui.Button(label="📊 View All Settings", style=discord.ButtonStyle.secondary, custom_id="view_all"))

                    # Register callbacks with selected config
                    for item in config_view.children:
                        if item.custom_id == "game_settings":
                            item.callback = lambda i: self.feature_callback(i, "game", ConfigHelper.load_config(selected_file))
                        elif item.custom_id == "rally_join":
                            item.callback = lambda i: self.feature_callback(i, "rally_join", ConfigHelper.load_config(selected_file))
                        elif item.custom_id == "rally_start":
                            item.callback = lambda i: self.feature_callback(i, "rally_start", ConfigHelper.load_config(selected_file))
                        elif item.custom_id == "discord":
                            item.callback = lambda i: self.feature_callback(i, "discord", ConfigHelper.load_config(selected_file))
                        elif item.custom_id == "object_scanning":
                            item.callback = lambda i: self.handle_object_scanning(i, selected_file)
                        elif item.custom_id == "gathering":
                            item.callback = lambda i: self.handle_toggle_feature(i, "enable_gathering")
                        elif item.custom_id == "monster":
                            item.callback = lambda i: self.handle_toggle_feature(i, "object_scanning_monster_attack")
                        elif item.custom_id == "view_all":
                            item.callback = lambda i: self.handle_view_settings(i)

                    try:
                        await select_interaction.response.edit_message(
                            content=f"Using configuration file: {selected_file}",
                            embed=embed,
                            view=config_view
                        )
                    except discord.errors.InteractionResponded:
                        await select_interaction.followup.edit_message(
                            message_id=select_interaction.message.id,
                            content=f"Using configuration file: {selected_file}",
                            embed=embed,
                            view=config_view
                        )
                except Exception as e:
                    logger.error(f"Error in config select callback: {str(e)}")
                    await select_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

            config_select.callback = config_select_callback
            view.add_item(config_select)

            # Send only the initial view with config selection
            await interaction.response.send_message(
                "Please select a configuration file to edit:",
                view=view,
                ephemeral=True
            )
            return # Stop here to prevent additional responses

            view.add_item(discord.ui.Button(
                label="📊 View All Settings",
                style=discord.ButtonStyle.primary,
                custom_id="view_all_settings"
            ))

            # Add separate buttons for gathering and monster attack toggles showing correct status
            gathering_enabled = False
            monster_attack_enabled = False

            # First check in toggles section for consistency
            if "toggles" in updated_config and "features" in updated_config["toggles"]:
                if "enable_gathering" in updated_config["toggles"]["features"]:
                    gathering_enabled = updated_config["toggles"]["features"]["enable_gathering"]
                if "enable_monster_attack" in updated_config["toggles"]["features"]:
                    monster_attack_enabled = updated_config["toggles"]["features"]["enable_monster_attack"]

            # If not in toggles, check in main.object_scanning
            if not gathering_enabled and "main" in updated_config and "object_scanning" in updated_config["main"]:
                gathering_enabled = updated_config["main"]["object_scanning"].get("enable_gathering", False)
            if not monster_attack_enabled and "main" in updated_config and "object_scanning" in updated_config["main"]:
                monster_attack_enabled = updated_config["main"]["object_scanning"].get("enable_monster_attack", False)

            toggle_gathering_button = discord.ui.Button(
                label=f"{'✅' if gathering_enabled else '🚫'} Resource Gathering",
                style=discord.ButtonStyle.success if gathering_enabled else discord.ButtonStyle.danger,
                custom_id="toggle_gathering"
            )
            view.add_item(toggle_gathering_button)

            toggle_monster_button = discord.ui.Button(
                label=f"⚔️ Monster Attack: {'Disable' if monster_attack_enabled else 'Enable'}",
                style=discord.ButtonStyle.danger if monster_attack_enabled else discord.ButtonStyle.success,
                custom_id="toggle_monster_attack"
            )
            view.add_item(toggle_monster_button)

            object_scanning_button = discord.ui.Button(
                label="🔍 Object Scanning Settings",
                style=discord.ButtonStyle.primary,
                custom_id="object_scanning_settings"
            )
            view.add_item(object_scanning_button)

            # Define button callbacks properly with correct interaction handling
            async def game_settings_callback(button_interaction):
                try:
                    embed, view = await ConfigHelper.create_simplified_feature_view("game")
                    await button_interaction.response.edit_message(embed=embed, view=view)

                    # Register callbacks for the new view
                    await self.register_feature_callbacks(view, updated_config)
                except Exception as e:
                    logger.error(f"Error in game settings callback: {str(e)}")
                    await button_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

            async def rally_join_callback(button_interaction):
                try:
                    embed, view = await ConfigHelper.create_simplified_feature_view("rally_join")
                    await button_interaction.response.edit_message(embed=embed, view=view)

                    # Register callbacks for the new view
                    await self.register_feature_callbacks(view, updated_config)
                except Exception as e:
                    logger.error(f"Error in rally join callback: {str(e)}")
                    await button_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

            async def rally_start_callback(button_interaction):
                try:
                    embed, view = await ConfigHelper.create_simplified_feature_view("rally_start")
                    await button_interaction.response.edit_message(embed=embed, view=view)

                    # Register callbacks for the new view
                    await self.register_feature_callbacks(view, updated_config)
                except Exception as e:
                    logger.error(f"Error in rally start callback: {str(e)}")
                    await button_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

            async def discord_callback(button_interaction):
                try:
                    embed, view = await ConfigHelper.create_simplified_feature_view("discord")
                    await button_interaction.response.edit_message(embed=embed, view=view)

                    # Register callbacks for the new view
                    await self.register_feature_callbacks(view, updated_config)
                except Exception as e:
                    logger.error(f"Error in discord callback: {str(e)}")
                    await button_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

            async def view_all_settings_callback(button_interaction):
                try:
                    # Use the existing view_settings command from RallyConfigCommands
                    from lokbot.discord_commands import RallyConfigCommands
                    rally_commands = RallyConfigCommands()
                    await rally_commands.view_settings(button_interaction)
                except Exception as e:
                    logger.error(f"Error in view all settings callback: {str(e)}")
                    await button_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

            async def object_scanning_callback(button_interaction):
                try:
                    # Use the existing object scanning UI
                    from lokbot.discord_commands import RallyConfigCommands
                    rally_commands = RallyConfigCommands()
                    await rally_commands.show_object_scanning_config(button_interaction)
                except Exception as e:
                    logger.error(f"Error in object scanning callback: {str(e)}")
                    await button_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

            # Register specific callbacks for main menu buttons
            for item in view.children:
                if item.custom_id == "simplified_game_settings":
                    item.callback = game_settings_callback
                elif item.custom_id == "simplified_rally_join":
                    item.callback = rally_join_callback
                elif item.custom_id == "simplified_rally_start":
                    item.callback = rally_start_callback
                elif item.custom_id == "simplified_discord":
                    item.callback = discord_callback
                elif item.custom_id == "view_all_settings":
                    item.callback = view_all_settings_callback
                elif item.custom_id == "object_scanning_settings":
                    item.callback = object_scanning_callback
                elif item.custom_id == "toggle_gathering":
                    item.callback = lambda i: self.handle_toggle_feature(i, "object_scanning_gathering")
                elif item.custom_id == "toggle_monster_attack":
                    item.callback = lambda i: self.handle_toggle_feature(i, "object_scanning_monster_attack")


            async def view_callback(button_interaction):
                try:
                    # Reload config to ensure latest data
                    updated_config = ConfigHelper.load_config()
                    new_embed = await ConfigHelper.create_config_overview_embed(updated_config)
                    new_view = await ConfigHelper.create_simplified_buttons()

                    if not button_interaction.response.is_done():
                        await button_interaction.response.edit_message(embed=new_embed, view=new_view)
                    else:
                        await button_interaction.followup.send(embed=new_embed, view=new_view, ephemeral=True)
                except Exception as e:
                    logger.error(f"Error in view callback: {str(e)}")
                    await button_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

            # Register callbacks for view buttons
            for item in view.children:
                item.callback = view_callback

            # Send the configuration view
            interaction_valid = True #Added for consistency with followup error handling
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                else:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            except discord.errors.NotFound:
                logger.warning(f"Interaction expired before response could be sent")
            except Exception as e:
                logger.error(f"Error sending initial config menu: {str(e)}")
                if interaction_valid and not interaction.response.is_done():
                    await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

        except Exception as e:
            logger.error(f"Error in config setup: {str(e)}")
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

    async def handle_toggle_feature(self, interaction, feature):
        """Handle toggling a feature on/off"""
        try:
            # Import toggle_rally_config from discord_bot for consistent handling
            from discord_bot import toggle_rally_config

            # Map the feature to the correct config section
            config_section = ""
            if feature == "rally_join":
                config_section = "rally.join"
            elif feature == "rally_start":
                config_section = "rally.start"
            elif feature == "discord":
                config_section = "features.discord"
            elif feature == "enable_gathering":
                config_section = "features.enable_gathering"
            elif feature == "object_scanning_monster_attack":
                config_section = "features.enable_monster_attack"
            elif feature == "object_scanning":
                config_section = "features.object_scanning"
            elif feature == "notify_discord":
                config_section = "features.notify_discord"
            elif feature.startswith("jobs."):
                config_section = feature
            elif feature.startswith("threads."):
                config_section = feature
            else:
                await interaction.response.send_message(f"Unknown feature: {feature}", ephemeral=True)
                return

            # Use the centralized toggle function for consistent behavior
            await toggle_rally_config(interaction, config_section)

        except Exception as e:
            logger.error(f"Error toggling feature {feature}: {str(e)}")
            try:
                # Only try to send a message if the interaction hasn't been responded to yet
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Error updating configuration: {str(e)}", ephemeral=True)
            except:
                # If we can't respond, just log the error
                logger.error(f"Could not send error message to user for feature {feature}")

    async def handle_marches_config(self, interaction, feature):
        """Handle march count configuration"""
        try:
            # Create the modal for march configuration
            modal = discord.ui.Modal(title=f"Configure {feature.replace('_', ' ').title()} Marches")

            # Add the input field
            marches_input = discord.ui.TextInput(
                label="Number of Marches (1-10)",
                placeholder="Enter a number between 1 and 10",
                required=True,
                min_length=1,
                max_length=2
            )
            modal.add_item(marches_input)

            # Define the callback for when the modal is submitted
            async def modal_callback(modal_interaction):
                # Validate and save the new value
                try:
                    new_marches = int(marches_input.value)
                    if new_marches < 1 or new_marches > 10:
                        await modal_interaction.response.send_message(
                            "Invalid input: Number of marches must be between 1 and 10",
                            ephemeral=True
                        )
                        return

                    # Update the configuration
                    config = ConfigHelper.load_config()

                    # Ensure structure exists
                    if "rally" not in config:
                        config["rally"] = {}

                    feature_key = feature.split("_")[-1]  # Gets "join" or "start"
                    if feature_key not in config["rally"]:
                        config["rally"][feature_key] = {"enabled": False, "numMarch": 6, "level_based_troops": True, "targets": []}

                    # Update the marchCount
                    config["rally"][feature_key]["numMarch"] = new_marches

                    # Save the config
                    ConfigHelper.save_config(config)

                    await modal_interaction.response.send_message(
                        f"Number of marches for {feature_key.title()} updated to {new_marches}!",
                        ephemeral=True
                    )

                except ValueError:
                    await modal_interaction.response.send_message(
                        "Invalid input: Please enter a valid number",
                        ephemeral=True
                    )
                except Exception as e:
                    logger.error(f"Error updating marches: {str(e)}")
                    await modal_interaction.response.send_message(
                        f"Error updating configuration: {str(e)}",
                        ephemeral=True
                    )

            # Set the callback
            modal.on_submit = modal_callback

            # Show the modal
            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error(f"Error handling marches config: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def handle_monsters_config(self, interaction, feature):
        """Handle monsters configuration"""
        try:
            # Redirect to the full monsters configuration interface
            from lokbot.discord_commands import RallyConfigCommands
            rally_commands = RallyConfigCommands()

            # Map feature to config section
            feature_key = feature.split("_")[-1]  # Gets "join" or "start"

            # First check if we need to use the new format or old format
            with open("config.json", "r") as f:
                config = json.load(f)

            # Check if we're using the new format (rally.join) or old format (rally_join)
            if "rally" in config and feature_key in config["rally"]:
                config_section = f"rally.{feature_key}"
                logger.info(f"Using new config format: {config_section}")
            else:
                # Fall back to old format
                old_key = f"rally_{feature_key}"
                if old_key in config:
                    config_section = old_key
                    logger.info(f"Using old config format: {config_section}")
                else:
                    # Create the structure if it doesn't exist
                    if "rally" not in config:
                        config["rally"] = {}
                    if feature_key not in config["rally"]:
                        config["rally"][feature_key] = {
                            "enabled": False,
                            "numMarch": 8,
                            "level_based_troops": True,
                            "targets": []
                        }
                        with open("config.json", "w") as f:
                            json.dump(config, f, indent=2)
                    config_section = f"rally.{feature_key}"
                    logger.info(f"Created config structure: {config_section}")

            # Use the existing monster configuration UI
            await rally_commands.show_monster_config(interaction, "config.json", config_section)

        except Exception as e:
            logger.error(f"Error handling monsters config: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def handle_jobs_config(self, interaction):
        """Handle jobs configuration"""
        try:
            # Redirect to the full jobs configuration interface
            from lokbot.discord_commands import RallyConfigCommands
            rally_commands = RallyConfigCommands()

            # Pass the current config file
            config_file = ConfigHelper.current_config_file
            await rally_commands.show_jobs_config(interaction, config_file)

        except Exception as e:
            logger.error(f"Error handling jobs config: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def handle_rally_join_config(self, interaction):
        """Handle Rally Join configuration"""
        # Get current configuration
        config_path = "rally.join"
        with open("config.json", "r") as f:
            config = json.load(f)

        # Check if we need to use the new format or old format
        if "rally" in config and "join" in config["rally"]:
            logger.info(f"Using new config format: {config_path}")
            rally_join_config = config.get("rally", {}).get("join", {})
        else:
            logger.warning(f"No configuration found for {config_path}, creating default")
            # Create default structure if it doesn't exist
            if "rally" not in config:
                config["rally"] = {}
            if "join" not in config["rally"]:
                config["rally"]["join"] = {}
            rally_join_config = config["rally"]["join"]

        # Create an embed to display the current configuration
        embed = discord.Embed(
            title="Rally Join Configuration",
            description="Configure monster targets for rally joins",
            color=discord.Color.blue()
        )

        # Add basic information
        embed.add_field(
            name="Basic Settings",
            value=f"**Enabled:** {'Yes' if rally_join_config.get('enabled', False) else 'No'}\n"
                  f"**Max Marches:** {rally_join_config.get('numMarch', 8)}\n"
                  f"**Level Based Troops:** {'Yes' if rally_join_config.get('level_based_troops', True) else 'No'}",
            inline=False
        )

        # Add monster targets information
        targets = rally_join_config.get("targets", [])
        if targets:
            monsters_info = []
            for target in targets:
                monster_code = target.get("monster_code", 0)
                monster_name = target.get("monster_name", "Unknown Monster")
                level_ranges = len(target.get("level_ranges", []))
                monsters_info.append(f"• **{monster_name}** (Code: {monster_code}, {level_ranges} level ranges)")

            embed.add_field(
                name="Configured Monsters",
                value="\n".join(monsters_info),
                inline=False
            )
        else:
            embed.add_field(
                name="Configured Monsters",
                value="No monsters configured yet. Use the buttons below to add monsters.",
                inline=False
            )

        # Log the monsters found for debugging
        logger.info(f"Found {len(targets)} monsters configured for rally join")
        for target in targets:
            monster_name = target.get("monster_name", "Unknown")
            monster_code = target.get("monster_code", 0)
            logger.info(f"  - {monster_name} (Code: {monster_code})")

        # Create a view with action buttons
        view = discord.ui.View(timeout=300)

        # Add monster button
        add_monster_button = discord.ui.Button(
            label="Add Monster",
            style=discord.ButtonStyle.primary,
            custom_id="add_monster"
        )
        view.add_item(add_monster_button)

        # Toggle enabled button
        toggle_button = discord.ui.Button(
            label=f"{'Disable' if rally_join_config.get('enabled', False) else 'Enable'} Rally Join",
            style=discord.ButtonStyle.danger if rally_join_config.get('enabled', False) else discord.ButtonStyle.success,
            custom_id="toggle_rally_join"
        )
        view.add_item(toggle_button)

        # Send the embed with view
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # Register button callbacks
        async def button_callback(button_interaction):
            custom_id = button_interaction.data["custom_id"]

            if custom_id == "add_monster":
                # Redirect to the monster configuration
                from lokbot.discord_commands import RallyConfigCommands
                rally_commands = RallyConfigCommands()
                await rally_commands.show_monster_config(button_interaction, "config.json", "rally.join")

            elif custom_id == "toggle_rally_join":
                # Toggle the enabled setting
                with open("config.json", "r") as f:
                    updated_config = json.load(f)

                if "rally" not in updated_config:
                    updated_config["rally"] = {}
                if "join" not in updated_config["rally"]:
                    updated_config["rally"]["join"] = {
                        "enabled": False,
                        "numMarch": 8,
                        "level_based_troops": True,
                        "targets": []
                    }

                updated_config["rally"]["join"]["enabled"] = not updated_config["rally"]["join"].get("enabled", False)

                with open("config.json", "w") as f:
                    json.dump(updated_config, f, indent=2)

                await button_interaction.response.send_message(
                    f"Rally Join is now {'enabled' if updated_config['rally']['join']['enabled'] else 'disabled'}.",
                    ephemeral=True
                )

        for item in view.children:
            item.callback = button_callback

    async def register_feature_callbacks(self, view, config):
        """Register callbacks for feature view buttons"""
        for item in view.children:
            if item.custom_id.startswith("simple_toggle_"):
                feature = item.custom_id.replace("simple_toggle_", "")
                item.callback = lambda i, f=feature: self.handle_toggle_feature(i, f)

            elif item.custom_id.startswith("simple_marches_"):
                feature = item.custom_id.replace("simple_marches_", "")
                item.callback = lambda i, f=feature: self.handle_marches_config(i, f)

            elif item.custom_id.startswith("simple_monsters_"):
                feature = item.custom_id.replace("simple_monsters_", "")
                item.callback = lambda i, f=feature: self.handle_monsters_config(i, f)

            elif item.custom_id == "simple_jobs":
                item.callback = lambda i: self.handle_jobs_config(i)

            elif item.custom_id == "simple_threads":
                item.callback = lambda i: self.handle_threads_config(i)

            elif item.custom_id == "simple_webhooks":
                item.callback = lambda i: self.handle_webhooks_config(i)

            elif item.custom_id == "back_to_overview":
                item.callback = lambda i: self.back_to_overview_callback(i, config)

            elif item.custom_id.startswith("help_"):
                feature_type = item.custom_id.replace("help_", "")
                item.callback = lambda i, ft=feature_type: self.help_callback(i, ft)

    async def back_to_overview_callback(self, interaction, config):
        """Handle back to overview button click"""
        try:
            new_embed = await ConfigHelper.create_config_overview_embed(config)
            new_view = await ConfigHelper.create_simplified_buttons()
            await interaction.response.edit_message(embed=new_embed, view=new_view)

            # Register callbacks for main menu
            for item in new_view.children:
                if item.custom_id == "simplified_game_settings":
                    item.callback = lambda i: self.feature_callback(i, "game", config)
                elif item.custom_id == "simplified_rally_join":
                    item.callback = lambda i: self.feature_callback(i, "rally_join", config)
                elif item.custom_id == "simplified_rally_start":
                    item.callback = lambda i: self.feature_callback(i, "rally_start", config)
                elif item.custom_id == "simplified_discord":
                    item.callback = lambda i: self.feature_callback(i, "discord", config)
        except Exception as e:
            logger.error(f"Error in back to overview callback: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def help_callback(self, interaction, feature_type):
        """Handle help button click"""
        try:
            help_embed = await ConfigHelper.create_help_embed(feature_type)
            await interaction.response.send_message(embed=help_embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in help callback: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def feature_callback(self, interaction, feature_type, config):
        """Handle feature button click"""
        try:
            # Use the currently selected config file
            config = ConfigHelper.load_config()  # This will now use current_config_file
            logger.info(f"Loading config for feature {feature_type} from {ConfigHelper.current_config_file}")

            # Generate embed and view with buttons reflecting current state
            embed, view = await ConfigHelper.create_simplified_feature_view(feature_type, config)
            await interaction.response.edit_message(embed=embed, view=view)

            # Register callbacks for the new view
            await self.register_feature_callbacks(view, config)

            # Log for debugging
            logger.info(f"Feature callback called for {feature_type}")

            # Register our toggle handlers for all toggleable features
            for child in view.children:
                if hasattr(child, 'custom_id') and child.custom_id and child.custom_id.startswith('simple_toggle_'):
                    feature = child.custom_id.replace('simple_toggle_', '')
                    child.callback = lambda i, f=feature: self.handle_toggle_feature(i, f)
                    logger.info(f"Registered toggle callback for feature {feature}")
                elif hasattr(child, 'custom_id') and child.custom_id and child.custom_id.startswith('simple_marches_'):
                    feature = child.custom_id.replace('simple_marches_', '')
                    child.callback = lambda i, f=feature: self.handle_marches_config(i, f)
                    logger.info(f"Registered marches callback for feature {feature}")
                elif hasattr(child, 'custom_id') and child.custom_id and child.custom_id.startswith('simple_monsters_'):
                    feature = child.custom_id.replace('simple_monsters_', '')
                    child.callback = lambda i, f=feature: self.handle_monsters_config(i, f)
                    logger.info(f"Registered monsters callback for feature {feature}")
        except Exception as e:
            logger.error(f"Error in feature callback: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def handle_threads_config(self, interaction):
        """Handle threads configuration"""
        try:
            # Redirect to the full threads configuration interface
            from lokbot.discord_commands import RallyConfigCommands
            rally_commands = RallyConfigCommands()

            # Use the existing threads configuration UI
            await rally_commands.show_threads_config(interaction)

        except Exception as e:
            logger.error(f"Error handling threads config: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def handle_webhooks_config(self, interaction):
        """Handle webhooks configuration"""
        try:
            # Redirect to the full webhooks configuration interface
            from lokbot.discord_commands import RallyConfigCommands
            rally_commands = RallyConfigCommands()

            # Use the existing webhooks configuration UI
            await rally_commands.show_webhooks_config(interaction)

        except Exception as e:
            logger.error(f"Error handling webhooks config: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def handle_object_scanning(self, interaction, config_file):
        """Handle object scanning configuration"""
        try:
            # Redirect to the full object scanning configuration interface
            from lokbot.discord_commands import RallyConfigCommands
            rally_commands = RallyConfigCommands()

            # Use the existing object scanning configuration UI
            await rally_commands.show_object_scanning_config(interaction)

        except Exception as e:
            logger.error(f"Error handling object scanning config: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def handle_view_settings(self, interaction):
        """Handle view all settings button click"""
        try:
            # Use the existing view_settings command from RallyConfigCommands
            from lokbot.discord_commands import RallyConfigCommands
            rally_commands = RallyConfigCommands()
            await rally_commands.view_settings(interaction)
        except Exception as e:
            logger.error(f"Error in view settings: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
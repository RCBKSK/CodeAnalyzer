import discord
from discord import app_commands
import json
import os
import logging
from lokbot.config_helper import ConfigHelper
from lokbot import troops_editor

logger = logging.getLogger(__name__)

class RallyConfigCommands(app_commands.Group):
    """Commands for managing rally configurations and game settings"""

    def __init__(self):
        super().__init__(name="game", description="Manage game configurations and settings")

    @app_commands.command(name="troops", description="Configure troops for different settings")
    async def troops_command(self, interaction: discord.Interaction):
        """Configure troops across different config files"""
        try:
            # List available config files
            config_files = [f for f in os.listdir() if f.endswith('.json')]
            
            # Create config selection view
            view = discord.ui.View(timeout=300)
            select = discord.ui.Select(
                placeholder="Select a config file",
                options=[discord.SelectOption(label=f, value=f) for f in config_files]
            )

            async def select_callback(select_interaction):
                selected_file = select_interaction.data["values"][0]
                ConfigHelper.set_current_config(selected_file)
                
                try:
                    # Load config
                    config = ConfigHelper.load_config()
                    
                    # Get troops data from different possible locations
                    troops_data = []
                    
                    # Check rally join/start configs
                    if 'rally' in config:
                        for rally_type in ['join', 'start']:
                            if rally_type in config['rally']:
                                for target in config['rally'][rally_type].get('targets', []):
                                    for level_range in target.get('level_ranges', []):
                                        troops_data.extend(level_range.get('troops', []))
                    
                    # Check normal monsters config
                    if 'main' in config and 'normal_monsters' in config['main']:
                        if 'common_troops' in config['main']['normal_monsters']:
                            troops_data.extend(config['main']['normal_monsters']['common_troops'])
                    
                    # Remove duplicates based on troop code
                    seen_codes = set()
                    unique_troops = []
                    for troop in troops_data:
                        code = troop.get('code')
                        if code not in seen_codes:
                            seen_codes.add(code)
                            unique_troops.append(troop)
                    
                    # Show troops editor
                    await troops_editor.show_troops_table(
                        interaction=select_interaction,
                        troops_data=unique_troops,
                        title=f"Troops Configuration - {selected_file}"
                    )
                
                except Exception as e:
                    await select_interaction.response.send_message(
                        f"Error loading troops from {selected_file}: {str(e)}",
                        ephemeral=True
                    )

            select.callback = select_callback
            view.add_item(select)
            
            await interaction.response.send_message(
                "Select a config file to edit troops:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            await interaction.response.send_message(
                f"Error: {str(e)}",
                ephemeral=True
            )

    # Internal method for use by /config setup
    async def view_settings(self, interaction: discord.Interaction):
        """Display the current configuration settings
        Internal method used by the unified /config setup interface.
        This method is not exposed as a slash command directly.
        """
        try:
            await interaction.response.defer(ephemeral=True)
            interaction_valid = True

            # Load the config file from selected config
            try:
                with open(ConfigHelper.current_config_file, "r") as f:
                    config = json.load(f)

                # Create embeds for different sections of the config
                main_embed = discord.Embed(
                    title="LokBot Configuration",
                    description="Current configuration settings",
                    color=discord.Color.blue()
                )

                # Main section - enabled jobs
                enabled_jobs = []
                for job in config.get('main', {}).get('jobs', []):
                    if job.get('enabled'):
                        job_name = job.get('name', 'Unknown')
                        interval = job.get('interval', {})
                        interval_str = f"{interval.get('start', 0)}-{interval.get('end', 0)}s"
                        enabled_jobs.append(f"• **{job_name}** ({interval_str})")

                if enabled_jobs:
                    main_embed.add_field(
                        name="Enabled Jobs",
                        value="\n".join(enabled_jobs),
                        inline=False
                    )
                else:
                    main_embed.add_field(
                        name="Enabled Jobs",
                        value="No jobs enabled",
                        inline=False
                    )

                # Enabled threads
                enabled_threads = []
                for thread in config.get('main', {}).get('threads', []):
                    if thread.get('enabled'):
                        thread_name = thread.get('name', 'Unknown')
                        kwargs = thread.get('kwargs', {})
                        kwargs_str = ", ".join([f"{k}={v}" for k, v in kwargs.items()]) if kwargs else ""
                        enabled_threads.append(f"• **{thread_name}** {kwargs_str}")

                if enabled_threads:
                    main_embed.add_field(
                        name="Enabled Threads",
                        value="\n".join(enabled_threads),
                        inline=False
                    )
                else:
                    main_embed.add_field(
                        name="Enabled Threads",
                        value="No threads enabled",
                        inline=False
                    )

                # Rally settings
                rally_embed = discord.Embed(
                    title="Rally Configuration",
                    description="Rally settings",
                    color=discord.Color.green()
                )

                # Rally start settings
                if config.get('rally_start', {}).get('enabled'):
                    rally_start = config.get('rally_start', {})
                    rally_embed.add_field(
                        name="Rally Start",
                        value=f"Enabled: Yes\nMax Marches: {rally_start.get('numMarch', 0)}\nLevel Based Troops: {rally_start.get('level_based_troops', False)}",
                        inline=False
                    )

                    # Rally targets
                    targets = rally_start.get('targets', [])
                    if targets:
                        targets_str = []
                        for target in targets:
                            from lokbot.rally_utils import get_monster_name_by_code
                            monster_code = target.get('monster_code', 0)
                            # Get monster name from config or fallback to utility function
                            monster_name = target.get('monster_name')
                            if not monster_name:
                                monster_name = get_monster_name_by_code(monster_code)
                            if not monster_name:
                                monster_name = f"Monster #{monster_code}"
                            level_ranges = len(target.get('level_ranges', []))
                            targets_str.append(f"• {monster_name} ({level_ranges} level ranges)")

                        rally_embed.add_field(
                            name="Rally Start Targets",
                            value="\n".join(targets_str),
                            inline=False
                        )
                else:
                    rally_embed.add_field(
                        name="Rally Start",
                        value="Enabled: No",
                        inline=False
                    )

                # Rally join settings
                if config.get('rally_join', {}).get('enabled'):
                    rally_join = config.get('rally_join', {})
                    rally_embed.add_field(
                        name="Rally Join",
                        value=f"Enabled: Yes\nMax Marches: {rally_join.get('numMarch', 0)}\nLevel Based Troops: {rally_join.get('level_based_troops', False)}",
                        inline=False
                    )

                    # Join targets summary
                    targets = rally_join.get('targets', [])
                    if targets:
                        targets_str = []
                        for target in targets:
                            from lokbot.rally_utils import get_monster_name_by_code
                            monster_code = target.get('monster_code', 0)
                            # Get monster name from config or fallback to utility function
                            monster_name = target.get('monster_name')
                            if not monster_name:
                                monster_name = get_monster_name_by_code(monster_code)
                            if not monster_name:
                                monster_name = f"Monster #{monster_code}"
                            level_ranges = len(target.get('level_ranges', []))
                            targets_str.append(f"• {monster_name} ({level_ranges} level ranges)")

                        rally_embed.add_field(
                            name="Rally Join Targets",
                            value="\n".join(targets_str),
                            inline=False
                        )
                else:
                    rally_embed.add_field(
                        name="Rally Join",
                        value="Enabled: No",
                        inline=False
                    )

                # Discord settings
                discord_embed = discord.Embed(
                    title="Discord Integration",
                    description="Discord webhook settings",
                    color=discord.Color.purple()
                )

                discord_config = config.get('discord', {})
                discord_enabled = discord_config.get('enabled', False)

                webhook_fields = [
                    ("Main Webhook", discord_config.get('webhook_url', '')),
                    ("Crystal Mine L1 Webhook", discord_config.get('crystal_mine_level1_webhook_url', '')),
                    ("Level 2+ Webhook", discord_config.get('level2plus_webhook_url', '')),
                    ("Level 3+ Webhook", discord_config.get('level3plus_webhook_url', '')),
                    ("Custom Webhook", discord_config.get('custom_webhook_url', '')),
                    ("Dragon Soul L2+ Webhook", discord_config.get('dragon_soul_level2plus_webhook_url', '')),
                    ("Occupied Resources Webhook", discord_config.get('occupied_resources_webhook_url', '')),
                    ("Rally Webhook", discord_config.get('rally_webhook_url', ''))
                ]

                for name, url in webhook_fields:
                    status = "✅ Set" if url else "❌ Not Set"
                    discord_embed.add_field(name=name, value=status, inline=True)

                # Send the embeds
                await interaction.followup.send(embed=main_embed, ephemeral=True)
                await interaction.followup.send(embed=rally_embed, ephemeral=True)
                await interaction.followup.send(embed=discord_embed, ephemeral=True)

            except FileNotFoundError:
                await interaction.followup.send("Config file not found. Please check if config.json exists.", ephemeral=True)
            except json.JSONDecodeError:
                await interaction.followup.send("Error parsing config.json. The file may be corrupted.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"Error reading config: {str(e)}", ephemeral=True)

        except Exception as e:
            logger.error(f"Error in view_settings command: {str(e)}")
            if interaction_valid:
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

    # Internal method for use by /config setup
    async def rally_config(self, interaction: discord.Interaction, config_type: str):
        """View and modify rally configuration
        Internal method used by the unified /config setup interface.
        This method is not exposed as a slash command directly.
        """
        logger.info(f"Rally config command executed by {interaction.user.name} for config type: {config_type}")

        # Check if user has administrator permission or the allowed role ID
        allowed_role_id = 508024195549102097
        has_permission = interaction.user.guild_permissions.administrator or any(role.id == allowed_role_id for role in interaction.user.roles)
        if not has_permission:
            logger.warning(f"User {interaction.user.name} attempted to use rally config without admin permissions")
            await interaction.response.send_message("You need administrator permission or the required role to use this command!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        logger.info(f"Interaction deferred, loading rally {config_type} configuration")

        # Determine which config file to load
        config_file = ConfigHelper.current_config_file # Use the currently selected config file
        # Use unified config structure - rally.join or rally.start instead of rally_join or rally_start
        config_section = "main" if config_type == "main" else f"rally.{config_type}"
        logger.info(f"Using config file: {config_file}, section: {config_section}")

        try:
            # Load the configuration
            with open(config_file, "r") as f:
                config = json.load(f)

            # Create the main embed for this configuration
            if config_type == "main":
                embed = discord.Embed(
                    title="Main Configuration",
                    description="Use the buttons below to modify settings",
                    color=discord.Color.blue()
                )

                # Add information about available jobs and threads
                main_config = config.get("main", {})

                # Jobs status
                jobs = main_config.get('jobs', [])
                enabled_jobs = sum(1 for job in jobs if job.get('enabled', False))
                total_jobs = len(jobs)

                # Threads status
                threads = main_config.get('threads', [])
                enabled_threads = sum(1 for thread in threads if thread.get('enabled', False))
                total_threads = len(threads)

                embed.add_field(
                    name="Status Overview",
                    value=f"**Enabled Jobs:** {enabled_jobs}/{total_jobs}\n"
                          f"**Enabled Threads:** {enabled_threads}/{total_threads}\n"
                          f"**Discord Integration:** {'Enabled' if config.get('discord', {}).get('enabled', False) else 'Disabled'}",
                    inline=False
                )
            else:
                embed = discord.Embed(
                    title=f"Rally {config_type.capitalize()} Configuration",
                    description="Use the buttons below to modify settings",
                    color=discord.Color.blue()
                )

                # Add basic rally settings - using unified config structure
                rally_section = config.get("rally", {}).get(config_type, {})
                embed.add_field(
                    name="Basic Settings",
                    value=f"**Enabled:** {'Yes' if rally_section.get('enabled', False) else 'No'}\n"
                          f"**Max Marches:** {rally_section.get('numMarch', 0)}\n"
                          f"**Level Based Troops:** {'Yes' if rally_section.get('level_based_troops', False) else 'No'}",
                    inline=False
                )

            # Add information about configured monsters for rally configs
            if config_type != "main":
                targets = rally_section.get('targets', [])
                if targets:
                    monsters_info = []
                    for target in targets:
                        monster_code = target.get('monster_code', 0)
                        # Get monster name from config or fallback to utility function
                        monster_name = target.get('monster_name', '')
                        if not monster_name:
                            from lokbot.rally_utils import get_monster_name_by_code
                            monster_name = get_monster_name_by_code(monster_code)
                            logger.info(f"Retrieved monster name for code {monster_code}: {monster_name}")

                        level_ranges = target.get('level_ranges', [])
                        level_range_info = []
                        for lr in level_ranges:
                            min_level = lr.get('min_level', 0)
                            max_level = lr.get('max_level', 0)
                            level_range_info.append(f"L{min_level}-{max_level}")

                        level_display = ", ".join(level_range_info) if level_range_info else "No levels"
                        monsters_info.append(f"• **{monster_name}** (Code: {monster_code}, {len(level_ranges)} ranges: {level_display})")
                        logger.info(f"Added monster to display: {monster_name} (Code: {monster_code})")

                    embed.add_field(
                        name="Configured Monsters",
                        value="\n".join(monsters_info) if monsters_info else "No monsters configured",
                        inline=False
                    )
                else:
                    logger.info("No monsters configured")
                    embed.add_field(
                        name="Configured Monsters",
                        value="No monsters configured",
                        inline=False
                    )

            # Add action buttons
            view = discord.ui.View(timeout=300)  # 5 minute timeout

            if config_type == "main":
                # Configure jobs button
                jobs_button = discord.ui.Button(
                    label="Configure Jobs",
                    style=discord.ButtonStyle.primary,
                    custom_id="configure_jobs"
                )
                view.add_item(jobs_button)

                # Configure threads button
                threads_button = discord.ui.Button(
                    label="Configure Threads",
                    style=discord.ButtonStyle.primary,
                    custom_id="configure_threads"
                )
                view.add_item(threads_button)

                # Discord webhooks button
                webhooks_button = discord.ui.Button(
                    label="Configure Discord Webhooks",
                    style=discord.ButtonStyle.primary,
                    custom_id="configure_webhooks"
                )
                view.add_item(webhooks_button)
            else:
                # Toggle enable button
                toggle_button = discord.ui.Button(
                    label=f"{'Disable' if rally_section.get('enabled', False) else 'Enable'} Rally {config_type.capitalize()}",
                    style=discord.ButtonStyle.danger if rally_section.get('enabled', False) else discord.ButtonStyle.success,
                    custom_id=f"rally_{config_type}_toggle"
                )
                view.add_item(toggle_button)

                # Edit marches button
                marches_button = discord.ui.Button(
                    label=f"Set Max Marches",
                    style=discord.ButtonStyle.primary,
                    custom_id=f"rally_{config_type}_marches"
                )
                view.add_item(marches_button)

                # Toggle level-based troops button
                level_troops_button = discord.ui.Button(
                    label=f"{'Disable' if rally_section.get('level_based_troops', False) else 'Enable'} Level-Based Troops",
                    style=discord.ButtonStyle.danger if rally_section.get('level_based_troops', False) else discord.ButtonStyle.success,
                    custom_id=f"rally_{config_type}_level_troops"
                )
                view.add_item(level_troops_button)

                # Monster button
                monster_button = discord.ui.Button(
                    label=f"Configure Monsters",
                    style=discord.ButtonStyle.primary,
                    custom_id=f"rally_{config_type}_monsters"
                )
                view.add_item(monster_button)

            # Send the configuration view
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

            # Setup button callbacks
            async def button_callback(button_interaction):
                if config_type == "main":
                    if button_interaction.data["custom_id"] == "configure_jobs":
                        await self.show_jobs_config(button_interaction)
                    elif button_interaction.data["custom_id"] == "configure_threads":
                        await self.show_threads_config(button_interaction)
                    elif button_interaction.data["custom_id"] == "configure_webhooks":
                        await self.show_webhooks_config(button_interaction)
                else:
                    if button_interaction.data["custom_id"] == f"rally_{config_type}_toggle":
                        await self.toggle_rally_config(button_interaction, config_file, config_section)
                    elif button_interaction.data["custom_id"] == f"rally_{config_type}_marches":
                        await self.show_march_modal(button_interaction, config_file, config_section)
                    elif button_interaction.data["custom_id"] == f"rally_{config_type}_monsters":
                        await self.show_monster_config(button_interaction, config_file, config_section)
                    elif button_interaction.data["custom_id"] == f"rally_{config_type}_level_troops":
                        await self.toggle_level_based_troops(button_interaction, config_file, config_section)

            # Register the callback
            view.on_timeout = lambda: view.clear_items()
            for item in view.children:
                item.callback = button_callback

        except Exception as e:
            logger.error(f"Error displaying rally config: {str(e)}")
            await interaction.followup.send(f"Error loading configuration: {str(e)}", ephemeral=True)

    async def toggle_rally_config(self, interaction, config_file, config_section):
        """Toggle the enabled state of a rally configuration"""
        try:
            # Load the configuration
            with open(config_file, "r") as f:
                config = json.load(f)

            # Parse the config section path (e.g., rally.join)
            parts = config_section.split('.')

            # Handle unified config structure
            if len(parts) == 2 and parts[0] == "rally":
                rally_type = parts[1]  # join or start

                # Ensure rally section exists
                if "rally" not in config:
                    config["rally"] = {}

                # Ensure the specific rally section exists
                if rally_type not in config["rally"]:
                    config["rally"][rally_type] = {"enabled": False, "numMarch": 6, "targets": [], "level_based_troops": False}

                # Toggle the enabled state
                config["rally"][rally_type]["enabled"] = not config["rally"][rally_type].get("enabled", False)
                new_state = config["rally"][rally_type]["enabled"]

                # Save the updated configuration
                with open(config_file, "w") as f:
                    json.dump(config, f, indent=2)

                await interaction.response.send_message(
                    f"Rally {rally_type.capitalize()} {'enabled' if new_state else 'disabled'}!",
                    ephemeral=True
                )
            else:
                # Legacy or non-rally config
                logger.warning(f"Unexpected config section format: {config_section}")
                await interaction.response.send_message(
                    f"Error: Unexpected configuration format. Please use the new unified configuration structure.",
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error toggling rally config: {str(e)}")
            await interaction.response.send_message(f"Error updating configuration: {str(e)}", ephemeral=True)

    async def show_march_modal(self, interaction, config_file, config_section):
        """Show a modal to set the maximum number of marches"""
        try:
            # Load current value
            with open(config_file, "r") as f:
                config = json.load(f)

            if config_section not in config:
                config[config_section] = {"enabled": False, "numMarch": 6, "targets": [], "level_based_troops": False}

            current_marches = config[config_section].get("numMarch", 6)

            # Create the modal
            modal = discord.ui.Modal(title=f"Set Max Rally Marches")

            # Add the input field
            marches_input = discord.ui.TextInput(
                label="Number of Marches (1-10)",
                placeholder="Enter a number between 1 and 10",
                default=str(current_marches),
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
                    with open(config_file, "r") as f:
                        config = json.load(f)

                    if config_section not in config:
                        config[config_section] = {"enabled": False, "numMarch": 6, "targets": [], "level_based_troops": False}

                    config[config_section]["numMarch"] = new_marches

                    # Save the updated configuration
                    with open(config_file, "w") as f:
                        json.dump(config, f, indent=2)

                    await modal_interaction.response.send_message(
                        f"Maximum marches updated to {new_marches}!",
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
            logger.error(f"Error showing march modal: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def show_monster_config(self, interaction, config_file, config_section):
        """Show a dropdown to select which monster to configure"""
        try:
            logger.info(f"Opening monster configuration UI for {config_section}")
            # Always use currently selected config file
            config_file = ConfigHelper.current_config_file
            logger.info(f"Loading monster config from: {config_file}")

            # Load the configuration
            with open(config_file, "r") as f:
                config = json.load(f)

            config_parts = config_section.split('.')
            if len(config_parts) == 2 and config_parts[0] in config and config_parts[1] in config[config_parts[0]]:
                current_config = config[config_parts[0]][config_parts[1]]
            else:
                current_config = {"enabled": False, "numMarch": 8, "targets": []}

            # Get the list of configured monsters
            targets = current_config.get("targets", [])
            logger.info(f"Found {len(targets)} configured monster targets")

            # Create the monster selection dropdown
            view = discord.ui.View(timeout=300)

            # Monster selection dropdown
            monster_select = discord.ui.Select(
                placeholder="Select a monster to configure",
                custom_id="monster_select",
                min_values=1,
                max_values=1
            )

            # Add options for existing monsters
            monster_codes = {}
            for target in targets:
                monster_code = target.get("monster_code", 0)
                monster_name = target.get("monster_name", "")
                logger.info(f"Processing monster: code={monster_code}, name={monster_name}")

                if not monster_name:
                    from lokbot.rally_utils import get_monster_name_by_code
                    monster_name = get_monster_name_by_code(monster_code)
                    logger.info(f"Retrieved monster name from utility: {monster_name}")

                if not monster_name:
                    monster_name = f"Monster #{monster_code}"
                    logger.warning(f"Could not determine name for monster code {monster_code}")

                monster_select.add_option(label=monster_name, value=str(monster_code))
                monster_codes[str(monster_code)] = monster_name
                logger.info(f"Added monster option: {monster_name} (code: {monster_code})")

            # Add option to add a new monster
            monster_select.add_option(label="Add New Monster", value="new")

            # Add predefined monster options for easy selection
            predefined_monsters = [
                (20200205, "Magdar"),
                (20200202, "Green Dragon"),
                (20200203, "Red Dragon"),
                (20200204, "Gold Dragon"),
                (20200301, "Spartoi"),
                (20200206, "Gargantua"),
                (20200207, "Pantagruel")
            ]

            # Add predefined monster button
            predefined_button = discord.ui.Button(
                label="Select Predefined Monster",
                style=discord.ButtonStyle.success,
                custom_id="predefined_monster"
            )

            async def predefined_button_callback(button_interaction):
                # Create a new view with a dropdown of predefined monsters
                predefined_view = discord.ui.View(timeout=300)
                predefined_select = discord.ui.Select(
                    placeholder="Select a predefined monster",
                    custom_id="predefined_select"
                )

                for code, name in predefined_monsters:
                    if str(code) not in monster_codes:
                        predefined_select.add_option(label=name, value=f"{code}_{name}")

                if not predefined_select.options:
                    await button_interaction.response.send_message(
                        "All predefined monsters are already configured!",
                        ephemeral=True
                    )
                    return

                async def predefined_select_callback(select_interaction):
                    selected_value = select_interaction.data["values"][0]
                    code_str, name = selected_value.split("_", 1)
                    code = int(code_str)

                    # Add the monster to the configuration
                    with open(config_file, "r") as f:
                        updated_config = json.load(f)

                    config_parts = config_section.split('.')
                    if len(config_parts) == 2 and config_parts[0] in updated_config and config_parts[1] in updated_config[config_parts[0]]:
                        current_config = updated_config[config_parts[0]][config_parts[1]]
                    else:
                        current_config = {"enabled": False, "numMarch": 8, "targets": []}


                    # Create a new target
                    new_target = {
                        "monster_code": code,
                        "monster_name": name,
                        "level_ranges": [
                            {
                                "min_level": 1,
                                "max_level": 6,
                                "troops": [
                                    {
                                        "code": 50100305,
                                        "name": "Dragoon (Tier 5 Cavalry)",
                                        "min_amount": 40000,
                                        "max_amount": 60000
                                    },
                                    {
                                        "code": 50100306,
                                        "name": "Marauder (Tier 6 Cavalry)",
                                        "min_amount": 20000,
                                        "max_amount": 30000
                                    }
                                ]
                            },
                            {
                                "min_level": 7,
                                "max_level": 10,
                                "troops": [
                                    {
                                        "code": 50100305,
                                        "name": "Dragoon (Tier 5 Cavalry)",
                                        "min_amount": 80000,
                                        "max_amount": 100000
                                    },
                                    {
                                        "code": 50100306,
                                        "name": "Marauder (Tier 6 Cavalry)",
                                        "min_amount": 40000,
                                        "max_amount": 50000
                                    }
                                ]
                            }
                        ]
                    }

                    # For rally_start add rally_time and message
                    if config_section == "rally.start":
                        for level_range in new_target["level_ranges"]:
                            level_range["rally_time"] = 10
                            message_prefix = "High Level " if level_range["min_level"] >= 7 else ""
                            level_range["message"] = f"{message_prefix}{name} Rally"

                    current_config["targets"].append(new_target)

                    # Save the updated configuration
                    current_file = ConfigHelper.current_config_file
                    with open(current_file, "w") as f:
                        json.dump(updated_config, f, indent=2)
                    logger.info(f"Saved monster config to: {current_file}")

                    await select_interaction.response.send_message(
                        f"Added {name} to the configuration!",
                        ephemeral=True
                    )

                predefined_select.callback = predefined_select_callback
                predefined_view.add_item(predefined_select)
                await button_interaction.response.send_message(
                    "Select a predefined monster to add:",
                    view=predefined_view,
                    ephemeral=True
                )

            predefined_button.callback = predefined_button_callback

            # Extract config type from section path
            config_parts = config_section.split('.')
            config_type = config_parts[1] if len(config_parts) == 2 else config_parts[0]

            async def monster_select_callback(select_interaction):
                selected_value = select_interaction.data["values"][0]

                if selected_value == "new":
                    # Show a modal to enter a new monster code and name
                    modal = discord.ui.Modal(title="Add New Monster")

                    code_input = discord.ui.TextInput(
                        label="Monster Code",
                        placeholder="Enter monster code (e.g., 20200205)",
                        required=True
                    )
                    modal.add_item(code_input)

                    name_input = discord.ui.TextInput(
                        label="Monster Name",
                        placeholder="Enter monster name (e.g., Magdar)",
                        required=True
                    )
                    modal.add_item(name_input)

                    async def modal_callback(modal_interaction):
                        try:
                            new_code = int(code_input.value)
                            new_name = name_input.value

                            # Add the monster to the configuration
                            with open(config_file, "r") as f:
                                updated_config = json.load(f)

                            config_parts = config_section.split('.')
                            if len(config_parts) == 2 and config_parts[0] in updated_config and config_parts[1] in updated_config[config_parts[0]]:
                                current_config = updated_config[config_parts[0]][config_parts[1]]
                            else:
                                current_config = {"enabled": False, "numMarch": 8, "targets": []}


                            # Check if the monster already exists
                            exists = False
                            for target in current_config.get("targets", []):
                                if target.get("monster_code") == new_code:
                                    exists = True
                                    break

                            if exists:
                                await modal_interaction.response.send_message(
                                    f"Monster with code {new_code} already exists in the configuration.",
                                    ephemeral=True
                                )
                                return

                            # Create a new target
                            new_target = {
                                "monster_code": new_code,
                                "monster_name": new_name,
                                "level_ranges": [
                                    {
                                        "min_level": 1,
                                        "max_level": 6,"troops": [
                                            {
                                                "code":50100305,
                                                "name": "Dragoon (Tier 5 Cavalry)",
                                                "minamount": 40000,
                                                "max_amount":60000
                                            },
                                            {
                                                "code": 50100306,
                                                "name": "Marauder (Tier 6 Cavalry)",
                                                "min_amount": 20000,
                                                "max_amount": 30000
                                            }
                                        ]
                                    },     {
                                        "min_level": 7,
                                        "max_level": 10,
                                        "troops": [
                                            {
                                                "code": 50100305,
                                                "name": "Dragoon (Tier 5 Cavalry)",
                                                "min_amount": 80000,
                                                "max_amount": 100000
                                            },
                                            {
                                                "code": 50100306,
                                                "name": "Marauder (Tier 6 Cavalry)",
                                                "min_amount": 40000,
                                                "max_amount": 50000
                                            }
                                        ]
                                    }
                                ]
                            }

                            # For rally_start add rally_time and message
                            if config_section == "rally.start":
                                for level_range in new_target["level_ranges"]:
                                    level_range["rally_time"] = 10
                                    message_prefix = "High Level " if level_range["min_level"] >= 7 else ""
                                    level_range["message"] = f"{message_prefix}{new_name} Rally"

                            current_config["targets"].append(new_target)

                            # Save the updated configuration
                            current_file = ConfigHelper.current_config_file
                            with open(current_file, "w") as f:
                                json.dump(updated_config, f, indent=2)
                            logger.info(f"Saved monster config to: {current_file}")

                            await modal_interaction.response.send_message(
                                f"Added {new_name} (Code: {new_code}) to the configuration!",
                                ephemeral=True
                            )

                        except ValueError:
                            await modal_interaction.response.send_message(
                                "Invalid monster code. Please enter a valid number.",
                                ephemeral=True
                            )
                        except Exception as e:
                            logger.error(f"Error adding monster: {str(e)}")
                            await modal_interaction.response.send_message(
                                f"Error adding monster: {str(e)}",
                                ephemeral=True
                            )

                    modal.on_submit = modal_callback
                    await select_interaction.response.send_modal(modal)

                else:
                    # Show configuration for the selected monster
                    monster_code = int(selected_value)

                    # Find the target in the configuration
                    target = None
                    rally_config = config.get('rally', {}).get(config_type, {})
                    for t in rally_config.get('targets', []):
                        if t.get('monster_code') == monster_code:
                            target = t
                            break

                    if not target:
                        await select_interaction.response.send_message(
                            f"Error: Monster not found in configuration.",
                            ephemeral=True
                        )
                        return

                    # Create an embed for the monster configuration
                    monster_name = target.get("monster_name", f"Monster #{monster_code}")
                    embed = discord.Embed(
                        title=f"{monster_name} Configuration",
                        description=f"Monster Code: {monster_code}",
                        color=discord.Color.green()
                    )

                    # Add level ranges
                    level_ranges = target.get("level_ranges", [])
                    for i, level_range in enumerate(level_ranges):
                        min_level = level_range.get("min_level", 0)
                        max_level = level_range.get("max_level", 0)

                        troops_info = []
                        for troop in level_range.get("troops", []):
                            troop_name = troop.get("name", f"Troop #{troop.get('code', 0)}")
                            min_amount = troop.get("min_amount", 0)
                            max_amount = troop.get("max_amount", 0)
                            troops_info.append(f"• {troop_name}: {min_amount}-{max_amount}")

                        # Add rally time and message for rally_start
                        if config_section == "rally.start":
                            rally_time = level_range.get("rally_time", 0)
                            message = level_range.get("message", "")

                            embed.add_field(
                                name=f"Level Range {i+1}: Levels {min_level}-{max_level}",
                                value=f"**Rally Time:** {rally_time} minutes\n"
                                      f"**Message:** {message}\n"
                                      f"**Troops:**\n" + ("\n".join(troops_info) if troops_info else "No troops configured"),
                                inline=False
                            )
                        else:
                            embed.add_field(
                                name=f"Level Range {i+1}: Levels {min_level}-{max_level}",
                                value="**Troops:**\n" + ("\n".join(troops_info) if troops_info else "No troops configured"),
                                inline=False
                            )

                    # Create action buttons for this monster
                    monster_view = discord.ui.View(timeout=300)

                    # Edit level range button
                    edit_level_button = discord.ui.Button(
                        label="Edit Level Range",
                        style=discord.ButtonStyle.primary,
                        custom_id=f"edit_level_{monster_code}"
                    )
                    monster_view.add_item(edit_level_button)

                    # Edit troops button
                    edit_troops_button = discord.ui.Button(
                        label="Edit Troops",
                        style=discord.ButtonStyle.primary,
                        custom_id=f"edit_troops_{monster_code}"
                    )
                    monster_view.add_item(edit_troops_button)

                    # Delete monster button
                    delete_button = discord.ui.Button(
                        label="Delete Monster",
                        style=discord.ButtonStyle.danger,
                        custom_id=f"delete_{monster_code}"
                    )
                    monster_view.add_item(delete_button)

                    async def monster_button_callback(button_interaction):
                        custom_id = button_interaction.data["custom_id"]

                        if custom_id.startswith("edit_level_"):
                            await self.edit_level_ranges(button_interaction, config_file, config_section, monster_code)
                        elif custom_id.startswith("edit_troops_"):
                            await self.edit_troops(button_interaction, config_file, config_section, monster_code)
                        elif custom_id.startswith("delete_"):
                            await self.delete_monster(button_interaction, config_file, config_section, monster_code)

                    for item in monster_view.children:
                        item.callback = monster_button_callback

                    await select_interaction.response.send_message(embed=embed, view=monster_view, ephemeral=True)

            monster_select.callback = monster_select_callback
            view.add_item(monster_select)
            view.add_item(predefined_button)

            await interaction.response.send_message(
                "Select a monster to configure or add a new one:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error showing monster config: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def edit_level_ranges(self, interaction, config_file, config_section, monster_code):
        """Show a modal to edit level ranges for a monster"""
        try:
            # Load the configuration
            with open(config_file, "r") as f:
                config = json.load(f)

            # Extract config type from section path
            config_parts = config_section.split('.')
            config_type = config_parts[1] if len(config_parts) == 2 else config_parts[0]

            # Find the target in the configuration
            target = None
            rally_config = config.get('rally', {}).get(config_type, {})
            for t in rally_config.get('targets', []):
                if t.get('monster_code') == monster_code:
                    target = t
                    break

            if not target:
                await interaction.response.send_message(
                    f"Error: Monster not found in configuration.",
                    ephemeral=True
                )
                return

            # Create a dropdown to select which level range to edit
            level_ranges = target.get("level_ranges", [])

            view = discord.ui.View(timeout=300)
            level_select = discord.ui.Select(
                placeholder="Select a level range to edit",
                custom_id="level_select"
            )

            # Add options for existing level ranges
            for i, level_range in enumerate(level_ranges):
                min_level = level_range.get("min_level", 0)
                max_level = level_range.get("max_level", 0)
                level_select.add_option(
                    label=f"Levels {min_level}-{max_level}",
                    value=str(i)
                )

            # Add option to add a new level range
            level_select.add_option(label="Add New Level Range", value="new")

            async def level_select_callback(select_interaction):
                selected_value = select_interaction.data["values"][0]

                if selected_value == "new":
                    # Show a modal to add a new level range
                    modal = discord.ui.Modal(title="Add New Level Range")

                    min_level_input = discord.ui.TextInput(
                        label="Minimum Level",
                        placeholder="Enter minimum level (e.g., 1)",
                        required=True
                    )
                    modal.add_item(min_level_input)

                    max_level_input = discord.ui.TextInput(
                        label="Maximum Level",
                        placeholder="Enter maximum level (e.g., 6)",
                        required=True
                    )
                    modal.add_item(max_level_input)

                    # Add rally time and message inputs for rally_start
                    if config_section == "rally.start":
                        rally_time_input = discord.ui.TextInput(
                            label="Rally Time (minutes)",
                            placeholder="Enter rally time in minutes (e.g., 10)",
                            default="10",
                            required=True
                        )
                        modal.add_item(rally_time_input)

                        message_input = discord.ui.TextInput(
                            label="Rally Message",
                            placeholder="Enter rally message (e.g., Magdar Rally)",
                            default=f"{target.get('monster_name', 'Monster')} Rally",
                            required=True
                        )
                        modal.add_item(message_input)

                    async def modal_callback(modal_interaction):
                        try:
                            min_level = int(min_level_input.value)
                            max_level = int(max_level_input.value)

                            if min_level < 1 or min_level > 10 or max_level < 1 or max_level > 10 or min_level > max_level:
                                await modal_interaction.response.send_message(
                                    "Invalid level range. Levels must be between 1 and 10, and minimum level must be less than or equal to maximum level.",
                                    ephemeral=True
                                )
                                return

                            # Create a new level range
                            new_level_range = {
                                "min_level": min_level,
                                "max_level": max_level,
                                "troops": [
                                    {
                                        "code": 50100305,
                                        "name": "Dragoon (Tier 5 Cavalry)",
                                        "min_amount": 40000,
                                        "max_amount": 60000
                                    },
                                    {
                                        "code": 50100306,
                                        "name": "Marauder (Tier 6 Cavalry)",
                                        "min_amount": 20000,
                                        "max_amount": 30000
                                    }
                                ]
                            }

                            # Add rally time and message for rally_start
                            if config_section == "rally.start":
                                rally_time = int(rally_time_input.value)
                                message = message_input.value

                                new_level_range["rally_time"] = rally_time
                                new_level_range["message"] = message

                            # Update the configuration
                            with open(config_file, "r") as f:
                                updated_config = json.load(f)

                            # Find the target again
                            rally_config = updated_config.get('rally', {}).get(config_type, {})
                            for t in rally_config.get('targets', []):
                                if t.get('monster_code') == monster_code:
                                    t.get("level_ranges", []).append(new_level_range)
                                    break

                            # Save the updated configuration
                            with open(config_file, "w") as f:
                                json.dump(updated_config, f, indent=2)

                            await modal_interaction.response.send_message(
                                f"Added new level range {min_level}-{max_level}!",
                                ephemeral=True
                            )

                        except ValueError:
                            await modal_interaction.response.send_message(
                                "Invalid input. Please enter valid numbers.",
                                ephemeral=True
                            )
                        except Exception as e:
                            logger.error(f"Error adding level range: {str(e)}")
                            await modal_interaction.response.send_message(
                                f"Error adding level range: {str(e)}",
                                ephemeral=True
                            )

                    modal.on_submit = modal_callback
                    await select_interaction.response.send_modal(modal)

                else:
                    # Show a modal to edit the selected level range
                    index = int(selected_value)
                    level_range = level_ranges[index]

                    modal = discord.ui.Modal(title="Edit Level Range")

                    min_level_input = discord.ui.TextInput(
                        label="Minimum Level",
                        placeholder="Enter minimum level (e.g., 1)",
                        default=str(level_range.get("min_level", 1)),
                        required=True
                    )
                    modal.add_item(min_level_input)

                    max_level_input = discord.ui.TextInput(
                        label="Maximum Level",
                        placeholder="Enter maximum level (e.g., 6)",
                        default=str(level_range.get("max_level", 6)),
                        required=True
                    )
                    modal.add_item(max_level_input)

                    # Add rally time and message inputs for rally_start
                    if config_section == "rally.start":
                        rally_time_input = discord.ui.TextInput(
                            label="Rally Time (minutes)",
                            placeholder="Enter rally time in minutes (e.g., 10)",
                            default=str(level_range.get("rally_time", 10)),
                            required=True
                        )
                        modal.add_item(rally_time_input)

                        message_input = discord.ui.TextInput(
                            label="Rally Message",
                            placeholder="Enter rally message (e.g., Magdar Rally)",
                            default=level_range.get("message", f"{target.get('monster_name', 'Monster')} Rally"),
                            required=True
                        )
                        modal.add_item(message_input)

                    async def modal_callback(modal_interaction):
                        try:
                            min_level = int(min_level_input.value)
                            max_level = int(max_level_input.value)

                            if min_level < 1 or min_level > 10 or max_level < 1 or max_level > 10 or min_level > max_level:
                                await modal_interaction.response.send_message(
                                    "Invalid level range. Levels must be between 1 and 10, and minimum level must be less than or equal to maximum level.",
                                    ephemeral=True
                                )
                                return

                            # Update the configuration
                            with open(config_file, "r") as f:
                                updated_config = json.load(f)

                            # Find the target and level range
                            rally_config = updated_config.get('rally', {}).get(config_type, {})
                            for t in rally_config.get('targets', []):
                                if t.get('monster_code') == monster_code:
                                    level_ranges = t.get("level_ranges", [])
                                    if index < len(level_ranges):
                                        level_ranges[index]["min_level"] = min_level
                                        level_ranges[index]["max_level"] = max_level

                                        # Update rally time and message for rally_start
                                        if config_section == "rally.start":
                                            rally_time = int(rally_time_input.value)
                                            message = message_input.value

                                            level_ranges[index]["rally_time"] = rally_time
                                            level_ranges[index]["message"] = message
                                    break

                            # Save the updated configuration
                            with open(config_file, "w") as f:
                                json.dump(updated_config, f, indent=2)

                            await modal_interaction.response.send_message(
                                f"Updated level range to {min_level}-{max_level}!",
                                ephemeral=True
                            )

                        except ValueError:
                            await modal_interaction.response.send_message(
                                "Invalid input. Please enter valid numbers.",
                                ephemeral=True
                            )
                        except Exception as e:
                            logger.error(f"Error updating level range: {str(e)}")
                            await modal_interaction.response.send_message(
                                f"Error updating level range: {str(e)}",
                                ephemeral=True
                            )

                    modal.on_submit = modal_callback
                    await select_interaction.response.send_modal(modal)

            level_select.callback = level_select_callback
            view.add_item(level_select)

            # Add a button to delete a level range
            delete_button = discord.ui.Button(
                label="Delete Level Range",
                style=discord.ButtonStyle.danger,
                custom_id="delete_level"
            )

            async def delete_button_callback(button_interaction):
                # Create a dropdown to select which level range to delete
                delete_view = discord.ui.View(timeout=300)
                delete_select = discord.ui.Select(
                    placeholder="Select a level range to delete",
                    custom_id="delete_level_select"
                )

                # Add options for existing level ranges
                for i, level_range in enumerate(level_ranges):
                    min_level = level_range.get("min_level", 0)
                    max_level = level_range.get("max_level", 0)
                    delete_select.add_option(
                        label=f"Levels {min_level}-{max_level}",
                        value=str(i)
                    )

                async def delete_select_callback(select_interaction):
                    selected_value = select_interaction.data["values"][0]
                    index = int(selected_value)

                    # Update the configuration
                    with open(config_file, "r") as f:
                        updated_config = json.load(f)

                    # Find the target and delete the level range
                    rally_config = updated_config.get('rally', {}).get(config_type, {})
                    for t in rally_config.get('targets', []):
                        if t.get('monster_code') == monster_code:
                            level_ranges = t.get("level_ranges", [])
                            if index < len(level_ranges):
                                deleted_range = level_ranges.pop(index)
                                min_level = deleted_range.get("min_level", 0)
                                max_level = deleted_range.get("max_level", 0)
                            break

                    # Save the updated configuration
                    with open(config_file, "w") as f:
                        json.dump(updated_config, f, indent=2)

                    await select_interaction.response.send_message(
                        f"Deleted level range {min_level}-{max_level}!",
                        ephemeral=True
                    )

                delete_select.callback = delete_select_callback
                delete_view.add_item(delete_select)

                await button_interaction.response.send_message(
                    "Select a level range to delete:",
                    view=delete_view,
                    ephemeral=True
                )

            delete_button.callback = delete_button_callback
            view.add_item(delete_button)

            await interaction.response.send_message(
                "Select a level range to edit or add a new one:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error editing level ranges: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def edit_troops(self, interaction, config_file, config_section, monster_code):
        """Show a modal to edit troops for a monster level range"""
        try:
            # Load the configuration
            with open(config_file, "r") as f:
                config = json.load(f)

            # Extract config type from section path
            config_parts = config_section.split('.')
            config_type = config_parts[1] if len(config_parts) == 2 else config_parts[0]

            # Find the target in the configuration
            target = None
            rally_config = config.get('rally', {}).get(config_type, {})
            for t in rally_config.get('targets', []):
                if t.get('monster_code') == monster_code:
                    target = t
                    break

            if not target:
                await interaction.response.send_message(
                    f"Error: Monster not found in configuration.",
                    ephemeral=True
                )
                return

            # Create a dropdown to select which level range to edit troops for
            level_ranges = target.get("level_ranges", [])

            view = discord.ui.View(timeout=300)
            level_select = discord.ui.Select(
                placeholder="Select a level range to edit troops",
                custom_id="level_select"
            )

            # Add options for existing level ranges
            for i, level_range in enumerate(level_ranges):
                min_level = level_range.get("min_level", 0)
                max_level = level_range.get("max_level", 0)
                level_select.add_option(
                    label=f"Levels {min_level}-{max_level}",
                    value=str(i)
                )

            async def level_select_callback(select_interaction):
                selected_value = select_interaction.data["values"][0]
                index = int(selected_value)

                if index >= len(level_ranges):
                    await select_interaction.response.send_message(
                        f"Error: Invalid level range selection.",
                        ephemeral=True
                    )
                    return

                level_range = level_ranges[index]
                min_level = level_range.get("min_level", 0)
                max_level = level_range.get("max_level", 0)

                # Show a view with buttons for different troop types
                troops_view = discord.ui.View(timeout=300)

                # Predefined troop types with more options
                troop_types = [
                    (50100303, "Heavy Cavalry (T3 Cavalry)"),
                    (50100304, "Iron Cavalry (T4 Cavalry)"),
                    (50100305, "Dragoon (T5 Cavalry)"),
                    (50100306, "Marauder (T6 Cavalry)")
                ]

                # Create a select menu for troops instead of buttons
                troop_select = discord.ui.Select(
                    placeholder="Select troop type to edit",
                    options=[
                        discord.SelectOption(label=name, value=str(code))
                        for code, name in troop_types
                    ]
                )
                troops_view.add_item(troop_select)

                async def troop_select_callback(select_interaction):
                    selected_troop_code = int(select_interaction.data["values"][0])

                    # Find the troop name
                    selected_troop_name = next((name for code, name in troop_types if code == selected_troop_code), f"Troop #{selected_troop_code}")

                    # Find if the troop is already configured
                    troop = None
                    for t in level_range.get("troops", []):
                        if t.get("code") == selected_troop_code:
                            troop = t
                            break

                    # Create a modal to edit the troop
                    modal = discord.ui.Modal(title=f"Edit {selected_troop_name}")

                    min_amount_input = discord.ui.TextInput(
                        label="Minimum Amount",
                        placeholder="Enter minimum amount (e.g., 40000)",
                        default=str(troop.get("min_amount", 0)) if troop else "0",
                        required=True
                    )
                    modal.add_item(min_amount_input)

                    max_amount_input = discord.ui.TextInput(
                        label="Maximum Amount",
                        placeholder="Enter maximum amount (e.g., 60000)",
                        default=str(troop.get("max_amount", 0)) if troop else "0",
                        required=True
                    )
                    modal.add_item(max_amount_input)

                    async def modal_callback(modal_interaction):
                        try:
                            min_amount = int(min_amount_input.value)
                            max_amount = int(max_amount_input.value)

                            if min_amount < 0 or max_amount < 0:
                                await modal_interaction.response.send_message(
                                    "Invalid amounts. Amounts must be non-negative.",
                                    ephemeral=True
                                )
                                return

                            # Update the configuration
                            with open(config_file, "r") as f:
                                updated_config = json.load(f)

                            # Find the target and level range
                            rally_config = updated_config.get('rally', {}).get(config_type, {})
                            for t in rally_config.get('targets', []):
                                if t.get('monster_code') == monster_code:
                                    level_ranges = t.get("level_ranges", [])
                                    if index < len(level_ranges):
                                        troops = level_ranges[index].get("troops", [])

                                        # Find if the troop is already configured
                                        troop_found = False
                                        for i, troop in enumerate(troops):
                                            if troop.get("code") == selected_troop_code:
                                                # Update existing troop
                                                troops[i]["min_amount"] = min_amount
                                                troops[i]["max_amount"] = max_amount
                                                troop_found = True
                                                break

                                        if not troop_found:
                                            # Add new troop
                                            troops.append({
                                                "code": selected_troop_code,
                                                "name": selected_troop_name,
                                                "min_amount": min_amount,
                                                "max_amount": max_amount
                                            })

                                        # Set updated troops
                                        level_ranges[index]["troops"] = troops
                                    # Save the updated configuration
                            with open(config_file, "w") as f:
                                json.dump(updated_config, f, indent=2)

                            await modal_interaction.response.send_message(
                                f"Updated {selected_troop_name} settings for levels {min_level}-{max_level}!",
                                ephemeral=True
                            )

                        except ValueError:
                            await modal_interaction.response.send_message(
                                "Invalid input. Please enter valid numbers.",
                                ephemeral=True
                            )
                        except Exception as e:
                            logger.error(f"Error updating troop: {str(e)}")
                            await modal_interaction.response.send_message(
                                f"Error updating troop: {str(e)}",
                                ephemeral=True
                            )

                    modal.on_submit = modal_callback
                    await select_interaction.response.send_modal(modal)

                troop_select.callback = troop_select_callback
                await select_interaction.response.send_message(
                    f"Edit troops for levels {min_level}-{max_level}:",
                    view=troops_view,
                    ephemeral=True
                )


            level_select.callback = level_select_callback
            view.add_item(level_select)

            # Add a button to remove a level range
            delete_button = discord.ui.Button(
                label="Delete Level Range",
                style=discord.ButtonStyle.danger,
                custom_id="delete_level"
            )

            async def delete_button_callback(button_interaction):
                # Create a dropdown to select which level range to delete
                delete_view = discord.ui.View(timeout=300)
                delete_select = discord.ui.Select(
                    placeholder="Select a level range to delete",
                    custom_id="delete_level_select"
                )

                # Add options for existing level ranges
                for i, level_range in enumerate(level_ranges):
                    min_level = level_range.get("min_level", 0)
                    max_level = level_range.get("max_level", 0)
                    delete_select.add_option(
                        label=f"Levels {min_level}-{max_level}",
                        value=str(i)
                    )

                async def delete_select_callback(select_interaction):
                    selected_value = select_interaction.data["values"][0]
                    index = int(selected_value)

                    # Update the configuration
                    with open(config_file, "r") as f:
                        updated_config = json.load(f)

                    # Find the target and delete the level range
                    rally_config = updated_config.get('rally', {}).get(config_type, {})
                    for t in rally_config.get('targets', []):
                        if t.get('monster_code') == monster_code:
                            level_ranges = t.get("level_ranges", [])
                            if index < len(level_ranges):
                                deleted_range = level_ranges.pop(index)
                                min_level = deleted_range.get("min_level", 0)
                                max_level = deleted_range.get("max_level", 0)
                            break

                    # Save the updated configuration
                    with open(config_file, "w") as f:
                        json.dump(updated_config, f, indent=2)

                    await select_interaction.response.send_message(
                        f"Deleted level range {min_level}-{max_level}!",
                        ephemeral=True
                    )

                delete_select.callback = delete_select_callback
                delete_view.add_item(delete_select)

                await button_interaction.response.send_message(
                    "Select a level range to delete:",
                    view=delete_view,
                    ephemeral=True
                )

            delete_button.callback = delete_button_callback
            view.add_item(delete_button)

            await interaction.response.send_message(
                "Select a level range to edit troops:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error editing troops: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def delete_monster(self, interaction, config_file, config_section, monster_code):
        """Delete a monster from the configuration"""
        try:
            # Load the configuration
            with open(config_file, "r") as f:
                config = json.load(f)

            # Find the target in the configuration
            target = None
            rally_config = config.get('rally', {}).get(config_type, {})
            for t in rally_config.get('targets', []):
                if t.get('monster_code') == monster_code:
                    target = t
                    break

            if not target:
                await interaction.response.send_message(
                    f"Error: Monster not found in configuration.",
                    ephemeral=True
                )
                return

            monster_name = target.get("monster_name", f"Monster #{monster_code}")

            # Create a confirmation view
            view = discord.ui.View(timeout=300)

            yes_button = discord.ui.Button(
                label="Yes, Delete",
                style=discord.ButtonStyle.danger,
                custom_id="confirm_delete"
            )
            view.add_item(yes_button)

            no_button = discord.ui.Button(
                label="No, Cancel",
                style=discord.ButtonStyle.secondary,
                custom_id="cancel_delete"
            )
            view.add_item(no_button)

            async def button_callback(button_interaction):
                custom_id = button_interaction.data["custom_id"]

                if custom_id == "confirm_delete":
                    # Update the configuration
                    with open(config_file, "r")as f:
                        updated_config = json.load(f)

                    # Remove thetarget
                    rally_config = updated_config.get('rally', {}).get(config_type, {})
                    targets = rally_config.get('targets', [])
                    targets[:] = [t for t in targets if t.get("monster_code") != monster_code]

                    # Save the updated configuration
                    with open(config_file, "w") as f:
                        json.dump(updated_config, f, indent=2)

                    await button_interaction.response.send_message(
                        f"Deleted {monster_name} from configuration!",
                        ephemeral=True
                    )
                else:
                    await button_interaction.response.send_message(
                        "Deletion cancelled.",
                        ephemeral=True
                    )

            for item in view.children:
                item.callback = button_callback

            await interaction.response.send_message(
                f"Are you sure you want to delete {monster_name} from the configuration?",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error deleting monster: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def toggle_level_based_troops(self, interaction, config_file, config_section):
        try:
            with open(config_file, "r") as f:
                config = json.load(f)

            if config_section not in config:
                config[config_section] = {"enabled": False, "numMarch": 6, "targets": [], "level_based_troops": False}

            config[config_section]["level_based_troops"] = not config[config_section].get("level_based_troops", False)
            new_state = config[config_section]["level_based_troops"]

            with open(config_file, "w") as f:
                json.dump(config, f, indent=2)

            await interaction.response.send_message(
                f"Level-based troops {'enabled' if new_state else 'disabled'}!",
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error toggling level_based_troops: {str(e)}")
            await interaction.response.send_message(f"Error updating configuration: {str(e)}", ephemeral=True)

    # Internal method used by /config setup
    async def game_settings(self, interaction: discord.Interaction):
        """Configure general game settings
        Internal method used by the unified /config setup interface.
        This method is not exposed as a slash command directly.
        """
        await interaction.response.defer(ephemeral=True)

        try:
            # Load the configuration from selected config file
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            # Create the main embed for the settings
            embed = discord.Embed(
                title="Game Settings Configuration",
                description="Use the buttons below to configure game settings",
                color=discord.Color.blue()
            )

            # Add basic info about available settings
            main_config = config.get('main', {})

            # Jobs status
            jobs = main_config.get('jobs', [])
            enabled_jobs = sum(1 for job in jobs if job.get('enabled', False))
            total_jobs = len(jobs)

            # Threads status
            threads = main_config.get('threads', [])
            enabled_threads = sum(1 for thread in threads if thread.get('enabled', False))
            total_threads = len(threads)

            # Object scanning status
            object_scanning = main_config.get('object_scanning', {})
            object_scanning_enabled = object_scanning.get('enabled', True)
            notify_discord = object_scanning.get('notify_discord', True)

            embed.add_field(
                name="Status Overview",
                value=f"**Enabled Jobs:** {enabled_jobs}/{total_jobs}\n"
                      f"**Enabled Threads:** {enabled_threads}/{total_threads}\n"
                      f"**Object Scanning:** {'Enabled' if object_scanning_enabled else 'Disabled'}\n"
                      f"**Discord Integration:** {'Enabled' if config.get('discord', {}).get('enabled', False) else 'Disabled'}",
                inline=False
            )

            # Add action buttons
            view = discord.ui.View(timeout=300)  # 5 minute timeout

            # Configure jobs button
            jobs_button = discord.ui.Button(
                label="Configure Jobs",
                style=discord.ButtonStyle.primary,
                custom_id="configure_jobs"
            )
            view.add_item(jobs_button)

            # Configure threads button
            threads_button = discord.ui.Button(
                label="Configure Threads",
                style=discord.ButtonStyle.primary,
                custom_id="configure_threads"
            )
            view.add_item(threads_button)

            # Object scanning button
            object_scanning_button = discord.ui.Button(
                label="Configure Object Scanning",
                style=discord.ButtonStyle.primary,
                custom_id="configure_object_scanning"
            )
            view.add_item(object_scanning_button)

            # Discord webhooks button
            webhooks_button = discord.ui.Button(
                label="Configure Discord Webhooks",
                style=discord.ButtonStyle.primary,
                custom_id="configure_webhooks"
            )
            view.add_item(webhooks_button)

            # List available configs button
            configs_button = discord.ui.Button(
                label="List Available Configs",
                style=discord.ButtonStyle.secondary,
                custom_id="list_configs"
            )
            view.add_item(configs_button)

            # Send the configuration view
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

            # Setup button callbacks
            async def button_callback(button_interaction):
                if button_interaction.data["custom_id"] == "configure_jobs":
                    await self.show_jobs_config(button_interaction)
                elif button_interaction.data["custom_id"] == "configure_threads":
                    await self.show_threads_config(button_interaction)
                elif button_interaction.data["custom_id"] == "configure_webhooks":
                    await self.show_webhooks_config(button_interaction)
                elif button_interaction.data["custom_id"] == "configure_object_scanning":
                    await self.show_object_scanning_config(button_interaction)
                elif button_interaction.data["custom_id"] == "list_configs":
                    await self.list_configs(button_interaction)

            # Register the callback
            view.on_timeout = lambda: view.clear_items()
            for item in view.children:
                item.callback = button_callback

        except Exception as e:
            logger.error(f"Error displaying game settings: {str(e)}")
            await interaction.followup.send(f"Error loading configuration: {str(e)}", ephemeral=True)

    async def show_jobs_config(self, interaction: discord.Interaction, view: discord.ui.View):
        """Show jobs configuration"""
        try:
            # Load the configuration from selected config file
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            jobs = config.get('main', {}).get('jobs', [])

            # Create an embed to display jobs
            embed = discord.Embed(
                title="Jobs Configuration",
                description="Toggle jobs on/off and configure intervals",
                color=discord.Color.green()
            )

            # Create dropdown to select job to configure
            view = discord.ui.View(timeout=300)
            job_select = discord.ui.Select(
                placeholder="Select a job to configure",
                custom_id="job_select"
            )

            # Add options for all jobs
            try:
                for job in jobs:
                    job_name = job.get('name', 'Unknown')
                    status = "✅ Enabled" if job.get('enabled', False) else "❌ Disabled"
                    job_select.add_option(label=f"{job_name} ({status})", value=job_name)
            except Exception as e:
                logger.error(f"Error loading jobs: {str(e)}")

            # Add options to the view
            view.add_item(job_select)

            # Send the embed and view
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

            # Add callback for job selection
            async def job_select_callback(select_interaction):
                selected_job = select_interaction.data["values"][0]

                # Find selected job
                selected_job_data = next((job for job in jobs if job.get('name') == selected_job), None)

                if selected_job_data:
                    # Create an embed for the job configuration
                    job_embed = discord.Embed(
                        title=f"{selected_job} Configuration",
                        description=f"Job Name: {selected_job}",
                        color=discord.Color.blue()
                    )

                    # Add existing settings to the embed
                    job_embed.add_field(
                        name="Status",
                        value=f"{'Enabled' if selected_job_data.get('enabled', False) else 'Disabled'}"
                    )

                    interval = selected_job_data.get('interval', {})
                    job_embed.add_field(
                        name="Interval",
                        value=f"Start: {interval.get('start', 0)}s, End: {interval.get('end', 0)}s"
                    )

                    # Add buttons to toggle enable/disable and edit interval
                    job_view = discord.ui.View(timeout=300)

                    # Toggle button
                    toggle_button = discord.ui.Button(
                        label=f"{'Disable' if selected_job_data.get('enabled', False) else 'Enable'}",
                        style=discord.ButtonStyle.danger if selected_job_data.get('enabled', False) else discord.ButtonStyle.success,
                        custom_id=f"toggle_{selected_job}"
                    )
                    job_view.add_item(toggle_button)

                    # Edit interval button
                    edit_interval_button = discord.ui.Button(
                        label="Edit Interval",
                        style=discord.ButtonStyle.primary,
                        custom_id=f"edit_interval_{selected_job}"
                    )
                    job_view.add_item(edit_interval_button)

                    async def job_button_callback(button_interaction):
                        custom_id = button_interaction.data["custom_id"]

                        if custom_id.startswith("toggle_"):
                            await self.toggle_job(button_interaction, selected_job)
                        elif custom_id.startswith("edit_interval_"):
                            await self.edit_job_interval(button_interaction, selected_job)

                    for item in job_view.children:
                        item.callback = job_button_callback

                    await select_interaction.response.send_message(embed=job_embed, view=job_view, ephemeral=True)

                else:
                    await select_interaction.response.send_message("Job not found.", ephemeral=True)

            job_select.callback = job_select_callback

        except Exception as e:
            logger.error(f"Error showing jobs config: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def toggle_job(self, interaction, job_name):
        """Toggle job enabled state"""
        try:
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            jobs = config.get('main', {}).get('jobs', [])
            job = next((job for job in jobs if job.get('name') == job_name), None)

            if job:
                job['enabled'] = not job.get('enabled', False)

                with open(ConfigHelper.current_config_file, "w") as f:
                    json.dump(config, f, indent=2)

                await interaction.response.send_message(f"Job '{job_name}' is now {'enabled' if job['enabled'] else 'disabled'}", ephemeral=True)
            else:
                await interaction.response.send_message("Job not found.", ephemeral=True)

        except Exception as e:
            logger.error(f"Error toggling job '{job_name}': {str(e)}")
            await interaction.response.send_message(f"Error updating job: {str(e)}", ephemeral=True)


    async def edit_job_interval(self, interaction, job_name):
        """Edit job interval"""
        try:
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            jobs = config.get('main', {}).get('jobs', [])
            job = next((job for job in jobs if job.get('name') == job_name), None)

            if job:
                modal = discord.ui.Modal(title=f"Edit Interval for {job_name}")

                start_input = discord.ui.TextInput(
                    label="Start (seconds)",
                    placeholder="Enter start time in seconds",
                    default=str(job['interval'].get('start', 0)),
                    required=True
                )
                modal.add_item(start_input)

                end_input = discord.ui.TextInput(
                    label="End (seconds)",
                    placeholder="Enter end time in seconds",
                    default=str(job['interval'].get('end', 0)),
                    required=True
                )
                modal.add_item(end_input)

                async def modal_callback(modal_interaction):
                    try:
                        start = int(start_input.value)
                        end = int(end_input.value)

                        if start < 0 or end < 0 or start > end:
                            await modal_interaction.response.send_message("Invalid interval. Start must be non-negative, end must be non-negative, and start must be less than or equal to end.", ephemeral=True)
                            return

                        job['interval'] = {'start': start, 'end': end}

                        with open(ConfigHelper.current_config_file, "w") as f:
                            json.dump(config, f, indent=2)

                        await modal_interaction.response.send_message(f"Interval for '{job_name}' updated to {start}-{end} seconds.", ephemeral=True)

                    except ValueError:
                        await modal_interaction.response.send_message("Invalid input. Please enter valid numbers.", ephemeral=True)
                    except Exception as e:
                        logger.error(f"Error updating job interval '{job_name}': {str(e)}")
                        await modal_interaction.response.send_message(f"Error updating job interval: {str(e)}", ephemeral=True)

                modal.on_submit = modal_callback
                await interaction.response.send_modal(modal)
            else:
                await interaction.response.send_message("Job not found.", ephemeral=True)

        except Exception as e:
            logger.error(f"Error editing job interval '{job_name}': {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def show_threads_config(self, interaction):
        """Show threads configuration"""
        try:
            # Load the configuration from selected config file
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            threads = config.get('main', {}).get('threads', [])

            # Create an embed to display threads
            embed = discord.Embed(
                title="Threads Configuration",
                description="Toggle threads on/off",
                color=discord.Color.green()
            )

            # Create dropdown to select thread to configure
            view = discord.ui.View(timeout=300)
            thread_select = discord.ui.Select(
                placeholder="Select a thread to configure",
                custom_id="thread_select"
            )

            for thread in threads:
                thread_name = thread.get('name', 'Unknown')
                status = "✅ Enabled" if thread.get('enabled', False) else "❌ Disabled"
                thread_select.add_option(label=f"{thread_name} ({status})", value=thread_name)

            # Add options to the view
            view.add_item(thread_select)

            # Send the embed and view
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

            # Add callback for thread selection
            async def thread_select_callback(select_interaction):
                selected_thread = select_interaction.data["values"][0]

                # Find selected thread
                selected_thread_data = next((thread for thread in threads if thread.get('name') == selected_thread), None)

                if selected_thread_data:
                    # Create an embed for the thread configuration
                    thread_embed = discord.Embed(
                        title=f"{selected_thread} Configuration",
                        description=f"Thread Name: {selected_thread}",
                        color=discord.Color.blue()
                    )

                    # Add existing settings to the embed
                    thread_embed.add_field(
                        name="Status",
                        value=f"{'Enabled' if selected_thread_data.get('enabled', False) else 'Disabled'}"
                    )

                    kwargs = selected_thread_data.get('kwargs', {})
                    kwargs_str = ", ".join([f"{k}={v}" for k, v in kwargs.items()]) if kwargs else "No additional arguments"
                    thread_embed.add_field(
                        name="Arguments",
                        value=kwargs_str
                    )

                    # Add buttons to toggle enable/disable and edit interval
                    thread_view = discord.ui.View(timeout=300)

                    # Toggle button
                    toggle_button = discord.ui.Button(
                        label=f"{'Disable' if selected_thread_data.get('enabled', False) else 'Enable'}",
                        style=discord.ButtonStyle.danger if selected_thread_data.get('enabled', False) else discord.ButtonStyle.success,
                        custom_id=f"toggle_{selected_thread}"
                    )
                    thread_view.add_item(toggle_button)

                    async def thread_button_callback(button_interaction):
                        custom_id = button_interaction.data["custom_id"]

                        if custom_id.startswith("toggle_"):
                            await self.toggle_thread(button_interaction, selected_thread)

                    for item in thread_view.children:
                        item.callback = thread_button_callback

                    await select_interaction.response.send_message(embed=thread_embed, view=thread_view, ephemeral=True)

                else:
                    await select_interaction.response.send_message("Thread not found.", ephemeral=True)

            thread_select.callback = thread_select_callback

        except Exception as e:
            logger.error(f"Error showing threads config: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def toggle_thread(self, interaction, thread_name):
        """Toggle thread enabled state"""
        try:
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            threads = config.get('main', {}).get('threads', [])
            thread = next((thread for thread in threads if thread.get('name') == thread_name), None)

            if thread:
                thread['enabled'] = not thread.get('enabled', False)

                with open(ConfigHelper.current_config_file, "w") as f:
                    json.dump(config, f, indent=2)

                await interaction.response.send_message(f"Thread '{thread_name}' is now {'enabled' if thread['enabled'] else 'disabled'}", ephemeral=True)
            else:
                await interaction.response.send_message("Thread not found.", ephemeral=True)

        except Exception as e:
            logger.error(f"Error toggling thread '{thread_name}': {str(e)}")
            await interaction.response.send_message(f"Error updating thread: {str(e)}", ephemeral=True)

    async def show_webhooks_config(self, interaction):
        """Show discord webhook configuration"""
        try:
            await interaction.response.defer(ephemeral=True)

            # Load the configuration from selected config file
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            discord_config = config.get('discord', {})

            # Create an embed to display webhooks
            embed = discord.Embed(
                title="Discord Webhooks Configuration",
                description="Configure Discord webhooks for different events",
                color=discord.Color.purple()
            )

            webhook_fields = [
                ("Main Webhook", discord_config.get('webhook_url', '')),
                ("Crystal Mine L1 Webhook", discord_config.get('crystal_mine_level1_webhook_url', '')),
                ("Level 2+ Webhook", discord_config.get('level2plus_webhook_url', '')),
                ("Level 3+ Webhook", discord_config.get('level3plus_webhook_url', '')),
                ("Custom Webhook", discord_config.get('custom_webhook_url', '')),
                ("Dragon Soul L2+ Webhook", discord_config.get('dragon_soul_level2plus_webhook_url', '')),
                ("Occupied Resources Webhook", discord_config.get('occupied_resources_webhook_url', '')),
                ("Rally Webhook", discord_config.get('rally_webhook_url', '')),
                ("Chat Webhook", discord_config.get('chat_webhook_url', ''))
            ]

            for name, url in webhook_fields:
                status = "✅ Set" if url else "❌ Not Set"
                embed.add_field(name=name, value=status, inline=True)

            # Create view with action buttons
            view = discord.ui.View(timeout=300)

            # Add buttons for each webhook type
            for name, _ in webhook_fields:
                button = discord.ui.Button(
                    label=f"Configure {name}",
                    style=discord.ButtonStyle.primary,
                    custom_id=f"configure_{name.lower().replace(' ', '_')}"
                )
                view.add_item(button)

            async def button_callback(button_interaction):
                custom_id = button_interaction.data["custom_id"]
                webhook_name = custom_id.replace("configure_", "").replace("_", " ")
                await self.configure_webhook(button_interaction, webhook_name)

            for item in view.children:
                item.callback = button_callback

            # Send the configuration view
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"Error showing webhooks config: {str(e)}")
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

    async def configure_webhook(self, interaction, webhook_name):
        """Configure discord webhook URL"""
        try:
            # Create view with configure and delete buttons
            view = discord.ui.View(timeout=300)

            configure_button = discord.ui.Button(
                label="Set Webhook URL",
                style=discord.ButtonStyle.primary,
                custom_id=f"configure_{webhook_name}"
            )
            view.add_item(configure_button)

            delete_button = discord.ui.Button(
                label="Delete Webhook URL",
                style=discord.ButtonStyle.danger,
                custom_id=f"delete_{webhook_name}"
            )
            view.add_item(delete_button)

            async def button_callback(button_interaction):
                if button_interaction.data["custom_id"].startswith("configure_"):
                    # Show modal to configure webhook
                    modal = discord.ui.Modal(title=f"Configure {webhook_name} Webhook")
                    url_input = discord.ui.TextInput(
                        label="Webhook URL",
                        placeholder="Enter the webhook URL",
                        style=discord.TextStyle.long,
                        required=True
                    )
                    modal.add_item(url_input)

                    async def modal_callback(modal_interaction):
                        try:
                            url = url_input.value
                            # Check valid URL
                            import re
                            if not re.match(r"https://discord\.com/api/webhooks/[0-9]+/[a-zA-Z0-9_-]+", url):
                                raise ValueError("Invalid webhook URL.")

                            # Update the configuration
                            with open(ConfigHelper.current_config_file, "r") as f:
                                config = json.load(f)

                            # Map webhook names to config keys
                            webhook_key_map = {
                                "main webhook": "webhook_url",
                                "crystal mine l1 webhook": "crystal_mine_level1_webhook_url",
                                "level 2+ webhook": "level2plus_webhook_url", 
                                "level 3+ webhook": "level3plus_webhook_url",
                                "custom webhook": "custom_webhook_url",
                                "dragon soul l2+ webhook": "dragon_soul_level2plus_webhook_url",
                                "occupied resources webhook": "occupied_resources_webhook_url",
                                "rally webhook": "rally_webhook_url",
                                "chat webhook": "chat_webhook_url"
                            }

                            webhook_key = webhook_key_map.get(webhook_name.lower())
                            if webhook_key:
                                discord_config = config.get('discord', {})
                                discord_config[webhook_key] = url
                            else:
                                raise ValueError(f"Unknown webhook type: {webhook_name}")

                            with open(ConfigHelper.current_config_file, "w") as f:
                                json.dump(config, f, indent=2)

                            await modal_interaction.response.send_message(f"{webhook_name} webhook updated.", ephemeral=True)

                        except ValueError as e:
                            await modal_interaction.response.send_message(str(e), ephemeral=True)
                        except Exception as e:
                            logger.error(f"Error updating webhook: {str(e)}")
                            await modal_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

                    modal.on_submit = modal_callback
                    await button_interaction.response.send_modal(modal)

                elif button_interaction.data["custom_id"].startswith("delete_"):
                    try:
                        # Update the configuration
                        with open(ConfigHelper.current_config_file, "r") as f:
                            config = json.load(f)

                        # Map webhook names to config keys
                        webhook_key_map = {
                            "main webhook": "webhook_url",
                            "crystal mine l1 webhook": "crystal_mine_level1_webhook_url",
                            "level 2+ webhook": "level2plus_webhook_url", 
                            "level 3+ webhook": "level3plus_webhook_url",
                            "custom webhook": "custom_webhook_url",
                            "dragon soul l2+ webhook": "dragon_soul_level2plus_webhook_url",
                            "occupied resources webhook": "occupied_resources_webhook_url",
                            "rally webhook": "rally_webhook_url",
                            "chat webhook": "chat_webhook_url"
                        }

                        webhook_key = webhook_key_map.get(webhook_name.lower())
                        if webhook_key:
                            discord_config = config.get('discord', {})
                            discord_config[webhook_key] = ""
                        else:
                            raise ValueError(f"Unknown webhook type: {webhook_name}")

                        with open(ConfigHelper.current_config_file, "w") as f:
                            json.dump(config, f, indent=2)

                        await button_interaction.response.send_message(f"{webhook_name} webhook URL deleted.", ephemeral=True)

                    except Exception as e:
                        logger.error(f"Error deleting webhook: {str(e)}")
                        await button_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

            for item in view.children:
                item.callback = button_callback

            await interaction.response.send_message(
                f"Configure {webhook_name} webhook:",
                view=view,
                ephemeral=True
            )

            async def modal_callback(modal_interaction):
                try:
                    url = url_input.value
                    # Check valid URL
                    import re
                    if not re.match(r"https://discord\.com/api/webhooks/[0-9]+/[a-zA-Z0-9_-]+", url):
                        raise ValueError("Invalid webhook URL.")

                    # Update the configuration
                    with open(ConfigHelper.current_config_file, "r") as f:
                        config = json.load(f)

                    # Map webhook names to config keys
                    webhook_key_map = {
                        "main webhook": "webhook_url",
                        "crystal mine l1 webhook": "crystal_mine_level1_webhook_url",
                        "level 2+ webhook": "level2plus_webhook_url", 
                        "level 3+ webhook": "level3plus_webhook_url",
                        "custom webhook": "custom_webhook_url",
                        "dragon soul l2+ webhook": "dragon_soul_level2plus_webhook_url",
                        "occupied resources webhook": "occupied_resources_webhook_url",
                        "rally webhook": "rally_webhook_url",
                        "chat webhook": "chat_webhook_url"
                    }

                    webhook_key = webhook_key_map.get(webhook_name.lower())
                    if webhook_key:
                        discord_config = config.get('discord', {})
                        discord_config[webhook_key] = url
                    else:
                        raise ValueError(f"Unknown webhook type: {webhook_name}")

                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(config, f, indent=2)

                    await modal_interaction.response.send_message(f"{webhook_name} webhook updated.", ephemeral=True)

                except ValueError as e:
                    await modal_interaction.response.send_message(str(e), ephemeral=True)
                except Exception as e:
                    logger.error(f"Error updating webhook: {str(e)}")
                    await modal_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

            modal.on_submit = modal_callback
            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error(f"Error configuring webhook '{webhook_name}': {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)


    async def toggle_discord(self, interaction):
        """Toggle discord integration"""
        try:
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            discord_config = config.get('discord', {})
            discord_config['enabled'] = not discord_config.get('enabled', False)

            with open(ConfigHelper.current_config_file, "w") as f:
                json.dump(config, f, indent=2)

            await interaction.response.send_message(f"Discord integration is now {'enabled' if discord_config['enabled'] else 'disabled'}", ephemeral=True)

        except Exception as e:
            logger.error(f"Error toggling discord integration: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def list_configs(self, interaction):
        """Lists available configurations"""
        try:
            import glob
            config_files = glob.glob("*.json")
            message = "Available Configurations:\n" + "\n".join(config_files)
            await interaction.response.send_message(message, ephemeral=True)

        except Exception as e:
            logger.error(f"Error listing configurations: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def show_object_scanning_config(self, interaction):
        """Show object scanning configuration"""
        try:
            # Load the configuration from selected config file
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            main_config = config.get('main', {})
            object_scanning = main_config.get('object_scanning', {"enabled": True, "notify_discord": True, "enable_gathering": True, "enable_monster_attack": True})
            object_scanning_enabled = object_scanning.get('enabled', True)
            notify_discord = object_scanning.get('notify_discord', True)
            enable_gathering = object_scanning.get('enable_gathering', True)
            enable_monster_attack = object_scanning.get('enable_monster_attack', True)
            distance_check = object_scanning.get('monster_distance_check', {"enabled": True, "max_distance": 200})
            distance_check_enabled = distance_check.get('enabled', True)
            max_distance = distance_check.get('max_distance', 200)

            # Get configured objects from socf_thread targets
            configured_objects = {}
            for job in config.get('main', {}).get('jobs', []):
                if job.get('name') == 'socf_thread':
                    if 'kwargs' in job and 'targets'in job['kwargs']:
                        for target in job['kwargs']['targets']:
                            if 'code' in target:
                                code = str(target['code'])
                                configured_objects[code] = {
                                    'name': target.get('name', f"Object #{code}"),
                                    'enabled': target.get('enabled', True),
                                    'levels': target.get('level', [])
                                }
                    break# Create an embed to display thecurrent configuration
            embed = discord.Embed(
                title="Object Scanning Configuration",
                description="Configure object scanning settings (socf_thread targets)",
                color=discord.Color.green()
            )

            embed.add_field(
                name="Current Settings",
                value=f"**Enabled:** {'Yes' if object_scanning_enabled else 'No'}\n"
                      f"**Notify Discord:** {'Yes' if notify_discord else 'No'}\n"
                      f"**Enable Gathering:** {'Yes' if enable_gathering else 'No'}\n"
                      f"**Enable Monster Attack:** {'Yes' if enable_monster_attack else 'No'}\n"
                      f"**Distance Check:** {'Yes' if distance_check_enabled else 'No'}\n"
                      f"**Max Distance:** {max_distance} tiles\n"
                      f"**Configured Objects:** {len(configured_objects)}",
                inline=False
            )

            # Add field for configured objects if any
            if configured_objects:
                objects_list = []
                for obj_code, obj_config in configured_objects.items():
                    enabled = obj_config.get('enabled', True)
                    status = "✅" if enabled else "❌"
                    obj_name = obj_config.get('name', f"Object #{obj_code}")
                    objects_list.append(f"{status} **{obj_name}** (Code: {obj_code})")

                # Show first 10 objects to avoid too large embed
                embed.add_field(
                    name="Configured Objects",
                    value="\n".join(objects_list[:10]) + (f"\n...and {len(objects_list) - 10} more" if len(objects_list) > 10 else ""),
                    inline=False
                )

            # Create buttons for toggling settings
            view = discord.ui.View(timeout=300)

            # Toggle enabled button
            toggle_enabled_button = discord.ui.Button(
                label=f"{'Disable' if object_scanning_enabled else 'Enable'} Object Scanning",
                style=discord.ButtonStyle.danger if object_scanning_enabled else discord.ButtonStyle.success,
                custom_id="toggle_object_scanning"
            )
            view.add_item(toggle_enabled_button)

            # Toggle gathering button
            toggle_gathering_button = discord.ui.Button(
                label=f"{'Disable' if enable_gathering else 'Enable'} Resource Gathering",
                style=discord.ButtonStyle.danger if enable_gathering else discord.ButtonStyle.success,
                custom_id="toggle_gathering"
            )
            view.add_item(toggle_gathering_button)

            # Toggle monster attack button
            toggle_monster_attack_button = discord.ui.Button(
                label=f"{'Disable' if enable_monster_attack else 'Enable'} Monster Attack",
                style=discord.ButtonStyle.danger if enable_monster_attack else discord.ButtonStyle.success,
                custom_id="toggle_monster_attack"
            )
            view.add_item(toggle_monster_attack_button)

            # Toggle notify discord button
            toggle_notify_button = discord.ui.Button(
                label=f"{'Disable' if notify_discord else 'Enable'} Discord Notifications",
                style=discord.ButtonStyle.danger if notify_discord else discord.ButtonStyle.success,
                custom_id="toggle_notify_discord"
            )
            view.add_item(toggle_notify_button)

            # Configure objects button
            # Distance check toggle button
            toggle_distance_check_button = discord.ui.Button(
                label=f"{'Disable' if distance_check_enabled else 'Enable'} Distance Check",
                style=discord.ButtonStyle.danger if distance_check_enabled else discord.ButtonStyle.success,
                custom_id="toggle_distance_check"
            )
            view.add_item(toggle_distance_check_button)

            # Configure distance button
            configure_distance_button = discord.ui.Button(
                label="Configure Max Distance",
                style=discord.ButtonStyle.primary,
                custom_id="configure_distance"
            )
            view.add_item(configure_distance_button)

            configure_objects_button = discord.ui.Button(
                label="Configure Objects",
                style=discord.ButtonStyle.primary,
                custom_id="configure_objects"
            )
            view.add_item(configure_objects_button)

            # Add max marches button
            max_marches_button = discord.ui.Button(
                label="Set Max Marches",
                style=discord.ButtonStyle.primary,
                custom_id="set_max_marches"
            )
            view.add_item(max_marches_button)

            # Send the embed and view
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

            # Add callbacks for buttons
            async def button_callback(button_interaction):
                custom_id = button_interaction.data["custom_id"]

                # Load the latest config
                with open(ConfigHelper.current_config_file, "r") as f:
                    updated_config = json.load(f)

                # Ensure the object_scanning section exists
                if 'main' not in updated_config:
                    updated_config['main'] = {}
                if 'object_scanning' not in updated_config['main']:
                    updated_config['main']['object_scanning'] ={"enabled": True, "notify_discord": True, "objects": {}, "enable_gathering": True, "enable_monster_attack": True}

                if custom_id == "toggle_object_scanning":
                    # Toggle the enabled setting
                    current_value = updated_config['main']['object_scanning'].get('enabled', True)
                    updated_config['main']['object_scanning']['enabled'] = not current_value

                    # Also make sure socf_thread job is enabled/disabled to match
                    jobs = updated_config.get('main', {}).get('jobs', [])
                    for job in jobs:
                        if job.get('name') == 'socf_thread':
                            job['enabled'] = not current_value
                            break

                    # Save the updated config
                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(updated_config, f, indent=2)

                    await button_interaction.response.send_message(
                        f"Object scanning has been {'disabled' if current_value else 'enabled'}. The socf_thread job has also been {'disabled' if current_value else 'enabled'}.",
                        ephemeral=True
                    )

                elif custom_id == "toggle_gathering":
                    # Ensure the object_scanning structure exists
                    if 'object_scanning' not in updated_config.get('main', {}):
                        updated_config['main']['object_scanning'] = {'enabled': False, 'notify_discord': True, 'enable_gathering': False, 'enable_monster_attack': False}
                    if 'enable_gathering' not in updated_config['main']['object_scanning']:
                        updated_config['main']['object_scanning']['enable_gathering'] = False

                    current_value = updated_config['main']['object_scanning']['enable_gathering']
                    updated_config['main']['object_scanning']['enable_gathering'] = not current_value

                    # Save the updated configuration
                    with open(ConfigHelper.current_config_file, "w")as f:
                        json.dump(updated_config, f, indent=2)

                    await button_interaction.response.send_message(
                        f"Resource gathering has been {'disabled' if current_value else 'enabled'}.",
                        ephemeral=True
                    )

                elif custom_id == "toggle_monster_attack":
                    # Ensure the object_scanning structure exists
                    if 'object_scanning' not in updated_config.get('main', {}):
                        updated_config['main']['object_scanning'] = {'enabled': False, 'notify_discord': True, 'enable_gathering': False, 'enable_monster_attack': False}
                    if 'enable_monster_attack' not in updated_config['main']['object_scanning']:
                        updated_config['main']['object_scanning']['enable_monster_attack'] = False

                    current_value = updated_config['main']['object_scanning']['enable_monster_attack']
                    updated_config['main']['object_scanning']['enable_monster_attack'] = not current_value

                    # Save the updated configuration
                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(updated_config, f, indent=2)

                    await button_interaction.response.send_message(
                        f"Monster attack has been {'disabled' if current_value else 'enabled'}.",
                        ephemeral=True
                    )

                    # Ensure the object_scanning structure exists
                    if 'object_scanning' not in updated_config.get('main', {}):
                        updated_config['main']['object_scanning'] = {'enabled': False, 'notify_discord': True, 'enable_gathering': False, 'enable_monster_attack': False}
                    if 'enable_monster_attack' not in updated_config['main']['object_scanning']:
                        updated_config['main']['object_scanning']['enable_monster_attack'] = False

                    current_value = updated_config['main']['object_scanning']['enable_monster_attack']
                    updated_config['main']['object_scanning']['enable_monster_attack'] = not current_value

                    # Save the updated configuration
                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(updated_config, f, indent=2)

                    await button_interaction.response.send_message(
                        f"Monster attack has been {'disabled' if current_value else 'enabled'}.",
                        ephemeral=True
                    )
                elif button_interaction.data["custom_id"] == "configure_monster_settings":
                    await self.show_monster_config(button_interaction, ConfigHelper.current_config_file, "main.monster_attack")

                    for item in monster_view.children:
                        item.callback = monster_button_callback

                    await button_interaction.response.send_message(
                        "Monster Attack Settings:",
                        view=monster_view,
                        ephemeral=True
                    )

                elif custom_id == "toggle_notify_discord":
                    # Toggle the notify_discord setting
                    current_value = updated_config['main']['object_scanning'].get('notify_discord', True)
                    updated_config['main']['object_scanning']['notify_discord'] = not current_value

                    # Save the updated config
                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(updated_config, f, indent=2)

                    await button_interaction.response.send_message(
                        f"Discord notifications for object scanning have been {'disabled' if current_value else 'enabled'}.",
                        ephemeral=True
                    )

                elif custom_id == "toggle_distance_check":
                    # Toggle the distance check setting
                    if 'monster_distance_check' not in updated_config['main']['object_scanning']:
                        updated_config['main']['object_scanning']['monster_distance_check'] = {"enabled": True, "max_distance": 200}
                    current_value = updated_config['main']['object_scanning']['monster_distance_check']['enabled']
                    updated_config['main']['object_scanning']['monster_distance_check']['enabled'] = not current_value

                    # Save the updated config
                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(updated_config, f, indent=2)

                    await button_interaction.response.send_message(
                        f"Monster distance check has been {'disabled' if current_value else 'enabled'}.",
                        ephemeral=True
                    )

                elif custom_id == "configure_distance":
                    # Show modal to configure max distance
                    modal = discord.ui.Modal(title="Configure Max Distance")
                    distance_input = discord.ui.TextInput(
                        label="Max Distance (tiles)",
                        placeholder="Enter maximum distance in tiles (e.g., 200)",
                        default=str(max_distance),
                        required=True
                    )
                    modal.add_item(distance_input)

                    async def distance_modal_callback(modal_interaction):
                        try:
                            new_distance = int(distance_input.value)
                            if new_distance < 1:
                                await modal_interaction.response.send_message(
                                    "Invalid distance. Please enter a positive number.",
                                    ephemeral=True
                                )
                                return

                            # Update the configuration
                            with open(ConfigHelper.current_config_file, "r") as f:
                                distance_config = json.load(f)

                            if 'monster_distance_check' not in distance_config['main']['object_scanning']:
                                distance_config['main']['object_scanning']['monster_distance_check'] = {"enabled": True, "max_distance": 200}

                            distance_config['main']['object_scanning']['monster_distance_check']['max_distance'] = new_distance

                            with open(ConfigHelper.current_config_file, "w") as f:
                                json.dump(distance_config, f, indent=2)

                            await modal_interaction.response.send_message(
                                f"Maximum monster distance updated to {new_distance} tiles.",
                                ephemeral=True
                            )
                        except ValueError:
                            await modal_interaction.response.send_message(
                                "Invalid input. Please enter a valid number.",
                                ephemeral=True
                            )

                    modal.on_submit = distance_modal_callback
                    await button_interaction.response.send_modal(modal)

                elif custom_id == "configure_objects":
                    await self.show_object_config_menu(button_interaction)
                
                elif custom_id == "set_max_marches":
                    # Show modal to set max marches
                    modal = discord.ui.Modal(title="Set Max Marches")
                    marches_input = discord.ui.TextInput(
                        label="Number of Marches (1-10)",
                        placeholder="Enter a number between 1 and 10",
                        required=True,
                        min_length=1,
                        max_length=2
                    )
                    modal.add_item(marches_input)

                    async def modal_callback(modal_interaction):
                        try:
                            new_marches = int(marches_input.value)
                            if new_marches < 1 or new_marches > 10:
                                await modal_interaction.response.send_message(
                                    "Invalid input: Number of marches must be between 1 and 10",
                                    ephemeral=True
                                )
                                return

                            # Always use the current config file from ConfigHelper
                            config_file = ConfigHelper.current_config_file
                            logger.info(f"Updating max_marches in config file: {config_file}")
                            
                            # Read the current config file
                            with open(config_file, "r") as f:
                                config = json.load(f)

                            # Ensure necessary structure exists
                            if 'main' not in config:
                                config['main'] = {}
                            if 'object_scanning' not in config['main']:
                                config['main']['object_scanning'] = {}
                            
                            # Update max_marches
                            config['main']['object_scanning']['max_marches'] = new_marches

                            # Save changes back to the currently selected config file
                            with open(config_file, "w") as f:
                                json.dump(config, f, indent=2)

                            await modal_interaction.response.send_message(
                                f"Maximum marches updated to {new_marches} in {config_file}!",
                                ephemeral=True
                            )

                        except ValueError:
                            await modal_interaction.response.send_message(
                                "Invalid input: Please enter a valid number",
                                ephemeral=True
                            )
                        except Exception as e:
                            logger.error(f"Error updating max marches: {str(e)}")
                            await modal_interaction.response.send_message(
                                f"Error updating configuration: {str(e)}",
                                ephemeral=True
                            )

                    modal.on_submit = modal_callback
                    await button_interaction.response.send_modal(modal)

            # Register the callback
            for item in view.children:
                item.callback = button_callback

        except Exception as e:
            logger.error(f"Error displaying object scanning config: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def show_object_config_menu(self, interaction):
        """Show menu for configuring scannable objects"""
        try:
            # Load the configuration from selected config file
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            # Ensure the object_scanning section exists
            if 'main' not in config:
                config['main'] = {}
            if 'object_scanning' not in config['main']:
                config['main']['object_scanning'] = {"enabled": True, "notify_discord": True, "objects": {}}

            # Get configured objects from socf_thread targets
            configured_objects = {}
            for job in config.get('main', {}).get('jobs', []):
                if job.get('name') == 'socf_thread':
                    if 'kwargs' in job and 'targets' in job['kwargs']:
                        for target in job['kwargs']['targets']:
                            if 'code' in target:
                                code = str(target['code'])
                                configured_objects[code] = {
                                    'name': target.get('name', f"Object #{code}"),
                                    'enabled': target.get('enabled', True),
                                    'levels': target.get('level', [])
                                }
                    break

            # Create an embed for the object configuration menu
            embed = discord.Embed(
                title="Object Configuration",
                description="Add or modify scannable objects",
                color=discord.Color.blue()
            )

            # Add field showing current object configurations with levels
            if configured_objects:
                objects_info = []
                for obj_code, obj_config in configured_objects.items():
                    obj_name = obj_config.get('name', f"Object #{obj_code}")
                    levels = obj_config.get('levels', [])
                    levels_str = f"Levels: {', '.join(map(str, levels))}" if levels else "No levels configured"
                    objects_info.append(f"• **{obj_name}** (Code: {obj_code})\n  {levels_str}")

                embed.add_field(
                    name="Configured Objects",
                    value="\n".join(objects_info[:10]) + (f"\n...and {len(objects_info) - 10} more" if len(objects_info) > 10 else ""),
                    inline=False
                )

            # Create a view with buttons for actions
            view = discord.ui.View(timeout=300)

            # Button to add a new object
            add_object_button = discord.ui.Button(
                label="Add New Object",
                style=discord.ButtonStyle.success,
                custom_id="add_object"
            )
            view.add_item(add_object_button)

            # Select menu to modify existing objects
            if configured_objects:
                modify_object_select = discord.ui.Select(
                    placeholder="Select an object to modify",
                    custom_id="modify_object"
                )

                # Add options for existing objects
                for obj_code, obj_config in configured_objects.items():
                    obj_name = obj_config.get('name', f"Object #{obj_code}")
                    enabled = obj_config.get('enabled', True)
                    status = "✅" if enabled else "❌"
                    modify_object_select.add_option(
                        label=f"{obj_name}",
                        description=f"Code: {obj_code}, Status: {'Enabled' if enabled else 'Disabled'}",
                        value=obj_code
                    )

                view.add_item(modify_object_select)

            # Add edit levels button
            edit_levels_button = discord.ui.Button(
                label="Edit Object Levels",
                style=discord.ButtonStyle.primary,
                custom_id="edit_levels"
            )
            view.add_item(edit_levels_button)

            async def edit_levels_callback(button_interaction):
                # Show dropdown to select object to edit levels
                edit_view = discord.ui.View(timeout=300)
                edit_select = discord.ui.Select(
                    placeholder="Select an object to edit levels",
                    custom_id="edit_levels_select"
                )

                for obj_code, obj_config in configured_objects.items():
                    obj_name = obj_config.get('name', f"Object #{obj_code}")
                    edit_select.add_option(
                        label=f"{obj_name}",
                        value=obj_code
                    )

                async def edit_select_callback(select_interaction):
                    selected_code = select_interaction.data["values"][0]
                    selected_obj = configured_objects.get(selected_code)

                    modal = discord.ui.Modal(title=f"Edit Levels for {selected_obj.get('name', 'Object')}")
                    current_levels = selected_obj.get('levels', [])

                    levels_input = discord.ui.TextInput(
                        label="Object Levels",
                        placeholder="Enter levels separated by comma (e.g., 1,2,3,4)",
                        default=",".join(map(str, current_levels)),
                        required=True,
                        min_length=1,
                        max_length=50
                    )
                    modal.add_item(levels_input)

                    async def level_modal_callback(modal_interaction):
                        try:
                            new_levels = [int(level.strip()) for level in levels_input.value.split(',')]

                            with open(ConfigHelper.current_config_file, "r") as f:
                                config = json.load(f)

                            # Update levels in socf_thread targets
                            for job in config['main']['jobs']:
                                if job['name'] == 'socf_thread':
                                    for target in job['kwargs']['targets']:
                                        if str(target.get('code')) == selected_code:
                                            target['level'] = new_levels
                                            break
                                    break

                            with open(ConfigHelper.current_config_file, "w") as f:
                                json.dump(config, f, indent=2)

                            await modal_interaction.response.send_message(
                                f"Updated levels for {selected_obj.get('name', 'Object')}",
                                ephemeral=True
                            )

                        except ValueError:
                            await modal_interaction.response.send_message(
                                "Invalid input. Please enter valid numbers separated by commas.",
                                ephemeral=True
                            )

                    modal.on_submit = level_modal_callback
                    await select_interaction.response.send_modal(modal)

                edit_select.callback = edit_select_callback
                edit_view.add_item(edit_select)
                await button_interaction.response.send_message(
                    "Select an object to edit levels:",
                    view=edit_view,
                    ephemeral=True
                )

            edit_levels_button.callback = edit_levels_callback

            # Send the embed and view
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

            # Add callbacks for interactions
            async def button_callback(button_interaction):
                custom_id = button_interaction.data["custom_id"]

                if custom_id == "add_object":
                    await self.show_add_object_modal(button_interaction)

            async def select_callback(select_interaction):
                selected_value = select_interaction.data["values"][0]
                await self.show_modify_object_menu(select_interaction, selected_value)

            # Register callbacks
            add_object_button.callback = button_callback
            if configured_objects:
                modify_object_select.callback = select_callback

        except Exception as e:
            logger.error(f"Error showing object config menu: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def show_add_object_modal(self, interaction):
        """Show modal to add a new scannable object"""
        try:
            modal = discord.ui.Modal(title="Add New Object")

            # Object code input
            code_input = discord.ui.TextInput(
                label="Object Code",
                placeholder="Enter object code (e.g., 20100105)",
                required=True
            )
            modal.add_item(code_input)

            # Object name input
            name_input = discord.ui.TextInput(
                label="Object Name",
                placeholder="Enter object name (e.g., Crystal Mine)",
                required=True
            )
            modal.add_item(name_input)

            # Object levels input
            levels_input = discord.ui.TextInput(
                label="Object Levels",
                placeholder="Enter levels separated by comma (e.g., 1,2,3,4)",
                required=True,
                min_length=1,
                max_length=50
            )
            modal.add_item(levels_input)
            # Checkbox for enabled (simulated with text input)
            enabled_input = discord.ui.TextInput(
                label="Enabled",
                placeholder="Type 'yes' to enable or 'no' to disable",
                default="yes",
                required=True
            )
            modal.add_item(enabled_input)

            async def modal_callback(modal_interaction):
                try:
                    # Get values from inputs
                    object_code = code_input.value.strip()
                    object_name = name_input.value.strip()
                    object_enabled = enabled_input.value.lower() in ('yes', 'true', '1', 'y')

                    # Validate object code
                    try:
                        object_code = int(object_code)
                    except ValueError:
                        await modal_interaction.response.send_message(
                            "Invalid object code. Please enter a valid integer.",
                            ephemeral=True
                        )
                        return

                    # Load the configuration
                    with open(ConfigHelper.current_config_file, "r") as f:
                        config = json.load(f)

                    # Parse levels
                    levels = [int(level.strip()) for level in levels_input.value.split(',')]

                    # Check if object already exists in socf_thread targets
                    existing_target = None
                    for job in config['main']['jobs']:
                        if job['name'] == 'socf_thread':
                            for target in job['kwargs']['targets']:
                                if target['code'] == int(object_code):
                                    existing_target = target
                                    break
                            break

                    if existing_target:
                        await modal_interaction.response.send_message(
                            f"Object with code {object_code} already exists in scanning configuration.",
                            ephemeral=True
                        )
                        return

                    # Add only to socf_thread targets
                    for job in config['main']['jobs']:
                        if job['name'] == 'socf_thread':
                            new_target = {
                                "code": int(object_code),
                                "level": levels,
                                "name": object_name,
                                "enabled": object_enabled
                            }
                            job['kwargs']['targets'].append(new_target)
                            break

                    # Save the updated configuration
                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(config, f, indent=2)

                    await modal_interaction.response.send_message(
                        f"Added object '{object_name}' (Code: {object_code}) to scanning configuration.",
                        ephemeral=True
                    )

                except Exception as e:
                    logger.error(f"Error adding object: {str(e)}")
                    await modal_interaction.response.send_message(
                        f"Error adding object: {str(e)}",
                        ephemeral=True
                    )

            modal.on_submit = modal_callback
            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error(f"Error showing add object modal: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def show_modify_object_menu(self, interaction, object_code):
        """Show menu to modify an existing scannable object"""
        try:
            # Load the configuration from selected config file
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            # Find the object in socf_thread targets
            object_config = None
            for job in config.get('main', {}).get('jobs', []):
                if job.get('name') == 'socf_thread':
                    for target in job.get('kwargs', {}).get('targets', []):
                        if str(target.get('code')) == object_code:
                            object_config = target
                            break
                    break

            if not object_config:
                await interaction.response.send_message(
                    f"Error: Object with code {object_code} not found.",
                    ephemeral=True
                )
                return

            object_name = object_config.get('name', f"Object #{object_code}")
            object_enabled = object_config.get('enabled', True)

            # Create embed for the object
            embed = discord.Embed(
                title=f"Modify {object_name}",
                description=f"Code: {object_code}",
                color=discord.Color.green()
            )

            embed.add_field(
                name="Current Settings",
                value=f"**Enabled:** {'Yes' if object_enabled else 'No'}",
                inline=False
            )

            # Create view with action buttons
            view = discord.ui.View(timeout=300)

            # Toggle enabled button
            toggle_button = discord.ui.Button(
                label=f"{'Disable' if object_enabled else 'Enable'} Object",
                style=discord.ButtonStyle.danger if object_enabled else discord.ButtonStyle.success,
                custom_id="toggle_object"
            )
            view.add_item(toggle_button)

            # Edit name button
            edit_name_button = discord.ui.Button(
                label="Edit Name",
                style=discord.ButtonStyle.primary,
                custom_id="edit_name"
            )
            view.add_item(edit_name_button)

            # Delete object button
            delete_button = discord.ui.Button(
                label="Delete Object",
                style=discord.ButtonStyle.danger,
                custom_id="delete_object"
            )
            view.add_item(delete_button)

            # Send the embed and view
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

            # Add callbacks for buttons
            async def button_callback(button_interaction):
                custom_id = button_interaction.data["custom_id"]

                # Load the latest config
                with open(ConfigHelper.current_config_file, "r") as f:
                    updated_config = json.load(f)

                if custom_id == "toggle_object":
                    # Toggle the enabled setting
                    for job in updated_config['main']['jobs']:
                        if job['name'] == 'socf_thread':
                            for target in job['kwargs']['targets']:
                                if str(target.get('code')) == object_code:
                                    current_value = target.get('enabled', True)
                                    target['enabled'] = not current_value
                                    break
                            break

                    # Save the updated config
                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(updated_config, f, indent=2)

                    await button_interaction.response.send_message(
                        f"Object '{object_name}' has been {'disabled' if current_value else 'enabled'}.",
                        ephemeral=True
                    )

                elif custom_id == "edit_name":
                    # Show modal to edit name
                    modal = discord.ui.Modal(title=f"Edit Object Name")

                    name_input = discord.ui.TextInput(
                        label="Object Name",
                        placeholder="Enter new object name",
                        default=object_name,
                        required=True
                    )
                    modal.add_item(name_input)

                    async def name_modal_callback(modal_interaction):
                        new_name = name_input.value.strip()

                        # Update the name in config
                        with open(ConfigHelper.current_config_file, "r") as f:
                            name_config = json.load(f)

                        for job in name_config['main']['jobs']:
                            if job['name'] == 'socf_thread':
                                for target in job['kwargs']['targets']:
                                    if str(target.get('code')) == object_code:
                                        target['name'] = new_name
                                        break
                                break

                        with open(ConfigHelper.current_config_file, "w") as f:
                            json.dump(name_config, f, indent=2)

                        await modal_interaction.response.send_message(
                            f"Object name updated from '{object_name}' to '{new_name}'.",
                            ephemeral=True
                        )

                    modal.on_submit = name_modal_callback
                    await button_interaction.response.send_modal(modal)

                elif custom_id == "delete_object":
                    # Show confirmation view
                    confirm_view = discord.ui.View(timeout=60)

                    yes_button = discord.ui.Button(
                        label="Yes, Delete",
                        style=discord.ButtonStyle.danger,
                        custom_id="confirm_delete"
                    )
                    confirm_view.add_item(yes_button)

                    no_button = discord.ui.Button(
                        label="No, Cancel",
                        style=discord.ButtonStyle.secondary,
                        custom_id="cancel_delete"
                    )
                    confirm_view.add_item(no_button)

                    async def confirm_callback(confirm_interaction):
                        if confirm_interaction.data["custom_id"] == "confirm_delete":
                            # Delete the object
                            with open(ConfigHelper.current_config_file, "r") as f:
                                delete_config = json.load(f)

                            for job in delete_config['main']['jobs']:
                                if job['name'] == 'socf_thread':
                                    targets = job['kwargs']['targets']
                                    targets[:] = [t for t in targets if str(t.get('code')) != object_code]
                                    break

                            with open(ConfigHelper.current_config_file, "w") as f:
                                json.dump(delete_config, f, indent=2)

                            await confirm_interaction.response.send_message(
                                f"Object '{object_name}' has been deleted.",
                                ephemeral=True
                            )
                        else:
                            await confirm_interaction.response.send_message(
                                "Deletion canceled.",
                                ephemeral=True
                            )

                    for item in confirm_view.children:
                        item.callback = confirm_callback

                    await button_interaction.response.send_message(
                        f"Are you sure you want to delete the object '{object_name}'?",
                        view=confirm_view,
                        ephemeral=True
                    )

            # Register callbacks
            for item in view.children:
                item.callback = button_callback

        except Exception as e:
            logger.error(f"Error showing modify object menu: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)


class LokBot(discord.Client):
    def __init__(self, **options):
        super().__init__(**options)
        self.tree = app_commands.CommandTree(self)
        self.rally_commands = RallyConfigCommands()

    async def setup_hook(self):
        self.tree.add_command(self.rally_commands)
        await self.tree.sync()

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")

    print("------")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

with open(ConfigHelper.current_config_file, "r") as f:
    config = json.load(f)

bot = LokBot(intents=intents)

try:
    from lokbot.discord_commands import RallyConfigCommands
    bot.rally_commands = RallyConfigCommands()
    bot.tree.add_command(bot.rally_commands)

    # Set up a setup hook to sync commands when the bot starts
    @bot.event
    async def on_ready():
        await bot.tree.sync()
        print(f"Bot is ready and commands synced!")

    # Run the bot
    bot.run(config["token"])
except Exception as e:
    print(f"Error starting bot: {e}")
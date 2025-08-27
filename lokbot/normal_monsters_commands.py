import discord
from discord import app_commands
import json
import logging
from lokbot.config_helper import ConfigHelper
import os

logger = logging.getLogger(__name__)

class NormalMonstersCommands(app_commands.Group):
    """Commands for managing Normal Monsters configuration"""

    def __init__(self):
        super().__init__(name="nmonsters", description="Manage Normal Monsters configuration")

    @app_commands.command(name="setup", description="Configure Normal Monsters settings")
    async def setup(self, interaction: discord.Interaction):
        """Configure Normal Monsters settings"""
        try:
            # Create a view with config file selection
            view = discord.ui.View(timeout=300)

            # Get list of config files
            config_files = [f for f in os.listdir('.') if f.endswith('.json')]

            # Create select menu for config files
            select = discord.ui.Select(
                placeholder="Select a configuration file",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(label=f, value=f)
                    for f in config_files
                ]
            )

            async def select_callback(select_interaction):
                selected_file = select_interaction.data["values"][0]
                ConfigHelper.set_current_config(selected_file)

                # Load the configuration
                with open(selected_file, "r") as f:
                    config = json.load(f)

                # Get normal monsters configuration
                normal_monsters = config.get('main', {}).get('normal_monsters', {})
                enabled = normal_monsters.get('enabled', False)
                targets = normal_monsters.get('targets', [])
                max_distance = normal_monsters.get('max_distance', 200)

                # Create embed with current configuration
                embed = discord.Embed(
                    title="Normal Monsters Configuration",
                    description=f"Configuration from: {selected_file}",
                    color=discord.Color.blue()
                )

                embed.add_field(
                    name="Status",
                    value=f"**Enabled:** {'✅' if enabled else '❌'}\n"
                          f"**Max Distance:** {max_distance}\n"
                          f"**Configured Monsters:** {len(targets)}",
                    inline=False
                )

                if targets:
                    monsters_list = []
                    for target in targets[:5]:  # Show first 5 monsters
                        monster_name = target.get('monster_name', 'Unknown')
                        monster_code = target.get('monster_code', 'N/A')
                        levels = target.get('level_ranges', [])
                        monsters_list.append(f"• **{monster_name}** (Code: {monster_code})\n  Levels: {len(levels)} ranges")

                    if len(targets) > 5:
                        monsters_list.append(f"...and {len(targets) - 5} more")

                    embed.add_field(
                        name="Configured Monsters",
                        value="\n".join(monsters_list),
                        inline=False
                    )

                # Create buttons for actions
                action_view = discord.ui.View(timeout=300)

                # Toggle enabled button
                toggle_button = discord.ui.Button(
                    label=f"{'Disable' if enabled else 'Enable'} Normal Monsters",
                    style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
                    custom_id="toggle_enabled"
                )
                action_view.add_item(toggle_button)

                # Configure distance button
                distance_button = discord.ui.Button(
                    label="Configure Max Distance",
                    style=discord.ButtonStyle.primary,
                    custom_id="configure_distance"
                )
                action_view.add_item(distance_button)

                # Configure monsters button
                monsters_button = discord.ui.Button(
                    label="Configure Monsters",
                    style=discord.ButtonStyle.primary,
                    custom_id="configure_monsters"
                )
                action_view.add_item(monsters_button)

                # Add configure troops button
                action_view.add_item(discord.ui.Button(
                    label=f"Configure Troops",
                    style=discord.ButtonStyle.primary,
                    custom_id="configure_troops"
                ))

                # Add a help button
                action_view.add_item(discord.ui.Button(
                    label="❓ Help",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"help_normal_monsters"
                ))


                async def button_callback(button_interaction):
                    if button_interaction.data["custom_id"] == "toggle_enabled":
                        await self.toggle_enabled(button_interaction)
                    elif button_interaction.data["custom_id"] == "configure_distance":
                        await self.configure_distance(button_interaction)
                    elif button_interaction.data["custom_id"] == "configure_monsters":
                        await self.configure_monsters(button_interaction)
                    elif button_interaction.data["custom_id"] == "configure_troops":
                        await self.configure_troops(button_interaction)

                for item in action_view.children:
                    item.callback = button_callback

                await select_interaction.response.send_message(
                    embed=embed,
                    view=action_view,
                    ephemeral=True
                )

            select.callback = select_callback
            view.add_item(select)

            await interaction.response.send_message(
                "Select a configuration file to manage Normal Monsters settings:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error in normal monsters setup: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def toggle_enabled(self, interaction):
        """Toggle normal monsters enabled state"""
        try:
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            if 'main' not in config:
                config['main'] = {}
            if 'normal_monsters' not in config['main']:
                config['main']['normal_monsters'] = {'enabled': False, 'targets': [], 'max_distance': 200}

            current_state = config['main']['normal_monsters']['enabled']
            config['main']['normal_monsters']['enabled'] = not current_state

            with open(ConfigHelper.current_config_file, "w") as f:
                json.dump(config, f, indent=2)

            await interaction.response.send_message(
                f"Normal Monsters {'disabled' if current_state else 'enabled'}!",
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error toggling normal monsters: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def configure_distance(self, interaction):
        """Configure max distance for normal monsters"""
        try:
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            current_distance = config.get('main', {}).get('normal_monsters', {}).get('max_distance', 200)

            modal = discord.ui.Modal(title="Configure Max Distance")
            distance_input = discord.ui.TextInput(
                label="Max Distance (tiles)",
                placeholder="Enter maximum distance (e.g., 200)",
                default=str(current_distance),
                required=True
            )
            modal.add_item(distance_input)

            async def modal_callback(modal_interaction):
                try:
                    new_distance = int(distance_input.value)
                    if new_distance < 1:
                        await modal_interaction.response.send_message(
                            "Invalid distance. Please enter a positive number.",
                            ephemeral=True
                        )
                        return

                    with open(ConfigHelper.current_config_file, "r") as f:
                        config = json.load(f)

                    if 'main' not in config:
                        config['main'] = {}
                    if 'normal_monsters' not in config['main']:
                        config['main']['normal_monsters'] = {'enabled': False, 'targets': [], 'max_distance': 200}

                    config['main']['normal_monsters']['max_distance'] = new_distance

                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(config, f, indent=2)

                    await modal_interaction.response.send_message(
                        f"Max distance updated to {new_distance} tiles!",
                        ephemeral=True
                    )

                except ValueError:
                    await modal_interaction.response.send_message(
                        "Invalid input. Please enter a valid number.",
                        ephemeral=True
                    )

            modal.on_submit = modal_callback
            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error(f"Error configuring distance: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def configure_monsters(self, interaction):
        """Configure normal monsters targets"""
        try:
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            normal_monsters = config.get('main', {}).get('normal_monsters', {})
            targets = normal_monsters.get('targets', [])

            # Create view with monster selection
            view = discord.ui.View(timeout=300)

            # Add new monster button
            add_button = discord.ui.Button(
                label="Add New Monster",
                style=discord.ButtonStyle.success,
                custom_id="add_monster"
            )
            view.add_item(add_button)

            # Select menu for existing monsters
            if targets:
                monster_select = discord.ui.Select(
                    placeholder="Select a monster to edit",
                    min_values=1,
                    max_values=1,
                    options=[
                        discord.SelectOption(
                            label=f"{target.get('monster_name', 'Unknown')}",
                            value=str(target.get('monster_code')),
                            description=f"Code: {target.get('monster_code')}"
                        )
                        for target in targets
                    ]
                )
                view.add_item(monster_select)

            async def add_button_callback(button_interaction):
                await self.add_monster(button_interaction)

            add_button.callback = add_button_callback

            if targets:
                async def select_callback(select_interaction):
                    monster_code = int(select_interaction.data["values"][0])
                    await self.edit_monster(select_interaction, monster_code)

                monster_select.callback = select_callback

            await interaction.response.send_message(
                "Select an action:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error configuring monsters: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def add_monster(self, interaction):
        """Add a new monster"""
        modal = discord.ui.Modal(title="Add New Monster")

        code_input = discord.ui.TextInput(
            label="Monster Code",
            placeholder="Enter monster code (e.g., 20200103)",
            required=True
        )
        modal.add_item(code_input)

        name_input = discord.ui.TextInput(
            label="Monster Name",
            placeholder="Enter monster name (e.g., Golem)",
            required=True
        )
        modal.add_item(name_input)

        levels_input = discord.ui.TextInput(
            label="Monster Levels",
            placeholder="Enter levels separated by comma (e.g., 4,5,6,7)",
            required=True
        )
        modal.add_item(levels_input)

        async def modal_callback(modal_interaction):
            try:
                monster_code = int(code_input.value)
                monster_name = name_input.value
                levels = [int(level.strip()) for level in levels_input.value.split(',')]

                with open(ConfigHelper.current_config_file, "r") as f:
                    config = json.load(f)

                if 'main' not in config:
                    config['main'] = {}
                if 'normal_monsters' not in config['main']:
                    config['main']['normal_monsters'] = {'enabled': False, 'targets': [], 'max_distance': 200}

                # Add new monster
                new_monster = {
                    'monster_code': monster_code,
                    'monster_name': monster_name,
                    'level_ranges': levels
                }

                config['main']['normal_monsters']['targets'].append(new_monster)

                with open(ConfigHelper.current_config_file, "w") as f:
                    json.dump(config, f, indent=2)

                await modal_interaction.response.send_message(
                    f"Added monster {monster_name} (Code: {monster_code})!",
                    ephemeral=True
                )

            except ValueError as e:
                await modal_interaction.response.send_message(
                    f"Invalid input: {str(e)}",
                    ephemeral=True
                )
            except Exception as e:
                logger.error(f"Error adding monster: {str(e)}")
                await modal_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

        modal.on_submit = modal_callback
        await interaction.response.send_modal(modal)

    async def edit_monster(self, interaction, monster_code):
        """Edit an existing monster"""
        try:
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            targets = config.get('main', {}).get('normal_monsters', {}).get('targets', [])
            monster = next((t for t in targets if t.get('monster_code') == monster_code), None)

            if not monster:
                await interaction.response.send_message(
                    f"Monster with code {monster_code} not found.",
                    ephemeral=True
                )
                return

            # Create view with edit options
            view = discord.ui.View(timeout=300)

            # Edit levels button
            edit_levels = discord.ui.Button(
                label="Edit Levels",
                style=discord.ButtonStyle.primary,
                custom_id="edit_levels"
            )
            view.add_item(edit_levels)

            # Delete monster button
            delete_button = discord.ui.Button(
                label="Delete Monster",
                style=discord.ButtonStyle.danger,
                custom_id="delete_monster"
            )
            view.add_item(delete_button)

            async def button_callback(button_interaction):
                if button_interaction.data["custom_id"] == "edit_levels":
                    await self.edit_monster_levels(button_interaction, monster_code)
                elif button_interaction.data["custom_id"] == "delete_monster":
                    await self.delete_monster(button_interaction, monster_code)

            for item in view.children:
                item.callback = button_callback

            await interaction.response.send_message(
                f"Editing {monster.get('monster_name')} (Code: {monster_code})",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error editing monster: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def edit_monster_levels(self, interaction, monster_code):
        """Edit monster levels"""
        try:
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            targets = config.get('main', {}).get('normal_monsters', {}).get('targets', [])
            monster = next((t for t in targets if t.get('monster_code') == monster_code), None)

            if not monster:
                await interaction.response.send_message(
                    f"Monster with code {monster_code} not found.",
                    ephemeral=True
                )
                return

            current_levels = monster.get('level_ranges', [])

            modal = discord.ui.Modal(title=f"Edit {monster.get('monster_name')} Levels")

            levels_input = discord.ui.TextInput(
                label="Monster Levels",
                placeholder="Enter levels separated by comma (e.g., 4,5,6,7)",
                default=",".join(map(str, current_levels)),
                required=True
            )
            modal.add_item(levels_input)

            async def modal_callback(modal_interaction):
                try:
                    new_levels = [int(level.strip()) for level in levels_input.value.split(',')]

                    with open(ConfigHelper.current_config_file, "r") as f:
                        config = json.load(f)

                    targets = config.get('main', {}).get('normal_monsters', {}).get('targets', [])
                    for target in targets:
                        if target.get('monster_code') == monster_code:
                            target['level_ranges'] = new_levels
                            break

                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(config, f, indent=2)

                    await modal_interaction.response.send_message(
                        f"Updated levels for {monster.get('monster_name')}!",
                        ephemeral=True
                    )

                except ValueError as e:
                    await modal_interaction.response.send_message(
                        f"Invalid input: {str(e)}",
                        ephemeral=True
                    )

            modal.on_submit = modal_callback
            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error(f"Error editing monster levels: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def delete_monster(self, interaction, monster_code):
        """Delete a monster"""
        try:
            with open(ConfigHelper.current_config_file, "r") as f:
                config = json.load(f)

            targets = config.get('main', {}).get('normal_monsters', {}).get('targets', [])
            monster = next((t for t in targets if t.get('monster_code') == monster_code), None)

            if not monster:
                await interaction.response.send_message(
                    f"Monster with code {monster_code} not found.",
                    ephemeral=True
                )
                return

            # Create confirmation view
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
                if button_interaction.data["custom_id"] == "confirm_delete":
                    with open(ConfigHelper.current_config_file, "r") as f:
                        config = json.load(f)

                    targets = config.get('main', {}).get('normal_monsters', {}).get('targets', [])
                    config['main']['normal_monsters']['targets'] = [
                        t for t in targets if t.get('monster_code') != monster_code
                    ]

                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(config, f, indent=2)

                    await button_interaction.response.send_message(
                        f"Deleted {monster.get('monster_name')}!",
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
                f"Are you sure you want to delete {monster.get('monster_name')}?",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error deleting monster: {str(e)}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    async def configure_troops(self, interaction):
        # Load current troop configuration
        import json  # Ensure json is available in this scope
        with open(ConfigHelper.current_config_file, "r") as f:
            config = json.load(f)

        common_troops = config.get('main', {}).get('normal_monsters', {}).get('common_troops', [])

        # Create embed for troop configuration
        embed = discord.Embed(
            title="Configure Normal Monster Troops",
            description="Configure troop amounts for normal monster attacks",
            color=discord.Color.blue()
        )

        # Show current troop configuration as a table
        if common_troops:
            # Format troops as a markdown table for better readability
            table_header = "```\n| Troop Name                   | Troop Code | Min Amount | Max Amount |\n|------------------------------|------------|------------|------------|\n"
            table_rows = []
            for troop in common_troops:
                name = troop.get('name', f"Troop #{troop.get('code')}")
                code = troop.get('code', '')
                min_amount = troop.get('min_amount', 0)
                max_amount = troop.get('max_amount', min_amount)
                # Pad the name to make the table look nice
                name_padded = name.ljust(30)[:30]
                table_rows.append(f"| {name_padded} | {code:<10} | {min_amount:<10} | {max_amount:<10} |")

            table_footer = "\n```"
            troops_table = table_header + "\n".join(table_rows) + table_footer

            embed.add_field(
                name="Current Troops",
                value=troops_table,
                inline=False
            )
            
            # Add quick help text
            embed.add_field(
                name="Quick Edit",
                value="Use the buttons below to add new troops or edit/delete existing ones.",
                inline=False
            )
        else:
            embed.add_field(
                name="Current Troops",
                value="No troops configured. Use the 'Add Troops' button below to configure troops.",
                inline=False
            )

        # Create view with troop options
        troops_view = discord.ui.View(timeout=300)

        # Get available troop data from assets to show options
        try:
            # Try to load troops from the assets file to show options
            import json
            import os
            troop_asset_path = os.path.join("lokbot", "assets", "troop.json")
            available_troops = []
            
            if os.path.exists(troop_asset_path):
                with open(troop_asset_path, "r") as f:
                    available_troops = json.load(f)
                
                # Filter to just cavalry troops for normal monsters which typically use cavalry
                cavalry_troops = [t for t in available_troops if t.get('type') == 3]
                
                # Add "Add predefined troops" button if we have cavalry troop data
                if cavalry_troops:
                    add_predefined_button = discord.ui.Button(
                        label="Add Predefined Troops",
                        style=discord.ButtonStyle.success,
                        custom_id="add_predefined_troops"
                    )
                    troops_view.add_item(add_predefined_button)
        except Exception as e:
            logger.error(f"Error loading troop assets: {str(e)}")
            # Continue without predefined troops if there's an error

        # Add buttons for troop management
        add_button = discord.ui.Button(
            label="Add New Troop",
            style=discord.ButtonStyle.primary,
            custom_id="add_troop"
        )
        troops_view.add_item(add_button)

        # Edit button for existing troops
        if common_troops:
            edit_button = discord.ui.Button(
                label="Edit Troop",
                style=discord.ButtonStyle.secondary,
                custom_id="edit_troop"
            )
            troops_view.add_item(edit_button)
            
            # Quick edit button for batch editing
            quick_edit_button = discord.ui.Button(
                label="Batch Edit All Troops",
                style=discord.ButtonStyle.primary,
                custom_id="batch_edit_troops"
            )
            troops_view.add_item(quick_edit_button)

            # Delete troop button
            delete_button = discord.ui.Button(
                label="Delete Troop",
                style=discord.ButtonStyle.danger,
                custom_id="delete_troop"
            )
            troops_view.add_item(delete_button)

        async def troop_button_callback(troop_interaction):
            custom_id = troop_interaction.data["custom_id"]
            
            if custom_id == "add_predefined_troops":
                # Create a view with predefined cavalry troops
                predefined_view = discord.ui.View(timeout=300)
                predefined_select = discord.ui.Select(
                    placeholder="Select cavalry troops to add",
                    custom_id="predefined_troops_select",
                    min_values=1,
                    max_values=len(cavalry_troops) if 'cavalry_troops' in locals() else 1
                )
                
                # Add options for each cavalry troop from assets
                if 'cavalry_troops' in locals():
                    for troop in cavalry_troops:
                        name = f"{troop.get('name', '')} (Tier {troop.get('power', 0)//5 + 1} Cavalry)"
                        code = troop.get('code', 0)
                        predefined_select.add_option(
                            label=name.capitalize(),
                            value=str(code),
                            description=f"Code: {code}"
                        )
                
                async def predefined_select_callback(select_interaction):
                    selected_codes = [int(code) for code in select_interaction.data["values"]]
                    
                    with open(ConfigHelper.current_config_file, "r") as f:
                        updated_config = json.load(f)
                    
                    if 'main' not in updated_config:
                        updated_config['main'] = {}
                    if 'normal_monsters' not in updated_config['main']:
                        updated_config['main']['normal_monsters'] = {}
                    if 'common_troops' not in updated_config['main']['normal_monsters']:
                        updated_config['main']['normal_monsters']['common_troops'] = []
                    
                    # Get existing troop codes
                    existing_codes = [t.get('code') for t in updated_config['main']['normal_monsters']['common_troops']]
                    added_troops = []
                    
                    # Add selected troops
                    for code in selected_codes:
                        if code in existing_codes:
                            continue  # Skip if already exists
                            
                        # Find troop data
                        troop_data = next((t for t in cavalry_troops if t.get('code') == code), None)
                        if troop_data:
                            tier = troop_data.get('power', 0) // 5 + 1
                            name = f"{troop_data.get('name', '')} (Tier {tier} Cavalry)"
                            
                            # Set default amounts based on tier
                            min_amount = 0
                            max_amount = 0
                            if tier <= 3:
                                min_amount = 2000
                                max_amount = 3000
                            elif tier == 4:
                                min_amount = 1000
                                max_amount = 2000
                            elif tier >= 5:
                                min_amount = 500
                                max_amount = 1000
                                
                            new_troop = {
                                'code': code,
                                'name': name.capitalize(),
                                'min_amount': min_amount,
                                'max_amount': max_amount
                            }
                            
                            updated_config['main']['normal_monsters']['common_troops'].append(new_troop)
                            added_troops.append(name.capitalize())
                    
                    # Save the updated configuration
                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(updated_config, f, indent=2)
                    
                    if added_troops:
                        await select_interaction.response.send_message(
                            f"Added {len(added_troops)} troops to configuration:\n" + 
                            "\n".join([f"• {name}" for name in added_troops]),
                            ephemeral=True
                        )
                    else:
                        await select_interaction.response.send_message(
                            "No new troops were added. All selected troops already exist in configuration.",
                            ephemeral=True
                        )
                
                predefined_select.callback = predefined_select_callback
                predefined_view.add_item(predefined_select)
                await troop_interaction.response.send_message(
                    "Select cavalry troops to add to configuration:",
                    view=predefined_view,
                    ephemeral=True
                )
                
            elif custom_id == "add_troop":
                await show_troop_modal(troop_interaction)
                
            elif custom_id == "edit_troop":
                # Show select menu for existing troops
                select_view = discord.ui.View(timeout=300)
                select = discord.ui.Select(
                    placeholder="Select a troop to edit",
                    custom_id="edit_troop_select"
                )

                for troop in common_troops:
                    name = troop.get('name', '')
                    code = troop.get('code', '')
                    min_amount = troop.get('min_amount', 0)
                    max_amount = troop.get('max_amount', 0)
                    select.add_option(
                        label=name,
                        value=str(code),
                        description=f"Min: {min_amount}, Max: {max_amount}"
                    )

                async def troop_select_callback(select_interaction):
                    selected_code = int(select_interaction.data["values"][0])
                    selected_troop = next(
                        (t for t in common_troops if t.get('code') == selected_code),
                        None
                    )
                    if selected_troop:
                        await show_troop_modal(
                            select_interaction,
                            code=selected_troop.get('code'),
                            name=selected_troop.get('name'),
                            min_amount=selected_troop.get('min_amount'),
                            max_amount=selected_troop.get('max_amount')
                        )

                select.callback = troop_select_callback
                select_view.add_item(select)
                await troop_interaction.response.send_message(
                    "Select a troop to edit:",
                    view=select_view,
                    ephemeral=True
                )
                
            elif custom_id == "batch_edit_troops":
                # Create a table view with editable fields for all troops
                batch_view = discord.ui.View(timeout=300)
                
                # Add batch adjustment button
                adjust_all_button = discord.ui.Button(
                    label="Adjust All Troops %",
                    style=discord.ButtonStyle.primary,
                    custom_id="adjust_all_troops"
                )
                
                async def adjust_all_callback(button_interaction):
                    modal = discord.ui.Modal(title="Adjust All Troops")
                    
                    percent_input = discord.ui.TextInput(
                        label="Adjustment Percentage",
                        placeholder="Enter % to adjust (e.g. -10 or +20)",
                        required=True
                    )
                    modal.add_item(percent_input)
                    
                    async def modal_callback(modal_interaction):
                        try:
                            percent = float(percent_input.value)
                            
                            with open(ConfigHelper.current_config_file, "r") as f:
                                config = json.load(f)
                            
                            troops = config['main']['normal_monsters']['common_troops']
                            for troop in troops:
                                # Adjust min and max by percentage
                                min_amount = troop.get('min_amount', 0)
                                max_amount = troop.get('max_amount', 0)
                                
                                new_min = int(min_amount * (1 + percent/100))
                                new_max = int(max_amount * (1 + percent/100))
                                
                                troop['min_amount'] = max(0, new_min)
                                troop['max_amount'] = max(0, new_max)
                            
                            with open(ConfigHelper.current_config_file, "w") as f:
                                json.dump(config, f, indent=2)
                            
                            await modal_interaction.response.send_message(
                                f"Adjusted all troop amounts by {percent}%",
                                ephemeral=True
                            )
                            
                        except ValueError:
                            await modal_interaction.response.send_message(
                                "Invalid input. Please enter a valid percentage number.",
                                ephemeral=True
                            )
                    
                    modal.on_submit = modal_callback
                    await button_interaction.response.send_modal(modal)
                
                adjust_all_button.callback = adjust_all_callback
                batch_view.add_item(adjust_all_button)
                
                # Create a button for each troop to quick edit
                for i, troop in enumerate(common_troops):
                    name = troop.get('name', f"Troop #{troop.get('code')}")
                    code = troop.get('code')
                    min_amount = troop.get('min_amount', 0)
                    max_amount = troop.get('max_amount', 0)
                    
                    # Add a button for each troop
                    button_label = f"{name} [{min_amount}-{max_amount}]"
                    button = discord.ui.Button(
                        label=button_label[:80],  # Discord has label length limit
                        style=discord.ButtonStyle.secondary,
                        custom_id=f"quick_edit_{code}"
                    )
                    batch_view.add_item(button)
                    
                    async def create_button_callback(troop_code, troop_name, troop_min, troop_max):
                        async def callback(button_interaction):
                            # Show a quick edit modal
                            modal = discord.ui.Modal(title=f"Edit {troop_name}")
                            
                            min_input = discord.ui.TextInput(
                                label="Minimum Amount",
                                placeholder="Enter minimum troop amount",
                                default=str(troop_min),
                                required=True
                            )
                            modal.add_item(min_input)
                            
                            max_input = discord.ui.TextInput(
                                label="Maximum Amount",
                                placeholder="Enter maximum troop amount",
                                default=str(troop_max),
                                required=True
                            )
                            modal.add_item(max_input)
                            
                            async def modal_callback(modal_interaction):
                                try:
                                    new_min = int(min_input.value)
                                    new_max = int(max_input.value)
                                    
                                    if new_min < 0 or new_max < new_min:
                                        await modal_interaction.response.send_message(
                                            "Invalid amounts. Maximum must be greater than or equal to minimum, and both must be non-negative.",
                                            ephemeral=True
                                        )
                                        return
                                    
                                    # Update the configuration
                                    with open(ConfigHelper.current_config_file, "r") as f:
                                        updated_config = json.load(f)
                                    
                                    for t in updated_config['main']['normal_monsters']['common_troops']:
                                        if t.get('code') == troop_code:
                                            t['min_amount'] = new_min
                                            t['max_amount'] = new_max
                                            break
                                    
                                    with open(ConfigHelper.current_config_file, "w") as f:
                                        json.dump(updated_config, f, indent=2)
                                    
                                    await modal_interaction.response.send_message(
                                        f"Updated {troop_name} to Min: {new_min}, Max: {new_max}",
                                        ephemeral=True
                                    )
                                    
                                except ValueError:
                                    await modal_interaction.response.send_message(
                                        "Invalid input. Please enter valid numbers for amounts.",
                                        ephemeral=True
                                    )
                            
                            modal.on_submit = modal_callback
                            await button_interaction.response.send_modal(modal)
                        
                        return callback
                    
                    # Create and set callback for this button
                    button.callback = await create_button_callback(code, name, min_amount, max_amount)
                
                # Add a button to save all changes
                save_button = discord.ui.Button(
                    label="Done",
                    style=discord.ButtonStyle.success,
                    custom_id=f"batch_edit_done"
                )
                
                async def save_callback(button_interaction):
                    await button_interaction.response.send_message(
                        "Click a specific troop to edit its values, or close this dialog when finished.",
                        ephemeral=True
                    )
                
                save_button.callback = save_callback
                batch_view.add_item(save_button)
                
                await troop_interaction.response.send_message(
                    "**Quick Edit Mode:** Click on a troop to edit its values:",
                    view=batch_view,
                    ephemeral=True
                )

            elif custom_id == "delete_troop":
                # Create select menu for troop deletion
                delete_view = discord.ui.View(timeout=300)
                delete_select = discord.ui.Select(
                    placeholder="Select a troop to delete",
                    custom_id="delete_troop_select"
                )

                for troop in common_troops:
                    name = troop.get('name', f"Troop #{troop.get('code')}")
                    code = troop.get('code')
                    delete_select.add_option(
                        label=name,
                        value=str(code),
                        description=f"Code: {code}"
                    )

                async def delete_select_callback(select_interaction):
                    code = int(select_interaction.data["values"][0])
                    
                    # Find troop name for confirmation
                    troop_to_delete = next((t for t in common_troops if t.get('code') == code), None)
                    if not troop_to_delete:
                        await select_interaction.response.send_message(
                            "Troop not found in configuration.",
                            ephemeral=True
                        )
                        return
                    
                    troop_name = troop_to_delete.get('name', f"Troop #{code}")
                    
                    # Create confirmation view
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
                            with open(ConfigHelper.current_config_file, "r") as f:
                                config = json.load(f)

                            troops = config['main']['normal_monsters']['common_troops']
                            config['main']['normal_monsters']['common_troops'] = [
                                t for t in troops if t.get('code') != code
                            ]

                            with open(ConfigHelper.current_config_file, "w") as f:
                                json.dump(config, f, indent=2)

                            await confirm_interaction.response.send_message(
                                f"Troop '{troop_name}' deleted successfully!",
                                ephemeral=True
                            )
                        else:
                            await confirm_interaction.response.send_message(
                                "Deletion cancelled.",
                                ephemeral=True
                            )
                    
                    for item in confirm_view.children:
                        item.callback = confirm_callback
                    
                    await select_interaction.response.send_message(
                        f"Are you sure you want to delete '{troop_name}'?",
                        view=confirm_view,
                        ephemeral=True
                    )

                delete_select.callback = delete_select_callback
                delete_view.add_item(delete_select)

                await troop_interaction.response.send_message(
                    "Select a troop to delete:",
                    view=delete_view,
                    ephemeral=True
                )

        async def show_troop_modal(interaction, code=None, name=None, min_amount=None, max_amount=None):
            modal = discord.ui.Modal(title="Add/Edit Troop")

            code_input = discord.ui.TextInput(
                label="Troop Code",
                placeholder="Enter troop code (e.g., 50100305)",
                default=str(code) if code else "",
                required=True
            )
            modal.add_item(code_input)

            name_input = discord.ui.TextInput(
                label="Troop Name",
                placeholder="Enter troop name (e.g., Dragoon T5)",
                default=name if name else "",
                required=True
            )
            modal.add_item(name_input)

            min_input = discord.ui.TextInput(
                label="Minimum Amount",
                placeholder="Enter minimum troop amount",
                default=str(min_amount) if min_amount is not None else "0",
                required=True
            )
            modal.add_item(min_input)

            max_input = discord.ui.TextInput(
                label="Maximum Amount",
                placeholder="Enter maximum troop amount",
                default=str(max_amount) if max_amount is not None else "0",
                required=True
            )
            modal.add_item(max_input)

            async def modal_callback(modal_interaction):
                try:
                    code = int(code_input.value)
                    name = name_input.value
                    min_amount = int(min_input.value)
                    max_amount = int(max_input.value)

                    if min_amount < 0 or max_amount < min_amount:
                        await modal_interaction.response.send_message(
                            "Invalid amounts. Maximum must be greater than or equal to minimum, and both must be non-negative.",
                            ephemeral=True
                        )
                        return

                    with open(ConfigHelper.current_config_file, "r") as f:
                        config = json.load(f)

                    if 'main' not in config:
                        config['main'] = {}
                    if 'normal_monsters' not in config['main']:
                        config['main']['normal_monsters'] = {}
                    if 'common_troops' not in config['main']['normal_monsters']:
                        config['main']['normal_monsters']['common_troops'] = []

                    # Update or add troop
                    troop_found = False
                    for troop in config['main']['normal_monsters']['common_troops']:
                        if troop.get('code') == code:
                            troop.update({
                                'name': name,
                                'min_amount': min_amount,
                                'max_amount': max_amount
                            })
                            troop_found = True
                            break

                    if not troop_found:
                        config['main']['normal_monsters']['common_troops'].append({
                            'code': code,
                            'name': name,
                            'min_amount': min_amount,
                            'max_amount': max_amount
                        })

                    with open(ConfigHelper.current_config_file, "w") as f:
                        json.dump(config, f, indent=2)

                    await modal_interaction.response.send_message(
                        f"Successfully {'updated' if troop_found else 'added'} troop configuration!",
                        ephemeral=True
                    )

                except ValueError:
                    await modal_interaction.response.send_message(
                        "Invalid input. Please enter valid numbers for code and amounts.",
                        ephemeral=True
                    )

            modal.on_submit = modal_callback
            await interaction.response.send_modal(modal)

        for item in troops_view.children:
            item.callback = troop_button_callback

        await interaction.response.send_message(
            embed=embed,
            view=troops_view,
            ephemeral=True
        )
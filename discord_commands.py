import discord
from discord.ext import commands, pages
from discord.commands import slash_command, Option
from discord.ui import Button, View
import json
import os
from typing import List

class ConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def config_setup(self, interaction: discord.Interaction):
        """Main entry point for the unified configuration interface - the only command needed for all bot settings"""
        try:
            print(f"[DEBUG] ====== Config Setup Started ======")
            print(f"[DEBUG] User ID: {interaction.user.id}")
            
            # Check permissions
            allowed_role_id = 508024195549102097
            has_permission = interaction.user.guild_permissions.administrator or any(role.id == allowed_role_id for role in interaction.user.roles)
            print(f"[DEBUG] Permission check result: {has_permission}")
            
            if not has_permission:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "You need administrator permission or the required role to use this command!", 
                        ephemeral=True
                    )
                return

            # Create the view with config options
            view = View()
            button = Button(label="Configure Settings", style=discord.ButtonStyle.primary)
            view.add_item(button)

            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Please select a configuration option:",
                    view=view,
                    ephemeral=True
                )
                print("[DEBUG] Initial response sent successfully")

        except discord.errors.InteractionResponded:
            print(f"[DEBUG] InteractionResponded error caught. Response state: {interaction.response.is_done()}")
            return
        except Exception as e:
            print(f"[DEBUG] Unexpected error in config setup: {e}")
            print(f"[DEBUG] Interaction state at error: {interaction.response.is_done()}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)


    # ... (rest of the ConfigCog class implementation) ...

def setup(bot):
    bot.add_cog(ConfigCog(bot))
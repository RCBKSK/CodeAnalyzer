
import discord
import json
import logging
from typing import Dict, Any, List, Optional
from lokbot.config_helper import ConfigHelper

logger = logging.getLogger(__name__)

async def show_troops_table(interaction: discord.Interaction, troops_data: List[Dict[str, Any]], title: str = "Troops Configuration") -> None:
    """Display troops in a table format with editing capabilities"""
    
    embed = discord.Embed(
        title=title,
        description="Configure troop amounts",
        color=discord.Color.blue()
    )

    # Format troops as a markdown table
    table_header = "```\n| Troop Name                   | Troop Code | Min Amount | Max Amount |\n|------------------------------|------------|------------|------------|\n"
    table_rows = []
    
    for troop in troops_data:
        name = troop.get('name', f"Troop #{troop.get('code')}")
        code = troop.get('code', '')
        min_amount = troop.get('min_amount', 0)
        max_amount = troop.get('max_amount', min_amount)
        name_padded = name.ljust(30)[:30]
        table_rows.append(f"| {name_padded} | {code:<10} | {min_amount:<10} | {max_amount:<10} |")

    table_footer = "\n```"
    troops_table = table_header + "\n".join(table_rows) + table_footer
    
    embed.add_field(
        name="Current Troops",
        value=troops_table,
        inline=False
    )

    # Create view with edit options
    view = discord.ui.View(timeout=300)

    # Add batch adjustment button
    adjust_all_button = discord.ui.Button(
        label="Adjust All Troops %",
        style=discord.ButtonStyle.primary,
        custom_id="adjust_all_troops"
    )
    view.add_item(adjust_all_button)

    # Add quick edit buttons for each troop
    for troop in troops_data:
        name = troop.get('name', f"Troop #{troop.get('code')}")
        code = troop.get('code')
        min_amount = troop.get('min_amount', 0)
        max_amount = troop.get('max_amount', 0)
        
        button_label = f"{name} [{min_amount}-{max_amount}]"
        button = discord.ui.Button(
            label=button_label[:80],
            style=discord.ButtonStyle.secondary,
            custom_id=f"quick_edit_{code}"
        )
        view.add_item(button)

    # Register button callbacks
    async def button_callback(button_interaction):
        if button_interaction.data["custom_id"] == "adjust_all_troops":
            await show_batch_adjust_modal(button_interaction, troops_data)
        else:
            troop_code = int(button_interaction.data["custom_id"].replace("quick_edit_", ""))
            await show_quick_edit_modal(button_interaction, troops_data, troop_code)

    for item in view.children:
        item.callback = button_callback

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def show_batch_adjust_modal(interaction: discord.Interaction, troops_data: List[Dict[str, Any]]) -> None:
    """Show modal for batch percentage adjustment"""
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
            
            for troop in troops_data:
                min_amount = troop.get('min_amount', 0)
                max_amount = troop.get('max_amount', 0)
                
                new_min = int(min_amount * (1 + percent/100))
                new_max = int(max_amount * (1 + percent/100))
                
                troop['min_amount'] = max(0, new_min)
                troop['max_amount'] = max(0, new_max)
            
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
    await interaction.response.send_modal(modal)

async def show_quick_edit_modal(interaction: discord.Interaction, troops_data: List[Dict[str, Any]], troop_code: int) -> None:
    """Show modal for quick editing individual troop amounts"""
    troop = next((t for t in troops_data if t.get('code') == troop_code), None)
    if not troop:
        await interaction.response.send_message("Troop not found.", ephemeral=True)
        return

    modal = discord.ui.Modal(title=f"Edit {troop.get('name', 'Troop')}")
    
    min_input = discord.ui.TextInput(
        label="Minimum Amount",
        placeholder="Enter minimum troop amount",
        default=str(troop.get('min_amount', 0)),
        required=True
    )
    modal.add_item(min_input)
    
    max_input = discord.ui.TextInput(
        label="Maximum Amount",
        placeholder="Enter maximum troop amount",
        default=str(troop.get('max_amount', 0)),
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
            
            troop['min_amount'] = new_min
            troop['max_amount'] = new_max
            
            await modal_interaction.response.send_message(
                f"Updated {troop.get('name')} to Min: {new_min}, Max: {new_max}",
                ephemeral=True
            )
            
        except ValueError:
            await modal_interaction.response.send_message(
                "Invalid input. Please enter valid numbers for amounts.",
                ephemeral=True
            )
    
    modal.on_submit = modal_callback
    await interaction.response.send_modal(modal)

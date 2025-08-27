
# LokBot Discord Commands Guide

This guide explains all available Discord commands and how to configure them in LokBot.

## Table of Contents
- [Basic Commands](#basic-commands)
- [Game Settings Commands](#game-settings-commands)
- [Rally Configuration Commands](#rally-configuration-commands)
- [Step-by-Step Configuration Guide](#step-by-step-configuration-guide)

## Basic Commands

### `/run`
Starts the bot with a specified configuration profile.

**Usage**: `/run config:[profile_name]`

**Available profiles**:
- `default` - Uses the main config.json
- `farmer_config` - Focused on resource gathering and building development
- `pvp_config` - Focused on PvP activities
- `rally_config` - Focused on rally activities

**Example**: `/run config:rally_config`

### `/alt`
Stops your currently running bot.

**Usage**: `/alt`

## Game Settings Commands

### `/game settings`
Configure general game settings including jobs, threads, object scanning, and Discord webhooks.

**Usage**: `/game settings`

This opens an interactive menu with buttons for:
- **Configure Jobs** - Manage periodic tasks like hospital recovery, wall repair, etc.
- **Configure Threads** - Manage continuous processes like free chest farming
- **Configure Object Scanning** - Set up scanning for game objects like resources and monsters
- **Configure Discord Webhooks** - Set up notifications for different events
- **List Available Configs** - View available configuration profiles

### `/game view_settings`
View all current configuration settings.

**Usage**: `/game view_settings`

Displays three embeds showing:
1. **Main Configuration** - Enabled jobs and threads
2. **Rally Configuration** - Rally join and start settings
3. **Discord Integration** - Webhook settings

## Rally Configuration Commands

### `/game rally_config`
Configure rally settings for both joining and starting rallies.

**Usage**: `/game rally_config [config_type]`

**Config Types**:
- `join` - Configure settings for joining rallies started by others
- `start` - Configure settings for starting rallies yourself
- `main` - Configure main game settings

This opens an interactive menu with options to:
- Toggle rally joining/starting on/off
- Set maximum number of marches to use
- Toggle level-based troops
- Configure monsters and troop compositions

## Step-by-Step Configuration Guide

### Setting Up Basic Configuration

1. **Start with a template**:
   ```
   /run config:farmer_config
   ```

2. **View current settings**:
   ```
   /game view_settings
   ```

3. **Configure general game settings**:
   ```
   /game settings
   ```
   
   - Click "Configure Jobs" to enable/disable tasks
   - Click "Configure Threads" to enable/disable background processes
   - Click "Configure Object Scanning" to set up scanning for resources/monsters
   - Click "Configure Discord Webhooks" to set up notifications

### Setting Up Rally Configuration

1. **Configure rally join settings**:
   ```
   /game rally_config join
   ```
   
   - Toggle rally joining on/off
   - Set maximum number of marches to use
   - Configure monsters by clicking "Configure Monsters"
   - For each monster, set up level ranges and troops to send

2. **Configure rally start settings** (if you want to start rallies):
   ```
   /game rally_config start
   ```
   
   - Toggle rally starting on/off
   - Set maximum number of marches to use
   - Configure monsters, level ranges, and rally times

### Configuring Jobs in Detail

Here's how to configure specific jobs:

1. Use `/game settings`
2. Click "Configure Jobs"
3. Select a job from the dropdown:
   - **hospital_recover** - Automatically heal troops in hospital
   - **wall_repair** - Repair city walls when damaged
   - **alliance_farmer** - Alliance activities automation
   - **mail_claim** - Claim items from mail
   - **caravan_farmer** - Manage caravans
   - **use_resource_in_item_list** - Use resource items
   - **vip_chest_claim** - Claim VIP chests
   - **harvester** - Gather resources
   - **socf_thread** - Scan for specific objects

4. For each job, you can:
   - Toggle Enable/Disable
   - Edit Interval (how often the job runs)

### Configuring Monster Targets

1. Use `/game rally_config join` or `/game rally_config start`
2. Click "Configure Monsters"
3. Select a monster from the dropdown or "Add New Monster"
4. For existing monsters, you can:
   - Edit Level Ranges (min/max levels)
   - Edit Troops (types and amounts)
   - Delete the monster configuration

5. For rally start configuration, you can also set:
   - Rally Time (in minutes)
   - Rally Message (shown when starting the rally)

### Configuring Discord Webhooks

1. Use `/game settings`
2. Click "Configure Discord Webhooks"
3. Click on the button for the webhook you want to configure
4. Enter the Discord webhook URL

Available webhook types:
- Main Webhook - General notifications
- Crystal Mine L1 Webhook - Level 1 crystal mine notifications
- Level 2+ Webhook - Level 2+ object notifications
- Level 3+ Webhook - Level 3+ object notifications
- Custom Webhook - Custom object notifications
- Dragon Soul L2+ Webhook - Dragon Soul Cavern level 2+ notifications
- Occupied Resources Webhook - Occupied resource notifications
- Rally Webhook - Rally-related notifications

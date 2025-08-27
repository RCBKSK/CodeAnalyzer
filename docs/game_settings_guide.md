
# LokBot Game Settings Guide

This guide explains all available game settings and configuration options in LokBot.

## Table of Contents
- [Command Overview](#command-overview)
- [Game Settings Configuration](#game-settings-configuration)
  - [Jobs](#jobs)
  - [Threads](#threads)
  - [Object Scanning](#object-scanning)
  - [Discord Webhooks](#discord-webhooks)
- [Rally Configuration](#rally-configuration)
  - [Rally Join Settings](#rally-join-settings)
  - [Rally Start Settings](#rally-start-settings)
- [Configuration Profiles](#configuration-profiles)

## Command Overview

The bot provides several Discord commands to manage settings:

- `/run` - Start the bot with a specified configuration
- `/alt` - Stop your currently running bot
- `/game settings` - Configure general game settings (jobs, threads, scanning)
- `/game view_settings` - View all current configuration settings
- `/rally_config` - Manage rally join and start configurations

## Game Settings Configuration

### Jobs

Jobs are periodic tasks that the bot performs at specified intervals.

| Job Name | Description | Config Parameters |
|----------|-------------|-------------------|
| `hospital_recover` | Automatically heal troops in hospital | `interval`: How often to check (seconds) |
| `wall_repair` | Repair city walls when damaged | `interval`: How often to check (seconds) |
| `alliance_farmer` | Alliance activities automation | `gift_claim`, `help_all`, `research_donate`, `shop_auto_buy_item_code_list` |
| `mail_claim` | Claim items from mail | `interval`: How often to check (seconds) |
| `caravan_farmer` | Manage caravans | `interval`: How often to check (seconds) |
| `use_resource_in_item_list` | Use resource items | `interval`: How often to check (seconds) |
| `vip_chest_claim` | Claim VIP chests | `interval`: How often to check (seconds) |
| `harvester` | Gather resources | `interval`: How often to check (seconds) |
| `socf_thread` | Scan for specific objects | `targets`, `radius`, `share_to` |

Each job has `enabled` (true/false) and `interval` parameters that control when it runs.

### Threads

Threads are continuous background processes that run while the bot is active.

| Thread Name | Description | Config Parameters |
|-------------|-------------|-------------------|
| `free_chest_farmer_thread` | Claim free chests | `enabled`: true/false |
| `quest_monitor_thread` | Monitor and claim quests | `enabled`: true/false |
| `building_farmer_thread` | Auto-manage building construction | `speedup`: Use speedups or not |
| `academy_farmer_thread` | Auto-manage research | `to_max_level`, `speedup` |
| `train_troop_thread` | Continuously train troops | `troop_code`, `speedup`, `interval` |

### Object Scanning

The object scanning feature lets you scan for specific game objects like resources, monsters, and other special features.

Configuration parameters:
- `enabled`: Enable/disable object scanning
- `notify_discord`: Send notifications to Discord
- `targets`: List of object codes and levels to scan for
- `radius`: How far to scan (distance in tiles)
- `share_to.chat_channels`: Alliance chat channels to share findings

Common object codes:
- `20100105` - Crystal Mine
- `20100106` - Dragon Soul Cavern
- `20200201` - Deathkar (Monster)
- `20200301` - Spartoi (Monster)
- `20200205` - Magdar (Monster)
- `20200202` - Green Dragon (Monster)
- `20200203` - Red Dragon (Monster)
- `20200204` - Gold Dragon (Monster)

To configure objects for scanning, modify the `socf_thread` job:
```json
{
  "name": "socf_thread",
  "enabled": true,
  "kwargs": {
    "targets": [
      {
        "code": 20100105,  // Object code
        "level": [1, 2, 3] // Levels to scan for (empty array = all levels)
      }
    ],
    "radius": 16,
    "share_to": {
      "chat_channels": [0, 0]
    }
  }
}
```

### Discord Webhooks

Discord webhook settings allow the bot to send notifications to specific Discord channels:

- `webhook_url`: General notifications
- `crystal_mine_level1_webhook_url`: Level 1 crystal mine notifications
- `level2plus_webhook_url`: Level 2+ object notifications
- `level3plus_webhook_url`: Level 3+ object notifications
- `custom_webhook_url`: Custom object notifications
- `dragon_soul_level2plus_webhook_url`: Dragon Soul Cavern level 2+ notifications
- `occupied_resources_webhook_url`: Occupied resource notifications
- `rally_webhook_url`: Rally-related notifications

## Rally Configuration

### Rally Join Settings

Rally join settings control how your bot joins rallies started by alliance members:

- `enabled`: Enable/disable rally joining
- `numMarch`: Maximum number of marches to use for rallies
- `level_based_troops`: Use different troops based on monster level
- `targets`: List of monster configurations:
  - `monster_code`: Unique identifier for the monster
  - `monster_name`: Display name
  - `level_ranges`: Configs for different level ranges:
    - `min_level`/`max_level`: Level range
    - `troops`: What troops to send (code, name, min/max amount)

### Rally Start Settings

Rally start settings control how your bot initiates rallies:

- `enabled`: Enable/disable rally starting
- `numMarch`: Maximum number of marches to use
- `level_based_troops`: Use different troops based on monster level
- `targets`: List of monster configurations:
  - `monster_code`: Unique identifier for the monster
  - `monster_name`: Display name
  - `level_ranges`: Configs for different level ranges:
    - `min_level`/`max_level`: Level range
    - `troops`: What troops to send (code, name, min/max amount)
    - `rally_time`: How long to set the rally timer (minutes)
    - `message`: Rally message to display

## Configuration Profiles

The bot supports multiple configuration profiles located in the `configs/` directory:

- `farmer_config.json`: Focused on resource gathering and building development
- `pvp_config.json`: Focused on PvP with troop training and minimal farming
- `rally_config.json`: Focused on rally activities with minimal other activities

Use these profiles when starting the bot:
```
/run config:rally_config
```

## Best Practices

1. Start with a predefined profile that best matches your gameplay style
2. Adjust settings through Discord commands rather than editing files directly
3. For object scanning, focus on high-value targets like Crystal Mines
4. Set reasonable intervals for jobs to avoid excessive API calls
5. Use webhooks to get notifications about important events

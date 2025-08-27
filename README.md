
# LokBot - League of Kingdoms Bot Management System

A comprehensive bot management system for League of Kingdoms with both Discord and web interfaces.

## Overview

LokBot is a multi-user bot management platform that allows users to:
- Run automated game bots for League of Kingdoms
- Manage bot instances through a web interface or Discord commands
- Configure rally joining, monster attacks, resource gathering, and more
- Monitor bot activity with real-time notifications
- Schedule automated tasks and maintenance

## Features

### Web Interface
- **Bot Management**: Start, stop, and monitor multiple bot instances
- **Real-time Notifications**: Live updates on bot activities via Server-Sent Events
- **Configuration Editor**: User-friendly interface for editing bot configurations
- **User Management**: Multi-user support with instance limits
- **Scheduling**: Schedule bot starts/stops and configuration changes
- **Simple Config Wizard**: Easy setup for common bot configurations

### Discord Integration
- **Bot Commands**: Start/stop bots directly from Discord
- **Status Monitoring**: Check bot status and receive notifications
- **Configuration Commands**: Modify rally, monster, and gathering settings
- **User Authentication**: Secure login with email/password or tokens

### Bot Capabilities
- **Rally Management**: Automatically join or start rallies
- **Monster Attacks**: Attack field monsters for resources
- **Resource Gathering**: Collect resources from map objects
- **Object Scanning**: Find and report crystal mines, dragon souls, etc.
- **Building Management**: Upgrade buildings and research
- **Hospital Recovery**: Automatically heal wounded troops

## Project Structure

```
lokbot/
├── web_app.py              # Main Flask web application
├── discord_bot.py          # Discord bot implementation
├── lokbot/                 # Core bot logic and modules
│   ├── farmer.py          # Main bot farming logic
│   ├── client.py          # Game API client
│   ├── config_helper.py   # Configuration management
│   └── assets/            # Game data (buildings, troops, etc.)
├── templates/             # HTML templates for web interface
├── data/                  # User configurations and bot data
├── config*.json          # Bot configuration files
└── users.txt             # User authentication file
```

## Quick Start

### 1. Environment Setup
Set the following secrets in Replit:
- `LOK_EMAIL`: Your League of Kingdoms email
- `LOK_PASSWORD`: Your League of Kingdoms password
- `DISCORD_BOT_TOKEN`: Discord bot token (optional)

### 2. User Configuration
Edit `users.txt` to add users:
```
username:password:max_instances
admin:admin123:10
user1:password1:2
```

### 3. Run the Application
Click the Run button to start the web application. The app will be available at the provided URL.

## Configuration Files

The bot uses JSON configuration files for different scenarios:

- `config.json` - Main configuration template
- `config_rally_join.json` - Rally joining settings
- `config_monster_attack.json` - Monster attack settings
- `config_gathering.json` - Resource gathering settings

Each user gets their own configuration file created automatically.

## Web Interface Usage

1. **Login**: Use credentials from `users.txt`
2. **Start Bot**: Provide game credentials and select configuration
3. **Monitor**: View real-time notifications and bot status
4. **Configure**: Edit bot settings through the web interface
5. **Manage**: Stop/start instances as needed

## Discord Commands

- `/run` - Start a bot instance
- `/stop` - Stop bot instances  
- `/status` - Check bot status
- `/config` - Modify bot configurations
- `/login_with_token` - Start bot with authentication token
- `/login_with_email` - Start bot with email/password

## API Endpoints

The web application provides a REST API for:
- Bot management (`/api/start_bot`, `/api/stop_bot`)
- Configuration (`/api/config`, `/api/rally_config`)
- Notifications (`/api/notifications/stream`)
- User management (`/api/users`)

## Development

### Adding New Features

1. **Bot Logic**: Add new functionality in `lokbot/farmer.py`
2. **API Endpoints**: Create new routes in `web_app.py`
3. **Discord Commands**: Add commands in `discord_bot.py`
4. **Configuration**: Update config files and `config_helper.py`

### Configuration Structure

Bot configurations support:
- Rally settings (join/start parameters)
- Monster attack configurations
- Object scanning targets
- Troop compositions
- Building upgrade priorities
- Research paths

## Security

- Session-based authentication for web interface
- User access controls for configuration files
- Process isolation per user
- Secure token handling for game authentication

## Deployment

This project is configured for Replit deployment with:
- Automatic package installation
- Health checks on `/health` endpoint
- Port configuration for web access
- Background process management

## Support

The bot includes comprehensive error handling, logging, and notification systems to help troubleshoot issues. Check the web interface notifications or Discord messages for bot status updates.

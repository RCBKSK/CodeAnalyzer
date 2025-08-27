
# LokBot - Automated Game Bot for League of the Kingdoms

LokBot is a comprehensive automation bot for League of the Kingdoms game, imported from https://github.com/RCBKSK/new-dev/. This sophisticated system features 4335+ lines of game automation logic, Discord bot integration, and a full-featured web control panel. The bot automates various game activities including rally participation, monster attacks, resource gathering, and advanced object scanning.

## Recent Changes (August 27, 2025)
- ✅ **Successfully imported complete bot from GitHub repository**
- ✅ **Fixed worker timeout issues in notification streaming**
- ✅ **Deployed working Flask web application**
- ✅ **Integrated lokbot module with advanced game automation**
- ✅ **Set up multi-configuration support for different automation modes**

## Features

- **Web Control Panel**: Modern web interface for bot management
- **Discord Bot Integration**: Control bots through Discord commands
- **Multi-Instance Support**: Run multiple bot instances simultaneously
- **Rally Automation**: Automatically join and start rallies
- **Monster Attack Automation**: Attack monsters automatically
- **Resource Gathering**: Automated resource collection
- **Object Scanning**: Scan for valuable objects like Crystal Mines and Dragon Souls
- **User Management**: Multi-user support with instance limits
- **Real-time Notifications**: Live updates on bot activities
- **Scheduling System**: Schedule bot tasks and maintenance

## Quick Start

1. **Set up environment variables**:
   - Go to the Secrets tab in Replit
   - Add `LOK_EMAIL` with your game email
   - Add `LOK_PASSWORD` with your game password

2. **Configure users** (optional):
   - Edit `users.txt` to add users in format: `username:password:max_instances`
   - Default admin user exists with unlimited instances

3. **Run the application**:
   - Click the Run button to start the web application
   - Access the web interface at the provided URL
   - Login with your configured credentials

## Project Structure

- `web_app.py` - Main Flask web application
- `discord_bot.py` - Discord bot implementation
- `lokbot/` - Core bot logic and modules
- `templates/` - HTML templates for web interface
- `data/` - User configurations and bot data
- `config*.json` - Bot configuration files

## Configuration

The bot uses JSON configuration files for different scenarios:
- `config.json` - Main configuration
- `config_rally_join.json` - Rally joining settings
- `config_monster_attack.json` - Monster attack settings
- `config_gathering.json` - Resource gathering settings

## Web Interface

The web interface provides:
- Bot instance management
- Real-time activity monitoring
- Configuration editing
- User management (admin only)
- Notification system
- Simple configuration wizard

## Discord Commands

- `/run` - Start a bot instance
- `/stop` - Stop bot instances
- `/status` - Check bot status
- Various configuration commands

## Technologies Used

- **Backend**: Python Flask
- **Frontend**: HTML, CSS, JavaScript
- **Database**: File-based storage
- **Authentication**: Session-based
- **Real-time Updates**: Server-Sent Events
- **Scheduling**: APScheduler

## Deployment

This project is ready for deployment on Replit. The web application runs on port 5000 and includes health checks and proper error handling.

## Security

- Session-based authentication
- User access controls
- Config file permissions
- Process isolation per user

## Support

For issues or questions, check the configuration files and logs. The bot includes comprehensive error handling and logging.

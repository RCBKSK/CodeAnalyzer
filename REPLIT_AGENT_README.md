
# LokBot - Replit Agent Integration

## Overview
LokBot is now fully compatible with Replit Agent. This bot management system provides automated League of Kingdoms gameplay with a comprehensive web interface and Discord integration.

## Replit Agent Features
- ✅ **Auto-setup**: Run `python replit_setup.py` for automatic environment configuration
- ✅ **Health Monitoring**: Built-in health checks at `/health` endpoint
- ✅ **Secrets Integration**: Uses Replit Secrets for secure credential storage
- ✅ **Multi-user Support**: Role-based access control with admin features
- ✅ **Real-time Updates**: Server-Sent Events for live notifications
- ✅ **Configuration Management**: JSON-based config system with user isolation

## Quick Start with Replit Agent

### 1. Set Required Secrets
In the Replit Secrets tab, add:
- `LOK_EMAIL`: Your League of Kingdoms account email
- `LOK_PASSWORD`: Your League of Kingdoms account password
- `DISCORD_BOT_TOKEN`: (Optional) For Discord integration

### 2. Initialize Environment
The setup script will automatically:
- Create necessary directories (`data/`, `templates/`, `static/`)
- Generate default configuration files
- Create admin user account
- Set up user management system

### 3. Access the Application
- **Web Interface**: Click Run button, access via provided URL
- **Default Login**: `admin` / `admin123`
- **Health Check**: Available at `/health`

## Project Structure for Replit Agent

```
LokBot/
├── web_app.py              # Main Flask application
├── discord_bot.py          # Discord bot interface
├── replit_setup.py         # Replit environment setup
├── lokbot/                 # Core bot logic
│   ├── farmer.py           # Main automation engine
│   ├── client.py           # Game API client
│   └── config_helper.py    # Configuration management
├── templates/              # Web interface templates
├── static/                 # Static web assets
├── data/                   # User configurations and tokens
├── config*.json            # Bot configuration files
├── users.txt               # User authentication
└── user_config_assignments.txt  # Config assignments
```

## Configuration System

### Bot Configurations
- `config.json` - Main configuration template
- `config_rally_join.json` - Rally joining settings
- `config_monster_attack.json` - Monster attack automation
- `config_gathering.json` - Resource gathering settings

### User Management
- **Format**: `username:password:max_instances:role:start_date:end_date:created_date`
- **Roles**: `user`, `admin`, `super_admin`
- **Config Assignment**: Map users to specific configuration files

## Web Interface Features

### Dashboard
- Real-time bot status monitoring
- Instance management (start/stop/configure)
- Live notification feed
- Configuration editor

### Admin Features
- User management and role assignment
- System monitoring and analytics
- Configuration assignment to users
- Temporary test account creation

### Simple Config Builder
- User-friendly configuration interface
- Preset templates for common scenarios
- Real-time validation and preview

## API Endpoints

### Bot Management
- `POST /api/start_bot` - Start bot instance
- `POST /api/stop_bot` - Stop bot instances
- `GET /api/status` - Get bot status

### Configuration
- `GET/POST /api/config` - Manage configurations
- `GET /api/config_files` - List available configs
- `POST /api/config/delete` - Delete configurations

### Notifications
- `GET /api/notifications/stream` - Real-time event stream
- `GET /api/notifications/history` - Notification history
- `POST /api/notifications/clear` - Clear notifications

### User Management (Admin)
- `GET/POST /api/users` - Manage users
- `GET /api/admin/user_activity_monitor` - Activity monitoring
- `GET /api/admin/session_monitor` - Session analytics

## Discord Integration

### Commands
- `/run` - Start bot instance
- `/stop` - Stop bot instances
- `/status` - Check bot status
- `/config` - Configuration management

### Features
- Real-time status updates via DMs
- Command permissions based on user roles
- Integration with web user system

## Security Features

### Authentication
- Session-based web authentication
- Role-based access control
- Configuration file access restrictions

### Process Isolation
- User-specific bot instances
- Isolated configuration spaces
- Secure token management

## Monitoring & Debugging

### Health Checks
- Application health at `/health`
- Bot instance monitoring
- Real-time status updates

### Logging
- Comprehensive application logging
- Bot activity tracking
- Error reporting and notifications

### Analytics
- User activity monitoring
- Bot performance metrics
- System resource tracking

## Development with Replit Agent

### Adding Features
1. **Bot Logic**: Extend `lokbot/farmer.py`
2. **Web Endpoints**: Add to `web_app.py`
3. **Discord Commands**: Modify `discord_bot.py`
4. **Configurations**: Create new JSON config files

### Best Practices
- Use existing error handling patterns
- Follow JSON schema for configurations
- Implement proper user permission checks
- Add comprehensive logging

### Testing
- Use health check endpoint for monitoring
- Test with multiple user accounts
- Verify configuration isolation
- Check real-time notification delivery

## Deployment

This project is pre-configured for Replit deployment:
- Port 5000 configured for web access
- Health monitoring included
- Environment variable integration
- Multi-user session management
- Production-ready error handling

The application automatically handles Replit's environment and provides a seamless experience for both development and production use.

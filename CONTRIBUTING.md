
# Contributing to LokBot

This guide helps the Replit Agent understand how to contribute to and modify the LokBot project.

## Architecture Overview

LokBot is built with a multi-interface architecture:

### Core Components

1. **Web Application** (`web_app.py`)
   - Flask-based web interface
   - Real-time notifications via Server-Sent Events
   - REST API for bot management
   - User authentication and session management

2. **Discord Bot** (`discord_bot.py`)
   - Discord.py based bot interface
   - Slash commands for bot control
   - Real-time status updates via DMs

3. **Bot Engine** (`lokbot/farmer.py`)
   - Main automation logic
   - Game API interactions
   - Multi-threaded task execution

4. **Configuration System** (`lokbot/config_helper.py`)
   - JSON-based configuration management
   - Per-user configuration isolation
   - Dynamic configuration updates

### Key Files and Their Purposes

#### Main Application Files
- `web_app.py` - Flask web server and API endpoints
- `discord_bot.py` - Discord bot implementation
- `lokbot/farmer.py` - Core bot automation logic
- `lokbot/client.py` - Game API client

#### Configuration Files
- `config.json` - Main configuration template
- `config_*.json` - Specialized configuration files
- `users.txt` - User authentication file
- `user_config_assignments.txt` - User-to-config mapping

#### Web Interface
- `templates/` - HTML templates for web interface
- `static/` - Static assets (CSS, JS, images)

#### Bot Assets
- `lokbot/assets/` - Game data (buildings, troops, monsters)

## Adding New Features

### 1. Adding Web API Endpoints

Add new routes to `web_app.py`:

```python
@app.route('/api/new_feature', methods=['GET', 'POST'])
@login_required
def handle_new_feature():
    # Implementation here
    pass
```

### 2. Adding Discord Commands

Add commands to `discord_bot.py` or create new command groups in `lokbot/discord_commands.py`:

```python
@tree.command(name="new_command", description="Description")
async def new_command(interaction: discord.Interaction):
    # Implementation here
    pass
```

### 3. Adding Bot Functionality

Extend `lokbot/farmer.py` with new automation features:

```python
def new_bot_feature(self):
    """Add new bot automation feature"""
    # Implementation here
    pass
```

### 4. Configuration Changes

Update configuration structure in relevant config files and modify `lokbot/config_helper.py` if needed.

## Common Modification Patterns

### Adding User Management Features

1. Modify `web_app.py` for web interface
2. Update `users.txt` format if needed
3. Add corresponding Discord commands if applicable

### Adding Bot Configurations

1. Create new config section in JSON files
2. Update `lokbot/config_helper.py` to handle new config
3. Add web interface for configuration
4. Add Discord commands for configuration

### Adding Notifications

1. Update notification system in `web_app.py`
2. Modify bot logic to send notifications
3. Update Discord webhook integration if needed

## File Organization

### Configuration Files
- Keep user-specific configs in `data/` directory
- Use descriptive names for config files
- Maintain JSON schema consistency

### Bot Logic
- Keep core logic in `lokbot/` directory
- Separate concerns (API client, automation, utilities)
- Use proper error handling and logging

### Web Interface
- Templates in `templates/` directory
- Static assets in `static/` directory
- Follow Flask best practices

## Code Style

### Python Code
- Follow PEP 8 style guidelines
- Use descriptive variable and function names
- Add docstrings for complex functions
- Use proper exception handling

### Configuration Files
- Use consistent JSON formatting
- Add comments where applicable
- Validate configuration structure

### Web Interface
- Use responsive design principles
- Maintain consistent UI/UX
- Follow accessibility guidelines

## Testing

### Local Testing
- Test web interface at `http://localhost:5000`
- Test Discord commands in development server
- Verify bot functionality with test configurations

### Error Handling
- Check logs for error messages
- Use try-catch blocks appropriately
- Provide meaningful error messages to users

## Security Considerations

### Authentication
- Validate user permissions for all operations
- Use secure session management
- Protect sensitive configuration data

### Configuration Access
- Implement proper file access controls
- Validate user ownership of configurations
- Sanitize user inputs

## Deployment

### Replit Deployment
- Ensure all dependencies are in `requirements.txt`
- Use environment variables for sensitive data
- Configure proper port forwarding

### Environment Variables
- `LOK_EMAIL` - Game account email
- `LOK_PASSWORD` - Game account password
- `DISCORD_BOT_TOKEN` - Discord bot token (optional)

This structure helps maintain code quality and makes it easier for the Replit Agent to understand and modify the project effectively.

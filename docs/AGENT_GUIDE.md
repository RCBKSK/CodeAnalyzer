
# Replit Agent Guide for LokBot

This guide provides specific information for the Replit Agent on how to work with the LokBot project.

## Project Understanding

LokBot is a sophisticated bot management system for the game "League of Kingdoms" with the following key characteristics:

### Primary Functions
1. **Game Automation**: Automates various in-game activities like rally joining, monster attacks, resource gathering
2. **Multi-User Management**: Supports multiple users with different permission levels
3. **Real-Time Monitoring**: Provides live notifications and status updates
4. **Configuration Management**: Flexible JSON-based configuration system

### Interface Types
- **Web Interface**: Primary user interface via Flask web app
- **Discord Interface**: Bot commands via Discord integration
- **API Interface**: RESTful endpoints for programmatic access

## Common Modification Scenarios

### 1. Adding New Bot Features

**Location**: `lokbot/farmer.py`
**Pattern**: Add new methods to the `Farmer` class
**Example**: Adding a new automation feature

```python
def new_automation_feature(self):
    """Add new automation capability"""
    try:
        # Feature implementation
        self.logger.info("New feature executed")
    except Exception as e:
        self.logger.error(f"Feature error: {e}")
```

### 2. Adding Web Interface Features

**Location**: `web_app.py`
**Pattern**: Add new routes with proper authentication
**Example**: New API endpoint

```python
@app.route('/api/new_feature', methods=['GET', 'POST'])
@login_required
def new_feature():
    user_id = session['user_id']
    # Implementation
    return jsonify({'success': True})
```

### 3. Adding Discord Commands

**Location**: `discord_bot.py` or `lokbot/discord_commands.py`
**Pattern**: Use Discord.py slash commands
**Example**: New Discord command

```python
@tree.command(name="new_command", description="New command description")
async def new_command(interaction: discord.Interaction):
    await interaction.response.send_message("Command executed", ephemeral=True)
```

### 4. Configuration Changes

**Location**: Various `config*.json` files and `lokbot/config_helper.py`
**Pattern**: Extend JSON schema and update helper functions

## File Modification Guidelines

### High-Frequency Modification Files
- `web_app.py` - Main web application logic
- `lokbot/farmer.py` - Core bot automation
- `config*.json` - Bot behavior configurations
- `discord_bot.py` - Discord interface

### Low-Frequency Modification Files
- `lokbot/client.py` - Game API client (stable)
- `lokbot/assets/` - Game data (rarely changes)
- `requirements.txt` - Dependencies (only when adding new packages)

### Configuration Files
- User-specific configs go in `data/` directory
- Template configs remain in root directory
- Always validate JSON structure after modifications

## Key Patterns to Follow

### 1. Error Handling
Always wrap operations in try-catch blocks:
```python
try:
    # Operation
    logger.info("Success message")
except Exception as e:
    logger.error(f"Error: {e}")
    return error_response
```

### 2. User Authentication
Web endpoints should use the `@login_required` decorator:
```python
@app.route('/api/endpoint')
@login_required
def endpoint():
    user_id = session['user_id']
    # Implementation
```

### 3. Configuration Access
Use the ConfigHelper for configuration operations:
```python
from lokbot.config_helper import ConfigHelper
config = ConfigHelper.load_config()
ConfigHelper.save_config(config)
```

### 4. Notifications
Add notifications for user feedback:
```python
add_notification(user_id, "type", "Title", "Message")
```

## Environment Setup

### Required Secrets
- `LOK_EMAIL` - Game account email
- `LOK_PASSWORD` - Game account password

### Optional Secrets
- `DISCORD_BOT_TOKEN` - For Discord integration

### Configuration Files
- Ensure `users.txt` exists with at least admin user
- Maintain `config.json` as the base template
- Keep `user_config_assignments.txt` for user permissions

## Testing Approach

### Web Interface Testing
1. Start the application
2. Login at the web interface
3. Test new features through the UI
4. Check browser console for errors
5. Monitor server logs

### Discord Testing
1. Ensure Discord bot token is set
2. Test commands in Discord server
3. Check bot logs for errors

### Bot Functionality Testing
1. Use test configurations
2. Monitor bot behavior through notifications
3. Check logs for proper execution

## Common Issues and Solutions

### Configuration Errors
- Validate JSON syntax
- Check file permissions
- Ensure proper configuration structure

### Authentication Issues
- Verify credentials in Secrets
- Check user file format
- Validate session management

### Bot Execution Problems
- Check game API connectivity
- Verify configuration parameters
- Monitor resource usage

## Best Practices for Agent

### 1. Understand Context
- Review related files before making changes
- Understand the flow between web, Discord, and bot components
- Consider user impact of modifications

### 2. Maintain Consistency
- Follow existing code patterns
- Use consistent naming conventions
- Maintain JSON schema integrity

### 3. Preserve Functionality
- Test changes thoroughly
- Maintain backward compatibility
- Document significant changes

### 4. Security Awareness
- Validate user inputs
- Maintain access controls
- Protect sensitive data

This guide helps the Replit Agent understand the project structure and make appropriate modifications while maintaining system integrity and functionality.

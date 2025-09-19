
# LokBot - Automated Game Bot for League of the Kingdoms

## ⚠️ CRITICAL WARNING FOR REPLIT AGENTS ⚠️

**HIGH PRIORITY DEVELOPMENT GUIDELINES:**

🚨 **DO NOT MAKE UNAUTHORIZED CHANGES** 🚨

1. **Follow Instructions EXACTLY** - Only implement what is specifically requested by the user
2. **NO Scope Creep** - Do not add features, modify UI elements, or change functionality that wasn't explicitly asked for  
3. **ASK Before Major Changes** - Always seek permission before making significant modifications to existing working systems
4. **Understand Before Acting** - Thoroughly analyze the existing codebase structure before making any changes
5. **Test Existing Functionality** - Ensure you understand how current features work before attempting modifications
6. **Preserve Working Features** - Do not break or modify existing functionality while adding new features

**RECENT LESSON LEARNED (Sept 6, 2025):**
- Rally Join/Start troops were ALREADY configured correctly (per-monster troops)  
- Agent incorrectly added general troops sections without understanding the existing architecture
- Caused confusion and required rollback of unnecessary changes
- Always examine existing code structure before assuming something is missing

**Remember: Users hire agents to be precise and follow directions, not to make arbitrary improvements!**

---

LokBot is a comprehensive automation bot for League of the Kingdoms game, imported from https://github.com/RCBKSK/new-dev/. This sophisticated system features 4335+ lines of game automation logic, Discord bot integration, and a full-featured web control panel. The bot automates various game activities including rally participation, monster attacks, resource gathering, and advanced object scanning.

## Recent Changes (September 3, 2025)
- ✅ **Implemented VIP Shop Farmer Thread - runs after caravan**
- ✅ **Added automatic VIP shop purchasing with priority system**
- ✅ **Fixed simple config page to auto-add VIP shop job when enabled**
- ✅ **Added VIP Shop Buy API Endpoint (`/api/vip_shop/buy`)**
- ✅ **Implemented complete VIP shop purchase functionality**
- ✅ **Added security validation and instance ownership checks**
- ✅ **Integrated with existing bot authentication system**
- ✅ **Added purchase notifications and comprehensive error handling**
- ✅ **Fixed missing buy method in VIP shop implementation**

## Previous Changes (September 2, 2025)
- ✅ **Added complete game data from latest table file**
- ✅ **Integrated 712 items with stats, abilities, costs, categories**
- ✅ **Added 254 abilities for optimization calculations**
- ✅ **Included 105 alliance skills (askill) for coordination**
- ✅ **Added 287 personal skills (pskill) for progression**
- ✅ **Enhanced bot capabilities with comprehensive item management**

## Previous Changes (September 1, 2025)
- ✅ **Enhanced Alliance Shop Farmer with comprehensive item selection**
- ✅ **Added 80+ alliance shop items with descriptions and categories**
- ✅ **Implemented priority-based purchasing system**
- ✅ **Added quantity controls (min/max buy amounts)**
- ✅ **Created intuitive web interface for shop configuration**
- ✅ **Maintained backward compatibility with existing configurations**

## Previous Changes (August 27, 2025)
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

## ⚠️ CRITICAL REPLIT CONFIGURATION SETTINGS ⚠️

**IMPORTANT**: This project requires specific Replit configuration settings to run properly. The `.replit` file contains essential settings that must always be maintained:

```toml
modules = ["python-3.11", "web", "nodejs-20"]
run = "python main.py"

[nix]
channel = "stable-25_05"
packages = ["cacert", "geckodriver", "glibcLocales", "libev", "openssl", "postgresql"]

[deployment]
run = ["python", "main.py"]

[workflows]
runButton = "Project"

[[workflows.workflow]]
name = "Project"
mode = "parallel"
author = "agent"

[[workflows.workflow.tasks]]
task = "workflow.run"
args = "Start application"

[[workflows.workflow]]
name = "Start application"
author = "agent"

[[workflows.workflow.tasks]]
task = "shell.exec"
args = "python main.py"
waitForPort = 5000

[[ports]]
localPort = 5000
externalPort = 5000

[agent]
```

**DO NOT MODIFY** these configuration settings unless absolutely necessary, as they ensure:
- Proper Python 3.11 environment
- Required system packages for web scraping and automation
- Correct workflow execution
- Proper port configuration for web access

**IMPORTANT NOTE**: All required environment variables (LOK_EMAIL, LOK_PASSWORD, etc.) and dependencies will be installed by the user as needed. The project uses Flask development server for all deployments.

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

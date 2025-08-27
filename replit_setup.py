
#!/usr/bin/env python3
"""
Replit setup script for LokBot
This script helps configure the environment for Replit deployment
"""

import os
import json
import sys

def setup_replit_environment():
    """Setup environment variables and configuration for Replit"""
    print("🚀 Setting up LokBot for Replit...")
    print("📋 Replit Agent Compatible Setup")
    
    # Check if required secrets are set
    required_secrets = ['LOK_EMAIL', 'LOK_PASSWORD']
    missing_secrets = []
    
    for secret in required_secrets:
        if not os.getenv(secret):
            missing_secrets.append(secret)
    
    if missing_secrets:
        print("❌ Missing required secrets:")
        for secret in missing_secrets:
            print(f"   - {secret}")
        print("\n🔧 To set secrets in Replit:")
        print("   1. Click on 'Secrets' tab in the left sidebar")
        print("   2. Add each secret with its value")
        print("   3. Restart the application")
        print("\nOptional: DISCORD_BOT_TOKEN for Discord integration")
        return False
    
    # Create default directories if they don't exist
    os.makedirs('data', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    # Create default users.txt if it doesn't exist
    if not os.path.exists('users.txt'):
        with open('users.txt', 'w') as f:
            f.write('admin:admin123:10\n')
        print("✅ Created default users.txt")
    
    # Create default config files if they don't exist
    config_files = [
        'config.json',
        'config_rally_join.json',
        'config_monster_attack.json',
        'config_gathering.json'
    ]
    
    for config_file in config_files:
        if not os.path.exists(config_file):
            # Create basic config structure
            basic_config = {
                "name": config_file.replace('.json', ''),
                "actions": {
                    "collectResources": True,
                    "collectVip": True,
                    "useHelp": True
                },
                "settings": {
                    "delay": 60,
                    "maxRuns": 100
                }
            }
            
            with open(config_file, 'w') as f:
                json.dump(basic_config, f, indent=2)
            print(f"✅ Created default {config_file}")
    
    print("\n🎉 LokBot is ready for Replit!")
    print("📋 Next steps:")
    print("1. Make sure your secrets are set (LOK_EMAIL, LOK_PASSWORD)")
    print("2. Click the Run button to start the web application")
    print("3. Access the web interface at the provided URL")
    print("4. Login with admin:admin123 (or your configured credentials)")
    print("\n🤖 Replit Agent Integration:")
    print("- Health check available at /health")
    print("- Multi-user support enabled")
    print("- Real-time notifications configured")
    print("- Configuration management ready")
    
    # Create a simple health check indicator
    try:
        with open('.replit-health', 'w') as f:
            f.write('setup_complete')
        print("✅ Health check indicator created")
    except Exception as e:
        print(f"⚠️  Could not create health indicator: {e}")
    
    return True

if __name__ == '__main__':
    setup_replit_environment()

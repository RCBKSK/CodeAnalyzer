
import json
import os
from lokbot import logger

class ConfigConverter:
    """Utility to convert between simplified and full configuration formats"""
    
    @staticmethod
    def convert_simplified_to_full(simplified_config_file, output_file="config.json"):
        """Convert a simplified config to full config format"""
        try:
            with open(simplified_config_file, 'r') as f:
                simplified = json.load(f)
            
            # Load existing full config or create new one
            try:
                with open(output_file, 'r') as f:
                    full_config = json.load(f)
            except FileNotFoundError:
                full_config = ConfigConverter._get_base_full_config()
            
            # Merge simplified config into full config
            if 'rally_join' in simplified:
                if 'rally' not in full_config:
                    full_config['rally'] = {}
                full_config['rally']['join'] = {
                    'enabled': simplified['rally_join']['enabled'],
                    'numMarch': simplified['rally_join']['max_marches'],
                    'level_based_troops': True,
                    'targets': simplified['rally_join']['targets']
                }
            
            if 'monster_attack' in simplified:
                if 'main' not in full_config:
                    full_config['main'] = {}
                if 'normal_monsters' not in full_config['main']:
                    full_config['main']['normal_monsters'] = {}
                
                full_config['main']['normal_monsters'] = {
                    'enabled': simplified['monster_attack']['enabled'],
                    'max_distance': simplified['monster_attack']['max_distance'],
                    'common_troops': simplified['monster_attack']['troops'],
                    'targets': simplified['monster_attack']['targets']
                }
            
            if 'gathering' in simplified:
                if 'main' not in full_config:
                    full_config['main'] = {}
                if 'object_scanning' not in full_config['main']:
                    full_config['main']['object_scanning'] = {}
                
                full_config['main']['object_scanning'].update({
                    'enabled': simplified['gathering']['enabled'],
                    'max_marches': simplified['gathering']['max_marches'],
                    'enable_gathering': True,
                    'objects': {str(target['resource_code']): target for target in simplified['gathering']['targets']}
                })
            
            # Save the full config
            with open(output_file, 'w') as f:
                json.dump(full_config, f, indent=2)
            
            logger.info(f"Converted {simplified_config_file} to {output_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error converting config: {str(e)}")
            return False
    
    @staticmethod
    def _get_base_full_config():
        """Return a minimal base full config structure"""
        return {
            "main": {
                "jobs": [],
                "threads": [],
                "normal_monsters": {
                    "enabled": False,
                    "targets": [],
                    "max_distance": 200
                },
                "object_scanning": {
                    "enabled": False,
                    "objects": {}
                }
            },
            "rally": {
                "join": {
                    "enabled": False,
                    "numMarch": 8,
                    "level_based_troops": True,
                    "targets": []
                },
                "start": {
                    "enabled": False,
                    "numMarch": 6,
                    "level_based_troops": True,
                    "targets": []
                }
            },
            "discord": {
                "enabled": False,
                "webhook_url": ""
            },
            "socketio": {
                "debug": false
            }
        }

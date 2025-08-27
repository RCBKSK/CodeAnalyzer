import json
import logging.handlers
import os
import pathlib
import sys

from loguru import logger

project_root = pathlib.Path(__file__).parent.parent

project_root.joinpath('data').mkdir(exist_ok=True)


def load_config(config_name=None):
    os.chdir(project_root)
    
    # First check environment variable for config
    env_config = os.environ.get('LOKBOT_CONFIG')
    if env_config:
        config_name = env_config

    # Then try user specified config
    if config_name:
        # Check in root directory
        config_path = f"{config_name}"
        if not config_path.endswith('.json'):
            config_path += '.json'
            logger.debug(f"Added .json extension to config path: {config_path}")
            
        if os.path.exists(config_path):
            logger.debug(f"Found config file in root directory: {config_path}")
            logger.info(f"Loading config from {config_path}")
            return json.load(open(config_path))
            
        # Check in configs directory
        configs_path = os.path.join(project_root, 'configs', f"{config_name}.json")
        logger.debug(f"Checking configs directory for: {configs_path}")
        if os.path.exists(configs_path):
            logger.debug(f"Found config file in configs directory")
            logger.info(f"Loading config from configs directory: {configs_path}")
            return json.load(open(configs_path))
            
        logger.warning(f"Specified config {config_name} not found in any location")
        logger.debug(f"Searched locations:\n- {config_path}\n- {configs_path}")

    # Fallback to default config
    if os.path.exists('config.json'):
        logger.info("Loading default config.json")
        return json.load(open('config.json'))

    # Last resort - example config
    if os.path.exists('config.example.json'):
        logger.warning("Using example config as fallback")
        return json.load(open('config.example.json'))

    logger.error("No valid config file found")
    return {}


config = load_config()

# Disable socket.io and engineio logging completely
logging.getLogger('socketio').setLevel(logging.CRITICAL)
logging.getLogger('engineio').setLevel(logging.CRITICAL)

# region socket-io related loggers
socf_logger = logging.getLogger(f'{__name__}.socf')
sock_logger = logging.getLogger(f'{__name__}.sock')
socc_logger = logging.getLogger(f'{__name__}.socc')

# Set to CRITICAL by default to completely suppress logs
socf_logger.setLevel(logging.CRITICAL)
sock_logger.setLevel(logging.CRITICAL)
socc_logger.setLevel(logging.CRITICAL)

# Clear any existing handlers
socf_logger.handlers.clear()
sock_logger.handlers.clear()
socc_logger.handlers.clear()

# Only enable debug logs and add handlers if explicitly configured
if config.get('socketio', {}).get('debug', False):
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    socf_logger.setLevel(logging.DEBUG)
    socf_file_channel = logging.handlers.TimedRotatingFileHandler(
        project_root.joinpath('data/socf.log'), interval=1, when='H', backupCount=48
    )
    socf_file_channel.setFormatter(formatter)
    socf_logger.addHandler(socf_file_channel)
    
    sock_logger.setLevel(logging.DEBUG)
    sock_file_channel = logging.handlers.TimedRotatingFileHandler(
        project_root.joinpath('data/sock.log'), interval=1, when='H', backupCount=48
    )
    sock_file_channel.setFormatter(formatter)
    sock_logger.addHandler(sock_file_channel)
    
    socc_logger.setLevel(logging.DEBUG)
    socc_file_channel = logging.handlers.TimedRotatingFileHandler(
        project_root.joinpath('data/socc.log'), interval=1, when='H', backupCount=48
    )
    socc_file_channel.setFormatter(formatter)
    socc_logger.addHandler(socc_file_channel)

# endregion

logger.remove()
logger.add(project_root.joinpath('data/main.log'), rotation='1 hour', retention=48)
logger.add(sys.stdout, colorize=True)

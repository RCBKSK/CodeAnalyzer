import asyncio
import functools
import os
import threading
import time

import schedule

import lokbot.util
from lokbot import project_root, logger, config
from lokbot.async_farmer import AsyncLokFarmer
from lokbot.exceptions import NoAuthException
from lokbot.farmer import LokFarmer


def find_alliance(farmer: LokFarmer):
    while True:
        alliance = farmer.api.alliance_recommend().get('alliance')

        if alliance.get('numMembers') < alliance.get('maxMembers'):
            farmer.api.alliance_join(alliance.get('_id'))
            break

        time.sleep(60 * 5)


thread_map = {}


def run_threaded(name, job_func):
    if name in thread_map and thread_map[name].is_alive():
        return

    job_thread = threading.Thread(target=job_func, name=name, daemon=True)
    thread_map[name] = job_thread
    job_thread.start()


def async_main(token):
    async_farmer = AsyncLokFarmer(token)

    asyncio.run(async_farmer.parallel_buy_caravan())


def get_valid_token():
    """Get valid token through email auth"""
    import os
    email = os.getenv('LOK_EMAIL')
    password = os.getenv('LOK_PASSWORD')

    if not email or not password:
        logger.error("LOK_EMAIL and LOK_PASSWORD must be set in environment")
        return None

    try:
        api = LokBotApi(None, {}, skip_jwt=True)  # Temporary API client for auth
        auth_result = api.auth_login(email, password)

        if not auth_result.get('result'):
            logger.error("Login failed with provided credentials")
            return None

        token = auth_result.get('token')

        # Get user ID from token
        _id = lokbot.util.decode_jwt(token).get('_id')

        # Save token to file
        token_file = project_root.joinpath(f'data/{_id}.token')
        token_file.parent.mkdir(exist_ok=True)
        with open(token_file, "w") as f:
            f.write(token)

        logger.info(f"Successfully authenticated with email. Token saved to {token_file}")
        return token
    except Exception as e:
        logger.error(f"Error getting token via email auth: {str(e)}")
        return None



def main(token=None, captcha_solver_config=None, config_file=None):
    # async_main(token)
    # exit()

    if captcha_solver_config is None:
        captcha_solver_config = {}

    # Import required modules
    from lokbot.config_helper import ConfigHelper
    import os

    # Set and validate config file
    if config_file:
        logger.info(f"Using provided config file: {config_file}")
    else:
        config_file = os.getenv("LOKBOT_CONFIG", "config.json")
        logger.info(f"Using config from environment: {config_file}")

    # Initialize config
    ConfigHelper.set_current_config(config_file)
    config = ConfigHelper.load_config(config_file)
    logger.info(f"Successfully loaded config: {config_file}")

    # First try to use provided token if any
    if token:
        logger.info("Using provided token")
    else:
        # Check for AUTH_TOKEN environment variable
        import os
        token = os.getenv("AUTH_TOKEN")

        # If no token is provided or in env vars, try email authentication
        if not token:
            logger.info("No token provided. Attempting email authentication...")
            token = get_valid_token()

            # If email auth fails, try Google authentication
            if not token:
                logger.info("Email authentication failed. Attempting Google authentication...")
                token = get_valid_token_google()

            if not token:
                logger.error("No valid token available. Please set AUTH_TOKEN, LOK_EMAIL+LOK_PASSWORD, or GOOGLE_ACCESS_TOKEN in environment variables.")
                return

    # Get user ID from token
    _id = lokbot.util.decode_jwt(token).get('_id')
    token_file = project_root.joinpath(f'data/{_id}.token')

    # Check if we have a stored token
    if token_file.exists():
        token_from_file = token_file.read_text()
        logger.info(f'Found token file: {token_file}')
        try:
            farmer = LokFarmer(token_from_file, captcha_solver_config)
        except NoAuthException:
            logger.info('Token from file is invalid, using newly acquired token')
            farmer = LokFarmer(token, captcha_solver_config)
    else:
        # Use the token we got via direct input or email auth
        farmer = LokFarmer(token, captcha_solver_config)

    threading.Thread(target=farmer.sock_thread, daemon=True).start()
    threading.Thread(target=farmer.socc_thread, daemon=True).start()

    farmer.keepalive_request()

    # Check if main section exists and has jobs
    main_config = config.get('main', {})
    jobs = main_config.get('jobs', [])
    threads = main_config.get('threads', [])

    if not jobs:
        logger.warning("No jobs found in configuration")

    for job in jobs:
        if not job.get('enabled'):
            continue

        name = job.get('name')

        schedule.every(
            job.get('interval').get('start')
        ).to(
            job.get('interval').get('end')
        ).minutes.do(run_threaded, name, functools.partial(getattr(farmer, name), **job.get('kwargs', {})))

    schedule.run_all()

    # schedule.every(15).to(20).minutes.do(farmer.keepalive_request)

    if not threads:
        logger.warning("No threads found in configuration")

    for thread in threads:
        if not thread.get('enabled'):
            continue

        thread_name = thread.get('name')
        # Use the recovery wrapper for socf_thread
        if thread_name == 'socf_thread':
            threading.Thread(target=farmer.socf_thread_with_recovery, kwargs=thread.get('kwargs', {}), daemon=True).start()
        else:
            threading.Thread(target=getattr(farmer, thread_name), kwargs=thread.get('kwargs', {}), daemon=True).start()

    while True:
        schedule.run_pending()
        time.sleep(1)
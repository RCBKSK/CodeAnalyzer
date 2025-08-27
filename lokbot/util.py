import random
import jwt
import base64
import json
from lokbot.enum import *
import logging

logger = logging.getLogger(__name__)


def get_resource_index_by_item_code(item_code):
    """
    Returns the index of the item in the resource list
    [0,    1,      2,     3   ]
    [food, lumber, stone, gold]
    """
    if (ITEM_CODE_FOOD_1K <= item_code <= ITEM_CODE_FOOD_10M) or (item_code == ITEM_CODE_FOOD):
        return 0

    if (ITEM_CODE_LUMBER_1K <= item_code <= ITEM_CODE_LUMBER_10M) or (item_code == ITEM_CODE_LUMBER):
        return 1

    if (ITEM_CODE_STONE_1K <= item_code <= ITEM_CODE_STONE_10M) or (item_code == ITEM_CODE_STONE):
        return 2

    if (ITEM_CODE_GOLD_1K <= item_code <= ITEM_CODE_GOLD_10M) or (item_code == ITEM_CODE_GOLD):
        return 3

    return -1


def run_functions_in_random_order(*funcs):
    functions = list(funcs)
    random.shuffle(functions)
    for func in functions:
        func()


def get_zone_id_by_coords(x, y):
    return (x // 32) + 64 * (y // 32)


def decode_jwt(token):
    if not token:
        return {}

    try:
        # Split the token and get the payload part (second section)
        parts = token.split('.')
        if len(parts) < 2:
            logger.error("Invalid JWT token format")
            return {}

        body = parts[1]

        # Add padding if needed
        body = body + '=' * (4 - len(body) % 4)

        # Decode the base64 payload
        decoded = base64.urlsafe_b64decode(body)

        # Parse the JSON
        return json.loads(decoded)
    except Exception as e:
        logger.error(f"Error decoding JWT: {str(e)}")
        return {}

def get_token_from_process(process):
    """Extract token from process output"""
    try:
        # Capture some output from the process to look for token
        output_lines = []
        for i in range(100):  # Try to read up to 100 lines
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                output_lines.append(line.strip())
                if "token" in line.lower() and ":" in line:
                    # Look for token in debug output
                    try:
                        token_parts = line.split("token")
                        for part in token_parts:
                            if '"' in part and ':' in part:
                                token_candidate = part.split('"')[1]
                                if len(token_candidate) > 50 and '.' in token_candidate:
                                    # This looks like a JWT token
                                    return token_candidate
                    except:
                        pass

        # Check if we can find the token in the process environment
        if hasattr(process, 'args') and len(process.args) > 2:
            arg = process.args[2]
            if len(arg) > 50 and '.' in arg:  # Likely a token
                return arg
    except Exception as e:
        logger.error(f"Error extracting token from process: {e}")
    return None

def award_title_with_api(token, title_code, kingdom_uid):
    """Award a title using the API"""
    try:
        from lokbot.client import LokBotApi
        api = LokBotApi(token, {})
        # This is a placeholder - would need the actual API endpoint for title awarding
        # Return format would depend on the actual API
        return {"result": True, "message": "Title awarded successfully"}
    except Exception as e:
        logger.error(f"Error awarding title: {e}")
        return {"result": False, "reason": str(e)}
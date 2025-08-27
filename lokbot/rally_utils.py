from lokbot.enum import (
    TROOP_CODE_FIGHTER, TROOP_CODE_HUNTER, TROOP_CODE_STABLE_MAN,
    TROOP_CODE_WARRIOR, TROOP_CODE_LONGBOW_MAN, TROOP_CODE_HORSEMAN,
    TROOP_CODE_KNIGHT, TROOP_CODE_RANGER, TROOP_CODE_HEAVY_CAVALRY,
    TROOP_CODE_GUARDIAN, TROOP_CODE_CROSSBOW_MAN, TROOP_CODE_IRON_CAVALRY,
    TROOP_CODE_CRUSADER, TROOP_CODE_SNIPER, TROOP_CODE_DRAGOON,
    TROOP_CODE_PALADIN, TROOP_CODE_DESTROYER, TROOP_CODE_MARKSMAN,
    TROOP_CODE_MUSKETEER, TROOP_CODE_MARAUDER, TROOP_CODE_VALKYRIE,
    INFANTRY_TROOPS, RANGED_TROOPS, CAVALRY_TROOPS,
    TROOP_POWER_MAP, TROOP_LOAD_MAP
)

def calculate_rally_power(troops_dict):
    """
    Calculate the total power of troops in a rally

    Args:
        troops_dict: Dictionary mapping troop codes to troop counts

    Returns:
        Total power value of the troops
    """
    total_power = 0
    for troop_code, troop_count in troops_dict.items():
        if troop_code in TROOP_POWER_MAP:
            total_power += TROOP_POWER_MAP[troop_code] * troop_count
    return total_power

def get_best_troops_for_monster(monster_code, max_troops=None, preferred_type=None):
    """
    Determine the best troops to use against a specific monster type

    Args:
        monster_code: Monster code to fight against
        max_troops: Maximum number of troops to use
        preferred_type: Preferred troop type (infantry, ranged, cavalry)

    Returns:
        Dictionary of recommended troops and counts
    """
    # Monster-specific troop recommendations based on game data
    monster_recommendations = {
        20200201: CAVALRY_TROOPS,  # Deathkar - best with cavalry
        20200205: CAVALRY_TROOPS,  # Magdar - best with cavalry
        20200301: [*INFANTRY_TROOPS, *RANGED_TROOPS],  # Spartoi - best with infantry and ranged
        20700506: CAVALRY_TROOPS,  # Dragon Soul - best with cavalry
        20200202: CAVALRY_TROOPS,  # Green Dragon - best with cavalry
        20200203: CAVALRY_TROOPS,  # Red Dragon - best with cavalry
        20200204: CAVALRY_TROOPS,  # Gold Dragon - best with cavalry
        20700502: CAVALRY_TROOPS,  # Battlefield Green Dragon - best with cavalry
        20700503: CAVALRY_TROOPS,  # Battlefield Red Dragon - best with cavalry
        20700504: CAVALRY_TROOPS,  # Battlefield Gold Dragon - best with cavalry
        20700505: CAVALRY_TROOPS,  # Battlefield Magdar - best with cavalry
    }

    recommended_troops = {}

    # Default to highest tier troops if no specific recommendation
    if preferred_type:
        if preferred_type == 'infantry':
            troop_candidates = INFANTRY_TROOPS
        elif preferred_type == 'ranged':
            troop_candidates = RANGED_TROOPS
        elif preferred_type == 'cavalry':
            troop_candidates = CAVALRY_TROOPS
    elif monster_code in monster_recommendations:
        troop_candidates = monster_recommendations[monster_code]
    else:
        # Default to all top tier troops
        troop_candidates = [
            TROOP_CODE_PALADIN, TROOP_CODE_DESTROYER,
            TROOP_CODE_MARKSMAN, TROOP_CODE_MUSKETEER,
            TROOP_CODE_MARAUDER, TROOP_CODE_VALKYRIE,
            TROOP_CODE_CRUSADER, TROOP_CODE_SNIPER, TROOP_CODE_DRAGOON
        ]

    # Select the highest tier troops from candidates
    best_troops = sorted(troop_candidates, reverse=True)[:3]

    # If max_troops specified, allocate them among the best troops
    if max_troops and best_troops:
        troops_per_type = max_troops // len(best_troops)
        for troop_code in best_troops:
            recommended_troops[troop_code] = troops_per_type

    return recommended_troops

def calculate_carry_capacity(troops_dict):
    """
    Calculate the total carrying capacity of troops

    Args:
        troops_dict: Dictionary mapping troop codes to troop counts

    Returns:
        Total carrying capacity of the troops
    """
    total_capacity = 0
    for troop_code, troop_count in troops_dict.items():
        if troop_code in TROOP_LOAD_MAP:
            total_capacity += TROOP_LOAD_MAP[troop_code] * troop_count
    return total_capacity

MONSTER_CODE_ORC = 101
MONSTER_CODE_SKELETON = 102
MONSTER_CODE_GOLEM = 103
MONSTER_CODE_TREASURE_GOBLIN = 104
MONSTER_CODE_DEATHKAR = 20200201
MONSTER_CODE_GREEN_DRAGON = 20200202
MONSTER_CODE_RED_DRAGON = 20200203
MONSTER_CODE_GOLD_DRAGON = 20200204
MONSTER_CODE_MAGDAR = 20200205
MONSTER_CODE_SPARTOI = 20200301
MONSTER_CODE_BF_ORC = 301
MONSTER_CODE_BF_SKELETON = 302
MONSTER_CODE_BF_GOLEM = 303
MONSTER_CODE_BF_TREASURE_GOBLIN = 304
MONSTER_CODE_BF_OGRE = 305
MONSTER_CODE_BF_WOLF = 306
MONSTER_CODE_BF_CYCLOPS = 307
MONSTER_CODE_BF_DEATHKAR = 308


def get_monster_name_by_code(monster_code):
    """Get monster name by code"""
    import logging
    logger = logging.getLogger(__name__)
    
    # Map monster codes to names
    monster_names = {
        # Standard monsters
        20200205: "Magdar",
        20200202: "Green Dragon",
        20200203: "Red Dragon",
        20200204: "Gold Dragon",
        20200201: "Deathkar",
        20200104: "Treasure Goblin",
        20200103: "Golem",
        20200102: "Skeleton",
        20200101: "Orc",
        20200301: "Spartoi",
        
        # Battlefield monsters
        20700502: "Battlefield Green Dragon",
        20700503: "Battlefield Red Dragon",
        20700504: "Battlefield Gold Dragon",
        20700505: "Battlefield Magdar",
        20700506: "Battlefield Spartoi",
        20700501: "Battlefield Deathkar",
        20700403: "Battlefield Golem",
        20700402: "Battlefield Skeleton",
        20700401: "Battlefield Orc",
        20700405: "Battlefield Ogre",
        20700406: "Battlefield Wolf",
        20700407: "Battlefield Cyclops",
        
        # Alternative codes that might be used
        20800401: "Battlefield Orc",
        20800402: "Battlefield Skeleton",
        20800403: "Battlefield Golem",
        20800404: "Battlefield Treasure Goblin",
        2020001: "Monster Nest",
        207000506: "Battlefield Spartoi"
    }

    name = monster_names.get(monster_code)
    if name is None:
        logger.warning(f"Unknown monster code: {monster_code}")
        return f"Monster #{monster_code}"
    
    logger.debug(f"Resolved monster code {monster_code} to name: {name}")
    return name
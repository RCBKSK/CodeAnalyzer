import base64
import functools
import gzip
import logging
import math
import random
import threading
import time
import json

import arrow
import numpy
import socketio
import tenacity

import lokbot.util
from lokbot import logger, config
from lokbot.client import LokBotApi
from lokbot.enum import *
from lokbot.exceptions import OtherException, FatalApiException, NotOnlineException

# Placeholder for project_root if not defined globally
try:
    project_root
except NameError:
    import os
    project_root = os.path.abspath(os.path.dirname(__file__))
    import pathlib
    project_root = pathlib.Path(project_root)


ws_headers = {
    'Accept':
    '*/*',
    'Accept-Encoding':
    'gzip, deflate, br',
    'Accept-Language':
    'en-US,en;q=0.9',
    'Cache-Control':
    'no-cache',
    'Origin':
    'https://play.leagueofkingdoms.com',
    'Pragma':
    'no-cache',
    'User-Agent':
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0'
}


# Ref: https://stackoverflow.com/a/16858283/6266737
def blockshaped(arr, nrows, ncols):
    """
    Return an array of shape (n, nrows, ncols) where
    n * nrows * ncols = arr.size

    If arr is a 2D array, the returned array should look like n subblocks with
    each subblock preserving the "physical" layout of arr.
    """
    h, w = arr.shape
    assert h % nrows == 0, f"{h} rows is not evenly divisible by {nrows}"
    assert w % ncols == 0, f"{w} cols is not evenly divisible by {ncols}"
    return (arr.reshape(h // nrows, nrows, -1,
                        ncols).swapaxes(1, 2).reshape(-1, nrows, ncols))


# Ref: https://stackoverflow.com/a/432175/6266737
# noinspection PyBroadException
def ndindex(ndarray, item):
    if len(ndarray.shape) == 1:
        try:
            return [ndarray.tolist().index(item)]
        except:
            pass
    else:
        for i, subarray in enumerate(ndarray):
            try:
                return [i] + ndindex(subarray, item)
            except:
                pass


# Ref: https://stackoverflow.com/a/22550933/6266737
def neighbors(a, radius, row_number, column_number):
    return [[
        a[i][j] if 0 <= i < len(a) and 0 <= j < len(a[0]) else 0
        for j in range(column_number - 1 - radius, column_number + radius)
    ] for i in range(row_number - 1 - radius, row_number + radius)]


class LokFarmer:

    def __init__(self, token, captcha_solver_config):
        self.kingdom_enter = None
        self.token = token
        self.api = LokBotApi(token, captcha_solver_config,
                             self._request_callback)

        auth_res = self.api.auth_connect({"deviceInfo": {"build": "global"}})
        self.api.protected_api_list = json.loads(
            base64.b64decode(auth_res.get('lstProtect')).decode())
        self.api.protected_api_list = [
            str(api).split('/api/').pop()
            for api in self.api.protected_api_list
        ]
        logger.debug(f'protected_api_list: {self.api.protected_api_list}')
        self.api.xor_password = json.loads(
            base64.b64decode(
                auth_res.get('regionHash')).decode()).split('-')[1]
        logger.debug(f'xor_password: {self.api.xor_password}')
        self.token = auth_res.get('token')
        self._id = lokbot.util.decode_jwt(token).get('_id')
        project_root.joinpath(f'data/{self._id}.token').write_text(self.token)

        self.kingdom_enter = self.api.kingdom_enter()
        self.alliance_id = self.kingdom_enter.get('kingdom',
                                                  {}).get('allianceId')

        self.api.auth_set_device_info({
            "build": "global",
            "OS": "Windows 10",
            "country": "USA",
            "language": "English",
            "bundle": "",
            "version": "1.1694.152.229",
            "platform": "web",
            "pushId": ""
        })

        self.api.chat_logs(
            f'w{self.kingdom_enter.get("kingdom").get("worldId")}')
        if self.alliance_id:
            self.api.chat_logs(f'a{self.alliance_id}')

        # Check if treasure feature is enabled and set page if it is
        treasure_config = config.get('main', {}).get('treasure', {})
        if treasure_config.get('enabled', True):
            treasure_page = treasure_config.get('page', 1)
            result = self.api.kingdom_treasure_page(treasure_page)
            
            # Send treasure page change notification
            if result:
                try:
                    self._send_notification(
                        'treasure_page_changed',
                        '📜 Treasure Page Changed',
                        f'Successfully set treasure page to {treasure_page}'
                    )
                except Exception as notif_error:
                    logger.debug(f"Failed to send treasure page notification: {notif_error}")

        # Skills are now handled by the dedicated skills management thread
        # This prevents conflicts with the periodic activation system

        # [food, lumber, stone, gold]
        self.resources = self.kingdom_enter.get('kingdom').get('resources')
        self.buff_item_use_lock = threading.Lock()
        self.hospital_recover_lock = threading.Lock()
        self.active_buffs = []  # Store active buffs for new buff management system
        self.has_additional_building_queue = self.kingdom_enter.get(
            'kingdom').get('vip', {}).get('level') >= 5
        self.troop_queue = []
        self.march_limit = 2
        self.march_size = 10000
        self.level = self.kingdom_enter.get('kingdom').get('level')

        # Initialize march objects tracking with high-frequency update support
        self.march_objects_data = {}
        self.march_objects_last_update = 0
        self.march_objects_lock = threading.Lock()  # Thread safety
        self.march_data_validation_errors = 0
        self.max_march_data_age = 300  # 5 minutes max age for march data
        self.march_data_update_count = 0  # Track frequency of updates
        self.march_data_by_zone = {}  # Zone-specific march data caching
        self.current_scanning_zone = None  # Track which zone is being scanned
        self.socf_entered = False
        self.socf_world_id = None
        self.field_object_processed = False
        self.started_at = time.time()
        self.building_queue_available = threading.Event()
        self.research_queue_available = threading.Event()
        self.train_queue_available = threading.Event()
        self.kingdom_tasks = []
        self.zones = []
        self.available_dragos = self._get_available_dragos()
        self.drago_action_point = self.kingdom_enter.get('kingdom').get(
            'dragoActionPoint', {}).get('value', 0)
        self.shared_objects = set()

        # Initialize buff management tracking
        self.buff_last_activation = {}
        self.buff_activation_cooldown = 1800  # 30 minutes in seconds

        # Initialize skin change tracking
        self.skin_last_change = 0
        self.skin_change_cooldown = 3600  # 60 minutes in seconds default

        # Crystal limit tracking
        self.crystal_limit_reached = False

        # Start checking for rallies after 1 minute to let other systems initialize
        if self.alliance_id:
            logger.info("Alliance detected, setting up rally monitoring")
            time.sleep(60)  # Wait 1 minute
            thread = threading.Thread(target=self._check_rallies_thread)
            thread.daemon = True
            thread.start()
            logger.info("Rally monitoring thread started")

        # Start buff management thread
        buff_thread = threading.Thread(target=self._buff_management_thread)
        buff_thread.daemon = True
        buff_thread.start()
        logger.info("Buff management thread started")

        # Start march status update thread
        march_status_thread = threading.Thread(target=self._march_status_update_thread)
        march_status_thread.daemon = True
        march_status_thread.start()
        logger.info("March status update thread started")

        # Start skin change thread
        try:
            skin_thread = threading.Thread(target=self._skin_change_thread)
            skin_thread.daemon = True
            skin_thread.start()
            logger.info("Skin change thread started")
        except Exception as e:
            logger.error(f"Failed to start skin change thread: {e}")

        # Start skills management thread
        try:
            skills_thread = threading.Thread(target=self._skills_management_thread)
            skills_thread.daemon = True
            skills_thread.start()
            logger.info("Skills management thread started")
        except Exception as e:
            logger.error(f"Failed to start skills management thread: {e}")

        # Initialize job registry
        try:
            self.jobs = {
                'hospital_recover': self.hospital_recover,
                'wall_repair': self.wall_repair,
                'alliance_farmer': self.alliance_farmer,
                'mail_claim': self.mail_claim,
                'caravan_farmer': self.caravan_farmer,
                'use_resource_in_item_list': self.use_resource_in_item_list,
                'vip_chest_claim': self.vip_chest_claim,
                'dsavip_chest_claim': self.dsavip_chest_claim,
                'harvester': self.harvester,
            }
        except Exception as e:
            logger.error(f"Failed to initialize job registry: {e}")
            self.jobs = {}

    def _march_status_update_thread(self):
        """Periodically update march status"""
        while True:
            try:
                time.sleep(30)  # Update every 30 seconds
                self._update_march_limit()
            except Exception as e:
                logger.error(f"Error in march status update thread: {str(e)}")
                time.sleep(60)  # Wait longer on error

    def _reconnect_kingdom(self):
        """Simple kingdom reconnection for not_online errors"""
        try:
            logger.info("Attempting kingdom reconnection...")

            # Try kingdom_enter to reconnect
            kingdom_result = self.api.kingdom_enter()

            if kingdom_result and kingdom_result.get('result'):
                # Update kingdom_enter data
                self.kingdom_enter = kingdom_result

                # Update alliance_id if it changed
                self.alliance_id = self.kingdom_enter.get('kingdom', {}).get('allianceId')

                # Initialize chat logs again
                world_id = self.kingdom_enter.get("kingdom").get("worldId")
                if world_id:
                    self.api.chat_logs(f'w{world_id}')
                if self.alliance_id:
                    self.api.chat_logs(f'a{self.alliance_id}')

                logger.info("Kingdom reconnection successful!")
                return True
            else:
                logger.error("Kingdom reconnection failed - invalid result from kingdom_enter")
                return False

        except Exception as e:
            logger.error(f"Kingdom reconnection failed: {str(e)}")
            return False

    def _reinitialize_bot(self):
        """Complete bot re-initialization like a fresh startup"""
        try:
            logger.info("Attempting complete bot re-initialization...")

            # Get stored token
            token_file = project_root.joinpath(f'data/{self._id}.token')
            if not token_file.exists():
                logger.error("No stored token found for re-initialization")
                return False

            stored_token = token_file.read_text().strip()
            if not stored_token:
                logger.error("Stored token is empty")
                return False

            logger.info("Found stored token, performing complete re-initialization...")

            # Create new API instance with stored token
            self.api = LokBotApi(stored_token, {}, self._request_callback)
            self.token = stored_token

            # Step 1: Re-establish authentication connection
            auth_res = self.api.auth_connect({"deviceInfo": {"build": "global"}})
            if not auth_res.get('result'):
                logger.error("Re-authentication failed with stored token")
                return False

            # Update API configuration like in __init__
            self.api.protected_api_list = json.loads(
                base64.b64decode(auth_res.get('lstProtect')).decode())
            self.api.protected_api_list = [
                str(api).split('/api/').pop()
                for api in self.api.protected_api_list
            ]
            logger.debug(f'protected_api_list: {self.api.protected_api_list}')

            self.api.xor_password = json.loads(
                base64.b64decode(
                    auth_res.get('regionHash')).decode()).split('-')[1]
            logger.debug(f'xor_password: {self.api.xor_password}')

            # Update token if we got a new one
            if auth_res.get('token'):
                self.token = auth_res.get('token')
                self.api.token = self.token
                self.api.opener.headers['X-Access-Token'] = self.token
                # Save updated token
                token_file.write_text(self.token)

            # Step 2: Re-enter kingdom and update all game state
            self.kingdom_enter = self.api.kingdom_enter()
            self.alliance_id = self.kingdom_enter.get('kingdom', {}).get('allianceId')

            # Step 3: Set device info like in __init__
            self.api.auth_set_device_info({
                "build": "global",
                "OS": "Windows 10",
                "country": "USA",
                "language": "English",
                "bundle": "",
                "version": "1.1694.152.229",
                "platform": "web",
                "pushId": ""
            })

            # Step 4: Re-initialize chat logs
            self.api.chat_logs(f'w{self.kingdom_enter.get("kingdom").get("worldId")}')
            if self.alliance_id:
                self.api.chat_logs(f'a{self.alliance_id}')

            # Step 5: Re-check treasure feature
            from lokbot import config
            treasure_config = config.get('main', {}).get('treasure', {})
            if treasure_config.get('enabled', True):
                treasure_page = treasure_config.get('page', 1)
                self.api.kingdom_treasure_page(treasure_page)

            # Step 6: Re-handle skills
            if config.get('main', {}).get('skills', {}).get('enabled', True):
                try:
                    skill_list = self.api.skill_list()
                    available_skills = [skill.get('code') for skill in skill_list.get('skills', [])]

                    for skill in config.get('main', {}).get('skills', {}).get('skills', []):
                        try:
                            if skill.get('enabled') and skill.get('code') in available_skills:
                                skill_info = next((s for s in skill_list.get('skills', []) if s.get('code') == skill.get('code')), None)
                                if skill_info and skill_info.get('nextSkillTime'):
                                    logger.info(f"Skill {skill.get('code')} is on cooldown until {skill_info.get('nextSkillTime')}")
                                    continue

                                self.api.skill_use(skill.get('code'))
                                logger.info(f"Re-used skill {skill.get('code')} after re-initialization")
                        except Exception as e:
                            logger.warning(f"Error re-using skill {skill.get('code')}: {e}")
                except Exception as e:
                    logger.warning(f"Error re-initializing skills: {e}")

            # Step 7: Update all internal state variables
            self.resources = self.kingdom_enter.get('kingdom').get('resources')
            self.level = self.kingdom_enter.get('kingdom').get('level')
            self.has_additional_building_queue = self.kingdom_enter.get('kingdom').get('vip', {}).get('level') >= 5

            # Step 8: Reset tracking variables and update march info
            self._update_march_limit()
            self.available_dragos = self._get_available_dragos()
            self.drago_action_point = self.kingdom_enter.get('kingdom').get('dragoActionPoint', {}).get('value', 0)

            # Step 9: Clear zones to force re-calculation for object scanning
            self.zones = []
            self.socf_entered = False
            self.socf_world_id = None
            self.field_object_processed = False

            # Step 10: Reset threading events
            self.building_queue_available.clear()
            self.research_queue_available.clear()
            self.train_queue_available.clear()

            # Step 11: Reset buff management tracking
            self.buff_last_activation = {}
            self.active_buffs = []

            # Step 12: Update kingdom tasks
            self.kingdom_tasks = []
            try:
                self.kingdom_tasks = self.api.kingdom_task_all().get('kingdomTasks', [])
            except Exception as e:
                logger.warning(f"Could not refresh kingdom tasks after re-initialization: {e}")

            # Step 13: Send keepalive to confirm everything is working
            try:
                self.keepalive_request()
                logger.info("Keepalive request successful after re-initialization")
            except Exception as e:
                logger.warning(f"Keepalive failed after re-initialization: {e}")

            logger.info("Complete bot re-initialization successful - all systems refreshed!")
            return True

        except Exception as e:
            logger.error(f"Complete bot re-initialization failed: {str(e)}")
            return False

    @staticmethod
    def calc_time_diff_in_seconds(expected_ended):
        time_diff = arrow.get(expected_ended) - arrow.utcnow()
        diff_in_seconds = int(time_diff.total_seconds())

        if diff_in_seconds < 0:
            diff_in_seconds = 0

        return diff_in_seconds + random.randint(5, 10)

    def _is_building_upgradeable(self, building, buildings):
        if building.get('state') != BUILDING_STATE_NORMAL:
            return False

        if building.get('code') == BUILDING_CODE_MAP['barrack']:
            for t in self.kingdom_tasks:
                if t.get('code') == TASK_CODE_CAMP:
                    return False

        # 暂时忽略联盟中心
        if building.get('code') == BUILDING_CODE_MAP['hall_of_alliance']:
            return False

        building_level = building.get('level')
        current_building_json = building_json.get(building.get('code'))

        if not current_building_json:
            return False

        next_level_building_json = current_building_json.get(
            str(building_level + 1))
        for requirement in next_level_building_json.get('requirements'):
            req_level = requirement.get('level')
            req_type = requirement.get('type')
            req_code = BUILDING_CODE_MAP.get(req_type)

            if not [
                    b for b in buildings if b.get('code') == req_code
                    and b.get('level') >= req_level
            ]:
                return False

        for res_requirement in next_level_building_json.get('resources'):
            req_value = res_requirement.get('value')
            req_type = res_requirement.get('type')

            if self.resources[RESOURCE_IDX_MAP[req_type]] < req_value:
                return False

        return True

    def _is_researchable(self,
                         academy_level,
                         category_name,
                         research_name,
                         exist_researches,
                         to_max_level=False):
        research_category = RESEARCH_CODE_MAP.get(category_name)
        research_code = research_category.get(research_name)

        exist_research = [
            each for each in exist_researches
            if each.get('code') == research_code
        ]
        current_research_json = research_json.get(research_code)

        # already finished
        if exist_research and exist_research[0].get('level') >= int(
                current_research_json[-1].get('level')):
            return False

        # minimum required level only
        if not to_max_level and \
                exist_research and \
                exist_research[0].get('level') >= RESEARCH_MINIMUM_LEVEL_MAP.get(category_name).get(research_name, 0):
            return False

        next_level_research_json = current_research_json[0]
        if exist_research:
            next_level_research_json = current_research_json[
                exist_research[0].get('level')]

        for requirement in next_level_research_json.get('requirements'):
            req_level = int(requirement.get('level'))
            req_type = requirement.get('type')

            # 判断学院等级
            if req_type == 'academy' and req_level > academy_level:
                return False

            # 判断前置研究是否完成
            if req_type != 'academy' and not [
                    each for each in exist_researches
                    if each.get('code') == research_category.get(req_type)
                    and each.get('level') >= req_level
            ]:
                return False

        for res_requirement in next_level_research_json.get('resources'):
            req_value = int(res_requirement.get('value'))
            req_type = res_requirement.get('type')

            if self.resources[RESOURCE_IDX_MAP[req_type]] < req_value:
                return False

        return True

    def _update_kingdom_enter_building(self, building):
        if building.get('code') == BUILDING_CODE_MAP['hospital']:
            if building.get('param', {}).get('wounded', []):
                logger.info(
                    'hospital has wounded troops, but recovery will follow the scheduled interval'
                )
                # Removed auto-triggering of hospital_recover() here

        buildings = self.kingdom_enter.get('kingdom', {}).get('buildings', [])

        self.kingdom_enter['kingdom']['buildings'] = [
            b
            for b in buildings if b.get('position') != building.get('position')
        ] + [building]

    def _request_callback(self, json_response):
        resources = json_response.get('resources')

        if resources and len(resources) == 4:
            logger.info(f'resources updated: {resources}')
            self.resources = resources

        # Check for crystal limit error
        error = json_response.get('err')
        if error and error.get('code') == 'exceed_crystal_daily_quota':
            self._handle_crystal_limit_error()

    def _get_optimal_speedups(self, need_seconds, speedup_type):
        current_map = ITEM_CODE_SPEEDUP_MAP.get(speedup_type)

        # Only for hospital recovery, don't use universal speedups
        if speedup_type != 'recover':
            current_map.update(ITEM_CODE_SPEEDUP_MAP.get('universal'))

        assert current_map, f'invalid speedup type: {speedup_type}'

        items = self.api.item_list().get('items', [])
        items = [
            item for item in items if item.get('code') in current_map.keys()
        ]

        if not items:
            logger.info(f'no speedup item found for {speedup_type}')
            return False

        # build `{code, amount, second}` map
        speedups = []
        for item in items:
            speedups.append({
                'code': item.get('code'),
                'amount': item.get('amount'),
                'second': current_map.get(item.get('code'))
            })

        # sort by speedup second desc
        speedups = sorted(speedups,
                          key=lambda x: x.get('second'),
                          reverse=True)

        counts = {each.get('code'): 0 for each in speedups}

        remaining_seconds = need_seconds
        used_seconds = 0
        for each in speedups:
            while remaining_seconds >= each.get('second') and counts.get(
                    each.get('code')) < each.get('amount'):
                remaining_seconds -= each.get('second')
                counts[each.get('code')] += 1
                used_seconds += each.get('second')

        if speedup_type == 'recover':
            # greedy mode
            speedups_asc = sorted(speedups, key=lambda x: x.get('second'))
            for each in speedups_asc:
                while remaining_seconds >= 0 and counts.get(
                        each.get('code')) < each.get('amount'):
                    remaining_seconds -= each.get('second')
                    counts[each.get('code')] += 1
                    used_seconds += each.get('second')

        counts = {k: v for k, v in counts.items() if v > 0}

        if not counts:
            logger.info(f'cannot find optimal speedups for {speedup_type}')
            return False

        return {'counts': counts, 'used_seconds': used_seconds}

    def do_speedup(self, expected_ended, task_id, speedup_type):
        need_seconds = self.calc_time_diff_in_seconds(expected_ended)

        if need_seconds > 60 * 5 or speedup_type == 'recover':
            # try speedup only when need_seconds > 5 minutes
            speedups = self._get_optimal_speedups(need_seconds, speedup_type)
            if speedups:
                counts = speedups.get('counts')
                used_seconds = speedups.get('used_seconds')

                # using speedup items
                logger.info(
                    f'need_seconds: {need_seconds}, using speedups: {counts}, saved {used_seconds} seconds'
                )

                # Better logging for hospital recovery
                if speedup_type == 'recover':
                    logger.info(
                        'Hospital recovery using ONLY recovery-specific speedups'
                    )

                for code, count in counts.items():
                    # Check if task is still active for building/research/training speedups
                    if speedup_type != 'recover':
                        # Check task status before applying speedup
                        try:
                            tasks = self.api.kingdom_task_all().get(
                                'kingdomTasks', [])
                            active_task = next(
                                (t for t in tasks if t.get('_id') == task_id
                                 and t.get('status') == 1), None)
                            if not active_task:
                                logger.info(
                                    f'Task {task_id} is no longer active, skipping remaining speedups'
                                )
                                break
                        except Exception as e:
                            logger.warning(
                                f'Failed to check task status: {e}, continuing with speedup'
                            )

                    # Apply the speedup
                    if speedup_type == 'recover':
                        item_type = "recovery" if code in ITEM_CODE_SPEEDUP_MAP.get(
                            'recover', {}) else "universal"
                        logger.info(
                            f'Using {count}x speedup item (code: {code}, type: {item_type})'
                        )
                        self.api.kingdom_heal_speedup(code, count)
                    else:
                        self.api.kingdom_task_speedup(task_id, code, count)

                    # Add longer delay between speedups to allow task status to update
                    time.sleep(random.randint(2, 4))

    def _upgrade_building(self, building, buildings, speedup):
        if not self._is_building_upgradeable(building, buildings):
            return 'continue'

        try:
            if building.get('level') == 0:
                res = self.api.kingdom_building_build(building)
                building = res.get('newBuilding', building)
            else:
                res = self.api.kingdom_building_upgrade(building)
                building = res.get('updateBuilding', building)
        except OtherException as error_code:
            if str(error_code) == 'full_task':
                logger.warning('building_farmer: full_task, quit')
                return 'break'

            logger.info(f'building upgrade failed: {building}')
            return 'continue'

        building['state'] = BUILDING_STATE_UPGRADING
        self._update_kingdom_enter_building(building)

        if speedup:
            self.do_speedup(
                res.get('newTask').get('expectedEnded'),
                res.get('newTask').get('_id'), 'building')

    def _alliance_gift_claim_all(self):
        try:
            self.api.alliance_gift_claim_all()
        except OtherException:
            pass

    def _alliance_help_all(self):
        try:
            self.api.alliance_help_all()
        except OtherException:
            pass

    def _alliance_research_donate_all(self):
        try:
            research_list = self.api.alliance_research_list()
        except OtherException:
            return

        code = research_list.get('recommendResearch')

        if not code:
            code = 31101003  # 骑兵攻击力 1

        try:
            self.api.alliance_research_donate_all(code)
        except OtherException:
            pass

    def _alliance_shop_autobuy(self, item_code_list=(ITEM_CODE_VIP_100, )):
        try:
            shop_list = self.api.alliance_shop_list()
        except OtherException:
            return

        alliance_point = shop_list.get('alliancePoint')
        shop_items = shop_list.get('allianceShopItems')

        for each_shop_item in shop_items:
            code = each_shop_item.get('code')
            if code not in item_code_list:
                continue

            cost = each_shop_item.get('ap_1')  # or 'ap_2'?
            amount_available = each_shop_item.get('amount')

            minimum_buy_amount = int(alliance_point / cost)
            if minimum_buy_amount < 1:
                continue

            amount = minimum_buy_amount if minimum_buy_amount < amount_available else amount_available

            try:
                self.api.alliance_shop_buy(code, amount)
            except OtherException as error_code:
                logger.warning(
                    f'alliance_shop_buy failed({str(error_code)}): {code}, {amount}'
                )
                return

            alliance_point -= cost * amount

    def _alliance_shop_autobuy_enhanced(self, shop_config):
        """Enhanced alliance shop buying with priority system and quantity controls."""
        try:
            from lokbot.enum import ALLIANCE_SHOP_ITEMS
            
            if not shop_config.get('enabled', False):
                return
                
            shop_list = self.api.alliance_shop_list()
        except OtherException:
            return

        alliance_point = shop_list.get('alliancePoint', 0)
        shop_items = shop_list.get('allianceShopItems', [])
        
        if alliance_point <= 0:
            logger.debug("No alliance points available for shop purchases")
            return

        # Create a mapping of available items in the shop
        available_items = {}
        for shop_item in shop_items:
            code = shop_item.get('code')
            if code:
                available_items[code] = {
                    'cost': shop_item.get('ap_1', 0),  # Alliance point cost
                    'amount': shop_item.get('amount', 0),  # Available quantity
                    'original_item': shop_item
                }

        # Get configured items and sort by priority
        configured_items = shop_config.get('items', [])
        enabled_items = [item for item in configured_items if item.get('enabled', False)]
        
        # Sort by priority (lower number = higher priority)
        enabled_items.sort(key=lambda x: x.get('priority', 999))
        
        logger.info(f"Starting enhanced alliance shop buying with {alliance_point} alliance points")
        logger.info(f"Found {len(enabled_items)} enabled items to consider")
        
        purchases_made = []
        
        for item_config in enabled_items:
            item_code = item_config.get('item_code')
            min_buy = item_config.get('min_buy', 1)
            max_buy = item_config.get('max_buy', 999999)
            priority = item_config.get('priority', 999)
            
            if item_code not in available_items:
                logger.debug(f"Item {item_code} not available in alliance shop")
                continue
                
            shop_item = available_items[item_code]
            item_cost = shop_item['cost']
            available_quantity = shop_item['amount']
            
            if item_cost <= 0 or available_quantity <= 0:
                logger.debug(f"Item {item_code}: invalid cost ({item_cost}) or quantity ({available_quantity})")
                continue
                
            # Calculate how many we can afford
            max_affordable = int(alliance_point / item_cost)
            
            if max_affordable < min_buy:
                logger.debug(f"Item {item_code}: cannot afford minimum purchase ({max_affordable} < {min_buy})")
                continue
                
            # Calculate actual purchase amount
            desired_amount = min(max_affordable, max_buy, available_quantity)
            
            if desired_amount < min_buy:
                logger.debug(f"Item {item_code}: desired amount ({desired_amount}) below minimum ({min_buy})")
                continue
                
            # Get item info for logging
            item_info = ALLIANCE_SHOP_ITEMS.get(item_code, {})
            item_name = item_info.get('name', f'Item {item_code}')
            
            try:
                logger.info(f"Attempting to buy {desired_amount}x {item_name} for {item_cost * desired_amount} alliance points")
                
                result = self.api.alliance_shop_buy(item_code, desired_amount)
                
                if result:
                    alliance_point -= item_cost * desired_amount
                    purchases_made.append({
                        'item_code': item_code,
                        'name': item_name,
                        'amount': desired_amount,
                        'cost': item_cost * desired_amount,
                        'priority': priority
                    })
                    
                    logger.info(f"✅ Successfully bought {desired_amount}x {item_name}")
                    logger.info(f"Remaining alliance points: {alliance_point}")
                    
                    # Update available quantity for future iterations
                    available_items[item_code]['amount'] -= desired_amount
                else:
                    logger.warning(f"❌ Failed to buy {item_name} - API returned false")
                    
            except OtherException as error_code:
                logger.warning(f"❌ Alliance shop buy failed for {item_name}: {str(error_code)}")
                # Don't return here, continue with other items
                continue
                
            # Stop if we're out of alliance points
            if alliance_point <= 0:
                logger.info("No more alliance points available, stopping purchases")
                break
                
        # Log summary
        if purchases_made:
            total_spent = sum(p['cost'] for p in purchases_made)
            logger.info(f"🛒 Alliance shop buying summary:")
            logger.info(f"   • Total items bought: {len(purchases_made)}")
            logger.info(f"   • Total alliance points spent: {total_spent}")
            logger.info(f"   • Remaining alliance points: {alliance_point}")
            for purchase in purchases_made:
                logger.info(f"   • {purchase['amount']}x {purchase['name']} (Priority {purchase['priority']})")
        else:
            logger.info("No alliance shop purchases were made")

    @functools.lru_cache()
    def _get_land_with_level(self):
        rank = self.api.field_worldmap_devrank().get('lands')

        land_with_level = [[], [], [], [], [], [], [], [], [], []]
        for index, level in enumerate(rank):
            # land id start from 100000
            land_with_level[int(level)].append(100000 + index)

        return land_with_level

    @staticmethod
    @functools.lru_cache()
    def _get_land_array():
        return numpy.arange(100000, 165536).reshape(256, 256)

    @functools.lru_cache()
    def _get_land_array_4_by_4(self):
        return blockshaped(self._get_land_array(), 4, 4)

    @staticmethod
    @functools.lru_cache()
    def _get_zone_array():
        return numpy.arange(0, 4096).reshape(64, 64)

    @functools.lru_cache()
    def _get_nearest_land(self, x, y, radius=32):
        land_array = self._get_land_array()
        # current_land_id = land_array[y // 8, x // 8]
        nearby_land_ids = neighbors(land_array, radius, y // 8 + 1, x // 8 + 1)
        nearby_land_ids = [
            item for sublist in nearby_land_ids for item in sublist
            if item != 0
        ]
        land_with_level = self._get_land_with_level()

        lands = []
        for index, each_level in enumerate(reversed(land_with_level)):
            level = 10 - index

            if level < 2:
                continue

            lands += [(each_land_id, level) for each_land_id in each_level
                      if each_land_id in nearby_land_ids]

        return lands

    def _get_top_leveled_land(self, limit=1024):
        land_with_level = self._get_land_with_level()

        lands = []
        for index, each_level in enumerate(reversed(land_with_level)):
            level = 10 - index

            if level < 2:
                continue

            if len(each_level) > limit:
                return lands + each_level[:limit]

            lands += [(each, level) for each in each_level]
            limit -= len(each_level)

        return lands

    @functools.lru_cache()
    def _get_zone_id_by_land_id(self, land_id):
        land_array = self._get_land_array_4_by_4()

        return ndindex(land_array, land_id)[0]

    @functools.lru_cache()
    def _get_nearest_zone(self, x, y, radius=16):
        lands = self._get_nearest_land(x, y, radius)
        zones = []
        for land_id, _ in lands:
            zone_id = self._get_zone_id_by_land_id(land_id)
            if zone_id not in zones:
                zones.append(zone_id)

        return zones

    def _get_nearest_zone_ng(self, x, y, radius=8):
        """Get zones sorted by actual tile distance from kingdom coordinates."""
        current_zone_id = lokbot.util.get_zone_id_by_coords(x, y)
        idx = ndindex(self._get_zone_array(), current_zone_id)

        # Get nearby zones in a radius
        nearby_zone_ids = neighbors(self._get_zone_array(), radius, idx[0] + 1,
                                    idx[1] + 1)
        nearby_zone_ids = [
            item.item() for sublist in nearby_zone_ids for item in sublist
            if item != 0
        ]

        # Kingdom position in actual tile coordinates
        kingdom_x = x
        kingdom_y = y

        logger.info(f"Kingdom location: [{kingdom_x}, {kingdom_y}]")

        # Calculate distances using actual tile coordinates
        zone_distances = []
        for zone_id in nearby_zone_ids:
            # Convert zone ID to zone coordinates
            zone_y = zone_id // 64
            zone_x = zone_id % 64

            # Convert zone coordinates to tile coordinates (center of zone)
            zone_tile_x = zone_x * 32 + 16  # Center of zone
            zone_tile_y = zone_y * 32 + 16  # Center of zone

            # Calculate Euclidean distance in tiles
            distance = math.sqrt((zone_tile_x - kingdom_x)**2 +
                                 (zone_tile_y - kingdom_y)**2)
            zone_distances.append((zone_id, distance, zone_x, zone_y))

        # Sort by distance
        sorted_zones = sorted(zone_distances, key=lambda x: x[1])

        # Log scanning order
        logger.info("Zone scanning order:")
        for zone_id, distance, x, y in sorted_zones[:5]:
            logger.info(
                f"Zone {zone_id} at [{x}, {y}], distance: {distance:.2f} tiles"
            )

        # Apply area restrictions if enabled
        filtered_zones = self._filter_zones_by_area_restrictions([zone[0] for zone in sorted_zones])
        
        return filtered_zones

    def _is_coordinate_in_allowed_areas(self, x, y):
        """
        Check if the given coordinates are within any of the allowed gathering areas.
        
        Args:
            x: X coordinate (0-2047)
            y: Y coordinate (0-2047)
            
        Returns:
            bool: True if coordinates are allowed, False otherwise
        """
        from lokbot import config
        
        # Get area restrictions from config
        restrictions = config.get('main', {}).get('object_scanning', {}).get('area_restrictions', {})
        
        # If restrictions are not enabled, allow all areas
        if not restrictions.get('enabled', False):
            return True
            
        allowed_areas = restrictions.get('allowed_areas', [])
        
        # If no areas defined, allow all (safety fallback)
        if not allowed_areas:
            return True
            
        # Check if coordinates fall within any allowed rectangular area
        for area in allowed_areas:
            min_x = area.get('min_x', 0)
            max_x = area.get('max_x', 2047)
            min_y = area.get('min_y', 0)
            max_y = area.get('max_y', 2047)
            
            if min_x <= x <= max_x and min_y <= y <= max_y:
                logger.debug(f"Coordinates [{x}, {y}] allowed in area: {area.get('name', 'Unnamed')}")
                return True
                
        logger.debug(f"Coordinates [{x}, {y}] outside all allowed areas")
        return False

    def _filter_zones_by_area_restrictions(self, zone_ids):
        """
        Filter zone list to only include zones that overlap with allowed areas.
        
        Args:
            zone_ids: List of zone IDs to filter
            
        Returns:
            list: Filtered list of zone IDs that are within allowed areas
        """
        from lokbot import config
        
        restrictions = config.get('main', {}).get('object_scanning', {}).get('area_restrictions', {})
        
        # If restrictions are not enabled, return all zones
        if not restrictions.get('enabled', False):
            return zone_ids
            
        allowed_zones = []
        
        for zone_id in zone_ids:
            # Convert zone ID to zone coordinates
            zone_y = zone_id // 64
            zone_x = zone_id % 64
            
            # Convert zone coordinates to tile coordinate boundaries
            zone_min_x = zone_x * 32
            zone_max_x = zone_x * 32 + 31
            zone_min_y = zone_y * 32
            zone_max_y = zone_y * 32 + 31
            
            # Check if any part of the zone overlaps with allowed areas
            zone_allowed = False
            for corner_x in [zone_min_x, zone_max_x]:
                for corner_y in [zone_min_y, zone_max_y]:
                    if self._is_coordinate_in_allowed_areas(corner_x, corner_y):
                        zone_allowed = True
                        break
                if zone_allowed:
                    break
                    
            # Also check zone center
            if not zone_allowed:
                zone_center_x = zone_x * 32 + 16
                zone_center_y = zone_y * 32 + 16
                if self._is_coordinate_in_allowed_areas(zone_center_x, zone_center_y):
                    zone_allowed = True
            
            if zone_allowed:
                allowed_zones.append(zone_id)
                
        if len(allowed_zones) != len(zone_ids):
            logger.info(f"Area restrictions filtered {len(zone_ids)} zones down to {len(allowed_zones)} allowed zones")
            
        return allowed_zones

    def _update_march_limit(self):
        try:
            troops = self.api.kingdom_profile_troops().get('troops')
            self.troop_queue = troops.get('field', [])
            self.march_limit = troops.get('info').get('marchLimit')
            self.march_size = troops.get('info').get('marchSize')

            # Send updated march status to web app
            self._send_march_status_update()

        except Exception as e:
            logger.error(f"Error updating march limit: {str(e)}")

    def _send_march_status_update(self):
        """Send march status update to web app"""
        try:
            import requests
            import os

            user_id = os.getenv('LOKBOT_USER_ID', 'web_user')
            instance_id = os.getenv('LOKBOT_INSTANCE_ID', 'unknown')
            account_name = os.getenv('LOKBOT_ACCOUNT_NAME')

            # If no account name in environment, try to get it from a more reliable source
            if not account_name or account_name in ['Bot Instance', 'unknown']:
                # Generate a meaningful account name based on instance timing
                if instance_id != 'unknown' and '_' in instance_id:
                    timestamp_part = instance_id.split('_')[-1]
                    account_name = f'Instance {timestamp_part[-4:]}'  # Use last 4 digits of timestamp
                else:
                    account_name = 'Bot Instance'

            march_data = {
                'user_id': user_id,
                'instance_id': instance_id,
                'account_name': account_name,
                'current_marches': len(self.troop_queue),
                'march_limit': self.march_limit,
                'march_size': self.march_size,
                'timestamp': time.time()
            }

            response = requests.post('http://localhost:5000/api/march_status_update',
                json=march_data, timeout=2)

        except Exception as e:
            logger.debug(f"Could not send march status update: {str(e)}")

    def _is_march_limit_exceeded(self, context='general'):
        """
        Check if march limit is exceeded with context-aware validation

        Args:
            context: The context for checking ('rally_join', 'rally_start', 'gathering', 'general')
        """
        # Get appropriate max marches based on context
        if context == 'rally_join':
            max_marches = config.get('rally', {}).get('join', {}).get('numMarch', 8)
        elif context == 'rally_start':
            max_marches = config.get('rally', {}).get('start', {}).get('numMarch', 8)
        elif context == 'gathering':
            max_marches = config.get('main', {}).get('object_scanning', {}).get('max_marches', self.march_limit)
        else:
            # General case - use the most restrictive limit
            max_marches = min(
                config.get('rally', {}).get('join', {}).get('numMarch', 8),
                config.get('rally', {}).get('start', {}).get('numMarch', 8),
                config.get('main', {}).get('object_scanning', {}).get('max_marches', self.march_limit)
            )

        current_queue_size = len(self.troop_queue)

        if current_queue_size >= max_marches:
            logger.debug(f"March limit exceeded: {current_queue_size}/{max_marches} (context: {context})")
            return True

        return False

    def _validate_march_capacity_for_gathering(self, to_loc, final_check=False):
        """
        Comprehensive march capacity validation for gathering with multiple data source checks

        Args:
            to_loc: Target location for the march
            final_check: If True, performs additional validation before march start

        Returns:
            bool: True if march capacity is available, False otherwise
        """
        try:
            # Get max marches from config first
            max_marches = config.get('main', {}).get('object_scanning', {}).get('max_marches')
            if not max_marches:
                logger.info("No max_marches configured in config file, skipping gather")
                return False

            # Update march limit information
            self._update_march_limit()

            # Get multiple data sources for march count validation
            internal_queue_size = len(self.troop_queue)

            # Get fresh march info from API
            try:
                march_info = self.api.field_march_info({
                    'fromId':
                    self.kingdom_enter.get('kingdom').get('fieldObjectId'),
                    'toLoc':
                    to_loc
                })
                api_march_count = march_info.get('numMarch', 0)
            except Exception as e:
                logger.error(f"Failed to get march info for capacity validation: {e}")
                return False

            # Get kingdom tasks for additional validation if performing final check
            active_march_tasks = 0
            if final_check:
                try:
                    kingdom_tasks = self.api.kingdom_task_all().get('kingdomTasks', [])
                    active_march_tasks = len([
                        task for task in kingdom_tasks
                        if task.get('code') in [TASK_CODE_MARCH_GATHER, TASK_CODE_MARCH_MONSTER, TASK_CODE_MARCH_RALLY]
                        and task.get('status') == 1  # Active status
                    ])
                except Exception as e:
                    logger.debug(f"Could not get kingdom tasks for march validation: {e}")
                    active_march_tasks = 0

            # Use the most conservative approach - take the highest count from all sources
            effective_march_count = max(
                internal_queue_size,
                api_march_count,
                active_march_tasks if final_check else 0
            )

            # Log detailed validation info
            check_type = "Final" if final_check else "Initial"
            logger.debug(f"{check_type} march capacity validation - Internal: {internal_queue_size}, API: {api_march_count}, Tasks: {active_march_tasks if final_check else 'N/A'}, Effective: {effective_march_count}, Max: {max_marches}")

            # Validate against configured maximum
            if effective_march_count >= max_marches:
                logger.debug(f"March capacity full (effective: {effective_march_count}/{max_marches}), cannot start gathering")
                return False

            # Additional context-aware validation
            if self._is_march_limit_exceeded('gathering'):
                logger.debug("March limit exceeded from context check")
                return False

            # Only add safety buffer if we're at actual capacity, not one below
            if final_check and effective_march_count >= max_marches:
                logger.debug(f"March capacity full on final check ({effective_march_count}/{max_marches})")
                return False

            logger.debug(f"March capacity validation passed - {effective_march_count}/{max_marches} marches active")
            return True

        except Exception as e:
            logger.error(f"Error in march capacity validation: {e}")
            return False

    def _is_object_being_marched(self, target_loc, target_foid=None):
        """
        High-frequency march conflict detection optimized for SOCF zone scanning
        Implements multiple validation layers including field object ID validation
        Enhanced with wait period for march data to arrive and improved logging
        """
        if not target_loc or len(target_loc) < 3:
            logger.error(f"Invalid target location provided: {target_loc}")
            return True  # Fail safe - skip if location is invalid

        try:
            with self.march_objects_lock:
                current_time = time.time()

                # ENHANCEMENT: Wait for march data to arrive for better accuracy
                validation_types = ["location"]
                if target_foid:
                    validation_types.append("field object ID")
                logger.info(f"Checking march conflicts for object at {target_loc} (FOID: {target_foid}) using {' and '.join(validation_types)} validation")
                logger.info("Waiting 3.5 seconds for fresh march data to arrive from zone...")

                # Wait for fresh march data (3.5 seconds to ensure proper verification)
                wait_time = 3.5
                time.sleep(wait_time)
                logger.info(f"Completed {wait_time:.1f} seconds wait for march data refresh")

                # Priority 1: Use zone-specific cached data if available and recent
                zone_key = f"{target_loc[0]//100},{target_loc[1]//100}"  # Group by 100x100 zones
                zone_data = self.march_data_by_zone.get(zone_key)

                march_data_to_use = None
                data_source = "unknown"

                if zone_data and (current_time - zone_data['timestamp']) < 60:  # 1 minute freshness for zone data
                    march_data_to_use = zone_data['data']
                    data_source = f"zone_cache_{zone_key}"
                    logger.info(f"Using zone-cached march data for conflict check (age: {current_time - zone_data['timestamp']:.1f}s)")

                # Priority 2: Use global march data if zone data not available
                if not march_data_to_use:
                    if not self.march_objects_data:
                        logger.info("No march objects data available after wait - assuming safe to proceed")
                        return False

                    data_age = current_time - self.march_objects_last_update
                    if data_age > self.max_march_data_age:
                        logger.warning(f"March objects data is stale ({data_age:.1f}s old) - clearing cache")
                        self.march_objects_data = {}
                        return False

                    march_data_to_use = self.march_objects_data
                    data_source = f"global_cache"

                # Validate target location format and sanitize
                try:
                    target_x, target_y, target_z = int(target_loc[0]), int(target_loc[1]), int(target_loc[2])
                    target_loc_normalized = [target_x, target_y, target_z]
                    target_loc_str = f"{target_x},{target_y},{target_z}"
                except (ValueError, IndexError, TypeError) as e:
                    logger.error(f"Invalid target location format {target_loc}: {e}")
                    return True  # Fail safe

                # ENHANCEMENT: Detailed logging of march data for verification
                logger.info(f"March data received from {data_source} for zone {zone_key}")
                logger.info(f"Raw march data structure: {type(march_data_to_use)}")
                if isinstance(march_data_to_use, dict):
                    logger.info(f"March data keys: {list(march_data_to_use.keys())}")
                elif isinstance(march_data_to_use, list):
                    logger.info(f"March data list length: {len(march_data_to_use)}")

                # Extract march objects with comprehensive validation
                march_objects = self._extract_march_objects_safely(march_data_to_use)

                if not march_objects:
                    logger.info("No march objects found in data after waiting - safe to proceed")
                    return False

                # ENHANCEMENT: Log all march objects for verification
                logger.info(f"Found {len(march_objects)} march objects to verify against target {target_loc} (FOID: {target_foid})")
                for i, march_obj in enumerate(march_objects[:5]):  # Log first 5 marches for verification
                    if isinstance(march_obj, dict):
                        march_location = self._extract_march_location_safely(march_obj)
                        march_foid = self._extract_march_foid_safely(march_obj)
                        logger.info(f"March {i+1}: Location={march_location}, FOID={march_foid}, Sample data: {dict(list(march_obj.items())[:3])}")

                # Check for conflicts with multiple validation approaches
                conflicts_found = []

                for i, march_obj in enumerate(march_objects):
                    if not isinstance(march_obj, dict):
                        logger.debug(f"Skipping invalid march object {i}: not a dict")
                        continue

                    # Extract march location and FOID for comparison
                    march_location = self._extract_march_location_safely(march_obj)
                    march_foid = self._extract_march_foid_safely(march_obj)

                    conflict_detected = False
                    conflict_reason = []

                    # Primary validation: Location match
                    if march_location and self._locations_match(target_loc_normalized, march_location):
                        conflict_detected = True
                        conflict_reason.append("location match")

                    # Enhanced validation: Field Object ID match (if available)
                    if target_foid and march_foid and str(target_foid) == str(march_foid):
                        conflict_detected = True
                        conflict_reason.append("FOID match")

                    if conflict_detected:
                        conflict_info = {
                            'march_index': i,
                            'march_location': march_location,
                            'march_foid': march_foid,
                            'conflict_reason': ' and '.join(conflict_reason),
                            'march_obj_sample': {k: v for k, v in list(march_obj.items())[:3]}  # Sample for logging
                        }
                        conflicts_found.append(conflict_info)

                # ENHANCEMENT: Detailed conflict reporting with full march data
                if conflicts_found:
                    logger.warning(f"🚨 MARCH CONFLICT DETECTED at {target_loc_str} (FOID: {target_foid}) using {data_source}")
                    logger.warning(f"Conflicting march details:")
                    for conflict in conflicts_found:
                        logger.warning(f"  - March #{conflict['march_index']}: Target={conflict['march_location']}, FOID={conflict['march_foid']}")
                        logger.warning(f"    Conflict reason: {conflict['conflict_reason']}")
                        logger.warning(f"    March object sample: {conflict['march_obj_sample']}")
                    logger.info(f"✋ Skipping gathering due to {len(conflicts_found)} march conflict(s)")
                    return True

                logger.info(f"✅ No march conflicts detected for {target_loc_str} (FOID: {target_foid}) - verified {len(march_objects)} marches, source: {data_source}")
                return False

        except Exception as e:
            logger.error(f"Critical error in march conflict detection: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            self.march_data_validation_errors += 1

            # If we're getting too many errors, clear the cache
            if self.march_data_validation_errors > 10:
                logger.error("Too many march data validation errors - clearing cache")
                self.march_objects_data = {}
                self.march_data_validation_errors = 0

            return True  # Fail safe - skip gathering if we can't validate safely

    def _extract_march_objects_safely(self, march_data):
        """Safely extract march objects from various data structures"""
        march_objects = []

        try:
            if isinstance(march_data, dict):
                # Try multiple field names for march data
                for field_name in ['objects', 'marches', 'data', 'items', 'marchObjects', 'activeMarches']:
                    if field_name in march_data:
                        field_data = march_data[field_name]
                        if isinstance(field_data, list):
                            march_objects.extend([obj for obj in field_data if isinstance(obj, dict)])
                            break
                        elif isinstance(field_data, dict):
                            march_objects.append(field_data)
                            break

                # If no standard fields found, try direct iteration
                if not march_objects:
                    for key, value in march_data.items():
                        if isinstance(value, list) and value and isinstance(value[0], dict):
                            # Check if this looks like march data
                            if any(loc_field in value[0] for loc_field in ['loc', 'toLoc', 'destination']):
                                march_objects.extend(value)
                                break

            elif isinstance(march_data, list):
                march_objects = [obj for obj in march_data if isinstance(obj, dict)]

        except Exception as e:
            logger.error(f"Error extracting march objects: {e}")

        return march_objects

    def _extract_march_location_safely(self, march_obj):
        """Safely extract location from march object with multiple validation approaches"""
        location_fields = ['loc', 'toLoc', 'location', 'target_loc', 'destination', 'targetLoc', 'endLoc']

        for loc_field in location_fields:
            try:
                march_loc = march_obj.get(loc_field)
                if not march_loc:
                    continue

                # Handle different location formats
                if isinstance(march_loc, list) and len(march_loc) >= 3:
                    try:
                        return [int(march_loc[0]), int(march_loc[1]), int(march_loc[2])]
                    except (ValueError, IndexError):
                        continue

                elif isinstance(march_loc, str):
                    # Try parsing string formats like "x,y,z"
                    try:
                        parts = march_loc.split(',')
                        if len(parts) >= 3:
                            return [int(parts[0]), int(parts[1]), int(parts[2])]
                    except (ValueError, IndexError):
                        continue

                elif isinstance(march_loc, dict):
                    # Handle nested location objects
                    try:
                        if all(k in march_loc for k in ['x', 'y', 'z']):
                            return [int(march_loc['x']), int(march_loc['y']), int(march_loc['z'])]
                        elif all(str(i) in march_loc for i in range(3)):
                            return [int(march_loc['0']), int(march_loc['1']), int(march_loc['2'])]
                    except (ValueError, KeyError):
                        continue

            except Exception as e:
                logger.debug(f"Error extracting location from field {loc_field}: {e}")
                continue

        return None

    def _extract_march_foid_safely(self, march_obj):
        """Safely extract field object ID from march object with multiple validation approaches"""
        foid_fields = ['toId', 'targetId', 'fieldObjectId', 'foid', 'fo_id', 'objectId', 'target_foid', 'destination_id']

        for foid_field in foid_fields:
            try:
                march_foid = march_obj.get(foid_field)
                if march_foid:
                    # Handle different FOID formats
                    if isinstance(march_foid, (str, int)):
                        try:
                            return str(march_foid)  # Normalize to string for consistent comparison
                        except (ValueError, TypeError):
                            continue
                    elif isinstance(march_foid, dict) and 'id' in march_foid:
                        # Handle nested FOID objects
                        try:
                            return str(march_foid['id'])
                        except (ValueError, TypeError, KeyError):
                            continue

            except Exception as e:
                logger.debug(f"Error extracting FOID from field {foid_field}: {e}")
                continue

        return None

    def _locations_match(self, loc1, loc2):
        """Compare two locations with multiple validation methods"""
        if not loc1 or not loc2 or len(loc1) < 3 or len(loc2) < 3:
            return False

        try:
            # Exact match
            if loc1[0] == loc2[0] and loc1[1] == loc2[1] and loc1[2] == loc2[2]:
                return True

            # String comparison as fallback
            loc1_str = f"{loc1[0]},{loc1[1]},{loc1[2]}"
            loc2_str = f"{loc2[0]},{loc2[1]},{loc2[2]}"
            return loc1_str == loc2_str

        except Exception as e:
            logger.debug(f"Error comparing locations {loc1} and {loc2}: {e}")
            return False

    def _set_current_scanning_zone(self, zone_coords):
        """Set the current zone being scanned by SOCF for optimized march data caching"""
        try:
            with self.march_objects_lock:
                self.current_scanning_zone = zone_coords
                if zone_coords:
                    logger.debug(f"SOCF scanning zone set to: [{zone_coords[0]},{zone_coords[1]}]")
                else:
                    logger.debug("SOCF scanning zone cleared")
        except Exception as e:
            logger.error(f"Error setting current scanning zone: {e}")

    def _get_march_data_stats(self):
        """Get statistics about march data updates for monitoring"""
        try:
            with self.march_objects_lock:
                current_time = time.time()
                global_age = current_time - self.march_objects_last_update if self.march_objects_data else None
                zone_count = len(self.march_data_by_zone)

                zone_ages = {}
                for zone_key, zone_data in self.march_data_by_zone.items():
                    zone_ages[zone_key] = current_time - zone_data['timestamp']

                return {
                    'update_count': self.march_data_update_count,
                    'global_data_age': global_age,
                    'zone_cache_count': zone_count,
                    'zone_ages': zone_ages,
                    'current_scanning_zone': self.current_scanning_zone
                }
        except Exception as e:
            logger.error(f"Error getting march data stats: {e}")
            return {}

    @staticmethod
    def _calc_distance(from_loc, to_loc):
        return math.ceil(
            math.sqrt(
                math.pow(from_loc[1] - to_loc[1], 2) +
                math.pow(from_loc[2] - to_loc[2], 2)))

    def _start_march(self,
                     to_loc,
                     march_troops,
                     march_type=MARCH_TYPE_GATHER,
                     drago_id=None):
        data = {
            'fromId': self.kingdom_enter.get('kingdom').get('fieldObjectId'),
            'marchType': march_type,
            'toLoc': to_loc,
            'marchTroops': march_troops
        }

        if drago_id:
            data['dragoId'] = drago_id

        res = self.api.field_march_start(data)

        new_task = res.get('newTask')
        new_task['endTime'] = new_task['expectedEnded']
        self.troop_queue.append(new_task)

        # Update march status after starting a march
        self._send_march_status_update()

        # Send gathering march notification if it's a gather march
        if march_type == MARCH_TYPE_GATHER:
            try:
                # Get resource info for notification
                march_info = self.api.field_march_info({
                    'fromId':
                    self.kingdom_enter.get('kingdom').get('fieldObjectId'),
                    'toLoc':
                    to_loc
                })
                resource_code = march_info.get('fo', {}).get('code')
                resource_level = march_info.get('fo', {}).get('level')

                # Map resource code to readable name
                resource_names = {
                    20100101: "Farm",
                    20100102: "Gold Mine",
                    20100103: "Lumber Camp",
                    20100104: "Quarry",
                    20100105: "Crystal Mine",
                    20100106: "Dragon Soul Cavern"
                }
                resource_type = resource_names.get(
                    resource_code, f"Resource {resource_code}")

                started_time = arrow.get(
                    new_task['started']).format('YYYY-MM-DD HH:mm:ss')
                ended_time = arrow.get(new_task['expectedEnded']).format(
                    'YYYY-MM-DD HH:mm:ss')

                # Log gathering march locally
                logger.info(f"🚛 Gathering March Started! Resource: {resource_type} (Level {resource_level}) at {to_loc}")

                # Send to web app notification system
                try:
                    import requests
                    import os
                    import time
                    user_id = os.getenv('LOKBOT_USER_ID', 'web_user')

                    # Generate instance_id and account_name based on current process
                    timestamp = int(time.time() * 1000)
                    instance_id = os.getenv('LOKBOT_INSTANCE_ID', f"{user_id}_{timestamp}")
                    account_name = os.getenv('LOKBOT_ACCOUNT_NAME', 'Bot Instance')

                    gathering_message = f"""Gathering March Started!
Resource: {resource_type} (Level {resource_level})
Location: {to_loc}
Started: {started_time}
Expected End: {ended_time}"""

                    response = requests.post('http://localhost:5000/api/gathering_notification',
                        json={
                            'resource_type': resource_type,
                            'resource_code': resource_code,
                            'level': resource_level,
                            'location': to_loc,
                            'started_time': started_time,
                            'ended_time': ended_time,
                            'formatted_message': gathering_message,
                            'user_id': user_id,
                            'instance_id': instance_id,
                            'account_name': account_name
                        },
                        timeout=2)
                    logger.info("Gathering notification sent to web app")
                except Exception as e:
                    logger.error(f"Error sending gathering notification to web app: {str(e)}")

                # Send Discord notification if enabled
                if config.get('discord', {}).get('enabled', False):
                    from lokbot.discord_webhook import DiscordWebhook
                    webhook_url = config.get('discord', {}).get('gathering_webhook_url')
                    if webhook_url:
                        webhook = DiscordWebhook(webhook_url)

                        message = "**Gathering March Started**\n"
                        message += f"Resource Type: {resource_type}\n"
                        message += f"Level: {resource_level}\n"
                        message += f"Location: {to_loc}\n"
                        message += f"Started: {started_time}\n"
                        message += f"Expected End: {ended_time}"

                        webhook.send_message(message)
                        logger.info("Gathering notification sent to Discord")
            except Exception as e:
                logger.error(
                    f"Failed to send gathering notification: {str(e)}")

    def _prepare_march_troops(self, each_obj, march_type=MARCH_TYPE_GATHER, ):
        march_info = self.api.field_march_info({
            'fromId':
            self.kingdom_enter.get('kingdom').get('fieldObjectId'),
            'toLoc':
            each_obj.get('loc')
        })

        expired_ts = arrow.get(march_info.get('fo').get('expired')).timestamp()
        if expired_ts < arrow.now().timestamp():
            logger.info(f'Expired: {march_info}')
            return []

        if march_type == MARCH_TYPE_MONSTER:
            # check if monster is already dead
            if march_info.get('fo').get('code') != each_obj.get('code'):
                return []

            # Get normal monsters config
            normal_monsters_config = config.get('main',
                                                {}).get('normal_monsters', {})
            if not normal_monsters_config:
                logger.info('No normal_monsters configuration found')
                return []

            monster_code = each_obj.get('code')
            monster_level = each_obj.get('level')

            # No hardcoded level restrictions - let config determine valid levels

            # Find target configuration
            target_monster = next(
                (target
                 for target in normal_monsters_config.get('targets', [])
                 if target.get('monster_code') == monster_code
                 and monster_level in target.get('level_ranges', [])), None)

            if not target_monster:
                logger.info(
                    f'Monster {monster_code} level {monster_level} not in configured targets'
                )
                return []

            # Use common troops configuration instead of fixed troops
            common_troops_config = normal_monsters_config.get('common_troops', [])
            if not common_troops_config:
                logger.info(f'No common troops configuration found for normal monsters')
                return []

            # Build available troops dictionary from march info
            available_troops = {}
            for troop in march_info.get('troops', []):
                troop_code = troop.get('code')
                troop_count = troop.get('amount', 0)
                available_troops[troop_code] = troop_count

            # Prepare march troops based on common troops configuration
            march_troops = []
            total_troops_needed = 0

            for troop_config in common_troops_config:
                troop_code = troop_config.get('code')
                configured_amount = troop_config.get('amount', 0)
                troop_name = troop_config.get('name', f'Troop {troop_code}')

                if configured_amount <= 0:
                    logger.debug(f'Skipping {troop_name} - amount is 0 in common troops config')
                    continue

                available = available_troops.get(troop_code, 0)
                if available < configured_amount:
                    logger.info(
                        f'Not enough {troop_name}: need {configured_amount}, have {available}'
                    )
                    return []

                march_troops.append({
                    'code': troop_code,
                    'level': 0,
                    'select': 0,
                    'amount': configured_amount,
                    'dead': 0,
                    'wounded': 0,
                    'hp': 0,
                    'attack': 0,
                    'defense': 0,
                    'seq': 0
                })
                total_troops_needed += configured_amount
                logger.debug(f'Added {configured_amount} {troop_name} to march')

            if not march_troops:
                logger.info('No troops configured for this monster level')
                return []

            logger.info(f'Using COMMON TROOPS - Prepared {total_troops_needed} total troops for monster level {monster_level}')
            return march_troops

        # For non-deathkar monsters and resources, use original logic
        troops = march_info.get('troops')
        troops.sort(key=lambda x: x.get('code'),
                    reverse=True)  # priority using high tier troops

        need_troop_count = march_info.get('fo').get('param').get('value')
        if march_type == MARCH_TYPE_MONSTER:
            need_troop_count *= 2.5

        if not need_troop_count:
            # "value": 0, means no more resources or monster
            return []

        troop_count = sum([each_troop.get('amount') for each_troop in troops])
        # we don't care about insufficient troops when gathering
        if (march_type == MARCH_TYPE_MONSTER) and (need_troop_count
                                                   > troop_count):
            logger.info(
                f'Insufficient troops: {troop_count} < {need_troop_count}: {each_obj}'
            )
            return []

        march_troops = []
        for troop in troops:
            code = troop.get('code')
            amount = troop.get('amount')

            # todo: calc troops load for MARCH_TYPE_MONSTER
            load = 1
            if march_type == MARCH_TYPE_GATHER:
                load = TROOP_LOAD_MAP.get(code, 1)

            total_load = amount * load

            if total_load >= need_troop_count:
                if need_troop_count == 0:
                    amount = 0
                else:
                    amount = math.ceil(need_troop_count / load)
                    need_troop_count = 0
            else:
                need_troop_count -= total_load

            march_troops.append({
                'code': code,
                'level': 0,
                'select': 0,
                'amount': int(amount),
                'dead': 0,
                'wounded': 0,
                'hp': 0,
                'attack': 0,
                'defense': 0,
                'seq': 0
            })

        march_troop_count = sum(
            [each_troop.get('amount') for each_troop in march_troops])
        if march_troop_count > self.march_size:
            logger.info(
                f'Troop count exceeded: {march_troop_count} > {self.march_size}: {each_obj}'
            )
            return []

        march_troops.sort(key=lambda x: x.get('code'))  # sort by code asc

        return march_troops

    def _get_available_dragos(self):
        drago_lair_list = self.api.drago_lair_list()
        dragos = drago_lair_list.get('dragos')
        available_dragos = [
            each for each in dragos
            if each['lair']['status'] == DRAGO_LAIR_STATUS_STANDBY
        ]

        return available_dragos

    def _handle_crystal_limit_error(self):
        """Handle crystal limit error by sending notification and stopping SOCF thread"""
        try:
            logger.critical("⚠️ CRYSTAL LIMIT REACHED - STOPPING BOT")

            # Send notification to web app
            try:
                import os
                import requests
                user_id = os.getenv('LOKBOT_USER_ID', 'web_user')

                # Generate instance_id and account_name based on current process
                import time
                timestamp = int(time.time() * 1000)
                instance_id = os.getenv('LOKBOT_INSTANCE_ID', f"{user_id}_{timestamp}")
                account_name = os.getenv('LOKBOT_ACCOUNT_NAME', 'Bot Instance')

                crystal_message = "🚨 **CRYSTAL LIMIT REACHED** - Your Daily Crystal Limit is Over, Please Stop the Bot"

                response = requests.post('http://localhost:5000/api/crystal_limit_notification',
                    json={
                        'user_id': user_id,
                        'instance_id': instance_id,
                        'account_name': account_name,
                        'message': crystal_message
                    },
                    timeout=2)
                logger.info("Crystal limit notification sent to web app")
            except Exception as e:
                logger.error(f"Failed to send crystal limit notification to web app: {e}")

            # Send Discord notification if enabled
            try:
                from lokbot import config
                if config.get('discord', {}).get('enabled', False):
                    from lokbot.discord_webhook import DiscordWebhook
                    webhook_url = config.get('discord', {}).get('webhook_url')
                    if webhook_url:
                        webhook = DiscordWebhook(webhook_url)
                        webhook.send_message("🚨 **CRYSTAL LIMIT REACHED** - Your Daily Crystal Limit is Over, Please Stop the Bot")
            except Exception as e:
                logger.error(f"Failed to send Discord crystal limit notification: {e}")

            # Stop SOCF thread by setting a flag
            self.crystal_limit_reached = True
            self.socf_thread_active = False

            logger.critical("SOCF thread terminated due to crystal limit")

        except Exception as e:
            logger.error(f"Error handling crystal limit: {str(e)}")

    def _skin_change_thread(self):
        """Thread to handle automatic skin changes based on configuration from multiple sources"""
        logger.info("Skin change thread started")

        while True:
            try:
                # Check all potential skin change sources
                skin_configs = self._get_all_skin_change_configs()
                
                if not skin_configs:
                    logger.debug("No skin change configurations enabled, waiting...")
                    time.sleep(60)  # Check every minute
                    continue

                current_time = time.time()

                # Process each enabled skin change configuration
                for source, config_data in skin_configs.items():
                    skin_item_id = config_data.get('skin_item_id', '')
                    change_interval_minutes = config_data.get('skin_change_interval', 60)
                    
                    if not skin_item_id:
                        logger.warning(f"Skin item ID not configured for {source}, skipping...")
                        continue

                    # Convert interval to seconds
                    change_interval_seconds = change_interval_minutes * 60
                    
                    # Use source-specific last change tracking
                    last_change_key = f'skin_last_change_{source}'
                    if not hasattr(self, last_change_key):
                        setattr(self, last_change_key, 0)
                    
                    last_change = getattr(self, last_change_key)

                    # Check if enough time has passed since last skin change for this source
                    if current_time - last_change >= change_interval_seconds:
                        try:
                            # Handle special Skills workflow
                            if source == 'skills':
                                self._handle_skills_skin_workflow(skin_item_id, current_time, last_change_key)
                            else:
                                # Standard skin change for other sources
                                self._perform_skin_change(skin_item_id, source, current_time, last_change_key)

                        except Exception as e:
                            logger.error(f"Error changing skin for {source}: {str(e)}")

                # Wait before next check (check every minute)
                time.sleep(60)

            except Exception as e:
                logger.error(f"Error in skin change thread: {str(e)}")
                time.sleep(60)

    def _get_skin_id_from_nft_id(self, nft_id):
        """Get skin ID from NFT ID by calling the API
        :param nft_id: The NFT ID to lookup
        :return: The corresponding skin ID (_id) or None if not found
        """
        try:
            if not nft_id:
                logger.warning("Empty NFT ID provided for skin lookup")
                return None
                
            # Convert to string to ensure consistent comparison
            nft_id = str(nft_id)
            
            logger.info(f"Looking up Skin ID for NFT ID: {nft_id}")
            
            # Call the API to get skin list
            skin_list_response = self.api.kingdom_skin_list({"type": 0})
            
            if not skin_list_response or not skin_list_response.get('result'):
                logger.error(f"Failed to fetch skin list: {skin_list_response}")
                return None
                
            skins = skin_list_response.get('skins', [])
            logger.debug(f"Retrieved {len(skins)} skins from API")
            
            # Search for matching NFT ID
            for skin in skins:
                skin_nft_id = str(skin.get('nftId', ''))
                if skin_nft_id == nft_id:
                    skin_id = skin.get('_id')
                    logger.info(f"✅ Found match! NFT ID {nft_id} -> Skin ID {skin_id}")
                    return skin_id
                    
            logger.warning(f"❌ No skin found with NFT ID: {nft_id}")
            logger.debug("Available NFT IDs in skin list:")
            for skin in skins[:10]:  # Log first 10 for debugging
                logger.debug(f"  NFT ID: {skin.get('nftId', 'Unknown')} -> Skin ID: {skin.get('_id', 'Unknown')}")
            
            return None
            
        except Exception as e:
            logger.error(f"Error looking up skin ID for NFT ID {nft_id}: {str(e)}")
            return None

    def _get_all_skin_change_configs(self):
        """Collect skin change configurations from all enabled sources"""
        skin_configs = {}
        
        # Check rally-join configuration
        rally_join_config = config.get('rally', {}).get('join', {})
        if rally_join_config.get('enabled', False) and rally_join_config.get('skin_change_enabled', False):
            skin_configs['rally_join'] = rally_join_config
            
        # Check rally-start configuration
        rally_start_config = config.get('rally', {}).get('start', {})
        if rally_start_config.get('enabled', False) and rally_start_config.get('skin_change_enabled', False):
            skin_configs['rally_start'] = rally_start_config
            
        # Check object scanning configuration
        object_scanning_config = config.get('main', {}).get('object_scanning', {})
        skin_change_settings = object_scanning_config.get('skin_change_settings', {})
        if object_scanning_config.get('enabled', False) and skin_change_settings.get('enabled', False):
            skin_configs['object_scanning'] = skin_change_settings
            
        # Check skills configuration  
        skills_config = config.get('main', {}).get('skills', {})
        if skills_config.get('enabled', False) and skills_config.get('skin_change_enabled', False):
            skin_configs['skills'] = skills_config
            
        # Check treasure configuration (existing functionality)
        treasure_config = config.get('main', {}).get('treasure', {})
        if treasure_config.get('enabled', False) and treasure_config.get('skin_change_enabled', False):
            skin_configs['treasure'] = treasure_config
            
        return skin_configs

    def _perform_skin_change(self, skin_nft_id, source, current_time, last_change_key):
        """Perform a standard skin change using NFT ID
        :param skin_nft_id: The NFT ID of the skin to equip
        :param source: Source of the skin change request
        :param current_time: Current timestamp
        :param last_change_key: Key for tracking last change time
        """
        try:
            # Convert NFT ID to Skin ID
            skin_id = self._get_skin_id_from_nft_id(skin_nft_id)
            
            if not skin_id:
                logger.error(f"Failed to find Skin ID for NFT ID: {skin_nft_id} (source: {source})")
                return
            
            logger.info(f"Using NFT ID {skin_nft_id} -> Skin ID {skin_id} for {source}")
            
            # Prepare the payload with the looked-up Skin ID
            payload = {"itemId": skin_id}

            # Call the skin equip API
            result = self.api.kingdom_skin_equip(payload)

            if result and result.get('result'):
                logger.info(f"✅ Successfully changed skin using NFT ID: {skin_nft_id} -> Skin ID: {skin_id} (source: {source})")
                setattr(self, last_change_key, current_time)
                
                # Send skin change notification
                try:
                    self._send_notification(
                        'skin_changed',
                        '👕 Skin Changed',
                        f'Successfully changed skin to {skin_id} (NFT ID: {skin_nft_id}) for {source}'
                    )
                except Exception as notif_error:
                    logger.debug(f"Failed to send skin change notification: {notif_error}")
            else:
                logger.warning(f"❌ Failed to change skin for {source}: {result}")

        except Exception as e:
            logger.error(f"Error changing skin for {source}: {str(e)}")

    def _handle_skills_skin_workflow(self, skin_nft_id, current_time, last_change_key):
        """Handle the 6-step Skills workflow using NFT IDs:
        1. Change skin (Skin 1)
        2. Change Treasure Page (First Treasure Page)  
        3. Activate Increase resource production (Code = 10018)
        4. Instant Harvest (Code = 10001)
        5. Change Treasure Page (Second Treasure page)
        6. Skin Change Second Skin
        """
        try:
            logger.info("Starting Skills 6-step activation workflow with NFT IDs")
            
            # Get skills config for second skin NFT ID and treasure pages
            skills_config = config.get('main', {}).get('skills', {})
            skin_nft_id_2 = skills_config.get('skin_item_id_2', '')
            treasure_page_1 = skills_config.get('treasure_page_1', 1)
            treasure_page_2 = skills_config.get('treasure_page_2', 2)
            
            # Step 1: Change skin (Skin 1) using NFT ID
            logger.info(f"Step 1: Looking up Skin ID for NFT ID: {skin_nft_id}")
            skin_id = self._get_skin_id_from_nft_id(skin_nft_id)
            
            if not skin_id:
                logger.error(f"❌ Step 1 Failed: Could not find Skin ID for NFT ID: {skin_nft_id}")
                return
                
            payload = {"itemId": skin_id}
            result = self.api.kingdom_skin_equip(payload)
            
            if not (result and result.get('result')):
                logger.warning(f"❌ Step 1 Failed - Skin change: {result}")
                return
                
            logger.info(f"✅ Step 1 Complete: Changed to first skin using NFT ID: {skin_nft_id} -> Skin ID: {skin_id}")
            time.sleep(2)  # Small delay between steps
            
            # Step 2: Change Treasure Page (First Treasure Page)
            try:
                logger.info(f"Step 2: Changing to treasure page {treasure_page_1}")
                self.api.kingdom_treasure_page(treasure_page_1)
                logger.info(f"✅ Step 2 Complete: Changed to treasure page {treasure_page_1}")
                time.sleep(2)
            except Exception as e:
                logger.error(f"❌ Step 2 Failed: Error changing to treasure page {treasure_page_1}: {str(e)}")
            
            # Step 3: Activate Increase resource production (Code = 10018)
            try:
                logger.info("Step 3: Activating Increase Resource Production skill (Code = 10018)")
                skill_result_10018 = self.api.skill_use(10018)
                
                if skill_result_10018 and skill_result_10018.get('result'):
                    logger.info("✅ Step 3 Complete: Successfully activated Increase Resource Production skill (10018)")
                else:
                    logger.warning(f"❌ Step 3 Failed: Could not activate skill 10018: {skill_result_10018}")
                time.sleep(2)
            except Exception as e:
                logger.error(f"❌ Step 3 Failed: Error activating skill 10018: {str(e)}")
            
            # Step 4: Instant Harvest (Code = 10001)
            try:
                logger.info("Step 4: Activating Instant Harvest skill (Code = 10001)")
                skill_result_10001 = self.api.skill_use(10001)
                
                if skill_result_10001 and skill_result_10001.get('result'):
                    logger.info("✅ Step 4 Complete: Successfully activated Instant Harvest skill (10001)")
                else:
                    logger.warning(f"❌ Step 4 Failed: Could not activate skill 10001: {skill_result_10001}")
                time.sleep(2)
            except Exception as e:
                logger.error(f"❌ Step 4 Failed: Error activating skill 10001: {str(e)}")
            
            # Step 5: Change Treasure Page (Second Treasure page)
            try:
                logger.info(f"Step 5: Changing to treasure page {treasure_page_2}")
                self.api.kingdom_treasure_page(treasure_page_2)
                logger.info(f"✅ Step 5 Complete: Changed to treasure page {treasure_page_2}")
                time.sleep(2)
            except Exception as e:
                logger.error(f"❌ Step 5 Failed: Error changing to treasure page {treasure_page_2}: {str(e)}")
            
            # Step 6: Skin Change Second Skin using NFT ID
            if skin_nft_id_2:
                try:
                    logger.info(f"Step 6: Looking up Skin ID for second NFT ID: {skin_nft_id_2}")
                    skin_id_2 = self._get_skin_id_from_nft_id(skin_nft_id_2)
                    
                    if not skin_id_2:
                        logger.error(f"❌ Step 6 Failed: Could not find Skin ID for NFT ID: {skin_nft_id_2}")
                    else:
                        logger.info(f"Step 6: Changing to second skin using NFT ID: {skin_nft_id_2} -> Skin ID: {skin_id_2}")
                        payload2 = {"itemId": skin_id_2}
                        result2 = self.api.kingdom_skin_equip(payload2)
                        
                        if result2 and result2.get('result'):
                            logger.info(f"✅ Step 6 Complete: Successfully changed to second skin using NFT ID: {skin_nft_id_2} -> Skin ID: {skin_id_2}")
                        else:
                            logger.warning(f"❌ Step 6 Failed: Could not change to second skin: {result2}")
                except Exception as e:
                    logger.error(f"❌ Step 6 Failed: Error changing to second skin: {str(e)}")
            else:
                logger.warning("❌ Step 6 Skipped: No second skin NFT ID configured")
            
            # Update last change time
            setattr(self, last_change_key, current_time)
            
            # Send completion notification
            try:
                self._send_skills_completion_notification()
            except Exception as e:
                logger.error(f"Error sending skills completion notification: {str(e)}")
            
            logger.info("🎉 Skills 6-step activation workflow completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Error in Skills 6-step workflow: {str(e)}")

    def _send_notification(self, notification_type, title, message):
        """Send notification to web app
        
        Args:
            notification_type: Type of notification ('skill_activated', 'buff_activated', 'skin_changed', etc.)
            title: Notification title
            message: Notification message
        """
        try:
            import requests
            
            # Get account name for notification
            account_name = getattr(self, 'account_name', 'Bot Instance')
            
            # Prepare notification data
            notification_data = {
                'user_id': self._id,
                'instance_id': self._id,
                'account_name': account_name,
                'notification_type': notification_type,
                'title': title,
                'message': message,
                'timestamp': time.time()
            }
            
            # Send to web app notification endpoint
            response = requests.post('http://localhost:5000/api/skills_notification', json=notification_data, timeout=5)
            if response.status_code == 200:
                logger.debug(f"Notification sent successfully: {notification_type}")
            else:
                logger.warning(f"Failed to send notification: {response.status_code}")
                
        except Exception as e:
            logger.debug(f"Error sending notification: {str(e)}")

    def _send_skills_completion_notification(self):
        """Send notification when skills activation workflow is completed"""
        try:
            self._send_notification(
                'skills_completion',
                '🎉 Skills Activation Complete',
                'All 6 steps of skills activation workflow completed successfully:\n• Skin 1 equipped\n• Treasure page 1 set\n• Resource production boost activated (10018)\n• Instant harvest activated (10001)\n• Treasure page 2 set\n• Skin 2 equipped'
            )
        except Exception as e:
            logger.error(f"Error sending skills completion notification: {str(e)}")

    def _skills_management_thread(self):
        """Skills management thread that runs at bot start and every 10 minutes"""
        logger.info("Skills management thread started")
        
        # Run skills immediately at startup
        self._execute_skills()
        
        # Then run every 10 minutes
        while True:
            try:
                time.sleep(600)  # Wait 10 minutes (600 seconds)
                self._execute_skills()
            except Exception as e:
                logger.error(f"Error in skills management thread: {str(e)}")
                time.sleep(60)  # Wait 1 minute on error before retrying

    def _execute_skills(self):
        """Execute configured skills if skills system is enabled"""
        try:
            # Get current config
            from lokbot import config
            skills_config = config.get('main', {}).get('skills', {})
            
            if not skills_config.get('enabled', False):
                logger.debug("Skills system is disabled")
                return
                
            logger.info("Executing skills configuration")
            
            # Get available skills from API
            skill_list = self.api.skill_list()
            available_skills_data = skill_list.get('skills', [])
            available_skill_codes = [skill.get('code') for skill in available_skills_data]
            
            logger.info(f"Available skills from API: {available_skill_codes}")

            # Check configured skills
            configured_skills = skills_config.get('skills', [])
            logger.info(f"Configured skills: {configured_skills}")

            # Use enabled skills if available 
            for skill_config in configured_skills:
                skill_code = skill_config.get('code')
                skill_enabled = skill_config.get('enabled', False)
                
                logger.info(f"Processing skill {skill_code}: enabled={skill_enabled}")
                
                if not skill_enabled:
                    logger.info(f"Skill {skill_code} is disabled in config, skipping")
                    continue
                    
                if skill_code not in available_skill_codes:
                    logger.warning(f"Skill {skill_code} is not available in game, skipping")
                    continue

                try:
                    # Get skill info to check cooldown
                    skill_info = next((s for s in available_skills_data if s.get('code') == skill_code), None)
                    if skill_info:
                        next_skill_time = skill_info.get('nextSkillTime')
                        if next_skill_time:
                            # Parse the cooldown time and compare with current time
                            from datetime import datetime
                            try:
                                # Parse the ISO format time string
                                cooldown_time = datetime.fromisoformat(next_skill_time.replace('Z', '+00:00'))
                                current_time = datetime.now(cooldown_time.tzinfo)
                                
                                if current_time < cooldown_time:
                                    logger.info(f"Skill {skill_code} is on cooldown until {next_skill_time} (current: {current_time.isoformat()})")
                                    continue
                                else:
                                    logger.info(f"Skill {skill_code} cooldown has expired ({next_skill_time} < {current_time.isoformat()}), proceeding to activate")
                            except Exception as time_parse_error:
                                logger.warning(f"Could not parse cooldown time for skill {skill_code}: {time_parse_error}. Attempting to use skill anyway.")
                                # If we can't parse the time, try to use the skill anyway

                    # Try to use the skill
                    logger.info(f"Attempting to use skill {skill_code}")
                    self.api.skill_use(skill_code)
                    logger.info(f"Successfully used skill {skill_code}")
                    
                    # Send skill activation notification
                    try:
                        skill_name = skill_info.get('name', f'Skill {skill_code}') if skill_info else f'Skill {skill_code}'
                        self._send_notification(
                            'skill_activated',
                            '⚡ Skill Activated',
                            f'Successfully activated {skill_name} (Code: {skill_code})'
                        )
                    except Exception as notif_error:
                        logger.debug(f"Failed to send skill notification: {notif_error}")
                    
                    # Add delay between skill uses
                    time.sleep(random.uniform(1, 3))
                    
                except OtherException as e:
                    error_str = str(e)
                    if error_str == 'yet_in_cooltime':
                        logger.info(f"Skill {skill_code} is still on cooldown")
                    elif error_str == 'not_enough_mp':
                        logger.info(f"Not enough MP to use skill {skill_code}")
                    else:
                        logger.error(f"Error using skill {skill_code}: {error_str}")
                except Exception as e:
                    logger.error(f"Unexpected error using skill {skill_code}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in skills execution: {e}")

    def _on_field_objects_gather(self, each_obj):
        # Check crystal limit first
        if getattr(self, 'crystal_limit_reached', False):
            logger.critical("Gathering stopped - Crystal limit reached")
            return False

        # Check if gathering is enabled in config FIRST - before any other processing
        enable_gathering = config.get('main', {}).get('object_scanning', {}).get('enable_gathering', False)
        if not enable_gathering:
            enable_gathering = config.get('toggles', {}).get('features', {}).get('enable_gathering', False)

        if not enable_gathering:
            logger.debug("Gathering is disabled in config, skipping gather")
            return False

        if each_obj.get('occupied'):
            return False

        if each_obj.get('code') == OBJECT_CODE_CRYSTAL_MINE and self.level < 11:
            return False

        to_loc = each_obj.get('loc')
        target_foid = each_obj.get('_id')  # Extract field object ID from the object

        # Check area restrictions before proceeding
        if to_loc and len(to_loc) >= 2:
            x, y = to_loc[0], to_loc[1]
            if not self._is_coordinate_in_allowed_areas(x, y):
                logger.debug(f"Skipping gathering - coordinates [{x}, {y}] outside allowed areas")
                return False

        # CHECK FOR MARCH CONFLICTS BEFORE PROCEEDING (with location and FOID validation)
        if self._is_object_being_marched(to_loc, target_foid):
            logger.warning(f"Skipping gathering at {to_loc} (FOID: {target_foid}) - object is already being marched to")
            return False

        # Enhanced march limit validation with comprehensive checks
        if not self._validate_march_capacity_for_gathering(to_loc):
            return False

        march_troops = self._prepare_march_troops(each_obj, MARCH_TYPE_GATHER)
        if not march_troops:
            return False

        # Final check: ensure total troops to send is greater than 0
        total_troops = sum(troop.get('amount', 0) for troop in march_troops)
        if total_troops <= 0:
            logger.debug(f"No troops available for gathering at {to_loc}, skipping")
            return False

        # Final validation before march start - double check capacity
        if not self._validate_march_capacity_for_gathering(to_loc, final_check=True):
            logger.info(f"March capacity validation failed on final check for {to_loc}")
            return False

        try:
            if each_obj.get('code') == OBJECT_CODE_DRAGON_SOUL_CAVERN:
                self._start_march(to_loc, march_troops, MARCH_TYPE_GATHER,
                                  self.available_dragos[0]['_id'])
                return True

            self._start_march(to_loc, march_troops, MARCH_TYPE_GATHER)
            return True
        except NotOnlineException:
            logger.warning(f"Kingdom is not online for gathering, attempting complete re-initialization...")

            # Try complete bot re-initialization instead of simple reconnection
            if self._reinitialize_bot():
                # Add a delay before retrying
                time.sleep(random.uniform(3, 6))

                try:
                    # Retry the gathering march after re-initialization
                    logger.info('Retrying gathering march after bot re-initialization...')
                    self._start_march(to_loc, march_troops, MARCH_TYPE_GATHER)
                    return True
                except Exception as retry_error:
                    logger.error(f'Gathering march still failed after re-initialization: {str(retry_error)}')
                    # Force SOCF thread restart by raising TryAgain
                    raise tenacity.TryAgain()
            else:
                logger.error('Bot re-initialization failed, forcing SOCF thread restart')
                # Force SOCF thread restart
                raise tenacity.TryAgain()
        except OtherException as error_code:
            error_str = str(error_code)
            if error_str == 'full_task':
                logger.info(f"March queue became full while starting gather to {to_loc}, skipping")
                return False
            elif error_str == 'exceed_crystal_daily_quota':
                logger.error(f"Crystal daily limit reached while gathering at {to_loc}")
                self._handle_crystal_limit_error()
                return False
            else:
                logger.error(f"Error starting gather march to {to_loc}: {error_str}")
                return False

    def _on_field_objects_monster(self, each_obj):
        # Check if monster attack is enabled
        from lokbot import config
        monster_attack_enabled = config.get('main', {}).get(
            'object_scanning', {}).get('enable_monster_attack', False)
        if not monster_attack_enabled:
            monster_attack_enabled = config.get('toggles', {}).get('features', {}).get('enable_monster_attack', False)

        if not monster_attack_enabled:
            logger.debug('Monster attack is disabled in config, skipping attack')
            return False

        # Get normal monsters config
        normal_monsters_config = config.get('main',
                                            {}).get('normal_monsters', {})
        if not normal_monsters_config.get('enabled', False):
            logger.info('Normal monsters section is disabled in config')
            return False

        monster_code = each_obj.get('code')
        monster_level = each_obj.get('level')
        monster_loc = each_obj.get('loc')

        # Check area restrictions for monster attacks
        if monster_loc and len(monster_loc) >= 2:
            x, y = monster_loc[0], monster_loc[1]
            if not self._is_coordinate_in_allowed_areas(x, y):
                logger.debug(f"Skipping monster attack - coordinates [{x}, {y}] outside allowed areas")
                return False

        # Check if monster is in configured targets
        target_monster = next(
            (target for target in normal_monsters_config.get('targets', [])
             if target.get('monster_code') == monster_code
             and monster_level in target.get('level_ranges', [])), None)

        if not target_monster:
            logger.info(
                f'Monster {monster_code} level {monster_level} not in configured targets'
            )
            return False

        # No hardcoded level restrictions - let config determine valid levels

        # Use common troops configuration instead of fixed troops
        common_troops_config = normal_monsters_config.get('common_troops', [])
        if not common_troops_config:
            logger.info(f'No common troops configuration found for normal monsters')
            return False

        # Check distance if enabled
        monster_foid = each_obj.get('_id')  # Extract field object ID from the monster object
        from_loc = self.kingdom_enter.get('kingdom').get('loc')
        distance = self._calc_distance(from_loc, monster_loc)

        # Check for march conflicts before proceeding (with location and FOID validation)
        if self._is_object_being_marched(monster_loc, monster_foid):
            logger.info(f"Skipping monster attack at {monster_loc} (FOID: {monster_foid}) - object is already being marched to")
            return False

        distance_check = config.get('main',
                                    {}).get('object_scanning',
                                            {}).get('monster_distance_check',
                                                    {})
        if distance_check.get('enabled', True):
            max_distance = distance_check.get('max_distance', 200)
            if distance > max_distance:
                logger.info(
                    f'Monster at {monster_loc} is too far ({distance} tiles), max allowed is {max_distance}'
                )
                return False

        # Check march queue capacity
        march_info = self.api.field_march_info({
            'fromId':
            self.kingdom_enter.get('kingdom').get('fieldObjectId'),
            'toLoc':
            monster_loc
        })

        # Get current number of marches and max allowed from config
        current_marches = march_info.get('numMarch', 0)
        max_allowed = config.get('main', {}).get('object_scanning',
                                                 {}).get('max_marches', 3)

        # Check if march queue has available slots
        if current_marches >= max_allowed:
            logger.info(
                f'March queue full ({current_marches}/{max_allowed}), skipping monster attack'
            )
            return False

        # Build available troops dictionary
        available_troops = {}
        for troop in march_info.get('troops', []):
            troop_code = troop.get('code')
            troop_count = troop.get('amount', 0)
            available_troops[troop_code] = troop_count

        # Prepare march troops using common troops config
        march_troops = []
        total_troops_needed = 0

        for troop_config in common_troops_config:
            troop_code = troop_config.get('code')
            configured_amount = troop_config.get('amount', 0)
            troop_name = troop_config.get('name', f'Troop {troop_code}')

            if configured_amount <= 0:
                logger.debug(f'Skipping {troop_name} - amount is 0 in common troops config')
                continue

            available = available_troops.get(troop_code, 0)
            if available < configured_amount:
                logger.info(
                    f'Not enough {troop_name}: need {configured_amount}, have {available}'
                )
                return False

            march_troops.append({
                'code': troop_code,
                'level': 0,
                'select': 0,
                'amount': configured_amount,
                'dead': 0,
                'wounded': 0,
                'hp': 0,
                'attack': 0,
                'defense': 0,
                'seq': 0
            })
            total_troops_needed += configured_amount
            logger.debug(f'Added {configured_amount} {troop_name} to march')

        if not march_troops:
            logger.info('No troops configured for this monster level')
            return False

        # Validate that we have troops to send before attempting march
        if not march_troops or sum(
                troop.get('amount', 0) for troop in march_troops) <= 0:
            logger.info(
                f'No troops available to attack monster at {monster_loc}, skipping'
            )
            return False

        # Add random delay before monster attack
        delay = random.uniform(3, 10)
        logger.info(f'Adding random delay of {delay:.2f} seconds before monster attack')
        time.sleep(delay)

        # Double check march queue before attacking
        march_info = self.api.field_march_info({
            'fromId': self.kingdom_enter.get('kingdom').get('fieldObjectId'),
            'toLoc': monster_loc
        })
        max_allowed = config.get('main', {}).get('object_scanning', {}).get('max_marches', 3)
        if march_info.get('numMarch', 0) >= max_allowed:
            logger.info(
                f"March queue full on final check ({march_info.get('numMarch')}/{max_allowed}), skipping monster attack"
            )
            return False

        logger.info(
            f'Attacking monster {monster_code} level {monster_level} at {monster_loc} using COMMON TROOPS config ({len(march_troops)} troop types, {total_troops_needed} total troops)'
        )
        try:
            # Send march start notification to Discord
            if config.get('discord', {}).get('enabled', False):
                try:
                    from lokbot.discord_webhook import DiscordWebhook
                    webhook_url = config.get('discord', {}).get('monster_webhook_url') or config.get('discord', {}).get('webhook_url')
                    if webhook_url:
                        webhook = DiscordWebhook(webhook_url)
                        started_time = arrow.now().format('YYYY-MM-DD HH:mm:ss')
                        total_troops = sum(troop.get('amount', 0) for troop in march_troops)

                        # Get monster name from code
                        monster_names = {
                            20700506: "Spartoi",
                            20200205: "Magdar",
                            20200301: "Kratt",
                            20200201: "Deathkar"
                        }
                        monster_name = monster_names.get(monster_code, f"Monster {monster_code}")

                        # Determine troop type
                        troop_type = "Unknown"
                        for troop in march_troops:
                            code = troop.get('code', 0)
                            if code >= 50100305:  # T5
                                troop_type = "T5"
                                break
                            elif code >= 50100304:  # T4
                                troop_type = "T4"
                                break
                            elif code >= 50100303:  # T3
                                troop_type = "T3"
                                break

                        from lokbot.rally_utils import get_monster_name_by_code
                        monster_display_name = get_monster_name_by_code(monster_code)

                        message = "**Monster Attack Started**\n"
                        message += f"Monster: {monster_display_name}\n"
                        message += f"Level: {monster_level}\n"
                        message += f"Location: {monster_loc}\n"
                        message += f"Troops Sent: {total_troops} {troop_type}\n"
                        message += f"Started: {started_time}"

                        webhook.send_message(message)
                except Exception as e:
                    logger.error(f"Failed to send Discord notification: {str(e)}")

            self._start_march(monster_loc, march_troops, MARCH_TYPE_MONSTER)
        except NotOnlineException:
            logger.warning(f'Kingdom is not online for monster attack, attempting complete re-initialization...')

            # Try complete bot re-initialization instead of simple reconnection
            if self._reinitialize_bot():
                # Add a delay before retrying
                time.sleep(random.uniform(3, 6))

                try:
                    # Retry the monster attack after re-initialization
                    logger.info('Retrying monster attack after bot re-initialization...')
                    self._start_march(monster_loc, march_troops, MARCH_TYPE_MONSTER)
                    return True
                except Exception as retry_error:
                    logger.error(f'Monster attack still failed after re-initialization: {str(retry_error)}')
                    # Force SOCF thread restart by raising TryAgain
                    raise tenacity.TryAgain()
            else:
                logger.error('Bot re-initialization failed, forcing SOCF thread restart')
                # Force SOCF thread restart
                raise tenacity.TryAgain()
        except OtherException as error_code:
            error_str = str(error_code)
            if error_str in ['not_enough_troop', 'no_troops', 'full_task']:
                logger.info(
                    f'Cannot attack monster at {monster_loc}, skipping (error: {error_str})'
                )
                return False
            # Handle insufficient action points by trying to use AP items
            if error_str == 'insufficient_actionpoint':
                logger.info('Insufficient action points for rally join, checking for AP items...')
                try:
                    items = self.api.item_list().get('items', [])
                    ap_items = {
                        10101052: {'amount': 2, 'value': 100},  # 100 AP
                        10101051: {'amount': 4, 'value': 50},   # 50 AP
                        10101050: {'amount': 10, 'value': 20},  # 20 AP
                        10101049: {'amount': 20, 'value': 10}   # 10 AP
                    }

                    # Check available AP items from highest to lowest
                    for item_code, config in ap_items.items():
                        available_item = next((item for item in items if item.get('code') == item_code), None)
                        if available_item:
                            use_amount = min(config['amount'], available_item.get('amount', 0))
                            if use_amount > 0:
                                logger.info(f'Using {use_amount}x AP item (code: {item_code}, value: {config["value"]} AP)')
                                self.api.item_use(item_code, use_amount)
                                # Retry the monster attack
                                self._start_march(monster_loc, march_troops, MARCH_TYPE_MONSTER)
                                return True

                    logger.info('No suitable AP items available')
                except Exception as e:
                    logger.error(f'Error using AP items: {str(e)}')

            # Log but don't re-raise other errors to keep socf thread running
            logger.error(f'Error attacking monster: {error_str}')
            return False

        # Send Discord notification if enabled
        if config.get('discord', {}).get('enabled', False):
            try:
                from lokbot.discord_webhook import DiscordWebhook
                webhook_url = config.get('discord', {}).get('webhook_url')
                if webhook_url:
                    webhook = DiscordWebhook(webhook_url)
                    total_troops = sum(
                        troop.get('amount', 0) for troop in march_troops)
                    troop_type = "T3" if any(
                        troop.get('code') == 50100303
                        for troop in march_troops) else "Unknown"
                    message = f"Monster Attack Started - Code {monster_code} Level {monster_level} - {total_troops} {troop_type} troops sent"
                    webhook.send_message(message)
                    logger.info("Sent monster attack notification to Discord")
            except Exception as e:
                logger.error(f"Failed to send Discord notification: {str(e)}")

        return True

    def join_rally(self, rally_id, march_troops=None, battle_data=None):
        """Join an existing rally following optimized sequence:
        1. Get battle info
        2. Check march queue capacity
        3. Select troops based on configuration
        4. Join rally if conditions met
        """
        from lokbot import config
        try:
            # Get battle data from battle_data parameter if provided
            if battle_data:
                battle = battle_data
                # Handle different data structures - try both paths for monster code and level
                monster_code = None
                monster_level = None
                target_monster = battle.get('targetMonster', {})
                if target_monster and 'code' in target_monster:
                    monster_code = target_monster.get('code')
                    monster_level = target_monster.get('level')
                else:
                    # Try alternative data structure
                    target_monster = battle.get('target',
                                                {}).get('monster', {})
                    if target_monster and 'code' in target_monster:
                        monster_code = target_monster.get('code')
                        monster_level = target_monster.get('level')
            else:
                logger.error(
                    f'No battle data provided for rally {rally_id}')
                return False

            if not monster_code:
                logger.info(
                    f'No monstercode found in rally info for rally ID: {rally_id}')
                return False

            # Debug log the monster code and level we found
            logger.info(
                f'Found monster code {monster_code}, level {monster_level} for rally {rally_id}'
            )

            # Add small delay to simulate human checking the monster type
            delay = random.uniform(0.5, 2)
            logger.info(
                f'Adding random delay of {delay:.2f} seconds while checking monster type'
            )
            time.sleep(delay)

            # Find matching rally config
            rally_config = next(
                (target
                 for target in config.get('rally', {}).get('join', {}).get(
                     'targets', [])
                 if target.get('monster_code') == monster_code), None)

            if not rally_config:
                logger.info(
                    f'No rallyconfiguration found for monster code {monster_code}')
                return False

            logger.info(
                f'Found matching rally config for monster code {monster_code}')

            # Add delay to simulate human selecting troops
            delay = random.uniform(1, 4)
            logger.info(
                f'Adding random delay of {delay:.2f} seconds while selecting troops'
            )
            time.sleep(delay)

            # Determine if we're using level-based troops configuration
            level_based_troops = config.get('rally', {}).get('join', {}).get(
                'level_based_troops', False)

            # Prepare march troops based on configuration
            # Only calculate march_troops if not provided as parameter
            if march_troops is None:
                march_troops = []

            if level_based_troops and monster_level is not None:
                # Convert level to integer
                monster_level = int(monster_level)
                logger.info(
                    f'Using level-based troop configuration for monster level {monster_level}'
                )

                # Find the appropriate level range configuration
                level_range_config = None
                for level_range in rally_config.get('level_ranges', []):
                    min_level = level_range.get('min_level', 0)
                    max_level = level_range.get('max_level', 0)
                    if min_level <= monster_level <= max_level:
                        level_range_config = level_range
                        logger.info(
                            f'Found matching level range: {min_level}-{max_level}')
                        break

                if level_range_config:
                    # Use the level-specific troop configuration
                    for troop in level_range_config.get('troops', []):
                        # Use fixed amounts system - randomly select one amount
                        fixed_amounts = troop.get('fixed_amounts', [])
                        if fixed_amounts:
                            random_amount = random.choice(fixed_amounts)
                            logger.info(
                                f'Selected {random_amount} troops of code {troop.get("code")} from fixed amounts: {fixed_amounts}'
                            )
                        else:
                            logger.warning(
                                f'No fixed_amounts configured for troop {troop.get("code")}, skipping'
                            )
                            continue

                        if random_amount > 0:
                            march_troops.append({
                                'code': troop.get('code'),
                                'level': 0,
                                'select': 0,
                                'amount': random_amount,
                                'dead': 0,
                                'wounded': 0,
                                'hp': 0,
                                'attack': 0,
                                'defense': 0,
                                'seq': 0
                            })
                else:
                    logger.warning(
                        f'No matching level range found for monster level {monster_level}'
                    )
                    return False
            else:
                # Use the legacy troops configuration if level-based is not enabled
                logger.info('Using legacy troop configuration')
                for troop in rally_config.get('troops', []):
                    # Only add troops that have a non-zero amount
                    if troop.get('amount', 0) > 0:
                        march_troops.append({
                            'code': troop.get('code'),
                            'level': 0,
                            'select': 0,
                            'amount': troop.get('amount', 0),
                            'dead': 0,
                            'wounded': 0,
                            'hp': 0,
                            'attack': 0,
                            'defense': 0,
                            'seq': 0
                        })

            # Check if we have any troops to send
            if not march_troops:
                logger.warning(
                    f'No troops configured with non-zero amounts for monster {monster_code}'
                )
                return False

            # 2. Check march queue capacity with comprehensive validation
            monster_loc = battle.get('target', {}).get(
                'monster', {}).get('loc') or battle.get('toLoc', [])
            march_info = self.api.field_march_info({
                'fromId':
                self.kingdom_enter.get('kingdom').get('fieldObjectId'),
                'toLoc':
                monster_loc
            })

            # Get current march counts from multiple sources for comprehensive validation
            current_marches = march_info.get('numMarch', 0)
            internal_queue_size = len(self.troop_queue)
            rally_max_marches = config.get('rally', {}).get('join', {}).get('numMarch', 8)

            # Use the higher of the two march counts for conservative validation
            effective_march_count = max(current_marches, internal_queue_size)

            logger.debug(f"March queue validation - API: {current_marches}, Internal: {internal_queue_size}, Effective: {effective_march_count}, Max: {rally_max_marches}")

            # Check if march queue has available slots
            if effective_march_count >= rally_max_marches:
                logger.info(
                    f'March queue full (effective count: {effective_march_count}/{rally_max_marches}), skipping rally join'
                )
                return False

            # Additional check using context-aware method
            if self._is_march_limit_exceeded('rally_join'):
                logger.info('March limit exceeded from context check, skipping rally join')
                return False

            # 3. Get available troops from march info
            available_troops = {}
            for troop in march_info.get('troops', []):
                troop_code = troop.get('code')
                troop_count = troop.get('amount', 0)
                available_troops[troop_code] = troop_count

            # Also check saveTroops
            for troop_list in march_info.get('saveTroops', []):
                for troop in troop_list:
                    troop_code = troop.get('code')
                    troop_count = troop.get('amount', 0)
                    available_troops[troop_code] = available_troops.get(
                        troop_code, 0) + troop_count

            # Check if we have enough of each troop type
            troops_unavailable = False
            for troop in march_troops:
                troop_code = troop.get('code')
                troop_amount = troop.get('amount')

                available = available_troops.get(troop_code, 0)

                if available < troop_amount:
                    logger.warning(
                        f'Not enough troops of type {troop_code}: need {troop_amount}, have {available}'
                    )
                    troops_unavailable = True
                    # Adjust to use what we have
                    troop['amount'] = available

                # If troops are unavailable, skip this rally
                if troops_unavailable:
                    logger.info(
                        "Required troops unavailable, skipping rally join")
                    return False

            # Check if we have any troops to send
            if not march_troops:
                logger.warning(
                    f'No troops configured for rally for monster {monster_code}'
                )
                return False

            logger.info(f'Prepared march troops: {march_troops}')

            # Add random delay to simulate human checking other conditions
            delay = random.uniform(1, 3)
            logger.info(
                f'Adding random delay of {delay:.2f} seconds while checking conditions'
            )
            time.sleep(delay)

            # Final comprehensive march queue validation before attempting to join
            monster_loc = battle.get('target', {}).get(
                'monster', {}).get('loc') or battle.get('toLoc', [])

            # Get fresh march info for final validation
            try:
                final_march_info = self.api.field_march_info({
                    'fromId':
                    self.kingdom_enter.get('kingdom').get('fieldObjectId'),
                    'toLoc':
                    monster_loc
                })
            except Exception as e:
                logger.error(f'Failed to get final march info: {e}')
                return False

            # Final validation with all checks
            final_current_marches = final_march_info.get('numMarch', 0)
            final_internal_queue = len(self.troop_queue)
            rally_join_max_marches = config.get('rally', {}).get('join', {}).get('numMarch', 8)

            # Use conservative approach - highest count wins
            final_effective_count = max(final_current_marches, final_internal_queue)

            logger.info(f"Final march queue validation - API: {final_current_marches}, Internal: {final_internal_queue}, Effective: {final_effective_count}, Max: {rally_join_max_marches}")

            if final_effective_count >= rally_join_max_marches:
                logger.info(
                    f'March queue full on final check (effective: {final_effective_count}/{rally_join_max_marches}), skipping rally join'
                )
                return False

            # Add final delay before actually joining the rally
            delay = random.uniform(2, 6)
            logger.info(
                f'Adding final random delay of {delay:.2f} seconds before joining rally'
            )
            time.sleep(delay)

            # Join the rally with debug logging
            logger.info(
                f"Joining rally {rally_id} with troops {march_troops}")
            try:
                res = self.api.field_rally_join(rally_id, march_troops)
                logger.info(f'Joined rally {rally_id}: {res}')
            except (OtherException, NotOnlineException) as error_code:
                error_str = str(error_code)
                if error_str == 'not_online':
                    logger.warning('Kingdom is not online for rally join, attempting complete re-initialization...')

                    # Try complete bot re-initialization instead of simple reconnection
                    if self._reinitialize_bot():
                        # Add a delay before retrying
                        time.sleep(random.uniform(3, 6))

                        try:
                            # Retry the rally join after re-initialization
                            logger.info('Retrying rally join after bot re-initialization...')
                            res = self.api.field_rally_join(rally_id, march_troops)
                            logger.info(f'Successfully joined rally {rally_id} after re-initialization: {res}')
                        except Exception as retry_error:
                            logger.error(f'Rally join still failed after re-initialization: {str(retry_error)}')
                            return False
                    else:
                        logger.error('Bot re-initialization failed, cannot join rally')
                        return False
                elif error_str == 'insufficient_actionpoint':
                    logger.info('Insufficient action points for rally join, checking for AP items...')
                    try:
                        items = self.api.item_list().get('items', [])
                        ap_items = {
                            10101052: {'amount': 2, 'value': 100},  # 100 AP
                            10101051: {'amount': 4, 'value': 50},   # 50 AP
                            10101050: {'amount': 10, 'value': 20},  # 20 AP
                            10101049: {'amount': 20, 'value': 10}   # 10 AP
                        }

                        # Check available AP items from highest to lowest
                        for item_code, config in ap_items.items():
                            available_item = next((item for item in items if item.get('code') == item_code), None)
                            if available_item:
                                use_amount = min(config['amount'], available_item.get('amount', 0))
                                if use_amount > 0:
                                    logger.info(f'Using {use_amount}x AP item (code: {item_code}, value: {config["value"]} AP)')
                                    self.api.item_use(item_code, use_amount)
                                    # Retry the rally join
                                    res = self.api.field_rally_join(rally_id, march_troops)
                                    logger.info(f'Successfully joined rally after using AP items: {res}')
                                    return True

                        logger.info('No suitable AP items available')
                        return False
                    except Exception as e:
                        logger.error(f'Error using AP items: {str(e)}')
                        return False
                else:
                    logger.error(f'Failed to join rally: {error_str}')
                    return False

            # Add delay before sending notification
            delay = random.uniform(1, 3)
            logger.info(
                f'Adding random delay of {delay:.2f} seconds before sending notification'
            )
            time.sleep(delay)

            # Send web app notification
            try:
                import requests
                import os

                # Get user ID and instance info from environment
                user_id = os.getenv('LOKBOT_USER_ID', config.get('discord', {}).get('user_id', 'web_user'))
                instance_id = os.getenv('LOKBOT_INSTANCE_ID', f"{user_id}_{int(time.time() * 1000)}")
                account_name = os.getenv('LOKBOT_ACCOUNT_NAME', 'Bot Instance')

                # Get monster name from code mapping
                from lokbot.rally_utils import get_monster_name_by_code
                monster_display_name = get_monster_name_by_code(monster_code)

                # Calculate total troops sent
                total_troops = sum(troop.get('amount', 0) for troop in march_troops)

                # Determine troop type (highest tier sent)
                troop_type = "Troops"
                if any(troop.get('code', 0) >= 50100306 for troop in march_troops):
                    troop_type = "T6"
                elif any(troop.get('code', 0) >= 50100305 for troop in march_troops):
                    troop_type = "T5"
                elif any(troop.get('code', 0) >= 50100304 for troop in march_troops):
                    troop_type = "T4"
                elif any(troop.get('code', 0) >= 50100303 for troop in march_troops):
                    troop_type = "T3"

                # Format the rally join message
                rally_message = f"""🔥 Rally Joined!
Monster: {monster_display_name} (Level {monster_level})
Troops Sent: {total_troops} {troop_type}
Rally ID: {rally_id}"""

                # Send to web app notification system
                response = requests.post('http://localhost:5000/api/rally_notification',
                    json={
                        'user_id': user_id,
                        'notification_type': 'rally_join',
                        'monster_code': monster_code,
                        'monster_level': monster_level,
                        'rally_id': rally_id,
                        'location': monster_loc,
                        'formatted_message': rally_message,
                        'instance_id': instance_id,
                        'account_name': account_name
                    },
                    timeout=2)
                logger.info("Rally join notification sent to web app")

            except Exception as e:
                logger.error(f"Error sending rally join notification to web app: {str(e)}")

            # Send Discord notification if enabled
            if config.get('discord', {}).get('enabled', False):
                try:
                    from lokbot.discord_webhook import DiscordWebhook

                    # Use the rally webhook if configured
                    webhook_url = config.get('discord',
                                             {}).get('webhook_url')
                    if config.get('discord', {}).get('rally_webhook_url'):
                        webhook_url = config.get('discord',
                                                 {}).get('rally_webhook_url')

                    if webhook_url:
                        webhook = DiscordWebhook(webhook_url)

                        # Get monster name from code
                        monster_names = {
                            20700506: "Spartoi",
                            20200205: "Magdar",
                            20200301: "Kratt",
                            20200201: "Deathkar"
                        }
                        # Pass the code directly to let discord_webhook handle the mapping
                        monster_name = str(monster_code)

                        # Calculate total troops sent
                        total_troops = sum(
                            troop.get('amount', 0) for troop in march_troops)

                        # Determine troop type (highest tier sent)
                        troop_type = "Troops"
                        if any(
                                troop.get('code', 0) >= 50100105
                                for troop in march_troops):
                            troop_type = "T5"
                        elif any(
                                troop.get('code', 0) >= 50100104
                                for troop in march_troops):
                            troop_type = "T4"

                        # Send formatted notification with user ID
                        user_id = config.get('discord', {}).get('user_id', '')
                        result = webhook.send_rally_join(
                            monster_name, monster_level, total_troops,
                            troop_type, user_id)

                        if result:
                            logger.info(
                                "Discord notification sent for rally join")
                        else:
                            logger.warning(
                                "Failed to send formatted Discord notification for rally join, trying simple message"
                            )
                            # Try with a simpler message if the formatted one failed
                            simple_message = f"Rally Joined - {monster_name} - Level {monster_level}"
                            webhook.send_message(simple_message)
                    else:
                        logger.error(
                            "Discord is enabled but no webhook URL is configured!"
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to send Discord notification: {str(e)}")
                    # Don't let notification failures block the process
                    pass

            return True

        except Exception as e:
            logger.error(f'Failed to join rally: {str(e)}')
            return False

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(4),
        wait=tenacity.wait_random_exponential(multiplier=1, max=60),
        retry=tenacity.retry_if_not_exception_type(FatalApiException),
        reraise=True)
    def sock_thread(self):
        """
        websocket connection of the kingdom
        :return:
        """
        url = self.kingdom_enter.get('networks').get('kingdoms')[0]

        sio = socketio.Client(reconnection=False,
                              logger=False,
                              engineio_logger=False)

        @sio.on('/building/update')
        def on_building_update(data):
            logger.debug(data)
            self._update_kingdom_enter_building(data)

        @sio.on('/resource/upgrade')
        def on_resource_update(data):
            logger.debug(data)
            self.resources[data.get('resourceIdx')] = data.get('value')

        @sio.on('/buff/list')
        def on_buff_list(data):
            try:
                logger.info("=== RAW BUFF DATA FROM SOCC_THREAD ===")
                logger.info(f"Raw buff data type: {type(data)}")
                logger.info(f"Raw buff data: {data}")

                if isinstance(data, list):
                    logger.info(f"Raw buff data is a list with {len(data)} items")
                    for i, item in enumerate(data):
                        logger.info(f"Raw buff item {i}: {item}")
                        logger.info(f"Raw buff item {i} type: {type(item)}")
                        if isinstance(item, dict):
                            logger.info(f"Raw buff item {i} keys: {list(item.keys())}")
                            for key, value in item.items():
                                logger.info(f"  {key}: {value} (type: {type(value)})")
                elif isinstance(data, dict):
                    logger.info(f"Raw buff data is a dict with keys: {list(data.keys())}")
                    for key, value in data.items():
                        logger.info(f"  {key}: {value} (type: {type(value)})")
                else:
                    logger.info(f"Raw buff data is of unexpected type: {type(data)}")

                logger.info("=== END RAW BUFF DATA ===")

                logger.debug(f'on_buff_list: received buff data: {data}')

                # Store active buffs for buff management system - this is the primary source
                self.active_buffs = data if data else []

                # Log currently active buffs to console with enhanced parsing
                if data:
                    logger.info("=== ACTIVE BUFFS (from socc_thread /buff/list) ===")
                    for i, buff in enumerate(data):
                        # Handle both itemCode and code structures
                        item_code = buff.get('param', {}).get('itemCode')
                        param_code = buff.get('param', {}).get('code')
                        buff_id = buff.get('_id', 'Unknown')
                        expired_date = buff.get('expiredDate', 'Unknown')
                        buff_type_num = buff.get('buffType', 'Unknown')
                        ability = buff.get('ability', [])

                        # Calculate remaining time from expiredDate if available
                        remaining_time = "Unknown"
                        if expired_date != 'Unknown':
                            try:
                                import arrow
                                expired_arrow = arrow.get(expired_date)
                                current_time = arrow.utcnow()
                                if expired_arrow > current_time:
                                    diff = expired_arrow - current_time
                                    total_seconds = int(diff.total_seconds())
                                    hours = total_seconds // 3600
                                    minutes = (total_seconds % 3600) // 60
                                    remaining_time = f"{hours}h {minutes}m"
                                else:
                                    remaining_time = "Expired"
                            except Exception as time_error:
                                logger.debug(f"Error calculating remaining time: {time_error}")
                                remaining_time = "Parse Error"

                        # Determine buff type name
                        buff_type = "Unknown"
                        display_code = item_code or param_code or "Unknown"

                        if item_code:
                            # Regular item-based buffs
                            for buff_name, codes in USABLE_BOOST_CODE_MAP.items():
                                if item_code in codes:
                                    buff_type = buff_name.replace('_', ' ').title()
                                    break
                        elif param_code:
                            # Special buffs with param.code (like skill buffs)
                            buff_type = f"Special Buff (Code: {param_code})"

                        logger.info(f"Buff #{i+1}: {buff_type}")
                        logger.info(f"  ID: {buff_id}")
                        logger.info(f"  Display Code: {display_code}")
                        logger.info(f"  Buff Type Number: {buff_type_num}")
                        logger.info(f"  Expired Date: {expired_date}")
                        logger.info(f"  Time Remaining: {remaining_time}")
                        logger.info(f"  Ability: {ability}")
                        if item_code:
                            logger.info(f"  Item Code: {item_code}")
                        if param_code:
                            logger.info(f"  Param Code: {param_code}")
                        logger.info("  ---")

                    logger.info("==================")
                else:
                    logger.info("No active buffs currently (from socc_thread /buff/list)")

                # Update Golden Hammer status for building queue (check both itemCode and code)
                golden_hammer_active = False
                if data:
                    for item in data:
                        param = item.get('param', {})
                        if (param.get('itemCode') == ITEM_CODE_GOLDEN_HAMMER or 
                            param.get('code') == ITEM_CODE_GOLDEN_HAMMER):
                            golden_hammer_active = True
                            break

                self.has_additional_building_queue = golden_hammer_active

                # Notify buff management system of real-time update
                logger.info(f"socc_thread: Buff data updated for buff management system - {len(self.active_buffs)} active buffs")

            except Exception as e:
                logger.error(f"Error handling /buff/list data from socc_thread: {str(e)}")


        @sio.on('/alliance/rally/new')
        def on_alliance_rally_new(data):
            logger.debug(data)
            code = data.get('code')
            rally_mo_id = data.get('_id')
            level = data.get('level', 'Unknown')
            location = data.get('loc', [])

            # Just log the rally notification, but don't try to join
            # Joining will be handled by the _check_rallies_thread instead
            logger.info(
                f'Received new rally notification for monster code: {code}, ID: {rally_mo_id}'
            )
            logger.info(
                'Rally joining will be handled by the periodic check thread')

            # Send web app notification for rally alert
            try:
                import requests
                import os
                import time

                # Get user ID from environment or config
                user_id = os.getenv('LOKBOT_USER_ID', config.get('discord', {}).get('user_id', 'web_user'))

                # Generate instance_id and account_name based on current process
                timestamp = int(time.time() * 1000)
                instance_id = os.getenv('LOKBOT_INSTANCE_ID', f"{user_id}_{timestamp}")
                account_name = os.getenv('LOKBOT_ACCOUNT_NAME', 'Bot Instance')

                # Get monster name from code mapping
                from lokbot.rally_utils import get_monster_name_by_code
                monster_display_name = get_monster_name_by_code(code)

                # Format the rally alert message
                rally_alert_message = f"""🚨 New Rally Available!
Monster: {monster_display_name} (Level {level})
Rally ID: {rally_mo_id}
Location: {location}
Status: Available to join"""

                # Send to web app notification system
                response = requests.post('http://localhost:5000/api/rally_notification',
                    json={
                        'user_id': user_id,
                        'notification_type': 'rally_alert',
                        'monster_code': code,
                        'monster_level': level,
                        'rally_id': rally_mo_id,
                        'location': location,
                        'formatted_message': rally_alert_message,
                        'instance_id': instance_id,
                        'account_name': account_name
                    },
                    timeout=2)
                logger.info("Rally alert notification sent to web app")

            except Exception as e:
                logger.error(f"Error sending rally alert notification to web app: {str(e)}")

        @sio.on('/task/update')
        def on_task_update(data):
            logger.debug(data)
            if data.get('status') == STATUS_FINISHED:
                if data.get('code') in (TASK_CODE_SILVER_HAMMER,
                                        TASK_CODE_GOLD_HAMMER):
                    self.building_queue_available.set()

            if data.get('status') == STATUS_CLAIMED:
                if data.get('code') == TASK_CODE_ACADEMY:
                    self.research_queue_available.set()
                if data.get('code') == TASK_CODE_CAMP:
                    self.train_queue_available.set()

        sio.connect(f'{url}?token={self.token}',
                    transports=["websocket"],
                    headers=ws_headers)
        sio.emit('/kingdom/enter', {"token": self.token})

        sio.wait()
        logger.warning('sock_thread disconnected, reconnecting')
        raise tenacity.TryAgain()

    def socf_thread(self, radius, targets, share_to=None):
        """Main socf_thread method that delegates to the recovery wrapper"""
        return self.socf_thread_with_recovery(radius, targets, share_to)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(4),
        wait=tenacity.wait_random_exponential(multiplier=1, max=60),
        retry=tenacity.retry_if_not_exception_type(FatalApiException),
        reraise=True)
    def socf_thread_with_recovery(self, radius, targets, share_to=None):
        """SOCF thread wrapper with bot re-initialization on failure"""
        try:
            # Try to run the SOCF thread
            return self._socf_thread_internal(radius, targets, share_to)
        except Exception as e:
            logger.error(f"SOCF thread failed completely: {str(e)}")
            logger.info("Attempting bot re-initialization...")

            if self._reinitialize_bot():
                logger.info("Bot re-initialization successful, retrying SOCF thread...")
                time.sleep(5)  # Brief pause before retry
                # Retry the SOCF thread with re-initialized bot
                return self._socf_thread_internal(radius, targets, share_to)
            else:
                logger.error("Bot re-initialization failed, SOCF thread stopped")
                raise

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(8),  # Increased from 4 to 8 attempts
        wait=tenacity.wait_exponential(multiplier=2, min=4,
                                       max=120),  # More aggressive backoff
        retry=tenacity.retry_if_not_exception_type(FatalApiException),
        before_sleep=lambda retry_state: logger.warning(
            f"SOCF thread failed, attempt {retry_state.attempt_number}. Retrying in {retry_state.next_action.sleep} seconds..."
        ),
        after=lambda retry_state: logger.
        info("SOCF thread recovered successfully" if retry_state.outcome.
             exception() is None else "SOCF thread failed all retries"))
    def _validate_march_data_structure(self, data):
        """Validate that the data structure contains usable march information"""
        try:
            if not data:
                return False

            if isinstance(data, dict):
                # Check for any recognizable march data fields
                march_fields = ['objects', 'marches', 'data', 'items', 'marchObjects', 'activeMarches']
                has_march_field = any(field in data for field in march_fields)

                # Also check for nested march-like structures
                has_nested_march_data = False
                for key, value in data.items():
                    if isinstance(value, list) and value:
                        # Check if list contains march-like objects
                        if isinstance(value[0], dict):
                            location_fields = ['loc', 'toLoc', 'destination', 'location']
                            if any(loc_field in value[0] for loc_field in location_fields):
                                has_nested_march_data = True
                                break

                return has_march_field or has_nested_march_data

            elif isinstance(data, list):
                # Check if it's a list of march objects
                if data and isinstance(data[0], dict):
                    location_fields = ['loc', 'toLoc', 'destination', 'location']
                    return any(loc_field in data[0] for loc_field in location_fields)

            return False

        except Exception as e:
            logger.debug(f"Error validating march data structure: {e}")
            return False

    def _count_march_objects_in_data(self, data):
        """Count the number of march objects in the data for logging"""
        try:
            march_objects = self._extract_march_objects_safely(data)
            return len(march_objects) if march_objects else 0
        except Exception:
            return "unknown"

    def _log_march_data_structure(self, data, current_time):
        """Detailed logging of march data structure for debugging"""
        try:
            if isinstance(data, dict):
                logger.debug(f'[{current_time}] MARCH OBJECTS - Data keys: {list(data.keys())}')
                for key, value in data.items():
                    if isinstance(value, list):
                        logger.debug(f'[{current_time}] MARCH OBJECTS - {key}: list with {len(value)} items')
                        if value and isinstance(value[0], dict):
                            sample_keys = list(value[0].keys())[:5]  # First 5 keys only
                            logger.debug(f'[{current_time}] MARCH OBJECTS - {key} item sample keys: {sample_keys}')
                    elif isinstance(value, dict):
                        logger.debug(f'[{current_time}] MARCH OBJECTS - {key}: dict with keys {list(value.keys())[:5]}')
                    else:
                        logger.debug(f'[{current_time}] MARCH OBJECTS - {key}: {type(value).__name__}')
            elif isinstance(data, list):
                logger.debug(f'[{current_time}] MARCH OBJECTS - Direct list with {len(data)} items')
                if data and isinstance(data[0], dict):
                    sample_keys = list(data[0].keys())[:5]
                    logger.debug(f'[{current_time}] MARCH OBJECTS - List item sample keys: {sample_keys}')
        except Exception as e:
            logger.debug(f'Error logging march data structure: {e}')

    def _socf_thread_internal(self, radius, targets, share_to=None):
        """
        websocket connection of the field
        Only scans for objects and logs them without starting marches
        :return:
        """
        # Set a flag to track thread status
        self.socf_thread_active = True

        # Watchdog timer thread
        def watchdog():
            while self.socf_thread_active:
                if not hasattr(self, 'last_socf_activity'):
                    self.last_socf_activity = time.time()

                if time.time(
                ) - self.last_socf_activity > 300:  # 5 minutes timeout
                    logger.error(
                        "SOCF thread appears stuck - forcing reconnection")
                    try:
                        self.socf_thread_active = False
                        raise tenacity.TryAgain()
                    except:
                        pass
                time.sleep(60)

        # Start watchdog
        watchdog_thread = threading.Thread(target=watchdog, daemon=True)
        watchdog_thread.start()

        try:
            logger.info("Starting SOCF thread")
            self.last_socf_activity = time.time()

            # Check for crystal limit before starting
            if getattr(self, 'crystal_limit_reached', False):
                logger.critical("SOCF thread stopped - Crystal limit reached")
                return

            # Check if object scanning is enabled
            object_scanning_enabled = config.get('main', {}).get(
                'object_scanning', {}).get('enabled', True)

            # Also check if the socf_thread job itself is enabled in config
            socf_enabled = False
            jobs = config.get('main', {}).get('jobs', [])
            for job in jobs:
                if job.get('name') == 'socf_thread' and job.get(
                        'enabled', False):
                    socf_enabled = True
                    break

            if not object_scanning_enabled:
                logger.info(
                    'Object scanning is disabled in config. Skipping object scanning.'
                )
                return

            if not socf_enabled:
                logger.info(
                    'socf_thread job is disabled in config. Skipping object scanning.'
                )
                return

            # Check if rally start is enabled for logging purposes
            rally_start_enabled = config.get('rally',
                                             {}).get('start',
                                                     {}).get('enabled', False)
            rally_join_enabled = config.get('rally',
                                            {}).get('join',
                                                    {}).get('enabled', False)

            # Informational log message only
            if not rally_start_enabled and rally_join_enabled:
                logger.info(
                    'Rally Start is disabled but Rally Join is enabled. Will scan for objects but not start rallies.'
                )

            while self.api.last_requested_at + 16 > time.time():
                # if last request is less than 16 seconds ago, wait
                # when we are in the field, we should not be doing anything else
                logger.info(
                    f'last requested at {arrow.get(self.api.last_requested_at).humanize()}, waiting...'
                )
                time.sleep(4)

            # File logging disabled - using web app and Discord notifications only
            logger.info("Starting object scanning session - notifications via web app and Discord only")

            self.socf_entered = False
            self.socf_world_id = self.kingdom_enter.get('kingdom').get(
                'worldId')
            url = self.kingdom_enter.get('networks').get('fields')[0]
            from_loc = self.kingdom_enter.get('kingdom').get('loc')

            if not self.zones:
                logger.info('getting nearest zone')
                self.zones = self._get_nearest_zone_ng(from_loc[1],
                                                       from_loc[2], radius)

            sio = socketio.Client(reconnection=False,
                                  logger=False,
                                  engineio_logger=False)

            @sio.on('/march/objects')
            def on_march_objects(data):
                """
                Robust march objects data handler with comprehensive validation and error recovery
                """
                current_time = arrow.now().format('HH:mm:ss.SSS')

                # Input validation
                if not data:
                    logger.debug(f'[{current_time}] MARCH OBJECTS - Empty data received')
                    return

                try:
                    with self.march_objects_lock:
                        logger.info(f'[{current_time}] MARCH OBJECTS - Processing incoming data')

                        decoded_data = None
                        data_source = "unknown"

                        # Multi-path data processing with fallbacks
                        try:
                            # Path 1: Packed and encoded data
                            packs = data.get('packs')
                            if packs and isinstance(packs, (list, bytes, bytearray)):
                                logger.debug(f'[{current_time}] MARCH OBJECTS - Processing packed data (length: {len(packs)})')

                                # Handle different pack formats
                                if isinstance(packs, list):
                                    packs = bytearray(packs)
                                elif isinstance(packs, bytes):
                                    packs = bytearray(packs)

                                # Decompress and decode
                                gzip_decompress = gzip.decompress(packs)
                                decoded_data = self.api.b64xor_dec(gzip_decompress)
                                data_source = "packed_encoded"

                        except Exception as pack_error:
                            logger.debug(f'[{current_time}] MARCH OBJECTS - Pack processing failed: {pack_error}')
                            decoded_data = None

                        # Path 2: Direct data (fallback)
                        if decoded_data is None:
                            if isinstance(data, dict) and len(data) > 0:
                                decoded_data = data
                                data_source = "direct"
                                logger.debug(f'[{current_time}] MARCH OBJECTS - Using direct data')
                            else:
                                logger.warning(f'[{current_time}] MARCH OBJECTS - No valid data found in any format')
                                return

                        # Validate decoded data structure
                        if not self._validate_march_data_structure(decoded_data):
                            logger.warning(f'[{current_time}] MARCH OBJECTS - Invalid data structure, skipping update')
                            return

                        # Thread-safe data update with backup
                        previous_data = self.march_objects_data.copy() if self.march_objects_data else {}
                        previous_update_time = self.march_objects_last_update

                        try:
                            # High-frequency update handling
                            current_update_time = time.time()
                            self.march_objects_data = decoded_data
                            self.march_objects_last_update = current_update_time
                            self.march_data_update_count += 1
                            self.march_data_validation_errors = max(0, self.march_data_validation_errors - 1)  # Reduce error count on success

                            # Zone-specific caching for SOCF operations
                            if self.current_scanning_zone:
                                zone_key = f"{self.current_scanning_zone[0]},{self.current_scanning_zone[1]}"
                                self.march_data_by_zone[zone_key] = {
                                    'data': decoded_data,
                                    'timestamp': current_update_time,
                                    'update_count': self.march_data_update_count
                                }
                                # Keep only recent zone data (last 10 zones)
                                if len(self.march_data_by_zone) > 10:
                                    oldest_key = min(self.march_data_by_zone.keys(),
                                                   key=lambda k: self.march_data_by_zone[k]['timestamp'])
                                    del self.march_data_by_zone[oldest_key]

                            # Log successful update with enhanced info
                            march_count = self._count_march_objects_in_data(decoded_data)
                            update_frequency = "frequent" if self.march_data_update_count % 10 == 0 else "normal"
                            logger.info(f'[{current_time}] MARCH OBJECTS - Updated #{self.march_data_update_count} (source: {data_source}, marches: {march_count}, freq: {update_frequency})')

                            # Zone-specific logging for SOCF operations
                            if self.current_scanning_zone:
                                logger.debug(f'[{current_time}] MARCH OBJECTS - Zone [{self.current_scanning_zone[0]},{self.current_scanning_zone[1]}] data cached')

                            # Detailed logging for debugging (only if debug enabled and not too frequent)
                            if self.march_data_update_count % 5 == 0:
                                self._log_march_data_structure(decoded_data, current_time)

                        except Exception as update_error:
                            # Rollback on update failure
                            logger.error(f'[{current_time}] MARCH OBJECTS - Update failed, rolling back: {update_error}')
                            self.march_objects_data = previous_data
                            self.march_objects_last_update = previous_update_time
                            raise

                except Exception as e:
                    logger.error(f'[{current_time}] MARCH OBJECTS - Critical error processing data: {e}')
                    import traceback
                    logger.debug(f'[{current_time}] MARCH OBJECTS - Error traceback: {traceback.format_exc()}')

                    # Error recovery - clear data if too many consecutive errors
                    self.march_data_validation_errors += 1
                    if self.march_data_validation_errors > 5:
                        logger.error(f'[{current_time}] MARCH OBJECTS - Too many errors ({self.march_data_validation_errors}), clearing cache')
                        with self.march_objects_lock:
                            self.march_objects_data = {}
                            self.march_objects_last_update = 0
                            self.march_data_validation_errors = 0


            @sio.on('/field/objects/v4')
            def on_field_objects(data):
                from lokbot import config

                # Check crystal limit flag before processing
                if getattr(self, 'crystal_limit_reached', False):
                    logger.critical("Stopping SOCF processing - Crystal limit reached")
                    sio.disconnect()
                    return

                packs = data.get('packs')
                gzip_decompress = gzip.decompress(bytearray(packs))
                data_decoded = self.api.b64xor_dec(gzip_decompress)
                objects = data_decoded.get('objects')
                # Only include enabled targets
                target_code_set = set([
                    target['code'] for target in targets
                    if target.get('enabled', True)
                ])

                logger.debug(f'Processing {len(objects)} objects')
                for each_obj in objects:
                    code = each_obj.get('code')
                    level = each_obj.get('level')
                    loc = each_obj.get('loc')
                    state = each_obj.get('state', 1)

                    # Skip if object is not in valid state
                    if state != 1:
                        continue

                    # Check if object is in our targets
                    if code not in target_code_set:
                        continue

                    # Get all level lists for this monster code
                    level_lists = [
                        target['level'] for target in targets
                        if target['code'] == code
                    ]

                    # Flatten the level lists into a single list of allowed levels
                    allowed_levels = [
                        level for sublist in level_lists for level in sublist
                    ]

                    # If allowed_levels is empty or the monster's level is in allowed_levels, process it
                    if not allowed_levels or level in allowed_levels:
                        # Determine if this is a resource or monster for correct logging
                        if code in OBJECT_MINE_CODE_LIST:
                            logger.info(
                                f'Found target resource: code={code} level={level} loc={loc}'
                            )
                        elif code in OBJECT_MONSTER_CODE_LIST:
                            logger.info(
                                f'Found target monster: code={code} level={level} loc={loc}'
                            )
                        else:
                            logger.info(
                                f'Found target object: code={code} level={level} loc={loc}'
                            )

                        # Share monster location if configured
                        if share_to and 'chat_channels' in share_to:
                            for chat_channel in share_to['chat_channels']:
                                if chat_channel:
                                    self.api.chat_new(
                                        chat_channel=chat_channel,
                                        chat_type=CHAT_TYPE_LOC,
                                        text='',
                                        param={'loc': loc})

                        # Start rally for monsters if rally start is enabled
                        if code in [
                                monster.get('monster_code')
                                for monster in config.get('rally', {}).get(
                                    'start', {}).get('targets', [])
                        ] and rally_start_enabled:
                            try:
                                # Get march info first to check available troops
                                march_info = self.api.field_march_info({
                                    'fromId':
                                    self.kingdom_enter.get('kingdom').get(
                                        'fieldObjectId'),
                                    'toLoc':
                                    loc
                                })

                                # Check if any configured troops are available
                                monster_config = next(
                                    (m for m in config.get('rally', {}).get(
                                        'start', {}).get('targets', [])
                                     if m.get('monster_code') == code), None)
                                if not monster_config:
                                    logger.info(
                                        f'No configuration found for monster {code}, skipping rally start'
                                    )
                                    continue

                                # Check troop availability for the configured level ranges
                                level_range = next(
                                    (lr for lr in monster_config.get(
                                        'level_ranges', [])
                                     if lr.get('min_level', 0) <= level <=
                                     lr.get('max_level', float('inf'))), None)
                                if not level_range:
                                    logger.info(
                                        f'No matching level range configuration found for monster {code} level {level}, skipping rally start'
                                    )
                                    continue

                                # Check if any configured troops are available
                                has_available_troops = False
                                for troop in level_range.get('troops', []):
                                    troop_code = troop.get('code')
                                    min_amount = troop.get('min_amount', 0)

                                    # Check both regular troops and saveTroops
                                    available = 0
                                    for t in march_info.get('troops', []):
                                        if t.get('code') == troop_code:
                                            available += t.get('amount', 0)

                                    # Check saveTroops
                                    for troop_list in march_info.get('saveTroops', []):
                                        for t in troop_list:
                                            if t.get('code') == troop_code:
                                                available += t.get('amount', 0)

                                    if available >= min_amount and min_amount > 0:
                                        has_available_troops = True
                                        break

                                if not has_available_troops:
                                    logger.info(
                                        'No troops configured for rally, skipping'
                                    )
                                    continue

                                # Check if there are any existing rallies to this target
                                try:
                                    battle_response = self.api.alliance_battle_list_v2(
                                    )
                                    if not isinstance(battle_response, dict):
                                        logger.error(
                                            f'Invalid response from alliance_battle_list_v2: {battle_response}'
                                        )
                                        continue
                                    existing_rallies = battle_response.get(
                                        'battles', [])
                                except Exception as e:
                                    logger.error(
                                        f'Failed to fetch battle list: {e}')
                                    continue
                                target_loc_str = f"{loc[0]},{loc[1]},{loc[2]}"
                                has_existing_rally = any(
                                    battle.get('toLoc', '') == target_loc_str
                                    for battle in existing_rallies)

                                if has_existing_rally:
                                    logger.info(
                                        f'Target at {loc} already has an active rally, skipping'
                                    )
                                    continue

                                # Check both march and rally limits
                                if self._is_march_limit_exceeded():
                                    logger.info(
                                        'March limit exceeded, skipping rally start'
                                    )
                                    continue

                                # Add initial delay before starting rally sequence
                                initial_delay = random.uniform(3, 8)
                                logger.info(
                                    f'Adding initial delay of {initial_delay:.2f} seconds before checking rally conditions'
                                )
                                time.sleep(initial_delay)

                                # Get march info first to check available troops
                                try:
                                    march_info = self.api.field_march_info({
                                        'fromId':
                                        self.kingdom_enter.get('kingdom').get(
                                            'fieldObjectId'),
                                        'toLoc':
                                        loc
                                    })

                                    # Build available troops dictionary
                                    available_troops = {}
                                    for troop in march_info.get('troops', []):
                                        troop_code = troop.get('code')
                                        troop_count = troop.get('amount', 0)
                                        available_troops[troop_code] = troop_count

                                    # Initialize march_troops before using it
                                    march_troops = []

                                    # Find the monster configuration in rally start config
                                    monster_config = next(
                                    (target
                                     for target in config.get('rally', {}).get(
                                             'start', {}).get('targets', [])
                                         if target.get('monster_code') == code),
                                        None)

                                    if not monster_config:
                                        logger.info(
                                            f'No rally start configuration found for monster code {code}'
                                        )
                                        continue

                                    # Prepare march troops based on level configuration
                                    if monster_config.get('level_ranges'):
                                        # Find matching level range
                                        level_range = next(
                                            (lr for lr in monster_config['level_ranges']
                                             if lr.get('min_level', 0) <= level <=
                                             lr.get('max_level', float('inf'))), None)

                                        if level_range and 'troops' in level_range:
                                            for troop in level_range['troops']:
                                                # Check if using new fixed_amounts system
                                                fixed_amounts = troop.get('fixed_amounts', [])
                                                if fixed_amounts:
                                                    # Use new fixed amounts system - randomly select one amount
                                                    random_amount = random.choice(fixed_amounts)
                                                    logger.info(
                                                        f'Selected {random_amount} troops of code {troop.get("code")} from fixed amounts: {fixed_amounts}'
                                                    )
                                                    march_troops.append({
                                                        'code':
                                                        troop.get('code'),
                                                        'level':
                                                        0,
                                                        'select':
                                                        0,
                                                        'amount':
                                                        random_amount,
                                                        'dead':
                                                        0,
                                                        'wounded':
                                                        0,
                                                        'hp':
                                                        0,
                                                        'attack':
                                                        0,
                                                        'defense':
                                                        0,
                                                        'seq':
                                                        0
                                                    })
                                                else:
                                                    # Legacy support for min/max amounts (will be deprecated)
                                                    min_amount = troop.get('min_amount', 0)
                                                    max_amount = troop.get('max_amount', min_amount)
                                                    if min_amount > 0:
                                                        logger.warning(
                                                            f'Using legacy min/max amounts for troop {troop.get("code")} - consider updating config to use "fixed_amounts"'
                                                        )
                                                        march_troops.append({
                                                            'code':
                                                            troop.get('code'),
                                                            'level':
                                                            0,
                                                            'select':
                                                            0,
                                                            'amount':
                                                            random.randint(min_amount, max_amount),
                                                            'dead':
                                                            0,
                                                            'wounded':
                                                            0,
                                                            'hp':
                                                            0,
                                                            'attack':
                                                            0,
                                                            'defense':
                                                            0,
                                                            'seq':
                                                            0
                                                        })

                                    if not march_troops:
                                        logger.info(
                                            'No troops configured for rally, skipping'
                                        )
                                        continue

                                    # Check if we have enough troops before proceeding
                                    has_any_troops = False
                                    for troop in march_troops:
                                        troop_code = troop.get('code')
                                        needed_amount = troop.get('amount', 0)

                                        # Skip if no troops needed
                                        if needed_amount <= 0:
                                            continue

                                        # Only check troops available in the main troops array
                                        available = 0
                                        for t in march_info.get('troops', []):
                                            if t.get('code') == troop_code:
                                                available += t.get('amount', 0)

                                        # Check if we have enough of this troop type
                                        if available <= 0:
                                            logger.info(
                                                f'No troops of type {troop_code} available'
                                            )
                                            troop['amount'] = 0
                                            continue

                                        if available < needed_amount:
                                            logger.info(
                                                f'Not enough troops of type {troop_code}: need {needed_amount}, have {available}, skipping rally'
                                            )
                                            # Don't adjust - skip rally if we don't have enough troops
                                            return False
                                        else:
                                            troop['amount'] = needed_amount
                                            has_any_troops = True

                                    # Only proceed if we have any troops to send
                                    if not has_any_troops:
                                        logger.info(
                                            'No troops available for rally, skipping'
                                        )
                                        continue

                                    # Make sure we filter out any troops with zero amounts
                                    march_troops = [
                                        troop for troop in march_troops
                                        if troop.get('amount', 0) > 0
                                    ]

                                    if not march_troops:
                                        logger.info(
                                            'No troops available after filtering zero-amount troops, skipping rally'
                                        )
                                        continue

                                    logger.info(
                                        f'Prepared march troops: {march_troops}')

                                    # Check if target already has a rally
                                    try:
                                        import time
                                        distance = 0  # Initialize distance
                                        march_info = self.api.field_march_info({
                                            'fromId':
                                            self.kingdom_enter.get('kingdom').get(
                                                'fieldObjectId'),
                                            'toLoc':
                                            loc
                                        })

                                        # Check if monster is already being rallied
                                        if march_info.get(
                                                'fo',
                                            {}).get('occupied') or march_info.get(
                                                'fo', {}).get('rally'):
                                            logger.info(
                                                f'Target at {loc} already has a rally, skipping'
                                            )
                                            continue

                                        # Proceed with rally only if checks pass
                                        rally_time = 10  # Default rally time
                                        rally_message = f"{monster_config.get('monster_name', 'Monster')} Rally ({distance} tiles)"  # Include distance in message

                                        # Get the level range configuration that was used for troops
                                        level_range_config = next(
                                            (lr for lr in monster_config.get(
                                                'level_ranges', [])
                                             if lr.get('min_level', 0) <= level <=
                                             lr.get('max_level', float('inf'))), None)

                                        # Update rally parameters if we have a matching level range
                                        if level_range_config:
                                            rally_time = level_range_config.get(
                                                'rally_time', 10)
                                            rally_message = level_range_config.get(
                                                'message', rally_message)

                                        # If no troops are configured or available, skip this rally
                                        if not march_troops:
                                            logger.info(
                                                'No troops configured for rally, skipping'
                                            )
                                            continue

                                        logger.info(
                                            f'Prepared march troops: {march_troops}')

                                        # Check if march queue is full
                                        if self._is_march_limit_exceeded():
                                            logger.info(
                                                'March limit exceeded, skipping rally start'
                                            )
                                            continue

                                        # Create rally data
                                        rally_data = {
                                            'fromId':
                                            self.kingdom_enter.get('kingdom').get(
                                                'fieldObjectId'),
                                            'marchType':
                                            5,  # Rally march type
                                            'toLoc':
                                            loc,
                                            'marchTroops':
                                            march_troops,
                                            'rallyTime':
                                            rally_time,  # Rally time in minutes from config
                                            'message':
                                            rally_message  # Rally message from config
                                        }

                                        try:
                                                # Final check that we have troops to send
                                                if not march_troops or sum(
                                                        troop.get('amount', 0) for
                                                        troop in march_troops) <= 0:
                                                    logger.info(
                                                        'No troops available for rally, skipping'
                                                    )
                                                    continue

                                                logger.info(
                                                    f'Attempting to start rally with {sum(troop.get("amount", 0) for troop in march_troops)} troops'
                                                )
                                                try:
                                                    res = self.api.field_rally_start(
                                                        rally_data)

                                                    if not res.get('result', False):
                                                        error_code = res.get('err',
                                                                             {}).get(
                                                                                 'code',
                                                                                 'unknown')
                                                        logger.warning(
                                                            f'Rally start failed with error: {error_code}'
                                                        )
                                                        continue

                                                    logger.info(
                                                        f'Rally API Response: {res}')
                                                    logger.info(
                                                        f'Successfully started rally against {monster_config.get("monster_name", "monster")} at {loc}'
                                                    )

                                                    # Send Discord notification if enabled
                                                    if config.get('discord', {}).get(
                                                            'enabled', False):
                                                        try:
                                                            from lokbot.discord_webhook import DiscordWebhook

                                                            # Use the rally webhook if configured
                                                            webhook_url = config.get(
                                                                'discord',
                                                                {}).get('webhook_url')
                                                            if config.get(
                                                                    'discord',
                                                                {}).get(
                                                                    'rally_webhook_url'):
                                                                webhook_url = config.get(
                                                                    'discord', {}
                                                                ).get('rally_webhook_url')

                                                            if webhook_url:
                                                                webhook = DiscordWebhook(
                                                                webhook_url)

                                                                # Determine troop type (highest tier sent)
                                                                troop_type = "Troops"
                                                                if any(
                                                                        troop.get(
                                                                            'code',
                                                                            0) >= 50100306
                                                                        for troop in
                                                                        march_troops):
                                                                    troop_type = "T6"
                                                                elif any(
                                                                        troop.get(
                                                                            'code',
                                                                            0) >= 50100305
                                                                        for troop in
                                                                        march_troops):
                                                                    troop_type = "T5"

                                                                # Send formatted notification
                                                                total_troops = sum(
                                                                troop.get('amount', 0)
                                                                for troop in
                                                                march_troops)
                                                                user_id = config.get(
                                                            'discord',
                                                                {}).get('user_id', '')
                                                                webhook.send_message(
                                                                    f"Rally Started - {monster_config.get('monster_name', 'Monster')} - Level {level} - {total_troops} {troop_type} troops sent"
                                                                )
                                                        except Exception as e:
                                                            logger.error(
                                                                f"Failed to send Discord notification: {e}"
                                                            )
                                                except OtherException as error_code:
                                                    error_msg = str(error_code)
                                                    logger.error(
                                                        f'Rally API Error: {error_msg}')
                                                    logger.error(
                                                        f'Rally Data: {rally_data}')

                                                    if error_msg in [
                                                            'full_task',
                                                            'same_target_rally'
                                                    ]:
                                                        wait_time = 60 if error_msg == 'full_task' else 120
                                                        logger.info(
                                                            f'Rally failed due to {error_msg}, waiting {wait_time} seconds before next attempt'
                                                        )
                                                        time.sleep(wait_time)
                                                        continue
                                        except Exception as e:
                                            logger.error(f'Failed to start rally: {e}')
                                    except Exception as e:
                                        logger.error(
                                            f"Failed to get march info: {str(e)}")
                                        continue
                                except Exception as e:
                                    logger.error(
                                        f"Failed to get march info: {str(e)}")
                                    continue
                            except Exception as e:
                                logger.error(f'Failed to process rally start: {e}')
                                continue
                    else:
                        logger.info(
                            f'Level {level} not in allowed levels {allowed_levels}, ignore: {each_obj}'
                        )
                        continue

                    # Determine if we should attempt to gather resources or attack monsters
                    # Check both main config and toggles config for gathering
                    enable_gathering = config.get('main', {}).get('object_scanning', {}).get('enable_gathering', False)
                    if not enable_gathering:
                        enable_gathering = config.get('toggles', {}).get('features', {}).get('enable_gathering', False)

                    # Check both main config and toggles config for monster attack
                    enable_monster_attack = config.get('main', {}).get('object_scanning', {}).get('enable_monster_attack', False)
                    if not enable_monster_attack:
                        enable_monster_attack = config.get('toggles', {}).get('features', {}).get('enable_monster_attack', False)

                    logger.debug(f"Gather enabled: {enable_gathering}, Monster attack enabled: {enable_monster_attack}")

                    # Find matching target and check if it's enabled
                    target = next(
                        (t for t in targets if t.get('code') == code), None)
                    if not target or target.get('enabled', True) is False:
                        logger.info(
                            f"Target {code} is disabled or not found, skipping"
                        )
                        continue

                    # Check object type and process accordingly
                    if code in OBJECT_MINE_CODE_LIST:
                        # Only call gather if gathering is enabled and target is in our code set
                        if enable_gathering and code in target_code_set:
                            logger.debug(f"Attempting to gather from resource code {code} at {each_obj.get('loc')}")
                            self._on_field_objects_gather(each_obj)
                        else:
                            logger.debug(f"Skipping gather - enable_gathering: {enable_gathering}, code_in_target: {code in target_code_set}")
                    elif code in OBJECT_MONSTER_CODE_LIST:
                        # Only call monster attack if monster attack is enabled and target is in our code set
                        if enable_monster_attack and code in target_code_set:
                            logger.debug(f"Attempting to attack monster code {code} at {each_obj.get('loc')}")
                            self._on_field_objects_monster(each_obj)
                        else:
                            logger.debug(f"Skipping monster attack - enable_monster_attack: {enable_monster_attack}, code_in_target: {code in target_code_set}")

                    if code in set(OBJECT_MINE_CODE_LIST).intersection(target_code_set) or \
                       code in set(OBJECT_MONSTER_CODE_LIST).intersection(target_code_set):
                        obj_type = "Resource" if code in OBJECT_MINE_CODE_LIST else "Monster"

                        # Map object codes to friendly names
                        object_names = {
                            20100101: "Farm",
                            20100102: "Forest",
                            20100103: "Quarry",
                            20100104: "Gold Mine",
                            20100105: "Crystal Mine",
                            20100106: "Dragon Soul Cavern",
                            20200103: "Golem",
                            20200201: "Deathkar",
                            20200301: "Kratt",
                            20200302: "Skeleton",
                            20700506: "Spartoi"
                        }

                        object_name = object_names.get(code, f"Unknown Object {code}")
                        status = 'Available' if not each_obj.get('occupied') else 'Occupied'

                        # Format the single notification message
                        formatted_message = f"""{object_name} Found!
Type: {obj_type} (Level {level} {object_name})
Code: {code}
Level: {level}
Location: {loc}
Status: {status}"""

                        # Single consolidated log entry
                        logger.info(formatted_message)

                        # Send to web app notification system once
                        try:
                            import requests
                            import os
                            import time
                            user_id = os.getenv('LOKBOT_USER_ID', 'web_user')

                            # Generate instance_id and account_name based on current process
                            timestamp = int(time.time() * 1000)
                            instance_id = os.getenv('LOKBOT_INSTANCE_ID', f"{user_id}_{timestamp}")
                            account_name = os.getenv('LOKBOT_ACCOUNT_NAME', 'Bot Instance')

                            response = requests.post('http://localhost:5000/api/object_notification',
                                json={
                                    'object_type': obj_type,
                                    'object_name': object_name,
                                    'code': code,
                                    'level': level,
                                    'location': loc,
                                    'status': status,
                                    'formatted_message': formatted_message,
                                    'user_id': user_id,
                                    'instance_id': instance_id,
                                    'account_name': account_name
                                },
                                timeout=2)
                        except Exception as e:
                            logger.error(f"Error sending object notification to web app: {str(e)}")

                        # File logging disabled - notifications sent to web app and Discord only

                        # Send to Discord if enabled (single Discord notification)
                        if config.get('discord', {}).get('enabled', False) and config.get('main', {}).get('object_scanning', {}).get('notify_discord', True):
                            try:
                                from lokbot.discord_webhook import DiscordWebhook
                                is_occupied = each_obj.get('occupied', False)

                                # Send to appropriate Discord webhook based on object type and level
                                if code == 20100105 and level == 1 and not is_occupied and config.get('discord', {}).get('crystal_mine_level1_webhook_url'):
                                    webhook = DiscordWebhook(config.get('discord', {}).get('crystal_mine_level1_webhook_url'))
                                    webhook.send_object_log(f"{obj_type} (Level 1 {object_name})", code, level, loc, status, "")
                                elif code == 20100105 and level >= 2 and not is_occupied and config.get('discord', {}).get('level2plus_webhook_url'):
                                    webhook = DiscordWebhook(config.get('discord', {}).get('level2plus_webhook_url'))
                                    webhook.send_object_log(f"{obj_type} (Level {level} {object_name})", code, level, loc, status, "")
                                elif code == 20100106 and level >= 2 and not is_occupied and config.get('discord', {}).get('dragon_soul_level2plus_webhook_url'):
                                    webhook = DiscordWebhook(config.get('discord', {}).get('dragon_soul_level2plus_webhook_url'))
                                    webhook.send_object_log(f"Dragon Soul Cavern (Level {level})", code, level, loc, status, "")
                                elif level >= 2 and is_occupied and config.get('discord', {}).get('occupied_resources_webhook_url'):
                                    webhook = DiscordWebhook(config.get('discord', {}).get('occupied_resources_webhook_url'))
                                    webhook.send_object_log(f"{obj_type} ({object_name}) - OCCUPIED", code, level, loc, status, "")
                                elif config.get('discord', {}).get('webhook_url'):
                                    webhook = DiscordWebhook(config.get('discord', {}).get('webhook_url'))
                                    webhook.send_object_log(f"{obj_type} ({object_name})", code, level, loc, status, "")
                            except Exception as e:
                                logger.error(f"Failed to send to Discord: {e}")

                self.field_object_processed = True

            @sio.on('/field/enter/v3')
            def on_field_enter(data):
                data_decoded = self.api.b64xor_dec(data)
                logger.debug(data_decoded)
                self.socf_world_id = data_decoded.get('loc')[
                    0]  # in case of cvc event world map

                # knock
                sio.emit('/zone/leave/list/v2', {
                    'world': self.socf_world_id,
                    'zones': '[]'
                })
                default_zones = '[0,64,1,65]'
                sio.emit(
                    '/zone/enter/list/v4',
                    self.api.b64xor_enc({
                        'world': self.socf_world_id,
                        'zones': default_zones
                    }))
                sio.emit('/zone/leave/list/v2', {
                    'world': self.socf_world_id,
                    'zones': default_zones
                })

                self.socf_entered = True

            sio.connect(f'{url}?token={self.token}',
                        transports=["websocket"],
                        headers=ws_headers)
            logger.debug(f'entering field: {self.zones}')
            sio.emit('/field/enter/v3',
                     self.api.b64xor_enc({'token': self.token}))

            while not self.socf_entered:
                time.sleep(1)

            step = 9
            grace = 7  # 9 times enter-leave action will cause ban
            index = 0
            while self.zones:
                if index >= grace:
                    logger.info('socf_thread grace exceeded, break')
                    break

                index += 1
                zone_ids = []
                for _ in range(step):
                    if not self.zones:
                        break

                    zone_ids.append(self.zones.pop(0))

                if len(zone_ids) < step:
                    logger.info('len(zone_ids) < {step}, break')
                    self.zones = []
                    break

                if not sio.connected:
                    logger.warning('socf_thread disconnected, reconnecting')
                    raise tenacity.TryAgain()

                # Set current scanning zones for march data optimization
                if zone_ids:
                    # Convert zone IDs to coordinates for march data caching
                    zone_coords_list = []
                    for zone_id in zone_ids:
                        zone_y = zone_id // 64
                        zone_x = zone_id % 64
                        zone_coords_list.append([zone_x, zone_y])

                    # Set the first zone as current scanning zone for march data context
                    self._set_current_scanning_zone(zone_coords_list[0])
                    logger.debug(f'Set scanning context for zones: {zone_coords_list}')

                message = {
                    'world': self.kingdom_enter.get('kingdom').get('worldId'),
                    'zones': json.dumps(zone_ids, separators=(',', ':'))
                }
                encoded_message = self.api.b64xor_enc(message)

                sio.emit('/zone/enter/list/v4', encoded_message)
                self.field_object_processed = False
                logger.debug(
                    f'entering zone: {zone_ids} and waiting for processing')
                while not self.field_object_processed:
                    time.sleep(1)

                # Clear scanning zone context when leaving zones
                self._set_current_scanning_zone(None)
                sio.emit('/zone/leave/list/v2', message)

            logger.info('Object scanning loop finished')
            try:
                sio.disconnect()
                sio.wait()
            except Exception as e:
                logger.error(f"Error disconnecting SOCF socket: {e}")
                raise tenacity.TryAgain()
            finally:
                # Clean up and prepare for next cycle
                self.socf_thread_active = False
                self.last_socf_activity = time.time()

                # Clear scanning zone context and log march data stats
                self._set_current_scanning_zone(None)
                march_stats = self._get_march_data_stats()
                logger.info(f"SOCF thread completed scanning cycle - March data updates: {march_stats.get('update_count', 0)}")

                if march_stats.get('zone_cache_count', 0) > 0:
                    logger.debug(f"Zone cache contains {march_stats['zone_cache_count']} cached zones")

                # Small delay before next retry to prevent rapid cycling
                time.sleep(random.uniform(2, 5))

                # Force a new cycle if conditions warrant it
                if not self.zones and self.kingdom_enter:
                    logger.info("Reinitializing zones for next scan cycle")
                    from_loc = self.kingdom_enter.get('kingdom').get('loc')
                    self.zones = self._get_nearest_zone_ng(
                        from_loc[1], from_loc[2], radius)
        except tenacity.TryAgain:
            # Reset SOCF state when forcing a restart
            logger.info("Forcing SOCF thread restart - resetting all state variables")
            self.zones = []
            self.socf_entered = False
            self.socf_world_id = None
            self.field_object_processed = False
            raise  # Trigger tenacity retry
        except Exception as e:
            logger.error(f"Fatal error in SOCF thread: {e}")
            # Reset SOCF state on any fatal error
            logger.info("Resetting SOCF state due to fatal error")
            self.zones = []
            self.socf_entered = False
            self.socf_world_id = None
            self.field_object_processed = False
            raise  # Let tenacity retry handle the error

    def socc_thread(self):
        """
        websocket connection of the chat
        :return:
        """
        url = self.kingdom_enter.get('networks').get('chats')[0]

        sio = socketio.Client(reconnection=False,
                              logger=False,
                              engineio_logger=False)

        @sio.on('/chat/message')
        def on_chat_message(data):
            try:
                # Check if chat monitoring is enabled
                if not config.get('toggles', {}).get('features', {}).get(
                        'chat_monitoring', False):
                    return

                # Log chat message
                logger.info(f"Chat message received: {data}")

                # Only forward to Discord if webhook is configured
                if config.get('discord', {}).get('enabled', False):
                    from lokbot.discord_webhook import DiscordWebhook

                    webhook_url = config.get('discord',
                                             {}).get('chat_webhook_url')
                    if webhook_url:
                        webhook = DiscordWebhook(webhook_url)
                        webhook.send_chat_message(
                            sender=data.get('from', 'Unknown'),
                            message=data.get('text', ''),
                            channel=data.get('chatChannel', 'Unknown'))
                        logger.info(
                            "Chat message forwarded to Discord webhook")
            except Exception as e:
                logger.error(f"Error in chat monitoring: {str(e)}")
                logger.error(f"Error handling chat message: {e}")

        # Status update thread
        def send_status_updates():
            while True:
                try:
                    if config.get('discord', {}).get('enabled', False):
                        webhook_url = config.get(
                            'discord',
                            {}).get('status_webhook_url') or config.get(
                                'discord', {}).get('webhook_url')
                        if webhook_url:
                            webhook = DiscordWebhook(webhook_url)

                            # Collect status info
                            status = {
                                "Building Queue":
                                "Active"
                                if self.building_queue_available.is_set() else
                                "Waiting",
                                "Research Queue":
                                "Active"
                                if self.research_queue_available.is_set() else
                                "Waiting",
                                "Training Queue":
                                "Active"
                                if self.train_queue_available.is_set() else
                                "Waiting",
                                "Active Marches":
                                f"{len(self.troop_queue)}/{self.march_limit}",
                                "Resources":
                                "Gathering" if any(
                                    True for march in self.troop_queue
                                    if march.get('marchType') ==
                                    MARCH_TYPE_GATHER) else "None"
                            }

                            webhook.send_status_update(status)
                except Exception as e:
                    logger.error(f"Error sending status update: {e}")
                finally:
                    time.sleep(1800)  # Update every 30 minutes

        # Start status update thread
        status_thread = threading.Thread(target=send_status_updates)
        status_thread.daemon = True
        status_thread.start()

        # Connect to chat
        sio.connect(url, transports=["websocket"], headers=ws_headers)
        sio.emit('/chat/enter', {'token': self.token})

        sio.wait()
        logger.warning('socc_thread disconnected, reconnecting')
        raise tenacity.TryAgain()

    def harvester(self):
        """
        收获资源
        :return:
        """
        buildings = self.kingdom_enter.get('kingdom', {}).get('buildings', [])

        random.shuffle(buildings)

        harvested_code = set()
        for building in buildings:
            code = building.get('code')
            position = building.get('position')

            if code not in HARVESTABLE_CODE:
                continue

            # 每个种类只需要收获一次, 就会自动收获整个种类下所有资源
            if code in harvested_code:
                continue

            harvested_code.add(code)

            self.api.kingdom_resource_harvest(position)

    def quest_monitor_thread(self):
        """
        任务监控
        :return:
        """
        quest_list = self.api.quest_list()

        # main quest(currently only one)
        [
            self.api.quest_claim(q) for q in quest_list.get('mainQuests')
            if q.get('status') == STATUS_FINISHED
        ]

        # side quest(max 5)
        if len([
                self.api.quest_claim(q) for q in quest_list.get('sideQuests')
                if q.get('status') == STATUS_FINISHED
        ]) >= 5:
            # 若五个均为已完成, 则翻页
            threading.Thread(target=self.quest_monitor_thread).start()
            return

        quest_list_daily = self.api.quest_list_daily().get('dailyQuest')

        # daily quest(max 5)
        if len([
                self.api.quest_claim_daily(q)
                for q in quest_list_daily.get('quests')
                if q.get('status') == STATUS_FINISHED
        ]) >= 5:
            # 若五个均为已完成, 则翻页
            threading.Thread(target=self.quest_monitor_thread).start()
            return

        # daily quest reward
        [
            self.api.quest_claim_daily_level(q)
            for q in quest_list_daily.get('rewards')
            if q.get('status') == STATUS_FINISHED
        ]

        # event
        event_list = self.api.event_list()
        event_has_red_dot = [
            each for each in event_list.get('events') if each.get('reddot') > 0
        ]
        for event in event_has_red_dot:
            event_info = self.api.event_info(event.get('_id'))
            finished_code = [
                each.get('code')
                for each in event_info.get('eventKingdom').get('events')
                if each.get('status') == STATUS_FINISHED
            ]

            if not finished_code:
                continue

            [
                self.api.event_claim(
                    event_info.get('event').get('_id'), each.get('_id'),
                    each.get('code'))
                for each in event_info.get('event').get('events')
                if each.get('code') in finished_code
            ]

        logger.info('quest_monitor: done, sleep for 1h')
        threading.Timer(3600, self.quest_monitor_thread).start()
        return

    def _building_farmer_worker(self, speedup=False):
        buildings = self.kingdom_enter.get('kingdom', {}).get('buildings', [])
        buildings.sort(key=lambda x: x.get('level'))
        kingdom_level = [
            b for b in buildings if b.get('code') == BUILDING_CODE_MAP['castle']
        ][0].get('level')

        # First check if there is any empty position available for building
        for level_requirement, positions in BUILD_POSITION_UNLOCK_MAP.items():
            if kingdom_level < level_requirement:
                continue

            for position in positions:
                if position.get('position') in [
                        building.get('position') for building in buildings
                ]:
                    continue

                building = {
                    'code': position.get('code'),
                    'position': position.get('position'),
                    'level': 0,
                    'state': BUILDING_STATE_NORMAL,
                }

                res = self._upgrade_building(building, buildings, speedup)

                if res == 'continue':
                    continue
                if res == 'break':
                    break

                return True

        # Then check if there is any upgradeable building
        for building in buildings:
            res = self._upgrade_building(building, buildings, speedup)

            if res == 'continue':
                continue
            if res == 'break':
                break

            return True

        return False

    def building_farmer_thread(self, speedup=False):
        """
        building farmer
        :param speedup:
        :return:
        """
        self.kingdom_tasks = self.api.kingdom_task_all().get(
            'kingdomTasks', [])

        silver_in_use = [
            t for t in self.kingdom_tasks
            if t.get('code') == TASK_CODE_SILVER_HAMMER
        ]
        gold_in_use = [
            t for t in self.kingdom_tasks
            if t.get('code') == TASK_CODE_GOLD_HAMMER
        ]

        if not silver_in_use or (self.has_additional_building_queue
                                 and not gold_in_use):
            if not self._building_farmer_worker(speedup):
                logger.info('no building to upgrade, sleep for 2h')
                threading.Timer(7200, self.building_farmer_thread).start()
                return

        self.building_queue_available.wait(
        )  # wait for building queue available from `sock_thread`
        self.building_queue_available.clear()
        threading.Thread(target=self.building_farmer_thread,
                         args=[speedup]).start()

    def academy_farmer_thread(self, to_max_level=False, speedup=False):
        """
        research farmer
        :param to_max_level:
        :param speedup:
        :return:
        """
        self.kingdom_tasks = self.api.kingdom_task_all().get(
            'kingdomTasks', [])

        worker_used = [
            t for t in self.kingdom_tasks if t.get('code') == TASK_CODE_ACADEMY
        ]

        if worker_used:
            if worker_used[0].get('status') == STATUS_CLAIMED:
                self.api.kingdom_task_claim(
                    self._random_choice_building(
                        BUILDING_CODE_MAP['academy'])['position'])
                logger.info(
                    f'train_troop: one loop completed, sleep for {interval} seconds'
                )
                threading.Timer(interval, self.train_troop_thread,
                                [troop_code, speedup, interval]).start()
                return

            if worker_used[0].get('status') == STATUS_PENDING:
                self.research_queue_available.wait(
                )  # wait for research queue available from `sock_thread`
                self.research_queue_available.clear()
                threading.Thread(target=self.academy_farmer_thread,
                                 args=[to_max_level, speedup]).start()
                return

            # 如果已完成, 则领取奖励并继续
            self.api.kingdom_task_claim(
                self._random_choice_building(
                    BUILDING_CODE_MAP['academy'])['position'])
            threading.Thread(target=self.academy_farmer_thread,
                             args=[to_max_level, speedup]).start()
            return


        exist_researches = self.api.kingdom_academy_research_list().get(
            'researches', [])
        buildings = self.kingdom_enter.get('kingdom', {}).get('buildings', [])
        academy_level = [
            b for b in buildings
            if b.get('code') == BUILDING_CODE_MAP['academy']
        ][0].get('level')

        for category_name, each_category in RESEARCH_CODE_MAP.items():
            for research_name, research_code in each_category.items():
                if not self._is_researchable(academy_level, category_name,
                                             research_name, exist_researches,
                                             to_max_level):
                    continue

                try:
                    res = self.api.kingdom_academy_research(
                        {'code': research_code})
                except OtherException as error_code:
                    if str(error_code) == 'not_enough_condition':
                        logger.warning(
                            f'category {category_name} reached max level')
                        break

                    logger.info(
                        f'research failed, try next one, current: {research_name}({research_code})'
                    )
                    continue

                if speedup:
                    self.do_speedup(
                        res.get('newTask').get('expectedEnded'),
                        res.get('newTask').get('_id'), 'research')

                self.research_queue_available.wait(
                )  # wait for research queue available from `sock_thread`
                self.research_queue_available.clear()
                threading.Thread(target=self.academy_farmer_thread,
                                 args=[to_max_level, speedup]).start()
                return

        logger.info('academy_farmer: no research to do, sleep for 2h')
        threading.Timer(2 * 3600, self.academy_farmer_thread,
                        [to_max_level]).start()
        return

    def _troop_training_capacity(self):
        """
        return total troop training capacity of all barracks
        """
        buildings = self.kingdom_enter.get('kingdom', {}).get('buildings', [])
        troop_training_capacity = 0
        for building in buildings:
            if building['code'] == BUILDING_CODE_MAP['barrack']:
                troop_training_capacity += BARRACK_LEVEL_TROOP_TRAINING_RATE_MAP[
                    int(building['level'])]

        return troop_training_capacity

    def _total_troops_capacity_all_barracks(self):
        """
        Calculate total troop capacity across all barracks
        :return: int - Total capacity
        """
        try:
            buildings = self.kingdom_enter.get('kingdom',
                                               {}).get('buildings', [])
            total_capacity = 0
            for building in buildings:
                if building['code'] == BUILDING_CODE_MAP['barrack']:
                    total_capacity += BARRACK_LEVEL_TROOP_TRAINING_RATE_MAP[
                        int(building['level'])]
            return total_capacity
        except Exception as e:
            logger.error(f"Error calculating total troop capacity: {e}")
            return 0

    def _total_troops_capacity_according_to_resources(self, troop_code):
        """
        return maximum number of troops according to resources
        """
        req_resources = TRAIN_TROOP_RESOURCE_REQUIREMENT[troop_code]

        amount = None
        for req_resource, resource in zip(req_resources, self.resources):
            if req_resource == 0:
                continue

            if amount is None or resource // req_resource <= amount:
                amount = resource // req_resource

        return amount if amount is not None else 0

    def _random_choice_building(self, building_code):
        """
        return a random building object with the building_code
        """
        buildings = self.kingdom_enter.get('kingdom', {}).get('buildings', [])
        return random.choice([
            building for building in buildings
            if building['code'] == building_code
        ])

    def train_troop_thread(self, troop_code, speedup=False, interval=3600):
        """
        train troop
        :param interval:
        :param troop_code:
        :param speedup:
        :return:
        """
        while self.api.last_requested_at + 16 > time.time():
            # attempt to prevent `insufficient_resources` due to race conditions
            logger.info(
                f'last requested at {arrow.get(self.api.last_requested_at).humanize()}, waiting...'
            )
            time.sleep(4)

        self.kingdom_tasks = self.api.kingdom_task_all().get(
            'kingdomTasks', [])

        worker_used = [
            t for t in self.kingdom_tasks if t.get('code') == TASK_CODE_CAMP
        ]

        troop_training_capacity = self._troop_training_capacity
        if worker_used:
            if worker_used[0].get('status') == STATUS_CLAIMED:
                self.api.kingdom_task_claim(
                    self._random_choice_building(
                        BUILDING_CODE_MAP['barrack'])['position'])
                logger.info(
                    f'train_troop: one loop completed, sleep for {interval} seconds'
                )
                threading.Timer(interval, self.train_troop_thread,
                                [troop_code, speedup, interval]).start()
                return

            if worker_used[0].get('status') == STATUS_PENDING:
                self.train_queue_available.wait(
                )  # wait for train queue available from `sock_thread`
                self.train_queue_available.clear()
                threading.Thread(target=self.train_troop_thread,
                                 args=[troop_code, speedup, interval]).start()
                return

        # if there are not enough resources, train how much possible
        total_troops_capacity_according_to_resources = self._total_troops_capacity_according_to_resources(
            troop_code)
        if troop_training_capacity > total_troops_capacity_according_to_resources:
            troop_training_capacity = total_troops_capacity_according_to_resources

        if not troop_training_capacity:
            logger.info('train_troop: no resource, sleep for 1h')
            threading.Timer(3600, self.train_troop_thread,
                            [troop_code, speedup, interval]).start()
            return

        try:
            res = self.api.train_troop(troop_code, troop_training_capacity)
        except OtherException as error_code:
            logger.info(f'train_troop: {error_code}, sleep for 1h')
            threading.Timer(3600, self.train_troop_thread,
                            [troop_code, speedup, interval]).start()
            return

        if speedup:
            self.do_speedup(
                res.get('newTask').get('expectedEnded'),
                res.get('newTask').get('_id'), 'train')

        self.train_queue_available.wait(
        )  # wait for train queue available from `sock_thread`
        self.train_queue_available.clear()
        threading.Thread(target=self.train_troop_thread,
                         args=[troop_code, speedup, interval]).start()

    def free_chest_farmer_thread(self, _type=0):
        """
        领取免费宝箱
        :return:
        """
        try:
            res = self.api.item_free_chest(_type)
        except OtherException as error_code:
            if str(error_code) == 'free_chest_not_yet':
                logger.info(
                    'free_chest_farmer: free_chest_not_yet, sleep for 2h')
                threading.Timer(2 * 3600,
                                self.free_chest_farmer_thread).start()
                return

            raise

        next_dict = {
            0:
            arrow.get(res.get('freeChest', {}).get('silver', {}).get('next')),
            1: arrow.get(res.get('freeChest', {}).get('gold', {}).get('next')),
            2: arrow.get(
                res.get('freeChest', {}).get('platinum', {}).get('next')),
        }
        next_type = min(next_dict, key=next_dict.get)

        threading.Timer(self.calc_time_diff_in_seconds(next_dict[next_type]),
                        self.free_chest_farmer_thread, [next_type]).start()

    def use_resource_in_item_list(self):
        """
        Use only 50 Action Points items of value 10 (total 500 AP)
        """
        try:
            item_list = self.api.item_list().get('items', [])
            if not item_list:
                logger.info("No items found in inventory")
                return

            # Find AP items with value 10
            ap_items = next(
                (item for item in item_list
                 if item.get('code') == ITEM_CODE_ACTION_POINTS_10), None)

            if not ap_items:
                logger.info("No AP items of value 10 found")
                return

            amount = ap_items.get('amount', 0)
            if amount <= 0:
                logger.info("No AP items available to use")
                return

            use_amount = min(50, amount)
            logger.info(f"Using {use_amount} x 10 AP items")
            self.api.item_use(ITEM_CODE_ACTION_POINTS_10, use_amount)
            time.sleep(random.randint(1, 3))

        except Exception as e:
            logger.error(f"Error using AP items: {str(e)}")

    def vip_chest_claim(self):
        """
        领取vip宝箱
        daily
        :return:
        """
        vip_info = self.api.kingdom_vip_info()

        if vip_info.get('vip', {}).get('isClaimed'):
            return

        self.api.kingdom_vip_claim()

    def dsavip_info(self):
        """
        DSA VIP info check
        :return:
        """
        try:
            dsavip_info = self.api.kingdom_dsavip_info()
            logger.info(f'DSA VIP info retrieved: {dsavip_info}')
            return dsavip_info
        except Exception as e:
            logger.error(f'Failed to get DSA VIP info: {str(e)}')
            return None

    def dsavip_chest_claim(self):
        """
        Claim DSA VIP chest (similar to vip_chest_claim)
        :return:
        """
        try:
            dsavip_info = self.api.kingdom_dsavip_info()

            # Check if DSA VIP chest is already claimed
            if dsavip_info.get('dsaVip', {}).get('isClaimed'):
                logger.info('DSA VIP chest already claimed today')
                return

            # Check if user has DSA VIP active
            if not dsavip_info.get('dsaVip', {}).get('isActive'):
                logger.info('DSA VIP is not active, cannot claim chest')
                return

            # Claim the DSA VIP chest
            result = self.api.kingdom_dsavip_claim()
            logger.info(f'DSA VIP chest claimed successfully: {result}')

        except Exception as e:
            logger.error(f'Failed to claim DSA VIP chest: {str(e)}')

    def activate_skills(self):
        """
        Activate enabled skills when they are available and not on cooldown
        """
        try:
            skills_config = self.config.get('main', {}).get('skills', {})

            if not skills_config.get('enabled', False):
                return

            skills_list = skills_config.get('skills', [])
            if not skills_list:
                return

            # Get current skill status using the correct API method
            skill_status = self.api.skill_list()
            if not skill_status:
                logger.warning('Failed to get skill status')
                return

            for skill in skills_list:
                if not skill.get('enabled', False):
                    continue

                skill_code = skill.get('code')
                if not skill_code:
                    continue

                try:
                    # Check if skill is available (not on cooldown and we have enough MP)
                    skill_info = None
                    for available_skill in skill_status.get('skills', []):
                        if available_skill.get('skillId') == skill_code or available_skill.get('code') == skill_code:
                            skill_info = available_skill
                            break

                    if not skill_info:
                        logger.debug(f'Skill {skill_code} not found in available skills')
                        continue

                    # Check if skill is on cooldown
                    cooldown = skill_info.get('cooldown', 0)
                    if cooldown > 0:
                        logger.debug(f'Skill {skill_code} is on cooldown: {cooldown} seconds')
                        continue

                    # Check if we have enough MP
                    current_mp = skill_status.get('mp', 0)
                    required_mp = skill_info.get('cost', 0)

                    if current_mp < required_mp:
                        logger.debug(f'Not enough MP for skill {skill_code}: {current_mp}/{required_mp}')
                        continue

                    # Activate the skill using the correct API method
                    result = self.api.skill_use(skill_code)
                    if result:
                        logger.info(f'✅ Successfully activated skill {skill_code}')
                        # Update current MP to prevent overlapping activations
                        current_mp -= required_mp
                    else:
                        logger.warning(f'❌ Failed to activate skill {skill_code}')

                except Exception as e:
                    logger.error(f'Error activating skill {skill_code}: {str(e)}')

        except Exception as e:
            logger.error(f'Error in activate_skills: {str(e)}')

    def alliance_farmer(self,
                        gift_claim=True,
                        help_all=True,
                        research_donate=True,
                        shop_auto_buy_item_code_list=None,
                        shop_items_config=None):
        if not self.alliance_id:
            return

        if gift_claim:
            self._alliance_gift_claim_all()

        if help_all:
            self._alliance_help_all()

        if research_donate:
            self._alliance_research_donate_all()

        # Enhanced shop buying with priority system and quantity controls
        if shop_items_config and isinstance(shop_items_config, dict):
            self._alliance_shop_autobuy_enhanced(shop_items_config)
        elif shop_auto_buy_item_code_list and type(shop_auto_buy_item_code_list) is list:
            # Backward compatibility - convert old format to new format
            old_config = {
                'enabled': True,
                'items': [{'item_code': code, 'enabled': True, 'priority': 1, 'min_buy': 1, 'max_buy': 999999} 
                         for code in shop_auto_buy_item_code_list]
            }
            self._alliance_shop_autobuy_enhanced(old_config)

    def caravan_farmer(self, caravan_items_config=None):
        """
        Enhanced caravan farmer with priority-based purchasing and quantity controls
        """
        try:
            caravan = self.api.kingdom_caravan_list().get('caravan')
            if not caravan:
                logger.info('No caravan data available')
                return

            available_items = caravan.get('items', [])
            if not available_items:
                logger.info('No items available in caravan')
                return

            # Use enhanced buying with configuration or fallback to basic mode
            if caravan_items_config and isinstance(caravan_items_config, dict):
                self._caravan_autobuy_enhanced(caravan_items_config, available_items)
            else:
                # Backward compatibility - basic caravan buying
                self._caravan_autobuy_basic(available_items)

        except Exception as e:
            logger.error(f'Error in caravan_farmer: {str(e)}')

    def _caravan_autobuy_enhanced(self, config, available_items):
        """
        Enhanced caravan buying with priority system and quantity controls
        """
        try:
            if not config.get('enabled', False):
                logger.debug('Caravan buying is disabled')
                return

            configured_items = config.get('items', [])
            if not configured_items:
                logger.info('No caravan items configured for purchase')
                return

            # Filter and sort items by priority (1 = highest priority)
            enabled_items = [item for item in configured_items if item.get('enabled', False)]
            if not enabled_items:
                logger.info('No caravan items enabled for purchase')
                return

            # Sort by priority (ascending, so 1 comes first)
            enabled_items.sort(key=lambda x: x.get('priority', 999))

            total_purchased = 0
            purchase_summary = []

            for config_item in enabled_items:
                item_code = config_item.get('item_code')
                if not item_code:
                    continue

                # Find this item in available caravan items
                available_item = None
                for caravan_item in available_items:
                    if caravan_item.get('code') == item_code:
                        available_item = caravan_item
                        break

                if not available_item:
                    logger.debug(f'Caravan item {item_code} not available in current caravan')
                    continue

                if available_item.get('amount', 0) < 1:
                    logger.debug(f'Caravan item {item_code} out of stock')
                    continue

                # Check cost and affordability
                cost = available_item.get('cost', 0)
                cost_item_code = available_item.get('costItemCode')
                
                if not cost_item_code:
                    logger.debug(f'No cost currency for item {item_code}')
                    continue

                # Get current resource amount
                resource_index = lokbot.util.get_resource_index_by_item_code(cost_item_code)
                if resource_index == -1:
                    logger.debug(f'Unknown cost currency {cost_item_code} for item {item_code}')
                    continue

                current_resources = self.resources[resource_index]
                if cost > current_resources:
                    logger.debug(f'Cannot afford item {item_code}: costs {cost}, have {current_resources}')
                    continue

                # Calculate how many we can/should buy
                min_buy = max(1, config_item.get('min_buy', 1))
                max_buy = config_item.get('max_buy', 999999)
                available_amount = available_item.get('amount', 0)
                
                # Determine actual purchase amount
                target_amount = min(max_buy, available_amount)
                target_amount = max(min_buy, target_amount) if target_amount >= min_buy else 0
                
                if target_amount == 0:
                    logger.debug(f'Purchase amount for item {item_code} is 0 (below minimum)')
                    continue

                # Check if we can afford the minimum amount
                total_cost = cost * target_amount
                if total_cost > current_resources:
                    # Try to buy as many as we can afford
                    affordable_amount = current_resources // cost
                    if affordable_amount >= min_buy:
                        target_amount = min(affordable_amount, max_buy)
                    else:
                        logger.debug(f'Cannot afford minimum quantity for item {item_code}')
                        continue

                # Attempt purchase
                try:
                    item_info = CARAVAN_ITEMS.get(item_code, {})
                    item_name = item_info.get('name', f'Item {item_code}')
                    
                    # For caravan, we buy one at a time in a loop
                    purchased_count = 0
                    for _ in range(target_amount):
                        try:
                            self.api.kingdom_caravan_buy(available_item.get('_id'))
                            purchased_count += 1
                            time.sleep(random.uniform(0.5, 1.5))  # Small delay between purchases
                        except Exception as e:
                            logger.warning(f'Failed to buy item {item_code}: {str(e)}')
                            break

                    if purchased_count > 0:
                        total_purchased += purchased_count
                        purchase_summary.append(f"{item_name} x{purchased_count}")
                        logger.info(f'✅ Bought {purchased_count}x {item_name} from caravan')
                        
                        # Update resource count for next calculations
                        self.resources[resource_index] -= (cost * purchased_count)

                except Exception as e:
                    logger.error(f'Error purchasing caravan item {item_code}: {str(e)}')

            # Summary
            if total_purchased > 0:
                logger.info(f'🛒 Caravan purchase complete: {", ".join(purchase_summary)}')
            else:
                logger.info('No caravan items purchased (none affordable/available)')

        except Exception as e:
            logger.error(f'Error in enhanced caravan buying: {str(e)}')

    def _caravan_autobuy_basic(self, available_items):
        """
        Basic caravan buying for backward compatibility
        """
        try:
            purchased_count = 0
            
            for each_item in available_items:
                if each_item.get('amount') < 1:
                    continue

                if each_item.get('code') not in BUYABLE_CARAVAN_ITEM_CODE_LIST:
                    continue

                cost_item_code = each_item.get('costItemCode')
                if not cost_item_code:
                    continue

                resource_index = lokbot.util.get_resource_index_by_item_code(cost_item_code)
                if resource_index == -1:
                    continue

                if each_item.get('cost', 0) > self.resources[resource_index]:
                    continue

                try:
                    self.api.kingdom_caravan_buy(each_item.get('_id'))
                    purchased_count += 1
                    item_info = CARAVAN_ITEMS.get(each_item.get('code'), {})
                    item_name = item_info.get('name', f"Item {each_item.get('code')}")
                    logger.info(f'✅ Bought {item_name} from caravan (basic mode)')
                    time.sleep(random.uniform(0.5, 1.5))
                except Exception as e:
                    logger.warning(f'Failed to buy caravan item: {str(e)}')

            if purchased_count > 0:
                logger.info(f'🛒 Basic caravan purchase complete: {purchased_count} items bought')
            else:
                logger.info('No caravan items purchased (basic mode)')
                
        except Exception as e:
            logger.error(f'Error in basic caravan buying: {str(e)}')

    def mail_claim(self):
        self.api.mail_claim_all(1)  # report
        time.sleep(random.randint(4, 6))
        self.api.mail_claim_all(2)  # alliance
        time.sleep(random.randint(4, 6))
        self.api.mail_claim_all(3)  # system

    def wall_repair(self):
        wall_info = self.api.kingdom_wall_info()

        max_durability = wall_info.get('wall', {}).get('maxDurability')
        durability = wall_info.get('wall', {}).get('durability')
        last_repair_date = wall_info.get('wall', {}).get('lastRepairDate')

        if not last_repair_date:
            return

        last_repair_date = arrow.get(last_repair_date)
        last_repair_diff = arrow.utcnow() - last_repair_date

        if durability >= max_durability:
            return

        if int(last_repair_diff.total_seconds()) < 60 * 30:
            # 30 minute interval
            return

        self.api.kingdom_wall_repair()

    def hospital_recover(self):
        if self.hospital_recover_lock.locked():
            logger.info('another hospital_recover is running, skip')
            return

        # Add a random delay before starting the recovery process to simulate human behavior
        initial_delay = random.uniform(5, 15)
        logger.info(
            f'Adding random initial delay of {initial_delay:.2f} seconds before checking hospital'
        )
        time.sleep(initial_delay)

        with self.hospital_recover_lock:
            # Check if there are wounded troops
            wounded = self.api.kingdom_hospital_wounded().get('wounded', [])

            if not wounded:
                logger.info('No wounded troops in hospital, skipping recovery')
                return

            logger.info(
                f'Found {sum(len(batch) for batch in wounded)} wounded troops in hospital'
            )

            # Add another small delay to simulate reviewing the wounded troops
            review_delay = random.uniform(2, 6)
            logger.info(
                f'Adding random delay of {review_delay:.2f} seconds while checking wounded troops'
            )
            time.sleep(review_delay)

            estimated_end_time = None
            for each_batch in wounded:
                if estimated_end_time is None:
                    estimated_end_time = arrow.get(
                        each_batch[0].get('startTime'))
                time_total = sum([each.get('time') for each in each_batch])
                estimated_end_time = estimated_end_time.shift(
                    seconds=time_total)

            if estimated_end_time and estimated_end_time > arrow.utcnow():
                # Add delay before using speedups
                speedup_delay = random.uniform(3, 8)
                logger.info(
                    f'Adding random delay of {speedup_delay:.2f} seconds before using speedupss'
                )
                time.sleep(speedup_delay)

                self.do_speedup(estimated_end_time, 'dummy_task_id', 'recover')

            # Final delay before issuing recovery command
            final_delay = random.uniform(2, 5)
            logger.info(
                f'Adding final random delay of {final_delay:.2f} seconds before hospital recovery'
            )
            time.sleep(final_delay)

            self.api.kingdom_hospital_recover()

    def keepalive_request(self):
        try:
            lokbot.util.run_functions_in_random_order(
                self.api.kingdom_wall_info,
                self.api.quest_main,
                self.api.item_list,
                self.api.kingdom_treasure_list,
                self.api.event_list,
                self.api.event_cvc_open,
                self.api.event_roulette_open,
                self.api.drago_lair_list,
                self.api.pkg_recommend,
                self.api.pkg_list,
            )
        except OtherException:
            pass

    def field_rally_join(self, rally_id, march_troops):
        """Join an existing rally.
        :param rally_id: The ID of the rally to join.
        :param march_troops: The troops to send to the rally.
        :return: The result of the rally join operation.
        """
        try:
            return self.post('field/rally/join', {
                'rallyId': rally_id,
                'marchTroops': march_troops
            })
        except Exception as e:
            logger.error(f'Failed to join rally {rally_id}: {e}')
            return None

    def _get_current_active_buffs(self):
        """Get current active buffs with enhanced validation - prioritizing socc_thread data"""
        try:
            # First priority: Use active_buffs from socc_thread /buff/list WebSocket events
            if hasattr(self, 'active_buffs') and self.active_buffs:
                logger.debug(f"Using socc_thread buff data: {len(self.active_buffs)} active buffs")
                return self.active_buffs

            # Fallback: Try to get fresh buff data from the kingdom enter response
            kingdom_response = self.api.kingdom_enter()
            if kingdom_response and 'kingdom' in kingdom_response:
                buffs = kingdom_response.get('kingdom', {}).get('buffs', [])
                if buffs:
                    logger.debug(f"Retrieved {len(buffs)} active buffs from kingdom_enter")
                    return buffs

            # Final fallback: empty list
            logger.debug("No buff data available from any source")
            return []

        except Exception as e:
            logger.debug(f"Failed to get buff data: {e}")
            return getattr(self, 'active_buffs', [])

    def _buff_management_thread(self):
        """Thread to monitor and automatically reactivate buffs based on configuration"""
        logger.info("Buff management thread started - checking every 10 minutes")

        # Track last activation times to prevent over-activation
        self.buff_last_activation = {}
        # Minimum cooldown between activations (in seconds) - 30 minutes default
        self.buff_activation_cooldown = 1800

        while True:
            try:
                # Get buff management configuration
                buff_config = config.get('buff_management', {})

                if not buff_config.get('enabled', False):
                    logger.debug("Buff management is disabled in config")
                    time.sleep(120)  # Sleep for 2 minutes
                    continue

                # Get configured buffs to monitor
                monitored_buffs = buff_config.get('buffs', [])
                if not monitored_buffs:
                    logger.debug("No buffs configured for monitoring")
                    time.sleep(120)
                    continue

                logger.info("Checking buff status and reactivating if needed (using socc_thread data)...")

                # Wait for initial startup before activating buffs
                while self.started_at + 10 > time.time():
                    logger.info(
                        f'started at {arrow.get(self.started_at).humanize()}, wait 10 seconds to activate buffs'
                    )
                    time.sleep(4)

                # Get fresh active buffs data with enhanced validation (prioritizes socc_thread data)
                current_active_buffs = self._get_current_active_buffs()
                logger.debug(f"Buff management using data source: {'socc_thread' if hasattr(self, 'active_buffs') and self.active_buffs else 'API fallback'}")

                # Get available items in inventory
                item_list = self.api.item_list().get('items', [])

                for buff_config_item in monitored_buffs:
                    if not buff_config_item.get('enabled', True):
                        continue

                    buff_name = buff_config_item.get('name', 'Unknown')
                    item_codes = buff_config_item.get('item_codes', [])
                    min_duration_minutes = buff_config_item.get('min_duration_minutes', 20)

                    if not item_codes:
                        logger.warning(f"No item codes configured for buff: {buff_name}")
                        continue

                    # Check cooldown to prevent over-activation
                    buff_key = f"{buff_name}_{':'.join(map(str, item_codes))}"
                    last_activation_time = self.buff_last_activation.get(buff_key, 0)
                    current_time = time.time()

                    if current_time - last_activation_time < self.buff_activation_cooldown:
                        remaining_cooldown = self.buff_activation_cooldown - (current_time - last_activation_time)
                        logger.info(f"{buff_name} is in cooldown, {remaining_cooldown/60:.1f} minutes remaining")
                        continue

                    # Check if buff is currently active with enhanced validation
                    active_buff = None
                    active_buff_count = 0

                    for buff in current_active_buffs:
                        buff_item_code = buff.get('param', {}).get('itemCode')
                        if buff_item_code in item_codes:
                            active_buff = buff
                            active_buff_count += 1

                    # Log multiple active buffs of same type (potential issue indicator)
                    if active_buff_count > 1:
                        logger.warning(f"Found {active_buff_count} active {buff_name} buffs - possible over-activation detected")

                    should_activate = False
                    activation_reason = ""

                    if active_buff:
                        # Check remaining time with enhanced validation
                        remaining_time = active_buff.get('remainingTime', 0)
                        remaining_minutes = remaining_time / 60 if remaining_time else 0

                        # Additional safety check - don't activate if remaining time is > 8 hours (suspicious)
                        if remaining_minutes > 480:
                            logger.warning(f"{buff_name} has {remaining_minutes:.1f} minutes remaining (>8h) - skipping activation")
                            continue

                        if remaining_minutes < min_duration_minutes:
                            should_activate = True
                            activation_reason = f"Low remaining time: {remaining_minutes:.1f}min < {min_duration_minutes}min threshold"
                        else:
                            logger.debug(f"{buff_name} buff still active with {remaining_minutes:.1f} minutes remaining")
                    else:
                        should_activate = True
                        activation_reason = "Buff not active"

                    if should_activate:
                        # Check if we have the buff items in inventory
                        available_items = [
                            item for item in item_list
                            if item.get('code') in item_codes and item.get('amount', 0) > 0
                        ]

                        if not available_items:
                            logger.info(f"No {buff_name} items available in inventory")
                            continue

                        if self.buff_item_use_lock.locked():
                            logger.debug("Buff lock is active, skipping this buff")
                            continue

                        try:
                            with self.buff_item_use_lock:
                                # Use the first available item
                                item_to_use = available_items[0]
                                item_code = item_to_use.get('code')

                                logger.info(f"Activating {buff_name} buff with item code: {item_code} - Reason: {activation_reason}")
                                self.api.item_use(item_code)

                                # Record activation time to prevent over-activation
                                self.buff_last_activation[buff_key] = current_time

                                # Update Golden Hammer status
                                if item_code == ITEM_CODE_GOLDEN_HAMMER:
                                    self.has_additional_building_queue = True

                                # Send buff activation notification
                                try:
                                    self._send_notification(
                                        'buff_activated',
                                        '🛡️ Buff Activated',
                                        f'Successfully activated {buff_name.replace("_", " ").title()} buff (Code: {item_code}) - {activation_reason}'
                                    )
                                except Exception as notif_error:
                                    logger.debug(f"Failed to send buff notification: {notif_error}")

                                # Add delay between buff activations
                                time.sleep(random.uniform(3, 8))

                                # Log activation for monitoring
                                logger.info(f"Successfully activated {buff_name} - Next activation allowed after: {arrow.get(current_time + self.buff_activation_cooldown).format('YYYY-MM-DD HH:mm:ss')}")

                        except Exception as e:
                            logger.error(f"Failed to activate {buff_name} buff: {str(e)}")

                logger.info("Buff management cycle completed")

            except Exception as e:
                logger.error(f"Error in buff management thread: {str(e)}")

            # Sleep for 10 minutes before next check
            time.sleep(600)

    def _check_rallies_thread(self):
        """Thread to periodically check for new rallies using alliance_battle_list_v2"""
        while True:
            try:
                # Get the rally configuration from config (new structure)
                rally_config = config.get('rally', {}).get('join', {})

                # Check if rally join is enabled
                if not rally_config.get('enabled', False):
                    logger.info(
                        'Rally join is disabled in config, skipping check')
                    time.sleep(60)
                    continue
                else:
                    logger.info(
                        'Rally join is enabled, checking for available rallies'
                    )

                # Get target monster codes from config
                target_codes = [
                    target.get('monster_code')
                    for target in rally_config.get('targets', [])
                ]

                if not target_codes:
                    logger.info('No rally targets configured, skipping check')
                    time.sleep(60)
                    continue

                # Get maximum number of rallies to join from config
                max_rallies = rally_config.get('numMarch', 9)

                # Check for available rallies using alliance_battle_list_v2
                logger.info(
                    'Checking for available rallies via alliance_battle_list_v2'
                )
                try:
                    battle_response = self.api.alliance_battle_list_v2()
                    if not isinstance(battle_response, dict):
                        logger.error(
                            f'Invalid response from alliance_battle_list_v2: {battle_response}'
                        )
                        time.sleep(60)
                        continue
                    battles = battle_response.get('battles', [])
                except Exception as e:
                    logger.error(f'Failed to fetch battle list: {e}')
                    time.sleep(60)
                    continue

                # Log the number of active rallies found
                logger.info(f'Found {len(battles)} active rallies')

                # Count rallies already joined
                joined_rallies = [b for b in battles if b.get('isJoined')]
                logger.info(f'Already joined {len(joined_rallies)} rallies')

                # Skip if we've already joined max rallies
                if len(joined_rallies) >= max_rallies:
                    logger.info(
                        f'Already joined maximum number of rallies ({max_rallies}), skipping check'
                    )
                    time.sleep(60)
                    continue

                # Process unjoined rallies
                for battle in battles:
                    # Skip if already joined
                    if battle.get('isJoined'):
                        continue

                    rally_id = battle.get('_id')
                    if not rally_id:
                        logger.warning(
                            'Found battle without rally ID, skipping')
                        continue

                    # Get monster code and level from battle info
                    monster_code = None
                    monster_level = None

                    # Try both data structures
                    if 'targetMonster' in battle and 'code' in battle.get(
                            'targetMonster', {}):
                        monster_code = battle.get('targetMonster',
                                                  {}).get('code')
                        monster_level = battle.get('targetMonster',
                                                   {}).get('level')
                    else:
                        # Try alternative data structure
                        target_monster = battle.get('target',
                                                    {}).get('monster', {})
                        if target_monster and 'code' in target_monster:
                            monster_code = target_monster.get('code')
                            monster_level = target_monster.get('level')

                    # Skip if no monster code found
                    if not monster_code:
                        logger.debug(
                            f"No monster code found for rally {rally_id}, skipping")
                        continue

                    # Check if monster code is in our target list
                    if monster_code in target_codes:
                        # If we're using level-based troops, check if we have a configuration for this level
                        if rally_config.get(
                                'level_based_troops',
                                False) and monster_level is not None:
                            monster_level = int(monster_level)

                            # Find target configuration for this monster code
                            target_config = next((
                                target
                                for target in rally_config.get('targets', [])
                                if target.get('monster_code') == monster_code),
                                                 None)

                            if target_config:
                                # Check if we have a level range that matches this monster's level
                                level_range_match = any(
                                    level_range.get('min_level', 0) <=
                                    monster_level <= level_range.get(
                                        'max_level', 0)
                                    for level_range in target_config.get(
                                        'level_ranges', []))

                                if not level_range_match:
                                    logger.info(
                                        f"No matching level range for monster level {monster_level}, skipping rally {rally_id}"
                                    )
                                    continue
                            else:
                                logger.info(
                                    f"No target configuration for monster code {monster_code}, skipping rally {rally_id}"
                                )
                                continue

                        logger.info(
                            f"Found unjoined rally for monster code {monster_code}, level {monster_level}: {rally_id}"
                        )

                        # Pass the battle data directly to join_rally to avoid an extra API call
                        if self.join_rally(rally_id, battle_data=battle):
                            logger.info(
                                f"Successfully joined rally {rally_id}")

                            # Discord notification is already handled in join_rally method
                            logger.info(
                                "Discord notification will be sent by the join_rally method"
                            )
                        else:
                            logger.error(f"Failed to join rally {rally_id} - checking if reconnection is needed")
                            # Add a small delay before trying next rally to avoid rapid failures
                            time.sleep(random.uniform(3, 6))

                # Check every 30 seconds
                time.sleep(30)
            except Exception as e:
                logger.error(f'Error checking rallies: {e}')
                time.sleep(60)  # Wait longer if there's an error
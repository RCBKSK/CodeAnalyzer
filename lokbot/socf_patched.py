    def _socf_thread_internal(self, radius, targets, share_to=None):
        """
        PATCHED: Fixed Socket.IO connection to match browser behavior exactly
        """
        import base64
        import json
        import gzip
        import threading
        import time
        import arrow
        import random
        from datetime import datetime, timezone
        from lokbot import config

        # Set a flag to track thread status
        self.socf_thread_active = True

        # Watchdog timer thread
        def watchdog():
            while self.socf_thread_active:
                if not hasattr(self, 'last_socf_activity'):
                    self.last_socf_activity = time.time()

                if time.time() - self.last_socf_activity > 300:  # 5 minutes timeout
                    logger.error("SOCF thread appears stuck - forcing reconnection")
                    try:
                        self.socf_thread_active = False
                    except:
                        pass
                time.sleep(60)

        # Start watchdog
        watchdog_thread = threading.Thread(target=watchdog, daemon=True)
        watchdog_thread.start()

        try:
            logger.info("Starting PATCHED SOCF thread")
            self.last_socf_activity = time.time()

            # Check if object scanning is enabled
            object_scanning_enabled = config.get('main', {}).get('object_scanning', {}).get('enabled', True)
            socf_enabled = False
            jobs = config.get('main', {}).get('jobs', [])
            for job in jobs:
                if job.get('name') == 'socf_thread' and job.get('enabled', False):
                    socf_enabled = True
                    break

            if not object_scanning_enabled or not socf_enabled:
                logger.info('Object scanning or socf_thread job is disabled in config.')
                return

            # Get field URL (keep original protocol)
            url = self.kingdom_enter.get('networks', {}).get('fields', [])[0]
            logger.info(f'[SOCF] Field URL: {url[:50]}...')

            # Initialize zones if needed
            if not getattr(self, 'zones', None):
                from_loc = self.kingdom_enter.get('kingdom').get('loc')
                self.zones = self._get_nearest_zone_ng(from_loc[1], from_loc[2], radius)

            # Create Socket.IO client
            sio = socketio.Client(
                reconnection=True,
                reconnection_attempts=10,
                reconnection_delay=1,
                reconnection_delay_max=5,
                logger=False,
                engineio_logger=False
            )

            # Threading events for proper sequencing
            field_enter_done = threading.Event()
            field_objects_done = threading.Event()

            # Helper for parsing field objects
            def parse_field_objects_internal(data):
                timestamp = arrow.now().format('HH:mm:ss.SSS')
                data_decoded = None
                
                # NEW FORMAT: {"EventName":"/field/objects/v4","Payload":"JSON_STRING"}
                if isinstance(data, dict) and 'EventName' in data and 'Payload' in data:
                    payload_str = data.get('Payload')
                    if isinstance(payload_str, str):
                        try:
                            data_decoded = json.loads(payload_str)
                        except json.JSONDecodeError:
                            return None
                    else:
                        data_decoded = payload_str
                
                # OLD FORMAT: Try packed/compressed data
                elif isinstance(data, dict) and 'packs' in data:
                    try:
                        packs = data.get('packs')
                        if isinstance(packs, list):
                            packs = bytearray(packs)
                        gzip_decompress = gzip.decompress(packs)
                        data_decoded = self.api.b64xor_dec(gzip_decompress)
                    except Exception:
                        return None
                
                # FALLBACK: Direct objects field
                elif isinstance(data, dict) and 'objects' in data:
                    data_decoded = data
                
                return data_decoded

            @sio.on('connect')
            def on_connect():
                timestamp = arrow.now().format('HH:mm:ss.SSS')
                logger.info(f'[{timestamp}] SOCF socket connected')
                time.sleep(0.1)
                
                # STEP 1: Send JWT token as plain string
                logger.info(f'[{timestamp}] Step 1: Sending JWT token')
                sio.emit('/field/enter/v3', self.token)
                time.sleep(0.05)
                
                # STEP 2: Send kingdom data as EventName/Payload object
                kingdom_data = self.kingdom_enter.get('kingdom', {})
                payload_obj = {
                    "loc": kingdom_data.get('loc', [0, 0, 0]),
                    "kingdom": kingdom_data,
                    "dbTime": self.kingdom_enter.get('dbTime', datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')),
                    "map": {"width": 3072, "height": 3072}
                }
                
                logger.info(f'[{timestamp}] Step 2: Sending kingdom data')
                sio.emit('/field/enter/v3', {
                    "EventName": "/field/enter/v3",
                    "Payload": json.dumps(payload_obj)
                })
                self.socf_entered = True

            @sio.on('/field/enter/v3')
            def on_field_enter(data):
                timestamp = arrow.now().format('HH:mm:ss.SSS')
                logger.info(f'[{timestamp}] Received /field/enter/v3 response')
                try:
                    if isinstance(data, dict) and 'Payload' in data:
                        payload_str = data['Payload']
                        data_decoded = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
                    else:
                        data_decoded = data
                    
                    self.socf_world_id = data_decoded.get('loc', [0])[0]
                    field_enter_done.set()
                    
                    # Send zone handshake sequence
                    time.sleep(0.05)
                    
                    # 3a. Leave empty zones
                    sio.emit('/zone/leave/list/v2', {
                        'world': self.socf_world_id,
                        'zones': '[]'
                    })
                    time.sleep(0.05)
                    
                    # 3b. Enter initial zones [0,96,1,97] (BASE64)
                    initial_zones = [0, 96, 1, 97]
                    payload_b64 = base64.b64encode(
                        json.dumps({
                            "world": self.socf_world_id,
                            "zones": json.dumps(initial_zones)
                        }).encode()
                    ).decode()
                    sio.emit('/zone/enter/list/v4', payload_b64)
                    time.sleep(0.05)
                    
                    # 3c. Leave initial zones
                    sio.emit('/zone/leave/list/v2', {
                        'world': self.socf_world_id,
                        'zones': json.dumps(initial_zones)
                    })
                    time.sleep(0.05)
                    
                    # 3d. Enter target zones (BASE64)
                    if getattr(self, 'zones', None):
                        target_zones = self.zones[:9]
                        payload_b64 = base64.b64encode(
                            json.dumps({
                                "world": self.socf_world_id,
                                "zones": json.dumps(target_zones)
                            }).encode()
                        ).decode()
                        sio.emit('/zone/enter/list/v4', payload_b64)
                except Exception as e:
                    logger.error(f'Error in field enter handler: {e}')

            @sio.on('/field/objects/v4')
            def on_field_objects(data):
                field_objects_done.set()
                self.last_socf_activity = time.time()
                
                data_decoded = parse_field_objects_internal(data)
                if not data_decoded:
                    return

                objects = data_decoded.get('objects', [])
                if not objects:
                    return

                # Process objects...
                for each_obj in objects:
                    code = each_obj.get('code')
                    if code in [20100101, 20100102, 20100103, 20100104, 20100105, 20100106]:
                        self._on_field_objects_gather(each_obj)
                    else:
                        self._on_field_objects_monster(each_obj)

            @sio.on('/march/objects')
            def on_march_objects(data):
                if isinstance(data, dict) and 'EventName' in data and 'Payload' in data:
                    payload_str = data.get('Payload')
                    try:
                        march_data = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
                        with self.march_objects_lock:
                            self.march_objects_data = march_data
                            self.march_objects_last_update = time.time()
                    except Exception as e:
                        logger.error(f'Error parsing march objects: {e}')

            # Connect
            ws_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36'
            }
            sio.connect(url, transports=['polling', 'websocket'], headers=ws_headers, namespaces=['/'])

            # Wait for handshake
            if not field_enter_done.wait(timeout=30):
                raise TimeoutError("Field enter timeout")
            if not field_objects_done.wait(timeout=30):
                raise TimeoutError("Field objects timeout")

            logger.info('[SOCF] Handshake complete, starting scan loop')

            while self.socf_thread_active:
                time.sleep(10)

        except Exception as e:
            logger.error(f"Error in SOCF thread: {e}")
        finally:
            self.socf_thread_active = False
            try:
                sio.disconnect()
            except:
                pass

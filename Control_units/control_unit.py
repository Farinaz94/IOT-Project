import json
import time
import sched
import requests
import copy
from datetime import datetime
import threading

class Controler():
    def __init__(self, catalogAddress, mqtt_client, main_topic):
        self.catalogAddress = catalogAddress.rstrip('/')
        self.client = mqtt_client
        self.main_topic = main_topic
        
        self.device_status_cache = {}
        self.last_motion_time = {}
        self.latest_light_level = {}

        self.scheduler = sched.scheduler(time.time, time.sleep)
        self.scheduler.enter(15, 1, self.check_environmental_conditions, ())
        
        self.thread = threading.Thread(target=self.scheduler.run)
        self.thread.daemon = True
        self.thread.start()

        self.msg_template = {
            "bn": None,
            "e": [{"n": "actuator", "u": "command", "t": None, "v": None}]
        }

    def process_message(self, topic, payload):
        try:
            parts = topic.split("/")
            if len(parts) < 6: return

            _, _, houseID, floorID, unitID, sensorType = parts[:6]
            key = (int(houseID), int(floorID), int(unitID))
            
            event = payload.get("e", [{}])[0]
            value = event.get("v")

            if sensorType == "motion_sensor":
                if value == "Detected":
                    self.last_motion_time[key] = time.time()
                    print(f"[ALERT] Motion in {key[0]}/{key[1]}/{key[2]}")
                    self.send_command(key, "light_switch", "ON", "Motion Detected")
            elif sensorType == "light_sensor":
                self.latest_light_level[key] = float(value)

        except Exception as e:
            print(f"[ERROR] Controller failed to process message: {e}")

    def check_environmental_conditions(self):
        now = time.time()
        all_known_keys = set(self.latest_light_level.keys()) | set(self.device_status_cache.keys())

        for key in all_known_keys:
            light_level = self.latest_light_level.get(key, 1000)
            last_motion = self.last_motion_time.get(key, 0)
            is_light_on = self.device_status_cache.get(key, {}).get("light_switch") == "ON"

            # SCENARIO 1: Turn light ON if it's dark
            if not is_light_on and light_level < 400:
                print(f"[ACTION] Low light in {key} -> Turn ON light")
                self.send_command(key, "light_switch", "ON", "Low Light Level")
                continue

            # SCENARIO 2: Turn light OFF if no motion and bright
            if is_light_on and (now - last_motion > 30):
                if light_level > 400:
                    print(f"[ACTION] No motion & bright in {key} -> Turn OFF light")
                    self.send_command(key, "light_switch", "OFF", "Auto-Off: Bright & No Motion")
                    if key in self.last_motion_time:
                        del self.last_motion_time[key]
        
        self.scheduler.enter(15, 1, self.check_environmental_conditions, ())

    def send_command(self, key, device_name, command, reason):
        houseID, floorID, unitID = key
        topic = f"{self.main_topic}/commands/{houseID}/{floorID}/{unitID}/{device_name}"
        msg = copy.deepcopy(self.msg_template)
        msg["bn"] = topic
        msg["e"][0]["t"] = str(time.time())
        msg["e"][0]["v"] = command
        self.client.myPublish(topic, msg)
        print(f"[CMD] {command} -> {topic} (Reason: {reason})")
        self.update_catalog(key, device_name, command, reason)
        
    def update_catalog(self, key, device_name, new_status, reason):
        if key not in self.device_status_cache:
            self.device_status_cache[key] = {}
        
        if self.device_status_cache[key].get(device_name) == new_status:
            return
        
        self.device_status_cache[key][device_name] = new_status
        
        try:
            r = requests.get(f"{self.catalogAddress}/houses")
            houses = r.json()
            device_to_update = None
            for house in houses:
                if str(house.get("houseID")) == str(key[0]):
                    for floor in house.get("floors", []):
                        if str(floor.get("floorID")) == str(key[1]):
                            for unit in floor.get("units", []):
                                if str(unit.get("unitID")) == str(key[2]):
                                    for device in unit.get("devicesList", []):
                                        if device.get("deviceName") == device_name:
                                            device_to_update = device
                                            break
            
            if device_to_update:
                device_to_update["deviceStatus"] = new_status
                device_to_update["lastUpdate"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # Add the reason to the device's data
                device_to_update["lastCommandReason"] = reason
                requests.put(f"{self.catalogAddress}/devices", json=device_to_update)
            
        except Exception as e:
            print(f"[ERROR] Failed to update catalog: {e}")
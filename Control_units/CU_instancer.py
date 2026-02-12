import requests
import time
import json
import math
import threading
from control_unit import Controler
from MyMQTT2 import MyMQTT

class CU_instancer():
    def __init__(self, catalogAddress):
        self.catalogAddress = catalogAddress.rstrip('/')
        self.PERIODIC_UPDATE_INTERVAL = 60
        self.NUM_UNITS_PER_CONTROLLER = 5

        self.controllers = {}
        self.unit_assignment = {}
        
        try:
            broker, port, main_topic = self.get_mqtt_config()
            self.main_topic = main_topic
            client_id = f"CU_Instancer_{int(time.time())}"
            self.client = MyMQTT(client_id, broker, port, self)
            self.client.start()
        except Exception as e:
            print(f"[FATAL] Could not start MQTT client for instancer: {e}")
            return
        
        self.update_and_rebalance_controllers()
        
        self.scheduler = threading.Timer(self.PERIODIC_UPDATE_INTERVAL, self.update_and_rebalance_controllers)
        self.scheduler.daemon = True
        self.scheduler.start()

    def get_mqtt_config(self):
        """Fetches broker details and the main topic from the catalog."""
        print(f"[INFO] CU Instancer fetching MQTT config from {self.catalogAddress}...")
        r_broker = requests.get(f"{self.catalogAddress}/broker", timeout=5)
        r_broker.raise_for_status()
        broker_info = r_broker.json()

        r_topic = requests.get(f"{self.catalogAddress}/topic", timeout=5)
        r_topic.raise_for_status()
        main_topic = r_topic.text.strip('"')

        return broker_info["IP"], int(broker_info["port"]), main_topic
        
    def notify(self, topic, payload):
        """This is the single entry point for all MQTT messages."""
        print(f"[DISPATCH] Received on topic: {topic}")
        try:
            parts = topic.split("/")
            if len(parts) < 5: return

            unit_key_str = f"{parts[2]}-{parts[3]}-{parts[4]}"
            assigned_controller_name = self.unit_assignment.get(unit_key_str)
            
            if assigned_controller_name:
                controller = self.controllers.get(assigned_controller_name)
                if controller:
                    controller.process_message(topic, payload)
                else:
                    print(f"[WARN] No controller instance found for '{assigned_controller_name}'")
            else:
                print(f"[WARN] No controller assigned for unit '{unit_key_str}'")
        except Exception as e:
            print(f"[ERROR] Error in dispatcher notify(): {e}")

    def update_and_rebalance_controllers(self):
        print("[INFO] Checking for unit updates and rebalancing controllers...")
        try:
            resp = requests.get(f"{self.catalogAddress}/houses", timeout=5)
            resp.raise_for_status()
            houses = resp.json()
            
            current_units = set()
            for house in houses:
                for floor in house.get("floors", []):
                    for unit in floor.get("units", []):
                        uid = f"{house['houseID']}-{floor['floorID']}-{unit['unitID']}"
                        current_units.add(uid)

            if set(self.unit_assignment.keys()) == current_units and self.controllers:
                print("[INFO] No change in units. No rebalance needed.")
                return

            print("[INFO] Unit list has changed. Rebalancing controllers.")
            availableUnitsList = sorted(list(current_units))

            needed_controllers = math.ceil(len(availableUnitsList) / self.NUM_UNITS_PER_CONTROLLER)
            for i in range(needed_controllers):
                name = f"controller_{i}"
                if name not in self.controllers:
                    self.controllers[name] = Controler(self.catalogAddress, self.client, self.main_topic)
                    print(f"[INIT] Created {name}")

            self.unit_assignment.clear()
            for idx, unit in enumerate(availableUnitsList):
                controller_idx = idx // self.NUM_UNITS_PER_CONTROLLER
                assigned_controller = f"controller_{controller_idx}"
                self.unit_assignment[unit] = assigned_controller
            
            print(f"[REBALANCE] Unit assignment updated: {self.unit_assignment}")
            
            topic_to_subscribe = f"{self.main_topic}/sensors/#"
            self.client.mySubscribe(topic_to_subscribe)
            print(f"[SUBSCRIBE] Instancer subscribed to master topic: {topic_to_subscribe}")

        except Exception as e:
            print(f"[ERROR] Failed during rebalance: {e}")


if __name__ == "__main__":
    # When running in Docker, this connects to the 'catalog' service
    catalogAddress = "http://catalog:8080/"
    cu_instancer = CU_instancer(catalogAddress)
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("\n[EXIT] Shutting down...")
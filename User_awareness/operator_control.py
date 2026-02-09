# changelog:
# - 2025-07-21: Converted from a polling to an event-driven model by adding an MQTT client.
# - 2025-07-21: Motion alerts are now received instantly and reliably.

# - 2025-07-27: Corrected the URL in fetch_unit_devices to include the /devices endpoint.
# - 2025-07-27: Removed debug prints for cleaner logs.
# - 2025-07-29: Added logic to inject `lastCommandReason` for light switches based on motion alerts.

import requests
import cherrypy
import time
import json
import threading
from MyMQTT2 import MyMQTT 

class OperatorControl:
    exposed = True

    def __init__(self, catalog_address):
        self.catalog_address = catalog_address.rstrip('/')
        self.houses = {}
        self.motion_alerts = {} 

        self.mqtt_client = None
        try:
            broker, port, main_topic = self.get_mqtt_config()
            client_id = f"OperatorControl_{int(time.time())}"
            self.mqtt_client = MyMQTT(client_id, broker, port, self)
            self.mqtt_client.start()
            self.mqtt_client.mySubscribe(f"{main_topic}/sensors/#")
            print(f"[MQTT] Operator Control subscribed to {main_topic}/sensors/#")
        except Exception as e:
            print(f"[FATAL ERROR] Could not start MQTT client: {e}")

        # Start a background thread to periodically update the house list
        self.house_update_thread = threading.Thread(target=self.periodic_house_update, daemon=True)
        self.house_update_thread.start()

    def notify(self, topic, payload):
        try:
            print(f"[MQTT NOTIFY] Received message on topic: {topic}")
            parts = topic.split("/")
            if len(parts) < 6 or "motion_sensor" not in parts[-1]:
                return 

            value = payload.get("e", [{}])[0].get("v")
            if value == "Detected":
                unit_key = f"{parts[2]}-{parts[3]}-{parts[4]}"
                self.motion_alerts[unit_key] = time.time()
                print(f"[ALERT] Real-time motion alert received for unit: {unit_key}")
        except Exception as e:
            print(f"[ERROR] Could not process MQTT message in Operator Control: {e}")

    def get_mqtt_config(self):
        r_broker = requests.get(f"{self.catalog_address}/broker", timeout=5)
        r_broker.raise_for_status()
        broker_info = r_broker.json()

        r_topic = requests.get(f"{self.catalog_address}/topic", timeout=5)
        r_topic.raise_for_status()
        main_topic = r_topic.text.strip('"')
        return broker_info["IP"], int(broker_info["port"]), main_topic

    @cherrypy.tools.json_out()
    def GET(self, *uri, **params):
        if not uri:
            return {"error": "Invalid endpoint."}

        path = uri[0].lower()
        if path == "houses":
            return self.get_realtime_data()
        elif path == "motion_alerts":
            active_alerts = [
                key for key, ts in self.motion_alerts.items() 
                if time.time() - ts < 300 
            ]
            return {"activeAlerts": active_alerts}
        return {"error": f"Endpoint '/{path}' not found."}

    def periodic_house_update(self):
        while True:
            try:
                response = requests.get(f"{self.catalog_address}/houses", timeout=5)
                response.raise_for_status()
                houses_list = response.json()
                self.houses = {str(h.get("houseID")): h for h in houses_list if h.get("houseID")}
                print(f"[INFO] House list updated. Found {len(self.houses)} houses.")
            except requests.exceptions.RequestException as e:
                print(f"[ERROR] Could not update house list from catalog: {e}")
            time.sleep(60)

    def get_realtime_data(self):
        if not self.houses:
            return {}
        
        real_time_houses = json.loads(json.dumps(self.houses)) 
        
        for house_id, house in real_time_houses.items():
            for floor in house.get("floors", []):
                for unit in floor.get("units", []):
                    # Fetch the raw device list first
                    unit["devicesList"] = self.fetch_unit_devices(unit)

                    
                    unit_key = f"{house.get('houseID')}-{floor.get('floorID')}-{unit.get('unitID')}"
                    
                    # Check if the current unit has a recent motion alert
                    unit_has_active_alert = (
                        unit_key in self.motion_alerts and
                        time.time() - self.motion_alerts.get(unit_key, 0) < 300 # 5-minute window for alerts
                    )

                    # Add the 'lastCommandReason' to light switches
                    for device in unit.get("devicesList", []):
                        if "light_switch" in device.get("deviceName", ""):
                            if device.get("deviceStatus") == "ON":
                                if unit_has_active_alert:
                                    device["lastCommandReason"] = "Motion Detected"
                                else:
                                    device["lastCommandReason"] = "Automatic Rule"
                            else:  # Status is OFF
                                device["lastCommandReason"] = "No Motion / Timed Out"
                    

        return real_time_houses

    def fetch_unit_devices(self, unit):
        all_devices = []
        urls_to_fetch = [unit.get("urlSensors"), unit.get("urlActuators")]
        
        for url in urls_to_fetch:
            if not url: continue
            try:
                full_url = f"{url.rstrip('/')}/devices"
                response = requests.get(full_url, timeout=3)
                response.raise_for_status()
                data = response.json()
                
                if isinstance(data, list):
                    all_devices.extend(data)
                
            except requests.exceptions.RequestException as e:
                print(f"[ERROR] Operator failed to fetch from {full_url}: {e}")
                
        return all_devices

def cors():
    cherrypy.response.headers["Access-Control-Allow-Origin"] = "*"
    cherrypy.response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    cherrypy.response.headers["Access-Control-Allow-Headers"] = "Content-Type"

def OPTIONS(*args, **kwargs):
    return ""

if __name__ == "__main__":
    cherrypy.tools.cors = cherrypy.Tool('before_handler', cors)
    conf = {
        "/": { "request.dispatch": cherrypy.dispatch.MethodDispatcher(), "tools.cors.on": True }
    }
    catalog_address = "http://catalog:8080/"
    operator_control = OperatorControl(catalog_address)
    operator_control.OPTIONS = OPTIONS 
    
    cherrypy.config.update({'server.socket_host': '0.0.0.0', 'server.socket_port': 8095})
    cherrypy.tree.mount(operator_control, "/", conf)
    cherrypy.engine.start()
    cherrypy.engine.block()
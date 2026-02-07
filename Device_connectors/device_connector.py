import requests
import time
import json
import copy
import cherrypy
import logging
import threading

from MyMQTT import MyMQTT
from sensors import LightSensor, MotionSensor

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class senPublisher():
    def __init__(self, clientID, broker, port):
        self.client = MyMQTT(clientID, broker, port, None)
        self.start()

    def start(self):
        self.client.start()

    def stop(self):
        self.client.stop()

    def publish(self, topic, msg):
        self.client.myPublish(topic, msg)

class Device_connector():
    exposed = True

    def __init__(self, catalog_url, DCConfiguration, baseClientID, houseID, floorID, unitID):
        self.catalog_url = catalog_url
        self.DCConfiguration = DCConfiguration
        self.houseID = houseID
        self.floorID = floorID
        self.unitID = unitID
        self.clientID = f"{baseClientID}_{houseID}_{floorID}_{unitID}_DCS"
        self.DATA_AVG_INTERVAL = self.DCConfiguration.get("DATA_AVG_INTERVAL", 10)
        self.DATA_SENDING_INTERVAL = self.DCConfiguration.get("DATA_SENDING_INTERVAL", 15) # Faster for demo
        self.latest_light_reading = 0 


        self._is_running = threading.Event()

        try:
            broker, port, main_topic = self.get_mqtt_config()
            self.main_topic = main_topic
        except Exception as e:
            logger.error(f"Failed to get broker info from catalog: {e}")
            return

        self.senPublisher = senPublisher(self.clientID, broker, port)
        self.light_sensor = LightSensor(f"{houseID}_{floorID}_{unitID}_light")
        self.motion_sensor = MotionSensor(f"{houseID}_{floorID}_{unitID}_motion")

        self.msg_template = {
            "bn": f"{self.main_topic}/sensors/{houseID}/{floorID}/{unitID}/",
            "e": [{"n": "sensorKind", "u": "unit", "t": None, "v": None}]
        }


        # It's important that this device has a unique ID. We'll base it on the light sensor's ID.
        light_sensor_id = self.DCConfiguration["devicesList"][0]["deviceID"]
        motion_sensor_device = {
            "deviceID": light_sensor_id + 10000, 
            "deviceName": "motion_sensor",
            "deviceStatus": "No Motion", # Initial status
            "availableStatuses": ["Detected", "No Motion"],
            "deviceLocation": { "houseID": houseID, "floorID": floorID, "unitID": unitID },
            "measureType": ["motion"],
            "availableServices": ["MQTT"],
            "servicesDetails": [{
                "serviceType": "MQTT",
                "topic": [f"{self.main_topic}/sensors/{houseID}/{floorID}/{unitID}/motion_sensor"]
            }],
            "lastUpdate": "2025-01-01 00:00:00"
        }
        # Add the new motion sensor to the list that the API will serve
        self.DCConfiguration["devicesList"].append(motion_sensor_device)

        self.registerer()
        self.start_sending_data()

    def start_sending_data(self):
        self._is_running.set()
        self.thread = threading.Thread(target=self.send_data_loop)
        self.thread.daemon = True
        self.thread.start()

    def stop_sending_data(self):
        self._is_running.clear()
        if self.thread and self.thread.is_alive():
            self.thread.join()
        self.senPublisher.stop()
        logger.info("MQTT publisher for %s stopped.", self.clientID)

    @cherrypy.tools.json_out()
    def GET(self, *uri, **params):
        if len(uri) != 0 and uri[0].lower() == "devices":
            response_data = json.loads(json.dumps(self.DCConfiguration)) # Create a deep copy
            # Find the light sensor and add its latest value
            for device in response_data.get("devicesList", []):
                if "light_sensor" in device.get("deviceName", ""):
                    device["value"] = self.latest_light_reading
            return response_data
        cherrypy.response.status = 404
        return {"error": "Invalid endpoint. Use /devices"}

    def send_data_loop(self):
        logger.info("Started publishing sensor data for %s...", self.clientID)
        while self._is_running.is_set():
            try:
                msg_light, msg_motion = self.get_sen_data()

                current_time = time.strftime("%Y-%m-%d %H:%M:%S")

                # Update light sensor status
                self.DCConfiguration["devicesList"][0]["deviceStatus"] = "ON" # Light sensor is always ON
                self.DCConfiguration["devicesList"][0]["lastUpdate"] = current_time
                
                # Update motion sensor status
                self.DCConfiguration["devicesList"][1]["deviceStatus"] = msg_motion["e"][0]["v"]
                self.DCConfiguration["devicesList"][1]["lastUpdate"] = current_time

                # Publish both messages
                self.senPublisher.publish(msg_light["bn"], msg_light)
                logger.info(f"Published light data: {msg_light['e'][0]['v']}")
                
                self.senPublisher.publish(msg_motion["bn"], msg_motion)
                logger.info(f"Published motion data: {msg_motion['e'][0]['v']}")

                time.sleep(self.DATA_SENDING_INTERVAL)
            except Exception as e:
                logger.error(f"An unexpected error occurred in send_data_loop for {self.clientID}: {e}")
                time.sleep(10)

    def get_sen_data(self):
        light_val = self.light_sensor.generate_data()
        self.latest_light_reading = light_val
        motion_val = self.motion_sensor.generate_data()
        motion_status = "Detected" if motion_val else "No Motion"
       

        msg_light = copy.deepcopy(self.msg_template)
        msg_light["bn"] += "light_sensor"
        msg_light["e"][0].update({"n": "light", "u": "lux", "t": str(time.time()), "v": light_val})

        msg_motion = copy.deepcopy(self.msg_template)
        msg_motion["bn"] += "motion_sensor"
        msg_motion["e"][0].update({"n": "motion", "u": "status", "t": str(time.time()), "v": motion_status})

        return msg_light, msg_motion

    def get_mqtt_config(self):
        r_broker = requests.get(f"{self.catalog_url}/broker", timeout=5)
        r_broker.raise_for_status()
        broker_info = r_broker.json()
        r_topic = requests.get(f"{self.catalog_url}/topic", timeout=5)
        r_topic.raise_for_status()
        main_topic = r_topic.text.strip('"')
        return broker_info["IP"], int(broker_info["port"]), main_topic

    def registerer(self):
        """Registers all devices this connector manages with the catalog."""
        for device in self.DCConfiguration["devicesList"]:
            try:
                # Use PUT for an "upsert" operation, which is simpler and more robust
                response = requests.put(f"{self.catalog_url}/devices", json=device, timeout=5)
                response.raise_for_status()
                logger.info(f"Device '{device['deviceName']}' for {self.clientID} registered/updated successfully.")
            except requests.exceptions.RequestException as e:
                logger.error(f"Error registering device '{device['deviceName']}' for {self.clientID}: {e}")


from MyMQTT import MyMQTT
import requests
import time
import json
import cherrypy

class Device_connector_act():
    exposed = True

    def __init__(self, catalog_url, DCConfiguration, baseClientID, DCID):
        self.catalog_url = catalog_url
        self.DCConfiguration = DCConfiguration
        self.clientID = f"{baseClientID}_{DCID}_DCA_{int(time.time())}"
        self.devices = self.DCConfiguration.get("devicesList", [])
        
        try:
            self.houseID, self.floorID, self.unitID = DCID.split("-")
        except ValueError:
            print(f"Error parsing DCID '{DCID}'.")
            return

        try:
            broker, port = self.get_broker()
            self.client = MyMQTT(self.clientID, broker, port, self)
            self.client.start()
            print(f"[{self.clientID}] MQTT client started.")
            
            topic = f"ThiefDetector/commands/{self.houseID}/{self.floorID}/{self.unitID}/#"
            self.client.mySubscribe(topic)
            print(f"[{self.clientID}] Subscribed to topic: {topic}")
        except Exception as e:
            print(f"[{self.clientID} ERROR] Failed to start MQTT client: {e}")

    @cherrypy.tools.json_out()
    def GET(self, *uri, **params):
        if len(uri) > 0 and uri[0] == "devices":
            return self.devices
        return "Go to '/devices' to see the devices list."

    def notify(self, topic, payload):
        print(f"[{self.clientID} NOTIFY] Command received on topic: {topic}")
        try:
            event = payload.get("e", [{}])[0]
            deviceStatusValue = event.get("v", "unknown")
            deviceName = topic.split("/")[-1]

            for device in self.devices:
                if device["deviceName"].lower() == deviceName.lower():
                    print(f"[{self.clientID}] Updating '{deviceName}' status to '{deviceStatusValue}'")
                    device["deviceStatus"] = deviceStatusValue
                    device["lastUpdate"] = time.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            print(f"[{self.clientID} ERROR] Unexpected error in notify: {e}")

    def stop(self):
        self.client.stop()
        print(f"[{self.clientID}] MQTT client stopped.")

    def get_broker(self):
        req_b = requests.get(f"{self.catalog_url}/broker")
        req_b.raise_for_status()
        broker_json = req_b.json()
        return broker_json["IP"], int(broker_json["port"])
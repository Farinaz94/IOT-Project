import requests
import time
import threading
from flask import Flask
from MyMQTT2 import MyMQTT

class Adaptor:
    def __init__(self, catalog_url):
        self.catalog_url = catalog_url
        self.clientID = f"ThingSpeak_Adaptor_V2_{int(time.time())}"
        self.channel_API = "https://api.thingspeak.com/update"
        self.unit_to_field_map = {
            "1-1-1": {"channel": "house1", "field": "field1"},
            "1-1-2": {"channel": "house1", "field": "field2"},
            "1-2-1": {"channel": "house1", "field": "field3"},
            "2-1-1": {"channel": "house2", "field": "field1"},
            "2-1-2": {"channel": "house2", "field": "field2"},
            "2-2-1": {"channel": "house2", "field": "field3"},
        }
        self.api_keys = {"house1": "TYJBKZK6C3VMU6X0", "house2": "639Q1WGL7VNX405K"}
        self.buffers = {
            "house1": {"field1": 0, "field2": 0, "field3": 0},
            "house2": {"field1": 0, "field2": 0, "field3": 0}
        }
        self.lock = threading.Lock()

        try:
            broker, port, main_topic = self.get_mqtt_config()
            self.client = MyMQTT(self.clientID, broker, port, self)
            self.client.start()
            command_topic = f"{main_topic}/commands/#"
            self.client.mySubscribe(command_topic)
            print(f"[SUBSCRIBE] Listening for all commands on: {command_topic}")
        except Exception as e:
            print(f"[ERROR] Adaptor could not start MQTT client: {e}")
            return
            
        for channel in self.api_keys.keys():
            self.schedule_update(channel)

    def get_mqtt_config(self):
        print(f"[INFO] Adaptor fetching MQTT config from {self.catalog_url}...")
        r_broker = requests.get(f"{self.catalog_url}broker", timeout=5)
        r_broker.raise_for_status()
        broker_info = r_broker.json()
        r_topic = requests.get(f"{self.catalog_url}topic", timeout=5)
        r_topic.raise_for_status()
        main_topic = r_topic.text.strip('"')
        return broker_info["IP"], int(broker_info["port"]), main_topic

    def schedule_update(self, channel):
        threading.Timer(15.0, self.flush_channel, args=[channel]).start()

    def flush_channel(self, channel):
        with self.lock:
            url = f"{self.channel_API}?api_key={self.api_keys[channel]}"
            for field, value in self.buffers[channel].items():
                url += f"&{field}={value}"
            try:
                r = requests.get(url, timeout=5)
                r.raise_for_status()
                print(f"[THING] Sent to {channel}: {self.buffers[channel]} -> Status {r.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"[ERROR] Failed to update ThingSpeak for {channel}: {e}")
        self.schedule_update(channel)

    def notify(self, topic, payload):
        print(f"[MQTT] Adaptor received command on: {topic}")
        try:
            parts = topic.split("/")
            if len(parts) < 6 or parts[-1] != "light_switch":
                return
            unit_key = f"{parts[2]}-{parts[3]}-{parts[4]}"
            command = payload.get("e", [{}])[0].get("v")
            if unit_key in self.unit_to_field_map:
                config = self.unit_to_field_map[unit_key]
                new_value = 1 if command == "ON" else 0
                with self.lock:
                    self.buffers[config["channel"]][config["field"]] = new_value
                print(f"[ADAPT] Updated {config['channel']}/{config['field']} to {new_value}")
        except Exception as e:
            print(f"[ERROR] Failed to process message on topic '{topic}': {e}")

app = Flask(__name__)
adaptor = Adaptor(catalog_url="http://catalog:8080/")

@app.route("/", methods=["GET"])
def index():
    return "<h1>ThingSpeak Adaptor is Running</h1>"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8099, debug=False, use_reloader=False)
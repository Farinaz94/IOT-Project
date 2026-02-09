# changelog:
# - 2025-07-29: Final version with proactive alerts for all command types.
# - The bot now listens to both sensor and command topics on MQTT.

import requests
import time
import json
import telepot
from telepot.loop import MessageLoop
from telepot.namedtuple import InlineKeyboardMarkup, InlineKeyboardButton
from MyMQTT2 import MyMQTT 

class TeleBot:
    def __init__(self, token, operator_control_url, ownership_file, catalog_url):
        self.token = token
        self.operator_control_url = operator_control_url
        self.ownership_file = ownership_file
        self.bot = telepot.Bot(self.token)
        self.load_ownership_data()

        # NEW: Initialize and start the MQTT client for real-time alerts
        self.mqtt_client = None
        try:
            broker, port, main_topic = self.get_mqtt_config(catalog_url)
            client_id = f"TelegramBot_Alerts_{int(time.time())}"
            # The 'self' object is passed as the notifier
            self.mqtt_client = MyMQTT(client_id, broker, port, self)
            self.mqtt_client.start()
            # Subscribe to both sensor and command topics
            self.mqtt_client.mySubscribe(f"{main_topic}/sensors/#")
            self.mqtt_client.mySubscribe(f"{main_topic}/commands/#")
            print(f"[TELEGRAM MQTT] Subscribed to all topics.")
        except Exception as e:
            print(f"[TELEGRAM MQTT ERROR] Could not start MQTT client: {e}")

        MessageLoop(self.bot, {'chat': self.on_chat_message, 'callback_query': self.on_callback_query}).run_as_thread()
        print("[TELEGRAM] Bot is now listening for commands...")

    def load_ownership_data(self):
        try:
            with open(self.ownership_file, 'r') as fp:
                self.ownership_dict = json.load(fp)
        except (FileNotFoundError, json.JSONDecodeError):
            self.ownership_dict = {}

    def get_mqtt_config(self, catalog_url):
        r_broker = requests.get(f"{catalog_url}/broker", timeout=5)
        r_broker.raise_for_status()
        broker_info = r_broker.json()
        r_topic = requests.get(f"{catalog_url}/topic", timeout=5)
        r_topic.raise_for_status()
        main_topic = r_topic.text.strip('"')
        return broker_info["IP"], int(broker_info["port"]), main_topic

    def notify(self, topic, payload):
        """MQTT callback for ALL real-time alerts."""
        try:
            parts = topic.split("/")
            if len(parts) < 6: return

            topic_type = parts[1]
            houseID = parts[2]
            unit_str = f"House {houseID}, F{parts[3]}/U{parts[4]}"
            
            # Find the user who owns this house
            owner_id = None
            for user_id, owned_house_id in self.ownership_dict.items():
                if str(owned_house_id) == str(houseID):
                    owner_id = user_id
                    break
            
            if not owner_id:
                return # No one owns this house, so no alert to send

            # Handle Motion Alerts from Sensor Topic
            if topic_type == "sensors" and "motion_sensor" in parts[-1]:
                value = payload.get("e", [{}])[0].get("v")
                if value == "Detected":
                    alert_message = f"🚨 *MOTION ALERT!* 🚨\n\nMotion detected in *{unit_str}*."
                    self.bot.sendMessage(owner_id, alert_message, parse_mode="Markdown")
            

        except Exception as e:
            print(f"[TELEGRAM MQTT ERROR] Could not process alert message: {e}")


    def get_house_data(self):
        try:
            response = requests.get(f"{self.operator_control_url}/houses")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"[TELEGRAM ERROR] Could not fetch house data: {e}")
            return {}

    def on_chat_message(self, msg):
        content_type, chat_type, chat_id = telepot.glance(msg)
        command = msg.get('text', '').strip()

        if command.lower() in ["/start", "/menu"]:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='📊 Track My House', callback_data='track_my_house')],
                [InlineKeyboardButton(text='🏠 Claim a House', callback_data='claim_a_house')],
                [InlineKeyboardButton(text='🌐 Track All Houses', callback_data='track_all_houses')]
            ])
            self.bot.sendMessage(chat_id, "Welcome to the ThiefDetector Bot! What would you like to do?", reply_markup=keyboard)
        else:
            self.bot.sendMessage(chat_id, "Sorry, I couldn't understand that command. Please use /menu.")

    def on_callback_query(self, msg):
        query_id, from_id, query_data = telepot.glance(msg, flavor='callback_query')
        from_id_str = str(from_id)
        all_house_data = self.get_house_data()

        if query_data == "claim_a_house":
            all_houses = list(all_house_data.keys())
            if not all_houses:
                self.bot.sendMessage(from_id, "No houses are currently online.")
                return
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"House {house_id}", callback_data=f"claim_{house_id}")]
                for house_id in all_houses
            ])
            self.bot.sendMessage(from_id, "Please select a house to claim:", reply_markup=keyboard)
        
        elif query_data.startswith("claim_"):
            houseID = query_data.split("_", 1)[1]
            self.ownership_dict[from_id_str] = houseID
            self.save_ownership_data()
            self.bot.answerCallbackQuery(query_id, text=f"You now own House {houseID}")
            self.bot.sendMessage(from_id, f"✅ You have successfully claimed House {houseID}!")

        elif query_data == "track_my_house":
            if from_id_str not in self.ownership_dict:
                self.bot.answerCallbackQuery(query_id, text="You don't own a house yet.")
                return

            houseID = self.ownership_dict[from_id_str]
            house_data = all_house_data.get(houseID)
            
            if not house_data:
                self.bot.sendMessage(from_id, f"Could not retrieve data for your house (House {houseID}). It might be offline.")
                return

            report = self.format_house_report(house_data)
            self.bot.sendMessage(from_id, report, parse_mode="Markdown")

        elif query_data == "track_all_houses":
            if not all_house_data:
                self.bot.sendMessage(from_id, "No houses are currently online.")
                return
            
            full_report = "*System Status Overview*\n" + "="*25 + "\n\n"
            for house_id, house_data in all_house_data.items():
                full_report += self.format_house_report(house_data) + "\n" + "="*25 + "\n\n"
            
            self.bot.sendMessage(from_id, full_report, parse_mode="Markdown")

    def format_house_report(self, house_data):
        house_id = house_data.get('houseID', 'N/A')
        report = f"📊 *Status for {house_data.get('houseName', 'House ' + house_id)}*\n\n"
        
        for floor in house_data.get("floors", []):
            for unit in floor.get("units", []):
                report += f"*F{floor.get('floorID', '?')}/U{unit.get('unitID', '?')}*:\n"
                if not unit.get("devicesList"):
                    report += "- _No devices found._\n"
                    continue
                
                for device in unit.get("devicesList", []):
                    name = device.get("deviceName", "Unknown").replace("_", " ").title()
                    status = device.get("deviceStatus", "N/A")
                    icon = "💡" if "light" in name.lower() else "🏃"
                    
                    report += f"- {icon} *{name}*: `{status}`\n"
                    
                    if "lastCommandReason" in device and device["lastCommandReason"]:
                        report += f"  `↳ Reason: {device['lastCommandReason']}`\n"

        return report

    def save_ownership_data(self):
        with open(self.ownership_file, 'w') as fp:
            json.dump(self.ownership_dict, fp, indent=4)

if __name__ == "__main__":
    catalog_url = "http://catalog:8080/"
    operator_control_url = "http://operator-control:8095/" 
    ownership_file = "device_ownership.json" 
    token = "replace your token"  # Replace with your actual token
    

    try:
        print("[TELEGRAM] Deleting any existing webhook...")
        bot_instance = telepot.Bot(token)
        bot_instance.deleteWebhook()
        print("[TELEGRAM] Webhook deleted successfully.")
    except Exception as e:
        print(f"[TELEGRAM WARNING] Could not delete webhook, but continuing: {e}")

    bot = TeleBot(token, operator_control_url, ownership_file, catalog_url)

    try:
        print("Telegram Bot is now running. Press Ctrl+C to exit.")
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("\nShutting down bot...")
        bot.save_ownership_data()
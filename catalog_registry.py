import cherrypy
import json
import datetime
import os
import tempfile

# Schema for validating a new device
DEVICE_SCHEMA = {
    "deviceID": {"type": (int, str), "required": True},
    "deviceName": {"type": str, "required": True},
    "deviceStatus": {"type": str, "required": True},
    "availableStatuses": {"type": list, "required": True},
    "deviceLocation": {"type": dict, "required": True},
    "measureType": {"type": list, "required": True},
    "availableServices": {"type": list, "required": True},
    "servicesDetails": {"type": list, "required": True},
}

# Schema for validating a new house
HOUSE_SCHEMA = {
    "houseID": {"type": str, "required": True},
    "houseName": {"type": str, "required": True},
    "floors": {"type": list, "required": True},
}

class WebCatalogThiefDetector():
    exposed = True

    def __init__(self, address):
        with open(address, 'r') as fptr:
            self.catalog = json.load(fptr)

        self.mainTopic = self.catalog["projectName"]
        self.broker = self.catalog["broker"]
        self.housesList = self.catalog["housesList"]

        self.deviceGetter()

        # Use CherryPy Monitor for background tasks
        cherrypy.process.plugins.Monitor(cherrypy.engine, self.periodic_cleanup, frequency=600).subscribe()

    def validate_payload(self, payload, schema):
        """
        Validates a payload against a given schema.
        Returns a list of errors. If the list is empty, the payload is valid.
        """
        errors = []
        for field, rules in schema.items():
            if rules.get("required") and field not in payload:
                errors.append(f"Missing required field: '{field}'")
                continue

            if field in payload and not isinstance(payload[field], rules["type"]):
                errors.append(f"Invalid type for field '{field}'. Expected {rules['type']}, got {type(payload[field])}")

        return errors

    @cherrypy.tools.json_out()
    def GET(self, *uri, **params):
        if len(uri) == 0:
            return "No valid URL. Try /broker, /devices, /device/{id}, /houses, /house/{houseID}, /topic"
        path = uri[0].lower()

        if path == "broker":
            return self.broker
        elif path == "devices":
            return self.devices
        elif path == "device":
            if len(uri) < 2:
                return "No device ID provided. Try /device/{id}"
            deviceID = uri[1]
            theDevice = self.get_device_by_id(deviceID)
            return theDevice if theDevice else f"No device found with ID {deviceID}"
        elif path == "houses":
            return self.housesList
        elif path == "house":
            if len(uri) < 2:
                return "No house ID provided. Try /house/{houseID}"
            houseID = uri[1]
            theHouse = self.get_house_by_id(houseID)
            return theHouse if theHouse else f"No house found with ID {houseID}"
        elif path == "topic":
            return self.mainTopic
        elif path == "houseshow":
            house = self.catalog["housesList"][0]
            return house
        else:
            return "Invalid URL. Try /broker, /devices, /device/{id}, /houses, /house/{houseID}, /topic"

    def _update_device_in_catalog(self, device_data):
        theTime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        device_data["lastUpdate"] = theTime
        try:
            houseID = str(device_data["deviceLocation"]["houseID"])
            floorID = str(device_data["deviceLocation"]["floorID"])
            unitID  = str(device_data["deviceLocation"]["unitID"])
        except KeyError:
            return "deviceLocation must contain houseID, floorID, unitID", 400

        house = self.get_house_by_id(houseID)
        if not house:
            return f"No house found with ID {houseID}", 404
        floorObj = self.get_floor_by_id(house, floorID)
        if not floorObj:
            return f"No floor {floorID} found in house {houseID}", 404
        unitObj = self.get_unit_by_id(floorObj, unitID)
        if not unitObj:
            return f"No unit {unitID} found on floor {floorID} of house {houseID}", 404

        existing_index = None
        for i, dev in enumerate(unitObj["devicesList"]):
            if str(dev.get("deviceID")) == str(device_data.get("deviceID")):
                existing_index = i
                break

        if existing_index is not None:
            unitObj["devicesList"][existing_index] = device_data
        else:
            unitObj["devicesList"].append(device_data)

        self.catalog["lastUpdate"] = theTime
        self.save_catalog()
        self.deviceGetter()
        return "Device updated/added successfully", 200 # Changed message to be generic

    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def POST(self, *uri, **params):
        if len(uri) == 0:
            return "Use /houses or /devices to add new items."
        path = uri[0].lower()

        if path == "houses":
            newHouse = cherrypy.request.json
            errors = self.validate_payload(newHouse, HOUSE_SCHEMA)
            if errors:
                return {"errors": errors}

            newHouse["lastUpdate"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.housesList.append(newHouse)
            self.catalog["lastUpdate"] = newHouse["lastUpdate"]
            self.save_catalog()
            self.deviceGetter()
            return "House added successfully", 201

        elif path == "devices":
            newDevice = cherrypy.request.json
            errors = self.validate_payload(newDevice, DEVICE_SCHEMA)
            if errors:
                return {"errors": errors}

            msg, code = self._update_device_in_catalog(newDevice)
            if code != 200:
                cherrypy.response.status = code
                return msg
            cherrypy.response.status = 201
            return "Device added successfully"

        else:
            return "Invalid path. Use /houses or /devices to add new items."

    @cherrypy.tools.json_out()
    @cherrypy.tools.json_in()
    def PUT(self, *uri, **params):
        if len(uri) == 0:
            return "Use /houses or /devices to update existing items."
        path = uri[0].lower()

        if path == "houses":
            body = cherrypy.request.json
            errors = self.validate_payload(body, HOUSE_SCHEMA)
            if errors:
                return {"errors": errors}

            houseID = str(body.get("houseID") or params.get("houseID"))
            if not houseID:
                return "No houseID specified to update."
            house = self.get_house_by_id(houseID)
            if not house:
                return f"No house found with ID {houseID}", 404
            for k, v in body.items():
                house[k] = v
            house["lastUpdate"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.catalog["lastUpdate"] = house["lastUpdate"]
            print(f"Updated house {houseID} with data: {body}")
            self.save_catalog()
            self.deviceGetter()
            return "House updated successfully", 200

        elif path == "devices":
            updatedDevice = cherrypy.request.json
            errors = self.validate_payload(updatedDevice, DEVICE_SCHEMA)
            if errors:
                return {"errors": errors}

            msg, code = self._update_device_in_catalog(updatedDevice)
            cherrypy.response.status = code
            return "Device updated successfully" if code == 200 else msg

        else:
            return "Invalid path. Use /houses or /devices to update items."

    @cherrypy.tools.json_out()
    @cherrypy.tools.json_in()
    def DELETE(self, *uri, **params):
        if len(uri) == 0:
            return "To delete: /houses?houseID=... or /devices?deviceID=..."
        path = uri[0].lower()

        if path == "devices":
            deviceID = params.get("deviceID")
            if not deviceID:
                return "Missing deviceID parameter."
            removed = False
            for house in self.housesList:
                for floor in house.get("floors", []):
                    for unit in floor.get("units", []):
                        original = len(unit["devicesList"])
                        unit["devicesList"] = [
                            d for d in unit["devicesList"]
                            if str(d["deviceID"]) != str(deviceID)
                        ]
                        if len(unit["devicesList"]) < original:
                            removed = True
            if removed:
                self.catalog["lastUpdate"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.save_catalog()
                self.deviceGetter()
                return f"Device {deviceID} removed successfully.", 200
            else:
                return f"Device {deviceID} not found.", 404

    def deviceGetter(self):
        self.devices = []
        for house in self.housesList:
            for floorObj in house.get("floors", []):
                for unitObj in floorObj.get("units", []):
                    for device in unitObj["devicesList"]:
                        self.devices.append(device)

    def get_house_by_id(self, houseID):
        return next((h for h in self.housesList if str(h["houseID"]) == str(houseID)), None)

    def get_floor_by_id(self, house, floorID):
        for f in house.get("floors", []):
            if str(f["floorID"]) == str(floorID):
                return f
        return None

    def get_unit_by_id(self, floorObj, unitID):
        for u in floorObj.get("units", []):
            if str(u["unitID"]) == str(unitID):
                return u
        return None

    def get_device_by_id(self, deviceID):
        for d in self.devices:
            if str(d["deviceID"]) == str(deviceID):
                return d
        return None

    def periodic_cleanup(self):
        # This method is now called by CherryPy Monitor
        THRESHOLD = 1
        now = datetime.datetime.now()
        cutoff = now - datetime.timedelta(hours=THRESHOLD)
        for house in self.housesList:
            for floorObj in house.get("floors", []):
                for unitObj in floorObj.get("units", []):
                    unitObj["devicesList"] = [
                        dev for dev in unitObj["devicesList"]
                        if datetime.datetime.strptime(
                            dev.get('lastUpdate', '1970-01-01 00:00:00'),
                            "%Y-%m-%d %H:%M:%S"
                        ) >= cutoff
                    ]
        self.catalog["lastUpdate"] = now.strftime("%Y-%m-%d %H:%M:%S")
        self.save_catalog()
        self.deviceGetter()
        # No need to reschedule, Monitor handles it

    def save_catalog(self):
        try:
            script_dir = os.path.dirname(__file__)
            catalog_file_path = os.path.join(script_dir, 'catalog.json')

            # Atomic save: write to temp file then rename
            with tempfile.NamedTemporaryFile('w', dir=script_dir, delete=False) as tf:
                json.dump(self.catalog, tf, indent=4)
                temp_name = tf.name

            os.replace(temp_name, catalog_file_path)
            print(f"Saving catalog to {catalog_file_path}")
        except Exception as e:
            print(f"Error saving catalog: {e}")
            if 'temp_name' in locals() and os.path.exists(temp_name):
                os.remove(temp_name)

if __name__ == "__main__":
    conf = {
        "/": {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            'tools.sessions.on': True
        }
    }
    cherrypy.config.update({'server.socket_host': '0.0.0.0'})
    webService = WebCatalogThiefDetector('catalog.json')
    cherrypy.tree.mount(webService, '/', conf)
    cherrypy.engine.start()
    try:
        cherrypy.engine.block()
    except KeyboardInterrupt:
        print("Shutting down...")
        cherrypy.engine.stop()
    finally:
        cherrypy.engine.block()

import flask
from flask import Flask, render_template, request, redirect, url_for
import requests
import json
import datetime

# --- App Configuration ---
app = Flask(__name__)
CATALOG_URL = "http://catalog:8080"

# --- Helper Functions ---
def get_catalog_data():
    """Fetches the complete list of houses from the catalog service."""
    try:
        response = requests.get(f"{CATALOG_URL}/houses")
        response.raise_for_status() # Raises an exception for bad status codes
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching catalog data: {e}")
        return [] # Return an empty list on failure

# --- Main Routes ---
@app.route('/', methods=['GET'])
def admin_panel():
    """Renders the main admin panel page with all current house data."""
    houses = get_catalog_data()
    return render_template('admin.html', houses=houses)

@app.route('/add/house', methods=['POST'])
def add_house():
    """Handles the form submission for adding a new house."""
    try:
        new_house = {
            "houseID": str(request.form['houseID']),
            "houseName": request.form['houseName'],
            "installationDate": datetime.datetime.now().strftime("%Y-%m-%d"),
            "floors": []
        }
        # The catalog service's POST endpoint handles the rest
        requests.post(f"{CATALOG_URL}/houses", json=new_house)
    except Exception as e:
        print(f"Error adding house: {e}")
    return redirect(url_for('admin_panel'))

@app.route('/add/floor', methods=['POST'])
def add_floor():
    """Handles adding a new floor to an existing house."""
    try:
        house_id = request.form['houseID']
        floor_id = request.form['floorID']
        
        # To add a floor, we must get the house, modify it, and PUT it back
        house_res = requests.get(f"{CATALOG_URL}/house/{house_id}")
        house = house_res.json()

        house['floors'].append({"floorID": str(floor_id), "units": []})

        requests.put(f"{CATALOG_URL}/houses", json=house)
    except Exception as e:
        print(f"Error adding floor: {e}")
    return redirect(url_for('admin_panel'))

@app.route('/add/unit', methods=['POST'])
def add_unit():
    """Handles adding a new unit to an existing floor."""
    try:
        house_id = request.form['houseID']
        floor_id = request.form['floorID']
        unit_id = request.form['unitID']

        house_res = requests.get(f"{CATALOG_URL}/house/{house_id}")
        house = house_res.json()

        for floor in house.get('floors', []):
            if str(floor.get('floorID')) == str(floor_id):
                floor['units'].append({
                    "unitID": str(unit_id),
                    "urlSensors": f"http://sensors:8085/raspberry_{house_id}-{floor_id}-{unit_id}",
                    "urlActuators": f"http://actuators:8086/arduino_{house_id}-{floor_id}-{unit_id}",
                    "devicesList": []
                })
                break
        
        requests.put(f"{CATALOG_URL}/houses", json=house)
    except Exception as e:
        print(f"Error adding unit: {e}")
    return redirect(url_for('admin_panel'))


@app.route('/add/device', methods=['POST'])
def add_device():
    """Handles adding a new motion sensor device."""
    try:
        house_id = request.form['houseID']
        floor_id = request.form['floorID']
        unit_id = request.form['unitID']
        
        # This creates a motion sensor with a structure matching your catalog's schema 
        new_device = {
            "deviceID": int(request.form['deviceID']),
            "deviceName": "motion_sensor", # Hardcoded for this example
            "deviceStatus": "No Motion",
            "availableStatuses": ["Detected", "No Motion"],
            "deviceLocation": {
                "houseID": int(house_id), "floorID": int(floor_id), "unitID": int(unit_id)
            },
            "measureType": ["motion"],
            "availableServices": ["MQTT"],
            "servicesDetails": [{
                "serviceType": "MQTT",
                "topic": [f"ThiefDetector/sensors/{house_id}/{floor_id}/{unit_id}/motion_sensor"]
            }]
        }
        
        requests.post(f"{CATALOG_URL}/devices", json=new_device)
    except Exception as e:
        print(f"Error adding device: {e}")
    return redirect(url_for('admin_panel'))


@app.route('/delete/device', methods=['POST'])
def delete_device():
    """Handles deleting a device using its ID."""
    try:
        device_id = request.form['deviceID']
        # The catalog service supports deleting a device via a DELETE request with a parameter
        requests.delete(f"{CATALOG_URL}/devices?deviceID={device_id}")
    except Exception as e:
        print(f"Error deleting device: {e}")
    return redirect(url_for('admin_panel'))

# --- Run the App ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, debug=True)
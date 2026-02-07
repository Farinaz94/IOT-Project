from device_connector_actuator import Device_connector_act
import json
import time
import cherrypy

if __name__ == "__main__":
    settingActFile = "Device_connectors/setting_act.json"

    try:
        with open(settingActFile) as fp:
            settingAct = json.load(fp)
    except Exception as e:
        print(f"Error loading settings from '{settingActFile}': {e}")
        exit(1)

    catalog_url = "http://catalog:8080/"
    baseClientID = settingAct["clientID"]
    DCID_act_dict = settingAct["DCID_dict"]

    deviceConnectorsAct = {}
    for DCID, plantConfig in DCID_act_dict.items():
        DC_name = f"arduino_{DCID}"
        connector = Device_connector_act(
            catalog_url,
            plantConfig,
            baseClientID,
            DCID
        )
        deviceConnectorsAct[DC_name] = connector
        cherrypy.tree.mount(connector, f'/{DC_name}', {
            '/': {
                'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            }
        })
        print(f"Mounted {DC_name} to CherryPy")

    cherrypy.config.update({
        'server.socket_host': '0.0.0.0',
        'server.socket_port': 8086
    })
    
    cherrypy.engine.start()
    print("Actuator service started.")
    cherrypy.engine.block()
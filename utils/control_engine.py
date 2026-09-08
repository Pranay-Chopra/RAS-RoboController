from kivymd.app import MDApp


class ControlProfile:
    """Manages input mappings and serializes profile JSONs."""

    def __init__(self, name="Default ESP32"):
        self.name = name
        # Default fallback mappings: Input ID -> Output Command Template
        self.mappings = {
            "joystick_vector": "JOY:{x},{y}",
            "dpad_up": "MOVE:FORWARD",
            "dpad_down": "MOVE:BACKWARD",
            "dpad_left": "MOVE:LEFT",
            "dpad_right": "MOVE:RIGHT",
            "btn_a": "CMD:ARM",
            "btn_b": "CMD:DISARM",
            "btn_x": "CMD:MODE_AUTO",
            "btn_y": "CMD:MODE_MANUAL",
            "slider_1": "THROTTLE:{val}",
            "slider_2": "AUX1:{val}",
        }

    def get_command(self, input_id, **kwargs):
        """Resolves input event to target string payload."""
        template = self.mappings.get(input_id, "")
        if not template:
            return None
        try:
            return template.format(**kwargs)
        except KeyError:
            return template


class ConnectionManager:
    """Thin dispatcher that forwards sends to the app's live services.

    It intentionally does NOT own WiFiService/BLEService instances. The
    instances on the running MDApp are the ones that hold the real connected
    socket / GATT, so all sends must go through them.
    """

    def send(self, command_str: str):
        print(f"[TX] {command_str.strip()}")
        if not command_str:
            return

        app = MDApp.get_running_app()
        if app is None:
            return

        # Do not append a terminator here; each service is responsible for
        # framing its own payload (wifi appends CRLF, ble appends LF).
        payload = command_str.strip()
        if not payload:
            return

        try:
            if getattr(app, "is_connected", False) and getattr(app, "current_robot", None):
                transport = getattr(app.current_robot, "transport", "").lower()

                if transport == "wifi":
                    if not app.wifi.send(payload):
                        print("[TX Error] WiFi send failed (disconnected).")
                elif transport in ("ble", "bluetooth"):
                    if not app.ble.send_command(payload):
                        print("[TX Error] BLE send failed (disconnected).")
                else:
                    print(f"[TX Error] Unknown transport: {transport}")
            else:
                print("[TX Warn] Not connected to any robot; command dropped.")
        except Exception as e:
            print(f"[TX Error] send failed: {e}")


# Shared Global Hardware Controller Instance
connection_mgr = ConnectionManager()
active_profile = ControlProfile()

import json
import os


class ConnectionSettings:
    """Central, shared store for user-editable connection parameters.

    A single instance of this lives on the app (`app.settings`) and is
    passed by reference into WiFiService and BLEService at construction
    time, and into SettingsDialog when the user opens it. Because it's
    shared by reference, saving a change in the dialog is immediately
    visible to both services on the next connect() call — no extra
    plumbing or callbacks needed.

    Persistence: values are written to a small JSON file in the app's
    user_data_dir (the standard, writable, per-app storage location Kivy
    provides on both Android and desktop) whenever save() is called, and
    read back automatically on construction. Without this, the dialog was
    only ever mutating this object in memory — nothing survived an app
    restart.

    Defaults match the ESP32 example robot: standard Nordic UART Service
    UUIDs for BLE, and 192.168.4.1 on the usual AP-mode candidate ports
    for Wi-Fi.
    """

    DEFAULT_WIFI_IP = "192.168.4.1"
    DEFAULT_WIFI_PORTS = [8888, 8080, 80]

    # Standard Nordic UART Service (NUS) UUIDs.
    # Note: these are the CORRECT standard UUIDs. The previous hardcoded
    # constants in ble.py had a typo in the last UUID segment
    # (...e0a9-e50e24dcca9e instead of ...e9a0-e9b0c5c9b300) which did not
    # match the standard NUS UUIDs, or the ESP32 sketch that implements them.
    DEFAULT_BLE_SERVICE_UUID = "6e400001-b5a3-f393-e9a0-e9b0c5c9b300"
    DEFAULT_BLE_RX_UUID = "6e400002-b5a3-f393-e9a0-e9b0c5c9b300"  # central writes here
    DEFAULT_BLE_TX_UUID = "6e400003-b5a3-f393-e9a0-e9b0c5c9b300"  # central subscribes here

    SETTINGS_FILENAME = "connection_settings.json"

    def __init__(self):
        self.wifi_ip = self.DEFAULT_WIFI_IP
        self.wifi_ports = list(self.DEFAULT_WIFI_PORTS)
        self.ble_service_uuid = self.DEFAULT_BLE_SERVICE_UUID
        self.ble_rx_uuid = self.DEFAULT_BLE_RX_UUID
        self.ble_tx_uuid = self.DEFAULT_BLE_TX_UUID
        # Pull in anything persisted from a previous run, if present.
        # Silently keeps defaults if there's nothing saved yet or the
        # file can't be read — first launch shouldn't error.
        self.load()

    def reset_to_defaults(self):
        self.wifi_ip = self.DEFAULT_WIFI_IP
        self.wifi_ports = list(self.DEFAULT_WIFI_PORTS)
        self.ble_service_uuid = self.DEFAULT_BLE_SERVICE_UUID
        self.ble_rx_uuid = self.DEFAULT_BLE_RX_UUID
        self.ble_tx_uuid = self.DEFAULT_BLE_TX_UUID

    def _settings_path(self):
        """Resolves the JSON file path under the app's user_data_dir.

        user_data_dir is Kivy's standard writable, per-app storage
        location — works out of the box on Android (internal app storage)
        and desktop (a per-user config dir) without needing any extra
        permissions. Falls back to the current working directory if no
        app is running yet (e.g. this class is unit-tested standalone).
        """
        base_dir = "."
        try:
            from kivy.app import App
            app = App.get_running_app()
            if app is not None:
                base_dir = app.user_data_dir
        except Exception:
            pass
        return os.path.join(base_dir, self.SETTINGS_FILENAME)

    def to_dict(self):
        return {
            "wifi_ip": self.wifi_ip,
            "wifi_ports": list(self.wifi_ports),
            "ble_service_uuid": self.ble_service_uuid,
            "ble_rx_uuid": self.ble_rx_uuid,
            "ble_tx_uuid": self.ble_tx_uuid,
        }

    def save(self):
        """Writes current values to disk. Returns True on success."""
        path = self._settings_path()
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w") as f:
                json.dump(self.to_dict(), f, indent=2)
            print(f"[ConnectionSettings] Saved to {path}")
            return True
        except Exception as e:
            print(f"[ConnectionSettings] Failed to save settings: {e}")
            return False

    def load(self):
        """Reads persisted values from disk, if the file exists.

        Each field is validated individually and only applied if it
        looks sane — a corrupted or hand-edited file with one bad field
        shouldn't wipe out the others or crash the app; it just falls
        back to the built-in default for that one field.
        """
        path = self._settings_path()
        if not os.path.exists(path):
            return False

        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[ConnectionSettings] Failed to load settings: {e}")
            return False

        ip = data.get("wifi_ip")
        if isinstance(ip, str) and ip.strip():
            self.wifi_ip = ip.strip()

        ports = data.get("wifi_ports")
        if isinstance(ports, list):
            valid_ports = [p for p in ports if isinstance(p, int) and 0 < p <= 65535]
            if valid_ports:
                self.wifi_ports = valid_ports

        service_uuid = data.get("ble_service_uuid")
        if isinstance(service_uuid, str) and service_uuid.strip():
            self.ble_service_uuid = service_uuid.strip()

        rx_uuid = data.get("ble_rx_uuid")
        if isinstance(rx_uuid, str) and rx_uuid.strip():
            self.ble_rx_uuid = rx_uuid.strip()

        tx_uuid = data.get("ble_tx_uuid")
        if isinstance(tx_uuid, str) and tx_uuid.strip():
            self.ble_tx_uuid = tx_uuid.strip()

        print(f"[ConnectionSettings] Loaded from {path}")
        return True

    @staticmethod
    def parse_ports(raw_text):
        """Parses a comma/semicolon/space separated ports string into an
        ordered list of unique, valid ints. Invalid entries are skipped
        rather than raising, so a stray typo doesn't nuke the whole list.
        """
        ports = []
        for chunk in raw_text.replace(";", ",").replace(" ", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                port = int(chunk)
            except ValueError:
                continue
            if 0 < port <= 65535 and port not in ports:
                ports.append(port)
        return ports

    @staticmethod
    def format_ports(ports):
        return ", ".join(str(p) for p in ports)

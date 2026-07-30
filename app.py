import threading
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.utils import platform
from kivymd.app import MDApp
from kivymd.uix.screenmanager import MDScreenManager

from screens.home import HomeScreen
from screens.about import AboutScreen
from services.ble import BLEService
from services.camera import CameraService
from services.storage import StorageService
from services.wifi import WiFiService


class RoboController(MDApp):
    selected_robot = None
    current_robot = None
    is_connected = False

    def build(self):
        # Configure KivyMD Theme
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Gold"  # KivyMD 2.0 palette name

        # Initialize core services
        self.wifi = WiFiService()
        self.ble = BLEService()
        self.camera = CameraService()
        self.storage = StorageService()

        # Load KV layout
        Builder.load_file("kv/home.kv")
        Builder.load_file("kv/about.kv")

        # Screen Manager setup
        self.sm = MDScreenManager()
        self.sm.add_widget(HomeScreen(name="home"))
        self.sm.add_widget(AboutScreen(name="about"))

        return self.sm

    def on_start(self):
        """Request permissions after the Kivy window is rendered."""
        # if platform == "android":
        self.request_android_permissions()

    def request_android_permissions(self):
        """Dynamic runtime permissions for Wi-Fi, BLE, and Location."""
        try:
            from android.permissions import Permission, request_permissions

            permissions = [
                Permission.INTERNET,
                Permission.ACCESS_NETWORK_STATE,
                Permission.ACCESS_WIFI_STATE,
                Permission.CHANGE_WIFI_STATE,
                Permission.ACCESS_FINE_LOCATION,
                Permission.ACCESS_COARSE_LOCATION,
                Permission.BLUETOOTH,
                Permission.BLUETOOTH_ADMIN,
                Permission.BLUETOOTH_SCAN,
                Permission.BLUETOOTH_CONNECT,
            ]
            request_permissions(permissions)
        except Exception as e:
            print(f"[App] Permission request error: {e}")

    def scan(self, on_complete):
        """
        Triggers non-blocking scans for both Wi-Fi and BLE.
        `on_complete` receives the merged list of found Robot objects.
        """
        combined_results = []
        scans_completed = 0
        lock = threading.Lock()

        def handle_partial_results(results):
            nonlocal scans_completed
            with lock:
                combined_results.extend(results)
                scans_completed += 1

                # Once both WiFi and BLE scans report back
                if scans_completed == 2:
                    # Safely pass back to Kivy UI thread
                    Clock.schedule_once(
                        lambda dt: on_complete(combined_results), 0
                    )

        # 1. Run Wi-Fi scan in background thread (to prevent UI lag)
        threading.Thread(
            target=lambda: self.wifi.scan(callback=handle_partial_results),
            daemon=True,
        ).start()

        # 2. Run BLE scan asynchronously
        self.ble.scan(on_complete_callback=handle_partial_results)

    def connect(self, robot, password=None, callback=None):
        """
        Wi-Fi connects synchronously and returns True/False immediately.
        BLE is asynchronous: this call kicks off the GATT sequence and
        returns None right away. The real result arrives later through
        `callback` (and mirrored onto self.is_connected/current_robot),
        which is what HomeScreen's polling thread and _ble_status_callback
        are actually watching.
        """
        if robot.transport == "wifi":
            success = self.wifi.connect(robot, password)

            if success:
                robot.connected = True
                self.selected_robot = robot
                self.current_robot = robot
                self.is_connected = True

            if callback:
                callback(success)

            return success

        # BLE path
        def _on_ble_result(connected, status_code=0):
            if connected:
                robot.connected = True
                self.selected_robot = robot
                self.current_robot = robot
                self.is_connected = True
            else:
                self.is_connected = False

            if callback:
                callback(connected, status_code)

        self.ble.connect(robot, on_result=_on_ble_result)
        return None

    def disconnect(self):
        if self.selected_robot:
            self.selected_robot.connected = False

        self.wifi.disconnect()
        self.ble.disconnect()

        self.selected_robot = None
        self.current_robot = None
        self.is_connected = False


if __name__ == "__main__":
    RoboController().run()

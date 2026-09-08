from utils.log_capture import log_capture
log_capture.install()

import threading

from jnius import autoclass
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.utils import platform
from kivymd.app import MDApp
from kivymd.uix.screenmanager import MDScreenManager

from screens.about import AboutScreen
from screens.home import HomeScreen
from screens.help_screen import HelpScreen
from screens.announcements import AnnouncementsScreen
from screens.settings import SettingsScreen
from screens.telemetry import TelemetryScreen
from screens.hud_controls import HUDControlsScreen
from screens.quiz import QuizScreen
from models.settings import ConnectionSettings
from services.ble import BLEService
from services.storage import StorageService
from services.wifi import WiFiService


class RoboController(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.selected_robot = None
        self.current_robot = None
        self.is_connected = False
        self.wifi = None
        self.ble = None
        self.storage = None
        self.sm = None
        # Shared by reference into WiFiService/BLEService (below) and into
        # SettingsScreen when the user navigates there — saving there
        # mutates this same object, so both services pick up the new
        # values on their next connect() call with no extra wiring.
        self.settings = ConnectionSettings()

    def build(self):
        # Without this, Android's soft keyboard just overlays the window
        # instead of the layout adjusting for it. That's almost certainly
        # why the settings dialog's SAVE/CANCEL buttons became unreachable
        # while a text field was focused — the keyboard was drawn on top of
        # them, and taps on the covered area don't reach the widgets under
        # the keyboard OR count as "tap outside the dialog" for dismissal.
        # "below_target" pans the window just enough to keep the focused
        # input visible above the keyboard.
        Window.softinput_mode = "below_target"

        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Amber"
        self.theme_cls.primary_hue = "500"

        self.wifi = WiFiService(settings=self.settings)
        self.ble = BLEService(settings=self.settings)
        self.storage = StorageService()

        Builder.load_file("kv/home.kv")
        Builder.load_file("kv/about.kv")
        Builder.load_file("kv/telemetry.kv")
        Builder.load_file("kv/hud_controls.kv")
        Builder.load_file("kv/settings.kv")
        Builder.load_file("kv/help.kv")
        Builder.load_file("kv/announcements.kv")
        Builder.load_file("kv/quiz.kv")

        self.sm = MDScreenManager()
        self.sm.add_widget(HomeScreen(name="home"))
        self.sm.add_widget(AboutScreen(name="about"))
        self.sm.add_widget(TelemetryScreen(name="serial"))
        self.sm.add_widget(HUDControlsScreen(name="controls"))
        self.sm.add_widget(SettingsScreen(name="settings"))
        self.sm.add_widget(HelpScreen(name="help"))
        self.sm.add_widget(AnnouncementsScreen(name="announcements"))
        self.sm.add_widget(QuizScreen(name="quiz"))

        return self.sm

    def on_start(self):
        self.request_android_permissions()

    def request_android_permissions(self):
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

    def open_link(self, url):
        """Opens a URL (or mailto: link) in whatever app the user has
        set as the default handler for it (browser, email client, the
        Instagram/LinkedIn app if installed, etc.), via a standard
        Android ACTION_VIEW intent. Callable from any kv file as
        app.open_link(url) -- put here rather than on a specific screen
        so it isn't tied to one screen's widget tree.
        """
        if not url:
            return
        try:
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            activity.startActivity(intent)
        except Exception as e:
            print(f"[App] Failed to open link '{url}': {e}")

    def scan(self, on_complete):
        combined_results = []
        scans_completed = 0
        lock = threading.Lock()

        def handle_partial_results(results):
            nonlocal scans_completed
            with lock:
                combined_results.extend(results)
                scans_completed += 1

                if scans_completed == 2:
                    Clock.schedule_once(
                        lambda dt: on_complete(combined_results), 0
                    )

        threading.Thread(
            target=lambda: self.wifi.scan(callback=handle_partial_results),
            daemon=True,
        ).start()

        self.ble.scan(on_complete_callback=handle_partial_results)

    def connect(self, robot, password=None, callback=None):
        """Wi-Fi connects and starts RX listener thread; BLE connects via GATT."""
        if robot.transport == "wifi":
            def _wifi_task():
                success = self.wifi.connect(robot, password)

                if success:
                    robot.connected = True
                    self.selected_robot = robot
                    self.current_robot = robot

                    # Start RX listener BEFORE marking connected
                    try:
                        telemetry_screen = self.sm.get_screen("serial")
                        self.wifi.start_rx_loop(telemetry_screen.on_network_data)
                    except Exception as err:
                        print(f"[App] Failed to bind RX listener to TelemetryScreen: {err}")

                    # Now safe to mark connected
                    self.is_connected = True

                if callback:
                    Clock.schedule_once(lambda dt: callback(success), 0)

            threading.Thread(target=_wifi_task, daemon=True).start()
            return None

        if robot.transport == "ble":
            def _on_ble_result(connected, status_code=0):
                if connected:
                    robot.connected = True
                    self.selected_robot = robot
                    self.current_robot = robot

                    try:
                        telemetry_screen = self.sm.get_screen("serial")
                        self.ble.on_data_received = telemetry_screen.on_network_data
                    except Exception as err:
                        print(f"[App] Failed to bind BLE listener: {err}")

                    self.is_connected = True
                else:
                    self.is_connected = False

                if callback:
                    callback(connected, status_code)

            self.ble.connect(robot, on_result=_on_ble_result)
            return None

    def send_command(self, cmd_str):
        """Unified transmission interface across active protocol."""
        if not self.is_connected or not self.current_robot:
            return False

        if self.current_robot.transport == "wifi":
            return self.wifi.send(cmd_str)
        elif self.current_robot.transport == "ble":
            return self.ble.send_command(cmd_str)
        return False

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

import threading
import time
from kivy.clock import Clock
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    StringProperty,
)
from kivymd.app import MDApp
from kivymd.uix.list import (
    MDListItem,
    MDListItemHeadlineText,
    MDListItemSupportingText,
)
from kivymd.uix.screen import MDScreen

from dialogs.connect_dialog import ConnectDialog


class HomeScreen(MDScreen):
    connection_status = StringProperty("Not Connected")
    status_icon = StringProperty("wifi-off")

    connected = BooleanProperty(False)
    scanning = BooleanProperty(False)

    robots = ListProperty([])
    _pending_robot = None
    _ble_timeout_ev = None

    @property
    def app(self):
        return MDApp.get_running_app()

    def switch_screen(self, screen_name):
        """Switches the app root screen manager view from the hamburger menu."""
        if hasattr(self.app, "root") and self.app.root:
            if hasattr(self.app.root, "current"):
                self.app.root.current = screen_name
            elif hasattr(self.app.root, "has_screen") and self.app.root.has_screen(screen_name):
                self.app.root.current = screen_name
            else:
                print(f"[HomeScreen] Screen '{screen_name}' not found on app root.")

    def on_enter(self):
        print("[HomeScreen] Loaded")
        try:
            self.app.bind(on_resume=self._on_app_resume)
        except Exception as e:
            print(f"[HomeScreen] Failed to bind on_resume: {e}")

    def _on_app_resume(self, *args):
        """Triggered when PythonActivity resumes from the background."""

        def _check_binding(dt):
            if self.connected:
                return

            is_bound = getattr(self.app, "is_connected", False) or getattr(
                self.app, "current_robot", None
            )
            robot = getattr(
                self.app, "current_robot", None
            ) or self._pending_robot

            if is_bound and robot:
                print(
                    f"[HomeScreen] Connection recovered on resume for {robot.name}"
                )
                self._update_connection(robot)

        Clock.schedule_once(_check_binding, 0.5)

    def scan(self):
        print("[HomeScreen] Starting device scan...")
        self.scanning = True
        self.status_icon = "radar"
        self.connection_status = "Scanning for robots..."

        self.robots.clear()
        self.ids.robot_container.clear_widgets()

        self.app.scan(self.scan_complete)

    def scan_complete(self, new_robots):
        """Receives scan results from app.scan() and updates UI on the main thread."""

        def _update_ui(dt):
            print(f"[HomeScreen] Scan received: {new_robots}")
            self.populate_list(new_robots)
            self._render_robot_list()
            self.scanning = False

            if not self.connected:
                if self.robots:
                    self.connection_status = (
                        f"Found {len(self.robots)} device(s)"
                    )
                    self.status_icon = "robot-happy-outline"
                else:
                    self.connection_status = "No devices found"
                    self.status_icon = "wifi-off"

        Clock.schedule_once(_update_ui, 0)

    def _get_intensity(self, robot):
        """Helper to safely extract RSSI/intensity for sorting."""
        return getattr(robot, "rssi", getattr(robot, "intensity", -999))

    def populate_list(self, new_robots):
        """Updates self.robots without duplicates and sorts by RSSI descending."""
        robot_map = {
            (r.name, getattr(r, "transport", "unknown")): r for r in self.robots
        }

        for robot in new_robots:
            key = (robot.name, getattr(robot, "transport", "unknown"))
            if key in robot_map:
                existing = robot_map[key]
                new_rssi = self._get_intensity(robot)
                if hasattr(existing, "rssi"):
                    existing.rssi = new_rssi
                elif hasattr(existing, "intensity"):
                    existing.intensity = new_rssi
            else:
                self.robots.append(robot)
                robot_map[key] = robot

        self.robots.sort(key=self._get_intensity, reverse=True)

    def _render_robot_list(self):
        """Rebuilds the MDListItem widgets from self.robots cleanly."""
        self.ids.robot_container.clear_widgets()

        for robot in self.robots:
            item = MDListItem()
            item.add_widget(MDListItemHeadlineText(text=robot.name))

            transport_text = getattr(robot, "transport", "WIFI").upper()
            rssi = getattr(robot, "rssi", getattr(robot, "intensity", None))

            if rssi is not None and rssi != -999:
                supporting_text = f"{transport_text}  •  {rssi} dBm"
            else:
                supporting_text = transport_text

            item.add_widget(MDListItemSupportingText(text=supporting_text))

            # Use factory callback to prevent lambda late-binding issues
            item.bind(on_release=self._create_connect_callback(robot))
            self.ids.robot_container.add_widget(item)

    def _create_connect_callback(self, robot):
        """Creates an explicit click handler for each list item."""
        def callback(instance):
            self.connect(robot)
        return callback

    def connect(self, robot):
        transport = getattr(robot, "transport", "wifi").lower()

        if transport == "wifi":
            ConnectDialog(
                robot=robot,
                callback=self._connect_wifi,
            ).open()
        elif transport in ["ble", "bluetooth"]:
            self._connect_ble(robot)

    def _connect_wifi(self, robot, password):
        self.connection_status = f"Connecting to {robot.name}..."
        self.status_icon = "wifi-sync"
        self._pending_robot = robot

        def _worker():
            success = self.app.connect(robot, password)

            def _finish_connect(dt):
                if success:
                    self._update_connection(robot)
                else:
                    is_bound = getattr(self.app, "is_connected", False)
                    if is_bound:
                        self._update_connection(robot)
                    else:
                        self.connected = False
                        self.connection_status = "Wi-Fi Connection Failed"
                        self.status_icon = "wifi-alert"

            Clock.schedule_once(_finish_connect, 0)

        threading.Thread(target=_worker, daemon=True).start()

    def _connect_ble(self, robot):
        """Handles BLE connection asynchronously with callback safety, active polling, and a 10s fallback timeout."""
        self.connection_status = f"Connecting BLE: {robot.name}..."
        self.status_icon = "bluetooth-sync"
        self._pending_robot = robot

        if self._ble_timeout_ev:
            self._ble_timeout_ev.cancel()

        # 1. Asynchronous JNI Callback
        def _ble_status_callback(is_connected, status_code=0):
            if self._ble_timeout_ev:
                self._ble_timeout_ev.cancel()

            def _update_ble_ui(dt):
                if is_connected:
                    print(f"[HomeScreen] Async BLE connected to {robot.name}")
                    self._update_connection(robot)
                else:
                    print(f"[HomeScreen] Async BLE failed/disconnected (code: {status_code})")
                    self.connected = False
                    self._pending_robot = None
                    self.connection_status = f"BLE Connection Failed ({status_code})"
                    self.status_icon = "bluetooth-off"

            Clock.schedule_once(_update_ble_ui, 0)

        # 2. Fallback Safety Timeout
        def _on_ble_timeout(dt):
            print("[HomeScreen] BLE connection timed out waiting for GATT callback.")
            self.connected = False
            self._pending_robot = None
            self.connection_status = "BLE Connection Timed Out"
            self.status_icon = "bluetooth-off"

        self._ble_timeout_ev = Clock.schedule_once(_on_ble_timeout, 10.0)

        # 3. Active Polling Thread (Catches backend state if JNI callback drops)
        def _poll_ble_connection():
            timeout = 10.0
            poll_interval = 0.2
            elapsed = 0.0

            while elapsed < timeout:
                if self.connected:
                    return  # Already resolved by callback

                is_connected = getattr(self.app, "is_connected", False)
                curr_robot = getattr(self.app, "current_robot", None)

                if is_connected or (curr_robot and curr_robot.name == robot.name):
                    print(f"[HomeScreen] Polling detected BLE connection to {robot.name}")
                    if self._ble_timeout_ev:
                        self._ble_timeout_ev.cancel()
                    Clock.schedule_once(lambda dt: self._update_connection(robot), 0)
                    return

                time.sleep(poll_interval)
                elapsed += poll_interval

        threading.Thread(target=_poll_ble_connection, daemon=True).start()

        # 4. Attach callback handler to app instance and invoke connect
        if hasattr(self.app, "ble_callback"):
            self.app.ble_callback = _ble_status_callback

        self.app.connect(robot, callback=_ble_status_callback)

    def _update_connection(self, robot):
        def _apply(dt):
            self.connected = True
            self.connection_status = f"Connected: {robot.name}"
            self._pending_robot = None

            if self._ble_timeout_ev:
                self._ble_timeout_ev.cancel()

            transport = getattr(robot, "transport", "wifi").lower()
            if transport in ["ble", "bluetooth"]:
                self.status_icon = "bluetooth-connect"
            else:
                self.status_icon = "wifi-check"

        Clock.schedule_once(_apply, 0)

    def disconnect(self):
        transport = "wifi"
        if hasattr(self.app, "current_robot") and self.app.current_robot:
            transport = getattr(self.app.current_robot, "transport", "wifi").lower()

        if self._ble_timeout_ev:
            self._ble_timeout_ev.cancel()

        self.app.disconnect()
        self.connected = False
        self._pending_robot = None
        self.connection_status = "Disconnected"

        if transport in ["ble", "bluetooth"]:
            self.status_icon = "bluetooth-off"
        else:
            self.status_icon = "wifi-off"

    def refresh(self):
        pass

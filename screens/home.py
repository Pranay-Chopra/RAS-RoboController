import threading
from kivy.clock import Clock
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    StringProperty,
)
from kivymd.app import MDApp
from kivymd.uix.list import MDListItem, MDListItemHeadlineText, MDListItemSupportingText
from kivymd.uix.screen import MDScreen

from dialogs.connect_dialog import ConnectDialog


class HomeScreen(MDScreen):
    connection_status = StringProperty("Not Connected")
    status_icon = StringProperty("wifi-off")

    connected = BooleanProperty(False)
    scanning = BooleanProperty(False)

    robots = ListProperty([])
    _pending_robot = None

    @property
    def app(self):
        return MDApp.get_running_app()

    def on_enter(self):
        print("[HomeScreen] Loaded")
        try:
            self.app.bind(on_resume=self._on_app_resume)
        except Exception as e:
            print(f"[HomeScreen] Failed to bind on_resume: {e}")

    def _on_app_resume(self, *args):
        """
        Triggered when PythonActivity resumes from the background.
        Checks if Android finished binding to the AP after the system dialog closed.
        """
        def _check_binding(dt):
            if self.connected:
                return

            is_bound = getattr(self.app, "is_connected", False) or getattr(
                self.app, "current_robot", None
            )
            robot = getattr(self.app, "current_robot", None) or self._pending_robot

            if is_bound and robot:
                print(f"[HomeScreen] Connection recovered on resume for {robot.name}")
                self._update_connection(robot)

        Clock.schedule_once(_check_binding, 0.5)

    def scan(self):
        print("[HomeScreen] Starting device scan...")
        self.scanning = True
        self.status_icon = "radar"
        self.connection_status = "Scanning for robots..."

        # Clear existing scanned robots before starting a new scan sequence
        self.robots.clear()
        self.ids.robot_container.clear_widgets()

        self.app.scan(self.scan_complete)

    def scan_complete(self, new_robots):
        """
        Receives scan results from app.scan() and updates self.robots.
        Ensures thread safety and UI rendering on the main thread.
        """
        def _update_ui(dt):
            print(f"[HomeScreen] Scan received: {new_robots}")
            self.populate_list(new_robots)
            self._render_robot_list()
            self.scanning = False

            if not self.connected:
                if self.robots:
                    self.connection_status = f"Found {len(self.robots)} device(s)"
                    self.status_icon = "robot-happy-outline"
                else:
                    self.connection_status = "No devices found"
                    self.status_icon = "wifi-off"

        Clock.schedule_once(_update_ui, 0)

    def _get_intensity(self, robot):
        """Helper to safely extract RSSI/intensity for sorting."""
        return getattr(robot, "rssi", getattr(robot, "intensity", -999))

    def populate_list(self, new_robots):
        """
        Updates self.robots without duplicates and sorts by signal intensity (RSSI) descending.
        Handles both Wi-Fi and BLE devices.
        """
        # Map existing robots by (name, transport) for fast lookup & update
        robot_map = {
            (r.name, getattr(r, "transport", "unknown")): r
            for r in self.robots
        }

        for robot in new_robots:
            key = (robot.name, getattr(robot, "transport", "unknown"))
            if key in robot_map:
                # Update RSSI/intensity on existing entry
                existing = robot_map[key]
                new_rssi = self._get_intensity(robot)
                if hasattr(existing, "rssi"):
                    existing.rssi = new_rssi
                elif hasattr(existing, "intensity"):
                    existing.intensity = new_rssi
            else:
                self.robots.append(robot)
                robot_map[key] = robot

        # Sort all devices by signal strength descending (highest/strongest RSSI first)
        self.robots.sort(key=self._get_intensity, reverse=True)

    def _render_robot_list(self):
        """Rebuilds the MDListItem widgets in robot_container from self.robots sorted by signal strength."""
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
            item.bind(on_release=lambda x, r=robot: self.connect(r))
            self.ids.robot_container.add_widget(item)

    def connect(self, robot):
        if robot.transport == "wifi":
            ConnectDialog(
                robot=robot,
                callback=self._connect_wifi,
            ).open()
            return

        success = self.app.connect(robot)
        if success:
            self._update_connection(robot)

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
                        self.connection_status = "Connection Failed"
                        self.status_icon = "wifi-alert"

            Clock.schedule_once(_finish_connect, 0)

        threading.Thread(target=_worker, daemon=True).start()

    def _update_connection(self, robot):
        self.connected = True
        self.connection_status = f"Connected: {robot.name}"
        self._pending_robot = None

        if getattr(robot, "transport", "wifi") == "wifi":
            self.status_icon = "wifi-check"
        else:
            self.status_icon = "bluetooth-connect"

    def disconnect(self):
        self.app.disconnect()
        self.connected = False
        self._pending_robot = None
        self.connection_status = "Not Connected"
        self.status_icon = "wifi-off"

    def refresh(self):
        pass

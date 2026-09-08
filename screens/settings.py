from kivymd.app import MDApp
from kivymd.toast import toast
from kivymd.uix.screen import MDScreen

from models.settings import ConnectionSettings


class SettingsScreen(MDScreen):
    """Wi-Fi IP/ports + BLE UUID settings, as a regular screen instead of
    a modal dialog. Navigated to/from exactly like every other screen in
    the app (HomeScreen.switch_screen / this screen's own switch_screen),
    which sidesteps every MDDialog-specific touch-routing/layout quirk
    that made the dialog version unreliable.

    Reads/writes app.settings directly (a ConnectionSettings shared by
    reference with WiFiService and BLEService), so a save here applies on
    the very next connect() call with no extra plumbing.
    """

    @property
    def app(self):
        return MDApp.get_running_app()

    def switch_screen(self, screen_name: str) -> None:
        """Dispatches screen transition requests, matching the pattern
        used by every other screen in the app."""
        if hasattr(self.app, "root") and self.app.root:
            if hasattr(self.app.root, "current"):
                self.app.root.current = screen_name

    def on_pre_enter(self, *args):
        """Refreshes the fields from the live settings object every time
        this screen is shown — covers both the first-ever display (after
        ConnectionSettings.load() pulled in a persisted value) and
        returning here after a Reset/Save on a previous visit."""
        self._populate_fields()

    def _populate_fields(self):
        settings = getattr(self.app, "settings", None)
        if settings is None:
            print("[SettingsScreen] app.settings is missing — cannot populate fields.")
            return

        self.ids.wifi_ip_field.text = settings.wifi_ip
        self.ids.wifi_ports_field.text = ConnectionSettings.format_ports(settings.wifi_ports)
        self.ids.ble_service_field.text = settings.ble_service_uuid
        self.ids.ble_rx_field.text = settings.ble_rx_uuid
        self.ids.ble_tx_field.text = settings.ble_tx_uuid

    def reset_defaults(self):
        print("[SettingsScreen] RESET DEFAULTS pressed.")
        settings = getattr(self.app, "settings", None)
        if settings is None:
            toast("No settings object available")
            return

        settings.reset_to_defaults()
        settings.save()
        self._populate_fields()
        toast("Restored default settings")

    def save_settings(self):
        print("[SettingsScreen] SAVE pressed.")
        settings = getattr(self.app, "settings", None)
        if settings is None:
            toast("No settings object available")
            return

        ip = self.ids.wifi_ip_field.text.strip()
        ports_raw = self.ids.wifi_ports_field.text.strip()
        service_uuid = self.ids.ble_service_field.text.strip()
        rx_uuid = self.ids.ble_rx_field.text.strip()
        tx_uuid = self.ids.ble_tx_field.text.strip()

        if not ip:
            toast("IP address can't be empty")
            return

        ports = ConnectionSettings.parse_ports(ports_raw)
        if not ports:
            toast("Enter at least one valid port (1-65535)")
            return

        if not (service_uuid and rx_uuid and tx_uuid):
            toast("All three BLE UUIDs are required")
            return

        settings.wifi_ip = ip
        settings.wifi_ports = ports
        settings.ble_service_uuid = service_uuid
        settings.ble_rx_uuid = rx_uuid
        settings.ble_tx_uuid = tx_uuid

        print(f"[SettingsScreen] Applied to settings id={id(settings)}: {settings.to_dict()}")

        if settings.save():
            toast("Settings saved")
        else:
            toast("Saved in-memory, but writing to disk failed — check logs")

        self.switch_screen("home")

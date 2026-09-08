from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen


class HelpScreen(MDScreen):
    """Static reference/documentation screen: how to connect over Wi-Fi
    and BLE, how the connection settings map to the ESP32 sketch, how
    each HUD control type works, and how commands are framed and parsed
    on the ESP32 side. No dynamic state -- just navigation.
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

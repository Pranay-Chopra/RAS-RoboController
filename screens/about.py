from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen


class AboutScreen(MDScreen):
    """About screen component providing app overview and system details."""

    def switch_screen(self, screen_name: str) -> None:
        """Dispatches screen transition requests triggered from the navigation drawer.

        Args:
            screen_name (str): Target screen identifier matching the ScreenManager layout.
        """
        app = MDApp.get_running_app()
        if hasattr(app, "root") and app.root:
            if hasattr(app.root, "current"):
                app.root.current = screen_name
            elif hasattr(app.root, "has_screen") and app.root.has_screen(screen_name):
                app.root.current = screen_name
            else:
                print(f"[AboutScreen] Screen '{screen_name}' not found on app root.")

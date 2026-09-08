import functools

from kivy.clock import Clock
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog

try:
    from .theme import BLACK, GOLD, MUTED_GRAY
except ImportError:
    GOLD = (0.83, 0.68, 0.21, 1)
    BLACK = (0, 0, 0, 1)
    MUTED_GRAY = (0.53, 0.53, 0.53, 1)


@functools.lru_cache(maxsize=1)
def _settings_runnable_class():
    from jnius import PythonJavaClass, autoclass, java_method

    class SettingsRunnable(PythonJavaClass):
        __javainterfaces__ = ["java/lang/Runnable"]

        def __init__(self, activity):
            super().__init__()
            self.activity = activity

        @java_method("()V")
        def run(self):
            Intent = autoclass("android.content.Intent")

            intent = Intent(
                "android.settings.LOCATION_SOURCE_SETTINGS"
            )

            self.activity.startActivity(intent)

    return SettingsRunnable


class LocationDialog:
    def __init__(self, on_enable_callback=None):
        self.on_enable_callback = on_enable_callback

        self.dialog = MDDialog(
            title="Enable Location",
            text=(
                "Location Services (GPS) are currently disabled.\n\n"
                "Android requires Location Services to be enabled "
                "before apps can scan for nearby Wi-Fi networks "
                "and Bluetooth devices."
            ),
            buttons=[
                MDFlatButton(
                    text="IGNORE",
                    theme_text_color="Custom",
                    text_color=MUTED_GRAY,
                    on_release=self.dismiss,
                ),
                MDRaisedButton(
                    text="OPEN SETTINGS",
                    md_bg_color=GOLD,
                    text_color=BLACK,
                    on_release=self.open_settings,
                ),
            ],
        )

    def open(self):
        self.dialog.open()

    def dismiss(self, *args):
        print("Dismissing location dialog")
        self.dialog.dismiss()

    def open_settings(self, *args):
        print("Opening Android settings")

        self.dialog.dismiss()

        Clock.schedule_once(self._launch_settings, 0.2)

    def _launch_settings(self, dt):
        try:
            from jnius import autoclass

            PythonActivity = autoclass(
                "org.kivy.android.PythonActivity"
            )

            activity = PythonActivity.mActivity

            if activity is None:
                print("Activity is None")
                return

            runnable = _settings_runnable_class()(activity)
            activity.runOnUiThread(runnable)

            if self.on_enable_callback:
                Clock.schedule_once(
                    lambda dt: self.on_enable_callback(), 0.5
                )

        except Exception as e:
            import traceback

            print("Failed to launch settings:")
            traceback.print_exc()

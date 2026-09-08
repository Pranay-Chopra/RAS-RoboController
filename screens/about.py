from datetime import datetime

from jnius import autoclass
from android import activity
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.properties import StringProperty
from kivy.uix.label import Label
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.toast import toast

from utils.log_capture import log_capture
from widgets.circular_image import CircularImage  # noqa: F401  (registers CircularImage for kv)

# Register the monospace face used by the log view under a stable name.
# MDLabel forces font_name back to the theme's proportional Roboto on
# every theme refresh, so the log lines use a plain Kivy Label with this
# font instead -- RobotoMono ships inside Kivy's own data/fonts dir.
_LOG_FONT = "Roboto"
try:
    LabelBase.register(
        name="RoboMono", fn_regular="data/fonts/RobotoMono-Regular.ttf"
    )
    _LOG_FONT = "RoboMono"
except Exception as e:  # pragma: no cover - font just falls back
    print(f"[AboutScreen] Could not register monospace log font: {e}")


class AboutScreen(MDScreen):
    """About screen component providing app overview, system details,
    and a view of captured application logs (exportable for sharing when
    asking for help)."""

    # How many of the most recent captured lines to actually render in
    # the on-screen log view. The full buffer (up to LogCapture.MAX_LINES)
    # is still what gets written out on export -- this is just to keep the
    # on-screen label stack from rendering an unbounded amount of text.
    LIVE_VIEW_LINE_LIMIT = 300

    # The live log view is split across several Labels of at most this
    # many lines each. A single Label rendering the whole buffer can
    # produce a texture taller than the GPU's max texture size, which
    # Kivy then draws as a solid black rectangle -- that's the "logs
    # section sometimes goes black" bug. Keeping each chunk small keeps
    # every individual texture well under that limit.
    _LOG_CHUNK_LINES = 30

    log_text = StringProperty("No logs captured yet.")

    # Arbitrary unique int identifying the log-export
    # startActivityForResult() call, so its on_activity_result callback
    # can tell it apart from any other pending request.
    _EXPORT_LOGS_REQUEST_CODE = 42101

    def switch_screen(self, screen_name: str) -> None:
        """Dispatches screen transition requests triggered from the navigation drawer."""
        app = MDApp.get_running_app()
        if hasattr(app, "root") and app.root:
            if hasattr(app.root, "current"):
                app.root.current = screen_name
            elif hasattr(app.root, "has_screen") and app.root.has_screen(screen_name):
                app.root.current = screen_name
            else:
                print(f"[AboutScreen] Screen '{screen_name}' not found on app root.")

    def on_enter(self):
        self.refresh_logs()

    def refresh_logs(self):
        text = log_capture.get_text(limit=self.LIVE_VIEW_LINE_LIMIT)
        self.log_text = text if text else "No logs captured yet."
        self._render_log_view()

    def _render_log_view(self):
        """Rebuilds the on-screen log view as a stack of small MDLabels
        instead of one giant one -- see _LOG_CHUNK_LINES for why."""
        container = self.ids.get("log_container")
        if container is None:
            return

        container.clear_widgets()
        lines = self.log_text.split("\n")
        for start in range(0, len(lines), self._LOG_CHUNK_LINES):
            block = "\n".join(lines[start:start + self._LOG_CHUNK_LINES])
            container.add_widget(self._make_log_label(block))

    @staticmethod
    def _make_log_label(text):
        lbl = Label(
            text=text,
            font_name=_LOG_FONT,
            font_size="12sp",
            color=(0.75, 0.9, 0.75, 1),
            size_hint_y=None,
            halign="left",
            valign="top",
        )
        lbl.bind(
            width=lambda inst, w: setattr(inst, "text_size", (w, None)),
            texture_size=lambda inst, ts: setattr(inst, "height", ts[1]),
        )
        return lbl

    def clear_logs(self):
        log_capture.clear()
        self.refresh_logs()
        toast("Logs cleared")

    def export_logs(self):
        """Lets the user pick a save location via Android's Storage
        Access Framework and writes the full captured log buffer there
        as plain text. Same ACTION_CREATE_DOCUMENT approach as
        HUDControlsScreen.export_layout() -- no storage permissions or
        manifest/FileProvider setup needed, since the system picker
        itself grants access to whatever content:// location is picked.
        """
        try:
            Intent = autoclass("android.content.Intent")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity_instance = PythonActivity.mActivity

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"robocontroller_log_{timestamp}.txt"

            intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("text/plain")
            intent.putExtra(Intent.EXTRA_TITLE, filename)

            activity.bind(on_activity_result=self._on_export_logs_result)
            activity_instance.startActivityForResult(intent, self._EXPORT_LOGS_REQUEST_CODE)
        except Exception as e:
            toast(f"Could not open export picker: {e}")
            print(f"[AboutScreen Error] export_logs: {e}")

    def _on_export_logs_result(self, requestCode, resultCode, intent):
        if requestCode != self._EXPORT_LOGS_REQUEST_CODE:
            return
        activity.unbind(on_activity_result=self._on_export_logs_result)

        try:
            Activity = autoclass("android.app.Activity")
            if resultCode != Activity.RESULT_OK or intent is None:
                print("[AboutScreen] Log export cancelled.")
                return

            uri = intent.getData()
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            resolver = PythonActivity.mActivity.getContentResolver()

            data_bytes = log_capture.get_text().encode("utf-8")

            output_stream = resolver.openOutputStream(uri)
            output_stream.write(data_bytes)
            output_stream.flush()
            output_stream.close()

            print(f"[AboutScreen] Exported logs to {uri.toString()}")
            Clock.schedule_once(lambda dt: toast("Logs exported"), 0)
        except Exception as e:
            print(f"[AboutScreen Error] _on_export_logs_result: {e}")
            Clock.schedule_once(lambda dt, err=e: toast(f"Export failed: {err}"), 0)

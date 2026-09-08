import queue
import threading
import time

from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.uix.label import Label
from kivymd.app import MDApp
from kivymd.toast import toast
from kivymd.uix.screen import MDScreen

# Monospace face for the console. Registered under a stable name because
# MDLabel resets font_name to the theme's proportional Roboto on every
# theme refresh -- the console uses plain Kivy Labels with this font.
_CONSOLE_FONT = "Roboto"
try:
    LabelBase.register(
        name="RoboMono", fn_regular="data/fonts/RobotoMono-Regular.ttf"
    )
    _CONSOLE_FONT = "RoboMono"
except Exception as e:  # pragma: no cover - font just falls back
    print(f"[TelemetryScreen] Could not register monospace console font: {e}")

try:
    from usbserial4a import get_usb_device
    import serial

    IS_ANDROID = True
except ImportError:
    try:
        import serial
    except ImportError:
        serial = None
    IS_ANDROID = False


class TelemetryScreen(MDScreen):
    # The console is a stack of Labels holding at most _CONSOLE_CHUNK_LINES
    # lines each, capped at _CONSOLE_MAX_CHUNKS. One ever-growing Label
    # eventually produces a texture taller than the GPU max texture size,
    # which Kivy renders as a solid black rectangle -- that's the "serial
    # monitor black box" bug. Small per-chunk textures avoid it.
    _CONSOLE_CHUNK_LINES = 40
    _CONSOLE_MAX_CHUNKS = 12

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.serial_port = None
        self.usb_connected = False
        self.rx_queue = queue.Queue()
        self.stop_threads = False
        print(f"[TelemetryScreen] Initialized. Android: {IS_ANDROID}")

        Clock.schedule_interval(self.process_queue, 0.1)

    def switch_screen(self, screen_name: str) -> None:
        """Dispatches screen transition requests triggered from the navigation drawer."""
        app = MDApp.get_running_app()
        if hasattr(app, "root") and app.root:
            if hasattr(app.root, "current"):
                app.root.current = screen_name

    def toggle_usb(self):
        self.disconnect_usb() if self.usb_connected else self.connect_usb()

    def connect_usb(self):
        if IS_ANDROID:
            device = get_usb_device()
            if not device:
                self.log("[color=#ff3333][ERROR] No USB device found.[/color]")
                toast("No USB Device")
                return
            try:
                self.serial_port = serial.Serial(
                    device.getDeviceName(), 115200, timeout=1
                )
            except Exception as e:
                self.log(f"[color=#ff3333][ERROR] {e}[/color]")
                return
        else:
            self.log("[color=#ff9933][WARN] PC Mode: USB bypassed.[/color]")
            toast("Mock Mode")

        self.usb_connected = True
        self.stop_threads = False
        self.log("[color=#33cc33][SUCCESS] USB Connected.[/color]")

        threading.Thread(target=self._read_usb, daemon=True).start()

    def disconnect_usb(self):
        self.usb_connected = False
        self.stop_threads = True
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.log("[color=#ff9933][INFO] USB Disconnected.[/color]")

    def send(self):
        cmd = self.ids.input_cmd.text.strip()
        if not cmd:
            return

        self.ids.input_cmd.text = ""
        self.log(f"[color=#3399ff][TX][/color] {cmd}")

        app = MDApp.get_running_app()

        # --- Network path (WiFi / BLE) ---
        if getattr(app, "is_connected", False) and app.current_robot:
            try:
                if app.send_command(cmd):
                    return  # success
                self.log("[color=#ff3333][ERROR] Network TX failed[/color]")
            except Exception as e:
                self.log(f"[color=#ff3333][ERROR] Network TX: {e}[/color]")
            return  # don't fall through to USB if we intended network

        # --- USB path ---
        if self.usb_connected and self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(f"{cmd}\r\n".encode("utf-8"))
            except Exception as e:
                self.log(f"[color=#ff3333][ERROR] USB TX: {e}[/color]")
        elif self.usb_connected and not IS_ANDROID:
            self.rx_queue.put(f"Mock Rx: {cmd}")
        else:
            self.log("[color=#ff9933][WARN] Not connected to any robot.[/color]")

    def _read_usb(self):
        while self.usb_connected and not self.stop_threads:
            try:
                if self.serial_port and self.serial_port.in_waiting > 0:
                    data = (
                        self.serial_port.readline()
                        .decode("utf-8", errors="ignore")
                        .strip()
                    )
                    if data:
                        self.rx_queue.put(data)
            except Exception as e:
                self.rx_queue.put(f"[color=#ff3333][ERROR] USB Read: {e}[/color]")
                self.disconnect_usb()
                break
            time.sleep(0.01)

    def on_network_data(self, data):
        """Hook for the main app to push WiFi/BLE data to this terminal."""
        self.rx_queue.put(data)

    def process_queue(self, dt):
        while not self.rx_queue.empty():
            self.log(f"[color=#00e6e6][RX][/color] {self.rx_queue.get()}")

    def log(self, msg):
        box = self.ids.get("console_box")
        if box is None:
            return

        for line in str(msg).split("\n"):
            self._append_console_line(box, line)

        Clock.schedule_once(
            lambda x: setattr(self.ids.scroll_view, "scroll_y", 0), 0.1
        )

    def _append_console_line(self, box, line):
        # box.children[0] is the most recently added chunk (Kivy prepends);
        # keep filling it until it's full, then start a new one.
        newest = box.children[0] if box.children else None
        if newest is not None and getattr(newest, "_line_count", 0) < self._CONSOLE_CHUNK_LINES:
            newest.text = f"{newest.text}\n{line}" if newest.text else line
            newest._line_count += 1
            return

        label = self._make_console_label(line)
        label._line_count = 1
        box.add_widget(label)

        # Drop the oldest chunk(s) once the retention cap is exceeded.
        while len(box.children) > self._CONSOLE_MAX_CHUNKS:
            box.remove_widget(box.children[-1])

    @staticmethod
    def _make_console_label(text):
        label = Label(
            text=text,
            markup=True,
            font_name=_CONSOLE_FONT,
            font_size="13sp",
            color=(0.9, 0.9, 0.9, 1),
            size_hint_y=None,
            halign="left",
            valign="top",
        )
        label.bind(
            width=lambda inst, w: setattr(inst, "text_size", (w, None)),
            texture_size=lambda inst, ts: setattr(inst, "height", ts[1]),
        )
        return label

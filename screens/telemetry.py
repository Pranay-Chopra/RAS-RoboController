import threading
import queue
import time
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.properties import BooleanProperty
from kivymd.uix.screen import MDScreen
from kivymd.toast import toast
ANDROID_MODE = False
try:
    from usbserial4a import get_usb_device
    import serial
    ANDROID_MODE = True
except ImportError:
    try:
        import serial  
    except ImportError:
        serial = None  
KV = '''
<TelemetryScreen>:
    MDBoxLayout:
        orientation: "vertical"
        md_bg_color: app.theme_cls.bg_normal

        MDTopAppBar:
            title: "USB Telemetry Monitor"
            elevation: 4
            left_action_items: [["robot-outline", lambda x: None]]
            right_action_items: [["usb-port", lambda x: root.toggle_connection()]]
            md_bg_color: app.theme_cls.primary_color

        MDCard:
            style: "elevated"
            padding: "12dp"
            margin: "12dp"
            elevation: 2
            size_hint_y: 0.85
            radius: [12, 12, 12, 12]
            
            ScrollView:
                id: scroll_view
                MDLabel:
                    id: console_log
                    text: "[b]System Initialized.[/b] Waiting for USB connection...\\n"
                    markup: True
                    valign: "top"
                    halign: "left"
                    size_hint_y: None
                    height: self.texture_size[1]
                    font_style: "Body2"

        MDBoxLayout:
            orientation: "horizontal"
            size_hint_y: 0.15
            padding: ["12dp", "0dp", "12dp", "12dp"]
            spacing: "12dp"

            MDTextField:
                id: command_input
                hint_text: "Enter serial command..."
                mode: "round"
                icon_left: "console-line"
                size_hint_x: 0.75
                on_text_validate: root.send_command()

            MDFillRoundFlatButton:
                text: "SEND"
                size_hint_x: 0.25
                pos_hint: {"center_y": 0.5}
                on_release: root.send_command()
'''

Builder.load_string(KV)

class TelemetryScreen(MDScreen):
    is_connected = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.serial_port = None
        self.rx_queue = queue.Queue()
        self.tx_queue = queue.Queue()
        self.stop_threads = False
        
        # Poll the queue every 100ms to update the UI safely on the main thread
        Clock.schedule_interval(self.process_queue, 0.1)

    def toggle_connection(self):
        if self.is_connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        if ANDROID_MODE:
            device = get_usb_device()
            if not device:
                self.log_message("[color=#ff3333][ERROR] No USB device detected.[/color]")
                toast("No USB Device Found")
                return
            try:
                self.serial_port = serial.Serial(device.getDeviceName(), 115200, timeout=1)
            except Exception as e:
                self.log_message(f"[color=#ff3333][ERROR] {str(e)}[/color]")
                return
        else:
            self.log_message("[color=#ff9933][WARN] PC Mode: Hardware libraries bypassed.[/color]")
            toast("Mock Mode Activated")
            self.is_connected = True
            return

        self.is_connected = True
        self.stop_threads = False
        self.log_message("[color=#33cc33][SUCCESS] Connected to hardware.[/color]")
        toast("Connected")
        
        # Launch background thread for non-blocking serial reads
        self.read_thread = threading.Thread(target=self._read_from_serial, daemon=True)
        self.read_thread.start()

    def disconnect(self):
        self.is_connected = False
        self.stop_threads = True
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.log_message("[color=#ff9933][INFO] Disconnected.[/color]")
        toast("Disconnected")

    def send_command(self):
        cmd = self.ids.command_input.text.strip()
        if not cmd:
            return
        
        self.ids.command_input.text = "" 
        self.log_message(f"[color=#3399ff][TX][/color] {cmd}")

        if self.is_connected and self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write((cmd + "\\n").encode('utf-8'))
            except Exception as e:
                self.log_message(f"[color=#ff3333][ERROR] TX Failed: {str(e)}[/color]")
        elif not ANDROID_MODE and self.is_connected:
            self.rx_queue.put(f"Mock Response to: {cmd}")

    def _read_from_serial(self):
        """Background thread to read data without freezing the Kivy UI."""
        while self.is_connected and not self.stop_threads:
            try:
                if self.serial_port.in_waiting > 0:
                    data = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                    if data:
                        self.rx_queue.put(data)
            except Exception as e:
                self.rx_queue.put(f"[color=#ff3333][ERROR] Serial Read Failed: {str(e)}[/color]")
                self.disconnect()
                break
            time.sleep(0.01)

    def process_queue(self, dt):
        """Pulls data from background queues to the UI."""
        while not self.rx_queue.empty():
            msg = self.rx_queue.get()
            self.log_message(f"[color=#00e6e6][RX][/color] {msg}")

    def log_message(self, msg):
        """Formats the terminal text and auto-scrolls."""
        console = self.ids.console_log
        console.text += f"\\n{msg}"
        scroll = self.ids.scroll_view
        Clock.schedule_once(lambda *args: setattr(scroll, 'scroll_y', 0), 0.1)

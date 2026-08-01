import threading
import queue
import time
from kivy.lang import Builder
from kivy.clock import Clock
from kivymd.uix.screen import MDScreen
from kivymd.toast import toast
from kivymd.app import MDApp

try:
    from usbserial4a import get_usb_device
    import serial
    IS_ANDROID = True
except ImportError:
    try: import serial
    except ImportError: serial = None
    IS_ANDROID = False

KV = '''
<TelemetryScreen>:
    MDBoxLayout:
        orientation: "vertical"
        md_bg_color: app.theme_cls.bg_normal

        MDTopAppBar:
            title: "Telemetry Monitor"
            elevation: 4
            left_action_items: [["robot-outline", lambda x: None]]
            right_action_items: [["usb-port", lambda x: root.toggle_usb()]]
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
                    id: console
                    text: "[b]System Ready.[/b] Waiting for connection...\\n"
                    markup: True
                    valign: "top"
                    size_hint_y: None
                    height: self.texture_size[1]

        MDBoxLayout:
            orientation: "horizontal"
            size_hint_y: 0.15
            padding: ["12dp", "0dp", "12dp", "12dp"]
            spacing: "12dp"

            MDTextField:
                id: input_cmd
                hint_text: "Enter command..."
                mode: "round"
                icon_left: "console-line"
                size_hint_x: 0.75
                on_text_validate: root.send()

            MDFillRoundFlatButton:
                text: "SEND"
                size_hint_x: 0.25
                pos_hint: {"center_y": 0.5}
                on_release: root.send()
'''

Builder.load_string(KV)

class TelemetryScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.serial_port = None
        self.usb_connected = False
        self.rx_queue = queue.Queue()
        self.stop_threads = False
        
        Clock.schedule_interval(self.process_queue, 0.1)

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
                self.serial_port = serial.Serial(device.getDeviceName(), 115200, timeout=1)
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
        if not cmd: return
        
        self.ids.input_cmd.text = "" 
        self.log(f"[color=#3399ff][TX][/color] {cmd}")
        
        app = MDApp.get_running_app()

        if getattr(app, 'is_connected', False) and app.current_robot:
            try:
                if app.current_robot.transport == "wifi":
                    app.wifi.send(cmd)
                elif app.current_robot.transport == "ble":
                    app.ble.write(cmd)
                return
            except Exception as e:
                self.log(f"[color=#ff3333][ERROR] Network TX: {e}[/color]")
                return

        if self.usb_connected and self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(f"{cmd}\n".encode('utf-8'))
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
                    data = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                    if data: self.rx_queue.put(data)
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
        self.ids.console.text += f"\n{msg}"
        Clock.schedule_once(lambda x: setattr(self.ids.scroll_view, 'scroll_y', 0), 0.1)

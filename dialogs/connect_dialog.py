from kivy.clock import Clock
from kivy.lang import Builder
from kivy.uix.modalview import ModalView

try:
    from .theme import BLACK, GOLD
except ImportError:
    GOLD = (0.83, 0.68, 0.21, 1)
    BLACK = (0, 0, 0, 1)

KV = """
<ConnectDialogContent>:
    size_hint: 0.88, None
    height: "220dp"
    auto_dismiss: True
    background_color: 0, 0, 0, 0.6

    MDCard:
        orientation: "vertical"
        padding: "24dp"
        spacing: "16dp"
        radius: [16]
        elevation: 4
        md_bg_color: 0.12, 0.12, 0.12, 1

        MDLabel:
            id: title_label
            text: "Connect to Robot"
            font_style: "H6"
            bold: True
            size_hint_y: None
            height: self.texture_size[1]
            theme_text_color: "Custom"
            text_color: 0.95, 0.95, 0.95, 1

        MDBoxLayout:
            size_hint_y: None
            height: "48dp"
            spacing: "4dp"

            MDTextField:
                id: password_field
                hint_text: "Wi-Fi Password"
                password: True
                multiline: False
                mode: "line"

                line_color_normal: 0.45, 0.45, 0.45, 1
                line_color_focus: 0.83, 0.68, 0.21, 1
                hint_text_color_focus: 0.83, 0.68, 0.21, 1
                active_line_color: 0.83, 0.68, 0.21, 1

            MDIconButton:
                id: password_toggle
                icon: "eye"
                size_hint_x: None
                pos_hint: {"center_y": 0.5}
                theme_text_color: "Custom"
                text_color: 0.6, 0.6, 0.6, 1
                on_release: root.toggle_password_visibility()

        Widget:

        MDBoxLayout:
            adaptive_height: True
            spacing: "12dp"

            Widget:

            MDFlatButton:
                text: "CANCEL"
                theme_text_color: "Custom"
                text_color: 0.83, 0.68, 0.21, 1
                on_release: root.cancel()

            MDRaisedButton:
                text: "CONNECT"
                md_bg_color: 0.83, 0.68, 0.21, 1
                text_color: 0, 0, 0, 1
                on_release: root.connect()
"""

Builder.load_string(KV)


class ConnectDialogContent(ModalView):
    def __init__(self, robot, callback, **kwargs):
        super().__init__(**kwargs)
        self.robot = robot
        self.callback = callback
        self.ids.title_label.text = f"Connect to {robot.name}"

    def toggle_password_visibility(self):
        field = self.ids.password_field
        field.password = not field.password
        # "eye" = currently masked (tap to reveal); "eye-off" = revealed.
        self.ids.password_toggle.icon = "eye" if field.password else "eye-off"

    def cancel(self):
        self.ids.password_field.focus = False
        self.dismiss()

    def connect(self):
        password = self.ids.password_field.text.strip()
        self.ids.password_field.focus = False
        self.dismiss()
        if self.callback:
            self.callback(self.robot, password)


class ConnectDialog:
    """Wrapper class so existing home.py calls work seamlessly."""

    def __init__(self, robot, callback):
        self.view = ConnectDialogContent(robot, callback)

    def open(self):
        self.view.open()

    def dismiss(self):
        self.view.dismiss()

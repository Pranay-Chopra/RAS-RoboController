from kivymd.uix.dialog import (
    MDDialog,
    MDDialogHeadlineText,
    MDDialogSupportingText,
    MDDialogContentContainer,
    MDDialogButtonContainer,
)
from kivymd.uix.button import (
    MDButton,
    MDButtonText,
)
from kivymd.uix.textfield import MDTextField


class ConnectDialog(MDDialog):

    def __init__(self, robot, callback, **kwargs):
        super().__init__(**kwargs)

        self.robot = robot
        self.callback = callback

        # 1. Dialog Title
        self.add_widget(
            MDDialogHeadlineText(
                text=f"Connect to {robot.name}"
            )
        )

        # 2. Supporting Text
        self.add_widget(
            MDDialogSupportingText(
                text="Enter the Wi-Fi password for this robot access point."
            )
        )

        # 3. Wrapping in MDDialogContentContainer prevents button overlap
        content_container = MDDialogContentContainer(
            orientation="vertical",
            spacing="12dp"
        )

        self.password_field = MDTextField(
            hint_text="Wi-Fi Password",
            password=True,
            mode="outlined",
        )
        content_container.add_widget(self.password_field)
        self.add_widget(content_container)

        # 4. Action Buttons
        self.add_widget(
            MDDialogButtonContainer(
                MDButton(
                    MDButtonText(text="Cancel"),
                    on_release=self._cancel,
                    style="text",
                ),
                MDButton(
                    MDButtonText(text="Connect"),
                    on_release=self._connect,
                    style="filled",
                ),
            )
        )

    def _cancel(self, *args):
        self.dismiss()

    def _connect(self, *args):
        password = self.password_field.text.strip()

        # Dismiss dialog immediately so UI stays responsive
        self.dismiss()

        # Trigger callback with target robot and inputted password
        if self.callback:
            self.callback(self.robot, password)

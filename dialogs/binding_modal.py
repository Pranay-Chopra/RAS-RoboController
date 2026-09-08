from kivy.metrics import dp
from kivy.clock import Clock
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.selectioncontrol import MDSwitch


class BindingModal:
    def __init__(self, wrapper, on_save_callback=None, on_delete_callback=None):
        self.wrapper = wrapper
        self.on_save_callback = on_save_callback
        self.on_delete_callback = on_delete_callback
        self.self_center_switch = None

        layout = MDBoxLayout(orientation="vertical", spacing="12dp", size_hint_y=None, adaptive_height=True)
        layout.bind(minimum_height=layout.setter("height"))

        self.id_input = MDTextField(
            text=wrapper.input_id,
            hint_text="Input ID / Label",
            mode="line"
        )
        self.cmd_input = MDTextField(
            text=wrapper.command_template,
            hint_text="Command Template (e.g. JOY:{x},{y})",
            mode="line"
        )
        layout.add_widget(self.id_input)
        if not wrapper.element_type == "label":
            layout.add_widget(self.cmd_input)


        if wrapper.element_type == "slider":
            self.min_input = MDTextField(
                text=str(wrapper.min_val),
                hint_text="Min Value",
                mode="line"
            )
            self.max_input = MDTextField(
                text=str(wrapper.max_val),
                hint_text="Max Value",
                mode="line"
            )
            layout.add_widget(self.min_input)
            layout.add_widget(self.max_input)

        if wrapper.element_type == "joystick":
            row = MDBoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(48),
                spacing=dp(10),
            )
            row.add_widget(
                MDLabel(
                    text="Self-Centering",
                    theme_text_color="Custom",
                    text_color=(1, 1, 1, 1),

                )
            )
            # NOTE: `active` must NOT be passed as a constructor kwarg here.
            # Doing so fires on_active during MDSwitch.__init__, before its
            # internal ids (thumb/track template widgets) exist yet, which
            # raises a KeyError inside KivyMD that escalates into an
            # AttributeError crash. Set it as a separate statement instead,
            # after construction has fully completed.
            self.self_center_switch = MDSwitch()
            self.self_center_switch.active = getattr(wrapper, "self_centering", True)
            row.add_widget(self.self_center_switch)
            layout.add_widget(row)
            row.add_widget(MDLabel(text="", size_hint=(.1, 1)))  # Spacer to align switch to left

        # --- Height-timing fix ---
        # layout.bind(minimum_height=layout.setter("height")) above only
        # fires once BoxLayout's internal layout pass actually runs, and
        # that pass is scheduled (deferred to Kivy's Clock), not run
        # inline by add_widget(). MDDialog(content_cls=layout, ...) below
        # constructs -- and reads layout.height to size itself -- in the
        # same call stack, before that deferred pass has ever fired. That
        # left layout.height at whatever it was originally (Kivy's Widget
        # default of 100), not the true height needed for however many
        # fields got added above, which is what produced the mismatched
        # empty space in the dialog. Forcing do_layout() here runs
        # BoxLayout's layout algorithm immediately and synchronously,
        # updating minimum_height (and, via the bind above, height) right
        # now, before MDDialog ever reads it.
        layout.do_layout()

        self.dialog = MDDialog(
            title=f"Rebind {wrapper.element_type.capitalize()}",
            type="custom",
            content_cls=layout,
            buttons=[
                MDFlatButton(
                    text="DELETE",
                    theme_text_color="Custom",
                    text_color=(0.9, 0.2, 0.2, 1),  # Red theme for destructive action
                    on_release=self._delete
                ),
                MDFlatButton(
                    text="CANCEL",
                    on_release=lambda *a: self.dialog.dismiss()
                ),
                MDFlatButton(
                    text="SAVE",
                    on_release=self._save
                )
            ]
        )

        # --- Title-to-content gap fix ---
        #
        # KivyMD's type="custom" dialog puts content_cls inside its
        # internal `spacer_top_box`. Its height is calculated during
        # a deferred layout pass, so sizing it immediately can leave
        # a large stale gap between the title and the first field.
        #
        # Finish the sizing on the next frame, after both the dialog
        # and content layout have completed their layout passes.
        def _fix_dialog_spacing(*_):
            layout.do_layout()
            layout.height = layout.minimum_height

            spacer = self.dialog.ids.get("spacer_top_box")
            if spacer is not None:
                # Use a small intentional title-to-content gap instead
                # of KivyMD's larger default custom-dialog spacing.
                spacer.padding = (0, dp(8), dp(16), 0)

                # Match the spacer to the actual content height.
                self.dialog._spacer_top = layout.height + dp(8)
                spacer.do_layout()

            # Recalculate the outer dialog after changing the spacer.
            try:
                self.dialog.height = self.dialog.ids.container.height
            except Exception:
                self.dialog.update_height()

        Clock.schedule_once(_fix_dialog_spacing, 0)

    def open(self):
        self.dialog.open()

    def _delete(self, *args):
        self.dialog.dismiss()
        if self.on_delete_callback:
            self.on_delete_callback(self.wrapper)

    def _save(self, *args):
        self.wrapper.input_id = self.id_input.text
        self.wrapper.command_template = self.cmd_input.text

        if self.wrapper.element_type == "slider":
            try:
                self.wrapper.min_val = float(self.min_input.text)
                self.wrapper.max_val = float(self.max_input.text)
                # Default position is always the midpoint of the range.
                self.wrapper.default_val = (
                    self.wrapper.min_val + self.wrapper.max_val
                ) / 2

                for child in self.wrapper.children:
                    if hasattr(child, 'min'):
                        child.min = self.wrapper.min_val
                        child.max = self.wrapper.max_val
                        child.value = self.wrapper.default_val
            except ValueError:
                pass

        if self.wrapper.element_type == "joystick" and self.self_center_switch is not None:
            self.wrapper.self_centering = self.self_center_switch.active

        if self.on_save_callback:
            self.on_save_callback(self.wrapper)

        self.dialog.dismiss()

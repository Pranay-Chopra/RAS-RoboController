import os
import json
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivy.properties import BooleanProperty
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.slider import MDSlider
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu
from kivymd.toast import toast
from kivy.clock import Clock
from jnius import autoclass
from android import activity

from utils.control_engine import connection_mgr
from widgets.hud_element import HUDElementWrapper
from widgets.joystick import TouchJoystick
from widgets.toggle_switch import ScalableToggle
from dialogs.binding_modal import BindingModal


class HUDControlsScreen(MDScreen):
    is_edit_mode = BooleanProperty(False)

    # Arbitrary unique ints identifying which startActivityForResult()
    # call an incoming on_activity_result belongs to.
    _EXPORT_REQUEST_CODE = 42001
    _IMPORT_REQUEST_CODE = 42002

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_menu = None
        self.profile_path = os.path.join(
            MDApp.get_running_app().user_data_dir, "hud_layout.json"
        )

    def on_enter(self):
        Clock.schedule_once(lambda dt: self.load_layout(), 0.05)

    def save_layout(self):
        """Serializes all HUD element positions, sizes, and command configs to disk."""
        elements_data = []

        # Iterate through canvas elements and export their wrapper metadata
        for child in self.ids.hud_canvas.children:
            if isinstance(child, HUDElementWrapper):
                elements_data.append(child.to_dict())

        try:
            with open(self.profile_path, "w") as f:
                json.dump(elements_data, f, indent=4)
            print(
                f"[HUD Studio] Profile saved successfully to {self.profile_path}"
            )
        except Exception as e:
            print(f"[HUD Studio Error] Failed to save layout: {e}")

    def export_layout(self):
        """Lets the user pick a save location (Downloads, Drive, USB,
        etc.) via Android's Storage Access Framework and writes the
        current HUD layout there as JSON.

        Uses ACTION_CREATE_DOCUMENT rather than a fixed shared-storage
        path: it needs no storage permissions or manifest/FileProvider
        setup (the system picker itself grants the app access to
        whatever content:// location the user picks), and it's the
        Android-recommended way to save a user-visible file from a
        scoped-storage app.
        """
        # Make sure the exported file reflects what's actually on the
        # canvas right now, not just whatever was last explicitly saved.
        self.save_layout()

        try:
            Intent = autoclass("android.content.Intent")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity_instance = PythonActivity.mActivity

            intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("application/json")
            intent.putExtra(Intent.EXTRA_TITLE, "hud_layout_export.json")

            activity.bind(on_activity_result=self._on_export_result)
            activity_instance.startActivityForResult(intent, self._EXPORT_REQUEST_CODE)
        except Exception as e:
            toast(f"Could not open export picker: {e}")
            print(f"[HUD Studio Error] export_layout: {e}")

    def _on_export_result(self, requestCode, resultCode, intent):
        if requestCode != self._EXPORT_REQUEST_CODE:
            return
        activity.unbind(on_activity_result=self._on_export_result)

        try:
            Activity = autoclass("android.app.Activity")
            if resultCode != Activity.RESULT_OK or intent is None:
                print("[HUD Studio] Export cancelled.")
                return

            uri = intent.getData()
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            resolver = PythonActivity.mActivity.getContentResolver()

            with open(self.profile_path, "rb") as f:
                data_bytes = f.read()

            output_stream = resolver.openOutputStream(uri)
            output_stream.write(data_bytes)
            output_stream.flush()
            output_stream.close()

            print(f"[HUD Studio] Exported layout to {uri.toString()}")
            Clock.schedule_once(lambda dt: toast("Layout exported"), 0)
        except Exception as e:
            print(f"[HUD Studio Error] _on_export_result: {e}")
            Clock.schedule_once(lambda dt, err=e: toast(f"Export failed: {err}"), 0)

    def import_layout(self):
        """Lets the user pick a previously-exported JSON layout file via
        Android's Storage Access Framework, validates it, then loads it
        (overwriting the current on-canvas layout)."""
        try:
            Intent = autoclass("android.content.Intent")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity_instance = PythonActivity.mActivity

            intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("application/json")

            activity.bind(on_activity_result=self._on_import_result)
            activity_instance.startActivityForResult(intent, self._IMPORT_REQUEST_CODE)
        except Exception as e:
            toast(f"Could not open import picker: {e}")
            print(f"[HUD Studio Error] import_layout: {e}")

    def _on_import_result(self, requestCode, resultCode, intent):
        if requestCode != self._IMPORT_REQUEST_CODE:
            return
        activity.unbind(on_activity_result=self._on_import_result)

        try:
            Activity = autoclass("android.app.Activity")
            if resultCode != Activity.RESULT_OK or intent is None:
                print("[HUD Studio] Import cancelled.")
                return

            uri = intent.getData()
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            resolver = PythonActivity.mActivity.getContentResolver()

            input_stream = resolver.openInputStream(uri)
            BufferedReader = autoclass("java.io.BufferedReader")
            InputStreamReader = autoclass("java.io.InputStreamReader")
            reader = BufferedReader(InputStreamReader(input_stream))

            lines = []
            line = reader.readLine()
            while line is not None:
                lines.append(line)
                line = reader.readLine()
            reader.close()
            content = "\n".join(lines)

            # Validate before touching the real profile -- a malformed
            # or unrelated JSON file picked by mistake should never wipe
            # out the working layout.
            data = json.loads(content)
            if not isinstance(data, list):
                raise ValueError("Expected a JSON list of HUD elements")

            with open(self.profile_path, "w") as f:
                json.dump(data, f, indent=4)

            print(f"[HUD Studio] Imported layout from {uri.toString()}")
            Clock.schedule_once(lambda dt: self.load_layout(), 0)
            Clock.schedule_once(lambda dt: toast("Layout imported"), 0)
        except Exception as e:
            print(f"[HUD Studio Error] _on_import_result: {e}")
            Clock.schedule_once(lambda dt, err=e: toast(f"Import failed: {err}"), 0)

    def load_layout(self):
        canvas_w = self.ids.hud_canvas.width
        canvas_h = self.ids.hud_canvas.height

        # Retry if the canvas hasn't been measured by Kivy yet
        if canvas_w <= 100 or canvas_h <= 100:
            Clock.schedule_once(lambda dt: self.load_layout(), 0.05)
            return

        self.ids.hud_canvas.clear_widgets()

        if not os.path.exists(self.profile_path):
            return

        try:
            with open(self.profile_path, "r") as f:
                data = json.load(f)

            for item in data:
                pos_x = item.get("pos_hint_x", 0.1) * canvas_w
                pos_y = item.get("pos_hint_y", 0.1) * canvas_h
                size = item.get("size_dp", [180, 180])

                self.add_control(
                    control_type=item["element_type"],
                    pos=(pos_x, pos_y),
                    size=tuple(size),
                    config=item,
                )
                rotation = item.get("rotation")
                if rotation is not None:
                    self.ids.hud_canvas.children[0].rotation = rotation
        except Exception as e:
            print(f"Error loading layout: {e}")

    def switch_screen(self, screen_name: str) -> None:
        """Dispatches screen transition requests triggered from the navigation drawer."""
        app = MDApp.get_running_app()
        self.save_layout()  # Save current layout before switching screens
        if hasattr(app, "root") and app.root:
            if hasattr(app.root, "current"):
                app.root.current = screen_name
            elif hasattr(app.root, "has_screen") and app.root.has_screen(
                screen_name
            ):
                app.root.current = screen_name
            else:
                print(
                    f"[ControlsScreen] Screen '{screen_name}' not found on app root."
                )

    def toggle_edit_mode(self):
        self.is_edit_mode = not self.is_edit_mode
        if not self.is_edit_mode:
            self.save_layout()
        for child in self.ids.hud_canvas.children:
            if isinstance(child, HUDElementWrapper):
                child.edit_mode = self.is_edit_mode
                if not self.is_edit_mode:
                    child.selected = False

    def open_add_widget_menu(self, caller):
        menu_items = [
            {
                "text": "Analog Joystick",
                "viewclass": "OneLineListItem",
                "on_release": lambda: self.add_control("joystick"),
            },
            {
                "text": "Action Button",
                "viewclass": "OneLineListItem",
                "on_release": lambda: self.add_control("button"),
            },
            {
                "text": "Slider Control",
                "viewclass": "OneLineListItem",
                "on_release": lambda: self.add_control("slider"),
            },
            {
                "text": "Toggle Switch",
                "viewclass": "OneLineListItem",
                "on_release": lambda: self.add_control("toggle"),
            },
            {
                "text": "Label",
                "viewclass": "OneLineListItem",
                "on_release": lambda: self.add_control("label"),
            },
        ]
        self.add_menu = MDDropdownMenu(
            caller=caller, items=menu_items, width_mult=4
        )
        self.add_menu.open()

    def add_control(
        self, control_type, pos=(100, 200), size=None, config=None
    ):
        if self.add_menu:
            self.add_menu.dismiss()

        if not size:
            if control_type == "joystick":
                size = (180, 180)
            elif control_type == "slider":
                size = (220, 50)
            elif control_type == "toggle":
                size = (130, 65)
            else:
                size = (140, 50)

        if control_type == "toggle":
            # ScalableToggle draws itself fresh from its own current
            # size, so this doesn't guard against any overflow/scaling
            # bug -- it just guards against an old saved layout (from
            # before this control existed at its current size) loading
            # back in at an unusably tiny size, since load_layout() uses
            # whatever size_dp is stored in the save file rather than
            # recomputing a default.
            min_w, min_h = 120, 56
            size = (max(size[0], min_w), max(size[1], min_h))

        # Shape constraints, matching ResizeHandle's own (see
        # widgets/hud_element.py) -- applied here too so a size loaded
        # from an OLD save file (from before these constraints existed)
        # self-corrects on load, rather than staying a non-conforming
        # shape until someone happens to drag the resize handle.
        if control_type == "joystick":
            side = max(size[0], size[1])
            size = (side, side)
        elif control_type == "slider":
            size = (size[0], min(size[1], 50))
        elif control_type == "toggle":
            size = (size[0], min(size[1], 65))

        wrapper = HUDElementWrapper(
            size_hint=(None, None),
            size=size,
            pos=pos,
            edit_mode=self.is_edit_mode,
            element_type=control_type,
        )
        wrapper.bind(
            on_edit_request=lambda *a: self.open_rebind_dialog_for(wrapper),
            on_delete_request=lambda *a: self.delete_selected_element(wrapper),
        )

        if config:
            wrapper.input_id = config.get("input_id", "unbound")
            wrapper.command_template = config.get("command_template", "")
            wrapper.self_centering = config.get("self_centering", True)

        # --- JOYSTICK ---
        if control_type == "joystick":
            if not wrapper.command_template:
                wrapper.command_template = "JOY:{x},{y}"
            js = TouchJoystick(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
            js.self_centering = wrapper.self_centering
            # Keeps the live joystick's self_centering in sync with
            # wrapper.self_centering for the rest of this element's life,
            # so a change saved from the binding modal (which only ever
            # touches wrapper.self_centering) applies immediately without
            # needing to rebuild the control.
            wrapper.bind(
                self_centering=lambda inst, val: setattr(js, "self_centering", val)
            )
            js.target_callback = (
                lambda x, y: connection_mgr.send(
                    wrapper.command_template.format(x=x, y=y)
                )
                if not self.is_edit_mode
                else None
            )
            wrapper.add_widget(js)

        # --- BUTTON ---
        elif control_type == "button":
            if not wrapper.command_template:
                wrapper.command_template = "CMD:ARM"
            btn = MDRaisedButton(
                text=wrapper.input_id.upper(),
                size_hint=(1, 1),
                pos_hint={"x": 0, "y": 0},
                md_bg_color=(0.83, 0.68, 0.21, 1),
                text_color=(0, 0, 0, 1),
            )
            btn.bind(
                on_release=lambda *a: connection_mgr.send(
                    wrapper.command_template
                )
                if not self.is_edit_mode
                else None
            )
            wrapper.add_widget(btn)

        # --- SLIDER ---
        elif control_type == "slider":
            if not wrapper.command_template:
                wrapper.command_template = "SERVO:{val}"

            # Restore the configured range from a saved/imported layout.
            # Falls back to the wrapper's own NumericProperty defaults
            # (0..180) for a freshly-added slider.
            if config:
                wrapper.min_val = config.get("min_val", wrapper.min_val)
                wrapper.max_val = config.get("max_val", wrapper.max_val)

            # The starting position is ALWAYS the midpoint of the range,
            # regardless of any stored default_val.
            wrapper.default_val = (wrapper.min_val + wrapper.max_val) / 2

            slider = MDSlider(
                min=wrapper.min_val,
                max=wrapper.max_val,
                value=wrapper.default_val,
                color=(0.83, 0.68, 0.21, 1),
                size_hint=(1, 1),
                pos_hint={"x": 0, "y": 0},
            )
            slider.bind(
                value=lambda inst, val: connection_mgr.send(
                    wrapper.command_template.format(val=int(val))
                )
                if not self.is_edit_mode
                else None
            )
            wrapper.add_widget(slider)

        # --- TOGGLE SWITCH ---
        elif control_type == "toggle":
            if not wrapper.command_template:
                wrapper.command_template = "SW:{state}"
            # ScalableToggle draws its own track+thumb fresh from
            # self.width/height on every redraw (same approach
            # TouchJoystick uses), so it scales correctly at whatever
            # size the wrapper is resized to -- no MDSwitch, no Scatter,
            # no fixed native size. See widgets/toggle_switch.py.
            toggle = ScalableToggle()
            toggle.bind(
                active=lambda inst, val: connection_mgr.send(
                    wrapper.command_template.format(state=(1 if val else 0))
                )
                if not self.is_edit_mode
                else None
            )
            wrapper.add_widget(toggle)

        # --- LABEL ---
        elif control_type == "label":
            lbl = MDLabel(
                text=wrapper.input_id,
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
                halign="center",
                valign="middle",
            )
            # size_hint fills the wrapper (forced by add_widget below);
            # text_size bound to size is what makes halign/valign actually
            # take effect within that box instead of defaulting to the
            # label's own natural text size.
            lbl.bind(size=lbl.setter("text_size"))
            # Font size scales with the wrapper -- otherwise resizing a
            # label bigger just grows empty space around fixed-size
            # text instead of the text itself becoming more prominent.
            # Scaled off the smaller of width/height so it stays
            # readable regardless of the label's aspect ratio, instead
            # of overflowing one axis if resized into a very wide-short
            # or tall-narrow shape.
            lbl.bind(
                size=lambda inst, val: setattr(
                    inst, "font_size", min(inst.width, inst.height) * 0.3
                )
            )
            wrapper.add_widget(lbl)

        self.ids.hud_canvas.add_widget(wrapper)



    def _on_binding_updated(self, wrapper):
        # Update button text display if it's a button element
        if wrapper.element_type == "button":
            for child in wrapper.children:
                if isinstance(child, MDRaisedButton):
                    child.text = wrapper.input_id.upper()

        # Update a standalone Label's displayed text on rebind
        elif wrapper.element_type == "label":
            for child in wrapper.children:
                if isinstance(child, MDLabel):
                    child.text = wrapper.input_id

        # Note: joystick's self_centering doesn't need handling here --
        # it's kept in sync via the wrapper.bind() set up in add_control().

    def delete_selected_element(self, wrapper=None):
            """Removes the target wrapper (or currently selected wrapper) from the canvas."""
            if not wrapper:
                for child in self.ids.hud_canvas.children:
                    if isinstance(child, HUDElementWrapper) and child.selected:
                        wrapper = child
                        break

            if wrapper and wrapper in self.ids.hud_canvas.children:
                self.ids.hud_canvas.remove_widget(wrapper)
                # Re-draw remaining borders/states
                self.ids.hud_canvas.canvas.ask_update()

    def open_rebind_dialog(self):
        """Opens binding modal for whichever element is currently selected in Edit Mode."""
        selected_wrapper = None
        for child in self.ids.hud_canvas.children:
            if isinstance(child, HUDElementWrapper) and child.selected:
                selected_wrapper = child
                break

        if selected_wrapper:
            self.open_rebind_dialog_for(selected_wrapper)

    def open_rebind_dialog_for(self, wrapper):
        """Opens the binding modal for a specific element directly —
        used by the element's own pencil icon, so it doesn't depend on
        selection-state lookup."""
        modal = BindingModal(
            wrapper,
            on_save_callback=self._on_binding_updated,
            on_delete_callback=self.delete_selected_element,
        )
        modal.open()

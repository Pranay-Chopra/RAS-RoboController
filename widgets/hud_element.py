from math import atan2, cos, degrees, radians, sin

from kivy.clock import Clock
from kivy.graphics import (
    Color,
    InstructionGroup,
    Line,
    PopMatrix,
    PushMatrix,
    Rotate,
)
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.floatlayout import FloatLayout
from kivymd.uix.button import MDIconButton

GOLD = (0.83, 0.68, 0.21, 1)
HANDLE_SIZE = dp(30)
MIN_ELEMENT_SIZE = dp(48)
DEFAULT_ELEMENT_SIZE = dp(80)

# Height caps for resize, matched EXACTLY to hud_controls.py's own
# default sizes for these element types (220x50 slider, 130x65 toggle)
# -- deliberately plain numbers, not dp(), for the same reason those
# defaults are plain numbers: mixing dp()-scaled and raw-number sizes
# for the same element caused a real, confirmed bug before (the toggle
# switch rendering larger than its own wrapper on real devices, since
# dp() resolves to more raw pixels than a plain number on any density
# above 1x). Keeping these in the same units as the sizes they're
# capping avoids repeating that.
MAX_SLIDER_HEIGHT = 50
MAX_TOGGLE_HEIGHT = 65


class OverlayIconButton(MDIconButton):
    """Base icon button for HUD edit overlay controls. Overrides collide_point
    to inverse-rotate parent/window coordinates into the target's unrotated local
    coordinate space so ButtonBehavior's on_touch_up collision check succeeds
    100% of the time when the wrapper is rotated."""
    target = ObjectProperty(None)

    def collide_point(self, x, y):
        if self.target:
            x, y = self.target._touch_to_local(x, y)
        return super().collide_point(x, y)


class RotateHandle(OverlayIconButton):
    """Small handle that, when dragged, rotates `target` around its own
    center. Deliberately bypasses ButtonBehavior's own touch handling
    (no super() call on the success path) so ripple/press states don't
    fight with the drag — a minor cosmetic tradeoff for predictability."""
    _start_angle = NumericProperty(0)
    _start_rotation = NumericProperty(0)

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos) or not self.target:
            return super().on_touch_down(touch)
        touch.grab(self)
        cx, cy = self.target.center
        self._start_angle = degrees(atan2(touch.y - cy, touch.x - cx))
        self._start_rotation = self.target.rotation
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self or not self.target:
            return super().on_touch_move(touch)
        cx, cy = self.target.center
        angle = degrees(atan2(touch.y - cy, touch.x - cx))
        self.target.rotation = (self._start_rotation + (angle - self._start_angle)) % 360
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            return True
        return super().on_touch_up(touch)


class ResizeHandle(OverlayIconButton):
    """Bottom-left-anchored resize: width/height are recomputed each move
    directly from the current touch position relative to the target's
    fixed x/y, rather than accumulated deltas — simpler and self-correcting.

    Applies per-element-type shape constraints on top of that (joystick
    forced square, slider/toggle height capped) — see on_touch_move.
    Without these, a non-rectangular wrapper around a circular/thin
    element leaves touchable wrapper area outside what's actually
    visible, since touch handling collides against the wrapper's full
    bounding box, not the element's own drawn shape.
    """

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos) or not self.target:
            return super().on_touch_down(touch)
        touch.grab(self)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self or not self.target:
            return super().on_touch_move(touch)
        lx, ly = self.target._touch_to_local(touch.x, touch.y)
        dx = lx - self.target.x
        dy = ly - self.target.y

        element_type = getattr(self.target, "element_type", None)

        if element_type == "joystick":
            # Perfectly square, using the AVERAGE of dx/dy rather than
            # max(new_w, new_h). max() has a discontinuity: whichever of
            # width/height is currently larger "wins" entirely, so a
            # drag that isn't perfectly diagonal crosses the point where
            # dx overtakes dy (or vice versa) at some moment, and right
            # at that crossover BOTH dimensions instantly snap to the
            # new larger value in a single frame -- that sudden jump is
            # what felt like "too aggressive on the slightest pull".
            # Averaging is smooth and continuous across the whole drag:
            # a purely horizontal or vertical pull grows the square at
            # half rate instead of snapping, and a diagonal pull (where
            # dx≈dy) behaves the same as before.
            side = max(MIN_ELEMENT_SIZE, (dx + dy) / 2)
            new_w = side
            new_h = side
        else:
            new_w = max(MIN_ELEMENT_SIZE, dx)
            new_h = max(MIN_ELEMENT_SIZE, dy)
            if element_type == "slider":
                # Height never exceeds the slider's own natural track
                # height -- only width should grow. Same dead-space
                # problem as the joystick otherwise: a tall wrapper
                # around a thin horizontal track leaves touchable space
                # above/below the actual track and thumb.
                new_h = min(new_h, MAX_SLIDER_HEIGHT)
            elif element_type == "toggle":
                new_h = min(new_h, MAX_TOGGLE_HEIGHT)

        self.target.size = (new_w, new_h)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            return True
        return super().on_touch_up(touch)


class HUDElementWrapper(FloatLayout):
    __events__ = ("on_edit_request", "on_delete_request")

    edit_mode = BooleanProperty(False)
    selected = BooleanProperty(False)
    input_id = StringProperty("unbound")
    command_template = StringProperty("")
    element_type = StringProperty("button")
    rotation = NumericProperty(0)

    # Dynamic boundary configuration for Sliders
    min_val = NumericProperty(0)
    max_val = NumericProperty(180)
    default_val = NumericProperty(90)

    # Joystick-only: whether releasing the touch snaps the knob back to
    # center (True, default) or leaves it wherever it was released.
    self_centering = BooleanProperty(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (None, None)
        if "size" not in kwargs:
            self.size = (DEFAULT_ELEMENT_SIZE, DEFAULT_ELEMENT_SIZE)

        self.touch_start_pos = None
        self.initial_pos = None
        self._main_control = None
        self._rotate_instruction = None
        self._overlay_built = False
        self._edit_btn = None
        self._delete_btn = None
        self._rotate_handle = None
        self._resize_handle = None
        # Maps an in-progress touch -> the main control it should be
        # manually forwarded to, once that control's own grab has been
        # hijacked in on_touch_down (see the play-mode branch of
        # on_touch_down/move/up below for why this is necessary).
        self._touch_child_map = {}

        # Apply OpenGL rotation to the ENTIRE wrapper (main control + handles + border)
        self._border_group = InstructionGroup()
        with self.canvas.before:
            PushMatrix()
            self._rotate_instruction = Rotate(angle=self.rotation, origin=self.center)
        self.canvas.after.add(self._border_group)
        with self.canvas.after:
            PopMatrix()

        self.bind(
            pos=self._sync_children,
            size=self._sync_children,
            rotation=self._sync_rotation_instruction,
            center=self._sync_rotation_instruction,
        )
        self.bind(
            edit_mode=self._on_edit_or_select_change,
            selected=self._on_edit_or_select_change,
        )

    # ------------------------------------------------------------------
    # Placing the main control (button / joystick / slider)
    # ------------------------------------------------------------------
    def add_widget(self, widget, *args, **kwargs):
        super().add_widget(widget, *args, **kwargs)
        widget.size_hint = (1, 1)
        widget.pos_hint = {"x": 0, "y": 0}
        widget.pos = self.pos
        widget.size = self.size
        widget.bind(size=self._enforce_child_geometry, pos=self._enforce_child_geometry)
        if hasattr(widget, "_update_graphics"):
            widget._update_graphics()
        self._main_control = widget
        # Widgets we fully control (TouchJoystick, ScalableToggle) expose
        # their own `target` property and do their own rotation
        # compensation internally via target._touch_to_local(). Wiring it
        # here automatically means on_touch_down's grab-hijack logic
        # below can skip them entirely and leave their already-correct
        # self-managed behavior alone -- the hijack mechanism exists only
        # for third-party widgets (MDSlider, MDRaisedButton) we can't add
        # a `target` property to ourselves.
        if hasattr(widget, "target"):
            widget.target = self
        if not self._overlay_built:
            self._build_edit_overlay()
            self._overlay_built = True

    def _enforce_child_geometry(self, child, *args):
        if tuple(child.size) != tuple(self.size):
            child.size = self.size
        if tuple(child.pos) != tuple(self.pos):
            child.pos = self.pos

    def _sync_children(self, *args):
        self._update_border()
        if self._main_control is not None:
            self._main_control.pos = self.pos
            self._main_control.size = self.size
            if hasattr(self._main_control, "_update_graphics"):
                self._main_control._update_graphics()
        self._position_overlay_handles()

    # ------------------------------------------------------------------
    # Rotation — visual transform on the entire wrapper and coordinate
    # mappings for touch dispatch
    # ------------------------------------------------------------------
    def _apply_rotation_to(self, widget=None):
        """Syncs the rotation instruction for the wrapper."""
        self._sync_rotation_instruction()

    def _sync_rotation_instruction(self, *args):
        if self._rotate_instruction:
            self._rotate_instruction.angle = self.rotation
            self._rotate_instruction.origin = self.center

    def _touch_to_local(self, x, y):
        """Inverse-rotates a parent-space point by -rotation around this
        widget's center, mapping it into unrotated local space."""
        rad = radians(-self.rotation)
        cx, cy = self.center
        dx, dy = x - cx, y - cy
        lx = cx + dx * cos(rad) - dy * sin(rad)
        ly = cy + dx * sin(rad) + dy * cos(rad)
        return lx, ly

    def _touch_to_parent(self, lx, ly):
        """Rotates a local-space point by +rotation around this
        widget's center, mapping it back to parent space."""
        rad = radians(self.rotation)
        cx, cy = self.center
        dx, dy = lx - cx, ly - cy
        px = cx + dx * cos(rad) - dy * sin(rad)
        py = cy + dx * sin(rad) + dy * cos(rad)
        return px, py

    def collide_point(self, x, y):
        lx, ly = self._touch_to_local(x, y)
        return self.x <= lx <= self.right and self.y <= ly <= self.top

    def _collide_point_local(self, lx, ly):
        return self.x <= lx <= self.right and self.y <= ly <= self.top

    # ------------------------------------------------------------------
    # Edit-mode overlay: pencil / bin / rotate handle / resize handle
    # ------------------------------------------------------------------
    def _overlay_widgets(self):
        return [
            w
            for w in (
                self._edit_btn,
                self._delete_btn,
                self._rotate_handle,
                self._resize_handle,
            )
            if w is not None
        ]

    def _build_edit_overlay(self):
        self._edit_btn = OverlayIconButton(
            target=self,
            icon="pencil",
            size_hint=(None, None),
            size=(HANDLE_SIZE, HANDLE_SIZE),
            theme_text_color="Custom",
            text_color=GOLD,
            md_bg_color=(0.05, 0.05, 0.05, 0.85),
            opacity=0,
            disabled=True,
            on_release=lambda *a: self.dispatch("on_edit_request"),
        )

        self._delete_btn = OverlayIconButton(
            target=self,
            icon="trash-can-outline",
            size_hint=(None, None),
            size=(HANDLE_SIZE, HANDLE_SIZE),
            theme_text_color="Custom",
            text_color=(0.9, 0.35, 0.35, 1),
            md_bg_color=(0.05, 0.05, 0.05, 0.85),
            opacity=0,
            disabled=True,
            on_release=lambda *a: self.dispatch("on_delete_request"),
        )

        self._resize_handle = ResizeHandle(
            target=self,
            icon="arrow-top-right-bottom-left",
            size_hint=(None, None),
            size=(HANDLE_SIZE, HANDLE_SIZE),
            theme_text_color="Custom",
            text_color=GOLD,
            md_bg_color=(0.05, 0.05, 0.05, 0.85),
            opacity=0,
            disabled=True,
        )

        self._rotate_handle = RotateHandle(
            target=self,
            icon="rotate-3d-variant",
            size_hint=(None, None),
            size=(HANDLE_SIZE, HANDLE_SIZE),
            theme_text_color="Custom",
            text_color=GOLD,
            md_bg_color=(0.05, 0.05, 0.05, 0.85),
            opacity=0,
            disabled=True,
        )

        for w in self._overlay_widgets():
            super().add_widget(w)

        self._position_overlay_handles()
        self._update_overlay_visibility()

    def _position_overlay_handles(self, *args):
        """Positions all four edit-mode handles fully OUTSIDE the wrapper's
        own rectangle, using a fixed dp margin rather than pos_hint (which
        is a fraction of the wrapper's own width/height — fine for large
        elements, but on a small one, e.g. at MIN_ELEMENT_SIZE, pos_hint
        corner placement kept the handles effectively on top of each
        other or overlapping the control itself).

        Edit and resize both anchor off the TOP corners but diverge
        outward diagonally (up-left vs up-right) rather than both sitting
        along the top edge, so they stay clear of each other no matter
        how small or narrow the element is.
        """
        margin = dp(6)

        if self._edit_btn is not None:
            # Outside the top-left corner: handle's bottom-right corner
            # touches the wrapper's top-left corner (plus margin).
            self._edit_btn.right = self.x - margin
            self._edit_btn.y = self.top + margin

        if self._delete_btn is not None:
            # Outside the bottom-left corner: handle's top-right corner
            # touches the wrapper's bottom-left corner (plus margin).
            self._delete_btn.right = self.x - margin
            self._delete_btn.top = self.y - margin

        if self._resize_handle is not None:
            # Outside the top-right corner: handle's bottom-left corner
            # touches the wrapper's top-right corner (plus margin).
            self._resize_handle.x = self.right + margin
            self._resize_handle.y = self.top + margin

        if self._rotate_handle is not None:
            # Unchanged: centered above the wrapper, already outside.
            self._rotate_handle.center_x = self.center_x
            self._rotate_handle.y = self.top + margin + dp(4)

    def _on_edit_or_select_change(self, *args):
        self._update_border()
        self._update_overlay_visibility()

    def _update_overlay_visibility(self, *args):
        visible = self.edit_mode and self.selected
        for w in self._overlay_widgets():
            w.opacity = 1 if visible else 0
            w.disabled = not visible

    def on_edit_request(self, *args):
        pass

    def on_delete_request(self, *args):
        pass

    # ------------------------------------------------------------------
    # Selection border
    # ------------------------------------------------------------------
    def _update_border(self, *args):
        self._border_group.clear()
        if self.edit_mode:
            if self.selected:
                self._border_group.add(Color(*GOLD))
                self._border_group.add(
                    Line(rectangle=(self.x, self.y, self.width, self.height), width=2)
                )
            else:
                self._border_group.add(Color(1, 1, 1, 0.3))
                self._border_group.add(
                    Line(
                        rectangle=(self.x, self.y, self.width, self.height),
                        width=1,
                        dash_length=4,
                        dash_offset=4,
                    )
                )

    # ------------------------------------------------------------------
    # Touch handling
    # ------------------------------------------------------------------
    def on_touch_down(self, touch):
        parent_touch_pos = (touch.x, touch.y)

        if self.edit_mode:
            # Check overlay chrome first in unmodified parent space
            for overlay in self._overlay_widgets():
                if overlay.opacity and not overlay.disabled and overlay.collide_point(*touch.pos):
                    if overlay.on_touch_down(touch):
                        return True

            # If inside wrapper bounds, initiate whole-body drag in parent coordinates
            if self.collide_point(*touch.pos):
                touch.grab(self)
                self.touch_start_pos = parent_touch_pos
                self.initial_pos = (self.x, self.y)
                if self.parent:
                    for child in self.parent.children:
                        if isinstance(child, HUDElementWrapper):
                            child.selected = (child is self)
                return True

            return super().on_touch_down(touch)

        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        touch.push()
        touch.apply_transform_2d(self._touch_to_local)
        ret = super().on_touch_down(touch)

        # If the main control grabbed this touch to track an ongoing
        # gesture (MDSlider dragging, MDRaisedButton pressed), hijack
        # that grab: ungrab the child and grab it ourselves instead.
        # Kivy's grab-redispatch calls the grabbing widget DIRECTLY for
        # every subsequent on_touch_move/on_touch_up -- bypassing this
        # wrapper's on_touch_move/on_touch_up (and the
        # apply_transform_2d() rotation compensation above, which only
        # ever runs during this initial top-down dispatch) entirely.
        # SKIPPED for widgets that already have a `target` property
        # (TouchJoystick, ScalableToggle) -- those handle rotation
        # compensation themselves via target._touch_to_local(), and
        # hijacking their grab here would fight with (and break) that
        # already-working mechanism instead of complementing it.
        if self._main_control is not None and not hasattr(self._main_control, "target"):
            try:
                touch.ungrab(self._main_control)
            except Exception:
                pass
            touch.grab(self)
            self._touch_child_map[touch] = self._main_control

        touch.pop()
        return ret

    def on_touch_move(self, touch):
        child = self._touch_child_map.get(touch)
        if touch.grab_current is self and child is not None:
            touch.push()
            touch.apply_transform_2d(self._touch_to_local)
            # Temporarily present as the child's own grab, matching what
            # Kivy's own redispatch loop does internally
            # (touch.grab_current = x; x.dispatch(...)) -- so the
            # child's internal "touch.grab_current is self"-style checks
            # (the standard Kivy idiom for grabbed-touch widgets, and
            # exactly what MDSlider/ButtonBehavior/etc. use) still pass
            # correctly, now with correctly-transformed coordinates.
            touch.grab_current = child
            child.dispatch("on_touch_move", touch)
            touch.grab_current = self
            touch.pop()
            return True

        if touch.grab_current is self and self.edit_mode:
            dx = touch.x - self.touch_start_pos[0]
            dy = touch.y - self.touch_start_pos[1]
            if self.parent:
                parent_w, parent_h = self.parent.width, self.parent.height

                # self.width/self.height are always the UNROTATED
                # bounding box -- Kivy's canvas Rotate is purely cosmetic
                # and never swaps these properties, even at 90/270
                # degrees where the VISUAL footprint is actually
                # taller-than-wide (or vice versa) relative to them.
                # Clamping directly against self.width/self.height
                # overestimates how much horizontal room a 90-degree-
                # rotated wide-short element (e.g. a slider) visually
                # needs, which is why it refused to go near the screen
                # edge -- the clamp still reserved the full unrotated
                # width even though the rotated visual only occupies a
                # fraction of that horizontally. Compute the true
                # rotated axis-aligned bounding box instead, and clamp
                # against that.
                angle_rad = radians(self.rotation)
                cos_a = abs(cos(angle_rad))
                sin_a = abs(sin(angle_rad))
                effective_w = self.width * cos_a + self.height * sin_a
                effective_h = self.width * sin_a + self.height * cos_a

                # The rotated visual is centered on self.center, so its
                # effective bounding box extends (effective_w - width)/2
                # further out (or in) from self.x than the unrotated box
                # does on each side. Fold that delta into the clamp
                # range for self.x/self.y directly.
                half_w_delta = (effective_w - self.width) / 2
                half_h_delta = (effective_h - self.height) / 2

                min_x = half_w_delta
                max_x = parent_w - self.width - half_w_delta
                min_y = half_h_delta
                max_y = parent_h - self.height - half_h_delta

                # If the element is bigger than its parent along an axis
                # (min > max), fall back to centering it on that axis
                # rather than leaving pos unclamped/inconsistent.
                if min_x > max_x:
                    new_x = (parent_w - self.width) / 2
                else:
                    new_x = max(min_x, min(max_x, self.initial_pos[0] + dx))
                if min_y > max_y:
                    new_y = (parent_h - self.height) / 2
                else:
                    new_y = max(min_y, min(max_y, self.initial_pos[1] + dy))

                self.pos = (new_x, new_y)
            return True

        # Pass grabbed overlay touches unmodified in parent space
        if self.edit_mode and touch.grab_current in self._overlay_widgets():
            return super().on_touch_move(touch)

        touch.push()
        touch.apply_transform_2d(self._touch_to_local)
        ret = super().on_touch_move(touch)
        touch.pop()
        return ret

    def on_touch_up(self, touch):
        child = self._touch_child_map.pop(touch, None)
        if touch.grab_current is self and child is not None:
            touch.push()
            touch.apply_transform_2d(self._touch_to_local)
            touch.grab_current = child
            child.dispatch("on_touch_up", touch)
            touch.grab_current = self
            touch.pop()
            touch.ungrab(self)
            return True

        if touch.grab_current is self:
            touch.ungrab(self)
            return True

        if self.edit_mode and touch.grab_current in self._overlay_widgets():
            return super().on_touch_up(touch)

        touch.push()
        touch.apply_transform_2d(self._touch_to_local)
        ret = super().on_touch_up(touch)
        touch.pop()
        return ret

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def to_dict(self):
        data = {
            "input_id": self.input_id,
            "element_type": self.element_type,
            "command_template": self.command_template,
            "pos_hint_x": (
                round(self.x / self.parent.width, 3)
                if self.parent and self.parent.width
                else 0
            ),
            "pos_hint_y": (
                round(self.y / self.parent.height, 3)
                if self.parent and self.parent.height
                else 0
            ),
            "size_dp": [self.width, self.height],
            "rotation": self.rotation,
        }
        if self.element_type == "slider":
            data["min_val"] = self.min_val
            data["max_val"] = self.max_val
            # Default is always the midpoint of the range, never stored
            # independently.
            data["default_val"] = (self.min_val + self.max_val) / 2
        elif self.element_type == "joystick":
            data["self_centering"] = self.self_centering
        return data

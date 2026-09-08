import math
from kivy.graphics import Color, Ellipse, Line
from kivy.properties import BooleanProperty, ObjectProperty
from kivy.uix.widget import Widget

class TouchJoystick(Widget):
    target_callback = ObjectProperty(None)
    # When True (default), releasing the touch snaps the knob back to
    # center and dispatches (0, 0) -- the classic joystick behavior. When
    # False, the knob (and the last-sent command) stays wherever it was
    # released, for throttle/sustained-value style controls.
    self_centering = BooleanProperty(True)

    # Reference to the containing HUDElementWrapper, auto-wired by
    # HUDElementWrapper.add_widget() (it duck-types any main control with
    # a `target` property). Used to independently transform touch
    # coordinates into the wrapper's rotated local space during a grabbed
    # on_touch_move. Necessary because Kivy's grab-redispatch mechanism
    # calls this widget's on_touch_move DIRECTLY once it has grabbed a
    # touch, bypassing the wrapper's own on_touch_move entirely -- and
    # with it, the rotation compensation the wrapper applies during the
    # normal top-down dispatch pass. Without this, dragging a rotated
    # joystick moves the knob according to raw screen-space direction
    # instead of the joystick's own rotated frame (e.g. at 90 degrees,
    # dragging right moves the knob "down" instead).
    target = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pad_x = 0
        self.pad_y = 0
        self.bind(pos=self._update_graphics, size=self._update_graphics)

    def _update_graphics(self, *args):
        self.canvas.before.clear()
        self.canvas.after.clear()

        radius = min(self.width, self.height) / 2
        center_x = self.x + (self.width / 2)
        center_y = self.y + (self.height / 2)

        with self.canvas.before:
            Color(0.83, 0.68, 0.21, 0.3)
            Ellipse(pos=(center_x - radius, center_y - radius), size=(radius * 2, radius * 2))
            Color(0.83, 0.68, 0.21, 1.0)
            Line(circle=(center_x, center_y, radius), width=1.5)

            # Top notch: a slight pale-yellow line inside the circle,
            # marking "up" in the joystick's own unrotated local space.
            # Since the whole HUDElementWrapper (including this widget's
            # canvas) is drawn inside the wrapper's
            # PushMatrix/Rotate/PopMatrix instructions, this line rotates
            # along with everything else automatically -- nothing here
            # needs to know the wrapper's current rotation.
            Color(1, 1, 0.75, 0.65)
            Line(
                points=[
                    center_x, center_y + radius * 0.35,
                    center_x, center_y + radius * 0.85,
                ],
                width=1.2,
            )

        with self.canvas.after:
            knob_radius = radius * 0.35
            knob_x = center_x + (self.pad_x * radius) - knob_radius
            knob_y = center_y + (self.pad_y * radius) - knob_radius

            Color(0.83, 0.68, 0.21, 0.9)
            Ellipse(pos=(knob_x, knob_y), size=(knob_radius * 2, knob_radius * 2))

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            touch.grab(self)
            # touch.x/y here are ALREADY in the wrapper's local/unrotated
            # space -- this event arrived via the normal top-down
            # dispatch, which HUDElementWrapper.on_touch_down transforms
            # before handing off to children. No extra transform needed.
            self._handle_touch(touch.x, touch.y)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            # Grabbed move events are dispatched directly to this widget,
            # bypassing the wrapper's rotation transform entirely -- so
            # touch.x/y here are RAW window/parent-space coordinates.
            # Transform them ourselves via the wrapper's own inverse-
            # rotation math (same helper the resize/rotate handles use).
            if self.target is not None:
                lx, ly = self.target._touch_to_local(touch.x, touch.y)
            else:
                lx, ly = touch.x, touch.y
            self._handle_touch(lx, ly)
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            if self.self_centering:
                self.pad_x = 0
                self.pad_y = 0
                self._update_graphics()
                self._dispatch_vector(0, 0)
            return True
        return super().on_touch_up(touch)

    def _handle_touch(self, local_x, local_y):
        """local_x/local_y must already be in this widget's own unrotated
        local coordinate space -- see call sites in on_touch_down/move for
        how each one gets there."""
        radius = min(self.width, self.height) / 2
        center_x = self.x + (self.width / 2)
        center_y = self.y + (self.height / 2)

        dx = local_x - center_x
        dy = local_y - center_y
        dist = math.hypot(dx, dy)

        if dist == 0:
            self.pad_x, self.pad_y = 0, 0
        else:
            clamped_dist = min(dist, radius)
            self.pad_x = (dx / dist) * (clamped_dist / radius)
            self.pad_y = (dy / dist) * (clamped_dist / radius)

        self._update_graphics()
        self._dispatch_vector(round(self.pad_x, 2), round(self.pad_y, 2))

    def _dispatch_vector(self, x, y):
        if self.target_callback:
            self.target_callback(x, y)

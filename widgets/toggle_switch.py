from kivy.graphics import Color, Ellipse, RoundedRectangle
from kivy.properties import BooleanProperty, ObjectProperty
from kivy.uix.widget import Widget


class ScalableToggle(Widget):
    """A simple track + thumb toggle switch, drawn entirely from
    self.width/self.height/self.pos on every redraw -- the same approach
    TouchJoystick already uses successfully, and it scales correctly at
    any size for the same reason: there's no fixed "native size" hiding
    anywhere, every coordinate is computed fresh from current geometry.

    This exists because MDSwitch does not scale its internal track/thumb
    proportionally when resized (confirmed: the thumb's travel distance
    stays hardcoded to its native size), and wrapping it in a Scatter to
    apply a pure visual scale transform turned out to have real
    positioning problems in practice (rendering outside its container
    and growing too large) that weren't worth continuing to debug blind
    against Scatter's internal transform-anchor semantics.

    `active` mirrors MDSwitch's own property name so this is a drop-in
    replacement for existing `switch.bind(active=...)` callers.
    """

    active = BooleanProperty(False)

    # Reference to the containing HUDElementWrapper, auto-wired by
    # HUDElementWrapper.add_widget() (it duck-types any main control with
    # a `target` property). Kivy's grab-redispatch calls on_touch_up
    # directly on this widget once it has grabbed a touch, bypassing the
    # wrapper's rotation-compensating transform entirely. Without this,
    # tapping a rotated toggle could fail to register (touch.pos would be
    # raw window coordinates compared against this widget's rotated
    # local bounds).
    target = ObjectProperty(None, allownone=True)

    ON_TRACK_COLOR = (0.83, 0.68, 0.21, 1)
    OFF_TRACK_COLOR = (0.35, 0.35, 0.35, 1)
    THUMB_COLOR = (0.95, 0.95, 0.95, 1)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(
            pos=self._update_graphics,
            size=self._update_graphics,
            active=self._update_graphics,
        )
        self._update_graphics()

    def _update_graphics(self, *args):
        self.canvas.before.clear()

        if self.width <= 0 or self.height <= 0:
            return

        track_h = self.height * 0.55
        track_y = self.y + (self.height - track_h) / 2
        track_radius = track_h / 2

        thumb_d = min(track_h * 1.35, self.height)
        thumb_y = self.y + (self.height - thumb_d) / 2
        travel = max(0, self.width - thumb_d)
        thumb_x = self.x + (travel if self.active else 0)

        with self.canvas.before:
            Color(*(self.ON_TRACK_COLOR if self.active else self.OFF_TRACK_COLOR))
            RoundedRectangle(
                pos=(self.x, track_y),
                size=(self.width, track_h),
                radius=[track_radius],
            )
            Color(*self.THUMB_COLOR)
            Ellipse(pos=(thumb_x, thumb_y), size=(thumb_d, thumb_d))

    def on_touch_down(self, touch):
        # touch.pos here is already in the wrapper's local/unrotated
        # space -- this arrives via the normal top-down dispatch, which
        # HUDElementWrapper.on_touch_down transforms before handing off
        # to children. No extra transform needed (matches TouchJoystick).
        if self.collide_point(*touch.pos):
            touch.grab(self)
            return True
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            # Grabbed touch_up is dispatched directly to this widget,
            # bypassing the wrapper's rotation transform -- touch.x/y
            # here are RAW window/parent-space coordinates, so transform
            # them ourselves before checking collision (same fix as
            # TouchJoystick.on_touch_move).
            if self.target is not None:
                lx, ly = self.target._touch_to_local(touch.x, touch.y)
            else:
                lx, ly = touch.x, touch.y
            if self.collide_point(lx, ly):
                self.active = not self.active
            return True
        return super().on_touch_up(touch)

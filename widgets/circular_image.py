from kivy.factory import Factory
from kivy.graphics import Color, Ellipse, Line
from kivy.loader import Loader
from kivy.properties import ListProperty, NumericProperty, StringProperty
from kivy.resources import resource_find
from kivy.uix.widget import Widget


class CircularImage(Widget):
    """Loads an image from a local path or URL and draws it clipped to a
    centered circle, with a thin ring border. Used for profile photos on
    the About screen.

    Drawing the texture straight into an Ellipse (rather than masking a
    normal Image with a stencil) keeps it to a handful of canvas
    instructions that update cleanly on resize. The source texture is
    centre-cropped to a square via tex_coords so a non-square photo isn't
    squashed into the circle.
    """

    source = StringProperty("")
    ring_color = ListProperty([0.83, 0.68, 0.21, 1])
    ring_width = NumericProperty(1.2)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._texture = None
        self._proxy = None
        with self.canvas:
            # Placeholder disc shown until (and if) the image loads.
            self._bg_color = Color(0.18, 0.18, 0.18, 1)
            self._bg = Ellipse(pos=self.pos, size=self.size)
            self._img_color = Color(1, 1, 1, 0)
            self._img = Ellipse(pos=self.pos, size=self.size)
            self._ring_col = Color(*self.ring_color)
            self._ring = Line(
                circle=(self.center_x, self.center_y, 1),
                width=self.ring_width,
            )
        self.bind(
            pos=self._redraw,
            size=self._redraw,
            source=self._load,
            ring_color=self._sync_ring,
        )
        if self.source:
            self._load()

    def _sync_ring(self, *_):
        self._ring_col.rgba = self.ring_color

    def _load(self, *_):
        self._texture = None
        src = self.source
        if not src:
            self._redraw()
            return
        # Resolve bundled/relative asset paths (e.g. "assets/images/x.jpeg")
        # against Kivy's resource search path; leave URLs untouched.
        if "://" not in src:
            src = resource_find(src) or src
        self._proxy = Loader.image(src)
        self._proxy.bind(on_load=self._on_loaded)
        # Already cached / decoded synchronously by the Loader.
        if self._proxy.loaded and self._proxy.image is not None:
            self._on_loaded(self._proxy)
        else:
            self._redraw()

    def _on_loaded(self, proxy, *_):
        self._texture = getattr(proxy.image, "texture", None)
        self._redraw()

    def _redraw(self, *_):
        side = max(1.0, min(self.width, self.height))
        x = self.center_x - side / 2.0
        y = self.center_y - side / 2.0

        self._bg.pos = (x, y)
        self._bg.size = (side, side)
        self._img.pos = (x, y)
        self._img.size = (side, side)
        self._ring.circle = (self.center_x, self.center_y, side / 2.0)
        self._ring.width = self.ring_width

        if self._texture is not None:
            self._img_color.rgba = (1, 1, 1, 1)
            # get_region() gives a centre square crop while keeping the
            # source texture's own vertical-flip state intact. Assigning
            # a hand-built tex_coords tuple instead (an earlier approach)
            # ignored that flip and rendered every photo upside down.
            self._img.texture = self._square_crop(self._texture)
        else:
            self._img_color.rgba = (1, 1, 1, 0)

    @staticmethod
    def _square_crop(texture):
        tw, th = texture.size
        if not tw or not th:
            return texture
        side = min(tw, th)
        x = (tw - side) // 2
        y = (th - side) // 2
        try:
            return texture.get_region(x, y, side, side)
        except Exception:
            return texture


Factory.register("CircularImage", cls=CircularImage)

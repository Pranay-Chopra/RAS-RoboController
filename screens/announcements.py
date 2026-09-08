from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen

from widgets.android_webview import LockedWebView


class AnnouncementsScreen(MDScreen):
    """Displays a single, completely locked-down announcements page via
    a native Android WebView -- see widgets/android_webview.py for the
    lockdown details (no address bar, no navigation, no interaction at
    all beyond looking at it).

    The URL is hardcoded for now -- swap ANNOUNCEMENTS_URL for the real
    admin-managed page once it's designed and hosted.
    """

    # TODO: replace with the real hosted announcements page URL.
    ANNOUNCEMENTS_URL = "https://ieee-ras-lnmiit.netlify.app/announcements.html"

    def __init__(self, **kwargs):
        # Set BEFORE super().__init__() -- on_kv_post fires as a side
        # effect of that call (Kivy's own kv-building machinery), and it
        # reads self._webview immediately. Setting this after
        # super().__init__() meant on_kv_post ran into an AttributeError
        # before this line ever got a chance to execute.
        self._webview = None
        self._is_active = False
        super().__init__(**kwargs)

    def switch_screen(self, screen_name: str) -> None:
        """Dispatches screen transition requests, matching the pattern
        used by every other screen in the app."""
        app = MDApp.get_running_app()
        if hasattr(app, "root") and app.root:
            if hasattr(app.root, "current"):
                app.root.current = screen_name

    def on_kv_post(self, base_widget):
        """Fires once this screen's kv rule has finished building, so
        self.ids.webview_container/nav_drawer are guaranteed to exist --
        unlike in __init__, where kv-assigned ids aren't populated yet."""
        if self._webview is None:
            self._webview = LockedWebView(
                url=self.ANNOUNCEMENTS_URL, size_hint=(1, 1)
            )
            self.ids.webview_container.add_widget(self._webview)

        # The native WebView is a real Android View layered above Kivy's
        # ENTIRE OpenGL rendering surface -- that's just how mixing
        # native views with Kivy/SDL2 works, and it isn't part of
        # Kivy's own widget z-ordering at all. The nav drawer is purely
        # Kivy-rendered content that slides in from the side within
        # that same surface, so no matter how its z-order is set within
        # Kivy, it can never visually appear above a view layered
        # outside Kivy entirely. Hiding the WebView whenever the drawer
        # opens (and re-showing it on close, but only if this screen is
        # still the active one) is what keeps the drawer visible
        # instead of being covered.
        self.ids.nav_drawer.bind(state=self._on_drawer_state)

    def _on_drawer_state(self, instance, value):
        if self._webview is None:
            return
        if value == "open":
            self._webview.reload()
            self._webview.hide()
        elif self._is_active:
            self._webview.reload()
            self._webview.show()

    def on_pre_enter(self):
        # Fires BEFORE the screen transition animation starts (unlike
        # on_enter, which fires during/after it) -- since show() is an
        # async call to Android's UI thread (@run_on_ui_thread), firing
        # it as early as possible gives it the best chance of actually
        # landing in sync with Kivy's own transition instead of the raw
        # WebView visibly popping in a beat late.
        self._is_active = True
        if self._webview is not None:
            self._webview.reload()
            self._webview.show()

    def on_pre_leave(self):
        self._is_active = False
        if self._webview is not None:
            self._webview.reload()
            self._webview.hide()

    def open_nav_drawer(self):
        """Bound to the hamburger icon instead of calling
        nav_drawer.set_state("toggle") directly. Hides the WebView
        synchronously (from Kivy's perspective) BEFORE the drawer even
        starts its own opening animation, rather than waiting to react
        to nav_drawer's state property changing afterward (see
        _on_drawer_state) -- that reactive path is still needed as a
        fallback for swipe-to-open (which doesn't go through this
        method at all), but for the common tap case this removes most
        of the lag that let the drawer visibly open underneath the
        still-visible WebView.
        """
        if self._webview is not None:
            self._webview.reload()
            self._webview.hide()
        self.ids.nav_drawer.set_state("toggle")

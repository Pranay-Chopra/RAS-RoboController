"""Native Android WebView integration for the Announcements screen.

The only actual requirement is that the URL never becomes visible --
and that's satisfied for free by simply never adding any browser chrome
(address bar, menu, etc.) around the WebView. A bare android.webkit.WebView
has none of that by default, so there's nothing extra to lock down there.

This is otherwise a normal, interactive WebView: JavaScript and DOM
storage are enabled (the hosted page needs both to render), and touch
input reaches the page normally (scrolling, tapping links, etc.).

A stock, un-overridden WebViewClient is set purely so that if a link is
tapped, navigation stays inside the WebView instead of Android's default
behavior with no WebViewClient at all, which hands the link off to an
external browser app via an Intent -- popping the user out of the app
entirely, which would be a worse outcome than anything this file is
trying to prevent.

WHY THIS ISN'T ROUTING LINKS TO THE SYSTEM BROWSER: an earlier version
of this file tried intercepting navigation via a custom WebViewClient
subclass (overriding shouldOverrideUrlLoading) to route every tapped
link to Android's default browser instead of loading it here. That's
been reverted -- it crashed on-device with:

    AttributeError: '_ExternalLinkWebViewClient' object has no
    attribute '__javainterfaces__'

pyjnius's PythonJavaClass unconditionally requires __javainterfaces__
in its own __init__ (jnius_proxy.pxi's _init_j_self_ptr checks it
directly) -- meaning PythonJavaClass, at least in the pyjnius version
this project builds against, only supports implementing Java
INTERFACES (__javainterfaces__), not extending concrete Java classes.
The __javaclass__ attribute used in that attempt isn't a real supported
mechanism here; it was silently ignored while the base class's own
init still demanded __javainterfaces__ regardless, which is what
actually crashed. This is confirmed by an on-device traceback, not
just a suspected compatibility issue -- so it isn't worth attempting
again the same way.

The safety net that DOES work without any of this risk: see reload()
below and AnnouncementsScreen.on_pre_enter(), which reloads the
original announcements URL every time the screen is re-entered. If a
tapped link navigates this WebView away from the announcements content,
leaving the screen and coming back always resets it -- no WebViewClient
override needed for that part to work.
"""

from jnius import autoclass
from android.runnable import run_on_ui_thread

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.widget import Widget

WebView = autoclass("android.webkit.WebView")
WebViewClient = autoclass("android.webkit.WebViewClient")
FrameLayoutParams = autoclass("android.widget.FrameLayout$LayoutParams")
PythonActivity = autoclass("org.kivy.android.PythonActivity")
View = autoclass("android.view.View")


class LockedWebView(Widget):
    """A Kivy widget that creates a native Android WebView loading `url`
    and overlays it at this widget's exact screen position, kept in
    sync via pos/size bindings.

    Because this is a real Android View sitting in the same window, NOT
    part of Kivy's own canvas/ScreenManager-driven rendering, it stays
    visually on top of whatever else is on screen regardless of which
    Kivy screen is "current" unless explicitly hidden. Whoever owns this
    widget (e.g. AnnouncementsScreen) is responsible for calling
    show()/hide() from on_enter/on_leave.
    """

    def __init__(self, url, **kwargs):
        super().__init__(**kwargs)
        self.url = url
        self._native_view = None
        self.bind(pos=self._sync_geometry, size=self._sync_geometry)
        # NOTE: must be wrapped in a lambda, not passed directly.
        # Clock.schedule_once stores the callback via Kivy's WeakMethod,
        # which introspects a bound method's __name__ to know how to
        # re-fetch it later -- but @run_on_ui_thread (android.runnable)
        # doesn't preserve the original method's name on the function it
        # returns, so WeakMethod ends up trying to getattr() the
        # decorator's own internal wrapper name instead of
        # "_create_webview", crashing with an AttributeError. A lambda
        # sidesteps this entirely (see kivy/kivy#7007 for the same root
        # cause with any decorated method used as a Kivy callback).
        Clock.schedule_once(lambda dt: self._create_webview(), 0)

    @run_on_ui_thread
    def _create_webview(self, *args):
        activity = PythonActivity.mActivity

        webview = WebView(activity)
        settings = webview.getSettings()
        settings.setJavaScriptEnabled(True)
        settings.setDomStorageEnabled(True)

        # Stock, un-overridden WebViewClient -- see module docstring for
        # why this isn't a custom subclass.
        webview.setWebViewClient(WebViewClient())

        params = FrameLayoutParams(1, 1)
        activity.addContentView(webview, params)

        # Starts hidden. Every screen (including this one) is
        # constructed upfront in app.py's build(), so this fires at app
        # startup regardless of which Kivy screen is actually current --
        # and since this is a real Android View sitting in the same
        # window, entirely outside Kivy's ScreenManager, it would
        # otherwise stay visible on top of whatever screen IS current
        # (e.g. Home) until AnnouncementsScreen.on_enter() eventually
        # got around to calling show() for the first time. Only
        # show()/hide() (driven by on_enter/on_leave) control visibility
        # from here on.
        webview.setVisibility(View.GONE)

        webview.loadUrl(self.url)

        self._native_view = webview
        self._apply_geometry()

    def _sync_geometry(self, *args):
        if self._native_view is not None:
            self._apply_geometry()

    @run_on_ui_thread
    def _apply_geometry(self):
        if self._native_view is None:
            return
        # Kivy's origin is bottom-left with y increasing upward;
        # Android Views use top-left with y increasing downward.
        android_x = int(self.x)
        android_y = int(Window.height - self.y - self.height)
        params = FrameLayoutParams(int(self.width), int(self.height))
        params.leftMargin = android_x
        params.topMargin = android_y
        self._native_view.setLayoutParams(params)

    @run_on_ui_thread
    def show(self):
        if self._native_view is not None:
            self._native_view.setVisibility(View.VISIBLE)

    @run_on_ui_thread
    def reload(self):
        """Reloads the original URL this widget was constructed with,
        discarding whatever the WebView may have navigated to since.

        This is the actual working fix for "no way back to the
        announcements content": there's no back button, no address bar,
        and no working navigation-blocking override on this WebView
        (see module docstring) -- so if a tapped link navigates it
        away, there's otherwise no way back short of this. Called every
        time the screen is re-entered (AnnouncementsScreen.on_pre_enter),
        so leaving and coming back always resets to the correct content.
        """
        if self._native_view is not None:
            self._native_view.loadUrl(self.url)

    @run_on_ui_thread
    def hide(self):
        if self._native_view is not None:
            self._native_view.setVisibility(View.GONE)

    @run_on_ui_thread
    def destroy(self):
        if self._native_view is None:
            return
        try:
            parent = self._native_view.getParent()
            if parent is not None:
                parent.removeView(self._native_view)
        except Exception:
            pass
        self._native_view.destroy()
        self._native_view = None

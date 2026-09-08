import logging
import sys
import threading
from collections import deque
from datetime import datetime


class _TeeStream:
    """Wraps an original stream (stdout/stderr) so every write also lands
    in LogCapture's buffer. The original stream still receives everything
    completely unchanged -- this only additionally copies it, so logcat/
    console output (and anything else already reading stdout/stderr) is
    unaffected.

    This only ever sees plain print()-style output -- NOT Kivy's own
    Logger messages. Kivy's Logger binds its own StreamHandler to
    whatever sys.stdout object exists at the moment Kivy's logging
    machinery first sets itself up, and that reference is captured once,
    not re-read from sys.stdout on every write -- so replacing
    sys.stdout afterward (regardless of import order) doesn't route
    Kivy's own logging through this wrapper. See _CaptureLogHandler
    below for how Kivy's Logger is actually captured.
    """

    def __init__(self, original_stream, capture, tag):
        self._original = original_stream
        self._capture = capture
        self._tag = tag

    def write(self, data):
        self._original.write(data)
        if data:
            self._capture._append(self._tag, data)
        return len(data)

    def flush(self):
        self._original.flush()

    def __getattr__(self, name):
        # Delegate anything else (isatty, fileno, encoding, ...) to the
        # real stream so nothing else that touches sys.stdout/stderr breaks.
        return getattr(self._original, name)


class _CaptureLogHandler(logging.Handler):
    """A standard logging.Handler attached directly to Kivy's own Logger
    object -- the correct way to intercept Kivy's log output, since
    tee-ing sys.stdout does NOT reliably catch it (see _TeeStream's
    docstring). This handler's own level threshold (set in
    LogCapture.install(), via LogCapture.KIVY_LOG_LEVEL) is what filters
    out Kivy's routine startup chatter (OpenGL/window/provider probing,
    clock scheduling -- all typically INFO or below) while still keeping
    genuine Kivy-reported problems (WARNING and above).
    """

    def __init__(self, capture):
        super().__init__()
        self._capture = capture

    def emit(self, record):
        try:
            message = record.getMessage()
        except Exception:
            message = str(getattr(record, "msg", record))
        self._capture._append(f"KIVY:{record.levelname}", message)


class LogCapture:
    """In-memory ring buffer combining two sources:

    1. Everything printed via stdout/stderr (our own app's print() calls,
       plus stderr for uncaught tracebacks) since install() was called.
    2. Kivy's own Logger output, filtered to KIVY_LOG_LEVEL and above --
       via a dedicated logging.Handler, not stdout interception (which
       doesn't work for Kivy's Logger specifically -- see _TeeStream).

    Anything printed/logged before install() runs won't be captured --
    install() should be called as early as possible during app startup.
    One known, minor gap: Kivy's very first few startup banner lines
    (version numbers etc.) are emitted as a side effect of first
    importing kivy.logger itself, which is also the moment our handler
    gets attached -- those specific lines fire during that same import
    and can't be intercepted before the import call that triggers them
    returns. Everything after that point is captured normally.
    """

    MAX_LINES = 2000

    # Kivy's own Logger is very chatty at INFO level during startup
    # (OpenGL vendor/backend info, provider probing, window setup, clock
    # scheduling, ...) -- hundreds of lines that would otherwise crowd
    # out anything useful. WARNING and above is where Kivy actually
    # reports real problems (missing providers, failed texture loads,
    # deprecated API use, etc.). Lower this to logging.INFO (or
    # logging.DEBUG) if more Kivy detail is ever needed.
    KIVY_LOG_LEVEL = logging.WARNING

    def __init__(self):
        self._lines = deque(maxlen=self.MAX_LINES)
        self._lock = threading.Lock()
        self._installed = False

    def install(self):
        if self._installed:
            return

        sys.stdout = _TeeStream(sys.stdout, self, "OUT")
        sys.stderr = _TeeStream(sys.stderr, self, "ERR")

        try:
            from kivy.logger import Logger as KivyLogger
            handler = _CaptureLogHandler(self)
            handler.setLevel(self.KIVY_LOG_LEVEL)
            KivyLogger.addHandler(handler)
        except Exception as e:
            # Don't let a failure to hook into Kivy's Logger take the
            # whole app down -- the stdout/stderr capture above still
            # works regardless.
            print(f"[LogCapture] Could not attach to Kivy Logger: {e}")

        self._installed = True

    def _append(self, tag, data):
        text = data.rstrip("\n")
        if not text:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            for line in text.split("\n"):
                self._lines.append(f"[{timestamp}] [{tag}] {line}")

    def get_text(self, limit=None):
        """Returns captured log lines joined as one string, most recent
        last. `limit`, if given, returns only the last `limit` lines
        (for a lightweight live view) -- omit it to get everything
        currently buffered (for export)."""
        with self._lock:
            lines = list(self._lines)
        if limit is not None:
            lines = lines[-limit:]
        return "\n".join(lines)

    def clear(self):
        with self._lock:
            self._lines.clear()


# Module-level singleton, matching the existing connection_mgr singleton
# pattern in utils/control_engine.py.
log_capture = LogCapture()

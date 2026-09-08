"""Google OAuth2 sign-in for the Quiz feature (Android app).

Authorization Code flow with PKCE and a custom-scheme redirect
(com.googleusercontent.apps.<id>:/oauth2redirect) -- the AppAuth pattern
against an "iOS" type OAuth client (the only type Google gives a usable
custom scheme for a browser flow, with no client secret). After consent
the system browser redirects straight back into this app via the
intent-filter in android/oauth_redirect_intent.xml; p4a delivers it as
on_new_intent.

Sign-in only runs on Android -- there's no loopback/desktop path. Test
the quiz on a device (or an emulator with Google set up).

The id_token is consumed WITHOUT local signature verification: it comes
straight from Google's token endpoint over TLS in this process, which
Google's docs say is enough to trust its claims. The Apps Script backend
independently re-verifies every token via the tokeninfo endpoint.
"""

import base64
import hashlib
import json
import os
import threading
import time
import webbrowser
from urllib.parse import parse_qs, urlencode, urlparse

from kivy.clock import Clock
from kivy.utils import platform

try:
    import requests
except ImportError:  # handled gracefully by callers
    requests = None

import quiz_config

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_SCOPES = "openid email profile"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_jwt_payload(token: str) -> dict:
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64))


def open_url(url: str) -> None:
    """Open a URL in the device browser."""
    try:
        from jnius import autoclass

        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        act = PythonActivity.mActivity
        intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        act.startActivity(intent)
        return
    except Exception:
        pass
    try:
        webbrowser.open(url)
    except Exception:
        pass


class GoogleAuth:
    """Holds the current session and drives sign-in / token refresh.

    Public methods are safe to call from the Kivy thread; network work
    runs on a worker thread and every callback is delivered back on the
    main thread via Clock.
    """

    def __init__(self):
        from kivymd.app import MDApp

        data_dir = MDApp.get_running_app().user_data_dir
        self._path = os.path.join(data_dir, "quiz_session.json")
        self._session = {}
        self._busy = False
        self._verifier = None
        self._on_done = None
        self._activity_module = None
        self.load()

    # -- persistence ------------------------------------------------------
    def load(self):
        try:
            with open(self._path, "r") as f:
                self._session = json.load(f)
        except (OSError, ValueError):
            self._session = {}

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self._session, f)
        except OSError as e:
            print(f"[GoogleAuth] Could not persist session: {e}")

    # -- state ----------------------------------------------------------
    @property
    def is_signed_in(self) -> bool:
        return bool(self._session.get("refresh_token") or self._session.get("id_token"))

    @property
    def email(self) -> str:
        return self._session.get("email", "")

    @property
    def name(self) -> str:
        return self._session.get("name") or self.email

    @property
    def is_admin(self) -> bool:
        return quiz_config.is_admin_email(self.email)

    @property
    def is_busy(self) -> bool:
        return self._busy

    def sign_out(self):
        self._session = {}
        try:
            os.remove(self._path)
        except OSError:
            pass

    # -- sign-in ------------------------------------------------------
    def sign_in(self, on_done):
        """Interactive Google sign-in. on_done(ok: bool, error: str|None)
        fires on the main thread."""
        if platform != "android":
            Clock.schedule_once(
                lambda dt: on_done(
                    False, "Quiz sign-in runs on the Android app only."
                )
            )
            return
        if self._busy:
            Clock.schedule_once(lambda dt: on_done(False, "Sign-in already in progress"))
            return
        if requests is None:
            Clock.schedule_once(lambda dt: on_done(False, "'requests' library unavailable"))
            return
        if not quiz_config.is_configured():
            Clock.schedule_once(
                lambda dt: on_done(False, "Quiz backend not configured (see SETUP_QUIZ.md)")
            )
            return

        self._busy = True
        self._on_done = on_done
        self._verifier = _b64url(os.urandom(40))
        challenge = _b64url(hashlib.sha256(self._verifier.encode("ascii")).digest())

        params = {
            "client_id": quiz_config.GOOGLE_CLIENT_ID,
            "redirect_uri": quiz_config.OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": _SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            # UX hint only -- backend still enforces the domain.
            "hd": quiz_config.ALLOWED_EMAIL_DOMAINS[0],
        }

        from android import activity as activity_module

        self._activity_module = activity_module
        activity_module.bind(on_new_intent=self._on_new_intent)
        open_url(_AUTH_ENDPOINT + "?" + urlencode(params))

    def _finish(self, ok, error):
        self._busy = False
        cb, self._on_done = self._on_done, None
        self._verifier = None
        if self._activity_module is not None:
            try:
                self._activity_module.unbind(on_new_intent=self._on_new_intent)
            except Exception:
                pass
            self._activity_module = None
        if cb:
            Clock.schedule_once(lambda dt: cb(ok, error))

    def _on_new_intent(self, intent):
        try:
            data = intent.getData()
            if data is None:
                return
            uri = data.toString()
            if not uri.startswith(quiz_config.OAUTH_REDIRECT_SCHEME + ":"):
                return  # not our redirect
            params = parse_qs(urlparse(uri).query)
            code = params.get("code", [None])[0]
            err = params.get("error", [None])[0]
            if err:
                self._finish(False, f"Google returned: {err}")
                return
            if not code:
                self._finish(False, "No authorization code in redirect")
                return
            threading.Thread(
                target=self._exchange_worker, args=(code,), daemon=True
            ).start()
        except Exception as e:  # noqa: BLE001
            self._finish(False, str(e))

    def _exchange_worker(self, code):
        try:
            resp = requests.post(
                _TOKEN_ENDPOINT,
                data={
                    "client_id": quiz_config.GOOGLE_CLIENT_ID,
                    "code": code,
                    "code_verifier": self._verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": quiz_config.OAUTH_REDIRECT_URI,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                self._finish(False, f"Token exchange failed ({resp.status_code})")
                return
            self._store_tokens(resp.json())
        except Exception as e:  # noqa: BLE001
            self._finish(False, str(e))

    def _store_tokens(self, tok):
        try:
            claims = _decode_jwt_payload(tok["id_token"])
        except Exception:
            self._finish(False, "Google returned an unreadable token")
            return
        email = claims.get("email", "")
        if str(claims.get("email_verified")).lower() not in ("true", "1"):
            self._finish(False, "Your Google email is not verified")
            return
        if not quiz_config.is_allowed_email(email):
            self._finish(
                False, "Only LNMIIT (lnmiit.ac.in) accounts can use the quiz."
            )
            return
        self._session = {
            "email": email,
            "name": claims.get("name", email),
            "id_token": tok["id_token"],
            "id_token_exp": int(claims.get("exp", 0)),
            "refresh_token": tok.get("refresh_token")
            or self._session.get("refresh_token", ""),
        }
        self._save()
        self._finish(True, None)

    # -- token access -------------------------------------------------
    def get_valid_id_token(self, on_done):
        """on_done(token: str|None, error: str|None) on the main thread.
        Refreshes silently when the cached id_token is near expiry."""
        if not self.is_signed_in:
            Clock.schedule_once(lambda dt: on_done(None, "Not signed in"))
            return
        exp = self._session.get("id_token_exp", 0)
        if self._session.get("id_token") and time.time() < exp - 120:
            token = self._session["id_token"]
            Clock.schedule_once(lambda dt: on_done(token, None))
            return
        if requests is None:
            Clock.schedule_once(lambda dt: on_done(None, "'requests' library unavailable"))
            return
        threading.Thread(
            target=self._refresh_worker, args=(on_done,), daemon=True
        ).start()

    def _refresh_worker(self, on_done):
        try:
            refresh_token = self._session.get("refresh_token")
            if not refresh_token:
                Clock.schedule_once(
                    lambda dt: on_done(None, "Session expired, please sign in again")
                )
                return
            resp = requests.post(
                _TOKEN_ENDPOINT,
                data={
                    "client_id": quiz_config.GOOGLE_CLIENT_ID,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=30,
            )
            if resp.status_code != 200:
                Clock.schedule_once(
                    lambda dt: on_done(None, "Could not refresh session, sign in again")
                )
                return
            tok = resp.json()
            claims = _decode_jwt_payload(tok["id_token"])
            self._session["id_token"] = tok["id_token"]
            self._session["id_token_exp"] = int(claims.get("exp", 0))
            self._save()
            token = tok["id_token"]
            Clock.schedule_once(lambda dt: on_done(token, None))
        except Exception as e:  # noqa: BLE001
            Clock.schedule_once(lambda dt, err=e: on_done(None, str(err)))

"""Configuration + access rules for the Quiz feature.

Fill the PASTE_* values in after following SETUP_QUIZ.md.

A native OAuth client id is not a confidential secret (Google's docs say
installed apps can't keep one; the Android client type has no secret at
all), and the Apps Script URL only does anything for a caller holding a
valid lnmiit.ac.in Google token. Still, review ADMIN_EMAILS before
shipping a build.
"""

# --- Google OAuth2 ("iOS" client) ---------------------------------
# Google Cloud Console -> APIs & Services -> Credentials -> OAuth client
# ID -> Application type: "iOS".
#
# Yes, "iOS" -- it's the only client type that issues a usable
# custom-scheme redirect for a browser OAuth flow with no client secret
# and no SHA-1. The "Android" type ONLY works with Google's native Play
# Services sign-in SDK (which this Kivy app doesn't use); pointing a
# browser auth request at it gives "Error 400: invalid_request".
# Bundle ID when creating it: org.ieeeras.robocontroller (any reverse-DNS
# string works; it isn't checked at runtime).
GOOGLE_CLIENT_ID = "1090468690005-do85caobta0nv2fjgbvmqijcc5hs4p3k.apps.googleusercontent.com"


def _reversed_client_id() -> str:
    """The 'iOS URL scheme' Google derives from an iOS client id:
    com.googleusercontent.apps.<client-id minus the .apps... suffix>."""
    base = GOOGLE_CLIENT_ID.split(".apps.googleusercontent.com")[0]
    return "com.googleusercontent.apps." + base


# Where the browser bounces back to. The SCHEME half must ALSO be pasted
# literally into android/oauth_redirect_intent.xml -- Android can't
# template a manifest <data android:scheme>.
OAUTH_REDIRECT_SCHEME = _reversed_client_id()
OAUTH_REDIRECT_URI = OAUTH_REDIRECT_SCHEME + ":/oauth2redirect"

# --- Backend (Google Apps Script web app) ----------------------------
# The ".../exec" URL you get from deploying backend/quiz_backend.gs.
BACKEND_URL = "https://script.google.com/macros/s/AKfycbw6mWOOblOk4-8xk6DUYdMHTB_pEjk1KBtVsItcMQkMcWXCzHhd0SkU6btNwje-74mq/exec"

# --- Access control -------------------------------------------------
# A signed-in Google account may take quizzes only if its email ends in
# one of these domains. "lnmiit.ac.in" also matches "x@dept.lnmiit.ac.in"
# (i.e. the "*.lnmiit.ac.in" ask) via the suffix check below.
ALLOWED_EMAIL_DOMAINS = ("lnmiit.ac.in",)

# Exact addresses (case-insensitive) allowed to POST problems and view
# everyone's results. Everyone else can only take the quiz + see their
# own score.
ADMIN_EMAILS = (
    "25ucs115@lnmiit.ac.in",
)


def is_allowed_email(email: str) -> bool:
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1]
    return any(
        domain == d or domain.endswith("." + d)
        for d in (x.lower() for x in ALLOWED_EMAIL_DOMAINS)
    )


def is_admin_email(email: str) -> bool:
    email = (email or "").strip().lower()
    return email in {e.strip().lower() for e in ADMIN_EMAILS}


def is_configured() -> bool:
    """True once the placeholders above have actually been filled in."""
    return not (
        GOOGLE_CLIENT_ID.startswith("PASTE_")
        or BACKEND_URL.startswith("PASTE_")
    )

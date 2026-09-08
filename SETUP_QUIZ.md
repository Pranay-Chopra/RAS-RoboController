# Quiz feature — one-time setup

The Quiz screen needs two things wired up: a **Google OAuth client** (so
students sign in with their `@lnmiit.ac.in` account) and a **Google Apps
Script backend** (a Google Sheet + a tiny web app that stores problems
and results). No Firebase, no server, no billing — all on a normal
Google account.

You'll end up filling in two values in **`quiz_config.py`**, one scheme
in **`android/oauth_redirect_intent.xml`**, and three in
**`backend/quiz_backend.gs`**.

---

## 1. Google Cloud — OAuth client (type: iOS)

Sign-in is the AppAuth pattern: tap → system browser → consent → Android
reopens the app via a `com.googleusercontent.apps.<id>:/oauth2redirect`
scheme. PKCE, **no client secret**.

> **Why "iOS" and not "Android"?** Google's *Android* OAuth client only
> works with the native Play Services sign-in SDK, which this Kivy app
> doesn't bundle — pointing a browser auth request at it returns
> `Error 400: invalid_request`. The *iOS* client type is the one that
> hands you a working custom-scheme redirect for a plain browser flow,
> with no secret and no SHA‑1. It is not checked against a real iOS app.

**Sign-in only works in the built Android APK**, not `python main.py` on
a desktop.

1. Go to <https://console.cloud.google.com/> and create a project
   (e.g. `ras-robocontroller`).
2. **APIs & Services → OAuth consent screen**
   - User type: **Internal** if `lnmiit.ac.in` is a Google Workspace org
     (restricts sign-in to the org, free). Otherwise **External** — keep
     it in "Testing" (≤100 users) or publish it; the app + backend still
     enforce the `lnmiit.ac.in` domain regardless.
   - App name, support email, developer email — fill in, save.
   - Scopes: none beyond the defaults (`openid`, `email`, `profile`).
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **iOS**
   - Name: `RoboController`
   - Bundle ID: `org.ieeeras.robocontroller` (any reverse-DNS string;
     not verified at runtime — matching the Android package is just tidy)
   - Create. Copy the **Client ID**, and note the **iOS URL scheme**
     Google shows (it's the client id reversed:
     `com.googleusercontent.apps.<client-id-without-.apps...>`).

4. Paste into **two** files:
   - `quiz_config.py`:
     ```python
     GOOGLE_CLIENT_ID = "1234-abcd.apps.googleusercontent.com"
     ```
     (`OAUTH_REDIRECT_SCHEME` / `OAUTH_REDIRECT_URI` are derived from it.)
   - `android/oauth_redirect_intent.xml` — replace the placeholder
     scheme with the **iOS URL scheme** from step 3:
     ```xml
     <data android:scheme="com.googleusercontent.apps.1234-abcd" />
     ```
     Android can't template a manifest value, so this one's a manual
     paste. It must match `OAUTH_REDIRECT_SCHEME`.

No redirect URI, SHA‑1, or package registration is needed for an iOS
client — Google derives the allowed scheme from the client id itself.

---

## 2. Google Apps Script — backend

1. Create a new Google Sheet (any name, e.g. `RAS Quiz Data`). Leave it
   empty — the script makes the `Problems` and `Results` tabs itself.
2. In that sheet: **Extensions → Apps Script**.
3. Delete the stub `Code.gs` content and paste all of
   **`backend/quiz_backend.gs`** from this repo.
4. Edit the CONFIG block at the top of the script:
   ```javascript
   var CLIENT_ID = 'SAME client id as quiz_config.GOOGLE_CLIENT_ID';
   var ALLOWED_DOMAINS = ['lnmiit.ac.in'];
   var ADMIN_EMAILS = ['your.id@lnmiit.ac.in'];   // exact addresses
   // var SPREADSHEET_ID = '';  // leave blank — uses this bound sheet
   ```
5. **Deploy → New deployment → type: Web app**
   - Description: `quiz v1`
   - Execute as: **Me**
   - Who has access: **Anyone**
   - Deploy. Approve the permission prompt (it needs to call Google's
     token-info endpoint and edit this sheet).
   - Copy the **Web app URL** — it ends in `/exec`.
6. Put it in `quiz_config.py`:
   ```python
   BACKEND_URL = "https://script.google.com/macros/s/AKfycb..../exec"
   ```

> Re-deploying after code edits: **Deploy → Manage deployments → edit
> (pencil) → Version: New version → Deploy.** The `/exec` URL stays the
> same.

---

## 3. Admin whitelist

Two places, keep them identical:

- `quiz_config.py` → `ADMIN_EMAILS = ("a@lnmiit.ac.in", "b@lnmiit.ac.in")`
  — controls what the **app UI** shows (the "Post Problem" / "View
  Results" buttons).
- `backend/quiz_backend.gs` → `var ADMIN_EMAILS = [...]` — the actual
  enforcement. A non-admin calling the admin actions directly is
  rejected server-side.

Matching is case-insensitive, exact address (not domain).

---

## 4. Try it

- Install the built APK on a device. **Quiz** in the drawer → **Sign in
  with Google**. The system browser opens; after you approve, Android
  drops you straight back in the app and it loads the quiz.
- Only `@lnmiit.ac.in` (and `@*.lnmiit.ac.in` subdomains) are accepted —
  anything else is rejected after sign-in with a message.
- As an admin: **Post Problem** adds a multiple-choice question;
  **View Results** lists every submission (also visible directly in the
  `Results` tab of your sheet).
- Students: answer all questions → **Submit** → see the score + which
  ones were right.

---

## How it hangs together

```
app (Kivy / Android)               Google                 Apps Script + Sheet
────────────────────               ──────                 ───────────────────
tap sign in ──browser + PKCE─────▶ consent
   ◀─ redirect org.ieeeras.robocontroller:/oauth2redirect?code=…
        ──exchange code (no secret)─▶
        ◀──── id_token ────────────
list_problems / submit / ...  ──── id_token in POST body ─▶ verify token
                                                            check domain+admin
                                                            read/write Sheet
        ◀──────────────── JSON {ok, data} ────────────────
```

- The app trusts the `id_token` it gets **straight from Google over
  TLS** (per Google's docs) and only reads the email/name from it.
- The backend **re-verifies every token** via
  `oauth2.googleapis.com/tokeninfo`, checks `aud` == your client id, the
  expiry, `email_verified`, the domain, and the admin list — so a
  tampered app build still can't post problems or read results.
- Deleting a problem is a soft-delete (`active=false`) so past results
  still show the question text.

## Notes / limits

- Apps Script free quota is ~20k `UrlFetch` calls/day and generous
  script runtime — fine for a class-sized quiz.
- `requests` is already added to `buildozer.spec`. (`pip install
  requests` too if you want to run non-quiz parts of the app locally.)
- `Error 400: invalid_request` on the consent page → the OAuth client is
  the wrong type. It must be **iOS** (see step 1's note), not Android or
  Web.
- Consent works but the app never comes back → the `<data
  android:scheme>` in `android/oauth_redirect_intent.xml` doesn't match
  the iOS URL scheme / `OAUTH_REDIRECT_SCHEME`. Fix it and rebuild the
  APK (a manifest change needs a fresh build).
- Rare: if Android kills the app while the browser is open, the redirect
  may not resume automatically. Just reopen the app and tap sign-in
  again.

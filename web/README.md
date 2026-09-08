# RAS Quiz — web version

A browser build of the Quiz screen, for people who can't install the
Android APK (iOS, laptops, …). It is a **static site** — no server — that
talks to the **same Google Apps Script backend and Google Sheet** the app
uses, so problems and results are shared: an admin sees app and web
submissions together.

```
web/
  index.html            markup
  styles.css            dark / gold theme
  quiz.js               all the logic (sign-in, quiz, admin, results)
  config.js             <-- the two values you fill in
  manifest.webmanifest  "Add to Home Screen" metadata
```

The Kivy app is **not touched**. There is one small, backwards-compatible
change to make in the Apps Script backend (step 2) so it also trusts
tokens minted for the website.

---

## 1. Google Cloud — a *Web* OAuth client

The app uses an "iOS" OAuth client with a custom-scheme redirect. The web
sign-in button (Google Identity Services) needs a **Web application**
client instead.

1. <https://console.cloud.google.com/> → same project as the app
   (`ras-robocontroller` or whatever you named it).
2. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Web application**
   - Name: `RAS Quiz Web`
   - **Authorised JavaScript origins** — add every origin you'll load the
     site from, scheme + host + port, no trailing slash:
     - `https://<your-site>.netlify.app` (or your GitHub Pages / Vercel URL)
     - `http://localhost:8000` (for local testing, see step 4)
   - **Authorised redirect URIs** — leave empty. This flow returns the ID
     token straight to JavaScript; there is no redirect.
   - Create, copy the **Client ID** (`…apps.googleusercontent.com`).
3. Paste it into `config.js`:
   ```js
   webClientId: "123456-abcdef.apps.googleusercontent.com",
   ```
   `backendUrl` is already set to the app's `/exec` URL — change it only
   if you redeploy the backend to a new URL.

> The OAuth consent screen is shared with the app. If it's **Internal**
> to a Workspace org, nothing to do. If **External / Testing**, add
> testers as usual — the backend still enforces `@lnmiit.ac.in` either
> way.

---

## 2. Backend — accept the web client's token (one-time, non-breaking)

`aud` (audience) on a Google ID token is the client ID it was minted for.
`backend/quiz_backend.gs` currently checks it against a single value, so a
web token would be rejected with *"Token audience mismatch"*. Make it a
list.

Open the script (**your Sheet → Extensions → Apps Script**).

**a. CONFIG block** — replace the single `var CLIENT_ID = '…';` line with:

```js
// Accept ID tokens minted for EITHER client. First = the Android/iOS
// app (unchanged), second = this web build.
var CLIENT_IDS = [
  '1090468690005-do85caobta0nv2fjgbvmqijcc5hs4p3k.apps.googleusercontent.com',
  'PASTE_WEB_OAUTH_CLIENT_ID.apps.googleusercontent.com',
];
```

**b.** Search the whole script for `CLIENT_ID` and make sure nothing
references the old singular name any more — only `CLIENT_IDS` should
remain.

**c. `verifyToken()`** — replace the whole function with this (it also
reports *why* a token was rejected instead of a bare message, and can't
throw on a malformed tokeninfo response):

```js
function verifyToken(idToken) {
  if (!idToken) throw new Error('Missing idToken');
  var url = 'https://oauth2.googleapis.com/tokeninfo?id_token=' +
    encodeURIComponent(idToken);
  var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  var info = null;
  try { info = JSON.parse(resp.getContentText()); } catch (e) { info = null; }
  if (resp.getResponseCode() !== 200 || !info || info.error) {
    throw new Error('Token verification failed: ' +
      ((info && (info.error_description || info.error)) || resp.getResponseCode()));
  }
  if (CLIENT_IDS.indexOf(info.aud) === -1) {
    throw new Error('Token audience mismatch (' + info.aud + ')');
  }
  if (Number(info.exp) * 1000 < Date.now()) throw new Error('Token expired');
  if (String(info.email_verified) !== 'true') throw new Error('Email not verified');
  return info;
}
```

Then **Deploy → Manage deployments → (pencil) → Version: New version →
Deploy**. Editing the code without cutting a new version leaves `/exec`
running the old code. The `/exec` URL is unchanged and the app keeps
working — its token's `aud` is still in the list.

Nothing else changes: the `@lnmiit.ac.in` domain check, the
`ADMIN_EMAILS` whitelist, and all Sheet I/O are identical.

> **Both app and website showing `Cannot read properties of undefined
> (reading 'aud')`?** That's this function in the *deployed* script
> throwing because `info` came back undefined — a half-applied edit.
> Paste the block above verbatim and redeploy a new version; both
> clients recover with no app rebuild.

### CORS

No CORS config is needed. `quiz.js` sends the body as `text/plain`, which
keeps the request a "simple" cross-origin request (no `OPTIONS`
preflight, which Apps Script can't answer). Apps Script parses the JSON
body regardless and serves the response with
`Access-Control-Allow-Origin: *`.

---

## 3. Deploy the site

Any static host. The folder has no build step.

- **Netlify:** drag the `web/` folder onto <https://app.netlify.com/drop>,
  or point Netlify at this repo with **Publish directory = `web`**.
- **GitHub Pages:** push and serve `web/` (Settings → Pages → *Deploy from
  branch*, folder `/web`), or copy the files to `/docs`.
- **Vercel / Cloudflare Pages:** import the repo, output/root directory
  `web`.

After it's live, make sure that exact origin is in the OAuth client's
**Authorised JavaScript origins** (step 1).

---

## 4. Run it locally

```sh
cd web
python3 -m http.server 8000
# open http://localhost:8000
```

`file://` will not work (Google sign-in needs a real origin).
`http://localhost:8000` must be listed in the OAuth client's authorised
origins.

---

## What it does

- **Sign in with Google** → students take every open problem; already
  answered ones show locked with the right/wrong colours and a running
  total, exactly like the app.
- **Submit** sends only the newly answered questions (one attempt each,
  also enforced server-side).
- **Admins** (addresses in the backend's `ADMIN_EMAILS`) get a
  **MANAGE / RESULTS** tab bar:
  - MANAGE: a gold **+** opens the "post a problem" form.
  - RESULTS: the scoreboard as a table (Name · Email · Score · %), with a
    gold refresh icon and sortable **Name / Email / %** column headers.

## Limits

- ID tokens last ~1 hour; when one expires the site drops you back to the
  sign-in screen. Just sign in again.
- Same Apps Script free quota as the app (~20k URL-fetch calls/day) —
  fine for a class.
- `config.js` ships the public client ID and backend URL. Neither is a
  secret (the backend re-verifies every token and enforces domain +
  admin server-side), but keep `ADMIN_EMAILS` review in mind before going
  live.

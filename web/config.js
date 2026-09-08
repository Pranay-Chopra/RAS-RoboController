/* Fill these in, then deploy the `web/` folder to any static host.
   See README.md for the Google Cloud + Apps Script steps. */
window.QUIZ_CONFIG = {
  // Google Cloud Console -> APIs & Services -> Credentials ->
  // Create credentials -> OAuth client ID -> Application type: "Web application".
  // Add your deployed origin(s) under "Authorised JavaScript origins",
  // e.g. https://ras-quiz.netlify.app and http://localhost:8000 for local testing.
  // No redirect URIs are needed (this uses the Google Identity Services
  // ID-token flow, not a redirect flow).
  webClientId: "1090468690005-mbihosgo4qstaohs48noutb4v0tita2b.apps.googleusercontent.com",

  // The same Apps Script ".../exec" URL the Android app uses
  // (mirrors quiz_config.BACKEND_URL). The backend needs the one-time,
  // backwards-compatible `aud` patch in README.md so it also accepts
  // ID tokens minted for the web client above.
  backendUrl: "https://script.google.com/macros/s/AKfycbw6mWOOblOk4-8xk6DUYdMHTB_pEjk1KBtVsItcMQkMcWXCzHhd0SkU6btNwje-74mq/exec",

  // Cosmetic hint only. Real domain + admin enforcement is server-side.
  allowedDomainNote: "lnmiit.ac.in",
};

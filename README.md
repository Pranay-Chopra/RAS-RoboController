# RAS RoboController

An Android app for driving IEEE RAS SBC (LNMIIT) robots from a phone — built
with [Kivy](https://kivy.org) + [KivyMD](https://kivymd.readthedocs.io).
It connects to a robot over **Wi-Fi** or **Bluetooth LE**, sends control
commands from an on-screen gamepad you can lay out yourself, and shows a
live serial feed coming back.

Defaults target an ESP32 reference robot: `192.168.4.1` on ports
`8888 / 8080 / 80` in AP mode for Wi-Fi, and the standard Nordic UART
Service (NUS) UUIDs for BLE. All of it is editable in **Settings**.

## Screens

| Screen | What it does |
| --- | --- |
| **Home** | Pick a transport (Wi-Fi / BLE), scan, connect. |
| **Controls** | HUD gamepad — draggable/rotatable joysticks, sliders and buttons, each bound to a command template (e.g. `JOYD:{x},{y}`, `DIR:{val}`). Layout persists. |
| **Serial Monitor** | Live RX stream from the robot; send raw lines back. |
| **Announcements** | Locked-down WebView of the club announcements page. |
| **Quiz** | Google-authenticated quiz for members; admins post questions and see a scoreboard. Needs one-time backend setup — see below. |
| **Settings** | Wi-Fi IP/ports and BLE service/RX/TX UUIDs, persisted to app storage. |
| **About / Help** | Club info, contributor links, and in-app application logs (exportable). |

## Project layout

```
main.py              entry point (Android GL + DEX preload shims, then app)
app.py               RoboController(MDApp): screen manager, services, permissions
screens/             one module per screen
kv/                  matching KivyMD layout files, loaded in app.build()
widgets/             reusable widgets (joystick, HUD element, webview, …)
services/            wifi, ble, storage, camera-stub, google_auth, quiz_api
models/              ConnectionSettings and robot model
dialogs/             connect / settings / binding / quiz dialogs
utils/               log capture, control engine
quiz_config.py       Quiz feature config + access rules (OAuth client id, backend URL, admin list)
android/             extra manifest fragments (OAuth redirect intent filter)
java_src/            custom Java (BLE GattCallback) compiled into the APK
buildozer.spec       Android packaging config
.github/workflows/   CI: build the APK
```

## Building the APK

### CI (recommended)

`.github/workflows/build-apk.yml` builds a debug APK with Buildozer.

- **Tag a release:** `git tag v1.0.0 && git push origin v1.0.0` — the APK is
  built and attached to the GitHub Release for that tag.
- **Manual run:** the *Run workflow* button; the APK lands in the run's
  *Artifacts*.

### Locally

Needs Linux (or WSL) with the usual [Buildozer
dependencies](https://buildozer.readthedocs.io/en/latest/installation.html).

```sh
pip install buildozer
buildozer android debug        # -> bin/robocontroller-*-debug.apk
buildozer android debug deploy run logcat   # build, install, tail logs
```

The first build downloads the Android SDK/NDK and compiles
python-for-android — expect 20–40 min. Subsequent builds are cached under
`.buildozer/`.

## Running on desktop (UI work only)

```sh
python -m venv .venv && source .venv/bin/activate
pip install "kivy[base]" kivymd
python main.py
```

Bluetooth, Wi-Fi TCP, Android permissions/intents and the announcements
WebView are Android-only and will no-op or error on desktop — desktop is
just for iterating on layout and screen logic. (Dependencies for the real
build are pinned in `buildozer.spec`, not a `requirements.txt`.)

## Quiz feature setup

The Quiz screen is inert until `quiz_config.py` is filled in:
`GOOGLE_CLIENT_ID`, `BACKEND_URL`, and `ADMIN_EMAILS`. Auth is Google
OAuth2 (an "iOS"-type client, PKCE, no secret); storage is a Google Apps
Script web app backed by a Sheet, which re-verifies every ID token and
enforces the allowed email domain + admin whitelist server-side.
`quiz_config.is_configured()` gates the UI until both values are set.

## Credits

Built by Pranay Chopra and Ojasva Koolwal for the IEEE Robotics &
Automation Society Student Branch Chapter, LNMIIT.

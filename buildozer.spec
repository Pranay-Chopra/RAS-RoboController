#
# RoboController Buildozer Configuration
#

[app]

# ------------------------------------------------------------------
# Application
# ------------------------------------------------------------------

title = RoboController
package.name = robocontroller
package.domain = org.ieeeras

source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,svg,json,ttf

version = 0.2.0

# ------------------------------------------------------------------
# Requirements
# ------------------------------------------------------------------

requirements = python3==3.11.15, hostpython3==3.11.15, kivy, https://github.com/kivymd/KivyMD/archive/master.zip, pyjnius, bleak, typing_extensions, materialyoucolor==3.0.3, materialshapes, pycairo, pillow, exceptiongroup, asyncgui, asynckivy, setuptools

# ------------------------------------------------------------------
# Orientation
# ------------------------------------------------------------------

orientation = portrait

# ------------------------------------------------------------------
# Android SDK
# ------------------------------------------------------------------

# Force landscape or portrait explicitly (don't use all)
# orientation = portrait

# Ensure API target is set to 33 or 34
android.api = 34
android.minapi = 24
android.min_sdk = 24
android.target_sdk = 34

# Enable OpenGL ES2 explicitly
# android.archs = arm64-v8a

android.enable_androidx = True
android.gradle_dependencies = org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3

# ------------------------------------------------------------------
# Permissions
# ------------------------------------------------------------------

android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, CHANGE_WIFI_STATE, CHANGE_NETWORK_STATE, ACCESS_FINE_LOCATION, BLUETOOTH, BLUETOOTH_ADMIN, BLUETOOTH_SCAN, BLUETOOTH_CONNECT

# ------------------------------------------------------------------
# Android Behaviour
# ------------------------------------------------------------------

fullscreen = 0

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

log_level = 2

# ------------------------------------------------------------------
# Assets
# ------------------------------------------------------------------

presplash.filename =
icon.filename =

# ------------------------------------------------------------------
# Build Options
# ------------------------------------------------------------------

warn_on_root = 1

# ------------------------------------------------------------------
# Python-for-Android
# ------------------------------------------------------------------

p4a.branch = master

# ------------------------------------------------------------------
# Gradle
# ------------------------------------------------------------------

# android.gradle_dependencies =

android.add_jars =

android.add_aars =

android.add_src = java_src
# Add custom rules for multidex
android.extra_manifest_args = multidex-keep.txt

# ------------------------------------------------------------------
# Services
# ------------------------------------------------------------------

services =

# ------------------------------------------------------------------
# Hooks
# ------------------------------------------------------------------

# p4a.hook =

# ------------------------------------------------------------------
# Excluded Files
# ------------------------------------------------------------------

source.exclude_dirs = .git,.venv,__pycache__,build,bin,.idea,.vscode

source.exclude_patterns = *.pyc,*.pyo

# ------------------------------------------------------------------
# Whitelist
# ------------------------------------------------------------------

android.whitelist =

# ------------------------------------------------------------------
# Backup
# ------------------------------------------------------------------

android.allow_backup = False

# ------------------------------------------------------------------
# Architectures
# ------------------------------------------------------------------

android.archs = arm64-v8a

# ------------------------------------------------------------------
# Entry Point
# ------------------------------------------------------------------

entrypoint = org.kivy.android.PythonActivity

#
# Buildozer
#

[buildozer]

log_level = 2

warn_on_root = 1

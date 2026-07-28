import os

# Force Kivy to use standard GLES2 driver on Android
os.environ['KIVY_GL_BACKEND'] = 'gl'

from jnius import autoclass

# Explicitly force the Android Activity's ClassLoader to load the class into memory
PythonActivity = autoclass("org.kivy.android.PythonActivity")
activity = PythonActivity.mActivity

try:
    # Use Android context classloader to resolve secondary DEX classes
    class_loader = activity.getClassLoader()
    gatt_class = class_loader.loadClass("org.kivy.android.GattCallback")
    print(f"[BLE] Successfully pre-loaded GattCallback: {gatt_class}")
except Exception as e:
    print(f"[BLE] Failed to pre-load GattCallback: {e}")

from app import RoboController

if __name__ == "__main__":
    RoboController().run()

from jnius import PythonJavaClass, autoclass, cast, java_method
from kivy.clock import Clock
from android.runnable import run_on_ui_thread


class AndroidWiFi:
    _active_callback = None
    _active_listener = None
    _timeout_event = None

    @classmethod
    def check_permissions(cls):
        """Ensures required Fine Location permissions are active for Wi-Fi operations."""
        try:
            from android.permissions import Permission, check_permission, request_permissions

            permissions = [
                Permission.ACCESS_FINE_LOCATION,
                Permission.ACCESS_COARSE_LOCATION,
                Permission.CHANGE_WIFI_STATE,
            ]

            missing = [p for p in permissions if not check_permission(p)]
            if missing:
                print(f"[AndroidWiFi] Requesting missing permissions: {missing}")
                request_permissions(missing)
                return False
            return True
        except Exception as e:
            print(f"[AndroidWiFi] Permission check error: {e}")
            return True

    @classmethod
    def is_wifi_enabled(cls):
        """Checks if Wi-Fi interface is active."""
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            activity = PythonActivity.mActivity
            wifi_manager = activity.getSystemService(Context.WIFI_SERVICE)
            return wifi_manager.isWifiEnabled()
        except Exception as e:
            print(f"[AndroidWiFi] Error checking Wi-Fi state: {e}")
            return False

    @classmethod
    @run_on_ui_thread
    def prompt_enable_wifi(cls):
        """Opens native Wi-Fi settings panel on UI thread."""
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            Settings = autoclass("android.provider.Settings")
            activity = PythonActivity.mActivity

            try:
                Panel = autoclass("android.provider.Settings$Panel")
                intent = Intent(Panel.ACTION_WIFI)
            except Exception:
                intent = Intent(Settings.ACTION_WIFI_SETTINGS)

            activity.startActivity(intent)
            print("[AndroidWiFi] Successfully launched Wi-Fi panel overlay.")
        except Exception as e:
            print(f"[AndroidWiFi] Failed to launch Wi-Fi panel: {e}")

    @classmethod
    def scan(cls):
        """Triggers and retrieves Wi-Fi scan results."""
        if not cls.check_permissions():
            print("[AndroidWiFi] Cannot scan: Missing Fine Location permission.")
            return []

        results = []
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            activity = PythonActivity.mActivity
            wifi_manager = activity.getSystemService(Context.WIFI_SERVICE)

            wifi_manager.startScan()
            scan_results = wifi_manager.getScanResults()

            for i in range(scan_results.size()):
                item = scan_results.get(i)
                ssid = str(item.SSID)
                rssi = int(item.level)
                if ssid:
                    results.append({"ssid": ssid, "rssi": rssi})
        except Exception as e:
            print(f"[AndroidWiFi] Scan exception: {e}")

        return results

    @classmethod
    def connect(cls, ssid, password=None, timeout=25, on_result=None):
        """Initiates system prompt for connecting to a local non-internet AP."""
        cls.check_permissions()
        cls.clear_timeout()

        @run_on_ui_thread
        def _request_network_ui():
            try:
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                Context = autoclass("android.content.Context")

                WifiNetworkSpecifierBuilder = autoclass(
                    "android.net.wifi.WifiNetworkSpecifier$Builder"
                )
                NetworkRequestBuilder = autoclass(
                    "android.net.NetworkRequest$Builder"
                )
                NetworkCapabilities = autoclass(
                    "android.net.NetworkCapabilities"
                )
                WiFiCallback = autoclass("org.kivy.android.WiFiCallback")

                activity = PythonActivity.mActivity
                cm = activity.getSystemService(Context.CONNECTIVITY_SERVICE)

                # 1. Specifier setup
                specifier_builder = WifiNetworkSpecifierBuilder()
                specifier_builder.setSsid(str(ssid))

                if password and len(str(password)) >= 8:
                    specifier_builder.setWpa2Passphrase(str(password))
                elif password:
                    print(f"[AndroidWiFi] Warning: Passphrase under 8 chars for {ssid}")

                wifi_specifier = specifier_builder.build()
                network_specifier = cast(
                    "android.net.NetworkSpecifier", wifi_specifier
                )

                # 2. Build local network request (Bypasses network recommendation/evaluator)
                request_builder = NetworkRequestBuilder()
                request_builder.addTransportType(NetworkCapabilities.TRANSPORT_WIFI)

                # Strip internet capability so OS ignores WAN check
                request_builder.removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                request_builder.addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_RESTRICTED)

                # Remove trusted capability if supported to bypass captive portal engine
                try:
                    request_builder.removeCapability(NetworkCapabilities.NET_CAPABILITY_TRUSTED)
                except Exception:
                    pass

                request_builder.setNetworkSpecifier(network_specifier)
                request = request_builder.build()

                # 3. Listener implementation
                class WiFiListenerHelper(PythonJavaClass):
                    __javainterfaces__ = ["org/kivy/android/WiFiCallback$Listener"]
                    __javacontext__ = "app"

                    def __init__(self):
                        super().__init__()
                        self.handled = False

                    @java_method("(Landroid/net/Network;)V")
                    def onAvailable(self, network):
                        print(f"[AndroidWiFi] Bound to AP Network: {network}")
                        try:
                            cm.bindProcessToNetwork(network)
                        except Exception as err:
                            print(f"[AndroidWiFi] Process bind error: {err}")

                        if self.handled:
                            return
                        self.handled = True

                        cls.clear_timeout()
                        if on_result:
                            Clock.schedule_once(lambda dt: on_result(True), 0)

                    @java_method("()V")
                    def onUnavailable(self):
                        print("[AndroidWiFi] Connection rejected or missing.")
                        if self.handled:
                            return
                        self.handled = True

                        cls.clear_timeout()
                        cls.disconnect()
                        if on_result:
                            Clock.schedule_once(lambda dt: on_result(False), 0)

                    @java_method("(Landroid/net/Network;)V")
                    def onLost(self, network):
                        print("[AndroidWiFi] Network link lost.")
                        try:
                            cm.bindProcessToNetwork(None)
                        except Exception:
                            pass

                cls._active_listener = WiFiListenerHelper()
                cls._active_callback = WiFiCallback(cls._active_listener)

                # 4. Watchdog Timeout
                def _handle_timeout(dt):
                    if cls._active_listener and not cls._active_listener.handled:
                        cls._active_listener.handled = True
                        print("[AndroidWiFi] Connection user prompt timed out.")
                        cls.disconnect()
                        if on_result:
                            on_result(False)

                cls._timeout_event = Clock.schedule_once(_handle_timeout, float(timeout))

                # Issue network request on UI Thread
                cm.requestNetwork(request, cls._active_callback)

            except Exception as e:
                print(f"[AndroidWiFi] RequestNetwork Exception: {e}")
                cls.disconnect()
                if on_result:
                    Clock.schedule_once(lambda dt: on_result(False), 0)

        _request_network_ui()

    @classmethod
    def clear_timeout(cls):
        if cls._timeout_event:
            cls._timeout_event.cancel()
            cls._timeout_event = None

    @classmethod
    @run_on_ui_thread
    def disconnect(cls):
        """Unbinds process network routing without dropping active specifiers."""
        cls.clear_timeout()
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            activity = PythonActivity.mActivity
            cm = activity.getSystemService(Context.CONNECTIVITY_SERVICE)

            try:
                cm.bindProcessToNetwork(None)
            except Exception:
                pass
        except Exception as e:
            print(f"[AndroidWiFi] Disconnect process unbind error: {e}")

    @classmethod
    @run_on_ui_thread
    def release_network(cls):
        """Explicitly unregisters the NetworkCallback and tears down the Wi-Fi specifier."""
        cls.disconnect()
        try:
            if cls._active_callback:
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                Context = autoclass("android.content.Context")
                activity = PythonActivity.mActivity
                cm = activity.getSystemService(Context.CONNECTIVITY_SERVICE)

                cm.unregisterNetworkCallback(cls._active_callback)
                print("[AndroidWiFi] Unregistered active NetworkCallback.")
        except Exception as e:
            print(f"[AndroidWiFi] Error releasing network: {e}")
        finally:
            cls._active_callback = None
            cls._active_listener = None

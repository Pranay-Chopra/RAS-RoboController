import json
import platform
import socket
import threading
import time

from kivy.clock import Clock
from models.bot import Robot
from models.settings import ConnectionSettings


class WiFiService:
    def __init__(self, settings=None):
        # Falls back to a fresh default-valued ConnectionSettings if none is
        # passed, so WiFiService still works standalone (e.g. in a script or
        # test) without requiring the app to wire one up.
        self.settings = settings or ConnectionSettings()
        self.socket = None
        self.robot = None
        self.active_port = None
        self._rx_buffer = ""
        self.is_listening = False
        self.rx_thread = None
        self.on_data_callback = None
        # Guards connect()/disconnect() so an overlapping call (e.g. a
        # duplicate UI tap that slips through) can't tear down the socket
        # and RX thread of a connection attempt that's still in flight.
        self._conn_lock = threading.RLock()

        try:
            from services.android_wifi import AndroidWiFi
            self.backend = AndroidWiFi
        except ImportError:
            self.backend = None

    def scan(self, callback=None):
        """Scans for targets. Automatically prompts for Wi-Fi/Permissions if off."""
        robots = []

        if self.backend:
            if hasattr(self.backend, "is_wifi_enabled"):
                if not self.backend.is_wifi_enabled():
                    print("[WiFiService] Wi-Fi adapter is off. Triggering panel overlay...")
                    if hasattr(self.backend, "prompt_enable_wifi"):
                        self.backend.prompt_enable_wifi()

            if hasattr(self.backend, "scan"):
                try:
                    networks = self.backend.scan() or []
                    for network in networks:
                        ssid = network.get("ssid") or ""
                        robots.append(
                            Robot(
                                name=ssid,
                                transport="wifi",
                                ip=self.settings.wifi_ip,
                                rssi=network.get("rssi", -100),
                            )
                        )
                except Exception as e:
                    print(f"[WiFiService] Scan failed: {e}")

        if callback:
            Clock.schedule_once(lambda dt: callback(robots), 0)

        return robots

    def connect(self, robot, password=None, timeout=15.0):
        """Connects via Android OS WifiNetworkSpecifier panel and opens a TCP socket."""
        with self._conn_lock:
            return self._connect_locked(robot, password, timeout)

    def _connect_locked(self, robot, password=None, timeout=15.0):
        self.disconnect()

        connection_event = threading.Event()
        connection_status = {"success": False}

        def on_wifi_result(success):
            connection_status["success"] = success
            connection_event.set()

        try:
            if self.backend and hasattr(self.backend, "connect"):
                print(f"[WiFiService] Triggering system connection dialog for {robot.name}...")
                self.backend.connect(
                    ssid=robot.name,
                    password=password,
                    timeout=timeout,
                    on_result=on_wifi_result,
                )

                signaled = connection_event.wait(timeout=timeout + 2.0)

                if not signaled or not connection_status["success"]:
                    print(f"[WiFiService] OS level connection to {robot.name} rejected or timed out.")
                    self.disconnect()
                    return False

                time.sleep(1.5)

            target_ip = getattr(robot, "ip", None) or self.settings.wifi_ip

            connected_socket = None
            bound_port = None
            bind_to_device = platform.system() == "Linux" and self.backend is None

            for port in self.settings.wifi_ports:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.5)

                # Only bind to the Wi-Fi interface when we do NOT have an
                # Android ConnectivityManager that already called
                # bindProcessToNetwork(). On Linux desktop this makes sure we
                # use the right NIC; on Android (which also reports platform
                # 'Linux' via platform.system()) we must NOT do this, because
                # the OS routing rules already send traffic through the bound
                # network.
                if bind_to_device:
                    try:
                        sock.setsockopt(socket.SOL_SOCKET, 25, b"wlan0")
                    except (PermissionError, OSError):
                        pass

                print(f"[WiFiService] Opening TCP Socket to {target_ip}:{port}...")

                try:
                    sock.connect((target_ip, port))
                    connected_socket = sock
                    bound_port = port
                    print(f"[WiFiService] Successfully connected on port {port}")
                    break
                except (socket.timeout, ConnectionRefusedError, OSError) as err:
                    print(f"[WiFiService] Port {port} failed ({err}). Retrying next port...")
                    try:
                        sock.close()
                    except Exception:
                        pass

            if not connected_socket:
                print(f"[WiFiService] Failed to establish TCP connection on any configured port {self.settings.wifi_ports}")
                self.disconnect()
                return False

            self.socket = connected_socket
            self.active_port = bound_port
            self.socket.settimeout(0.5)

            self.robot = robot
            self._rx_buffer = ""
            print(f"[WiFiService] TCP session active with {robot.name} on {target_ip}:{bound_port}")
            return True

        except Exception as e:
            print(f"[WiFiService] Connection failed: {e}")
            self.disconnect()
            return False

    def start_rx_loop(self, on_data_callback=None):
        """Starts background thread to continuously read incoming lines from ESP8266."""
        self.on_data_callback = on_data_callback
        self.is_listening = True
        self.rx_thread = threading.Thread(target=self._listen_worker, daemon=True)
        self.rx_thread.start()

    def _listen_worker(self):
        """Worker loop reading TCP socket stream and firing callbacks."""
        while self.is_listening and self.socket:
            try:
                data = self.socket.recv(1024)
                if not data:
                    break

                self._rx_buffer += data.decode("utf-8", errors="ignore")

                while "\r\n" in self._rx_buffer:
                    line, self._rx_buffer = self._rx_buffer.split("\r\n", 1)
                    line = line.strip()
                    if line and self.on_data_callback:
                        Clock.schedule_once(lambda dt, msg=line: self.on_data_callback(msg), 0)

            except socket.timeout:
                continue
            except Exception as e:
                print(f"[WiFi RX Worker Error] {e}")
                break

        self.is_listening = False

    def send(self, command):
        """Sends raw command string or JSON dictionary over TCP socket."""
        if not self.socket:
            return False

        try:
            if isinstance(command, dict):
                packet = json.dumps(command) + "\r\n"
            else:
                packet = str(command).strip() + "\r\n"

            self.socket.sendall(packet.encode("utf-8"))
            return True
        except Exception as e:
            print(f"[WiFiService] Send error: {e}")
            self.disconnect()
            return False

    def disconnect(self):
        """Releases sockets, stops background RX worker, and cleans state."""
        with self._conn_lock:
            self._disconnect_locked()

    def _disconnect_locked(self):
        self.is_listening = False
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None

        # NOTE: backend.disconnect() only unbinds this process's traffic
        # routing (cm.bindProcessToNetwork(None)) — it does NOT release the
        # WifiNetworkSpecifier NetworkRequest registered in connect(). As
        # long as that request stays registered, Android treats it as still
        # wanted and keeps the device associated with the AP even after our
        # TCP socket is closed. release_network() unregisters the
        # NetworkCallback, which actually releases the request and lets the
        # OS disconnect from the AP. It's safe to call even if no request is
        # currently active (it no-ops when _active_callback is None).
        if self.backend:
            if hasattr(self.backend, "release_network"):
                try:
                    self.backend.release_network()
                except Exception as e:
                    print(f"[WiFiService] Backend release_network error: {e}")
            elif hasattr(self.backend, "disconnect"):
                try:
                    self.backend.disconnect()
                except Exception as e:
                    print(f"[WiFiService] Backend disconnect error: {e}")

        self.robot = None
        self.active_port = None
        self._rx_buffer = ""
        print("[WiFiService] Disconnected cleanly.")

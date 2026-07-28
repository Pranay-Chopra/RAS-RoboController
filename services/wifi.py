import json
import platform
import socket
import threading
import time
from kivy.clock import Clock
from models.bot import Robot

# Standard target ports in descending order of priority
STANDARD_PORTS = [8888, 8080, 80]


class WiFiService:

    def __init__(self):
        self.socket = None
        self.robot = None
        self.active_port = None
        self._rx_buffer = ""

        try:
            from services.android_wifi import AndroidWiFi
            self.backend = AndroidWiFi
        except ImportError:
            self.backend = None

    def scan(self, callback=None):
        """Scans for targets. Automatically prompts for Wi-Fi/Permissions if off."""
        robots = []

        if self.backend:
            # 1. Verify Wi-Fi is toggled on; prompt overlay if disabled
            if hasattr(self.backend, "is_wifi_enabled"):
                if not self.backend.is_wifi_enabled():
                    print("[WiFiService] Wi-Fi adapter is off. Triggering panel overlay...")
                    if hasattr(self.backend, "prompt_enable_wifi"):
                        self.backend.prompt_enable_wifi()

            # 2. Run scan
            if hasattr(self.backend, "scan"):
                try:
                    networks = self.backend.scan() or []
                    for network in networks:
                        ssid = network.get("ssid") or ""
                        # if "ROBOT" in ssid.upper():
                        robots.append(
                            Robot(
                                name=ssid,
                                transport="wifi",
                                ip="192.168.4.1",
                                rssi=network.get("rssi", -100),
                            )
                        )
                except Exception as e:
                    print(f"[WiFiService] Scan failed: {e}")

        if callback:
            Clock.schedule_once(lambda dt: callback(robots), 0)

        return robots

    def connect(self, robot, password=None, timeout=15.0):
        """Connects via Android OS WifiNetworkSpecifier panel and opens a TCP socket.

        Tries target ports sequentially (8888, 8080, 80) to handle different ESP32 firmware setups.
        Must be executed inside a background worker thread!
        """
        self.disconnect()

        connection_event = threading.Event()
        connection_status = {"success": False}

        def on_wifi_result(success):
            connection_status["success"] = success
            connection_event.set()

        try:
            # 1. Trigger OS dialogue panel
            if self.backend and hasattr(self.backend, "connect"):
                print(f"[WiFiService] Triggering system connection dialog for {robot.name}...")
                self.backend.connect(
                    ssid=robot.name,
                    password=password,
                    timeout=timeout,
                    on_result=on_wifi_result,
                )

                # Wait for user approval on system popup
                signaled = connection_event.wait(timeout=timeout + 2.0)

                if not signaled or not connection_status["success"]:
                    print(f"[WiFiService] OS level connection to {robot.name} rejected or timed out.")
                    self.disconnect()
                    return False

            # 2. DHCP lease stabilization delay
            time.sleep(1.5)

            target_ip = getattr(robot, "ip", "192.168.4.1")

            # 3. Port Sweep Loop (8888 -> 8080 -> 80)
            connected_socket = None
            bound_port = None

            for port in STANDARD_PORTS:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.5)  # Fast timeout for handshake attempt

                if platform.system() == "Linux":
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
                print(f"[WiFiService] Failed to establish TCP connection on any standard port {STANDARD_PORTS}")
                self.disconnect()
                return False

            # Assign successful socket and set low timeout for live control loop
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

    def send(self, command):
        """Sends JSON packet appended with newline delimiter."""
        if not self.socket:
            return False

        try:
            packet = json.dumps(command) + "\n"
            self.socket.sendall(packet.encode("utf-8"))
            return True
        except Exception as e:
            print(f"[WiFiService] Send error: {e}")
            self.disconnect()
            return False

    def receive(self):
        """Buffered stream reader handling split chunks."""
        if not self.socket:
            return None

        try:
            data = self.socket.recv(1024)
            if not data:
                return None

            self._rx_buffer += data.decode("utf-8", errors="ignore")

            if "\n" in self._rx_buffer:
                line, self._rx_buffer = self._rx_buffer.split("\n", 1)
                line = line.strip()
                if line:
                    return json.loads(line)

            return None

        except socket.timeout:
            return None
        except json.JSONDecodeError as e:
            print(f"[WiFiService] JSON Parse Error: {e}")
            return None
        except Exception as e:
            print(f"[WiFiService] Receive error: {e}")
            self.disconnect()
            return False

    def disconnect(self):
        """Releases sockets and unbinds OS NetworkCallback."""
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

        if self.backend and hasattr(self.backend, "disconnect"):
            try:
                self.backend.disconnect()
            except Exception as e:
                print(f"[WiFiService] Backend disconnect error: {e}")

        self.robot = None
        self.active_port = None
        self._rx_buffer = ""
        print("[WiFiService] Disconnected cleanly.")

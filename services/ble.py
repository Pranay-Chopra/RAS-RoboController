from jnius import PythonJavaClass, autoclass, java_method
from kivy.clock import Clock
from models.bot import Robot


class BLEService:

    # Standard ESP32 Nordic UART Service / RX Characteristic UUIDs
    UART_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
    UART_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

    def __init__(self):
        self.is_connected = False
        self.connected_device = None
        self.gatt = None
        self._write_characteristic = None
        self._scan_cb = None
        self._gatt_cb = None  # Persistent reference to Java GattCallback wrapper
        self._gatt_listener = None  # Persistent reference to PyJNIus listener interface

    def _get_adapter(self):
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            activity = PythonActivity.mActivity
            bt_manager = activity.getSystemService(Context.BLUETOOTH_SERVICE)
            return bt_manager.getAdapter() if bt_manager else None
        except Exception as e:
            print(f"[BLEService] Failed to retrieve BluetoothAdapter: {e}")
            return None

    @classmethod
    def is_bluetooth_enabled(cls):
        """Checks if Bluetooth is enabled on the device."""
        try:
            BluetoothAdapter = autoclass("android.bluetooth.BluetoothAdapter")
            adapter = BluetoothAdapter.getDefaultAdapter()
            return adapter is not None and adapter.isEnabled()
        except Exception as e:
            print(f"[BLEService] Error checking Bluetooth status: {e}")
            return False

    @classmethod
    def prompt_enable_bluetooth(cls):
        """Triggers native Android system popup asking the user to enable Bluetooth."""
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            BluetoothAdapter = autoclass("android.bluetooth.BluetoothAdapter")

            activity = PythonActivity.mActivity
            intent = Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE)
            activity.startActivity(intent)
            print("[BLEService] Triggered system Bluetooth request dialog.")
        except Exception as e:
            print(f"[BLEService] Error requesting Bluetooth enable: {e}")

    def _check_and_prompt_bt(self):
        """Internal check that prompts user if Bluetooth is OFF."""
        if not self.is_bluetooth_enabled():
            print("[BLEService] Bluetooth is OFF. Triggering system dialog...")
            Clock.schedule_once(
                lambda dt: BLEService.prompt_enable_bluetooth(), 0
            )
            return False
        return True

    def scan(self, on_complete_callback):
        if not self._check_and_prompt_bt():
            if on_complete_callback:
                Clock.schedule_once(lambda dt: on_complete_callback([]), 0)
            return

        adapter = self._get_adapter()
        if not adapter:
            print("[BLEService] BluetoothAdapter is null.")
            if on_complete_callback:
                Clock.schedule_once(lambda dt: on_complete_callback([]), 0)
            return

        discovered_robots = []

        class LeScanCallback(PythonJavaClass):
            __javainterfaces__ = [
                "android/bluetooth/BluetoothAdapter$LeScanCallback"
            ]
            __javacontext__ = "app"

            def __init__(self):
                super().__init__()

            @java_method("(Landroid/bluetooth/BluetoothDevice;I[B)V")
            def onLeScan(self, device, rssi, scanRecord):
                address = device.getAddress()
                raw_name = device.getName()
                name = str(raw_name) if raw_name else str(address)

                print(
                    f"[BLE DISCOVERY] MAC: {address} | Name: '{name}' | RSSI: {rssi}"
                )

                if not any(r.mac == address for r in discovered_robots):
                    discovered_robots.append(
                        Robot(
                            name=name,
                            transport="ble",
                            mac=address,
                            rssi=int(rssi),
                        )
                    )

        self._scan_cb = LeScanCallback()

        try:
            adapter.startLeScan(self._scan_cb)
            print("[BLEService] BLE scan started safely...")
        except Exception as e:
            print(f"[BLEService] Failed to start scan: {e}")
            if on_complete_callback:
                Clock.schedule_once(lambda dt: on_complete_callback([]), 0)
            return

        def _stop_scan(dt):
            try:
                adapter.stopLeScan(self._scan_cb)
                print(
                    f"[BLEService] Scan complete. Found {len(discovered_robots)} devices."
                )
            except Exception as e:
                print(f"[BLEService] Stop scan exception: {e}")

            if on_complete_callback:
                Clock.schedule_once(
                    lambda dt: on_complete_callback(discovered_robots), 0
                )

        Clock.schedule_once(_stop_scan, 5.0)

    def connect(self, target, on_result=None):
            """Connects to a target BLE device with explicit TRANSPORT_LE and thread-safe dispatch."""
            if hasattr(target, "mac"):
                mac_address = str(target.mac)
            else:
                mac_address = str(target)

            if not mac_address or len(mac_address) != 17 or ":" not in mac_address:
                print(f"[BLEService] Invalid MAC address format: '{mac_address}'")
                if on_result:
                    Clock.schedule_once(lambda dt: on_result(False), 0)
                return

            if not self._check_and_prompt_bt():
                if on_result:
                    Clock.schedule_once(lambda dt: on_result(False), 0)
                return

            adapter = self._get_adapter()
            if not adapter:
                print("[BLEService] Adapter unavailable for connection.")
                if on_result:
                    Clock.schedule_once(lambda dt: on_result(False), 0)
                return

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            BluetoothProfile = autoclass("android.bluetooth.BluetoothProfile")
            BluetoothDevice = autoclass("android.bluetooth.BluetoothDevice")
            GattCallback = autoclass("org.kivy.android.GattCallback")

            activity = PythonActivity.mActivity
            device = adapter.getRemoteDevice(mac_address)

            if not device:
                print(f"[BLEService] Could not resolve remote device {mac_address}.")
                if on_result:
                    Clock.schedule_once(lambda dt: on_result(False), 0)
                return

            service_self = self

            class GattListenerHelper(PythonJavaClass):
                __javainterfaces__ = ["org/kivy/android/GattCallback$Listener"]
                __javacontext__ = "app"

                def __init__(self):
                    super().__init__()

                @java_method("(Landroid/bluetooth/BluetoothGatt;II)V")
                def onConnectionStateChange(self, gatt, status, newState):
                    print(f"[BLEService] JNI onConnectionStateChange status={status}, newState={newState}")

                    if status != 0:
                        print(f"[BLEService] Connection failed with GATT status code: {status}")
                        service_self.is_connected = False

                        def _fail_cleanup(dt):
                            if service_self.gatt:
                                try:
                                    service_self.gatt.close()
                                except Exception:
                                    pass
                                service_self.gatt = None
                            if on_result:
                                on_result(False)

                        Clock.schedule_once(_fail_cleanup, 0)
                        return

                    if newState == BluetoothProfile.STATE_CONNECTED:
                        print(f"[BLEService] Radio connected to {mac_address}. Initiating discoverServices()...")
                        service_self.gatt = gatt

                        def _do_discover(dt):
                            try:
                                gatt.discoverServices()
                            except Exception as e:
                                print(f"[BLEService] discoverServices failed: {e}")
                                if on_result:
                                    on_result(False)

                        Clock.schedule_once(_do_discover, 0.1)

                    elif newState == BluetoothProfile.STATE_DISCONNECTED:
                        print("[BLEService] Disconnected from GATT server.")
                        service_self.is_connected = False
                        service_self._write_characteristic = None

                        def _cleanup(dt):
                            if service_self.gatt:
                                try:
                                    service_self.gatt.close()
                                except Exception:
                                    pass
                                service_self.gatt = None
                            if on_result:
                                on_result(False)

                        Clock.schedule_once(_cleanup, 0)

                @java_method("(Landroid/bluetooth/BluetoothGatt;I)V")
                def onServicesDiscovered(self, gatt, status):
                    print(f"[BLEService] JNI onServicesDiscovered status={status}")

                    def _handle_discovery(dt):
                        if status == 0:
                            print("[BLEService] GATT Services Discovered successfully.")
                            target_uuid = service_self.UART_RX_CHAR_UUID.lower().replace("-", "")
                            matched = False

                            try:
                                services = gatt.getServices()
                                for i in range(services.size()):
                                    svc = services.get(i)
                                    chars = svc.getCharacteristics()
                                    for j in range(chars.size()):
                                        c = chars.get(j)
                                        char_uuid = c.getUuid().toString().lower().replace("-", "")
                                        if target_uuid in char_uuid:
                                            service_self._write_characteristic = c
                                            matched = True
                                            print(f"[BLEService] Matched Write Characteristic: {c.getUuid().toString()}")
                                            break
                                    if matched:
                                        break
                            except Exception as err:
                                print(f"[BLEService] Characteristic parsing error: {err}")

                            service_self.is_connected = True
                            print(f"[BLEService] Connection sequence complete. Handshake success={service_self.is_connected}")

                            if on_result:
                                on_result(True)
                        else:
                            print(f"[BLEService] Service discovery failed with status: {status}")
                            service_self.is_connected = False
                            if on_result:
                                on_result(False)

                    Clock.schedule_once(_handle_discovery, 0)

            # Retain references on instance to prevent GC during connection sequence
            self._gatt_listener = GattListenerHelper()
            self._gatt_cb = GattCallback(self._gatt_listener)

            print(f"[BLEService] Initiating GATT connection (TRANSPORT_LE) to {mac_address}...")
            try:
                self.gatt = device.connectGatt(
                    activity,
                    False,
                    self._gatt_cb,
                    BluetoothDevice.TRANSPORT_LE
                )
            except Exception as e:
                print(f"[BLEService] TRANSPORT_LE connectGatt failed, falling back: {e}")
                try:
                    self.gatt = device.connectGatt(activity, False, self._gatt_cb)
                except Exception as err:
                    print(f"[BLEService] Exception during connectGatt: {err}")
                    self.is_connected = False
                    if on_result:
                        Clock.schedule_once(lambda dt: on_result(False), 0)

    def send_command(self, data_bytes):
        """Writes control bytes to the connected robot using modern and legacy write APIs."""
        if not self.is_connected or not self.gatt:
            print("[BLEService] Cannot send data: Not connected.")
            return False

        if self._write_characteristic:
            try:
                # Modern Android (API 33+) vs Legacy API compatibility fallback
                BluetoothGattCharacteristic = autoclass("android.bluetooth.BluetoothGattCharacteristic")
                write_type = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT

                if hasattr(self.gatt, "writeCharacteristic") and len(self.gatt.writeCharacteristic.args) == 3:
                    return self.gatt.writeCharacteristic(
                        self._write_characteristic,
                        data_bytes,
                        write_type
                    )
                else:
                    self._write_characteristic.setValue(data_bytes)
                    return self.gatt.writeCharacteristic(self._write_characteristic)
            except Exception as e:
                print(f"[BLEService] Write characteristic failed: {e}")
                return False

        print("[BLEService] Write characteristic not resolved yet.")
        return False

    def disconnect(self, on_complete=None):
        """Gracefully disconnects and releases GATT hardware resources."""
        if self.gatt:
            print("[BLEService] Closing GATT client...")
            try:
                self.gatt.disconnect()
                self.gatt.close()
            except Exception as e:
                print(f"[BLEService] Error during disconnect: {e}")
            finally:
                self.gatt = None
                self.is_connected = False
                self._write_characteristic = None
                self._gatt_listener = None
                self._gatt_cb = None
        else:
            print("[BLEService] No active GATT session to disconnect.")
            self.is_connected = False

        if on_complete:
            Clock.schedule_once(lambda dt: on_complete(), 0)

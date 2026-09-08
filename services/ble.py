from jnius import PythonJavaClass, autoclass, java_method
from kivy.clock import Clock
from models.bot import Robot
from models.settings import ConnectionSettings

# CCCD (Client Characteristic Configuration Descriptor) — the standard
# GATT descriptor a central writes to actually enable notifications on a
# characteristic. Not user-configurable; it's part of the Bluetooth spec,
# not the Nordic UART Service.
CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"


class BLEService:
    # NOTE: UUIDs used to live here as hardcoded class constants (and had a
    # typo in the last segment that didn't match the standard Nordic UART
    # UUIDs). They're now read from self.settings on every connect(), so
    # they can be changed at runtime via the settings dialog. Defaults live
    # in models/settings.py (ConnectionSettings) — the correct standard
    # Nordic UART Service UUIDs.

    def __init__(self, settings=None):
        # Falls back to a fresh default-valued ConnectionSettings if none is
        # passed, so BLEService still works standalone without requiring
        # the app to wire one up.
        self.settings = settings or ConnectionSettings()
        self.is_connected = False
        self.connected_device = None
        self.gatt = None
        self._write_characteristic = None
        self._notify_characteristic = None
        self._scan_cb = None
        self._gatt_cb = None
        self._gatt_listener = None
        self.on_data_received = None
        # Buffers partial notification chunks until a full CRLF-terminated
        # line has arrived — a single line easily spans several
        # notifications since each one is capped by the BLE MTU (~20 bytes
        # unnegotiated).
        self._rx_buffer = ""

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
        try:
            BluetoothAdapter = autoclass("android.bluetooth.BluetoothAdapter")
            adapter = BluetoothAdapter.getDefaultAdapter()
            return adapter is not None and adapter.isEnabled()
        except Exception as e:
            print(f"[BLEService] Error checking Bluetooth status: {e}")
            return False

    @classmethod
    def prompt_enable_bluetooth(cls):
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
                    service_self._notify_characteristic = None
                    service_self._rx_buffer = ""

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
                        rx_target = service_self.settings.ble_rx_uuid.lower().replace("-", "")
                        tx_target = service_self.settings.ble_tx_uuid.lower().replace("-", "")
                        matched_rx = False
                        matched_tx = None

                        try:
                            services = gatt.getServices()
                            for i in range(services.size()):
                                svc = services.get(i)
                                chars = svc.getCharacteristics()
                                for j in range(chars.size()):
                                    c = chars.get(j)
                                    char_uuid = c.getUuid().toString().lower().replace("-", "")
                                    if not matched_rx and rx_target in char_uuid:
                                        service_self._write_characteristic = c
                                        matched_rx = True
                                        print(f"[BLEService] Matched RX (write) characteristic: {c.getUuid().toString()}")
                                    elif matched_tx is None and tx_target in char_uuid:
                                        matched_tx = c
                                        print(f"[BLEService] Matched TX (notify) characteristic: {c.getUuid().toString()}")
                        except Exception as err:
                            print(f"[BLEService] Characteristic parsing error: {err}")

                        if matched_tx is not None:
                            service_self._notify_characteristic = matched_tx
                            service_self._enable_notifications(gatt, matched_tx)
                        else:
                            print(
                                "[BLEService] No TX (notify) characteristic matched "
                                f"'{service_self.settings.ble_tx_uuid}' — BLE read will not work "
                                "until the peripheral exposes a matching characteristic."
                            )

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

            # Fires when the peripheral sends a notification on a
            # characteristic we've subscribed to (see _enable_notifications).
            # This is the piece that was missing entirely before: the RX
            # (write) characteristic was being found, but nothing ever
            # looked up the TX (notify) characteristic, enabled
            # notifications on it at the GATT level, or implemented this
            # handler to receive the resulting callback.
            #
            # NOTE: this assumes org.kivy.android.GattCallback$Listener (the
            # custom Java interface autoclass'd above) declares a matching
            # onCharacteristicChanged method with this signature — the
            # 2-argument pre-API-33 overload
            # (BluetoothGatt, BluetoothGattCharacteristic). That Java source
            # wasn't available to check directly. If the interface instead
            # only declares the 3-argument API 33+ overload
            # (..., byte[] value), jnius will silently never call this
            # method (no notifications will show up, no error either) and
            # the java_method signature string below needs to change to
            # "(Landroid/bluetooth/BluetoothGatt;Landroid/bluetooth/BluetoothGattCharacteristic;[B)V"
            # with a third `value` parameter. Share GattCallback.java if
            # that turns out to be the case.
            @java_method("(Landroid/bluetooth/BluetoothGatt;Landroid/bluetooth/BluetoothGattCharacteristic;)V")
            def onCharacteristicChanged(self, gatt, characteristic):
                try:
                    char_uuid = characteristic.getUuid().toString().lower().replace("-", "")
                    tx_target = service_self.settings.ble_tx_uuid.lower().replace("-", "")
                    if tx_target not in char_uuid:
                        return  # notification from a characteristic we don't care about

                    raw = characteristic.getValue()
                    if raw is None:
                        return

                    # raw is a Java byte[] (signed bytes) — mask to unsigned
                    # before decoding as UTF-8 text.
                    data_bytes = bytes(b & 0xFF for b in raw)
                    service_self._on_ble_bytes(data_bytes)
                except Exception as err:
                    print(f"[BLEService] onCharacteristicChanged error: {err}")

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

    def _enable_notifications(self, gatt, characteristic):
        """Enables notifications on the TX characteristic, both at the
        Android BluetoothGatt level and at the actual GATT protocol level.

        setCharacteristicNotification() only turns on local delivery of the
        callback — it does NOT tell the peripheral to start sending
        notifications. That requires separately writing the CCCD
        descriptor's ENABLE_NOTIFICATION_VALUE, which is the step this
        service was missing entirely before. Skipping it is a very common
        way to end up with "everything looks connected, nothing ever
        arrives."
        """
        try:
            gatt.setCharacteristicNotification(characteristic, True)
        except Exception as e:
            print(f"[BLEService] setCharacteristicNotification failed: {e}")
            return

        try:
            UUID = autoclass("java.util.UUID")
            descriptor = characteristic.getDescriptor(UUID.fromString(CCCD_UUID))
        except Exception as e:
            print(f"[BLEService] Failed to look up CCCD descriptor: {e}")
            descriptor = None

        if descriptor is None:
            print(
                "[BLEService] TX characteristic has no CCCD (0x2902) descriptor — "
                "notifications cannot be enabled at the GATT protocol level, even "
                "though setCharacteristicNotification() succeeded locally."
            )
            return

        try:
            BluetoothGattDescriptor = autoclass("android.bluetooth.BluetoothGattDescriptor")
            enable_value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE

            # Same API-33-vs-legacy split as send_command()'s writeCharacteristic:
            # the modern writeDescriptor(descriptor, value) overload returns an
            # int status code (0 == success); the legacy setValue()+writeDescriptor(descriptor)
            # pair returns a real boolean from writeDescriptor().
            try:
                status = gatt.writeDescriptor(descriptor, enable_value)
                ok = (status == 0)
            except Exception:
                descriptor.setValue(enable_value)
                ok = bool(gatt.writeDescriptor(descriptor))

            if ok:
                print("[BLEService] CCCD notifications enabled on TX characteristic.")
            else:
                print("[BLEService] writeDescriptor() reported failure enabling CCCD notifications.")
        except Exception as e:
            print(f"[BLEService] Failed to write CCCD descriptor: {e}")

    def _on_ble_bytes(self, data_bytes):
        """Buffers incoming notification bytes and fires on_data_received
        once per complete CRLF-terminated line, mirroring WiFiService's
        _listen_worker framing so both transports behave identically in
        the telemetry console.
        """
        try:
            self._rx_buffer += data_bytes.decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"[BLEService] RX decode error: {e}")
            return

        while "\r\n" in self._rx_buffer:
            line, self._rx_buffer = self._rx_buffer.split("\r\n", 1)
            line = line.strip()
            if line and self.on_data_received:
                Clock.schedule_once(lambda dt, msg=line: self.on_data_received(msg), 0)

    def send_command(self, payload):
        """Writes string or byte data to connected BLE device."""
        if not self.is_connected or not self.gatt:
            print("[BLEService] Cannot send data: Not connected.")
            return False

        if isinstance(payload, str):
            data_bytes = (payload.strip() + "\r\n").encode("utf-8")
        else:
            data_bytes = payload

        if self._write_characteristic:
            try:
                BluetoothGattCharacteristic = autoclass("android.bluetooth.BluetoothGattCharacteristic")
                write_type = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT

                # API 33+ Modern write API returns an int STATUS CODE, where
                # BluetoothStatusCodes.SUCCESS == 0 — NOT a boolean. That was
                # the actual bug behind "Network TX failed": in Python, 0 is
                # falsy, so a *successful* write was returned as 0, which
                # every caller up the chain (app.send_command,
                # TelemetryScreen.send) correctly treated as "falsy" i.e.
                # failure, even though the write had gone out fine. We now
                # explicitly compare the status code instead of returning it
                # directly.
                try:
                    status = self.gatt.writeCharacteristic(
                        self._write_characteristic,
                        data_bytes,
                        write_type
                    )
                    return status == 0
                except Exception:
                    # Legacy fallback (pre-API 33) — writeCharacteristic(characteristic)
                    # genuinely returns a boolean here, so this one was already correct.
                    self._write_characteristic.setValue(data_bytes)
                    return bool(self.gatt.writeCharacteristic(self._write_characteristic))

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
                self._notify_characteristic = None
                self._rx_buffer = ""
                self._gatt_listener = None
                self._gatt_cb = None
        else:
            print("[BLEService] No active GATT session to disconnect.")
            self.is_connected = False

        if on_complete:
            Clock.schedule_once(lambda dt: on_complete(), 0)

package org.kivy.android;

import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;

public class GattCallback extends BluetoothGattCallback {
    public interface Listener {
        void onConnectionStateChange(BluetoothGatt gatt, int status, int newState);
        void onServicesDiscovered(BluetoothGatt gatt, int status);
    }

    private Listener listener;

    public GattCallback(Listener listener) {
        this.listener = listener;
    }

    @Override
    public void onConnectionStateChange(BluetoothGatt gatt, int status, int newState) {
        if (listener != null) listener.onConnectionStateChange(gatt, status, newState);
    }

    @Override
    public void onServicesDiscovered(BluetoothGatt gatt, int status) {
        if (listener != null) listener.onServicesDiscovered(gatt, status);
    }
}

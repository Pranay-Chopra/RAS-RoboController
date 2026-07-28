package org.kivy.android;

import android.net.ConnectivityManager;
import android.net.Network;

public class WiFiCallback extends ConnectivityManager.NetworkCallback {
    public interface Listener {
        void onAvailable(Network network);
        void onUnavailable();
        void onLost(Network network);
    }

    private Listener listener;

    public WiFiCallback(Listener listener) {
        this.listener = listener;
    }

    @Override
    public void onAvailable(Network network) {
        if (listener != null) listener.onAvailable(network);
    }

    @Override
    public void onUnavailable() {
        if (listener != null) listener.onUnavailable();
    }

    @Override
    public void onLost(Network network) {
        if (listener != null) listener.onLost(network);
    }
}

def is_location_enabled() -> bool:
    """Checks if Android system Location Services (GPS or Network) are enabled."""
    print("[LocationService] Checking location status...")
    try:
        # Lazy import inside function
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        LocationManager = autoclass("android.location.LocationManager")

        activity = PythonActivity.mActivity
        if not activity:
            print("[LocationService] PythonActivity.mActivity is None")
            return True

        location_service = activity.getSystemService(Context.LOCATION_SERVICE)
        if not location_service:
            print("[LocationService] Could not retrieve LOCATION_SERVICE")
            return True

        gps_enabled = location_service.isProviderEnabled(
            LocationManager.GPS_PROVIDER
        )
        network_enabled = location_service.isProviderEnabled(
            LocationManager.NETWORK_PROVIDER
        )

        status = gps_enabled or network_enabled
        print(f"[LocationService] Location Enabled: {status}")
        return status

    except Exception as e:
        import traceback

        print(f"[LocationService] Exception checking status: {e}")
        traceback.print_exc()
        return True

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'dart:async';

SharedPreferences? globalPrefs;

class AppSettings {
  const AppSettings({
    this.enableGeofence = false,
    this.geofenceRadius = 200.0,
    this.triggerMode = 'periodic',
    this.periodicInterval = 30,
    this.showRadiusOnMap = true,
  });

  final bool enableGeofence;
  final double geofenceRadius;
  final String triggerMode;
  final int periodicInterval;
  final bool showRadiusOnMap;

  AppSettings copyWith({
    bool? enableGeofence,
    double? geofenceRadius,
    String? triggerMode,
    int? periodicInterval,
    bool? showRadiusOnMap,
  }) {
    return AppSettings(
      enableGeofence: enableGeofence ?? this.enableGeofence,
      geofenceRadius: geofenceRadius ?? this.geofenceRadius,
      triggerMode: triggerMode ?? this.triggerMode,
      periodicInterval: periodicInterval ?? this.periodicInterval,
      showRadiusOnMap: showRadiusOnMap ?? this.showRadiusOnMap,
    );
  }
}

class AppSettingsNotifier extends Notifier<AppSettings> {
  @override
  AppSettings build() {
    final prefs = globalPrefs!;
    return AppSettings(
      enableGeofence: prefs.getBool('enableGeofence') ?? false,
      geofenceRadius: prefs.getDouble('geofenceRadius') ?? 200.0,
      triggerMode: prefs.getString('triggerMode') ?? 'periodic',
      periodicInterval: prefs.getInt('periodicInterval') ?? 30,
      showRadiusOnMap: prefs.getBool('showRadiusOnMap') ?? true,
    );
  }

  void updateState(AppSettings settings) {
    state = settings;
  }

  Future<void> saveSettings() async {
    final prefs = globalPrefs!;
    await prefs.setBool('enableGeofence', state.enableGeofence);
    await prefs.setDouble('geofenceRadius', state.geofenceRadius);
    await prefs.setString('triggerMode', state.triggerMode);
    await prefs.setInt('periodicInterval', state.periodicInterval);
    await prefs.setBool('showRadiusOnMap', state.showRadiusOnMap);
  }

  Future<void> updateSettings(AppSettings settings) async {
    updateState(settings);
    await saveSettings();
  }
}



final appSettingsProvider = NotifierProvider<AppSettingsNotifier, AppSettings>(() {
  return AppSettingsNotifier();
});

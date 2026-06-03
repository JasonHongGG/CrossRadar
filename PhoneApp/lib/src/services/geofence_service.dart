import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../data/credential_store.dart';
import '../data/mobile_bundle_repository.dart';
import '../data/tdx_client.dart';
import '../domain/models.dart';
import '../domain/prediction_service.dart';
import '../domain/railway_clock.dart';
import 'app_settings_service.dart';
import 'location_service.dart';
import 'notification_service.dart';

class GeofenceService {
  GeofenceService(this.ref) {
    _init();
  }

  final Ref ref;
  final _locationService = LocationService();
  final _notificationService = NotificationService();
  final _credentialStore = const TdxCredentialStore();
  final _railwayClock = RailwayClock.instance;
  late final _tdxClient = TdxTraClient(railwayClock: _railwayClock);
  late final _predictionService = PredictionService(railwayClock: _railwayClock);

  StreamSubscription<GeoPoint>? _locationSub;
  Timer? _periodicTimer;
  GeoPoint? _latestPosition;
  String? _lastTriggeredCrossingId;
  DateTime? _lastTriggerTime;

  void _init() {
    ref.listen<AppSettings>(appSettingsProvider, (previous, current) {
      if (current.enableGeofence) {
        _startListening();
        
        if (current.triggerMode == 'periodic') {
           if (previous?.triggerMode != 'periodic' || previous?.periodicInterval != current.periodicInterval) {
             _startPeriodicTimer(current.periodicInterval);
           }
        } else {
           _periodicTimer?.cancel();
           _periodicTimer = null;
        }
      } else {
        _stopListening();
      }
    }, fireImmediately: true);
  }

  void _startPeriodicTimer(int intervalSeconds) {
    _periodicTimer?.cancel();
    _periodicTimer = Timer.periodic(Duration(seconds: intervalSeconds), (_) {
      if (_latestPosition != null) {
        _checkGeofence(_latestPosition!);
      }
    });
  }

  void _startListening() {
    if (_locationSub != null) return;
    
    // Fetch an initial position to ensure _latestPosition is not null
    _locationService.currentPosition().then((pos) {
      if (pos != null && _latestPosition == null) {
        _latestPosition = pos;
        _checkGeofence(pos);
      }
    });

    _locationSub = _locationService.getPositionStream().listen((position) {
      _latestPosition = position;
      _checkGeofence(position);
    });
    
    final settings = ref.read(appSettingsProvider);
    if (settings.triggerMode == 'periodic') {
      _startPeriodicTimer(settings.periodicInterval);
    }
  }

  void _stopListening() {
    _locationSub?.cancel();
    _locationSub = null;
    _periodicTimer?.cancel();
    _periodicTimer = null;
    _latestPosition = null;
    _lastTriggeredCrossingId = null;
    _lastTriggerTime = null;
  }

  Future<void> _checkGeofence(GeoPoint position) async {
    final settings = ref.read(appSettingsProvider);
    if (!settings.enableGeofence) return;

    final bundleAsync = ref.read(mobileBundleProvider);
    final bundle = bundleAsync.value;
    if (bundle == null) return;

    const distanceCalc = Distance();
    final userLatLng = LatLng(position.lat, position.lon);

    Crossing? nearestCrossing;
    double minDistance = double.infinity;

    for (final crossing in bundle.crossings) {
      final d = distanceCalc(userLatLng, LatLng(crossing.geometry.lat, crossing.geometry.lon));
      if (d <= settings.geofenceRadius && d < minDistance) {
        minDistance = d;
        nearestCrossing = crossing;
      }
    }

    if (nearestCrossing == null) {
      // User is outside any crossing's radius
      _lastTriggeredCrossingId = null;
      return;
    }

    // User is inside the radius of `nearestCrossing`
    final now = DateTime.now();

    if (settings.triggerMode == 'once') {
      if (_lastTriggeredCrossingId == nearestCrossing.id) {
        // Already triggered for this crossing, do nothing
        return;
      }
      _lastTriggeredCrossingId = nearestCrossing.id;
      _lastTriggerTime = now;
      print('[Geofence] Triggering once for crossing ${nearestCrossing.name}');
      await _triggerAlert(nearestCrossing, bundle);
    } else if (settings.triggerMode == 'periodic') {
      // Tolerate up to 2 seconds of timer drift
      if (_lastTriggeredCrossingId != nearestCrossing.id || _lastTriggerTime == null || now.difference(_lastTriggerTime!).inSeconds >= (settings.periodicInterval - 2)) {
        print('[Geofence] Triggering periodic for crossing ${nearestCrossing.name} (elapsed: ${_lastTriggerTime == null ? 'first' : now.difference(_lastTriggerTime!).inSeconds}s)');
        _lastTriggeredCrossingId = nearestCrossing.id;
        _lastTriggerTime = now;
        await _triggerAlert(nearestCrossing, bundle);
      } else {
        print('[Geofence] Skipping periodic tick, only ${now.difference(_lastTriggerTime!).inSeconds}s elapsed');
      }
    }
  }

  Future<void> _triggerAlert(Crossing crossing, MobileBundle bundle) async {
    try {
      final credentials = await _credentialStore.read();
      if (credentials == null) return;

      // Use the built-in cache TTL (90 seconds for liveboards, 5 minutes for trainInfos)
      // to avoid hammering the TDX API every 10 seconds just to update a local countdown timer.
      final liveboards = await _tdxClient.getLiveboardsSnapshot(credentials, forceRefresh: false);
      final timetables = await _tdxClient.getTodayTimetablesSnapshot(credentials, forceRefresh: false);
      final trainInfos = await _tdxClient.getTodayTrainInfosSnapshot(credentials, forceRefresh: false);

      final snapshot = PredictionDataSnapshot(
        comprehensive: liveboards.complete && timetables.complete && trainInfos.complete,
        liveboardCount: liveboards.items.length,
        delayedLiveboardCount: liveboards.items.where((item) => (item.delayTime ?? 0) != 0).length,
        timetableCount: timetables.items.length,
        trainInfoCount: trainInfos.items.length,
        delayedTrainInfoCount: trainInfos.items.where((item) => (item.delayTime ?? 0) != 0).length,
        liveboardScope: const ['all'],
        sources: [
          liveboards.toSnapshotSource(source: 'liveboards', scope: 'all', delayed: (item) => (item.delayTime ?? 0) != 0),
          timetables.toSnapshotSource(source: 'timetables'),
          trainInfos.toSnapshotSource(source: 'train_info', delayed: (item) => (item.delayTime ?? 0) != 0),
        ],
      );

      final envelope = _predictionService.predictForCrossing(
        crossing: crossing,
        liveboards: liveboards.items,
        timetables: timetables.items,
        trainInfos: trainInfos.items,
        stationLookupById: bundle.stationById,
        calibrationRules: bundle.calibrationRules,
        stationPairProjections: bundle.stationPairProjections,
        stationPairProjectionRejections: bundle.stationPairProjectionRejections,
        dataSnapshot: snapshot,
        horizonMinutes: null,
      );

      await _notificationService.showGeofenceAlert(crossing, envelope);
    } catch (e) {
      // Ignore errors in background execution
    }
  }
}

final geofenceServiceProvider = Provider<GeofenceService>((ref) {
  return GeofenceService(ref);
});

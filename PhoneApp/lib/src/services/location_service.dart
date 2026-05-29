import 'package:geolocator/geolocator.dart';
import 'package:permission_handler/permission_handler.dart' as permissions;

import '../domain/models.dart';

class LocationService {
  Future<GeoPoint?> currentPosition() async {
    var status = await permissions.Permission.locationWhenInUse.status;
    if (!status.isGranted) {
      status = await permissions.Permission.locationWhenInUse.request();
    }
    if (!status.isGranted) return null;
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) return null;
    final position = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(accuracy: LocationAccuracy.high),
    );
    return GeoPoint(lat: position.latitude, lon: position.longitude);
  }
}

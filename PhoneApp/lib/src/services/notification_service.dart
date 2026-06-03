import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:permission_handler/permission_handler.dart' as permissions;
import 'package:timezone/data/latest.dart' as timezone_data;
import 'package:timezone/timezone.dart' as timezone;

import '../domain/models.dart';

class NotificationService {
  NotificationService({FlutterLocalNotificationsPlugin? plugin}) : _plugin = plugin ?? FlutterLocalNotificationsPlugin();

  final FlutterLocalNotificationsPlugin _plugin;
  bool _initialized = false;

  static const _channel = AndroidNotificationChannel('crossradar_prediction', 'CrossRadar predictions', description: 'Train approach warnings for selected level crossings.', importance: Importance.high);

  Future<void> initialize() async {
    if (_initialized) return;
    timezone_data.initializeTimeZones();
    const android = AndroidInitializationSettings('@mipmap/ic_launcher');
    await _plugin.initialize(settings: const InitializationSettings(android: android));
    await _plugin.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()?.createNotificationChannel(_channel);
    _initialized = true;
  }

  Future<bool> requestPermission() async {
    final status = await permissions.Permission.notification.request();
    return status.isGranted;
  }

  Future<void> showPredictionAlert(PredictionRecord prediction) async {
    await initialize();
    await _plugin.show(id: prediction.trainNo.hashCode, title: '${prediction.trainNo}次 ${prediction.trainType ?? ''}'.trim(), body: '${prediction.upstreamStationName} → ${prediction.downstreamStationName}', notificationDetails: _details);
  }

  Future<void> schedulePredictionAlert(PredictionRecord prediction, Crossing crossing) async {
    await initialize();
    final id = crossing.id.hashCode;
    await _plugin.cancel(id: id);
    final scheduledAt = prediction.eta.subtract(Duration(minutes: prediction.warningWindowMinutes));
    final title = '${prediction.trainNo}次 ${prediction.trainType ?? ''}'.trim();
    final body = '${crossing.name} · ${prediction.direction == 1 ? '南下' : '北上'} · ${_clock(prediction.eta)}';
    if (!scheduledAt.isAfter(DateTime.now())) {
      await _plugin.show(id: id, title: title, body: body, notificationDetails: _details);
      return;
    }
    await _plugin.zonedSchedule(id: id, title: title, body: body, scheduledDate: timezone.TZDateTime.from(scheduledAt, timezone.local), notificationDetails: _details, androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle);
  }

  Future<void> showGeofenceAlert(Crossing crossing, PredictionEnvelope envelope) async {
    await initialize();
    final now = DateTime.now();

    final allPredictions = List.of(envelope.predictions)..sort((a, b) => a.eta.compareTo(b.eta));
    
    // Find recent passed (eta in the past 5 minutes)
    final recentPassed = allPredictions.where((p) {
      final diff = now.difference(p.eta);
      return diff.inSeconds >= 0 && diff.inMinutes < 5;
    }).lastOrNull;

    // Find next upcoming
    final nextUpcoming = allPredictions.where((p) => p.eta.isAfter(now)).firstOrNull;

    if (recentPassed != null) {
      final diff = now.difference(recentPassed.eta);
      final hh = diff.inHours.toString().padLeft(2, '0');
      final mm = (diff.inMinutes % 60).toString().padLeft(2, '0');
      final ss = (diff.inSeconds % 60).toString().padLeft(2, '0');
      final dirStr = recentPassed.direction == 1 ? '南下' : '北上';
      
      final title = '${crossing.name} 警報';
      final body = '$dirStr火車 已於 ${_clockSeconds(recentPassed.eta)} 通過 (已經過 $hh:$mm:$ss)';
      
      final uniqueId = DateTime.now().millisecondsSinceEpoch ~/ 1000;
      print('[NotificationService] Showing recentPassed notification ID: $uniqueId, body: $body');
      
      await _plugin.show(
        id: uniqueId,
        title: title,
        body: body,
        notificationDetails: _details,
      );
    } else {
      print('[NotificationService] No recentPassed train to show.');
    }

    if (nextUpcoming != null) {
      final diff = nextUpcoming.eta.difference(now);
      final hh = diff.inHours.toString().padLeft(2, '0');
      final mm = (diff.inMinutes % 60).toString().padLeft(2, '0');
      final ss = (diff.inSeconds % 60).toString().padLeft(2, '0');
      final dirStr = nextUpcoming.direction == 1 ? '南下' : '北上';
      
      final title = '${crossing.name} 警報';
      final body = '$dirStr火車 預計 ${_clockSeconds(nextUpcoming.eta)} 抵達 (剩餘 $hh:$mm:$ss)';
      
      final uniqueId = (DateTime.now().millisecondsSinceEpoch ~/ 1000) + 1;
      print('[NotificationService] Showing nextUpcoming notification ID: $uniqueId, body: $body');
      
      await _plugin.show(
        id: uniqueId,
        title: title,
        body: body,
        notificationDetails: _details,
      );
    } else {
      print('[NotificationService] No nextUpcoming train to show.');
    }
  }
}

const _details = NotificationDetails(
  android: AndroidNotificationDetails('crossradar_prediction', 'CrossRadar predictions', channelDescription: 'Train approach warnings for selected level crossings.', importance: Importance.high, priority: Priority.high),
);

String _clock(DateTime value) => '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';
String _clockSeconds(DateTime value) => '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}:${value.second.toString().padLeft(2, '0')}';

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../data/credential_store.dart';
import '../data/tdx_client.dart';
import '../domain/models.dart';
import '../domain/prediction_service.dart';
import '../services/location_service.dart';
import '../services/notification_service.dart';
import '../theme/app_theme.dart';

class PredictionScreen extends StatefulWidget {
  const PredictionScreen({super.key, required this.crossing, required this.bundle});

  final Crossing crossing;
  final MobileBundle bundle;

  @override
  State<PredictionScreen> createState() => _PredictionScreenState();
}

class _PredictionScreenState extends State<PredictionScreen> {
  final _credentialStore = const TdxCredentialStore();
  final _tdxClient = TdxTraClient();
  final _predictionService = PredictionService();
  final _locationService = LocationService();
  final _notificationService = NotificationService();
  final _mapController = MapController();
  Timer? _timer;
  PredictionEnvelope? _envelope;
  PredictionRuntimeState _runtime = const PredictionRuntimeState();
  GeoPoint? _userLocation;
  String? _error;
  var _loading = true;

  @override
  void initState() {
    super.initState();
    _refreshPrediction(forceRefresh: false);
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final mainPrediction = _envelope?.upcomingPredictions.firstOrNull;
    final following = (_envelope?.upcomingPredictions.length ?? 0) > 1 ? _envelope!.upcomingPredictions[1] : null;
    return Scaffold(
      appBar: AppBar(
        actions: [
          IconButton(tooltip: '定位', onPressed: _focusGps, icon: const Icon(Icons.my_location_rounded)),
          IconButton(tooltip: '刷新', onPressed: () => _refreshPrediction(forceRefresh: true), icon: const Icon(Icons.refresh_rounded)),
          IconButton(tooltip: '通知', onPressed: mainPrediction == null ? null : () => _notify(mainPrediction), icon: const Icon(Icons.notifications_active_rounded)),
        ],
      ),
      body: Stack(
        children: [
          ListView(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
            children: [
              _MiniMap(crossing: widget.crossing, userLocation: _userLocation, controller: _mapController),
              const SizedBox(height: 16),
              _CrossingStrip(crossing: widget.crossing),
              const SizedBox(height: 24),
              AnimatedSwitcher(
                duration: const Duration(milliseconds: 300),
                switchInCurve: Curves.easeOutCubic,
                child: _loading
                    ? const _PredictionSkeleton(key: ValueKey('loading'))
                    : _error != null
                    ? _UnavailablePanel(key: const ValueKey('error'), title: '無法更新', detail: _error!)
                    : _envelope?.available == false
                    ? _UnavailablePanel(key: const ValueKey('unavailable'), title: '暫無預測', detail: _envelope?.unavailableDetail ?? _envelope?.unavailableReason ?? '')
                    : mainPrediction == null
                    ? const _UnavailablePanel(key: ValueKey('empty'), title: '尚無班次', detail: '目前快照沒有可用的下一班資料。')
                    : Column(
                        key: ValueKey(mainPrediction.identityKey),
                        children: [
                          _MainPredictionPanel(prediction: mainPrediction, now: DateTime.now()),
                        ],
                      ),
              ),
              const SizedBox(height: 20),
              SizedBox(
                height: 140,
                child: PageView(
                  controller: PageController(viewportFraction: 0.92),
                  children: [
                    _CompactPredictionCard(icon: Icons.skip_previous_rounded, prediction: _runtime.previous),
                    _CompactPredictionCard(icon: Icons.skip_next_rounded, prediction: following),
                  ],
                ),
              ),
            ],
          ),
          if (_envelope?.dataSnapshot != null)
            Positioned(
              top: 8,
              right: 16,
              child: _SnapshotDot(snapshot: _envelope!.dataSnapshot!),
            ),
        ],
      ),
    );
  }

  Future<void> _refreshPrediction({required bool forceRefresh}) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final credentials = await _credentialStore.read();
      if (credentials == null) {
        setState(() {
          _loading = false;
          _error = '需要 TDX 憑證';
        });
        return;
      }
      final liveboardsFuture = _tdxClient.getLiveboardsSnapshot(credentials, forceRefresh: forceRefresh);
      final timetablesFuture = _tdxClient.getTodayTimetablesSnapshot(credentials, forceRefresh: forceRefresh);
      final trainInfosFuture = _tdxClient.getTodayTrainInfosSnapshot(credentials, forceRefresh: forceRefresh);
      final liveboards = await liveboardsFuture;
      final timetables = await timetablesFuture;
      final trainInfos = await trainInfosFuture;
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
      final envelope = _predictionService.predictForCrossing(crossing: widget.crossing, liveboards: liveboards.items, timetables: timetables.items, trainInfos: trainInfos.items, stationLookupById: widget.bundle.stationById, calibrationRules: widget.bundle.calibrationRules, stationPairProjections: widget.bundle.stationPairProjections, dataSnapshot: snapshot, horizonMinutes: null);
      if (!mounted) return;
      setState(() {
        _envelope = envelope;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error.toString();
      });
    }
  }

  void _tick() {
    final predictions = _envelope?.upcomingPredictions ?? const <PredictionRecord>[];
    if (predictions.isEmpty) return;
    setState(() => _runtime = _runtime.advance(predictions, DateTime.now()));
  }

  Future<void> _focusGps() async {
    final location = await _locationService.currentPosition();
    if (!mounted || location == null) return;
    setState(() => _userLocation = location);
    _mapController.move(LatLng(location.lat, location.lon), 15);
  }

  Future<void> _notify(PredictionRecord prediction) async {
    final ok = await _notificationService.requestPermission();
    if (!ok) return;
    await _notificationService.schedulePredictionAlert(prediction, widget.crossing);
  }
}

class _MiniMap extends StatelessWidget {
  const _MiniMap({required this.crossing, required this.userLocation, required this.controller});

  final Crossing crossing;
  final GeoPoint? userLocation;
  final MapController controller;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 188,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        boxShadow: [BoxShadow(color: AppColors.pastelBlueDeep.withValues(alpha: 0.1), blurRadius: 16, offset: const Offset(0, 8))],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(24),
        child: Stack(
          children: [
            FlutterMap(
              mapController: controller,
              options: MapOptions(initialCenter: LatLng(crossing.geometry.lat, crossing.geometry.lon), initialZoom: 14),
              children: [
                TileLayer(urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', userAgentPackageName: 'crossradar.phone', retinaMode: true),
                PolylineLayer(polylines: _connectionLine()),
                MarkerLayer(
                  markers: [
                    if (crossing.stationA.position != null) _stationMarker(crossing.stationA),
                    if (crossing.stationB.position != null) _stationMarker(crossing.stationB),
                    Marker(point: LatLng(crossing.geometry.lat, crossing.geometry.lon), width: 44, height: 44, child: const _CrossingMarker()),
                    if (userLocation != null)
                      Marker(point: LatLng(userLocation!.lat, userLocation!.lon), width: 28, height: 28, child: const Icon(Icons.my_location_rounded, color: AppColors.pastelBlueDeep)),
                  ],
                ),
              ],
            ),
            Positioned(
              right: 8,
              bottom: 8,
              child: FloatingActionButton.small(
                heroTag: 'prediction_compass',
                onPressed: () => controller.rotate(0),
                backgroundColor: Colors.white,
                foregroundColor: AppColors.pastelBlueDeep,
                elevation: 4,
                child: const Icon(Icons.explore_rounded),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Marker _stationMarker(StationRef station) {
    final point = station.position!;
    return Marker(
      point: LatLng(point.lat, point.lon),
      width: 100,
      height: 36,
      alignment: Alignment.topCenter,
      child: Center(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(color: AppColors.pastelBlueSoft, borderRadius: BorderRadius.circular(12), border: Border.all(color: Colors.white, width: 2), boxShadow: [BoxShadow(color: AppColors.pastelBlueDeep.withValues(alpha: 0.3), blurRadius: 4)]),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.train_rounded, color: AppColors.pastelBlueDeep, size: 14),
              const SizedBox(width: 4),
              Flexible(child: Text(station.name ?? '未知車站', overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: AppColors.pastelBlueDeep))),
            ],
          ),
        ),
      ),
    );
  }

  List<Polyline> _connectionLine() {
    final stationA = crossing.stationA.position;
    final stationB = crossing.stationB.position;
    if (stationA == null || stationB == null) return const [];
    return [Polyline(points: [LatLng(stationA.lat, stationA.lon), LatLng(crossing.geometry.lat, crossing.geometry.lon), LatLng(stationB.lat, stationB.lon)], color: AppColors.pastelBlueDeep.withValues(alpha: 0.6), strokeWidth: 4)];
  }
}

class _CrossingMarker extends StatelessWidget {
  const _CrossingMarker();

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(color: AppColors.pastelPinkDeep, shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 3), boxShadow: [BoxShadow(color: AppColors.pastelPinkDeep.withValues(alpha: 0.4), blurRadius: 8, offset: const Offset(0, 4))]),
      child: const Icon(Icons.railway_alert_rounded, color: Colors.white, size: 20),
    );
  }
}

class _CrossingStrip extends StatelessWidget {
  const _CrossingStrip({required this.crossing});

  final Crossing crossing;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(crossing.name, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w900, color: AppColors.ink)),
              const SizedBox(height: 4),
              if (crossing.subtitle.isNotEmpty) Text(crossing.subtitle, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: AppColors.muted)),
            ],
          ),
        ),
        const SizedBox(width: 12),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          decoration: BoxDecoration(color: AppColors.pastelBlueSoft, borderRadius: BorderRadius.circular(20)),
          child: Text(crossing.stationPairLabel, style: const TextStyle(fontWeight: FontWeight.w800, color: AppColors.pastelBlueDeep)),
        ),
      ],
    );
  }
}

class _MainPredictionPanel extends StatelessWidget {
  const _MainPredictionPanel({required this.prediction, required this.now});

  final PredictionRecord prediction;
  final DateTime now;

  @override
  Widget build(BuildContext context) {
    final remaining = prediction.eta.difference(now);
    final isWarning = remaining.inSeconds <= prediction.warningWindowMinutes * 60;
    
    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: isWarning ? AppColors.pastelPinkSoft : Colors.white,
        borderRadius: BorderRadius.circular(32),
        border: Border.all(color: isWarning ? AppColors.pastelPinkDeep.withValues(alpha: 0.3) : AppColors.pastelBlueSoft, width: 1.5),
        boxShadow: [BoxShadow(color: (isWarning ? AppColors.pastelPinkDeep : AppColors.pastelBlueDeep).withValues(alpha: 0.12), blurRadius: 32, offset: const Offset(0, 16))],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(prediction.dataBasis == 'liveboard' ? Icons.bolt_rounded : Icons.schedule_rounded, color: isWarning ? AppColors.pastelPinkDeep : AppColors.pastelBlueDeep),
              const SizedBox(width: 8),
              Text('${prediction.trainNo}次', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900, color: AppColors.ink)),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(color: (prediction.direction == 1 ? AppColors.pastelBlueSoft : AppColors.pastelPinkSoft), borderRadius: BorderRadius.circular(12)),
                child: Row(
                  children: [
                    Icon(prediction.direction == 1 ? Icons.south_rounded : Icons.north_rounded, size: 16, color: prediction.direction == 1 ? AppColors.pastelBlueDeep : AppColors.pastelPinkDeep),
                    const SizedBox(width: 4),
                    Text(prediction.direction == 1 ? '南下' : '北上', style: TextStyle(fontWeight: FontWeight.w900, color: prediction.direction == 1 ? AppColors.pastelBlueDeep : AppColors.pastelPinkDeep)),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 24),
          Center(
            child: Text(
              _formatCountdown(remaining),
              style: TextStyle(
                fontSize: 64,
                height: 1.0,
                letterSpacing: -2,
                fontWeight: FontWeight.w900,
                color: isWarning ? AppColors.danger : AppColors.pastelBlueDeep,
              ),
            ),
          ),
          const SizedBox(height: 24),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _TimelineNode(name: prediction.previousStopStationName ?? prediction.upstreamStationName, time: prediction.previousStopDeparture, alignStart: true),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: Stack(
                    alignment: Alignment.center,
                    children: [
                      Container(height: 4, decoration: BoxDecoration(color: AppColors.pastelBlueSoft, borderRadius: BorderRadius.circular(2))),
                      LinearProgressIndicator(value: _progress(remaining, prediction.warningWindowMinutes), minHeight: 4, borderRadius: BorderRadius.circular(2), backgroundColor: Colors.transparent, color: isWarning ? AppColors.danger : AppColors.pastelBlueDeep),
                      Icon(Icons.directions_railway_rounded, color: isWarning ? AppColors.danger : AppColors.pastelBlueDeep),
                    ],
                  ),
                ),
              ),
              _TimelineNode(name: prediction.nextStopStationName ?? prediction.downstreamStationName, time: prediction.nextStopArrival, alignStart: false),
            ],
          ),
          const SizedBox(height: 24),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _IconStat(icon: Icons.access_time_rounded, value: _formatClock(prediction.eta)),
              const SizedBox(width: 24),
              _IconStat(icon: Icons.update_rounded, value: _delayText(prediction), color: (prediction.delaySeconds ?? 0) > 0 ? AppColors.amber : AppColors.muted),
              const SizedBox(width: 24),
              _IconStat(icon: Icons.speed_rounded, value: _accuracyText(prediction)),
            ],
          ),
        ],
      ),
    );
  }

  static double _progress(Duration remaining, int warningMinutes) {
    final window = warningMinutes * 60;
    if (window <= 0) return 0;
    return (1.0 - remaining.inSeconds.clamp(0, window) / window).clamp(0.0, 1.0);
  }
}

class _TimelineNode extends StatelessWidget {
  const _TimelineNode({required this.name, required this.time, required this.alignStart});
  final String name;
  final DateTime? time;
  final bool alignStart;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: alignStart ? CrossAxisAlignment.start : CrossAxisAlignment.end,
      children: [
        Text(name, style: const TextStyle(fontWeight: FontWeight.w900, color: AppColors.ink)),
        const SizedBox(height: 4),
        Text(_formatClock(time), style: const TextStyle(color: AppColors.muted, fontWeight: FontWeight.w700, fontSize: 12)),
      ],
    );
  }
}

class _IconStat extends StatelessWidget {
  const _IconStat({required this.icon, required this.value, this.color = AppColors.muted});
  final IconData icon;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, size: 16, color: color),
        const SizedBox(width: 6),
        Text(value, style: TextStyle(fontWeight: FontWeight.w700, color: color)),
      ],
    );
  }
}

class _SnapshotDot extends StatelessWidget {
  const _SnapshotDot({required this.snapshot});
  final PredictionDataSnapshot snapshot;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: snapshot.sources.map((item) => '${_sourceLabel(item.source)} ${item.recordCount}${item.isStale ? ' stale' : ''}').join(' · '),
      child: Container(
        width: 12,
        height: 12,
        decoration: BoxDecoration(
          color: snapshot.hasStaleSource ? AppColors.amber : AppColors.mint,
          shape: BoxShape.circle,
          border: Border.all(color: Colors.white, width: 2),
        ),
      ),
    );
  }
}

class _CompactPredictionCard extends StatelessWidget {
  const _CompactPredictionCard({required this.icon, required this.prediction});
  final IconData icon;
  final PredictionRecord? prediction;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(right: 12),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      color: Colors.white,
      shadowColor: AppColors.pastelBlueDeep.withValues(alpha: 0.1),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: prediction == null
            ? Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(icon, color: AppColors.muted),
                  const Spacer(),
                  const Icon(Icons.hourglass_empty_rounded, color: AppColors.muted),
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(padding: const EdgeInsets.all(6), decoration: BoxDecoration(color: AppColors.pastelBlueSoft, borderRadius: BorderRadius.circular(10)), child: Icon(icon, size: 18, color: AppColors.pastelBlueDeep)),
                      const Spacer(),
                      Text('${prediction!.trainNo}次', style: const TextStyle(fontWeight: FontWeight.w900, color: AppColors.ink)),
                    ],
                  ),
                  const Spacer(),
                  Text('${prediction!.previousStopStationName ?? prediction!.upstreamStationName} → ${prediction!.nextStopStationName ?? prediction!.downstreamStationName}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: AppColors.muted)),
                  const SizedBox(height: 4),
                  Text(_formatClock(prediction!.eta), style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w900, color: AppColors.pastelBlueDeep)),
                ],
              ),
      ),
    );
  }
}

class _PredictionSkeleton extends StatelessWidget {
  const _PredictionSkeleton({super.key});
  @override
  Widget build(BuildContext context) {
    return Container(height: 320, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(32)), child: const Center(child: CircularProgressIndicator()));
  }
}

class _UnavailablePanel extends StatelessWidget {
  const _UnavailablePanel({super.key, required this.title, required this.detail});
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 240,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(32)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.info_outline_rounded, color: AppColors.pastelBlueDeep, size: 32),
          const Spacer(),
          Text(title, style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w900, color: AppColors.ink)),
          const SizedBox(height: 8),
          Text(detail, maxLines: 3, overflow: TextOverflow.ellipsis, style: const TextStyle(color: AppColors.muted)),
        ],
      ),
    );
  }
}

String _formatClock(DateTime? value) {
  if (value == null) return '--:--';
  return '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';
}

String _formatCountdown(Duration remaining) {
  final seconds = remaining.inSeconds;
  if (seconds <= 0) return '通過';
  final minutes = seconds ~/ 60;
  final rest = seconds % 60;
  if (minutes >= 60) {
    return '${minutes ~/ 60}h${(minutes % 60).toString().padLeft(2, '0')}m';
  }
  return '${minutes.toString().padLeft(2, '0')}:${rest.toString().padLeft(2, '0')}';
}

String _accuracyText(PredictionRecord prediction) {
  final tier = switch (prediction.accuracyTier) {
    'high' => 'H',
    'medium' => 'M',
    'low' => 'L',
    _ => '?',
  };
  final uncertainty = prediction.etaUncertaintySeconds;
  return uncertainty == null ? tier : '±${uncertainty}s';
}

String _delayText(PredictionRecord prediction) {
  final seconds = prediction.delaySeconds ?? prediction.delayMinutes * 60;
  if (seconds == 0) return '準點';
  final prefix = seconds > 0 ? '+' : '-';
  final minutes = (seconds.abs() / 60).round();
  return '$prefix${minutes}m';
}

String _sourceLabel(String source) => switch (source) {
  'liveboards' => 'liveboard',
  'timetables' => 'timetable',
  'train_info' => 'train-info',
  _ => source,
};

extension _FirstOrNull<T> on List<T> {
  T? get firstOrNull => isEmpty ? null : first;
}

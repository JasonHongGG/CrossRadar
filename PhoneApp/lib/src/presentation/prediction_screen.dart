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
        title: Text(widget.crossing.name, maxLines: 1, overflow: TextOverflow.ellipsis),
        actions: [
          IconButton(tooltip: '定位', onPressed: _focusGps, icon: const Icon(Icons.my_location_rounded)),
          IconButton(tooltip: '刷新', onPressed: () => _refreshPrediction(forceRefresh: true), icon: const Icon(Icons.refresh_rounded)),
          IconButton(tooltip: '通知', onPressed: mainPrediction == null ? null : () => _notify(mainPrediction), icon: const Icon(Icons.notifications_active_rounded)),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 18),
        children: [
          _MiniMap(crossing: widget.crossing, userLocation: _userLocation, controller: _mapController),
          const SizedBox(height: 12),
          _CrossingStrip(crossing: widget.crossing),
          const SizedBox(height: 14),
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 260),
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
                      const SizedBox(height: 10),
                      _SnapshotLine(snapshot: _envelope?.dataSnapshot),
                    ],
                  ),
          ),
          const SizedBox(height: 12),
          SizedBox(
            height: 158,
            child: PageView(
              controller: PageController(viewportFraction: 0.92),
              children: [
                _CompactPredictionCard(label: '上一班', prediction: _runtime.previous),
                _CompactPredictionCard(label: '下下一班', prediction: following),
              ],
            ),
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
    return ClipRRect(
      borderRadius: BorderRadius.circular(18),
      child: SizedBox(
        height: 188,
        child: FlutterMap(
          mapController: controller,
          options: MapOptions(initialCenter: LatLng(crossing.geometry.lat, crossing.geometry.lon), initialZoom: 14),
          children: [
            TileLayer(urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', userAgentPackageName: 'crossradar.phone'),
            PolylineLayer(polylines: _connectionLine()),
            MarkerLayer(
              markers: [
                if (crossing.stationA.position != null) _stationMarker(crossing.stationA, AppColors.amber),
                if (crossing.stationB.position != null) _stationMarker(crossing.stationB, AppColors.blue),
                Marker(point: LatLng(crossing.geometry.lat, crossing.geometry.lon), width: 44, height: 44, child: const _CrossingMarker()),
                if (userLocation != null)
                  Marker(
                    point: LatLng(userLocation!.lat, userLocation!.lon),
                    width: 28,
                    height: 28,
                    child: const Icon(Icons.my_location_rounded, color: AppColors.blue),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Marker _stationMarker(StationRef station, Color color) {
    final point = station.position!;
    return Marker(
      point: LatLng(point.lat, point.lon),
      width: 34,
      height: 34,
      child: Tooltip(
        message: station.name ?? '',
        child: Icon(Icons.train_rounded, color: color, size: 28),
      ),
    );
  }

  List<Polyline> _connectionLine() {
    final stationA = crossing.stationA.position;
    final stationB = crossing.stationB.position;
    if (stationA == null || stationB == null) return const [];
    return [
      Polyline(points: [LatLng(stationA.lat, stationA.lon), LatLng(crossing.geometry.lat, crossing.geometry.lon), LatLng(stationB.lat, stationB.lon)], color: AppColors.blue.withValues(alpha: 0.62), strokeWidth: 4),
    ];
  }
}

class _CrossingMarker extends StatelessWidget {
  const _CrossingMarker();

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.rose,
        shape: BoxShape.circle,
        border: Border.all(color: Colors.white, width: 3),
      ),
      child: const Icon(Icons.close_rounded, color: Colors.white),
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
              Text(
                crossing.name,
                style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900, color: AppColors.ink),
              ),
              const SizedBox(height: 3),
              Text(
                crossing.subtitle,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: AppColors.muted),
              ),
            ],
          ),
        ),
        const SizedBox(width: 10),
        DecoratedBox(
          decoration: BoxDecoration(color: AppColors.blueSoft, borderRadius: BorderRadius.circular(999)),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Text(
              crossing.stationPairLabel,
              style: const TextStyle(fontWeight: FontWeight.w800, color: AppColors.ink),
            ),
          ),
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
    final color = isWarning ? AppColors.danger : AppColors.blue;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: isWarning ? AppColors.roseSoft : Colors.white,
        borderRadius: BorderRadius.circular(8),
        boxShadow: [BoxShadow(color: color.withValues(alpha: 0.16), blurRadius: 28, offset: const Offset(0, 14))],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _BasisChip(icon: prediction.dataBasis == 'liveboard' ? Icons.bolt_rounded : Icons.schedule_rounded, text: prediction.dataBasis == 'liveboard' ? '即時' : '班表', color: color),
              const SizedBox(width: 8),
              _BasisChip(icon: Icons.directions_railway_rounded, text: '${prediction.trainNo}次', color: AppColors.ink),
              const Spacer(),
              Text(prediction.direction == 1 ? '南下' : '北上', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _BasisChip(icon: Icons.speed_rounded, text: _accuracyText(prediction), color: AppColors.mint),
              _BasisChip(icon: Icons.more_time_rounded, text: _delayText(prediction), color: prediction.delaySeconds == null || prediction.delaySeconds == 0 ? AppColors.muted : AppColors.amber),
              if (prediction.calibrationOffsetSeconds != 0) _BasisChip(icon: Icons.tune_rounded, text: '${prediction.calibrationOffsetSeconds > 0 ? '+' : ''}${prediction.calibrationOffsetSeconds}s', color: AppColors.blue),
            ],
          ),
          const SizedBox(height: 18),
          Text(
            _formatCountdown(remaining),
            style: TextStyle(fontSize: 48, height: 0.95, fontWeight: FontWeight.w900, color: color),
          ),
          const SizedBox(height: 14),
          LinearProgressIndicator(minHeight: 6, borderRadius: BorderRadius.circular(999), value: _progress(remaining, prediction.warningWindowMinutes), backgroundColor: Colors.white, color: color),
          const SizedBox(height: 18),
          Row(
            children: [
              Expanded(
                child: _StopBlock(name: prediction.previousStopStationName ?? prediction.upstreamStationName, time: prediction.previousStopDeparture),
              ),
              const Icon(Icons.arrow_forward_rounded, color: AppColors.muted),
              Expanded(
                child: _StopBlock(name: prediction.nextStopStationName ?? prediction.downstreamStationName, time: prediction.nextStopArrival, alignEnd: true),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: Text(
                  '${prediction.originStationName ?? ''} → ${prediction.destinationStationName ?? ''}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              Text(_formatClock(prediction.eta), style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 20)),
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

class _SnapshotLine extends StatelessWidget {
  const _SnapshotLine({required this.snapshot});

  final PredictionDataSnapshot? snapshot;

  @override
  Widget build(BuildContext context) {
    final snapshot = this.snapshot;
    if (snapshot == null) return const SizedBox.shrink();
    final source = snapshot.sources.map((item) => '${_sourceLabel(item.source)} ${item.recordCount}${item.isStale ? ' stale' : ''}').join(' · ');
    return DecoratedBox(
      decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.78), borderRadius: BorderRadius.circular(8)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        child: Row(
          children: [
            Icon(snapshot.hasStaleSource ? Icons.cloud_off_rounded : Icons.cloud_done_rounded, size: 17, color: snapshot.hasStaleSource ? AppColors.amber : AppColors.blue),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                source.isEmpty ? '快照 ${snapshot.liveboardCount}/${snapshot.timetableCount}/${snapshot.trainInfoCount}' : source,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12, color: AppColors.muted, fontWeight: FontWeight.w700),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CompactPredictionCard extends StatelessWidget {
  const _CompactPredictionCard({required this.label, required this.prediction});

  final String label;
  final PredictionRecord? prediction;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(right: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: prediction == null
            ? Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: const TextStyle(fontWeight: FontWeight.w900)),
                  const Spacer(),
                  const Icon(Icons.hourglass_empty_rounded, color: AppColors.muted),
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(label, style: const TextStyle(fontWeight: FontWeight.w900)),
                      const Spacer(),
                      Text('${prediction!.trainNo}次', style: const TextStyle(fontWeight: FontWeight.w800)),
                    ],
                  ),
                  const Spacer(),
                  Text('${prediction!.previousStopStationName ?? prediction!.upstreamStationName} → ${prediction!.nextStopStationName ?? prediction!.downstreamStationName}', maxLines: 1, overflow: TextOverflow.ellipsis),
                  const SizedBox(height: 8),
                  Text(
                    _formatClock(prediction!.eta),
                    style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w900, color: AppColors.blue),
                  ),
                ],
              ),
      ),
    );
  }
}

class _BasisChip extends StatelessWidget {
  const _BasisChip({required this.icon, required this.text, required this.color});

  final IconData icon;
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(999)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        child: Row(
          children: [
            Icon(icon, size: 15, color: color),
            const SizedBox(width: 5),
            Text(
              text,
              style: TextStyle(fontWeight: FontWeight.w800, color: color),
            ),
          ],
        ),
      ),
    );
  }
}

class _StopBlock extends StatelessWidget {
  const _StopBlock({required this.name, required this.time, this.alignEnd = false});

  final String name;
  final DateTime? time;
  final bool alignEnd;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: alignEnd ? CrossAxisAlignment.end : CrossAxisAlignment.start,
      children: [
        Text(
          name,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontWeight: FontWeight.w900),
        ),
        const SizedBox(height: 5),
        Text(
          _formatClock(time),
          style: const TextStyle(color: AppColors.muted, fontWeight: FontWeight.w700),
        ),
      ],
    );
  }
}

class _PredictionSkeleton extends StatelessWidget {
  const _PredictionSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 286,
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(8)),
      child: const Center(child: CircularProgressIndicator()),
    );
  }
}

class _UnavailablePanel extends StatelessWidget {
  const _UnavailablePanel({super.key, required this.title, required this.detail});

  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 220,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(8)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.info_outline_rounded, color: AppColors.blue),
          const Spacer(),
          Text(title, style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w900)),
          const SizedBox(height: 6),
          Text(
            detail,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: AppColors.muted),
          ),
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
  if (seconds <= 0) return '已通過';
  final minutes = seconds ~/ 60;
  final rest = seconds % 60;
  if (minutes >= 60) {
    return '${minutes ~/ 60}時${(minutes % 60).toString().padLeft(2, '0')}分';
  }
  return '${minutes.toString().padLeft(2, '0')}:${rest.toString().padLeft(2, '0')}';
}

String _accuracyText(PredictionRecord prediction) {
  final tier = switch (prediction.accuracyTier) {
    'high' => '高信度',
    'medium' => '中信度',
    'low' => '低信度',
    _ => '信度',
  };
  final uncertainty = prediction.etaUncertaintySeconds;
  return uncertainty == null ? tier : '$tier ±${uncertainty}s';
}

String _delayText(PredictionRecord prediction) {
  final seconds = prediction.delaySeconds ?? prediction.delayMinutes * 60;
  if (seconds == 0) return '準點';
  final label = seconds > 0 ? '延誤' : '提早';
  final minutes = (seconds.abs() / 60).round();
  return '$label $minutes分';
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

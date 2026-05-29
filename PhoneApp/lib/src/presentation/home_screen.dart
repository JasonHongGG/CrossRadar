import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../data/mobile_bundle_repository.dart';
import '../domain/models.dart';
import '../domain/search_service.dart';
import '../services/location_service.dart';
import '../theme/app_theme.dart';
import 'prediction_screen.dart';

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  final _searchController = TextEditingController();
  final _mapController = MapController();
  final _searchService = SearchService();
  final _locationService = LocationService();
  var _mode = 0;
  GeoPoint? _userLocation;
  Crossing? _selectedCrossing;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bundle = ref.watch(mobileBundleProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('CrossRadar', style: TextStyle(fontWeight: FontWeight.w800)),
        actions: [IconButton(tooltip: '授權', onPressed: _showAbout, icon: const Icon(Icons.info_outline_rounded))],
      ),
      body: bundle.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => _ErrorState(message: error.toString()),
        data: _buildLoaded,
      ),
    );
  }

  Widget _buildLoaded(MobileBundle bundle) {
    final groups = _searchService.search(bundle.crossings, _searchController.text);
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 2, 16, 12),
          child: Column(
            children: [
              TextField(
                controller: _searchController,
                onChanged: (_) => setState(() {}),
                decoration: const InputDecoration(prefixIcon: Icon(Icons.search_rounded), hintText: '台南、善化、大同區'),
              ),
              const SizedBox(height: 10),
              SegmentedButton<int>(
                segments: const [
                  ButtonSegment(value: 0, icon: Icon(Icons.map_rounded), label: Text('地圖')),
                  ButtonSegment(value: 1, icon: Icon(Icons.manage_search_rounded), label: Text('搜尋')),
                ],
                selected: {_mode},
                onSelectionChanged: (value) => setState(() => _mode = value.first),
              ),
            ],
          ),
        ),
        Expanded(
          child: _mode == 0 ? _MapPicker(bundle: bundle, selectedCrossing: _selectedCrossing, mapController: _mapController, userLocation: _userLocation, onGps: _focusGps, onPick: _openPrediction) : _SearchResults(bundle: bundle, groups: groups, onPick: _openPrediction),
        ),
      ],
    );
  }

  Future<void> _focusGps() async {
    final location = await _locationService.currentPosition();
    if (!mounted || location == null) return;
    setState(() => _userLocation = location);
    _mapController.move(LatLng(location.lat, location.lon), 14);
  }

  void _openPrediction(Crossing crossing, MobileBundle bundle) {
    setState(() => _selectedCrossing = crossing);
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => PredictionScreen(crossing: crossing, bundle: bundle),
      ),
    );
  }

  void _showAbout() {
    showAboutDialog(context: context, applicationName: 'CrossRadar', applicationVersion: '1.0.0', children: const [Text('Map tiles and rail-derived crossing assets contain OpenStreetMap data. OpenStreetMap contributors, ODbL.')]);
  }
}

class _MapPicker extends StatelessWidget {
  const _MapPicker({required this.bundle, required this.selectedCrossing, required this.mapController, required this.userLocation, required this.onGps, required this.onPick});

  final MobileBundle bundle;
  final Crossing? selectedCrossing;
  final MapController mapController;
  final GeoPoint? userLocation;
  final VoidCallback onGps;
  final void Function(Crossing crossing, MobileBundle bundle) onPick;

  @override
  Widget build(BuildContext context) {
    final center = bundle.crossings.firstWhere((crossing) => crossing.county?.contains('臺南') ?? false, orElse: () => bundle.crossings.first).geometry;
    return Stack(
      children: [
        FlutterMap(
          mapController: mapController,
          options: MapOptions(initialCenter: LatLng(center.lat, center.lon), initialZoom: 11),
          children: [
            TileLayer(urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', userAgentPackageName: 'crossradar.phone'),
            if (selectedCrossing != null) PolylineLayer(polylines: _selectedPolylines()),
            MarkerLayer(markers: _stationMarkers(bundle.stations)),
            if (selectedCrossing != null) MarkerLayer(markers: _selectedStationMarkers()),
            MarkerLayer(markers: _crossingMarkers(context)),
            if (userLocation != null)
              MarkerLayer(
                markers: [Marker(point: LatLng(userLocation!.lat, userLocation!.lon), width: 34, height: 34, child: const _PulseDot())],
              ),
          ],
        ),
        Positioned(
          right: 16,
          bottom: 18,
          child: FloatingActionButton.small(heroTag: 'home_gps', onPressed: onGps, child: const Icon(Icons.my_location_rounded)),
        ),
        Positioned(
          left: 16,
          right: 16,
          top: 10,
          child: _MetricStrip(crossings: bundle.crossings.length, ratios: (bundle.metadata['runtime_ratio_count'] as num?)?.toInt() ?? 0),
        ),
      ],
    );
  }

  List<Marker> _crossingMarkers(BuildContext context) {
    return bundle.crossings
        .map(
          (crossing) => Marker(
            point: LatLng(crossing.geometry.lat, crossing.geometry.lon),
            width: 38,
            height: 38,
            child: Tooltip(
              message: crossing.name,
              child: GestureDetector(
                onTap: () => onPick(crossing, bundle),
                child: Container(
                  decoration: BoxDecoration(
                    color: selectedCrossing?.id == crossing.id ? AppColors.danger : AppColors.rose.withValues(alpha: 0.92),
                    shape: BoxShape.circle,
                    border: Border.all(color: Colors.white, width: 3),
                    boxShadow: [BoxShadow(color: AppColors.rose.withValues(alpha: 0.25), blurRadius: 14)],
                  ),
                  child: const Icon(Icons.close_rounded, size: 17, color: Colors.white),
                ),
              ),
            ),
          ),
        )
        .toList(growable: false);
  }

  List<Marker> _stationMarkers(List<Station> stations) {
    return stations
        .map(
          (station) => Marker(
            point: LatLng(station.position.lat, station.position.lon),
            width: 30,
            height: 30,
            child: Tooltip(
              message: station.name,
              child: Container(
                decoration: BoxDecoration(
                  color: AppColors.blue.withValues(alpha: 0.86),
                  shape: BoxShape.circle,
                  border: Border.all(color: Colors.white, width: 2),
                ),
                child: const Icon(Icons.train_rounded, size: 14, color: Colors.white),
              ),
            ),
          ),
        )
        .toList(growable: false);
  }

  List<Polyline> _selectedPolylines() {
    final crossing = selectedCrossing;
    final stationA = crossing?.stationA.position;
    final stationB = crossing?.stationB.position;
    if (crossing == null || stationA == null || stationB == null) {
      return const [];
    }
    return [
      Polyline(points: [LatLng(stationA.lat, stationA.lon), LatLng(crossing.geometry.lat, crossing.geometry.lon), LatLng(stationB.lat, stationB.lon)], color: AppColors.blue.withValues(alpha: 0.55), strokeWidth: 3),
    ];
  }

  List<Marker> _selectedStationMarkers() {
    final crossing = selectedCrossing;
    if (crossing == null) return const [];
    return [if (crossing.stationA.position != null) _stationRefMarker(crossing.stationA, AppColors.amber), if (crossing.stationB.position != null) _stationRefMarker(crossing.stationB, AppColors.blue)];
  }

  Marker _stationRefMarker(StationRef station, Color color) {
    final position = station.position!;
    return Marker(
      point: LatLng(position.lat, position.lon),
      width: 42,
      height: 42,
      child: Tooltip(
        message: station.ukPrimary == null ? station.name ?? '' : '${station.name} · ${station.ukPrimary}',
        child: Container(
          decoration: BoxDecoration(
            color: color,
            shape: BoxShape.circle,
            border: Border.all(color: Colors.white, width: 3),
          ),
          child: const Icon(Icons.train_rounded, size: 18, color: Colors.white),
        ),
      ),
    );
  }
}

class _SearchResults extends StatelessWidget {
  const _SearchResults({required this.bundle, required this.groups, required this.onPick});

  final MobileBundle bundle;
  final List<SearchGroup> groups;
  final void Function(Crossing crossing, MobileBundle bundle) onPick;

  @override
  Widget build(BuildContext context) {
    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 20),
      itemCount: groups.length,
      itemBuilder: (context, index) {
        final group = groups[index];
        return Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(left: 4, bottom: 8),
                child: Text(
                  group.label,
                  style: const TextStyle(fontWeight: FontWeight.w800, color: AppColors.muted),
                ),
              ),
              ...group.crossings
                  .take(80)
                  .map(
                    (crossing) => Card(
                      child: ListTile(
                        leading: const Icon(Icons.close_rounded, color: AppColors.rose),
                        title: Text(crossing.name, maxLines: 1, overflow: TextOverflow.ellipsis),
                        subtitle: Text(crossing.subtitle, maxLines: 1, overflow: TextOverflow.ellipsis),
                        trailing: Text(crossing.stationPairLabel, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
                        onTap: () => onPick(crossing, bundle),
                      ),
                    ),
                  ),
            ],
          ),
        );
      },
    );
  }
}

class _MetricStrip extends StatelessWidget {
  const _MetricStrip({required this.crossings, required this.ratios});

  final int crossings;
  final int ratios;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        _MetricPill(icon: Icons.close_rounded, value: crossings.toString()),
        const SizedBox(width: 8),
        _MetricPill(icon: Icons.alt_route_rounded, value: ratios.toString()),
      ],
    );
  }
}

class _MetricPill extends StatelessWidget {
  const _MetricPill({required this.icon, required this.value});

  final IconData icon;
  final String value;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.90), borderRadius: BorderRadius.circular(999)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 16, color: AppColors.blue),
            const SizedBox(width: 6),
            Text(value, style: const TextStyle(fontWeight: FontWeight.w800)),
          ],
        ),
      ),
    );
  }
}

class _PulseDot extends StatelessWidget {
  const _PulseDot();

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0.55, end: 1.0),
      duration: const Duration(milliseconds: 900),
      builder: (context, value, _) => Container(
        decoration: BoxDecoration(
          color: AppColors.blue.withValues(alpha: 0.18 + value * 0.20),
          shape: BoxShape.circle,
        ),
        child: Center(
          child: Container(
            width: 13,
            height: 13,
            decoration: const BoxDecoration(color: AppColors.blue, shape: BoxShape.circle),
          ),
        ),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(message, textAlign: TextAlign.center),
      ),
    );
  }
}

import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../data/mobile_bundle_repository.dart';
import '../domain/models.dart';
import '../domain/search_service.dart';
import '../services/location_service.dart';
import '../services/search_history_service.dart';
import '../theme/app_theme.dart';
import 'prediction_screen.dart';
import 'settings_screen.dart';

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
  final _historyService = const SearchHistoryService();
  var _mode = 0;
  GeoPoint? _userLocation;
  Crossing? _selectedCrossing;
  List<SearchHistoryEntry> _history = const [];

  @override
  void initState() {
    super.initState();
    _searchController.addListener(_handleSearchChanged);
    _loadHistory();
  }

  @override
  void dispose() {
    _searchController.removeListener(_handleSearchChanged);
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bundle = ref.watch(mobileBundleProvider);
    return Scaffold(
      body: bundle.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => _ErrorState(message: error.toString()),
        data: _buildLoaded,
      ),
    );
  }

  Widget _buildLoaded(MobileBundle bundle) {
    final groups = _searchService.search(bundle.crossings, _searchController.text);
    final history = _history.where((entry) => bundle.crossingById.containsKey(entry.crossingId)).toList(growable: false);
    return DecoratedBox(
      decoration: const BoxDecoration(gradient: AppGradients.softBrand),
      child: SafeArea(
        child: Column(
          children: [
            _HomeCommandBar(controller: _searchController, mode: _mode, onModeChanged: (mode) => setState(() => _mode = mode), onSearchFocus: () => setState(() => _mode = 1), onSettings: _openSettings, onAbout: _showAbout),
            Expanded(
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 260),
                switchInCurve: Curves.easeOutCubic,
                switchOutCurve: Curves.easeInCubic,
                child: _mode == 0 ? _MapPicker(key: const ValueKey('map'), bundle: bundle, selectedCrossing: _selectedCrossing, mapController: _mapController, userLocation: _userLocation, onGps: _focusGps, onPick: _openPrediction) : _SearchResults(key: const ValueKey('search'), bundle: bundle, groups: groups, history: history, onPick: _openPrediction, onHistoryDelete: _deleteHistory),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _handleSearchChanged() {
    if (_mode != 1) {
      setState(() => _mode = 1);
      return;
    }
    setState(() {});
  }

  Future<void> _loadHistory() async {
    final history = await _historyService.load();
    if (!mounted) return;
    setState(() => _history = history);
  }

  Future<void> _deleteHistory(String crossingId) async {
    final history = await _historyService.remove(crossingId);
    if (!mounted) return;
    setState(() => _history = history);
  }

  Future<void> _focusGps() async {
    final location = await _locationService.currentPosition();
    if (!mounted || location == null) return;
    setState(() => _userLocation = location);
    _mapController.move(LatLng(location.lat, location.lon), 14);
  }

  Future<void> _openPrediction(Crossing crossing, MobileBundle bundle) async {
    final history = await _historyService.save(crossing);
    if (!mounted) return;
    setState(() {
      _selectedCrossing = crossing;
      _history = history;
    });
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => PredictionScreen(crossing: crossing, bundle: bundle),
      ),
    );
  }

  Future<void> _openSettings() async {
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SettingsScreen()));
  }

  void _showAbout() {
    showAboutDialog(context: context, applicationName: 'CrossRadar', applicationVersion: '1.0.0', children: const [Text('Map tiles and rail-derived crossing assets contain OpenStreetMap data. OpenStreetMap contributors, ODbL.')]);
  }
}

class _HomeCommandBar extends StatelessWidget {
  const _HomeCommandBar({required this.controller, required this.mode, required this.onModeChanged, required this.onSearchFocus, required this.onSettings, required this.onAbout});

  final TextEditingController controller;
  final int mode;
  final ValueChanged<int> onModeChanged;
  final VoidCallback onSearchFocus;
  final VoidCallback onSettings;
  final VoidCallback onAbout;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 10),
      child: Container(
        padding: const EdgeInsets.all(6),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.92),
          borderRadius: BorderRadius.circular(8),
          boxShadow: [BoxShadow(color: AppColors.blueDeep.withValues(alpha: 0.10), blurRadius: 24, offset: const Offset(0, 12))],
        ),
        child: Row(
          children: [
            Expanded(
              child: SizedBox(
                height: 46,
                child: TextField(
                  controller: controller,
                  onTap: onSearchFocus,
                  textInputAction: TextInputAction.search,
                  decoration: InputDecoration(
                    hintText: '搜尋平交道',
                    prefixIcon: const Icon(Icons.search_rounded),
                    suffixIcon: controller.text.isEmpty ? null : IconButton(tooltip: '清除', onPressed: controller.clear, icon: const Icon(Icons.close_rounded)),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 6),
            _ModeIconButton(icon: Icons.map_rounded, tooltip: '地圖', selected: mode == 0, onPressed: () => onModeChanged(0)),
            const SizedBox(width: 4),
            _ModeIconButton(icon: Icons.manage_search_rounded, tooltip: '搜尋', selected: mode == 1, onPressed: () => onModeChanged(1)),
            const SizedBox(width: 4),
            IconButton(tooltip: 'TDX', onPressed: onSettings, icon: const Icon(Icons.tune_rounded)),
            const SizedBox(width: 4),
            IconButton(tooltip: '授權', onPressed: onAbout, icon: const Icon(Icons.info_outline_rounded)),
          ],
        ),
      ),
    );
  }
}

class _ModeIconButton extends StatelessWidget {
  const _ModeIconButton({required this.icon, required this.tooltip, required this.selected, required this.onPressed});

  final IconData icon;
  final String tooltip;
  final bool selected;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      curve: Curves.easeOutCubic,
      decoration: BoxDecoration(gradient: selected ? AppGradients.brand : null, color: selected ? null : AppColors.panelTint, borderRadius: BorderRadius.circular(8)),
      child: IconButton(
        tooltip: tooltip,
        onPressed: onPressed,
        style: IconButton.styleFrom(backgroundColor: Colors.transparent, foregroundColor: selected ? Colors.white : AppColors.blueDeep),
        icon: Icon(icon),
      ),
    );
  }
}

class _MapPicker extends StatelessWidget {
  const _MapPicker({super.key, required this.bundle, required this.selectedCrossing, required this.mapController, required this.userLocation, required this.onGps, required this.onPick});

  final MobileBundle bundle;
  final Crossing? selectedCrossing;
  final MapController mapController;
  final GeoPoint? userLocation;
  final VoidCallback onGps;
  final Future<void> Function(Crossing crossing, MobileBundle bundle) onPick;

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
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 180),
                  decoration: BoxDecoration(
                    gradient: selectedCrossing?.id == crossing.id ? AppGradients.brand : null,
                    color: selectedCrossing?.id == crossing.id ? null : AppColors.rose.withValues(alpha: 0.92),
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
                  color: AppColors.blue.withValues(alpha: 0.82),
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
  const _SearchResults({super.key, required this.bundle, required this.groups, required this.history, required this.onPick, required this.onHistoryDelete});

  final MobileBundle bundle;
  final List<SearchGroup> groups;
  final List<SearchHistoryEntry> history;
  final Future<void> Function(Crossing crossing, MobileBundle bundle) onPick;
  final ValueChanged<String> onHistoryDelete;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 2, 12, 20),
      children: [
        if (history.isNotEmpty) ...[_HistoryRail(history: history, crossingById: bundle.crossingById, bundle: bundle, onPick: onPick, onDelete: onHistoryDelete), const SizedBox(height: 8)],
        if (groups.isEmpty) const _EmptySearchState() else for (var groupIndex = 0; groupIndex < groups.length; groupIndex++) _SearchGroupSection(group: groups[groupIndex], bundle: bundle, groupIndex: groupIndex, onPick: onPick),
      ],
    );
  }
}

class _HistoryRail extends StatelessWidget {
  const _HistoryRail({required this.history, required this.crossingById, required this.bundle, required this.onPick, required this.onDelete});

  final List<SearchHistoryEntry> history;
  final Map<String, Crossing> crossingById;
  final MobileBundle bundle;
  final Future<void> Function(Crossing crossing, MobileBundle bundle) onPick;
  final ValueChanged<String> onDelete;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 88,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: history.length,
        separatorBuilder: (context, index) => const SizedBox(width: 8),
        itemBuilder: (context, index) {
          final entry = history[index];
          final crossing = crossingById[entry.crossingId];
          return _HistoryChip(entry: entry, enabled: crossing != null, onTap: crossing == null ? null : () => onPick(crossing, bundle), onDelete: () => onDelete(entry.crossingId));
        },
      ),
    );
  }
}

class _HistoryChip extends StatelessWidget {
  const _HistoryChip({required this.entry, required this.enabled, required this.onTap, required this.onDelete});

  final SearchHistoryEntry entry;
  final bool enabled;
  final VoidCallback? onTap;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return AnimatedScale(
      duration: const Duration(milliseconds: 160),
      scale: enabled ? 1 : 0.96,
      child: SizedBox(
        width: 178,
        child: Material(
          color: Colors.white.withValues(alpha: 0.94),
          borderRadius: BorderRadius.circular(8),
          child: InkWell(
            borderRadius: BorderRadius.circular(8),
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 28,
                        height: 28,
                        decoration: BoxDecoration(gradient: AppGradients.brand, borderRadius: BorderRadius.circular(8)),
                        child: const Icon(Icons.close_rounded, color: Colors.white, size: 17),
                      ),
                      const Spacer(),
                      InkResponse(
                        radius: 18,
                        onTap: onDelete,
                        child: const Icon(Icons.close_rounded, size: 17, color: AppColors.muted),
                      ),
                    ],
                  ),
                  const Spacer(),
                  Text(
                    entry.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w900, color: AppColors.ink),
                  ),
                  if (entry.detail != null)
                    Text(
                      entry.detail!,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 12, color: AppColors.muted, fontWeight: FontWeight.w700),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _SearchGroupSection extends StatelessWidget {
  const _SearchGroupSection({required this.group, required this.bundle, required this.groupIndex, required this.onPick});

  final SearchGroup group;
  final MobileBundle bundle;
  final int groupIndex;
  final Future<void> Function(Crossing crossing, MobileBundle bundle) onPick;

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: Duration(milliseconds: 220 + math.min(groupIndex, 4) * 55),
      curve: Curves.easeOutCubic,
      builder: (context, value, child) => Opacity(
        opacity: value,
        child: Transform.translate(offset: Offset(0, 12 * (1 - value)), child: child),
      ),
      child: Padding(
        padding: const EdgeInsets.only(bottom: 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(left: 4, bottom: 8),
              child: Text(
                group.label,
                style: const TextStyle(fontWeight: FontWeight.w900, color: AppColors.blueDeep),
              ),
            ),
            ...group.crossings.take(80).map((crossing) => _SearchResultTile(crossing: crossing, onTap: () => onPick(crossing, bundle))),
          ],
        ),
      ),
    );
  }
}

class _SearchResultTile extends StatelessWidget {
  const _SearchResultTile({required this.crossing, required this.onTap});

  final Crossing crossing;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: Colors.white.withValues(alpha: 0.94),
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
            child: Row(
              children: [
                Container(
                  width: 38,
                  height: 38,
                  decoration: BoxDecoration(color: AppColors.roseSoft, borderRadius: BorderRadius.circular(8)),
                  child: const Icon(Icons.close_rounded, color: AppColors.roseDeep, size: 21),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        crossing.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w900, color: AppColors.ink),
                      ),
                      if (crossing.subtitle.isNotEmpty)
                        Text(
                          crossing.subtitle,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 12, color: AppColors.muted, fontWeight: FontWeight.w700),
                        ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                const Icon(Icons.chevron_right_rounded, color: AppColors.blue),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _EmptySearchState extends StatelessWidget {
  const _EmptySearchState();

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 220,
      child: Center(
        child: Container(
          width: 84,
          height: 84,
          decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.86), borderRadius: BorderRadius.circular(8)),
          child: const Icon(Icons.manage_search_rounded, size: 38, color: AppColors.blue),
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
      tween: Tween(begin: 0.55, end: 1),
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

import 'dart:math' as math;
import 'dart:ui';

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
    return Stack(
      children: [
        AnimatedSwitcher(
          duration: const Duration(milliseconds: 360),
          switchInCurve: Curves.easeOutCubic,
          switchOutCurve: Curves.easeInCubic,
          child: _mode == 0
              ? _MapPicker(key: const ValueKey('map'), bundle: bundle, selectedCrossing: _selectedCrossing, mapController: _mapController, userLocation: _userLocation, onGps: _focusGps, onPick: _openPrediction)
              : _SearchResults(key: const ValueKey('search'), bundle: bundle, groups: groups, history: history, onPick: _openPrediction, onHistoryDelete: _deleteHistory),
        ),
        Positioned(
          top: 0,
          left: 0,
          right: 0,
          child: SafeArea(
            bottom: false,
            child: _HomeCommandBar(controller: _searchController, mode: _mode, onModeChanged: (mode) => setState(() => _mode = mode), onSearchFocus: () => setState(() => _mode = 1), onSettings: _openSettings),
          ),
        ),
      ],
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
      MaterialPageRoute(builder: (_) => PredictionScreen(crossing: crossing, bundle: bundle)),
    );
  }

  Future<void> _openSettings() async {
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SettingsScreen()));
  }
}

class _HomeCommandBar extends StatelessWidget {
  const _HomeCommandBar({required this.controller, required this.mode, required this.onModeChanged, required this.onSearchFocus, required this.onSettings});

  final TextEditingController controller;
  final int mode;
  final ValueChanged<int> onModeChanged;
  final VoidCallback onSearchFocus;
  final VoidCallback onSettings;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(24),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 12, sigmaY: 12),
          child: Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: AppColors.glassBackground,
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: Colors.white.withValues(alpha: 0.5), width: 1),
              boxShadow: [BoxShadow(color: AppColors.pastelBlueDeep.withValues(alpha: 0.08), blurRadius: 24, offset: const Offset(0, 12))],
            ),
            child: Row(
              children: [
                Expanded(
                  child: SizedBox(
                    height: 48,
                    child: TextField(
                      controller: controller,
                      onTap: onSearchFocus,
                      textInputAction: TextInputAction.search,
                      decoration: InputDecoration(
                        hintText: '搜尋平交道...',
                        hintStyle: const TextStyle(color: AppColors.muted),
                        fillColor: Colors.white.withValues(alpha: 0.6),
                        prefixIcon: const Icon(Icons.search_rounded, color: AppColors.pastelBlueDeep),
                        suffixIcon: controller.text.isEmpty ? null : IconButton(tooltip: '清除', onPressed: controller.clear, icon: const Icon(Icons.close_rounded, color: AppColors.muted)),
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  height: 48,
                  padding: const EdgeInsets.all(4),
                  decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.6), borderRadius: BorderRadius.circular(24)),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _ModeIconButton(icon: Icons.map_rounded, selected: mode == 0, onPressed: () => onModeChanged(0)),
                      _ModeIconButton(icon: Icons.format_list_bulleted_rounded, selected: mode == 1, onPressed: () => onModeChanged(1)),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  height: 48,
                  width: 48,
                  decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.6), shape: BoxShape.circle),
                  child: IconButton(tooltip: '設定', onPressed: onSettings, icon: const Icon(Icons.tune_rounded, color: AppColors.ink)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ModeIconButton extends StatelessWidget {
  const _ModeIconButton({required this.icon, required this.selected, required this.onPressed});

  final IconData icon;
  final bool selected;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 250),
      curve: Curves.easeOutCubic,
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: selected ? AppColors.pastelBlueDeep : Colors.transparent,
        borderRadius: BorderRadius.circular(20),
        boxShadow: selected ? [BoxShadow(color: AppColors.pastelBlueDeep.withValues(alpha: 0.3), blurRadius: 8, offset: const Offset(0, 4))] : [],
      ),
      child: IconButton(
        padding: EdgeInsets.zero,
        onPressed: onPressed,
        style: IconButton.styleFrom(backgroundColor: Colors.transparent, foregroundColor: selected ? Colors.white : AppColors.muted),
        icon: Icon(icon, size: 20),
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
          options: MapOptions(initialCenter: LatLng(center.lat, center.lon), initialZoom: 12),
          children: [
            TileLayer(urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', userAgentPackageName: 'crossradar.phone'),
            if (selectedCrossing != null) PolylineLayer(polylines: _selectedPolylines()),
            MarkerLayer(markers: _stationMarkers(bundle.stations)),
            if (selectedCrossing != null) MarkerLayer(markers: _selectedStationMarkers()),
            MarkerLayer(markers: _crossingMarkers(context)),
            if (userLocation != null) MarkerLayer(markers: [Marker(point: LatLng(userLocation!.lat, userLocation!.lon), width: 44, height: 44, child: const _PulseDot())]),
          ],
        ),
        Positioned(
          right: 20,
          bottom: 24,
          child: FloatingActionButton(
            heroTag: 'home_gps',
            onPressed: onGps,
            backgroundColor: Colors.white,
            foregroundColor: AppColors.pastelBlueDeep,
            elevation: 4,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
            child: const Icon(Icons.my_location_rounded),
          ),
        ),
      ],
    );
  }

  List<Marker> _crossingMarkers(BuildContext context) {
    return bundle.crossings.map((crossing) {
      final isSelected = selectedCrossing?.id == crossing.id;
      return Marker(
        point: LatLng(crossing.geometry.lat, crossing.geometry.lon),
        width: isSelected ? 48 : 36,
        height: isSelected ? 48 : 36,
        child: GestureDetector(
          onTap: () => onPick(crossing, bundle),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 300),
            curve: Curves.easeOutBack,
            decoration: BoxDecoration(
              color: isSelected ? AppColors.pastelPinkDeep : Colors.white,
              shape: BoxShape.circle,
              border: Border.all(color: isSelected ? Colors.white : AppColors.pastelPinkDeep, width: isSelected ? 4 : 2),
              boxShadow: [BoxShadow(color: AppColors.pastelPinkDeep.withValues(alpha: 0.3), blurRadius: isSelected ? 12 : 6, offset: const Offset(0, 4))],
            ),
            child: Icon(Icons.railway_alert_rounded, size: isSelected ? 22 : 18, color: isSelected ? Colors.white : AppColors.pastelPinkDeep),
          ),
        ),
      );
    }).toList(growable: false);
  }

  List<Marker> _stationMarkers(List<Station> stations) {
    return stations.map((station) => Marker(
      point: LatLng(station.position.lat, station.position.lon),
      width: 28,
      height: 28,
      child: Container(
        decoration: BoxDecoration(color: AppColors.pastelBlueSoft, shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 2), boxShadow: [BoxShadow(color: AppColors.pastelBlueDeep.withValues(alpha: 0.2), blurRadius: 4)]),
        child: const Icon(Icons.train_rounded, size: 14, color: AppColors.pastelBlueDeep),
      ),
    )).toList(growable: false);
  }

  List<Polyline> _selectedPolylines() {
    final crossing = selectedCrossing;
    final stationA = crossing?.stationA.position;
    final stationB = crossing?.stationB.position;
    if (crossing == null || stationA == null || stationB == null) return const [];
    return [
      Polyline(points: [LatLng(stationA.lat, stationA.lon), LatLng(crossing.geometry.lat, crossing.geometry.lon), LatLng(stationB.lat, stationB.lon)], color: AppColors.pastelBlueDeep.withValues(alpha: 0.8), strokeWidth: 4),
    ];
  }

  List<Marker> _selectedStationMarkers() {
    final crossing = selectedCrossing;
    if (crossing == null) return const [];
    return [
      if (crossing.stationA.position != null) _stationRefMarker(crossing.stationA, AppColors.pastelBlueDeep),
      if (crossing.stationB.position != null) _stationRefMarker(crossing.stationB, AppColors.pastelBlueDeep),
    ];
  }

  Marker _stationRefMarker(StationRef station, Color color) {
    final position = station.position!;
    return Marker(
      point: LatLng(position.lat, position.lon),
      width: 44,
      height: 44,
      child: Container(
        decoration: BoxDecoration(color: color, shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 3), boxShadow: [BoxShadow(color: color.withValues(alpha: 0.4), blurRadius: 8, offset: const Offset(0, 4))]),
        child: const Icon(Icons.train_rounded, size: 20, color: Colors.white),
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
    return DecoratedBox(
      decoration: const BoxDecoration(color: AppColors.surface),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 120, 16, 32),
        children: [
          if (history.isNotEmpty) ...[_HistoryRail(history: history, crossingById: bundle.crossingById, bundle: bundle, onPick: onPick, onDelete: onHistoryDelete), const SizedBox(height: 24)],
          if (groups.isEmpty) const _EmptySearchState() else for (var groupIndex = 0; groupIndex < groups.length; groupIndex++) _SearchGroupSection(group: groups[groupIndex], bundle: bundle, groupIndex: groupIndex, onPick: onPick),
        ],
      ),
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
      height: 100,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: history.length,
        separatorBuilder: (context, index) => const SizedBox(width: 12),
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
      duration: const Duration(milliseconds: 200),
      scale: enabled ? 1 : 0.95,
      child: Container(
        width: 160,
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20), boxShadow: [BoxShadow(color: AppColors.pastelBlueDeep.withValues(alpha: 0.05), blurRadius: 12, offset: const Offset(0, 4))]),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            borderRadius: BorderRadius.circular(20),
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(padding: const EdgeInsets.all(6), decoration: BoxDecoration(color: AppColors.pastelPinkSoft, borderRadius: BorderRadius.circular(10)), child: const Icon(Icons.history_rounded, color: AppColors.pastelPinkDeep, size: 16)),
                      const Spacer(),
                      InkResponse(radius: 20, onTap: onDelete, child: const Icon(Icons.close_rounded, size: 16, color: AppColors.muted)),
                    ],
                  ),
                  const Spacer(),
                  Text(entry.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w800, color: AppColors.ink)),
                  if (entry.detail != null) Text(entry.detail!, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
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
      duration: Duration(milliseconds: 300 + math.min(groupIndex, 4) * 60),
      curve: Curves.easeOutCubic,
      builder: (context, value, child) => Opacity(opacity: value, child: Transform.translate(offset: Offset(0, 20 * (1 - value)), child: child)),
      child: Padding(
        padding: const EdgeInsets.only(bottom: 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(padding: const EdgeInsets.only(left: 4, bottom: 12), child: Text(group.label, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900, color: AppColors.pastelBlueDeep))),
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
      padding: const EdgeInsets.only(bottom: 12),
      child: Container(
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16), boxShadow: [BoxShadow(color: AppColors.pastelBlueDeep.withValues(alpha: 0.04), blurRadius: 8, offset: const Offset(0, 4))]),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            borderRadius: BorderRadius.circular(16),
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
              child: Row(
                children: [
                  Container(
                    width: 44,
                    height: 44,
                    decoration: BoxDecoration(color: AppColors.pastelBlueSoft, borderRadius: BorderRadius.circular(12)),
                    child: const Icon(Icons.railway_alert_rounded, color: AppColors.pastelBlueDeep, size: 24),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(crossing.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: AppColors.ink)),
                        const SizedBox(height: 4),
                        if (crossing.subtitle.isNotEmpty) Text(crossing.subtitle, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13, color: AppColors.muted)),
                      ],
                    ),
                  ),
                  const Icon(Icons.arrow_forward_ios_rounded, color: AppColors.pastelBlueDeep, size: 16),
                ],
              ),
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
      height: 300,
      child: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(width: 96, height: 96, decoration: const BoxDecoration(color: AppColors.pastelBlueSoft, shape: BoxShape.circle), child: const Icon(Icons.search_off_rounded, size: 48, color: AppColors.pastelBlueDeep)),
            const SizedBox(height: 24),
            const Text('找不到結果', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: AppColors.ink)),
            const SizedBox(height: 8),
            const Text('請嘗試其他關鍵字', style: TextStyle(color: AppColors.muted)),
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
      tween: Tween(begin: 0.4, end: 1),
      duration: const Duration(milliseconds: 1200),
      builder: (context, value, _) => Container(
        decoration: BoxDecoration(color: AppColors.pastelBlueDeep.withValues(alpha: 0.15 + value * 0.25), shape: BoxShape.circle),
        child: Center(child: Container(width: 16, height: 16, decoration: BoxDecoration(color: AppColors.pastelBlueDeep, shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 2)))),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Center(child: Padding(padding: const EdgeInsets.all(32), child: Text(message, textAlign: TextAlign.center, style: const TextStyle(color: AppColors.danger, fontWeight: FontWeight.w600))));
  }
}

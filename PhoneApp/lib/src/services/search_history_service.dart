import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../domain/models.dart';

class SearchHistoryEntry {
  const SearchHistoryEntry({required this.crossingId, required this.name, required this.selectedAt, this.detail});

  final String crossingId;
  final String name;
  final String? detail;
  final DateTime selectedAt;

  factory SearchHistoryEntry.fromCrossing(Crossing crossing, DateTime selectedAt) {
    final detailParts = [crossing.county, crossing.subtitle].whereType<String>().where((value) => value.trim().isNotEmpty).toList(growable: false);
    return SearchHistoryEntry(crossingId: crossing.id, name: crossing.name, detail: detailParts.isEmpty ? null : detailParts.join(' · '), selectedAt: selectedAt);
  }

  factory SearchHistoryEntry.fromJson(Map<String, dynamic> json) {
    return SearchHistoryEntry(crossingId: json['crossing_id']?.toString() ?? '', name: json['name']?.toString() ?? '', detail: json['detail']?.toString(), selectedAt: DateTime.tryParse(json['selected_at']?.toString() ?? '') ?? DateTime.fromMillisecondsSinceEpoch(0));
  }

  Map<String, dynamic> toJson() => {'crossing_id': crossingId, 'name': name, if (detail != null) 'detail': detail, 'selected_at': selectedAt.toIso8601String()};
}

abstract class SearchHistoryPreferences {
  Future<String?> getString(String key);
  Future<void> setString(String key, String value);
  Future<void> remove(String key);
}

class SharedPreferencesSearchHistoryPreferences implements SearchHistoryPreferences {
  const SharedPreferencesSearchHistoryPreferences();

  @override
  Future<String?> getString(String key) async {
    return (await SharedPreferences.getInstance()).getString(key);
  }

  @override
  Future<void> setString(String key, String value) async {
    await (await SharedPreferences.getInstance()).setString(key, value);
  }

  @override
  Future<void> remove(String key) async {
    await (await SharedPreferences.getInstance()).remove(key);
  }
}

class SearchHistoryService {
  const SearchHistoryService({SearchHistoryPreferences preferences = const SharedPreferencesSearchHistoryPreferences()}) : _preferences = preferences;

  static const maxEntries = 10;
  static const _key = 'crossradar.search_history.v1';

  final SearchHistoryPreferences _preferences;

  Future<List<SearchHistoryEntry>> load() async {
    final raw = await _preferences.getString(_key);
    if (raw == null || raw.trim().isEmpty) return const [];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) return const [];
      final entries = decoded.whereType<Map>().map((item) => SearchHistoryEntry.fromJson(item.map((key, value) => MapEntry(key.toString(), value)))).where((entry) => entry.crossingId.isNotEmpty && entry.name.isNotEmpty).toList(growable: false);
      entries.sort((first, second) => second.selectedAt.compareTo(first.selectedAt));
      return entries.take(maxEntries).toList(growable: false);
    } catch (_) {
      return const [];
    }
  }

  Future<List<SearchHistoryEntry>> save(Crossing crossing, {DateTime? selectedAt}) async {
    final nextEntry = SearchHistoryEntry.fromCrossing(crossing, selectedAt ?? DateTime.now());
    final entries = [
      nextEntry,
      for (final entry in await load())
        if (entry.crossingId != crossing.id) entry,
    ].take(maxEntries).toList(growable: false);
    await _write(entries);
    return entries;
  }

  Future<List<SearchHistoryEntry>> remove(String crossingId) async {
    final entries = [
      for (final entry in await load())
        if (entry.crossingId != crossingId) entry,
    ];
    await _write(entries);
    return entries;
  }

  Future<void> clear() async {
    await _preferences.remove(_key);
  }

  Future<void> _write(List<SearchHistoryEntry> entries) async {
    await _preferences.setString(_key, jsonEncode(entries.map((entry) => entry.toJson()).toList(growable: false)));
  }
}

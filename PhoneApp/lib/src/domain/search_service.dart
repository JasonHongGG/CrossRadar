import 'models.dart';

class SearchGroup {
  const SearchGroup({required this.label, required this.crossings});

  final String label;
  final List<Crossing> crossings;
}

class SearchService {
  String normalize(String value) {
    return value.trim().replaceAll('臺', '台').replaceAll(RegExp(r'\s+'), '').toLowerCase();
  }

  List<SearchGroup> search(List<Crossing> crossings, String query) {
    final normalized = normalize(query);
    final filtered = normalized.isEmpty
        ? crossings
        : crossings
              .where((crossing) {
                final haystack = normalize([crossing.county, crossing.line, crossing.kmMarker, crossing.roadType, crossing.stationPairText, crossing.stationA.name, crossing.stationB.name, crossing.name].whereType<String>().join(' '));
                return haystack.contains(normalized);
              })
              .toList(growable: false);
    final grouped = <String, List<Crossing>>{};
    for (final crossing in filtered) {
      final key = crossing.county ?? '其他';
      grouped.putIfAbsent(key, () => []).add(crossing);
    }
    final groups = grouped.entries.map((entry) => SearchGroup(label: entry.key, crossings: [...entry.value]..sort((a, b) => b.geometry.lat.compareTo(a.geometry.lat)))).toList(growable: false);
    groups.sort((a, b) => a.label.compareTo(b.label));
    return groups;
  }
}

import 'models.dart';

const _countyOrder = [
  '基隆市', '新北市', '桃園市', '新竹市', '新竹縣', '苗栗縣',
  '台中市', '南投縣', '彰化縣', '雲林縣', '嘉義市', '嘉義縣',
  '台南市', '高雄市', '屏東縣', '宜蘭縣', '花蓮縣', '台東縣',
];

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
      final key = crossing.county == null ? '其他' : crossing.county!.replaceAll('臺', '台');
      grouped.putIfAbsent(key, () => []).add(crossing);
    }
    
    final groups = grouped.entries.map((entry) => SearchGroup(label: entry.key, crossings: [...entry.value]..sort((a, b) => b.geometry.lat.compareTo(a.geometry.lat)))).toList(growable: false);
    
    groups.sort((a, b) {
      final indexA = _countyOrder.indexOf(a.label);
      final indexB = _countyOrder.indexOf(b.label);
      if (indexA != -1 && indexB != -1) return indexA.compareTo(indexB);
      if (indexA != -1) return -1;
      if (indexB != -1) return 1;
      return a.label.compareTo(b.label);
    });
    
    return groups;
  }
}


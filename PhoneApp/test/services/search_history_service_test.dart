import 'package:crossradar_phone/src/domain/models.dart';
import 'package:crossradar_phone/src/services/search_history_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('keeps selected crossings latest-first and caps history at 10', () async {
    final service = SearchHistoryService(preferences: _MemoryHistoryPreferences());
    final baseTime = DateTime(2026, 5, 29, 8);

    for (var index = 0; index < 12; index++) {
      await service.save(_crossing('crossing-$index', '平交道 $index'), selectedAt: baseTime.add(Duration(minutes: index)));
    }

    final history = await service.load();
    expect(history, hasLength(10));
    expect(history.first.crossingId, 'crossing-11');
    expect(history.last.crossingId, 'crossing-2');
  });

  test('deduplicates by crossing id and moves the newest selection to the top', () async {
    final service = SearchHistoryService(preferences: _MemoryHistoryPreferences());

    await service.save(_crossing('demo', '四叉巷'), selectedAt: DateTime(2026, 5, 29, 8));
    await service.save(_crossing('other', '大同'), selectedAt: DateTime(2026, 5, 29, 9));
    await service.save(_crossing('demo', '四叉巷'), selectedAt: DateTime(2026, 5, 29, 10));

    final history = await service.load();
    expect(history.map((entry) => entry.crossingId), ['demo', 'other']);
  });

  test('removes and clears entries', () async {
    final service = SearchHistoryService(preferences: _MemoryHistoryPreferences());
    await service.save(_crossing('first', '第一'));
    await service.save(_crossing('second', '第二'));

    expect(await service.remove('first'), hasLength(1));
    expect((await service.load()).single.crossingId, 'second');

    await service.clear();
    expect(await service.load(), isEmpty);
  });

  test('ignores corrupt stored JSON', () async {
    final preferences = _MemoryHistoryPreferences()..values['crossradar.search_history.v1'] = '{bad json';
    final service = SearchHistoryService(preferences: preferences);

    expect(await service.load(), isEmpty);
  });
}

Crossing _crossing(String id, String name) => Crossing(
  id: id,
  name: name,
  county: '臺南市',
  line: '縱貫線',
  kmMarker: 'K353+375',
  geometry: const GeoPoint(lat: 23, lon: 120),
  stationA: const StationRef(id: 'A', name: '永康', position: GeoPoint(lat: 23.1, lon: 120.1)),
  stationB: const StationRef(id: 'B', name: '臺南', position: GeoPoint(lat: 22.9, lon: 120.2)),
  runtimeRatios: const {},
);

class _MemoryHistoryPreferences implements SearchHistoryPreferences {
  final values = <String, String>{};

  @override
  Future<String?> getString(String key) async => values[key];

  @override
  Future<void> setString(String key, String value) async {
    values[key] = value;
  }

  @override
  Future<void> remove(String key) async {
    values.remove(key);
  }
}

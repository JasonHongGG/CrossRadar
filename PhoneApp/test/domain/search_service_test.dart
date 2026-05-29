import 'package:crossradar_phone/src/domain/models.dart';
import 'package:crossradar_phone/src/domain/search_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('normalizes 台 and 臺 for city and district search', () {
    final service = SearchService();
    final groups = service.search([_crossing()], '台南');

    expect(groups, hasLength(1));
    expect(groups.first.label, '臺南市');
    expect(groups.first.crossings.single.name, '四叉巷');
  });
}

Crossing _crossing() => const Crossing(
  id: 'demo',
  name: '四叉巷',
  county: '臺南市',
  stationPairText: '永康-臺南',
  geometry: GeoPoint(lat: 23.0, lon: 120.0),
  stationA: StationRef(
    id: 'A',
    name: '永康',
    position: GeoPoint(lat: 23.1, lon: 120.1),
  ),
  stationB: StationRef(
    id: 'B',
    name: '臺南',
    position: GeoPoint(lat: 22.9, lon: 120.2),
  ),
  runtimeRatios: {},
);

import 'dart:convert';

import 'package:crossradar_phone/src/app.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('loads the main CrossRadar shell from a mobile bundle asset', (tester) async {
    TestWidgetsFlutterBinding.ensureInitialized();
    tester.binding.defaultBinaryMessenger.setMockMessageHandler('flutter/assets', (message) async {
      final key = const StringCodec().decodeMessage(message);
      if (key != 'assets/data/crossradar_mobile_bundle.json') return null;
      final encoded = utf8.encode(jsonEncode(_bundleFixture));
      return ByteData.view(Uint8List.fromList(encoded).buffer);
    });

    await tester.pumpWidget(const ProviderScope(child: CrossRadarApp()));
    await tester.pumpAndSettle();

    expect(find.text('CrossRadar'), findsOneWidget);
    expect(find.text('地圖'), findsOneWidget);
    expect(find.text('搜尋'), findsOneWidget);
  });
}

final _bundleFixture = {
  'metadata': {'schema_version': 2, 'runtime_ratio_count': 2},
  'crossings': [
    {
      'id': 'demo-crossing',
      'name': '四叉巷',
      'line': '縱貫線北段',
      'county': '臺南市',
      'road_type': '農路',
      'km_marker': 'K353+375',
      'station_pair_text': '永康-台南',
      'geometry': {'lat': 23.0277, 'lon': 120.2371},
      'geolocation_confidence': 'high',
      'segment_ratio': 0.32,
      'ratio_source': 'osm_path',
      'segment_confidence': 'high',
      'station_a': {
        'id': 'A',
        'name': '永康',
        'position': {'lat': 23.03825, 'lon': 120.25347},
      },
      'station_b': {
        'id': 'B',
        'name': '臺南',
        'position': {'lat': 22.99681, 'lon': 120.21295},
      },
      'runtime_ratios': {
        'A|B': {'upstream_station_id': 'A', 'downstream_station_id': 'B', 'ratio': 0.32, 'source': 'osm_path', 'confidence': 'high'},
        'B|A': {'upstream_station_id': 'B', 'downstream_station_id': 'A', 'ratio': 0.68, 'source': 'osm_path', 'confidence': 'high'},
      },
    },
  ],
  'stations': [
    {
      'station_id': 'A',
      'name': '永康',
      'position': {'lat': 23.03825, 'lon': 120.25347},
    },
    {
      'station_id': 'B',
      'name': '臺南',
      'position': {'lat': 22.99681, 'lon': 120.21295},
    },
  ],
  'station_pair_projections': {},
  'calibration': {'rules': []},
};

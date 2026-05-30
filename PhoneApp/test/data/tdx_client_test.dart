import 'dart:convert';

import 'package:crossradar_phone/src/data/credential_store.dart';
import 'package:crossradar_phone/src/data/tdx_client.dart';
import 'package:crossradar_phone/src/domain/railway_clock.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  const credentials = TdxCredentials(clientId: 'id', clientSecret: 'secret');

  test('reuses today timetable file cache only for the Taipei service date', () async {
    final now = DateTime.now().toUtc();
    SharedPreferences.setMockInitialValues({
      'tdx_cache_today_timetables': jsonEncode({
        'cached_at': now.toIso8601String(),
        'service_date': '2026-05-28',
        'data': [_timetableRow('cached')],
      }),
    });
    final transport = _FakeTransport(trainTimetables: [_timetableRow('network')]);
    final client = TdxTraClient(
      dio: transport.dio,
      railwayClock: RailwayClock(utcNow: () => DateTime.utc(2026, 5, 28, 1, 30)),
    );

    final result = await client.getTodayTimetablesSnapshot(credentials);

    expect(result.fetchedFrom, 'file_cache');
    expect(result.items.single.trainNo, 'cached');
    expect(transport.getCount, 0);
  });

  test('rejects stale service-date timetable cache and replaces it after network fetch', () async {
    final now = DateTime.now().toUtc();
    SharedPreferences.setMockInitialValues({
      'tdx_cache_today_timetables': jsonEncode({
        'cached_at': now.toIso8601String(),
        'service_date': '2026-05-27',
        'data': [_timetableRow('stale')],
      }),
    });
    final transport = _FakeTransport(trainTimetables: [_timetableRow('network')]);
    final client = TdxTraClient(
      dio: transport.dio,
      railwayClock: RailwayClock(utcNow: () => DateTime.utc(2026, 5, 28, 1, 30)),
    );

    final result = await client.getTodayTimetablesSnapshot(credentials);
    final preferences = await SharedPreferences.getInstance();
    final persisted = jsonDecode(preferences.getString('tdx_cache_today_timetables')!) as Map<String, dynamic>;

    expect(result.fetchedFrom, 'api');
    expect(result.items.single.trainNo, 'network');
    expect(transport.getCount, 1);
    expect(persisted['service_date'], '2026-05-28');
  });
}

Map<String, Object?> _timetableRow(String trainNo) => {
  'TrainInfo': {'TrainNo': trainNo, 'TrainTypeName': '區間', 'StartingStationID': 'A', 'EndingStationID': 'B'},
  'StopTimes': [
    {
      'StationID': 'A',
      'StationName': {'Zh_tw': '永康'},
      'StopSequence': 1,
      'ArrivalTime': '10:00',
      'DepartureTime': '10:00',
    },
    {
      'StationID': 'B',
      'StationName': {'Zh_tw': '臺南'},
      'StopSequence': 2,
      'ArrivalTime': '10:10',
      'DepartureTime': '10:10',
    },
  ],
};

class _FakeTransport {
  _FakeTransport({required this.trainTimetables}) {
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          if (options.method == 'POST') {
            handler.resolve(Response(requestOptions: options, data: {'access_token': 'token', 'expires_in': 3600}));
            return;
          }
          getCount += 1;
          handler.resolve(Response(requestOptions: options, data: {'TrainTimetables': trainTimetables}));
        },
      ),
    );
  }

  final Dio dio = Dio();
  final List<Map<String, Object?>> trainTimetables;
  var getCount = 0;
}

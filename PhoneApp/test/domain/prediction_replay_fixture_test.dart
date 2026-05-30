import 'dart:convert';
import 'dart:io';

import 'package:crossradar_phone/src/domain/models.dart';
import 'package:crossradar_phone/src/domain/prediction_service.dart';
import 'package:crossradar_phone/src/domain/railway_clock.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('replays the WebApp parity contract fixture through the PhoneApp predictor', () {
    final fixture = jsonDecode(File('test/fixtures/prediction_replay_fixture.json').readAsStringSync()) as Map<String, dynamic>;
    final clock = RailwayClock(utcNow: () => DateTime.utc(2026, 5, 28, 1, 30));
    final service = PredictionService(railwayClock: clock);
    final expected = fixture['expected'] as Map<String, dynamic>;

    final stations = {for (final stationJson in mapList(fixture['stations'])) Station.fromJson(stationJson).id: Station.fromJson(stationJson)};
    final envelope = service.predictForCrossing(
      crossing: Crossing.fromJson(mapValue(fixture['crossing'])),
      timetables: mapList(fixture['timetables']).map(TrainTimetable.fromJson).toList(growable: false),
      liveboards: mapList(fixture['liveboards']).map(TrainLiveBoard.fromJson).toList(growable: false),
      trainInfos: mapList(fixture['train_info']).map(TrainInfo.fromJson).toList(growable: false),
      stationLookupById: stations,
      calibrationRules: const [],
      dataSnapshot: PredictionDataSnapshot.fromJson(mapValue(fixture['data_snapshot'])),
      now: clock.parseTdxUpdateTime(fixture['now'].toString())!,
    );

    expect(envelope.available, expected['available']);
    final prediction = envelope.predictions.single;
    final trace = prediction.trace!;
    final expectedEta = clock.parseTdxUpdateTime(expected['eta'].toString())!;

    expect(prediction.trainNo, expected['train_no']);
    expect(prediction.dataBasis, expected['data_basis']);
    expect(prediction.delaySource, expected['delay_source']);
    expect(prediction.delaySeconds, expected['delay_seconds']);
    expect(prediction.eta.difference(expectedEta).inSeconds, 0);
    expect(prediction.segmentRatio, closeTo((expected['segment_ratio'] as num).toDouble(), 0.000001));
    expect(prediction.timingModel, expected['timing_model']);
    expect(prediction.anchorTimeSource, expected['anchor_time_source']);
    expect(trace.serviceDate, expected['service_date']);
    expect(trace.timeFraction, closeTo((expected['time_fraction'] as num).toDouble(), 0.000001));
    expect(trace.delaySeconds, expected['delay_seconds']);
    expect(trace.eta.difference(expectedEta).inSeconds, 0);
  });
}

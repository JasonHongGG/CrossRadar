import 'package:crossradar_phone/src/domain/models.dart';
import 'package:crossradar_phone/src/domain/prediction_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('reverse direction applies 1 minus segment ratio and preserves crossing order', () {
    final service = PredictionService();
    final now = DateTime(2026, 5, 28, 9, 30);
    final timetable = _timetable(directionReverse: true);

    final north = service.predictForCrossing(crossing: _crossing('north', 0.3), timetables: [timetable], liveboards: const [], trainInfos: const [], stationLookupById: _stations, calibrationRules: const [], now: now);
    final south = service.predictForCrossing(crossing: _crossing('south', 0.7), timetables: [timetable], liveboards: const [], trainInfos: const [], stationLookupById: _stations, calibrationRules: const [], now: now);

    expect(north.predictions.single.segmentRatio, closeTo(0.7, 0.0001));
    expect(south.predictions.single.segmentRatio, closeTo(0.3, 0.0001));
    expect(south.predictions.single.eta.isBefore(north.predictions.single.eta), isTrue);
  });

  test('train-info delay shifts upstream and downstream stop times', () {
    final service = PredictionService();
    final now = DateTime(2026, 5, 28, 9, 30);

    final envelope = service.predictForCrossing(
      crossing: _crossing('demo', 0.5),
      timetables: [_timetable()],
      liveboards: const [],
      trainInfos: const [TrainInfo(trainNo: '3001', delayTime: 4)],
      stationLookupById: _stations,
      calibrationRules: const [],
      now: now,
    );

    final prediction = envelope.predictions.single;
    expect(prediction.delaySource, 'train_info');
    expect(prediction.previousStopDeparture, DateTime(2026, 5, 28, 10, 4));
    expect(prediction.nextStopArrival, DateTime(2026, 5, 28, 10, 14));
  });

  test('runtime previous panel state starts empty and advances after eta', () {
    final prediction = PredictionRecord(trainNo: '3001', upstreamStationId: 'A', upstreamStationName: '甲站', downstreamStationId: 'B', downstreamStationName: '乙站', eta: DateTime(2026, 5, 28, 10), warning: true, warningWindowMinutes: 5, confidence: 'high', dataBasis: 'timetable', reason: 'test', segmentRatio: 0.5);

    final state = const PredictionRuntimeState().advance([prediction], DateTime(2026, 5, 28, 10, 0, 1));

    expect(state.previous, prediction);
    expect(state.processedKeys, isNotEmpty);
  });

  test('projects a liveboard station onto the active station pair', () {
    final service = PredictionService();
    final now = DateTime(2026, 5, 28, 9, 45);
    final snapshot = PredictionDataSnapshot(
      liveboardCount: 1,
      timetableCount: 1,
      trainInfoCount: 0,
      sources: const [PredictionSnapshotSource(source: 'liveboards', fetchedFrom: 'stale_cache', recordCount: 1)],
    );

    final envelope = service.predictForCrossing(
      crossing: _crossing('demo', 0.6),
      timetables: [_timetable()],
      liveboards: [TrainLiveBoard(trainNo: '3001', stationId: 'C', stationName: '中間站', updateTime: DateTime(2026, 5, 28, 10, 6))],
      trainInfos: const [],
      stationLookupById: _stations,
      calibrationRules: const [],
      stationPairProjections: const {'C|A|B': StationPairProjection(stationId: 'C', upstreamStationId: 'A', downstreamStationId: 'B', ratio: 0.4, source: 'osm_path', confidence: 'medium')},
      dataSnapshot: snapshot,
      now: now,
    );

    final prediction = envelope.predictions.single;
    expect(prediction.dataBasis, 'liveboard');
    expect(prediction.delaySource, 'liveboard');
    expect(prediction.reason, contains('Projected'));
    expect(prediction.eta.difference(DateTime(2026, 5, 28, 10, 8)).inSeconds.abs(), lessThanOrEqualTo(5));
    expect(envelope.dataSnapshot?.hasStaleSource, isTrue);
    expect(envelope.dataSnapshot?.timingsMs, contains('prediction_total'));
  });
}

Crossing _crossing(String id, double ratio) => Crossing(
  id: id,
  name: '四叉巷',
  line: '縱貫線北段',
  county: '臺南市',
  kmMarker: 'K353+375',
  geometry: const GeoPoint(lat: 23.0277, lon: 120.2371),
  geolocationConfidence: 'high',
  segmentRatio: ratio,
  ratioSource: 'osm_path',
  segmentConfidence: 'high',
  stationA: const StationRef(id: 'A', name: '永康', position: GeoPoint(lat: 23.03825, lon: 120.25347)),
  stationB: const StationRef(id: 'B', name: '臺南', position: GeoPoint(lat: 22.99681, lon: 120.21295)),
  runtimeRatios: {
    'A|B': RuntimeRatio(upstreamStationId: 'A', downstreamStationId: 'B', ratio: ratio, source: 'osm_path', confidence: 'high'),
    'B|A': RuntimeRatio(upstreamStationId: 'B', downstreamStationId: 'A', ratio: 1 - ratio, source: 'osm_path', confidence: 'high'),
  },
);

TrainTimetable _timetable({bool directionReverse = false}) => TrainTimetable(
  trainNo: '3001',
  trainTypeName: '區間',
  originStationId: directionReverse ? 'B' : 'A',
  originStationName: directionReverse ? '臺南' : '永康',
  destinationStationId: directionReverse ? 'A' : 'B',
  destinationStationName: directionReverse ? '永康' : '臺南',
  stopTimes: directionReverse ? const [StopTime(stationId: 'B', stationName: '臺南', stopSequence: 1, arrivalTime: '10:00', departureTime: '10:00'), StopTime(stationId: 'A', stationName: '永康', stopSequence: 2, arrivalTime: '10:10', departureTime: '10:10')] : const [StopTime(stationId: 'A', stationName: '永康', stopSequence: 1, arrivalTime: '10:00', departureTime: '10:00'), StopTime(stationId: 'B', stationName: '臺南', stopSequence: 2, arrivalTime: '10:10', departureTime: '10:10')],
);

const _stations = {'A': Station(id: 'A', name: '永康', position: GeoPoint(lat: 23.03825, lon: 120.25347)), 'B': Station(id: 'B', name: '臺南', position: GeoPoint(lat: 22.99681, lon: 120.21295))};

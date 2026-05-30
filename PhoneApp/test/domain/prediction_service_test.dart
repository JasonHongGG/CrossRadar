import 'package:crossradar_phone/src/domain/models.dart';
import 'package:crossradar_phone/src/domain/prediction_service.dart';
import 'package:crossradar_phone/src/domain/railway_clock.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final clock = RailwayClock.instance;

  test('reverse direction applies 1 minus segment ratio and preserves crossing order', () {
    final service = PredictionService(railwayClock: clock);
    final now = _taipei(2026, 5, 28, 9, 30);
    final timetable = _timetable(directionReverse: true);

    final north = service.predictForCrossing(crossing: _crossing('north', 0.3), timetables: [timetable], liveboards: const [], trainInfos: const [], stationLookupById: _stations, calibrationRules: const [], now: now);
    final south = service.predictForCrossing(crossing: _crossing('south', 0.7), timetables: [timetable], liveboards: const [], trainInfos: const [], stationLookupById: _stations, calibrationRules: const [], now: now);

    expect(north.predictions.single.segmentRatio, closeTo(0.7, 0.0001));
    expect(south.predictions.single.segmentRatio, closeTo(0.3, 0.0001));
    expect(south.predictions.single.eta.isBefore(north.predictions.single.eta), isTrue);
  });

  test('train-info delay shifts upstream and downstream stop times', () {
    final service = PredictionService(railwayClock: clock);
    final now = _taipei(2026, 5, 28, 9, 30);

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
    expect(prediction.previousStopDeparture, _taipei(2026, 5, 28, 10, 4));
    expect(prediction.nextStopArrival, _taipei(2026, 5, 28, 10, 14));
    expect(prediction.trace?.delaySeconds, 240);
  });

  test('runtime previous panel state starts empty and advances after eta', () {
    final prediction = PredictionRecord(trainNo: '3001', upstreamStationId: 'A', upstreamStationName: '甲站', downstreamStationId: 'B', downstreamStationName: '乙站', eta: _taipei(2026, 5, 28, 10), warning: true, warningWindowMinutes: 5, confidence: 'high', dataBasis: 'timetable', reason: 'test', segmentRatio: 0.5);

    final state = const PredictionRuntimeState().advance([prediction], _taipei(2026, 5, 28, 10, 0, 1));

    expect(state.previous, prediction);
    expect(state.processedKeys, isNotEmpty);
  });

  test('projects a liveboard station onto the active station pair', () {
    final service = PredictionService(railwayClock: clock);
    final now = _taipei(2026, 5, 28, 9, 45);
    final snapshot = PredictionDataSnapshot(
      liveboardCount: 1,
      timetableCount: 1,
      trainInfoCount: 0,
      sources: const [PredictionSnapshotSource(source: 'liveboards', fetchedFrom: 'stale_cache', recordCount: 1)],
    );

    final envelope = service.predictForCrossing(
      crossing: _crossing('demo', 0.6),
      timetables: [_timetable()],
      liveboards: [TrainLiveBoard(trainNo: '3001', stationId: 'C', stationName: '中間站', updateTime: _taipei(2026, 5, 28, 10, 6))],
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
    expect(prediction.eta.difference(_taipei(2026, 5, 28, 10, 8)).inSeconds.abs(), lessThanOrEqualTo(5));
    expect(prediction.trace?.observedRatio, closeTo(0.4, 0.0001));
    expect(prediction.trace?.projectionReason, contains('Projected'));
    expect(envelope.dataSnapshot?.hasStaleSource, isTrue);
    expect(envelope.dataSnapshot?.timingsMs, contains('prediction_total'));
  });

  test('timetable fallback keeps liveboard projection rejection detail', () {
    final service = PredictionService(railwayClock: clock);
    final now = _taipei(2026, 5, 28, 9, 45);

    final envelope = service.predictForCrossing(
      crossing: _crossing('demo', 0.6),
      timetables: [_timetable()],
      liveboards: [TrainLiveBoard(trainNo: '3001', stationId: 'C', stationName: '中間站', updateTime: _taipei(2026, 5, 28, 10, 6))],
      trainInfos: const [],
      stationLookupById: _stations,
      calibrationRules: const [],
      stationPairProjectionRejections: const {'C|A|B': StationPairProjectionRejection(stationId: 'C', upstreamStationId: 'A', downstreamStationId: 'B', source: 'unavailable', confidence: 'low', note: 'No usable station-pair projection was exported for this liveboard station.')},
      now: now,
    );

    final prediction = envelope.predictions.single;
    expect(prediction.dataBasis, 'timetable');
    expect(prediction.delaySource, 'none');
    expect(prediction.reason, contains('中間站'));
    expect(prediction.reason, contains('No usable station-pair projection was exported for this liveboard station.'));
  });

  test('timetable fallback uses liveboard delay when only a downstream stop record exists', () {
    final service = PredictionService(railwayClock: clock);
    final now = _taipei(2026, 5, 28, 9, 45);

    final envelope = service.predictForCrossing(
      crossing: _crossing('demo', 0.6),
      timetables: [_timetable()],
      liveboards: [TrainLiveBoard(trainNo: '3001', stationId: 'B', stationName: '臺南', delayTime: 1, updateTime: _taipei(2026, 5, 28, 10, 10))],
      trainInfos: const [],
      stationLookupById: _stations,
      calibrationRules: const [],
      now: now,
    );

    final prediction = envelope.predictions.single;
    expect(prediction.dataBasis, 'timetable');
    expect(prediction.delaySource, 'liveboard');
    expect(prediction.delayMinutes, 1);
    expect(prediction.reason, contains('liveboard delay fallback'));
    expect(prediction.reason, contains('no crossing-valid liveboard station context'));
  });

  test('timetable fallback preserves zero-minute liveboard delay when projection is rejected', () {
    final service = PredictionService(railwayClock: clock);
    final now = _taipei(2026, 5, 28, 9, 45);

    final envelope = service.predictForCrossing(
      crossing: _crossing('demo', 0.6),
      timetables: [_timetable()],
      liveboards: [TrainLiveBoard(trainNo: '3001', stationId: 'C', stationName: '中間站', delayTime: 0, updateTime: _taipei(2026, 5, 28, 10, 6))],
      trainInfos: const [],
      stationLookupById: _stations,
      calibrationRules: const [],
      stationPairProjectionRejections: const {'C|A|B': StationPairProjectionRejection(stationId: 'C', upstreamStationId: 'A', downstreamStationId: 'B', source: 'unavailable', confidence: 'low', note: 'No usable station-pair projection was exported for this liveboard station.')},
      now: now,
    );

    final prediction = envelope.predictions.single;
    expect(prediction.dataBasis, 'timetable');
    expect(prediction.delaySource, 'liveboard');
    expect(prediction.delayMinutes, 0);
    expect(prediction.reason, contains('No usable station-pair projection was exported for this liveboard station.'));
    expect(prediction.reason, contains('liveboard delay fallback'));
  });

  test('mobile bundle decodes station pair projection rejections', () {
    final bundle = MobileBundle.fromJson({
      'metadata': {'schema_version': 2},
      'crossings': [],
      'stations': [],
      'station_pair_projections': {},
      'station_pair_projection_rejections': {
        'C|A|B': {'station_id': 'C', 'upstream_station_id': 'A', 'downstream_station_id': 'B', 'source': 'unavailable', 'confidence': 'low', 'note': 'No usable station-pair projection was exported for this liveboard station.'},
      },
      'calibration': {'rules': []},
    });

    expect(bundle.stationPairProjectionRejections['C|A|B']?.note, 'No usable station-pair projection was exported for this liveboard station.');
  });

  test('blocks predictions when a required snapshot source is incomplete', () {
    final service = PredictionService(railwayClock: clock);
    final envelope = service.predictForCrossing(
      crossing: _crossing('demo', 0.5),
      timetables: [_timetable()],
      liveboards: const [],
      trainInfos: const [],
      stationLookupById: _stations,
      calibrationRules: const [],
      dataSnapshot: const PredictionDataSnapshot(comprehensive: false, sources: [PredictionSnapshotSource(source: 'liveboards', complete: false)]),
      now: _taipei(2026, 5, 28, 9, 30),
    );

    expect(envelope.available, isFalse);
    expect(envelope.unavailableReason, 'snapshot_incomplete');
    expect(envelope.predictions, isEmpty);
    expect(envelope.dataSnapshot?.timingsMs, contains('prediction_total'));
  });

  test('parses TDX update times without offset as Taipei railway time', () {
    final service = PredictionService(railwayClock: RailwayClock(utcNow: () => DateTime.utc(2026, 5, 28, 1, 45)));
    final liveboard = TrainLiveBoard.fromJson({
      'TrainNo': '3001',
      'StationID': 'A',
      'StationName': {'Zh_tw': '永康'},
      'UpdateTime': '2026-05-28T10:02:00',
      'DelayTime': 0,
    });

    final envelope = service.predictForCrossing(crossing: _crossing('demo', 0.5), timetables: [_timetable()], liveboards: [liveboard], trainInfos: const [], stationLookupById: _stations, calibrationRules: const [], now: DateTime.utc(2026, 5, 28, 1, 45));

    final prediction = envelope.predictions.single;
    expect(prediction.delaySeconds, 120);
    expect(prediction.anchorTimeSource, 'liveboard_update');
    expect(prediction.trace?.serviceDate, '2026-05-28');
    expect(prediction.trace?.liveboardUpdateTime, _taipei(2026, 5, 28, 10, 2));
  });

  test('applies calibration offsets and exposes timing trace parity fields', () {
    final service = PredictionService(railwayClock: clock);
    final base = service.predictForCrossing(crossing: _crossing('demo', 0.5), timetables: [_timetable()], liveboards: const [], trainInfos: const [], stationLookupById: _stations, calibrationRules: const [], now: _taipei(2026, 5, 28, 9, 30)).predictions.single;
    final calibrated = service
        .predictForCrossing(
          crossing: _crossing('demo', 0.5),
          timetables: [_timetable()],
          liveboards: const [],
          trainInfos: const [],
          stationLookupById: _stations,
          calibrationRules: const [
            CalibrationRule(id: 'demo-rule', match: {'crossing_id': 'demo', 'direction': 0, 'train_type_family': 'local', 'upstream_station_id': 'A'}, offsetSeconds: 45),
          ],
          now: _taipei(2026, 5, 28, 9, 30),
        )
        .predictions
        .single;

    expect(calibrated.calibrationOffsetSeconds, 45);
    expect(calibrated.eta.difference(base.eta).inSeconds, 45);
    expect(calibrated.trace?.travelProfileId, isNotEmpty);
    expect(calibrated.trace?.timeFraction, closeTo(base.trace!.timeFraction, 0.000001));
  });
}

DateTime _taipei(int year, int month, int day, int hour, [int minute = 0, int second = 0]) => RailwayClock.instance.parseTimetableTime(DateTime(year, month, day), '${hour.toString().padLeft(2, '0')}:${minute.toString().padLeft(2, '0')}:${second.toString().padLeft(2, '0')}')!;

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

import 'dart:convert';

import 'package:crossradar_phone/src/domain/models.dart';
import 'package:crossradar_phone/src/domain/prediction_diagnostics.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'exports replayable prediction debug capture with trace and bundle contract',
    () {
      final capture = buildPredictionDebugCapture(
        crossing: _crossing,
        bundle: _bundle,
        envelope: _envelope,
        capturedAt: DateTime.utc(2026, 5, 28, 2),
      );
      final decoded =
          jsonDecode(encodePredictionDebugCapture(capture))
              as Map<String, dynamic>;
      final prediction = decoded['prediction'] as Map<String, dynamic>;
      final predictions = prediction['predictions'] as List;
      final trace =
          (predictions.single as Map<String, dynamic>)['trace']
              as Map<String, dynamic>;

      expect(decoded['railway_time_zone'], 'Asia/Taipei');
      expect((decoded['bundle'] as Map<String, dynamic>)['schema_version'], 3);
      expect(
        (decoded['crossing'] as Map<String, dynamic>)['runtime_ratios'],
        contains('1000|2000'),
      );
      expect(trace['train_no'], '1234');
      expect(trace['timing_model'], 'scheduled_segment_fraction');
      expect(trace['eta'], '2026-05-28T10:05:30.000Z');
    },
  );
}

const _stationA = StationRef(
  id: '1000',
  name: '永康',
  position: GeoPoint(lat: 23.038, lon: 120.253),
);
const _stationB = StationRef(
  id: '2000',
  name: '臺南',
  position: GeoPoint(lat: 22.997, lon: 120.212),
);

final _crossing = Crossing(
  id: 'c1',
  name: '測試平交道',
  geometry: const GeoPoint(lat: 23.0, lon: 120.2),
  stationA: _stationA,
  stationB: _stationB,
  runtimeRatios: const {
    '1000|2000': RuntimeRatio(
      upstreamStationId: '1000',
      downstreamStationId: '2000',
      ratio: 0.55,
      source: 'osm_chainage',
      confidence: 'high',
    ),
  },
);

final _bundle = MobileBundle(
  metadata: const {
    'schema_version': 3,
    'data_version': 'test',
    'generated_at': '2026-05-28T00:00:00Z',
    'prediction_contract': {
      'railway_time_zone': 'Asia/Taipei',
      'snapshot_required_sources': ['liveboards', 'timetables', 'train_info'],
    },
  },
  crossings: [_crossing],
  stations: const [
    Station(
      id: '1000',
      name: '永康',
      position: GeoPoint(lat: 23.038, lon: 120.253),
    ),
    Station(
      id: '2000',
      name: '臺南',
      position: GeoPoint(lat: 22.997, lon: 120.212),
    ),
  ],
  calibrationRules: const [],
);

final _record = PredictionRecord(
  trainNo: '1234',
  upstreamStationId: '1000',
  upstreamStationName: '永康',
  downstreamStationId: '2000',
  downstreamStationName: '臺南',
  eta: DateTime.utc(2026, 5, 28, 10, 5, 30),
  warning: false,
  warningWindowMinutes: 5,
  confidence: 'high',
  dataBasis: 'liveboard',
  reason: 'test',
  segmentRatio: 0.55,
  trace: PredictionTrace(
    serviceDate: '2026-05-28',
    trainNo: '1234',
    upstreamStationId: '1000',
    downstreamStationId: '2000',
    ratio: 0.55,
    ratioSource: 'osm_chainage',
    segmentConfidence: 'high',
    scheduledUpstream: DateTime.utc(2026, 5, 28, 10),
    scheduledDownstream: DateTime.utc(2026, 5, 28, 10, 10),
    actualUpstream: DateTime.utc(2026, 5, 28, 10),
    actualDownstream: DateTime.utc(2026, 5, 28, 10, 10),
    delaySeconds: 0,
    delaySource: 'liveboard',
    travelProfileId: 'baseline',
    trainTypeFamily: 'local',
    timeFraction: 0.55,
    timingModel: 'scheduled_segment_fraction',
    calibrationOffsetSeconds: 0,
    eta: DateTime.utc(2026, 5, 28, 10, 5, 30),
  ),
);

final _envelope = PredictionEnvelope(
  crossingId: 'c1',
  generatedAt: DateTime.utc(2026, 5, 28, 2),
  warningWindowMinutes: 5,
  recentWindowMinutes: 3,
  available: true,
  dataSnapshot: const PredictionDataSnapshot(
    comprehensive: true,
    liveboardCount: 1,
    timetableCount: 1,
    trainInfoCount: 1,
    sources: [
      PredictionSnapshotSource(source: 'liveboards', recordCount: 1),
      PredictionSnapshotSource(source: 'timetables', recordCount: 1),
      PredictionSnapshotSource(source: 'train_info', recordCount: 1),
    ],
  ),
  upcomingPredictions: [_record],
  predictions: [_record],
);

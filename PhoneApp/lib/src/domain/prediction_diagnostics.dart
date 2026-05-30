import 'dart:convert';

import 'models.dart';

Map<String, Object?> buildPredictionDebugCapture({
  required Crossing crossing,
  required MobileBundle bundle,
  required PredictionEnvelope envelope,
  required DateTime capturedAt,
}) {
  return {
    'schema_version': 1,
    'captured_at': capturedAt.toIso8601String(),
    'railway_time_zone':
        bundle.predictionContract['railway_time_zone'] ?? 'Asia/Taipei',
    'bundle': {
      'schema_version': bundle.schemaVersion,
      'data_version': bundle.metadata['data_version'],
      'generated_at': bundle.metadata['generated_at'],
      'prediction_contract': bundle.predictionContract,
      'has_calibration_rules': bundle.hasCalibrationRules,
      'calibration_rule_count': bundle.calibrationRules.length,
      'station_pair_projection_count': bundle.stationPairProjections.length,
      'station_pair_projection_rejection_count':
          bundle.stationPairProjectionRejections.length,
    },
    'crossing': crossing.toJson(),
    'prediction': envelope.toJson(),
  };
}

String encodePredictionDebugCapture(Map<String, Object?> capture) {
  return const JsonEncoder.withIndent('  ').convert(capture);
}

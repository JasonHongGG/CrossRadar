import 'dart:convert';

import 'railway_clock.dart';

double? doubleValue(Object? value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  return double.tryParse(value.toString());
}

int intValue(Object? value, [int fallback = 0]) {
  if (value == null || value == '') return fallback;
  if (value is int) return value;
  if (value is num) return value.round();
  return int.tryParse(value.toString()) ?? fallback;
}

String? textValue(Object? value) {
  if (value == null) return null;
  if (value is String) return value.trim().isEmpty ? null : value.trim();
  if (value is Map) return textValue(value['Zh_tw']) ?? textValue(value['En']);
  final text = value.toString().trim();
  return text.isEmpty ? null : text;
}

Map<String, dynamic> mapValue(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) {
    return value.map((key, val) => MapEntry(key.toString(), val));
  }
  return const {};
}

List<Map<String, dynamic>> mapList(Object? value) {
  if (value is! List) return const [];
  return value
      .map(mapValue)
      .where((item) => item.isNotEmpty)
      .toList(growable: false);
}

class GeoPoint {
  const GeoPoint({required this.lat, required this.lon});

  final double lat;
  final double lon;

  factory GeoPoint.fromJson(Map<String, dynamic> json) {
    return GeoPoint(
      lat: doubleValue(json['lat'] ?? json['PositionLat']) ?? 0,
      lon: doubleValue(json['lon'] ?? json['PositionLon']) ?? 0,
    );
  }

  Map<String, Object?> toJson() => {'lat': lat, 'lon': lon};
}

class StationRef {
  const StationRef({
    required this.id,
    required this.name,
    required this.position,
    this.ukPrimary,
    this.ukValues = const [],
  });

  final String? id;
  final String? name;
  final GeoPoint? position;
  final String? ukPrimary;
  final List<String> ukValues;

  factory StationRef.fromJson(Map<String, dynamic> json) {
    final position = mapValue(json['position']);
    return StationRef(
      id: textValue(json['id'] ?? json['station_id'] ?? json['StationID']),
      name: textValue(json['name'] ?? json['StationName']),
      position: position.isEmpty ? null : GeoPoint.fromJson(position),
      ukPrimary: textValue(json['uk_primary'] ?? json['UK_primary']),
      ukValues: (json['uk_values'] as List? ?? json['UK'] as List? ?? const [])
          .map((value) => value.toString())
          .where((value) => value.trim().isNotEmpty)
          .toList(growable: false),
    );
  }

  Map<String, Object?> toJson() => {
    'id': id,
    'name': name,
    'position': position?.toJson(),
    'uk_primary': ukPrimary,
    'uk_values': ukValues,
  };
}

class RuntimeRatio {
  const RuntimeRatio({
    required this.upstreamStationId,
    required this.downstreamStationId,
    required this.ratio,
    required this.source,
    required this.confidence,
    this.note,
  });

  final String upstreamStationId;
  final String downstreamStationId;
  final double ratio;
  final String source;
  final String confidence;
  final String? note;

  String get key => '$upstreamStationId|$downstreamStationId';

  factory RuntimeRatio.fromJson(Map<String, dynamic> json) {
    return RuntimeRatio(
      upstreamStationId: textValue(json['upstream_station_id']) ?? '',
      downstreamStationId: textValue(json['downstream_station_id']) ?? '',
      ratio: doubleValue(json['ratio']) ?? 0.5,
      source: textValue(json['source']) ?? 'unavailable',
      confidence: textValue(json['confidence']) ?? 'low',
      note: textValue(json['note']),
    );
  }

  Map<String, Object?> toJson() => {
    'upstream_station_id': upstreamStationId,
    'downstream_station_id': downstreamStationId,
    'ratio': ratio,
    'source': source,
    'confidence': confidence,
    'note': note,
  };
}

class StationPairProjection {
  const StationPairProjection({
    required this.stationId,
    required this.upstreamStationId,
    required this.downstreamStationId,
    required this.ratio,
    required this.source,
    required this.confidence,
    this.note,
  });

  final String stationId;
  final String upstreamStationId;
  final String downstreamStationId;
  final double ratio;
  final String source;
  final String confidence;
  final String? note;

  String get key => '$stationId|$upstreamStationId|$downstreamStationId';

  factory StationPairProjection.fromJson(Map<String, dynamic> json) {
    return StationPairProjection(
      stationId: textValue(json['station_id']) ?? '',
      upstreamStationId: textValue(json['upstream_station_id']) ?? '',
      downstreamStationId: textValue(json['downstream_station_id']) ?? '',
      ratio: doubleValue(json['ratio']) ?? 0.5,
      source: textValue(json['source']) ?? 'unavailable',
      confidence: textValue(json['confidence']) ?? 'low',
      note: textValue(json['note']),
    );
  }
}

class StationPairProjectionRejection {
  const StationPairProjectionRejection({
    required this.stationId,
    required this.upstreamStationId,
    required this.downstreamStationId,
    required this.source,
    required this.confidence,
    this.note,
  });

  final String stationId;
  final String upstreamStationId;
  final String downstreamStationId;
  final String source;
  final String confidence;
  final String? note;

  String get key => '$stationId|$upstreamStationId|$downstreamStationId';

  factory StationPairProjectionRejection.fromJson(Map<String, dynamic> json) {
    return StationPairProjectionRejection(
      stationId: textValue(json['station_id']) ?? '',
      upstreamStationId: textValue(json['upstream_station_id']) ?? '',
      downstreamStationId: textValue(json['downstream_station_id']) ?? '',
      source: textValue(json['source']) ?? 'unavailable',
      confidence: textValue(json['confidence']) ?? 'low',
      note: textValue(json['note']),
    );
  }
}

class Crossing {
  const Crossing({
    required this.id,
    required this.name,
    required this.geometry,
    required this.stationA,
    required this.stationB,
    required this.runtimeRatios,
    this.runtimeRatioRejections = const {},
    this.line,
    this.county,
    this.roadType,
    this.kmMarker,
    this.stationPairText,
    this.stationPairSource,
    this.geolocationConfidence,
    this.segmentRatio,
    this.ratioSource,
    this.segmentConfidence,
    this.segmentConfidenceReason,
  });

  final String id;
  final String name;
  final String? line;
  final String? county;
  final String? roadType;
  final String? kmMarker;
  final String? stationPairText;
  final String? stationPairSource;
  final GeoPoint geometry;
  final String? geolocationConfidence;
  final double? segmentRatio;
  final String? ratioSource;
  final String? segmentConfidence;
  final String? segmentConfidenceReason;
  final StationRef stationA;
  final StationRef stationB;
  final Map<String, RuntimeRatio> runtimeRatios;
  final Map<String, Map<String, dynamic>> runtimeRatioRejections;

  String get stationPairLabel {
    final first = stationA.name ?? '';
    final second = stationB.name ?? '';
    if (first.isEmpty || second.isEmpty) return stationPairText ?? '';
    return '$first-$second';
  }

  String get subtitle {
    final parts = [
      line,
      kmMarker,
      roadType,
    ].whereType<String>().where((value) => value.isNotEmpty).toList();
    return parts.join('-');
  }

  factory Crossing.fromJson(Map<String, dynamic> json) {
    final ratios = <String, RuntimeRatio>{};
    for (final entry in mapValue(json['runtime_ratios']).entries) {
      final ratio = RuntimeRatio.fromJson(mapValue(entry.value));
      if (ratio.upstreamStationId.isNotEmpty &&
          ratio.downstreamStationId.isNotEmpty) {
        ratios[entry.key] = ratio;
      }
    }
    final rejections = <String, Map<String, dynamic>>{};
    for (final entry in mapValue(json['runtime_ratio_rejections']).entries) {
      rejections[entry.key] = mapValue(entry.value);
    }
    return Crossing(
      id: textValue(json['id']) ?? '',
      name: textValue(json['name']) ?? '未命名平交道',
      line: textValue(json['line']),
      county: textValue(json['county']),
      roadType: textValue(json['road_type']),
      kmMarker: textValue(json['km_marker']),
      stationPairText: textValue(json['station_pair_text']),
      stationPairSource: textValue(json['station_pair_source']),
      geometry: GeoPoint.fromJson(mapValue(json['geometry'])),
      geolocationConfidence: textValue(json['geolocation_confidence']),
      segmentRatio: doubleValue(json['segment_ratio']),
      ratioSource: textValue(json['ratio_source']),
      segmentConfidence: textValue(json['segment_confidence']),
      segmentConfidenceReason: textValue(json['segment_confidence_reason']),
      stationA: StationRef.fromJson(mapValue(json['station_a'])),
      stationB: StationRef.fromJson(mapValue(json['station_b'])),
      runtimeRatios: ratios,
      runtimeRatioRejections: rejections,
    );
  }

  Map<String, Object?> toJson() => {
    'id': id,
    'name': name,
    'line': line,
    'county': county,
    'road_type': roadType,
    'km_marker': kmMarker,
    'station_pair_text': stationPairText,
    'station_pair_source': stationPairSource,
    'geometry': geometry.toJson(),
    'geolocation_confidence': geolocationConfidence,
    'segment_ratio': segmentRatio,
    'ratio_source': ratioSource,
    'segment_confidence': segmentConfidence,
    'segment_confidence_reason': segmentConfidenceReason,
    'station_a': stationA.toJson(),
    'station_b': stationB.toJson(),
    'runtime_ratios': runtimeRatios.map(
      (key, value) => MapEntry(key, value.toJson()),
    ),
    'runtime_ratio_rejections': runtimeRatioRejections,
  };
}

class Station {
  const Station({
    required this.id,
    required this.name,
    required this.position,
    this.ukPrimary,
  });

  final String id;
  final String name;
  final GeoPoint position;
  final String? ukPrimary;

  factory Station.fromJson(Map<String, dynamic> json) {
    return Station(
      id: textValue(json['station_id'] ?? json['StationID']) ?? '',
      name: textValue(json['name'] ?? json['StationName']) ?? '',
      position: GeoPoint.fromJson(
        mapValue(json['position'] ?? json['StationPosition']),
      ),
      ukPrimary: textValue(json['uk_primary'] ?? json['UK_primary']),
    );
  }
}

class CalibrationRule {
  const CalibrationRule({
    required this.id,
    required this.match,
    required this.offsetSeconds,
  });

  final String id;
  final Map<String, dynamic> match;
  final int offsetSeconds;

  factory CalibrationRule.fromJson(Map<String, dynamic> json) {
    return CalibrationRule(
      id: textValue(json['id']) ?? '',
      match: mapValue(json['match']),
      offsetSeconds: intValue(json['offset_seconds']),
    );
  }
}

class MobileBundle {
  const MobileBundle({
    required this.metadata,
    required this.crossings,
    required this.stations,
    required this.calibrationRules,
    this.calibrationMetadata = const {},
    this.stationPairProjections = const {},
    this.stationPairProjectionRejections = const {},
  });

  final Map<String, dynamic> metadata;
  final List<Crossing> crossings;
  final List<Station> stations;
  final List<CalibrationRule> calibrationRules;
  final Map<String, dynamic> calibrationMetadata;
  final Map<String, StationPairProjection> stationPairProjections;
  final Map<String, StationPairProjectionRejection>
  stationPairProjectionRejections;

  int get schemaVersion => intValue(metadata['schema_version']);
  Map<String, dynamic> get predictionContract =>
      mapValue(metadata['prediction_contract']);
  bool get hasCalibrationRules => calibrationRules.isNotEmpty;

  Map<String, Crossing> get crossingById => {
    for (final crossing in crossings) crossing.id: crossing,
  };
  Map<String, Station> get stationById => {
    for (final station in stations) station.id: station,
  };

  factory MobileBundle.fromJson(Map<String, dynamic> json) {
    final calibration = mapValue(json['calibration']);
    final projections = <String, StationPairProjection>{};
    final projectionRejections = <String, StationPairProjectionRejection>{};
    for (final entry in mapValue(json['station_pair_projections']).entries) {
      final projection = StationPairProjection.fromJson(mapValue(entry.value));
      if (projection.stationId.isNotEmpty &&
          projection.upstreamStationId.isNotEmpty &&
          projection.downstreamStationId.isNotEmpty) {
        projections[entry.key] = projection;
      }
    }
    for (final entry in mapValue(
      json['station_pair_projection_rejections'],
    ).entries) {
      final rejection = StationPairProjectionRejection.fromJson(
        mapValue(entry.value),
      );
      if (rejection.stationId.isNotEmpty &&
          rejection.upstreamStationId.isNotEmpty &&
          rejection.downstreamStationId.isNotEmpty) {
        projectionRejections[entry.key] = rejection;
      }
    }
    return MobileBundle(
      metadata: mapValue(json['metadata']),
      crossings: mapList(
        json['crossings'],
      ).map(Crossing.fromJson).toList(growable: false),
      stations: mapList(
        json['stations'],
      ).map(Station.fromJson).toList(growable: false),
      calibrationRules: mapList(
        calibration['rules'],
      ).map(CalibrationRule.fromJson).toList(growable: false),
      calibrationMetadata: mapValue(calibration['metadata']),
      stationPairProjections: projections,
      stationPairProjectionRejections: projectionRejections,
    );
  }

  factory MobileBundle.decode(String source) =>
      MobileBundle.fromJson(jsonDecode(source) as Map<String, dynamic>);
}

class StopTime {
  const StopTime({
    required this.stationId,
    required this.stationName,
    required this.stopSequence,
    this.arrivalTime,
    this.departureTime,
  });

  final String stationId;
  final String stationName;
  final int stopSequence;
  final String? arrivalTime;
  final String? departureTime;

  factory StopTime.fromJson(Map<String, dynamic> json) {
    return StopTime(
      stationId: textValue(json['StationID']) ?? '',
      stationName: textValue(json['StationName']) ?? '',
      stopSequence: intValue(json['StopSequence']),
      arrivalTime: textValue(json['ArrivalTime']),
      departureTime: textValue(json['DepartureTime']),
    );
  }
}

class TrainTimetable {
  const TrainTimetable({
    required this.trainNo,
    required this.trainTypeName,
    required this.originStationId,
    required this.originStationName,
    required this.destinationStationId,
    required this.destinationStationName,
    required this.stopTimes,
    this.headsign,
    this.direction,
  });

  final String trainNo;
  final String? trainTypeName;
  final String? originStationId;
  final String? originStationName;
  final String? destinationStationId;
  final String? destinationStationName;
  final String? headsign;
  final int? direction;
  final List<StopTime> stopTimes;

  factory TrainTimetable.fromJson(Map<String, dynamic> json) {
    final info = mapValue(json['TrainInfo']);
    final stops = mapList(
      json['StopTimes'],
    ).map(StopTime.fromJson).toList(growable: false);
    return TrainTimetable(
      trainNo: textValue(info['TrainNo']) ?? '',
      trainTypeName: textValue(info['TrainTypeName']),
      originStationId:
          textValue(info['StartingStationID']) ??
          (stops.isEmpty ? null : stops.first.stationId),
      originStationName:
          textValue(info['StartingStationName']) ??
          (stops.isEmpty ? null : stops.first.stationName),
      destinationStationId:
          textValue(info['EndingStationID']) ??
          (stops.isEmpty ? null : stops.last.stationId),
      destinationStationName:
          textValue(info['EndingStationName']) ??
          (stops.isEmpty ? null : stops.last.stationName),
      headsign: textValue(info['TripHeadSign']),
      direction: info['Direction'] != null ? intValue(info['Direction']) : null,
      stopTimes: stops,
    );
  }
}

class TrainLiveBoard {
  const TrainLiveBoard({
    required this.trainNo,
    required this.stationId,
    this.stationName,
    this.trainTypeName,
    this.updateTime,
    this.delayTime,
  });

  final String trainNo;
  final String stationId;
  final String? stationName;
  final String? trainTypeName;
  final DateTime? updateTime;
  final int? delayTime;

  factory TrainLiveBoard.fromJson(Map<String, dynamic> json) {
    final rawUpdate = textValue(json['UpdateTime'] ?? json['SrcUpdateTime']);
    return TrainLiveBoard(
      trainNo: textValue(json['TrainNo']) ?? '',
      stationId: textValue(json['StationID']) ?? '',
      stationName: textValue(json['StationName']),
      trainTypeName: textValue(json['TrainTypeName']),
      updateTime: RailwayClock.instance.parseTdxUpdateTime(rawUpdate),
      delayTime: json['DelayTime'] == null ? null : intValue(json['DelayTime']),
    );
  }
}

class PredictionTrace {
  const PredictionTrace({
    required this.serviceDate,
    required this.trainNo,
    required this.upstreamStationId,
    required this.downstreamStationId,
    required this.ratio,
    required this.ratioSource,
    required this.segmentConfidence,
    required this.scheduledUpstream,
    required this.scheduledDownstream,
    required this.actualUpstream,
    required this.actualDownstream,
    required this.delaySeconds,
    required this.delaySource,
    required this.travelProfileId,
    required this.trainTypeFamily,
    required this.timeFraction,
    required this.timingModel,
    required this.calibrationOffsetSeconds,
    required this.eta,
    this.liveboardStationId,
    this.liveboardUpdateTime,
    this.observedRatio,
    this.projectionReason,
    this.anchorTimeSource,
  });

  final String serviceDate;
  final String trainNo;
  final String upstreamStationId;
  final String downstreamStationId;
  final double ratio;
  final String ratioSource;
  final String segmentConfidence;
  final DateTime scheduledUpstream;
  final DateTime scheduledDownstream;
  final DateTime actualUpstream;
  final DateTime actualDownstream;
  final int delaySeconds;
  final String delaySource;
  final String travelProfileId;
  final String trainTypeFamily;
  final double timeFraction;
  final String timingModel;
  final String? anchorTimeSource;
  final int calibrationOffsetSeconds;
  final DateTime eta;
  final String? liveboardStationId;
  final DateTime? liveboardUpdateTime;
  final double? observedRatio;
  final String? projectionReason;

  Map<String, Object?> toJson() => {
    'service_date': serviceDate,
    'train_no': trainNo,
    'upstream_station_id': upstreamStationId,
    'downstream_station_id': downstreamStationId,
    'ratio': ratio,
    'ratio_source': ratioSource,
    'segment_confidence': segmentConfidence,
    'scheduled_upstream': scheduledUpstream.toIso8601String(),
    'scheduled_downstream': scheduledDownstream.toIso8601String(),
    'actual_upstream': actualUpstream.toIso8601String(),
    'actual_downstream': actualDownstream.toIso8601String(),
    'delay_seconds': delaySeconds,
    'delay_source': delaySource,
    'travel_profile_id': travelProfileId,
    'train_type_family': trainTypeFamily,
    'time_fraction': timeFraction,
    'timing_model': timingModel,
    'anchor_time_source': anchorTimeSource,
    'calibration_offset_seconds': calibrationOffsetSeconds,
    'eta': eta.toIso8601String(),
    'liveboard_station_id': liveboardStationId,
    'liveboard_update_time': liveboardUpdateTime?.toIso8601String(),
    'observed_ratio': observedRatio,
    'projection_reason': projectionReason,
  };
}

class TrainInfo {
  const TrainInfo({required this.trainNo, this.delayTime});

  final String trainNo;
  final int? delayTime;

  factory TrainInfo.fromJson(Map<String, dynamic> json) => TrainInfo(
    trainNo: textValue(json['TrainNo']) ?? '',
    delayTime: json['DelayTime'] == null ? null : intValue(json['DelayTime']),
  );
}

class PredictionSnapshotSource {
  const PredictionSnapshotSource({
    required this.source,
    this.complete = true,
    this.recordCount = 0,
    this.delayedRecordCount = 0,
    this.fetchedFrom,
    this.cachedAt,
    this.scope,
    this.detail,
    this.timingBreakdown = const {},
  });

  final String source;
  final bool complete;
  final int recordCount;
  final int delayedRecordCount;
  final String? fetchedFrom;
  final DateTime? cachedAt;
  final String? scope;
  final String? detail;
  final Map<String, int> timingBreakdown;

  bool get isStale => (fetchedFrom ?? '').startsWith('stale_');

  factory PredictionSnapshotSource.fromJson(Map<String, dynamic> json) {
    final cachedAtText = textValue(json['cached_at']);
    return PredictionSnapshotSource(
      source: textValue(json['source']) ?? '',
      complete: json['complete'] != false,
      recordCount: intValue(json['record_count']),
      delayedRecordCount: intValue(json['delayed_record_count']),
      fetchedFrom: textValue(json['fetched_from']),
      cachedAt: cachedAtText == null
          ? null
          : DateTime.tryParse(cachedAtText)?.toLocal(),
      scope: textValue(json['scope']),
      detail: textValue(json['detail']),
      timingBreakdown: mapValue(
        json['timing_breakdown'],
      ).map((key, value) => MapEntry(key, intValue(value))),
    );
  }

  Map<String, Object?> toJson() => {
    'source': source,
    'complete': complete,
    'record_count': recordCount,
    'delayed_record_count': delayedRecordCount,
    'fetched_from': fetchedFrom,
    'cached_at': cachedAt?.toIso8601String(),
    'scope': scope,
    'detail': detail,
    'timing_breakdown': timingBreakdown,
  };
}

class PredictionDataSnapshot {
  const PredictionDataSnapshot({
    this.comprehensive = true,
    this.liveboardCount = 0,
    this.delayedLiveboardCount = 0,
    this.timetableCount = 0,
    this.trainInfoCount = 0,
    this.delayedTrainInfoCount = 0,
    this.liveboardScope = const [],
    this.sources = const [],
    this.timingsMs = const {},
  });

  final bool comprehensive;
  final int liveboardCount;
  final int delayedLiveboardCount;
  final int timetableCount;
  final int trainInfoCount;
  final int delayedTrainInfoCount;
  final List<String> liveboardScope;
  final List<PredictionSnapshotSource> sources;
  final Map<String, int> timingsMs;

  bool get hasStaleSource => sources.any((source) => source.isStale);

  factory PredictionDataSnapshot.fromJson(Map<String, dynamic> json) {
    return PredictionDataSnapshot(
      comprehensive: json['comprehensive'] != false,
      liveboardCount: intValue(json['liveboard_count']),
      delayedLiveboardCount: intValue(json['delayed_liveboard_count']),
      timetableCount: intValue(json['timetable_count']),
      trainInfoCount: intValue(json['train_info_count']),
      delayedTrainInfoCount: intValue(json['delayed_train_info_count']),
      liveboardScope: (json['liveboard_scope'] as List? ?? const [])
          .map((value) => value.toString())
          .toList(growable: false),
      sources: mapList(
        json['sources'],
      ).map(PredictionSnapshotSource.fromJson).toList(growable: false),
      timingsMs: mapValue(
        json['timings_ms'],
      ).map((key, value) => MapEntry(key, intValue(value))),
    );
  }

  Map<String, Object?> toJson() => {
    'comprehensive': comprehensive,
    'liveboard_count': liveboardCount,
    'delayed_liveboard_count': delayedLiveboardCount,
    'timetable_count': timetableCount,
    'train_info_count': trainInfoCount,
    'delayed_train_info_count': delayedTrainInfoCount,
    'liveboard_scope': liveboardScope,
    'sources': sources.map((source) => source.toJson()).toList(),
    'timings_ms': timingsMs,
  };
}

class PredictionRecord {
  const PredictionRecord({
    required this.trainNo,
    required this.upstreamStationId,
    required this.upstreamStationName,
    required this.downstreamStationId,
    required this.downstreamStationName,
    required this.eta,
    required this.warning,
    required this.warningWindowMinutes,
    required this.confidence,
    required this.dataBasis,
    required this.reason,
    required this.segmentRatio,
    this.trainType,
    this.direction,
    this.headsign,
    this.originStationId,
    this.originStationName,
    this.destinationStationId,
    this.destinationStationName,
    this.sourceStationId,
    this.sourceStationName,
    this.previousStopStationId,
    this.previousStopStationName,
    this.previousStopDeparture,
    this.nextStopStationId,
    this.nextStopStationName,
    this.nextStopArrival,
    this.confidenceReason,
    this.delayMinutes = 0,
    this.delaySeconds,
    this.delaySource,
    this.predictionMethod,
    this.timingModel,
    this.anchorTimeSource,
    this.calibrationOffsetSeconds = 0,
    this.etaUncertaintySeconds,
    this.accuracyTier,
    this.ratioSource,
    this.segmentConfidence,
    this.trace,
  });

  final String trainNo;
  final String? trainType;
  final int? direction;
  final String? headsign;
  final String? originStationId;
  final String? originStationName;
  final String? destinationStationId;
  final String? destinationStationName;
  final String? sourceStationId;
  final String? sourceStationName;
  final String? previousStopStationId;
  final String? previousStopStationName;
  final DateTime? previousStopDeparture;
  final String? nextStopStationId;
  final String? nextStopStationName;
  final DateTime? nextStopArrival;
  final String upstreamStationId;
  final String upstreamStationName;
  final String downstreamStationId;
  final String downstreamStationName;
  final DateTime eta;
  final bool warning;
  final int warningWindowMinutes;
  final String confidence;
  final String? confidenceReason;
  final int delayMinutes;
  final int? delaySeconds;
  final String? delaySource;
  final String dataBasis;
  final String? predictionMethod;
  final String? timingModel;
  final String? anchorTimeSource;
  final int calibrationOffsetSeconds;
  final int? etaUncertaintySeconds;
  final String? accuracyTier;
  final String reason;
  final String? ratioSource;
  final String? segmentConfidence;
  final double segmentRatio;
  final PredictionTrace? trace;

  String get identityKey => '$trainNo|$upstreamStationId|$downstreamStationId';

  Map<String, Object?> toJson() => {
    'train_no': trainNo,
    'train_type': trainType,
    'direction': direction,
    'headsign': headsign,
    'origin_station_id': originStationId,
    'origin_station_name': originStationName,
    'destination_station_id': destinationStationId,
    'destination_station_name': destinationStationName,
    'source_station_id': sourceStationId,
    'source_station_name': sourceStationName,
    'previous_stop_station_id': previousStopStationId,
    'previous_stop_station_name': previousStopStationName,
    'previous_stop_departure': previousStopDeparture?.toIso8601String(),
    'next_stop_station_id': nextStopStationId,
    'next_stop_station_name': nextStopStationName,
    'next_stop_arrival': nextStopArrival?.toIso8601String(),
    'upstream_station_id': upstreamStationId,
    'upstream_station_name': upstreamStationName,
    'downstream_station_id': downstreamStationId,
    'downstream_station_name': downstreamStationName,
    'eta': eta.toIso8601String(),
    'warning': warning,
    'warning_window_minutes': warningWindowMinutes,
    'confidence': confidence,
    'confidence_reason': confidenceReason,
    'delay_minutes': delayMinutes,
    'delay_seconds': delaySeconds,
    'delay_source': delaySource,
    'data_basis': dataBasis,
    'prediction_method': predictionMethod,
    'timing_model': timingModel,
    'anchor_time_source': anchorTimeSource,
    'calibration_offset_seconds': calibrationOffsetSeconds,
    'eta_uncertainty_seconds': etaUncertaintySeconds,
    'accuracy_tier': accuracyTier,
    'reason': reason,
    'ratio_source': ratioSource,
    'segment_confidence': segmentConfidence,
    'segment_ratio': segmentRatio,
    'trace': trace?.toJson(),
  };
}

class PredictionEnvelope {
  const PredictionEnvelope({
    required this.crossingId,
    required this.generatedAt,
    required this.warningWindowMinutes,
    required this.recentWindowMinutes,
    required this.available,
    this.horizonMinutes,
    this.unavailableReason,
    this.unavailableDetail,
    this.dataSnapshot,
    this.recentPrediction,
    this.upcomingPredictions = const [],
    this.predictions = const [],
  });

  final String crossingId;
  final DateTime generatedAt;
  final int warningWindowMinutes;
  final int recentWindowMinutes;
  final int? horizonMinutes;
  final bool available;
  final String? unavailableReason;
  final String? unavailableDetail;
  final PredictionDataSnapshot? dataSnapshot;
  final PredictionRecord? recentPrediction;
  final List<PredictionRecord> upcomingPredictions;
  final List<PredictionRecord> predictions;

  Map<String, Object?> toJson() => {
    'crossing_id': crossingId,
    'generated_at': generatedAt.toIso8601String(),
    'warning_window_minutes': warningWindowMinutes,
    'recent_window_minutes': recentWindowMinutes,
    'horizon_minutes': horizonMinutes,
    'available': available,
    'unavailable_reason': unavailableReason,
    'unavailable_detail': unavailableDetail,
    'data_snapshot': dataSnapshot?.toJson(),
    'recent_prediction': recentPrediction?.toJson(),
    'upcoming_predictions': upcomingPredictions
        .map((prediction) => prediction.toJson())
        .toList(),
    'predictions': predictions
        .map((prediction) => prediction.toJson())
        .toList(),
  };
}

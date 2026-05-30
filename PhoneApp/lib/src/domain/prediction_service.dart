import 'dart:math' as math;

import 'models.dart';
import 'travel_profile_service.dart';

class PreparedTimetableCandidate {
  const PreparedTimetableCandidate({required this.timetable, required this.upstream, required this.downstream, required this.direction, required this.upstreamIndex, required this.downstreamIndex});

  final TrainTimetable timetable;
  final StopTime upstream;
  final StopTime downstream;
  final int direction;
  final int upstreamIndex;
  final int downstreamIndex;
}

class PreparedTimetableSet {
  const PreparedTimetableSet({required this.allCandidates, required this.byTrainNo});

  final List<PreparedTimetableCandidate> allCandidates;
  final Map<String, List<PreparedTimetableCandidate>> byTrainNo;
}

class DelayEstimate {
  const DelayEstimate({required this.seconds, required this.minutes, required this.source, this.reason});

  final int seconds;
  final int minutes;
  final String source;
  final String? reason;
}

class _LiveContext {
  const _LiveContext({required this.candidate, required this.liveboard, required this.observedStop, required this.observedIndex, required this.delayEstimate, this.observedRatio, this.projectionReason});

  final PreparedTimetableCandidate candidate;
  final TrainLiveBoard liveboard;
  final StopTime? observedStop;
  final int? observedIndex;
  final DelayEstimate delayEstimate;
  final double? observedRatio;
  final String? projectionReason;
}

class _LiveSelection {
  const _LiveSelection({this.context, this.fallbackReason});

  final _LiveContext? context;
  final String? fallbackReason;
}

class _LivePredictionBuildResult {
  const _LivePredictionBuildResult({required this.predictions, required this.fallbackReasons, required this.fallbackDelays, required this.fallbackLiveboards});

  final List<PredictionRecord> predictions;
  final Map<String, String> fallbackReasons;
  final Map<String, DelayEstimate> fallbackDelays;
  final Map<String, TrainLiveBoard> fallbackLiveboards;
}

class _StationProjectionResolution {
  const _StationProjectionResolution({required this.reason, this.ratio});

  final String reason;
  final double? ratio;
}

class _SegmentContext {
  const _SegmentContext({required this.ratio, required this.source, required this.confidence, required this.note});

  final double? ratio;
  final String source;
  final String confidence;
  final String note;
}

class _TimingEstimate {
  const _TimingEstimate({required this.eta, required this.ratio, required this.ratioSource, required this.segmentConfidence, required this.segmentNote, required this.actualUpstream, required this.actualDownstream, required this.timingModel, required this.calibrationOffsetSeconds, required this.etaUncertaintySeconds, required this.accuracyTier, required this.profile, this.anchorTimeSource});

  final DateTime eta;
  final double ratio;
  final String ratioSource;
  final String segmentConfidence;
  final String segmentNote;
  final DateTime actualUpstream;
  final DateTime actualDownstream;
  final String timingModel;
  final String? anchorTimeSource;
  final int calibrationOffsetSeconds;
  final int etaUncertaintySeconds;
  final String accuracyTier;
  final TravelProfileEstimate profile;
}

class PredictionRuntimeState {
  const PredictionRuntimeState({this.previous, this.processedKeys = const {}});

  final PredictionRecord? previous;
  final Set<String> processedKeys;

  PredictionRuntimeState advance(List<PredictionRecord> tracked, DateTime now) {
    var previous = this.previous;
    final processed = {...processedKeys};
    for (final prediction in tracked) {
      final key = '${prediction.identityKey}|${prediction.eta.toIso8601String()}';
      if (!processed.contains(key) && !prediction.eta.isAfter(now)) {
        previous = prediction;
        processed.add(key);
      }
    }
    return PredictionRuntimeState(previous: previous, processedKeys: processed);
  }
}

class PredictionService {
  PredictionService({TravelProfileService? travelProfileService}) : travelProfileService = travelProfileService ?? TravelProfileService();

  final TravelProfileService travelProfileService;

  PredictionEnvelope predictForCrossing({
    required Crossing crossing,
    required List<TrainTimetable> timetables,
    required List<TrainLiveBoard> liveboards,
    required List<TrainInfo> trainInfos,
    required Map<String, Station> stationLookupById,
    required List<CalibrationRule> calibrationRules,
    Map<String, StationPairProjection> stationPairProjections = const {},
    Map<String, StationPairProjectionRejection> stationPairProjectionRejections = const {},
    PredictionDataSnapshot? dataSnapshot,
    DateTime? now,
    int? horizonMinutes,
    int recentMinutes = 10,
    int warningMinutes = 5,
  }) {
    final started = Stopwatch()..start();
    now ??= DateTime.now();
    dataSnapshot ??= PredictionDataSnapshot(liveboardCount: liveboards.length, delayedLiveboardCount: liveboards.where((item) => (item.delayTime ?? 0) != 0).length, timetableCount: timetables.length, trainInfoCount: trainInfos.length, delayedTrainInfoCount: trainInfos.where((item) => (item.delayTime ?? 0) != 0).length);
    final stationAId = crossing.stationA.id;
    final stationBId = crossing.stationB.id;
    if (stationAId == null || stationAId.isEmpty || stationBId == null || stationBId.isEmpty) {
      return _unavailable(crossing, now, warningMinutes, horizonMinutes, recentMinutes, 'station_pair_unresolved', 'Station pair is unavailable.', dataSnapshot: dataSnapshot);
    }
    if (crossing.ratioSource != 'osm_path' || crossing.segmentRatio == null) {
      return _unavailable(crossing, now, warningMinutes, horizonMinutes, recentMinutes, 'runtime_segment_unavailable', crossing.segmentConfidenceReason ?? 'No accepted OSM runtime segment is available.', dataSnapshot: dataSnapshot);
    }

    final prepared = prepareTimetablesForCrossing(timetables, stationAId, stationBId, stationLookupById);
    final trainInfoByNo = {for (final info in trainInfos) info.trainNo: info};
    final liveResult = _buildPredictionsFromLiveboards(crossing, liveboards, prepared, trainInfoByNo, stationLookupById, stationPairProjections, stationPairProjectionRejections, calibrationRules, now, horizonMinutes, recentMinutes, warningMinutes);
    final timetablePredictions = _buildPredictionsFromTimetables(crossing, prepared, trainInfoByNo, stationLookupById, calibrationRules, now, horizonMinutes, recentMinutes, warningMinutes, liveboardFallbackReasons: liveResult.fallbackReasons, liveboardFallbackDelays: liveResult.fallbackDelays, liveboardFallbackLiveboards: liveResult.fallbackLiveboards);
    final predictions = _dedupePredictions(_mergePredictions(liveResult.predictions, timetablePredictions));
    final snapshot = _snapshotWithTiming(dataSnapshot, 'prediction_total', started.elapsedMilliseconds);
    if (predictions.isEmpty) {
      return _unavailable(crossing, now, warningMinutes, horizonMinutes, recentMinutes, 'no_prediction_candidates', liveResult.fallbackReasons.values.firstOrNull ?? 'No timetable or liveboard candidates matched this crossing.', dataSnapshot: snapshot);
    }
    final partition = _partitionPredictions(predictions, now, recentMinutes);
    return PredictionEnvelope(crossingId: crossing.id, generatedAt: now, warningWindowMinutes: warningMinutes, horizonMinutes: horizonMinutes, recentWindowMinutes: recentMinutes, available: true, dataSnapshot: snapshot, recentPrediction: partition.$1, upcomingPredictions: partition.$2, predictions: partition.$3);
  }

  PreparedTimetableSet prepareTimetablesForCrossing(List<TrainTimetable> timetables, String stationAId, String stationBId, Map<String, Station> stationLookupById) {
    final all = <PreparedTimetableCandidate>[];
    final byTrainNo = <String, List<PreparedTimetableCandidate>>{};
    for (final timetable in timetables) {
      final pair = resolveStopPair(timetable, stationAId, stationBId, stationLookupById);
      if (pair == null) continue;
      final upstreamIndex = timetable.stopTimes.indexOf(pair.$1);
      final downstreamIndex = timetable.stopTimes.indexOf(pair.$2);
      if (upstreamIndex < 0 || downstreamIndex < 0) continue;
      final candidate = PreparedTimetableCandidate(timetable: timetable, upstream: pair.$1, downstream: pair.$2, direction: pair.$3, upstreamIndex: upstreamIndex, downstreamIndex: downstreamIndex);
      all.add(candidate);
      byTrainNo.putIfAbsent(timetable.trainNo, () => []).add(candidate);
    }
    for (final candidates in byTrainNo.values) {
      candidates.sort((a, b) => _candidateScore(b, stationAId, stationBId).compareTo(_candidateScore(a, stationAId, stationBId)));
    }
    return PreparedTimetableSet(allCandidates: all, byTrainNo: byTrainNo);
  }

  (StopTime, StopTime, int)? resolveStopPair(TrainTimetable timetable, String stationAId, String stationBId, Map<String, Station> stationLookupById) {
    if (timetable.stopTimes.length < 2) return null;
    final stopA = timetable.stopTimes.where((stop) => stop.stationId == stationAId).firstOrNull;
    final stopB = timetable.stopTimes.where((stop) => stop.stationId == stationBId).firstOrNull;
    if (stopA == null || stopB == null) {
      if (stopA != null) {
        return _resolveSingleAnchorStopPair(timetable.stopTimes, anchorStop: stopA, anchorStationId: stationAId, targetStationId: stationBId, stationLookupById: stationLookupById, anchorRole: 'a', trainDirection: timetable.direction);
      }
      if (stopB != null) {
        return _resolveSingleAnchorStopPair(timetable.stopTimes, anchorStop: stopB, anchorStationId: stationBId, targetStationId: stationAId, stationLookupById: stationLookupById, anchorRole: 'b', trainDirection: timetable.direction);
      }
      return null;
    }
    final seqA = stopA.stopSequence;
    final seqB = stopB.stopSequence;
    if (seqA == seqB) return null;
    final direction = timetable.direction ?? (seqA < seqB ? 0 : 1);
    return seqA < seqB ? (stopA, stopB, direction) : (stopB, stopA, direction);
  }

  List<PredictionRecord> _buildPredictionsFromTimetables(Crossing crossing, PreparedTimetableSet prepared, Map<String, TrainInfo> trainInfoByNo, Map<String, Station> stationLookupById, List<CalibrationRule> calibrationRules, DateTime now, int? horizonMinutes, int recentMinutes, int warningMinutes, {Map<String, String> liveboardFallbackReasons = const {}, Map<String, DelayEstimate> liveboardFallbackDelays = const {}, Map<String, TrainLiveBoard> liveboardFallbackLiveboards = const {}}) {
    final predictions = <PredictionRecord>[];
    for (final candidate in prepared.allCandidates) {
      final timetable = candidate.timetable;
      final upstreamDeparture = parseTimeOnDate(now, candidate.upstream.departureTime ?? candidate.upstream.arrivalTime);
      final downstreamArrival = parseTimeOnDate(now, candidate.downstream.arrivalTime ?? candidate.downstream.departureTime);
      if (upstreamDeparture == null || downstreamArrival == null || !downstreamArrival.isAfter(upstreamDeparture)) {
        continue;
      }
      final delay = liveboardFallbackDelays[timetable.trainNo] ?? _resolveDelayMinutes(timetable.trainNo, trainInfoByNo: trainInfoByNo);
      final timing = _estimatePredictionTiming(
        crossing,
        trainNo: timetable.trainNo,
        trainTypeName: timetable.trainTypeName,
        upstreamStationId: candidate.upstream.stationId,
        downstreamStationId: candidate.downstream.stationId,
        upstream: candidate.upstream,
        downstream: candidate.downstream,
        upstreamDeparture: upstreamDeparture,
        downstreamArrival: downstreamArrival,
        delaySeconds: delay.seconds,
        delaySource: delay.source,
        direction: candidate.direction,
        stationLookupById: stationLookupById,
        calibrationRules: calibrationRules,
        dataBasis: 'timetable',
      );
      if (timing == null || !_isPredictionInWindow(timing.eta, now, horizonMinutes, recentMinutes)) {
        continue;
      }
      predictions.add(_buildRecord(crossing, timetable, candidate, timing, warningMinutes, hasLiveboard: false, delay: delay, liveboard: liveboardFallbackLiveboards[timetable.trainNo], fallbackReason: liveboardFallbackReasons[timetable.trainNo]));
    }
    predictions.sort((a, b) => a.eta.compareTo(b.eta));
    return predictions;
  }

  _LivePredictionBuildResult _buildPredictionsFromLiveboards(Crossing crossing, List<TrainLiveBoard> liveboards, PreparedTimetableSet prepared, Map<String, TrainInfo> trainInfoByNo, Map<String, Station> stationLookupById, Map<String, StationPairProjection> stationPairProjections, Map<String, StationPairProjectionRejection> stationPairProjectionRejections, List<CalibrationRule> calibrationRules, DateTime now, int? horizonMinutes, int recentMinutes, int warningMinutes) {
    final predictions = <PredictionRecord>[];
    final fallbackReasons = <String, String>{};
    final fallbackDelays = <String, DelayEstimate>{};
    final fallbackLiveboards = <String, TrainLiveBoard>{};
    final index = _buildLiveboardIndex(liveboards);
    for (final entry in prepared.byTrainNo.entries) {
      final trainLiveboards = index[entry.key] ?? const <TrainLiveBoard>[];
      final selection = _selectLiveboardCandidateContext(crossing, trainLiveboards, entry.value, trainInfoByNo, stationPairProjections, stationPairProjectionRejections, now);
      final context = selection.context;
      if (context == null) {
        final fallbackReason = selection.fallbackReason;
        if (fallbackReason != null) {
          fallbackReasons[entry.key] = fallbackReason;
        }
        final delayFallback = _resolveLiveboardDelayFallback(trainLiveboards);
        if (delayFallback != null) {
          fallbackDelays[entry.key] = delayFallback.$1;
          fallbackLiveboards[entry.key] = delayFallback.$2;
        }
        continue;
      }
      final candidate = context.candidate;
      final timetable = candidate.timetable;
      final upstreamDeparture = parseTimeOnDate(now, candidate.upstream.departureTime ?? candidate.upstream.arrivalTime);
      final downstreamArrival = parseTimeOnDate(now, candidate.downstream.arrivalTime ?? candidate.downstream.departureTime);
      if (upstreamDeparture == null || downstreamArrival == null || !downstreamArrival.isAfter(upstreamDeparture)) {
        continue;
      }
      final timing = _estimatePredictionTiming(
        crossing,
        trainNo: timetable.trainNo,
        trainTypeName: timetable.trainTypeName ?? context.liveboard.trainTypeName,
        upstreamStationId: candidate.upstream.stationId,
        downstreamStationId: candidate.downstream.stationId,
        upstream: candidate.upstream,
        downstream: candidate.downstream,
        upstreamDeparture: upstreamDeparture,
        downstreamArrival: downstreamArrival,
        delaySeconds: context.delayEstimate.seconds,
        delaySource: context.delayEstimate.source,
        direction: candidate.direction,
        stationLookupById: stationLookupById,
        calibrationRules: calibrationRules,
        dataBasis: 'liveboard',
        liveboard: context.liveboard,
      );
      if (timing == null || !_isPredictionInWindow(timing.eta, now, horizonMinutes, recentMinutes)) {
        continue;
      }
      predictions.add(_buildRecord(crossing, timetable, candidate, timing, warningMinutes, hasLiveboard: true, delay: context.delayEstimate, liveboard: context.liveboard, observedRatio: context.observedRatio, projectionReason: context.projectionReason));
    }
    return _LivePredictionBuildResult(predictions: predictions, fallbackReasons: fallbackReasons, fallbackDelays: fallbackDelays, fallbackLiveboards: fallbackLiveboards);
  }

  PredictionRecord _buildRecord(Crossing crossing, TrainTimetable timetable, PreparedTimetableCandidate candidate, _TimingEstimate timing, int warningMinutes, {required bool hasLiveboard, required DelayEstimate delay, required TrainLiveBoard? liveboard, double? observedRatio, String? projectionReason, String? fallbackReason}) {
    final now = DateTime.now();
    final predictionMethod = hasLiveboard
        ? timing.anchorTimeSource != null
              ? 'liveboard-anchor+travel-profile${timing.calibrationOffsetSeconds == 0 ? '' : '+calibrated'}'
              : 'liveboard-delay+travel-profile${timing.calibrationOffsetSeconds == 0 ? '' : '+calibrated'}'
        : delay.source == 'train_info'
        ? 'travel-profile+delay-segment${timing.calibrationOffsetSeconds == 0 ? '' : '+calibrated'}'
        : 'travel-profile${timing.calibrationOffsetSeconds == 0 ? '' : '+calibrated'}';
    final delayReason = delay.reason;
    final baseReason = hasLiveboard
        ? observedRatio == null
              ? 'Used TrainLiveBoard delay correction at a timetable stop.'
              : projectionReason ?? 'Projected a liveboard station observation onto the active OSM stop-pair.'
        : delay.source == 'liveboard'
        ? 'Used timetable with liveboard delay fallback.'
        : delay.source == 'train_info'
        ? 'Used timetable with train-info delay fallback.'
        : 'Used timetable without runtime delay evidence.';
    final reasonDetails = [fallbackReason, delayReason].whereType<String>().where((value) => value.trim().isNotEmpty).join(' ');
    return PredictionRecord(
      trainNo: timetable.trainNo,
      trainType: timetable.trainTypeName ?? liveboard?.trainTypeName,
      direction: candidate.direction,
      headsign: timetable.headsign,
      originStationId: timetable.originStationId,
      originStationName: timetable.originStationName,
      destinationStationId: timetable.destinationStationId,
      destinationStationName: timetable.destinationStationName,
      sourceStationId: liveboard?.stationId ?? candidate.upstream.stationId,
      sourceStationName: liveboard?.stationName ?? candidate.upstream.stationName,
      previousStopStationId: candidate.upstream.stationId,
      previousStopStationName: candidate.upstream.stationName,
      previousStopDeparture: timing.actualUpstream,
      nextStopStationId: candidate.downstream.stationId,
      nextStopStationName: candidate.downstream.stationName,
      nextStopArrival: timing.actualDownstream,
      upstreamStationId: candidate.upstream.stationId,
      upstreamStationName: candidate.upstream.stationName,
      downstreamStationId: candidate.downstream.stationId,
      downstreamStationName: candidate.downstream.stationName,
      eta: timing.eta,
      warning: !timing.eta.isAfter(now.add(Duration(minutes: warningMinutes))),
      warningWindowMinutes: warningMinutes,
      confidence: _predictionConfidence(crossing.geolocationConfidence, timing.segmentConfidence, hasLiveboard: hasLiveboard),
      confidenceReason: 'Timing source: ${hasLiveboard ? 'liveboard' : 'timetable'}. Ratio source: ${timing.ratioSource}. ${timing.segmentNote}',
      delayMinutes: delay.minutes,
      delaySeconds: delay.seconds,
      delaySource: delay.source,
      dataBasis: hasLiveboard ? 'liveboard' : 'timetable',
      predictionMethod: predictionMethod,
      timingModel: timing.timingModel,
      anchorTimeSource: timing.anchorTimeSource,
      calibrationOffsetSeconds: timing.calibrationOffsetSeconds,
      etaUncertaintySeconds: timing.etaUncertaintySeconds,
      accuracyTier: timing.accuracyTier,
      reason: reasonDetails.isEmpty ? baseReason : '$baseReason $reasonDetails',
      ratioSource: timing.ratioSource,
      segmentConfidence: timing.segmentConfidence,
      segmentRatio: timing.ratio,
    );
  }

  _TimingEstimate? _estimatePredictionTiming(
    Crossing crossing, {
    required String trainNo,
    required String? trainTypeName,
    required String upstreamStationId,
    required String downstreamStationId,
    required StopTime upstream,
    required StopTime downstream,
    required DateTime upstreamDeparture,
    required DateTime downstreamArrival,
    required int delaySeconds,
    required String delaySource,
    required int direction,
    required Map<String, Station> stationLookupById,
    required List<CalibrationRule> calibrationRules,
    required String dataBasis,
    TrainLiveBoard? liveboard,
  }) {
    final context = _predictionSegmentContext(crossing, upstreamStationId, downstreamStationId);
    final ratio = context.ratio;
    if (ratio == null || !_isPredictionSegmentValid(crossing, upstreamStationId, downstreamStationId, ratio, context.source)) {
      return null;
    }
    final scheduledDuration = downstreamArrival.difference(upstreamDeparture);
    var actualUpstream = upstreamDeparture.add(Duration(seconds: delaySeconds));
    var actualDownstream = downstreamArrival.add(Duration(seconds: delaySeconds));
    final profile = travelProfileService.estimate(ratio: ratio, trainTypeName: trainTypeName, upstreamDwellSeconds: _stopDwellSeconds(upstream, upstreamDeparture), downstreamDwellSeconds: _stopDwellSeconds(downstream, downstreamArrival));
    var eta = actualUpstream.add(_scaleDuration(scheduledDuration, profile.timeFraction));
    var timingModel = 'travel_profile';
    String? anchorTimeSource;
    final anchor = _resolveLiveboardAnchorTime(liveboard, upstreamStationId, actualUpstream, actualDownstream);
    if (anchor != null) {
      actualUpstream = anchor;
      actualDownstream = anchor.add(scheduledDuration);
      eta = actualUpstream.add(_scaleDuration(scheduledDuration, profile.timeFraction));
      timingModel = 'liveboard_anchor_profile';
      anchorTimeSource = 'liveboard_update';
    }
    final calibration = _lookupOffsetSeconds(calibrationRules, crossingId: crossing.id, direction: direction, trainTypeName: trainTypeName, upstreamStationId: upstreamStationId);
    if (calibration != 0) {
      eta = eta.add(Duration(seconds: calibration));
      timingModel = '$timingModel+calibrated';
    }
    final uncertainty = _estimateUncertaintySeconds(baseUncertaintySeconds: profile.baseUncertaintySeconds, segmentConfidence: context.confidence, dataBasis: dataBasis, delaySource: delaySource, anchorTimeSource: anchorTimeSource, calibrated: calibration != 0);
    return _TimingEstimate(eta: eta, ratio: ratio, ratioSource: context.source, segmentConfidence: context.confidence, segmentNote: context.note, actualUpstream: actualUpstream, actualDownstream: actualDownstream, timingModel: timingModel, anchorTimeSource: anchorTimeSource, calibrationOffsetSeconds: calibration, etaUncertaintySeconds: uncertainty, accuracyTier: _accuracyTierFromUncertainty(uncertainty), profile: profile);
  }

  _SegmentContext _predictionSegmentContext(Crossing crossing, String upstreamStationId, String downstreamStationId) {
    final stationAId = crossing.stationA.id;
    final stationBId = crossing.stationB.id;
    if (crossing.segmentRatio != null && crossing.ratioSource == 'osm_path' && upstreamStationId == stationAId && downstreamStationId == stationBId) {
      return _SegmentContext(ratio: crossing.segmentRatio, source: 'osm_path', confidence: crossing.segmentConfidence ?? 'high', note: crossing.segmentConfidenceReason ?? 'OSM runtime segment.');
    }
    if (crossing.segmentRatio != null && crossing.ratioSource == 'osm_path' && upstreamStationId == stationBId && downstreamStationId == stationAId) {
      return _SegmentContext(ratio: 1.0 - crossing.segmentRatio!, source: 'osm_path', confidence: crossing.segmentConfidence ?? 'high', note: 'Reverse direction OSM runtime segment.');
    }
    final ratio = crossing.runtimeRatios['$upstreamStationId|$downstreamStationId'];
    if (ratio != null && ratio.source == 'osm_path') {
      return _SegmentContext(ratio: ratio.ratio, source: ratio.source, confidence: ratio.confidence, note: ratio.note ?? 'Precomputed OSM stop-pair ratio.');
    }
    return const _SegmentContext(ratio: null, source: 'unavailable', confidence: 'low', note: 'No OSM ratio for this stop pair.');
  }

  bool _isPredictionSegmentValid(Crossing crossing, String upstreamStationId, String downstreamStationId, double ratio, String ratioSource) {
    final stationAId = crossing.stationA.id;
    final stationBId = crossing.stationB.id;
    if ((upstreamStationId == stationAId && downstreamStationId == stationBId) || (upstreamStationId == stationBId && downstreamStationId == stationAId)) {
      return true;
    }
    return ratioSource == 'osm_path' && ratio > 0.0 && ratio < 1.0;
  }

  _LiveSelection _selectLiveboardCandidateContext(Crossing crossing, List<TrainLiveBoard> liveboards, List<PreparedTimetableCandidate> candidates, Map<String, TrainInfo> trainInfoByNo, Map<String, StationPairProjection> stationPairProjections, Map<String, StationPairProjectionRejection> stationPairProjectionRejections, DateTime referenceDate) {
    _LiveContext? best;
    (int, int, int, int)? bestScore;
    String? fallbackReason;
    (int, int, int, int)? fallbackScore;
    for (final liveboard in liveboards) {
      for (final candidate in candidates) {
        final observedIndex = _findTimetableStopIndex(candidate.timetable.stopTimes, liveboard.stationId, candidate);
        StopTime? observedStop;
        double? observedRatio;
        String? projectionReason;
        late DelayEstimate delay;
        late int phaseRank;
        late int stopGap;
        final pairSpan = math.max(candidate.downstreamIndex - candidate.upstreamIndex, 0);
        final liveRank = -(liveboard.updateTime?.millisecondsSinceEpoch ?? 0);
        if (observedIndex == null) {
          final projection = _projectLiveboardStationRatio(liveboard, candidate, stationPairProjections, stationPairProjectionRejections);
          final failureScore = (1, 0, pairSpan, liveRank);
          if (projection.ratio == null) {
            if (fallbackScore == null || _compareScore(failureScore, fallbackScore) < 0) {
              fallbackScore = failureScore;
              fallbackReason = projection.reason;
            }
            continue;
          }
          final projectedRatio = projection.ratio!;
          observedRatio = projectedRatio;
          final crossingRatio = _predictionSegmentContext(crossing, candidate.upstream.stationId, candidate.downstream.stationId).ratio;
          if (crossingRatio == null) {
            if (fallbackScore == null || _compareScore(failureScore, fallbackScore) < 0) {
              fallbackScore = failureScore;
              fallbackReason = _formatLiveboardFallbackReason(liveboard, candidate, 'No OSM stop-pair ratio is available for this station pair.');
            }
            continue;
          }
          if (projectedRatio >= crossingRatio) {
            if (fallbackScore == null || _compareScore(failureScore, fallbackScore) < 0) {
              fallbackScore = failureScore;
              fallbackReason = _formatLiveboardFallbackReason(liveboard, candidate, 'The projected station lies beyond the crossing on this stop pair.');
            }
            continue;
          }
          projectionReason = projection.reason;
          delay = _resolveProjectedLiveboardDelayEstimate(candidate, liveboard, projectedRatio, trainInfoByNo, referenceDate);
          phaseRank = 1;
          stopGap = 0;
        } else {
          observedStop = candidate.timetable.stopTimes[observedIndex];
          delay = _resolveLiveboardDelayEstimate(candidate.timetable.trainNo, liveboard, observedStop, trainInfoByNo, referenceDate);
          phaseRank = observedIndex == candidate.upstreamIndex ? 0 : 2;
          stopGap = math.max(candidate.upstreamIndex - observedIndex, 0);
        }
        final score = (phaseRank, stopGap, pairSpan, liveRank);
        if (bestScore == null || _compareScore(score, bestScore) < 0) {
          bestScore = score;
          best = _LiveContext(candidate: candidate, liveboard: liveboard, observedStop: observedStop, observedIndex: observedIndex, observedRatio: observedRatio, delayEstimate: delay, projectionReason: projectionReason);
        }
      }
    }
    return _LiveSelection(context: best, fallbackReason: best == null ? fallbackReason : null);
  }

  _StationProjectionResolution _projectLiveboardStationRatio(TrainLiveBoard liveboard, PreparedTimetableCandidate candidate, Map<String, StationPairProjection> stationPairProjections, Map<String, StationPairProjectionRejection> stationPairProjectionRejections) {
    final key = '${liveboard.stationId}|${candidate.upstream.stationId}|${candidate.downstream.stationId}';
    final projection = stationPairProjections[key];
    final stationLabel = liveboard.stationName ?? liveboard.stationId;
    final pairLabel = '${candidate.upstream.stationName}-${candidate.downstream.stationName}';
    if (projection != null) {
      if (projection.source != 'osm_path') {
        return _StationProjectionResolution(reason: '$stationLabel could not use the exported projection for $pairLabel: ${projection.note ?? 'projection source is not OSM-backed.'}');
      }
      if (projection.ratio <= 0.0 || projection.ratio >= 1.0) {
        return _StationProjectionResolution(reason: '$stationLabel could not use the exported projection for $pairLabel: ${projection.note ?? 'projection ratio is outside the usable range.'}');
      }
      return _StationProjectionResolution(ratio: projection.ratio, reason: 'Projected $stationLabel onto $pairLabel via the mobile OSM stop-pair map.');
    }
    final rejection = stationPairProjectionRejections[key];
    return _StationProjectionResolution(reason: _formatLiveboardFallbackReason(liveboard, candidate, rejection?.note ?? 'No usable station-pair projection was exported for this liveboard station.'));
  }

  String _formatLiveboardFallbackReason(TrainLiveBoard liveboard, PreparedTimetableCandidate candidate, String detail) {
    final stationLabel = liveboard.stationName ?? liveboard.stationId;
    return '$stationLabel could not be projected onto ${candidate.upstream.stationName}-${candidate.downstream.stationName}: $detail';
  }

  int? _findTimetableStopIndex(List<StopTime> stops, String stationId, PreparedTimetableCandidate candidate) {
    final indexes = <int>[];
    for (var i = 0; i < stops.length; i++) {
      if (stops[i].stationId == stationId && i < candidate.downstreamIndex) {
        indexes.add(i);
      }
    }
    if (indexes.isEmpty) return null;
    indexes.sort((a, b) {
      final rankA = a <= candidate.upstreamIndex ? 0 : 1;
      final rankB = b <= candidate.upstreamIndex ? 0 : 1;
      if (rankA != rankB) return rankA.compareTo(rankB);
      return (candidate.upstreamIndex - a).abs().compareTo((candidate.upstreamIndex - b).abs());
    });
    return indexes.first;
  }

  DelayEstimate _resolveLiveboardDelayEstimate(String trainNo, TrainLiveBoard liveboard, StopTime observedStop, Map<String, TrainInfo> trainInfoByNo, DateTime referenceDate) {
    final scheduled = parseTimeOnDate(referenceDate, observedStop.departureTime ?? observedStop.arrivalTime);
    final observedAt = liveboard.updateTime;
    if (scheduled != null && observedAt != null) {
      final delta = observedAt.difference(scheduled).inSeconds;
      if (delta >= -300 && delta <= 7200) {
        return DelayEstimate(seconds: delta, minutes: (delta / 60).round(), source: 'liveboard', reason: 'Accepted the liveboard update-time delta against the matched timetable stop.');
      }
    }
    if (liveboard.delayTime != null) {
      return DelayEstimate(seconds: liveboard.delayTime! * 60, minutes: liveboard.delayTime!, source: 'liveboard', reason: 'Accepted the train-level TrainLiveBoard DelayTime because the stop-time delta was outside the usable window.');
    }
    final info = trainInfoByNo[trainNo];
    if (info?.delayTime != null) {
      return DelayEstimate(seconds: info!.delayTime! * 60, minutes: info.delayTime!, source: 'train_info', reason: 'Fell back to TrainInfo DelayTime because TrainLiveBoard did not provide a usable delay signal.');
    }
    return const DelayEstimate(seconds: 0, minutes: 0, source: 'none', reason: 'No usable TrainLiveBoard or TrainInfo delay signal was available for this matched station context.');
  }

  DelayEstimate _resolveProjectedLiveboardDelayEstimate(PreparedTimetableCandidate candidate, TrainLiveBoard liveboard, double observedRatio, Map<String, TrainInfo> trainInfoByNo, DateTime referenceDate) {
    final upstreamDeparture = parseTimeOnDate(referenceDate, candidate.upstream.departureTime ?? candidate.upstream.arrivalTime);
    final downstreamArrival = parseTimeOnDate(referenceDate, candidate.downstream.arrivalTime ?? candidate.downstream.departureTime);
    final observedAt = liveboard.updateTime;
    if (upstreamDeparture != null && downstreamArrival != null && observedAt != null && downstreamArrival.isAfter(upstreamDeparture)) {
      final profile = travelProfileService.estimate(ratio: observedRatio, trainTypeName: candidate.timetable.trainTypeName ?? liveboard.trainTypeName, upstreamDwellSeconds: _stopDwellSeconds(candidate.upstream, referenceDate), downstreamDwellSeconds: _stopDwellSeconds(candidate.downstream, referenceDate));
      final scheduledObserved = upstreamDeparture.add(_scaleDuration(downstreamArrival.difference(upstreamDeparture), profile.timeFraction));
      final delta = observedAt.difference(scheduledObserved).inSeconds;
      if (delta >= -300 && delta <= 7200) {
        return DelayEstimate(seconds: delta, minutes: (delta / 60).round(), source: 'liveboard', reason: 'Accepted the projected TrainLiveBoard update-time delta on the active OSM stop-pair.');
      }
    }
    return _resolveLiveboardDelayEstimate(candidate.timetable.trainNo, liveboard, candidate.upstream, trainInfoByNo, referenceDate);
  }

  DelayEstimate _resolveDelayMinutes(String trainNo, {Map<String, TrainInfo>? trainInfoByNo}) {
    final info = trainInfoByNo?[trainNo];
    if (info?.delayTime != null) {
      return DelayEstimate(seconds: info!.delayTime! * 60, minutes: info.delayTime!, source: 'train_info', reason: 'Used TrainInfo DelayTime because no liveboard evidence was selected for this train.');
    }
    return const DelayEstimate(seconds: 0, minutes: 0, source: 'none', reason: 'No liveboard or train-info delay evidence was available for this train.');
  }

  (DelayEstimate, TrainLiveBoard)? _resolveLiveboardDelayFallback(List<TrainLiveBoard> liveboards) {
    for (final liveboard in liveboards) {
      if (liveboard.delayTime == null) continue;
      return (DelayEstimate(seconds: liveboard.delayTime! * 60, minutes: liveboard.delayTime!, source: 'liveboard', reason: 'Used TrainLiveBoard DelayTime even though no crossing-valid liveboard station context was available.'), liveboard);
    }
    return null;
  }

  Map<String, List<TrainLiveBoard>> _buildLiveboardIndex(List<TrainLiveBoard> liveboards) {
    final selected = <String, TrainLiveBoard>{};
    for (final liveboard in liveboards) {
      final key = '${liveboard.trainNo}|${liveboard.stationId}';
      final current = selected[key];
      if (current == null || (liveboard.updateTime?.millisecondsSinceEpoch ?? -1) >= (current.updateTime?.millisecondsSinceEpoch ?? -1)) {
        selected[key] = liveboard;
      }
    }
    final index = <String, List<TrainLiveBoard>>{};
    for (final liveboard in selected.values) {
      index.putIfAbsent(liveboard.trainNo, () => []).add(liveboard);
    }
    for (final records in index.values) {
      records.sort((a, b) => (b.updateTime?.millisecondsSinceEpoch ?? -1).compareTo(a.updateTime?.millisecondsSinceEpoch ?? -1));
    }
    return index;
  }

  (StopTime, StopTime, int)? _resolveSingleAnchorStopPair(List<StopTime> stops, {required StopTime anchorStop, required String anchorStationId, required String targetStationId, required Map<String, Station> stationLookupById, required String anchorRole, required int? trainDirection}) {
    final anchorIndex = stops.indexOf(anchorStop);
    if (anchorIndex < 0) return null;
    final indexes = [anchorIndex - 1, anchorIndex + 1].where((index) => index >= 0 && index < stops.length).toList();
    final bestIndex = _pickNeighborTowardTarget(stops, anchorStationId, targetStationId, indexes, stationLookupById);
    if (bestIndex == null) return null;
    final candidate = stops[bestIndex];
    if (bestIndex < anchorIndex) {
      return (candidate, anchorStop, trainDirection ?? (anchorRole == 'b' ? 0 : 1));
    }
    return (anchorStop, candidate, trainDirection ?? (anchorRole == 'a' ? 0 : 1));
  }

  int? _pickNeighborTowardTarget(List<StopTime> stops, String anchorStationId, String targetStationId, List<int> candidateIndexes, Map<String, Station> stationLookupById) {
    final anchor = stationLookupById[anchorStationId]?.position;
    final target = stationLookupById[targetStationId]?.position;
    if (anchor == null || target == null) {
      return candidateIndexes.length == 1 ? candidateIndexes.first : null;
    }
    final anchorDistance = _distanceSq(anchor, target);
    final scored = <(int, double, double, int)>[];
    for (final index in candidateIndexes) {
      final candidate = stationLookupById[stops[index].stationId]?.position;
      if (candidate == null) continue;
      final distance = _distanceSq(candidate, target);
      final progress = anchorDistance - distance;
      final alignment = _alignment(anchor, target, candidate);
      if (alignment <= 0) continue;
      scored.add((progress > 0 ? 0 : 1, distance, -alignment, index));
    }
    if (scored.isEmpty) return null;
    scored.sort((a, b) {
      final first = a.$1.compareTo(b.$1);
      if (first != 0) return first;
      final second = a.$2.compareTo(b.$2);
      if (second != 0) return second;
      return a.$3.compareTo(b.$3);
    });
    return scored.first.$4;
  }

  double _distanceSq(GeoPoint a, GeoPoint b) => math.pow(a.lat - b.lat, 2).toDouble() + math.pow(a.lon - b.lon, 2).toDouble();

  double _alignment(GeoPoint anchor, GeoPoint target, GeoPoint candidate) {
    final targetVector = (target.lat - anchor.lat, target.lon - anchor.lon);
    final candidateVector = (candidate.lat - anchor.lat, candidate.lon - anchor.lon);
    return targetVector.$1 * candidateVector.$1 + targetVector.$2 * candidateVector.$2;
  }

  DateTime? parseTimeOnDate(DateTime date, String? timeText) {
    if (timeText == null || timeText.trim().isEmpty) return null;
    final parts = timeText.split(':');
    if (parts.length < 2) return null;
    final hour = int.tryParse(parts[0]);
    final minute = int.tryParse(parts[1]);
    final second = parts.length >= 3 ? int.tryParse(parts[2]) ?? 0 : 0;
    if (hour == null || minute == null) return null;
    return DateTime(date.year, date.month, date.day, hour, minute, second);
  }

  Duration _scaleDuration(Duration duration, double fraction) => Duration(microseconds: (duration.inMicroseconds * fraction).round());

  int _stopDwellSeconds(StopTime stop, DateTime referenceDate) {
    final arrival = parseTimeOnDate(referenceDate, stop.arrivalTime);
    final departure = parseTimeOnDate(referenceDate, stop.departureTime);
    if (arrival == null || departure == null) return 0;
    return math.max(departure.difference(arrival).inSeconds, 0);
  }

  DateTime? _resolveLiveboardAnchorTime(TrainLiveBoard? liveboard, String upstreamStationId, DateTime scheduledUpstream, DateTime scheduledDownstream) {
    if (liveboard == null || liveboard.stationId != upstreamStationId || liveboard.updateTime == null) {
      return null;
    }
    final parsed = liveboard.updateTime!;
    if (parsed.isBefore(scheduledUpstream.subtract(const Duration(minutes: 5))) || parsed.isAfter(scheduledDownstream.add(const Duration(minutes: 10)))) {
      return null;
    }
    return parsed.isBefore(scheduledUpstream) ? scheduledUpstream : parsed;
  }

  int _lookupOffsetSeconds(List<CalibrationRule> rules, {required String crossingId, required int direction, required String? trainTypeName, required String upstreamStationId}) {
    final family = travelProfileService.classifyTrainTypeFamily(trainTypeName);
    for (final rule in rules) {
      final match = rule.match;
      if (match['crossing_id'] != null && match['crossing_id'] != crossingId) {
        continue;
      }
      if (match['direction'] != null && intValue(match['direction']) != direction) {
        continue;
      }
      if (match['train_type_family'] != null && match['train_type_family'] != family) {
        continue;
      }
      if (match['upstream_station_id'] != null && match['upstream_station_id'] != upstreamStationId) {
        continue;
      }
      return rule.offsetSeconds;
    }
    return 0;
  }

  int _estimateUncertaintySeconds({required int baseUncertaintySeconds, required String segmentConfidence, required String dataBasis, required String delaySource, required String? anchorTimeSource, required bool calibrated}) {
    var uncertainty = math.max(baseUncertaintySeconds, 15);
    if (dataBasis == 'timetable') uncertainty += 25;
    if (delaySource == 'train_info' || delaySource == 'none') {
      uncertainty += 18;
    } else if (delaySource == 'liveboard') {
      uncertainty += 4;
    }
    if (anchorTimeSource != null) uncertainty = math.max(18, uncertainty - 15);
    if (calibrated) uncertainty = math.max(18, uncertainty - 6);
    if (segmentConfidence == 'medium') {
      uncertainty += 20;
    } else if (segmentConfidence != 'high') {
      uncertainty += 40;
    }
    return uncertainty;
  }

  String _accuracyTierFromUncertainty(int seconds) {
    if (seconds <= 35) return 'high';
    if (seconds <= 80) return 'medium';
    return 'low';
  }

  String _predictionConfidence(String? geoConfidence, String? segmentConfidence, {required bool hasLiveboard}) {
    final rank = math.min(_confidenceRank(geoConfidence), _confidenceRank(segmentConfidence ?? geoConfidence));
    if (rank >= 3 && hasLiveboard) return 'high';
    if (rank >= 2) return 'medium';
    return 'low';
  }

  int _confidenceRank(String? value) => value == 'high'
      ? 3
      : value == 'medium'
      ? 2
      : 1;

  bool _isPredictionInWindow(DateTime eta, DateTime now, int? horizonMinutes, int recentMinutes) {
    if (eta.isBefore(now.subtract(Duration(minutes: recentMinutes)))) {
      return false;
    }
    if (horizonMinutes == null) return true;
    return !eta.isAfter(now.add(Duration(minutes: horizonMinutes)));
  }

  (PredictionRecord?, List<PredictionRecord>, List<PredictionRecord>) _partitionPredictions(List<PredictionRecord> predictions, DateTime now, int recentMinutes) {
    PredictionRecord? recent;
    final upcoming = <PredictionRecord>[];
    final recentAndUpcoming = <PredictionRecord>[];
    final cutoff = now.subtract(Duration(minutes: recentMinutes));
    for (final prediction in predictions) {
      if (!prediction.eta.isBefore(now)) {
        upcoming.add(prediction);
        recentAndUpcoming.add(prediction);
      } else if (!prediction.eta.isBefore(cutoff)) {
        recent = prediction;
        // For UI: include recent in the full list
        recentAndUpcoming.add(prediction);
      }
    }
    return (recent, upcoming.take(2).toList(growable: false), recentAndUpcoming);
  }

  List<PredictionRecord> _mergePredictions(List<PredictionRecord> livePredictions, List<PredictionRecord> timetablePredictions) {
    final liveKeys = livePredictions.map((record) => record.identityKey).toSet();
    return [...livePredictions, ...timetablePredictions.where((record) => !liveKeys.contains(record.identityKey))];
  }

  List<PredictionRecord> _dedupePredictions(List<PredictionRecord> predictions) {
    final selected = <String, PredictionRecord>{};
    for (final prediction in predictions) {
      final current = selected[prediction.identityKey];
      if (current == null || _predictionPreference(prediction).compareTo(_predictionPreference(current)) < 0) {
        selected[prediction.identityKey] = prediction;
      }
    }
    final values = selected.values.toList(growable: false);
    values.sort((a, b) {
      final eta = a.eta.compareTo(b.eta);
      if (eta != 0) return eta;
      final basis = (a.dataBasis == 'liveboard' ? 0 : 1).compareTo(b.dataBasis == 'liveboard' ? 0 : 1);
      if (basis != 0) return basis;
      return a.trainNo.compareTo(b.trainNo);
    });
    return values;
  }

  (int, int, int, int) _predictionPreference(PredictionRecord prediction) {
    final basisRank = prediction.dataBasis == 'liveboard' ? 0 : 1;
    final sourceRank = prediction.sourceStationId == prediction.upstreamStationId || prediction.sourceStationId == prediction.downstreamStationId ? 0 : 1;
    final anchorRank = prediction.anchorTimeSource == null ? 1 : 0;
    final delayRank = prediction.delaySource == 'liveboard'
        ? 0
        : prediction.delaySource == 'train_info'
        ? 1
        : 2;
    return (basisRank, sourceRank, anchorRank, delayRank);
  }

  (int, int, int) _candidateScore(PreparedTimetableCandidate candidate, String stationAId, String stationBId) {
    final pairIds = {candidate.upstream.stationId, candidate.downstream.stationId};
    final anchorIds = {stationAId, stationBId};
    final exact = pairIds.length == anchorIds.length && pairIds.containsAll(anchorIds) ? 1 : 0;
    final anchors = (anchorIds.contains(candidate.upstream.stationId) ? 1 : 0) + (anchorIds.contains(candidate.downstream.stationId) ? 1 : 0);
    final gap = (candidate.downstream.stopSequence - candidate.upstream.stopSequence).abs();
    return (exact, anchors, -gap);
  }

  int _compareScore((int, int, int, int) a, (int, int, int, int) b) {
    final first = a.$1.compareTo(b.$1);
    if (first != 0) return first;
    final second = a.$2.compareTo(b.$2);
    if (second != 0) return second;
    final third = a.$3.compareTo(b.$3);
    if (third != 0) return third;
    return a.$4.compareTo(b.$4);
  }

  PredictionDataSnapshot _snapshotWithTiming(PredictionDataSnapshot snapshot, String key, int elapsedMs) {
    return PredictionDataSnapshot(comprehensive: snapshot.comprehensive, liveboardCount: snapshot.liveboardCount, delayedLiveboardCount: snapshot.delayedLiveboardCount, timetableCount: snapshot.timetableCount, trainInfoCount: snapshot.trainInfoCount, delayedTrainInfoCount: snapshot.delayedTrainInfoCount, liveboardScope: snapshot.liveboardScope, sources: snapshot.sources, timingsMs: {...snapshot.timingsMs, key: elapsedMs});
  }

  PredictionEnvelope _unavailable(Crossing crossing, DateTime now, int warningMinutes, int? horizonMinutes, int recentMinutes, String reason, String detail, {PredictionDataSnapshot? dataSnapshot}) {
    return PredictionEnvelope(crossingId: crossing.id, generatedAt: now, warningWindowMinutes: warningMinutes, horizonMinutes: horizonMinutes, recentWindowMinutes: recentMinutes, available: false, unavailableReason: reason, unavailableDetail: detail, dataSnapshot: dataSnapshot);
  }
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}

extension _RecordComparable on (int, int, int, int) {
  int compareTo((int, int, int, int) other) {
    final first = $1.compareTo(other.$1);
    if (first != 0) return first;
    final second = $2.compareTo(other.$2);
    if (second != 0) return second;
    final third = $3.compareTo(other.$3);
    if (third != 0) return third;
    return $4.compareTo(other.$4);
  }
}

extension _TripleRecordComparable on (int, int, int) {
  int compareTo((int, int, int) other) {
    final first = $1.compareTo(other.$1);
    if (first != 0) return first;
    final second = $2.compareTo(other.$2);
    if (second != 0) return second;
    return $3.compareTo(other.$3);
  }
}

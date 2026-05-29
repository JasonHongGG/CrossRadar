import 'dart:math' as math;

class TravelProfile {
  const TravelProfile(
    this.profileId,
    this.accelTimeFraction,
    this.decelTimeFraction,
    this.baseUncertaintySeconds,
  );

  final String profileId;
  final double accelTimeFraction;
  final double decelTimeFraction;
  final int baseUncertaintySeconds;
}

class TravelProfileEstimate {
  const TravelProfileEstimate({
    required this.profileId,
    required this.trainTypeFamily,
    required this.timeFraction,
    required this.baseUncertaintySeconds,
  });

  final String profileId;
  final String trainTypeFamily;
  final double timeFraction;
  final int baseUncertaintySeconds;
}

const Map<String, TravelProfile> _profiles = {
  'local|from_stop|to_stop': TravelProfile('local-stop-stop', 0.18, 0.16, 45),
  'local|from_stop|through': TravelProfile(
    'local-stop-through',
    0.16,
    0.05,
    40,
  ),
  'local|through|to_stop': TravelProfile('local-through-stop', 0.05, 0.16, 40),
  'local|through|through': TravelProfile(
    'local-through-through',
    0.03,
    0.03,
    35,
  ),
  'local_fast|from_stop|to_stop': TravelProfile(
    'local-fast-stop-stop',
    0.15,
    0.14,
    42,
  ),
  'local_fast|from_stop|through': TravelProfile(
    'local-fast-stop-through',
    0.14,
    0.04,
    38,
  ),
  'local_fast|through|to_stop': TravelProfile(
    'local-fast-through-stop',
    0.04,
    0.14,
    38,
  ),
  'local_fast|through|through': TravelProfile(
    'local-fast-through-through',
    0.03,
    0.03,
    32,
  ),
  'puyuma|from_stop|to_stop': TravelProfile('puyuma-stop-stop', 0.10, 0.10, 36),
  'puyuma|from_stop|through': TravelProfile(
    'puyuma-stop-through',
    0.09,
    0.03,
    32,
  ),
  'puyuma|through|to_stop': TravelProfile(
    'puyuma-through-stop',
    0.03,
    0.09,
    32,
  ),
  'puyuma|through|through': TravelProfile(
    'puyuma-through-through',
    0.02,
    0.02,
    28,
  ),
  'express_3000|from_stop|to_stop': TravelProfile(
    'express3000-stop-stop',
    0.10,
    0.10,
    35,
  ),
  'express_3000|from_stop|through': TravelProfile(
    'express3000-stop-through',
    0.08,
    0.03,
    30,
  ),
  'express_3000|through|to_stop': TravelProfile(
    'express3000-through-stop',
    0.03,
    0.08,
    30,
  ),
  'express_3000|through|through': TravelProfile(
    'express3000-through-through',
    0.02,
    0.02,
    26,
  ),
  'express|from_stop|to_stop': TravelProfile(
    'express-stop-stop',
    0.11,
    0.11,
    38,
  ),
  'express|from_stop|through': TravelProfile(
    'express-stop-through',
    0.09,
    0.03,
    32,
  ),
  'express|through|to_stop': TravelProfile(
    'express-through-stop',
    0.03,
    0.09,
    32,
  ),
  'express|through|through': TravelProfile(
    'express-through-through',
    0.02,
    0.02,
    28,
  ),
  'default|from_stop|to_stop': TravelProfile(
    'default-stop-stop',
    0.12,
    0.12,
    45,
  ),
  'default|from_stop|through': TravelProfile(
    'default-stop-through',
    0.10,
    0.04,
    38,
  ),
  'default|through|to_stop': TravelProfile(
    'default-through-stop',
    0.04,
    0.10,
    38,
  ),
  'default|through|through': TravelProfile(
    'default-through-through',
    0.03,
    0.03,
    34,
  ),
};

class TravelProfileService {
  String classifyTrainTypeFamily(String? trainTypeName) {
    final value = trainTypeName ?? '';
    final normalized = value.trim().toLowerCase();
    if (value.contains('普悠瑪') || normalized.contains('puyuma')) return 'puyuma';
    if (value.contains('3000')) return 'express_3000';
    if (value.contains('區間快')) return 'local_fast';
    if (value.contains('區間')) return 'local';
    if (value.contains('自強') || value.contains('莒光') || value.contains('太魯閣')) {
      return 'express';
    }
    return 'default';
  }

  TravelProfileEstimate estimate({
    required double ratio,
    required String? trainTypeName,
    required int upstreamDwellSeconds,
    required int downstreamDwellSeconds,
  }) {
    ratio = ratio.clamp(0.0, 1.0);
    final family = classifyTrainTypeFamily(trainTypeName);
    final startState = upstreamDwellSeconds > 0 ? 'from_stop' : 'through';
    final endState = downstreamDwellSeconds > 0 ? 'to_stop' : 'through';
    final profile =
        _profiles['$family|$startState|$endState'] ??
        _profiles['default|$startState|$endState']!;
    return TravelProfileEstimate(
      profileId: profile.profileId,
      trainTypeFamily: family,
      timeFraction: timeFractionForRatio(ratio, profile),
      baseUncertaintySeconds: profile.baseUncertaintySeconds,
    );
  }

  double timeFractionForRatio(double ratio, TravelProfile profile) {
    ratio = ratio.clamp(0.0, 1.0);
    final accelTime = profile.accelTimeFraction.clamp(0.0, 0.45);
    final decelTime = profile.decelTimeFraction.clamp(0.0, 0.45);
    final cruiseTime = math.max(1.0 - accelTime - decelTime, 0.01);
    final peakSpeed = 1.0 / (cruiseTime + 0.5 * accelTime + 0.5 * decelTime);
    final accelDistance = 0.5 * accelTime * peakSpeed;
    final cruiseDistance = cruiseTime * peakSpeed;
    final decelDistance = 0.5 * decelTime * peakSpeed;

    if (ratio <= accelDistance && accelTime > 0) {
      return math.sqrt((2.0 * accelTime * ratio) / peakSpeed).clamp(0.0, 1.0);
    }
    if (ratio <= accelDistance + cruiseDistance) {
      final cruiseProgress = ratio - accelDistance;
      return (accelTime + cruiseProgress / peakSpeed).clamp(0.0, 1.0);
    }
    if (decelTime <= 0 || decelDistance <= 0) return 1.0;
    final remainingDistance = math.max(1.0 - ratio, 0.0);
    final remainingTime = math.sqrt(
      (2.0 * decelTime * remainingDistance) / peakSpeed,
    );
    return (1.0 - remainingTime).clamp(0.0, 1.0);
  }
}

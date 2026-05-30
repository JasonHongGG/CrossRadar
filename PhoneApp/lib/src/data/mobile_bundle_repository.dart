import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/models.dart';

final mobileBundleProvider = FutureProvider<MobileBundle>((ref) async {
  return MobileBundleRepository().load();
});

class MobileBundleRepository {
  const MobileBundleRepository({this.assetPath = 'assets/data/crossradar_mobile_bundle.json'});

  final String assetPath;

  Future<MobileBundle> load() async {
    final source = await rootBundle.loadString(assetPath);
    final bundle = MobileBundle.decode(source);
    if (bundle.crossings.isEmpty) {
      throw StateError('Mobile bundle contains no crossings.');
    }
    if (bundle.schemaVersion < 2) {
      throw StateError('Mobile bundle schema v2 or newer is required. Found v${bundle.schemaVersion}.');
    }
    if (bundle.schemaVersion >= 3) {
      final contract = bundle.predictionContract;
      if (contract['railway_time_zone'] != 'Asia/Taipei') {
        throw StateError('Mobile bundle prediction contract must declare Asia/Taipei railway time.');
      }
      final requiredSources = (contract['snapshot_required_sources'] as List? ?? const []).map((value) => value.toString()).toSet();
      if (!requiredSources.containsAll(const {'liveboards', 'timetables', 'train_info'})) {
        throw StateError('Mobile bundle prediction contract is missing required TDX snapshot sources.');
      }
    }
    final missingRuntime = bundle.crossings.where((crossing) => crossing.runtimeRatios.isEmpty).length;
    if (missingRuntime > 0) {
      throw StateError('Mobile bundle has $missingRuntime crossings without runtime ratios.');
    }
    return bundle;
  }
}

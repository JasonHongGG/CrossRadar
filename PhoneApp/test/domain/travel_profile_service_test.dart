import 'package:crossradar_phone/src/domain/travel_profile_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('classifies TRA train families', () {
    final service = TravelProfileService();

    expect(service.classifyTrainTypeFamily('區間'), 'local');
    expect(service.classifyTrainTypeFamily('區間快'), 'local_fast');
    expect(service.classifyTrainTypeFamily('普悠瑪'), 'puyuma');
    expect(service.classifyTrainTypeFamily('新自強3000'), 'express_3000');
  });

  test('biases stop-to-stop timing away from raw distance ratio', () {
    final service = TravelProfileService();

    final early = service.estimate(
      ratio: 0.2,
      trainTypeName: '區間',
      upstreamDwellSeconds: 30,
      downstreamDwellSeconds: 30,
    );
    final late = service.estimate(
      ratio: 0.8,
      trainTypeName: '區間',
      upstreamDwellSeconds: 30,
      downstreamDwellSeconds: 30,
    );

    expect(early.timeFraction, greaterThan(0.2));
    expect(late.timeFraction, lessThan(0.8));
  });
}

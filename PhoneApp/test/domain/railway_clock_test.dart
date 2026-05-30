import 'package:crossradar_phone/src/domain/railway_clock.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('uses Asia Taipei as the railway service clock', () {
    final clock = RailwayClock(utcNow: () => DateTime.utc(2026, 5, 28, 1, 30));

    expect(clock.serviceDateKey(), '2026-05-28');
    expect(clock.nowTaipei().hour, 9);
    expect(clock.nowTaipei().minute, 30);
  });

  test('parses timetable and TDX update text as Taipei railway time', () {
    final clock = RailwayClock.instance;
    final serviceDate = DateTime(2026, 5, 28);
    final scheduled = clock.parseTimetableTime(serviceDate, '10:04:05')!;
    final updateWithoutOffset = clock.parseTdxUpdateTime('2026-05-28T10:04:05')!;
    final updateWithUtcOffset = clock.parseTdxUpdateTime('2026-05-28T02:04:05Z')!;

    expect(clock.serviceDateKey(scheduled), '2026-05-28');
    expect(scheduled.hour, 10);
    expect(updateWithoutOffset.difference(scheduled).inSeconds, 0);
    expect(updateWithUtcOffset.difference(scheduled).inSeconds, 0);
  });
}

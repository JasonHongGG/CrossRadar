import 'package:timezone/data/latest.dart' as timezone_data;
import 'package:timezone/timezone.dart' as timezone;

class RailwayClock {
  RailwayClock({DateTime Function()? utcNow}) : _utcNow = utcNow;

  static final RailwayClock instance = RailwayClock();

  static bool _initialized = false;
  static late timezone.Location _taipei;

  final DateTime Function()? _utcNow;

  static timezone.Location get taipeiLocation {
    _ensureInitialized();
    return _taipei;
  }

  static void _ensureInitialized() {
    if (_initialized) return;
    timezone_data.initializeTimeZones();
    _taipei = timezone.getLocation('Asia/Taipei');
    _initialized = true;
  }

  DateTime nowTaipei() {
    final now = (_utcNow?.call() ?? DateTime.now()).toUtc();
    return timezone.TZDateTime.from(now, taipeiLocation);
  }

  DateTime normalizeTaipei(DateTime value) {
    if (value.isUtc) return timezone.TZDateTime.from(value, taipeiLocation);
    return timezone.TZDateTime(taipeiLocation, value.year, value.month, value.day, value.hour, value.minute, value.second, value.millisecond, value.microsecond);
  }

  DateTime? parseTimetableTime(DateTime serviceDate, String? timeText) {
    if (timeText == null || timeText.trim().isEmpty) return null;
    final parts = timeText.trim().split(':');
    if (parts.length < 2) return null;
    final hour = int.tryParse(parts[0]);
    final minute = int.tryParse(parts[1]);
    final second = parts.length >= 3 ? int.tryParse(parts[2]) ?? 0 : 0;
    if (hour == null || minute == null) return null;
    final reference = normalizeTaipei(serviceDate);
    return timezone.TZDateTime(taipeiLocation, reference.year, reference.month, reference.day, hour, minute, second);
  }

  DateTime? parseTdxUpdateTime(String? rawValue, {DateTime? defaultDate}) {
    final raw = rawValue?.trim();
    if (raw == null || raw.isEmpty) return null;
    final normalized = raw.replaceFirst(' ', 'T');
    final parsed = DateTime.tryParse(normalized.replaceFirst('Z', '+00:00'));
    if (parsed == null) return null;
    final hasExplicitOffset = RegExp(r'(Z|[+-]\d{2}:?\d{2})$').hasMatch(raw);
    if (hasExplicitOffset || parsed.isUtc) {
      return timezone.TZDateTime.from(parsed.toUtc(), taipeiLocation);
    }
    final reference = defaultDate == null ? null : normalizeTaipei(defaultDate);
    return timezone.TZDateTime(taipeiLocation, parsed.year == 0 ? reference?.year ?? parsed.year : parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute, parsed.second, parsed.millisecond, parsed.microsecond);
  }

  String serviceDateKey([DateTime? value]) {
    final taipei = value == null ? nowTaipei() : normalizeTaipei(value);
    final month = taipei.month.toString().padLeft(2, '0');
    final day = taipei.day.toString().padLeft(2, '0');
    return '${taipei.year}-$month-$day';
  }
}

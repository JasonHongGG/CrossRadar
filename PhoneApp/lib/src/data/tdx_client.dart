import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../domain/models.dart';
import '../domain/railway_clock.dart';
import 'credential_store.dart';

class _CacheEntry<T> {
  const _CacheEntry({required this.value, required this.expiresAt, required this.cachedAt});

  final T value;
  final DateTime expiresAt;
  final DateTime cachedAt;

  bool isValid(DateTime now) => now.isBefore(expiresAt);
}

class _PersistentRows {
  const _PersistentRows({required this.rows, required this.cachedAt, this.serviceDateKey});

  final List<Map<String, dynamic>> rows;
  final DateTime cachedAt;
  final String? serviceDateKey;
}

class TdxCollectionResult<T> {
  const TdxCollectionResult({required this.items, required this.fetchedFrom, required this.complete, this.cachedAt, this.timingMs = const {}});

  final List<T> items;
  final String fetchedFrom;
  final bool complete;
  final DateTime? cachedAt;
  final Map<String, int> timingMs;

  PredictionSnapshotSource toSnapshotSource({required String source, String? scope, bool Function(T item)? delayed}) {
    final delayedCount = delayed == null ? 0 : items.where(delayed).length;
    return PredictionSnapshotSource(source: source, complete: complete, recordCount: items.length, delayedRecordCount: delayedCount, fetchedFrom: fetchedFrom, cachedAt: cachedAt, scope: scope, timingBreakdown: timingMs);
  }
}

class TdxTraClient {
  TdxTraClient({Dio? dio, RailwayClock? railwayClock, this.basicBaseUrl = 'https://tdx.transportdata.tw/api/basic', this.tokenUrl = 'https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token'}) : _dio = dio ?? Dio(), railwayClock = railwayClock ?? RailwayClock.instance;

  final Dio _dio;
  final RailwayClock railwayClock;
  final String basicBaseUrl;
  final String tokenUrl;
  final Map<String, _CacheEntry<List<Map<String, dynamic>>>> _collectionCache = {};
  String? _accessToken;
  DateTime? _tokenExpiresAt;

  Future<List<TrainTimetable>> getTodayTimetables(TdxCredentials credentials, {bool forceRefresh = false}) async {
    return (await getTodayTimetablesSnapshot(credentials, forceRefresh: forceRefresh)).items;
  }

  Future<TdxCollectionResult<TrainTimetable>> getTodayTimetablesSnapshot(TdxCredentials credentials, {bool forceRefresh = false}) async {
    final serviceDateKey = railwayClock.serviceDateKey();
    final result = await _getCollection(credentials, cacheKey: 'today_timetables:$serviceDateKey', path: '/v3/Rail/TRA/DailyTrainTimetable/Today', collectionKey: 'TrainTimetables', ttl: const Duration(minutes: 30), forceRefresh: forceRefresh, persistentKey: 'today_timetables', serviceDateKey: serviceDateKey);
    return result.map((row) => TrainTimetable.fromJson(row)).where((item) => item.trainNo.isNotEmpty).toResult();
  }

  Future<List<TrainLiveBoard>> getLiveboards(TdxCredentials credentials, {bool forceRefresh = false}) async {
    return (await getLiveboardsSnapshot(credentials, forceRefresh: forceRefresh)).items;
  }

  Future<TdxCollectionResult<TrainLiveBoard>> getLiveboardsSnapshot(TdxCredentials credentials, {bool forceRefresh = false}) async {
    final result = await _getCollection(credentials, cacheKey: 'liveboards', path: '/v3/Rail/TRA/TrainLiveBoard', collectionKey: 'TrainLiveBoards', ttl: const Duration(seconds: 90), forceRefresh: forceRefresh);
    return result.map((row) => TrainLiveBoard.fromJson(row)).where((item) => item.trainNo.isNotEmpty && item.stationId.isNotEmpty).toResult();
  }

  Future<List<TrainInfo>> getTodayTrainInfos(TdxCredentials credentials, {bool forceRefresh = false}) async {
    return (await getTodayTrainInfosSnapshot(credentials, forceRefresh: forceRefresh)).items;
  }

  Future<TdxCollectionResult<TrainInfo>> getTodayTrainInfosSnapshot(TdxCredentials credentials, {bool forceRefresh = false}) async {
    final serviceDateKey = railwayClock.serviceDateKey();
    final result = await _getCollection(credentials, cacheKey: 'today_train_info:$serviceDateKey', path: '/v2/Rail/TRA/DailyTrainInfo/Today', collectionKey: 'TrainInfos', ttl: const Duration(minutes: 5), forceRefresh: forceRefresh, persistentKey: 'today_train_info', serviceDateKey: serviceDateKey);
    return result.map((row) => TrainInfo.fromJson(row)).where((item) => item.trainNo.isNotEmpty).toResult();
  }

  Future<TdxCollectionResult<Map<String, dynamic>>> _getCollection(TdxCredentials credentials, {required String cacheKey, required String path, required String collectionKey, required Duration ttl, required bool forceRefresh, String? persistentKey, String? serviceDateKey}) async {
    final now = DateTime.now().toUtc();
    final memory = _collectionCache[cacheKey];
    if (!forceRefresh && memory != null && memory.isValid(now)) {
      return TdxCollectionResult(items: memory.value, fetchedFrom: 'memory_cache', complete: true, cachedAt: memory.cachedAt, timingMs: const {'memory_cache': 0});
    }

    final persistent = await _readPersistentRows(persistentKey ?? cacheKey, serviceDateKey: serviceDateKey);
    if (!forceRefresh && persistent != null && now.difference(persistent.cachedAt.toUtc()) <= ttl) {
      _collectionCache[cacheKey] = _CacheEntry(value: persistent.rows, expiresAt: now.add(ttl), cachedAt: persistent.cachedAt);
      return TdxCollectionResult(items: persistent.rows, fetchedFrom: 'file_cache', complete: true, cachedAt: persistent.cachedAt, timingMs: const {'file_cache': 0});
    }

    final stopwatch = Stopwatch()..start();
    try {
      final response = await _authorizedGet(credentials, path, retryOnUnauthorized: true);
      final parseStarted = stopwatch.elapsedMilliseconds;
      final rows = _extractCollection(response.data, collectionKey);
      final cachedAt = DateTime.now().toUtc();
      _collectionCache[cacheKey] = _CacheEntry(value: rows, expiresAt: cachedAt.add(ttl), cachedAt: cachedAt);
      await _writePersistentRows(persistentKey ?? cacheKey, cachedAt, rows, serviceDateKey: serviceDateKey);
      return TdxCollectionResult(items: rows, fetchedFrom: 'api', complete: true, cachedAt: cachedAt, timingMs: {'network_fetch': parseStarted, 'network_parse': stopwatch.elapsedMilliseconds - parseStarted});
    } on DioException catch (error) {
      final fallback = _staleFallback(memory: memory, persistent: persistent, timingMs: {'network_error': stopwatch.elapsedMilliseconds, 'status': error.response?.statusCode ?? -1});
      if (fallback != null) return fallback;
      rethrow;
    }
  }

  Future<Response<Object?>> _authorizedGet(TdxCredentials credentials, String path, {required bool retryOnUnauthorized}) async {
    final token = await _getAccessToken(credentials);
    try {
      return await _dio.getUri(
        Uri.parse('$basicBaseUrl$path').replace(queryParameters: {'\$format': 'JSON'}),
        options: Options(headers: {'Authorization': 'Bearer $token'}, receiveTimeout: const Duration(seconds: 15), sendTimeout: const Duration(seconds: 15)),
      );
    } on DioException catch (error) {
      if (retryOnUnauthorized && error.response?.statusCode == 401) {
        final refreshed = await _getAccessToken(credentials, forceRefresh: true);
        return _dio.getUri(
          Uri.parse('$basicBaseUrl$path').replace(queryParameters: {'\$format': 'JSON'}),
          options: Options(headers: {'Authorization': 'Bearer $refreshed'}, receiveTimeout: const Duration(seconds: 15), sendTimeout: const Duration(seconds: 15)),
        );
      }
      rethrow;
    }
  }

  TdxCollectionResult<Map<String, dynamic>>? _staleFallback({required _CacheEntry<List<Map<String, dynamic>>>? memory, required _PersistentRows? persistent, required Map<String, int> timingMs}) {
    if (memory != null) {
      return TdxCollectionResult(items: memory.value, fetchedFrom: 'stale_memory_cache', complete: false, cachedAt: memory.cachedAt, timingMs: timingMs);
    }
    if (persistent != null) {
      return TdxCollectionResult(items: persistent.rows, fetchedFrom: 'stale_file_cache', complete: false, cachedAt: persistent.cachedAt, timingMs: timingMs);
    }
    return null;
  }

  List<Map<String, dynamic>> _extractCollection(Object? data, String collectionKey) {
    final raw = data is Map ? data[collectionKey] : data;
    if (raw is! List) return const [];
    return raw.map(mapValue).where((item) => item.isNotEmpty).toList(growable: false);
  }

  Future<_PersistentRows?> _readPersistentRows(String cacheKey, {String? serviceDateKey}) async {
    final preferences = await SharedPreferences.getInstance();
    final raw = preferences.getString('tdx_cache_$cacheKey');
    if (raw == null) return null;
    try {
      final payload = mapValue(jsonDecode(raw));
      final cachedAtText = textValue(payload['cached_at']);
      final cachedAt = cachedAtText == null ? null : DateTime.tryParse(cachedAtText);
      if (cachedAt == null) return null;
      final cachedServiceDateKey = textValue(payload['service_date']);
      if (serviceDateKey != null && cachedServiceDateKey != serviceDateKey) {
        return null;
      }
      return _PersistentRows(rows: mapList(payload['data']), cachedAt: cachedAt, serviceDateKey: cachedServiceDateKey);
    } on FormatException {
      return null;
    }
  }

  Future<void> _writePersistentRows(String cacheKey, DateTime cachedAt, List<Map<String, dynamic>> rows, {String? serviceDateKey}) async {
    final preferences = await SharedPreferences.getInstance();
    final payload = <String, Object?>{'cached_at': cachedAt.toUtc().toIso8601String(), 'data': rows};
    if (serviceDateKey != null) {
      payload['service_date'] = serviceDateKey;
    }
    await preferences.setString('tdx_cache_$cacheKey', jsonEncode(payload));
  }

  Future<String> _getAccessToken(TdxCredentials credentials, {bool forceRefresh = false}) async {
    final now = DateTime.now().toUtc();
    if (!forceRefresh && _accessToken != null && _tokenExpiresAt != null && now.add(const Duration(minutes: 5)).isBefore(_tokenExpiresAt!)) {
      return _accessToken!;
    }
    final response = await _dio.postUri(
      Uri.parse(tokenUrl),
      data: {'grant_type': 'client_credentials', 'client_id': credentials.clientId, 'client_secret': credentials.clientSecret},
      options: Options(contentType: Headers.formUrlEncodedContentType, receiveTimeout: const Duration(seconds: 15), sendTimeout: const Duration(seconds: 15)),
    );
    final data = mapValue(response.data);
    final token = textValue(data['access_token']);
    final expiresIn = intValue(data['expires_in']);
    if (token == null || expiresIn <= 0) {
      throw StateError('TDX token response is missing access_token.');
    }
    _accessToken = token;
    _tokenExpiresAt = now.add(Duration(seconds: expiresIn));
    return token;
  }
}

class _MappedTdxResult<T> {
  const _MappedTdxResult(this.source, this.items);

  final TdxCollectionResult<Map<String, dynamic>> source;
  final Iterable<T> items;

  _MappedTdxResult<T> where(bool Function(T item) test) => _MappedTdxResult(source, items.where(test));

  TdxCollectionResult<T> toResult() {
    return TdxCollectionResult<T>(items: items.toList(growable: false), fetchedFrom: source.fetchedFrom, complete: source.complete, cachedAt: source.cachedAt, timingMs: source.timingMs);
  }
}

extension _TdxCollectionMap on TdxCollectionResult<Map<String, dynamic>> {
  _MappedTdxResult<T> map<T>(T Function(Map<String, dynamic> row) convert) => _MappedTdxResult<T>(this, items.map(convert));
}

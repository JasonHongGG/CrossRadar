import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter/services.dart';

final credentialStoreProvider = Provider<TdxCredentialStore>((ref) => const TdxCredentialStore());

class TdxCredentials {
  const TdxCredentials({required this.clientId, required this.clientSecret});

  final String clientId;
  final String clientSecret;

  bool get isComplete => clientId.trim().isNotEmpty && clientSecret.trim().isNotEmpty;
}

enum TdxCredentialSource { saved, defaults, none }

class TdxCredentialResolution {
  const TdxCredentialResolution({required this.source, this.credentials});

  final TdxCredentialSource source;
  final TdxCredentials? credentials;
}

abstract class TdxCredentialStorage {
  Future<String?> read({required String key});
  Future<void> write({required String key, required String value});
  Future<void> delete({required String key});
}

class SecureTdxCredentialStorage implements TdxCredentialStorage {
  const SecureTdxCredentialStorage({FlutterSecureStorage storage = const FlutterSecureStorage()}) : _storage = storage;

  final FlutterSecureStorage _storage;

  @override
  Future<String?> read({required String key}) => _storage.read(key: key);

  @override
  Future<void> write({required String key, required String value}) => _storage.write(key: key, value: value);

  @override
  Future<void> delete({required String key}) => _storage.delete(key: key);
}

abstract class TdxCredentialDefaults {
  Future<TdxCredentials?> read();
}

class EnvironmentTdxCredentialDefaults implements TdxCredentialDefaults {
  const EnvironmentTdxCredentialDefaults();

  static const _envClientId = String.fromEnvironment('TDX_CLIENT_ID');
  static const _envClientSecret = String.fromEnvironment('TDX_CLIENT_SECRET');
  static const _assetPath = 'assets/config/default_credentials.json';

  @override
  Future<TdxCredentials?> read() async {
    final fromEnvironment = _credentialsOrNull(_envClientId, _envClientSecret);
    if (fromEnvironment != null) return fromEnvironment;
    try {
      final decoded = jsonDecode(await rootBundle.loadString(_assetPath));
      if (decoded is! Map) return null;
      return _credentialsOrNull(decoded['tdx_client_id']?.toString(), decoded['tdx_client_secret']?.toString());
    } catch (_) {
      return null;
    }
  }

  TdxCredentials? _credentialsOrNull(String? clientId, String? clientSecret) {
    final credentials = TdxCredentials(clientId: clientId ?? '', clientSecret: clientSecret ?? '');
    return credentials.isComplete ? credentials : null;
  }
}

class TdxCredentialStore {
  const TdxCredentialStore({TdxCredentialStorage storage = const SecureTdxCredentialStorage(), TdxCredentialDefaults defaults = const EnvironmentTdxCredentialDefaults()}) : _storage = storage, _defaults = defaults;

  static const _clientIdKey = 'tdx_client_id';
  static const _clientSecretKey = 'tdx_client_secret';

  final TdxCredentialStorage _storage;
  final TdxCredentialDefaults _defaults;

  Future<TdxCredentialResolution> resolve() async {
    final clientId = await _storage.read(key: _clientIdKey);
    final clientSecret = await _storage.read(key: _clientSecretKey);
    final credentials = TdxCredentials(clientId: clientId ?? '', clientSecret: clientSecret ?? '');
    if (credentials.isComplete) {
      return TdxCredentialResolution(source: TdxCredentialSource.saved, credentials: credentials);
    }
    final defaults = await _defaults.read();
    if (defaults != null) {
      return TdxCredentialResolution(source: TdxCredentialSource.defaults, credentials: defaults);
    }
    return const TdxCredentialResolution(source: TdxCredentialSource.none);
  }

  Future<TdxCredentials?> read() async {
    return (await resolve()).credentials;
  }

  Future<void> save(TdxCredentials credentials) async {
    await _storage.write(key: _clientIdKey, value: credentials.clientId.trim());
    await _storage.write(key: _clientSecretKey, value: credentials.clientSecret.trim());
  }

  Future<void> clear() async {
    await _storage.delete(key: _clientIdKey);
    await _storage.delete(key: _clientSecretKey);
  }
}

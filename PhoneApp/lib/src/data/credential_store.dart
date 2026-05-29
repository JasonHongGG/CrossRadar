import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

final credentialStoreProvider = Provider<TdxCredentialStore>(
  (ref) => const TdxCredentialStore(),
);

class TdxCredentials {
  const TdxCredentials({required this.clientId, required this.clientSecret});

  final String clientId;
  final String clientSecret;

  bool get isComplete =>
      clientId.trim().isNotEmpty && clientSecret.trim().isNotEmpty;
}

class TdxCredentialStore {
  const TdxCredentialStore({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage();

  static const _clientIdKey = 'tdx_client_id';
  static const _clientSecretKey = 'tdx_client_secret';
  static const _envClientId = String.fromEnvironment('TDX_CLIENT_ID');
  static const _envClientSecret = String.fromEnvironment('TDX_CLIENT_SECRET');

  final FlutterSecureStorage _storage;

  Future<TdxCredentials?> read() async {
    if (_envClientId.trim().isNotEmpty && _envClientSecret.trim().isNotEmpty) {
      return const TdxCredentials(
        clientId: _envClientId,
        clientSecret: _envClientSecret,
      );
    }
    final clientId = await _storage.read(key: _clientIdKey);
    final clientSecret = await _storage.read(key: _clientSecretKey);
    final credentials = TdxCredentials(
      clientId: clientId ?? '',
      clientSecret: clientSecret ?? '',
    );
    return credentials.isComplete ? credentials : null;
  }

  Future<void> save(TdxCredentials credentials) async {
    await _storage.write(key: _clientIdKey, value: credentials.clientId.trim());
    await _storage.write(
      key: _clientSecretKey,
      value: credentials.clientSecret.trim(),
    );
  }
}

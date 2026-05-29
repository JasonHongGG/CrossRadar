import 'package:crossradar_phone/src/data/credential_store.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('uses saved credentials before defaults', () async {
    final storage = _MemoryCredentialStorage({'tdx_client_id': 'saved-id', 'tdx_client_secret': 'saved-secret'});
    final store = TdxCredentialStore(
      storage: storage,
      defaults: const _StaticDefaults(TdxCredentials(clientId: 'default-id', clientSecret: 'default-secret')),
    );

    final resolution = await store.resolve();

    expect(resolution.source, TdxCredentialSource.saved);
    expect(resolution.credentials?.clientId, 'saved-id');
  });

  test('falls back to defaults when secure storage is empty', () async {
    final store = TdxCredentialStore(
      storage: _MemoryCredentialStorage(),
      defaults: const _StaticDefaults(TdxCredentials(clientId: 'default-id', clientSecret: 'default-secret')),
    );

    final resolution = await store.resolve();

    expect(resolution.source, TdxCredentialSource.defaults);
    expect(resolution.credentials?.clientSecret, 'default-secret');
  });

  test('saves trimmed credentials and clear reveals defaults again', () async {
    final storage = _MemoryCredentialStorage();
    final store = TdxCredentialStore(
      storage: storage,
      defaults: const _StaticDefaults(TdxCredentials(clientId: 'default-id', clientSecret: 'default-secret')),
    );

    await store.save(const TdxCredentials(clientId: ' saved-id ', clientSecret: ' saved-secret '));
    expect((await store.resolve()).credentials?.clientId, 'saved-id');

    await store.clear();
    final resolution = await store.resolve();
    expect(resolution.source, TdxCredentialSource.defaults);
    expect(resolution.credentials?.clientId, 'default-id');
  });

  test('returns none when neither saved nor default credentials exist', () async {
    final store = TdxCredentialStore(storage: _MemoryCredentialStorage(), defaults: const _StaticDefaults(null));

    final resolution = await store.resolve();

    expect(resolution.source, TdxCredentialSource.none);
    expect(resolution.credentials, isNull);
  });
}

class _MemoryCredentialStorage implements TdxCredentialStorage {
  _MemoryCredentialStorage([Map<String, String>? values]) : values = {...?values};

  final Map<String, String> values;

  @override
  Future<String?> read({required String key}) async => values[key];

  @override
  Future<void> write({required String key, required String value}) async {
    values[key] = value;
  }

  @override
  Future<void> delete({required String key}) async {
    values.remove(key);
  }
}

class _StaticDefaults implements TdxCredentialDefaults {
  const _StaticDefaults(this.credentials);

  final TdxCredentials? credentials;

  @override
  Future<TdxCredentials?> read() async => credentials;
}

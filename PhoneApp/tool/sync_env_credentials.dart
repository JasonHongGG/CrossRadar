import 'dart:convert';
import 'dart:io';

Future<void> main() async {
  final root = _workspaceRoot();
  final envFile = File('${root.path}${Platform.pathSeparator}.env');
  if (!envFile.existsSync()) {
    stderr.writeln('No .env file found at ${envFile.path}.');
    exitCode = 1;
    return;
  }

  final env = _parseEnv(await envFile.readAsLines());
  final clientId = env['TDX_CLIENT_ID']?.trim() ?? '';
  final clientSecret = env['TDX_CLIENT_SECRET']?.trim() ?? '';
  if (clientId.isEmpty || clientSecret.isEmpty) {
    stderr.writeln('TDX_CLIENT_ID and TDX_CLIENT_SECRET must both exist in .env.');
    exitCode = 1;
    return;
  }

  final configDir = Directory('${root.path}${Platform.pathSeparator}PhoneApp${Platform.pathSeparator}assets${Platform.pathSeparator}config');
  await configDir.create(recursive: true);
  final configFile = File('${configDir.path}${Platform.pathSeparator}default_credentials.json');
  await configFile.writeAsString(const JsonEncoder.withIndent('  ').convert({'tdx_client_id': clientId, 'tdx_client_secret': clientSecret}));
  stdout.writeln('Wrote PhoneApp TDX default credentials asset from .env.');
}

Directory _workspaceRoot() {
  final current = Directory.current;
  if (File('${current.path}${Platform.pathSeparator}PhoneApp${Platform.pathSeparator}pubspec.yaml').existsSync()) {
    return current;
  }
  if (File('${current.path}${Platform.pathSeparator}pubspec.yaml').existsSync() && current.path.endsWith('PhoneApp')) {
    return current.parent;
  }
  var cursor = current;
  while (cursor.parent.path != cursor.path) {
    if (File('${cursor.path}${Platform.pathSeparator}PhoneApp${Platform.pathSeparator}pubspec.yaml').existsSync()) {
      return cursor;
    }
    cursor = cursor.parent;
  }
  return current;
}

Map<String, String> _parseEnv(List<String> lines) {
  final values = <String, String>{};
  for (final rawLine in lines) {
    final line = rawLine.trim();
    if (line.isEmpty || line.startsWith('#')) continue;
    final separator = line.indexOf('=');
    if (separator <= 0) continue;
    final key = line.substring(0, separator).trim();
    var value = line.substring(separator + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.substring(1, value.length - 1);
    }
    values[key] = value;
  }
  return values;
}

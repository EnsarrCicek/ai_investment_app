import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import '../models/position_limits.dart';

/// Ham saklama arka ucu (testte bellek içi sahte kullanılır).
abstract class LimitStorageBackend {
  Future<String?> read(String key);
  Future<void> write(String key, String content);
}

/// Uygulamanın cihaz içi destek klasöründe hesap başına bir JSON dosyası.
/// Cihazlar arası senkronizasyon YOKTUR.
class FileLimitStorageBackend implements LimitStorageBackend {
  Future<File> _file(String key) async {
    final dir = Directory('${(await getApplicationSupportDirectory()).path}/position_limits');
    if (!await dir.exists()) await dir.create(recursive: true);
    return File('${dir.path}/$key.json');
  }

  @override
  Future<String?> read(String key) async {
    final f = await _file(key);
    return await f.exists() ? f.readAsString() : null;
  }

  @override
  Future<void> write(String key, String content) async {
    await (await _file(key)).writeAsString(content, flush: true);
  }
}

/// Kullanıcı tanımlı kâr/zarar sınırları — yalnız bu cihazda, hesap kimliğine (Firebase UID) göre ayrı.
class PositionLimitStore {
  final LimitStorageBackend backend;

  PositionLimitStore({LimitStorageBackend? backend}) : backend = backend ?? FileLimitStorageBackend();

  static String _key(String uid) {
    if (uid.isEmpty || !RegExp(r'^[A-Za-z0-9_-]+$').hasMatch(uid)) {
      throw ArgumentError('Geçersiz hesap kimliği');
    }
    return 'user_$uid';
  }

  Future<Map<String, PositionLimits>> _all(String uid) async {
    final raw = await backend.read(_key(uid));
    if (raw == null || raw.isEmpty) return {};
    final json = jsonDecode(raw) as Map<String, dynamic>;
    return json.map((k, v) => MapEntry(k, PositionLimits.fromJson(v as Map<String, dynamic>)));
  }

  Future<void> _put(String uid, Map<String, PositionLimits> all) =>
      backend.write(_key(uid), jsonEncode(all.map((k, v) => MapEntry(k, v.toJson()))));

  Future<PositionLimits?> load(String uid, String asset) async => (await _all(uid))[asset.toUpperCase()];

  Future<void> save(String uid, String asset, PositionLimits limits) async {
    final all = await _all(uid);
    all[asset.toUpperCase()] = limits;
    await _put(uid, all);
  }

  Future<void> remove(String uid, String asset) async {
    final all = await _all(uid);
    all.remove(asset.toUpperCase());
    await _put(uid, all);
  }
}

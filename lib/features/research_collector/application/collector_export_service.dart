import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:crypto/crypto.dart';
import 'package:path/path.dart' as p;

import '../data/collector_database.dart';
import '../data/collector_repository.dart';
import '../domain/collector_constants.dart';
import '../domain/market_time.dart';
import '../domain/study_anchors.g.dart';

const String kExportManifestName = 'export_manifest.json';

class ExportBusyException implements Exception {
  @override
  String toString() => 'Toplama sürerken dışa aktarma yapılamaz; toplama bitince tekrar deneyin.';
}

class ExportResult {
  final String zipPath;
  final Map<String, Object?> manifest;

  ExportResult(this.zipPath, this.manifest);
}

/// export_manifest.json content. Keys are fixed and values derive only from the exported bytes + anchors.
Map<String, Object?> buildExportManifest({
  required DateTime exportedAt,
  required String dbSha256,
  required int dbSizeBytes,
}) =>
    {
      'exported_at': utcIso(exportedAt),
      'app_version': kAppVersion,
      'collector_version': kCollectorVersion,
      'schema_version': kSchemaVersion,
      'study_manifest_sha': kStudyManifestSha256,
      'label_sha': kLabelManifestSha256,
      'universe_sha': kUniverseSha256,
      'prospective_start_session': kProspectiveStartSession,
      'db_file': kDatabaseName,
      'db_sha256': dbSha256,
      'db_size_bytes': dbSizeBytes,
      'collection_role': kCollectionRole,
      'primary_validation_eligible': false,
      'note': 'MOBILE_SHADOW archive: not primary data of the current prospective study',
    };

/// Read-only export: momentum_shadow.db + export_manifest.json in one ZIP. There is deliberately NO import.
class CollectorExportService {
  final CollectorDatabase database;
  final CollectorRepository repo;
  final Future<Directory> Function() outputDir;
  final DateTime Function() clock;

  CollectorExportService({
    required this.database,
    required this.repo,
    required this.outputDir,
    DateTime Function()? clock,
  }) : clock = clock ?? (() => DateTime.now().toUtc());

  Future<ExportResult> export() async {
    final now = clock();
    const owner = 'export';
    if (!await repo.acquireLock(owner, now)) throw ExportBusyException();
    late List<int> bytes;
    try {
      // Close so every committed page is in the main file (no open journal), copy the bytes, reopen lazily.
      await database.close();
      bytes = await File(await database.path).readAsBytes();
    } finally {
      await repo.releaseLock(owner);
    }
    final manifest = buildExportManifest(
      exportedAt: now,
      dbSha256: sha256.convert(bytes).toString(),
      dbSizeBytes: bytes.length,
    );
    final manifestBytes = utf8.encode('${const JsonEncoder.withIndent(' ').convert(manifest)}\n');
    final archive = Archive()
      ..addFile(ArchiveFile(kDatabaseName, bytes.length, bytes))
      ..addFile(ArchiveFile(kExportManifestName, manifestBytes.length, manifestBytes));
    final zip = ZipEncoder().encode(archive);
    final dir = await outputDir();
    await dir.create(recursive: true);
    final stamp = utcIso(now).replaceAll(RegExp(r'[^0-9T]'), '').substring(0, 15);
    final path = p.join(dir.path, 'momentum_shadow_export_${stamp}Z.zip');
    await File(path).writeAsBytes(zip, flush: true);
    return ExportResult(path, manifest);
  }
}

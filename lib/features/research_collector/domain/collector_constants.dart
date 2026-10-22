import 'study_anchors.g.dart';

/// MOBILE_SHADOW: the phone archive is a backup/comparison copy. It is NEVER part of the current prospective
/// study's primary validation (the Windows collector is primary). Every row carries this role.
const String kCollectionRole = 'MOBILE_SHADOW';
const String kCollectorVersion = 'momentum-mobile-shadow-1.0.0';

/// Must equal `version:` in pubspec.yaml (checked by a test).
const String kAppVersion = '1.0.0+1';

const String kSource = 'yahoo_finance';
const String kDatabaseName = 'momentum_shadow.db';
const int kSchemaVersion = 1;

const List<String> kIntervals = ['1m', '5m'];
const Map<String, int> kIntervalSeconds = {'1m': 60, '5m': 300};

/// Recovery window: both intervals are fetched with range=5d so one or two missed days are recovered.
const String kRecoveryRange = '5d';

const String kExpectedExchange = 'IST';
const String kExpectedCurrency = 'TRY';

const String kModeBackgroundEod = 'BACKGROUND_EOD';
const String kModeManualSync = 'MANUAL_SYNC';

const String kPhasePreStart = 'PRE_START_SHADOW';
const String kPhaseProspective = 'PROSPECTIVE_SHADOW';

const String kRolePrimary = 'PRIMARY';
const String kRoleBenchmark = 'BENCHMARK';

const String kIdentityMatch = 'MATCH';
const String kIdentityUnverified = 'UNVERIFIED';
const String kIdentityMismatch = 'MISMATCH';

/// Shadow universe: the 87 frozen primary assets + benchmark. KTLEV (descriptive-only) is NOT collected.
List<String> shadowSymbols() => [...kPrimaryUniverse, kBenchmark];

String universeRoleOf(String symbol) => symbol == kBenchmark ? kRoleBenchmark : kRolePrimary;

/// Static anchors stored in every run and in the export manifest.
Map<String, String> studyAnchors() => {
      'study_manifest_sha256': kStudyManifestSha256,
      'label_manifest_sha256': kLabelManifestSha256,
      'universe_sha256': kUniverseSha256,
      'prospective_start_session': kProspectiveStartSession,
      'collection_role': kCollectionRole,
      'collector_version': kCollectorVersion,
    };

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../../widgets/gradient_app_bar.dart';
import '../application/collector_export_service.dart';
import '../application/collector_health_service.dart';
import '../application/collector_scheduler.dart';
import '../application/mobile_collector_service.dart';
import '../data/collector_database.dart';
import '../data/collector_repository.dart';
import '../data/yahoo_mobile_source.dart';
import '../domain/collector_constants.dart';
import '../domain/market_time.dart';

/// Manual sync state shared across page visits (the sync keeps running if the page is closed).
class ManualSyncController extends ChangeNotifier {
  static final ManualSyncController instance = ManualSyncController._();
  ManualSyncController._();

  bool running = false;
  int done = 0;
  int total = 0;
  String? current;
  String? lastResult;
  CancelToken? _cancel;

  Future<void> start(MobileCollectorService service) async {
    if (running) return;
    running = true;
    done = 0;
    total = shadowSymbols().length;
    current = null;
    _cancel = CancelToken();
    notifyListeners();
    try {
      final s = await service.run(
        mode: kModeManualSync,
        cancel: _cancel,
        onProgress: (d, t, sym) {
          done = d;
          total = t;
          current = sym;
          notifyListeners();
        },
      );
      lastResult = '${s.status}: ${s.symbolsSucceeded.length} başarılı, ${s.symbolsFailed.length} başarısız, '
          '1m +${s.newBars1m}, 5m +${s.newBars5m}, revizyon ${s.revisions}, partial ${s.partialBars}';
    } catch (e) {
      lastResult = 'Hata: $e';
    } finally {
      running = false;
      _cancel = null;
      notifyListeners();
    }
  }

  void cancel() => _cancel?.cancel();
}

class ResearchCollectorPage extends StatefulWidget {
  const ResearchCollectorPage({super.key});

  @override
  State<ResearchCollectorPage> createState() => _ResearchCollectorPageState();
}

class _ResearchCollectorPageState extends State<ResearchCollectorPage> {
  final _database = CollectorDatabase.instance();
  late final _repo = CollectorRepository(_database);
  late final _health = CollectorHealthService(_repo);
  final _sync = ManualSyncController.instance;

  _Snapshot? _snap;
  String? _loadError;
  bool _exporting = false;

  @override
  void initState() {
    super.initState();
    _sync.addListener(_onSync);
    _load();
  }

  @override
  void dispose() {
    _sync.removeListener(_onSync);
    super.dispose();
  }

  bool _wasRunning = false;

  void _onSync() {
    if (!mounted) return;
    setState(() {});
    if (_wasRunning && !_sync.running) _load();
    _wasRunning = _sync.running;
  }

  CollectorScheduler get _scheduler => CollectorScheduler(repo: _repo, registrar: WorkmanagerRegistrar());

  Future<void> _load() async {
    try {
      final now = DateTime.now().toUtc();
      final path = await _database.path;
      var size = 0;
      for (final suffix in ['', '-journal', '-wal']) {
        final f = File('$path$suffix');
        if (await f.exists()) size += await f.length();
      }
      final snap = _Snapshot(
        enabled: await _repo.collectorEnabled(),
        mobileData: await _repo.collectOnMobileData(),
        lastOk: await _repo.lastRun(successfulOnly: true),
        lastBackground: await _repo.lastRun(mode: kModeBackgroundEod),
        nextRun: await _health.approximateNextRun(),
        dbBytes: size,
        today: await _repo.dayStatus(sessionDateOf(now)),
        totals: await _repo.totals(),
        mismatchSymbols: await _repo.mismatchSymbols(),
        runs: await _repo.runs(limit: 5),
        schedulerError: await _repo.setting(kSettingSchedulerError) ?? '',
      );
      if (mounted) setState(() => _snap = snap);
    } catch (e) {
      if (mounted) setState(() => _loadError = '$e');
    }
  }

  Future<void> _toggleEnabled(bool v) async {
    await _repo.setSetting(kSettingCollectorEnabled, '$v', DateTime.now().toUtc());
    await _reschedule();
  }

  Future<void> _toggleMobileData(bool v) async {
    await _repo.setSetting(kSettingCollectOnMobileData, '$v', DateTime.now().toUtc());
    await _reschedule();
  }

  Future<void> _reschedule() async {
    try {
      if (Platform.isAndroid) await _scheduler.ensureScheduled(reset: true);
    } catch (e) {
      await _repo.setSetting(kSettingSchedulerError, '$e', DateTime.now().toUtc());
    }
    await _load();
  }

  void _syncNow() {
    _sync.start(MobileCollectorService(repo: _repo, source: YahooMobileSource(), network: currentNetworkKind));
  }

  Future<void> _showHealth() async {
    final h = await _health.health();
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Toplama Sağlığı'),
        content: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final e in h.entries)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Text('${e.key}: ${_fmt(e.value)}', style: const TextStyle(fontSize: 13)),
                ),
            ],
          ),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Kapat'))],
      ),
    );
  }

  Future<void> _export() async {
    setState(() => _exporting = true);
    try {
      final result = await CollectorExportService(
        database: _database,
        repo: _repo,
        outputDir: () async => Directory('${(await getTemporaryDirectory()).path}/shadow_export'),
      ).export();
      await SharePlus.instance.share(ShareParams(
        files: [XFile(result.zipPath, mimeType: 'application/zip')],
        subject: 'momentum_shadow export (MOBILE_SHADOW)',
      ));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Dışa aktarılamadı: $e')));
    } finally {
      if (mounted) setState(() => _exporting = false);
      await _load();
    }
  }

  static String _fmt(Object? v) => v == null ? '—' : (v is List ? (v.isEmpty ? '[]' : v.join(', ')) : '$v');

  static String _local(Object? utc) {
    if (utc is! String || utc.isEmpty) return '—';
    final t = DateTime.tryParse(utc);
    if (t == null) return utc;
    final w = istanbulWallClock(t);
    return '${isoDate(w)} ${w.hour.toString().padLeft(2, '0')}:${w.minute.toString().padLeft(2, '0')}';
  }

  static String _size(int bytes) {
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }

  @override
  Widget build(BuildContext context) {
    final snap = _snap;
    return Scaffold(
      appBar: GradientAppBar(title: const Text('Araştırma Veri Toplayıcı')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            Card(
              color: Colors.amber.shade100,
              child: const ListTile(
                leading: Icon(Icons.shield_outlined, color: Colors.brown),
                title: Text('MOBILE SHADOW — mevcut prospective çalışmanın primary verisi değildir.',
                    style: TextStyle(fontWeight: FontWeight.bold, color: Colors.brown)),
                subtitle: Text('Primary toplayıcı Windows bilgisayarıdır. Bu veriler yalnız yedek ve '
                    'karşılaştırma içindir; model sonucu gösterilmez.'),
              ),
            ),
            const Card(
              child: ListTile(
                leading: Icon(Icons.battery_alert_outlined),
                title: Text('Arka plan veri toplama Android pil optimizasyonu nedeniyle gecikebilir.'),
                subtitle: Text('Günlük toplama hedefi 19:15 (İstanbul); Android tam saat garantisi vermez. '
                    'Eksik günler sonraki toplamada son 5 günden kurtarılır.'),
              ),
            ),
            if (_loadError != null)
              Card(child: ListTile(leading: const Icon(Icons.error_outline), title: Text(_loadError!))),
            if (snap == null && _loadError == null) const Center(child: Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator())),
            if (snap != null) ..._content(snap),
          ],
        ),
      ),
    );
  }

  List<Widget> _content(_Snapshot s) {
    final theme = Theme.of(context);
    final mismatchToday = (s.today['identity_mismatches'] as int? ?? 0) > 0;
    return [
      _section('Collector Durumu', [
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(s.enabled ? 'Aktif' : 'Pasif'),
          subtitle: const Text('Günlük arka plan EOD arşivi'),
          value: s.enabled,
          onChanged: _sync.running ? null : _toggleEnabled,
        ),
        _row('Son başarılı toplama', _local(s.lastOk?['finished_at'])),
        _row('Son arka plan çalışma', _local(s.lastBackground?['started_at'])),
        _row('Bir sonraki yaklaşık çalışma', s.enabled ? '~${_local(utcIso(s.nextRun))}' : '—'),
        _row('Database boyutu', _size(s.dbBytes)),
        if (s.schedulerError.isNotEmpty) _row('Zamanlayıcı hatası', s.schedulerError),
      ]),
      _section('Bugünkü durum', [
        _row('Başarılı asset', '${s.today['symbols_succeeded']}'),
        _row('Başarısız asset', '${s.today['symbols_failed']}'),
        _row('1m bar', '${s.today['bars_1m']}'),
        _row('5m bar', '${s.today['bars_5m']}'),
        _row('Partial', '${s.today['partial_bars']}'),
        _row('Revizyon', '${s.today['revisions']}'),
        _row('Identity mismatch', '${s.today['identity_mismatches']}',
            color: mismatchToday ? theme.colorScheme.error : null),
      ]),
      if (s.mismatchSymbols.isNotEmpty)
        Card(
          color: theme.colorScheme.errorContainer,
          child: ListTile(
            leading: const Icon(Icons.warning_amber_outlined),
            title: const Text('Kimlik uyuşmazlığı (MISMATCH) görülen semboller'),
            subtitle: Text(s.mismatchSymbols.join(', ')),
          ),
        ),
      _section('Toplam', [
        _row('Kayıtlı gün', '${s.totals['days_with_data']}'),
        _row('Asset sayısı', '${s.totals['assets']}'),
        _row('1m toplam bar', '${s.totals['bars_1m']}'),
        _row('5m toplam bar', '${s.totals['bars_5m']}'),
      ]),
      _section('Ayarlar', [
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('Collect on mobile data'),
          subtitle: const Text('Kapalıysa yalnız Wi-Fi ile toplanır'),
          value: s.mobileData,
          onChanged: _sync.running ? null : _toggleMobileData,
        ),
      ]),
      if (_sync.running)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Senkronize ediliyor: ${_sync.done} / ${_sync.total}${_sync.current == null ? '' : '  (${_sync.current})'}'),
                const SizedBox(height: 8),
                LinearProgressIndicator(value: _sync.total == 0 ? null : _sync.done / _sync.total),
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton.icon(onPressed: _sync.cancel, icon: const Icon(Icons.stop), label: const Text('İptal')),
                ),
              ],
            ),
          ),
        ),
      if (!_sync.running && _sync.lastResult != null)
        Card(child: ListTile(leading: const Icon(Icons.info_outline), title: Text(_sync.lastResult!))),
      const SizedBox(height: 4),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          FilledButton.icon(
            onPressed: _sync.running ? null : _syncNow,
            icon: const Icon(Icons.sync),
            label: const Text('Şimdi Senkronize Et'),
          ),
          OutlinedButton.icon(
            onPressed: _showHealth,
            icon: const Icon(Icons.health_and_safety_outlined),
            label: const Text('Sağlığı Kontrol Et'),
          ),
          OutlinedButton.icon(
            onPressed: _sync.running || _exporting ? null : _export,
            icon: _exporting
                ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.ios_share),
            label: const Text('Veriyi Dışa Aktar'),
          ),
        ],
      ),
      const SizedBox(height: 12),
      _section('Son çalışmalar', [
        if (s.runs.isEmpty) const Text('Henüz çalışma yok.'),
        for (final r in s.runs)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Text(
              '${r['mode']} · ${r['status']}\n'
              'planlanan ${_local(r['scheduled_for'])} · başlangıç ${_local(r['started_at'])} · bitiş ${_local(r['finished_at'])}\n'
              '${r['symbols_succeeded']}/${r['symbols_requested']} başarılı · 1m +${r['new_bars_1m']} · 5m +${r['new_bars_5m']} · '
              'hata ${r['error_count']}',
              style: const TextStyle(fontSize: 12),
            ),
          ),
      ]),
    ];
  }

  Widget _section(String title, List<Widget> children) => Card(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 6),
              ...children,
            ],
          ),
        ),
      );

  Widget _row(String label, String value, {Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(
          children: [
            Expanded(child: Text(label)),
            Flexible(
              child: Text(value,
                  textAlign: TextAlign.right, style: TextStyle(fontWeight: FontWeight.w600, color: color)),
            ),
          ],
        ),
      );
}

class _Snapshot {
  final bool enabled;
  final bool mobileData;
  final Map<String, Object?>? lastOk;
  final Map<String, Object?>? lastBackground;
  final DateTime nextRun;
  final int dbBytes;
  final Map<String, Object?> today;
  final Map<String, Object?> totals;
  final List<String> mismatchSymbols;
  final List<Map<String, Object?>> runs;
  final String schedulerError;

  _Snapshot({
    required this.enabled,
    required this.mobileData,
    required this.lastOk,
    required this.lastBackground,
    required this.nextRun,
    required this.dbBytes,
    required this.today,
    required this.totals,
    required this.mismatchSymbols,
    required this.runs,
    required this.schedulerError,
  });
}

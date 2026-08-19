import 'package:flutter/material.dart';

import '../../models/notification_record.dart';
import '../../services/api/notification_api.dart';

const Map<String, String> _kindLabels = {'TEST': 'Test', 'BUY': 'AL', 'SELL': 'SAT'};

Color _kindColor(String kind) {
  switch (kind) {
    case 'BUY':
      return Colors.green;
    case 'SELL':
      return Colors.red;
    default:
      return Colors.grey;
  }
}

IconData _kindIcon(String kind) {
  switch (kind) {
    case 'BUY':
      return Icons.trending_up;
    case 'SELL':
      return Icons.trending_down;
    default:
      return Icons.notifications_outlined;
  }
}

String _fmtDate(DateTime d) {
  final local = d.toLocal();
  final day = local.day.toString().padLeft(2, '0');
  final month = local.month.toString().padLeft(2, '0');
  final hour = local.hour.toString().padLeft(2, '0');
  final minute = local.minute.toString().padLeft(2, '0');
  return '$day.$month.${local.year} $hour:$minute';
}

class NotificationHistoryScreen extends StatefulWidget {
  const NotificationHistoryScreen({super.key});

  @override
  State<NotificationHistoryScreen> createState() => _NotificationHistoryScreenState();
}

class _NotificationHistoryScreenState extends State<NotificationHistoryScreen> {
  late Future<List<NotificationRecord>> _future;

  @override
  void initState() {
    super.initState();
    _future = NotificationApi().fetchHistory();
  }

  Future<void> _refresh() async {
    setState(() {
      _future = NotificationApi().fetchHistory();
    });
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Bildirimler')),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: FutureBuilder<List<NotificationRecord>>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [Center(child: Text('Hata: ${snapshot.error}'))],
              );
            }
            final records = snapshot.data!;
            if (records.isEmpty) {
              return ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: const [
                  Padding(
                    padding: EdgeInsets.only(top: 80),
                    child: Center(
                      child: Text(
                        'Henüz bildirim gönderilmedi.\nAyarlar\'dan test bildirimi gönderebilirsiniz.',
                        textAlign: TextAlign.center,
                      ),
                    ),
                  ),
                ],
              );
            }
            return ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(12),
              itemCount: records.length,
              separatorBuilder: (_, _) => const SizedBox(height: 8),
              itemBuilder: (context, index) => _NotificationCard(record: records[index]),
            );
          },
        ),
      ),
    );
  }
}

class _NotificationCard extends StatelessWidget {
  final NotificationRecord record;
  const _NotificationCard({required this.record});

  @override
  Widget build(BuildContext context) {
    final color = _kindColor(record.kind);
    return Card(
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: color.withValues(alpha: 0.15),
          child: Icon(_kindIcon(record.kind), color: color),
        ),
        title: Text(record.title, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 4),
            Text(record.body),
            const SizedBox(height: 4),
            Text(_fmtDate(record.createdAt), style: const TextStyle(fontSize: 11, color: Colors.grey)),
          ],
        ),
        trailing: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(6)),
          child: Text(
            _kindLabels[record.kind] ?? record.kind,
            style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 12),
          ),
        ),
        isThreeLine: true,
      ),
    );
  }
}

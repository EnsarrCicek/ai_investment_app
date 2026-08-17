import 'package:flutter/material.dart';

import '../../models/macro_snapshot.dart';
import '../../services/api/analysis_api.dart';

const Map<String, String> _macroLabels = {
  'dxy': 'Dolar Endeksi (DXY)',
  'us_10y_yield': 'ABD 10 Yıllık Tahvil Faizi',
  'vix': 'VIX (Volatilite Endeksi)',
  'oil': 'Petrol',
  'gold': 'Altın',
  'usdtry': 'USD/TRY',
};

class MacroScreen extends StatefulWidget {
  const MacroScreen({super.key});

  @override
  State<MacroScreen> createState() => _MacroScreenState();
}

class _MacroScreenState extends State<MacroScreen> {
  late Future<MacroSnapshotDetail> _future;

  @override
  void initState() {
    super.initState();
    _future = AnalysisApi().fetchMacro();
  }

  Future<void> _refresh() async {
    setState(() {
      _future = AnalysisApi().fetchMacro();
    });
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Makro Analiz')),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: FutureBuilder<MacroSnapshotDetail>(
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
            final data = snapshot.data!;
            final color = data.macroScore >= 0 ? Colors.green : Colors.red;
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(12),
              children: [
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Makro Skor: ${data.macroScore >= 0 ? '+' : ''}${data.macroScore.toStringAsFixed(1)}',
                          style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 18),
                        ),
                        Text('Güven: %${data.confidence.toStringAsFixed(0)}'),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                const Text('Gösterge Katkıları', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                ...data.components.entries.map((e) {
                  final indicator = data.indicators[e.key] as Map<String, dynamic>?;
                  final pctChange = (indicator?['pct_change'] as num?)?.toDouble();
                  final value = (indicator?['value'] as num?)?.toDouble();
                  return Card(
                    child: ListTile(
                      title: Text(_macroLabels[e.key] ?? e.key),
                      subtitle: value != null
                          ? Text(
                              'Değer: ${value.toStringAsFixed(2)}'
                              '${pctChange != null ? '  (${pctChange >= 0 ? '+' : ''}${pctChange.toStringAsFixed(2)}%)' : ''}',
                            )
                          : null,
                      trailing: Text(
                        '${e.value >= 0 ? '+' : ''}${e.value.toStringAsFixed(1)}',
                        style: TextStyle(
                          color: e.value >= 0 ? Colors.green : Colors.red,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  );
                }),
              ],
            );
          },
        ),
      ),
    );
  }
}

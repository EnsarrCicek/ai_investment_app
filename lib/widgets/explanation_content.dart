import 'package:flutter/material.dart';

import '../models/explanation.dart';

/// AL/SAT kararının dayandığı verilerin okunabilir dökümü — DecisionEngine'in
/// gerçekten kullandığı ağırlıklar (missing-data normalizasyonundan SONRAKİ
/// gerçek değerler) + teknik/haber/makro gerekçeleri. Hem Dashboard'daki
/// "Karar Gerekçesi" diyaloğunda hem Teknik sekmesine gömülü kartta kullanılır.
class ExplanationContent extends StatelessWidget {
  final Explanation explanation;

  const ExplanationContent({super.key, required this.explanation});

  String _pct(double? weight) => '%${(weight! * 100).round()}';

  @override
  Widget build(BuildContext context) {
    final hasWeights = explanation.technicalWeight != null || explanation.newsWeight != null || explanation.macroWeight != null;
    return SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(explanation.summary),
          if (hasWeights) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 12,
              runSpacing: 4,
              children: [
                if (explanation.technicalWeight != null) Text('Teknik: ${_pct(explanation.technicalWeight)}'),
                if (explanation.newsWeight != null) Text('Haber: ${_pct(explanation.newsWeight)}'),
                if (explanation.macroWeight != null) Text('Makro: ${_pct(explanation.macroWeight)}'),
              ],
            ),
          ],
          if (explanation.technicalReasons.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Text('Teknik Analiz:', style: TextStyle(fontWeight: FontWeight.bold)),
            for (final reason in explanation.technicalReasons) Text('•  $reason'),
          ],
          if (explanation.newsReasons.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Text('Haber Analizi:', style: TextStyle(fontWeight: FontWeight.bold)),
            for (final reason in explanation.newsReasons) Text('•  $reason'),
          ],
          if (explanation.macroReasons.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Text('Makro Etkenler:', style: TextStyle(fontWeight: FontWeight.bold)),
            for (final reason in explanation.macroReasons) Text('•  $reason'),
          ],
          if (explanation.missing.isNotEmpty) ...[
            const SizedBox(height: 12),
            for (final note in explanation.missing)
              Text(note, style: const TextStyle(color: Colors.orange, fontStyle: FontStyle.italic)),
          ],
        ],
      ),
    );
  }
}

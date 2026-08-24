import 'package:flutter/material.dart';

import '../../widgets/gradient_app_bar.dart';

import '../../models/fund_analysis.dart';
import '../../models/news_item.dart';
import '../../services/api/fund_api.dart';
import '../../utils/url_launch.dart';
import 'fund_style.dart';

/// AŞAMA 60: Fon detay ekranı — kullanıcı isteği: "arama kısmı ekle her fona
/// ulaşabileyim... fon kısmı daha detaylı olsun." Öneriler listesindeki bir
/// karta ya da arama sonucuna dokununca açılır; risk dağılımını, "neden
/// önerildi" açıklamasını ve haber/yorum kaynaklarında bulunanları gösterir.
class FundDetailScreen extends StatefulWidget {
  final String fundCode;
  const FundDetailScreen({super.key, required this.fundCode});

  @override
  State<FundDetailScreen> createState() => _FundDetailScreenState();
}

class _FundDetailScreenState extends State<FundDetailScreen> {
  late Future<FundAnalysis> _future;
  late Future<List<NewsItem>> _newsFuture;

  @override
  void initState() {
    super.initState();
    _future = FundApi().fetchFundDetail(widget.fundCode);
    _newsFuture = FundApi().fetchFundNews(widget.fundCode);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: GradientAppBar(title: Text(widget.fundCode)),
      body: FutureBuilder<FundAnalysis>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Padding(padding: const EdgeInsets.all(16), child: Text('Hata: ${snapshot.error}')));
          }
          final fund = snapshot.data!;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text(fund.fundName, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              const SizedBox(height: 4),
              Text('Fiyat: ${fund.price.toStringAsFixed(4)} TL · ${fund.investorCount} yatırımcı',
                  style: const TextStyle(color: Colors.grey, fontSize: 12)),
              const SizedBox(height: 16),
              _SectionCard(
                title: 'Getiri Skoru',
                child: Column(
                  children: [
                    Text(
                      fund.compositeScore.toStringAsFixed(1),
                      style: TextStyle(
                        fontSize: 32,
                        fontWeight: FontWeight.bold,
                        color: fund.compositeScore >= 0 ? Colors.green : Colors.red,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceAround,
                      children: [
                        _DetailReturnBadge(label: '1 Ay', value: fund.return1mPct),
                        _DetailReturnBadge(label: '3 Ay', value: fund.return3mPct),
                        _DetailReturnBadge(label: '6 Ay', value: fund.return6mPct),
                        _DetailReturnBadge(label: '1 Yıl', value: fund.return1yPct),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              _SectionCard(
                title: 'Risk Seviyesi',
                child: fund.riskLevel == null
                    ? const Text('Portföy dağılım verisi alınamadığı için risk hesaplanamadı.')
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                                decoration: BoxDecoration(
                                  color: riskColor(fund.riskLevel).withValues(alpha: 0.15),
                                  borderRadius: BorderRadius.circular(6),
                                ),
                                child: Text(
                                  fundRiskLabelsTr[fund.riskLevel] ?? fund.riskLevel!,
                                  style: TextStyle(color: riskColor(fund.riskLevel), fontWeight: FontWeight.bold),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 10),
                          Text('Hisse/riskli varlık ağırlığı: %${fund.equityExposurePct?.toStringAsFixed(1) ?? '—'}'),
                          Text('Nakit/tahvil/mevduat ağırlığı: %${fund.safeExposurePct?.toStringAsFixed(1) ?? '—'}'),
                          const SizedBox(height: 6),
                          const Text(
                            'Risk, TEFAS\'ın gerçek portföy varlık dağılımı verisinden hesaplanır — bir '
                            'portföy optimizasyon modeli değildir, yalnızca fonun ne kadar dalgalı bir '
                            'varlık sınıfında olduğuna dair şeffaf bir gösterge.',
                            style: TextStyle(fontSize: 11, color: Colors.grey),
                          ),
                        ],
                      ),
              ),
              const SizedBox(height: 12),
              _SectionCard(
                title: 'Neden Bu Fon?',
                child: Text(fund.explanation.isEmpty ? 'Açıklama üretilemedi.' : fund.explanation),
              ),
              const SizedBox(height: 12),
              _SectionCard(
                title: 'Haber ve Yorum Kaynakları',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Bu fon hakkında finans haber/yorum kaynaklarında bulunanlar — belirli bir '
                      'hesabın/otoritenin önerisi olduğu iddia edilmez, gerçek makale başlıkları '
                      'olduğu gibi listelenir.',
                      style: TextStyle(fontSize: 11, color: Colors.grey),
                    ),
                    const SizedBox(height: 8),
                    FutureBuilder<List<NewsItem>>(
                      future: _newsFuture,
                      builder: (context, newsSnapshot) {
                        if (newsSnapshot.connectionState != ConnectionState.done) {
                          return const Padding(
                            padding: EdgeInsets.symmetric(vertical: 12),
                            child: Center(child: CircularProgressIndicator()),
                          );
                        }
                        if (newsSnapshot.hasError) {
                          return Text('Haberler alınamadı: ${newsSnapshot.error}');
                        }
                        final news = newsSnapshot.data!;
                        if (news.isEmpty) {
                          return const Text('Bu fonla ilgili haber/yorum bulunamadı.');
                        }
                        return Column(
                          children: news.map((n) => _FundNewsCard(item: n)).toList(),
                        );
                      },
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _SectionCard extends StatelessWidget {
  final String title;
  final Widget child;
  const _SectionCard({required this.title, required this.child});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            child,
          ],
        ),
      ),
    );
  }
}

class _DetailReturnBadge extends StatelessWidget {
  final String label;
  final double? value;
  const _DetailReturnBadge({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: Colors.grey)),
        const SizedBox(height: 2),
        Text(fmtPct(value), style: TextStyle(fontWeight: FontWeight.bold, color: pctColor(value), fontSize: 14)),
      ],
    );
  }
}

class _FundNewsCard extends StatelessWidget {
  final NewsItem item;
  const _FundNewsCard({required this.item});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 6),
      child: ListTile(
        dense: true,
        title: Text(item.title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold)),
        subtitle: Text(
          item.analystFirm != null ? '${item.analystFirm} · ${item.publisher}' : item.publisher,
          style: const TextStyle(fontSize: 11, color: Colors.grey),
        ),
        onTap: () => openExternalUrl(context, item.url),
      ),
    );
  }
}

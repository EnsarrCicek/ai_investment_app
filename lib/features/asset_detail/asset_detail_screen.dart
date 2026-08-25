import 'package:flutter/material.dart';

import '../../widgets/gradient_app_bar.dart';
import '../../widgets/explanation_content.dart';

import '../../models/analyst_consensus.dart';
import '../../models/backtest_result.dart';
import '../../models/decision.dart';
import '../../models/decision_journal_entry.dart';
import '../../models/explanation.dart';
import '../../models/news_analysis.dart';
import '../../models/news_item.dart';
import '../../models/price_quote.dart';
import '../../models/technical_analysis.dart';
import '../../services/api/analysis_api.dart';
import '../../services/api/analyst_api.dart';
import '../../services/api/backtest_api.dart';
import '../../services/api/decision_api.dart';
import '../../services/api/market_data_api.dart';
import '../../services/api/news_analysis_api.dart';
import '../../services/api/news_api.dart';
import '../../services/api/portfolio_api.dart';
import '../../utils/decision_style.dart';
import '../../utils/url_launch.dart';

const Map<String, ({String period, String interval})> _chartPeriods = {
  '1G': (period: '1d', interval: '5m'),
  '1H': (period: '5d', interval: '30m'),
  '1A': (period: '1mo', interval: '1d'),
  '3A': (period: '3mo', interval: '1d'),
  '6A': (period: '6mo', interval: '1d'),
  '1Y': (period: '1y', interval: '1wk'),
};

const Map<String, String> _changeLabels = {
  '1d': '1 Gün',
  '1w': '1 Hafta',
  '1m': '1 Ay',
  '3m': '3 Ay',
  '6m': '6 Ay',
  '1y': '1 Yıl',
};

const Map<String, String> _technicalLabels = {
  'rsi': 'RSI',
  'macd': 'MACD',
  'trend': 'EMA Trend (20/50)',
  'ema_slope': 'EMA Eğimi',
  'bollinger': 'Bollinger Bantları',
  'momentum': 'Momentum',
  'roc': 'ROC (Değişim Oranı)',
};

const Map<String, String> _signalClassLabels = {
  'STRONG_BULLISH_INITIATION': 'Güçlü Yükseliş Başlangıcı',
  'BULLISH_CONFIRMED': 'Yükseliş Teyitli',
  'BULLISH_CANDIDATE': 'Yükseliş Adayı',
  'WATCHLIST': 'İzleme Listesi',
  'NEUTRAL': 'Nötr',
  'BEARISH_CANDIDATE': 'Düşüş Adayı',
  'NO_SIGNAL': 'Sinyal Yok',
};

const Map<String, String> _marketStructureLabels = {
  'UPTREND': 'Yükseliş Trendi',
  'DOWNTREND': 'Düşüş Trendi',
  'RANGE': 'Yatay Bant',
  'UNKNOWN': 'Belirsiz',
};

const Map<String, String> _volatilityRegimeLabels = {
  'LOW': 'Düşük',
  'NORMAL': 'Normal',
  'HIGH': 'Yüksek',
  'EXTREME': 'Aşırı Yüksek',
  'UNKNOWN': 'Belirsiz',
};

const Map<String, String> _trendRegimeLabels = {
  'TRENDING': 'Güçlü/Az Gürültülü',
  'CHOPPY': 'Gürültülü/Yatay',
  'UNKNOWN': 'Belirsiz',
};

const Map<String, String> _relativeVolumeLabels = {
  'LOW': 'Düşük Hacim',
  'NORMAL': 'Normal Hacim',
  'HIGH': 'Yüksek Hacim',
  'VERY_HIGH': 'Çok Yüksek Hacim',
  'UNKNOWN': 'Belirsiz',
};

const Map<String, String> _relativeStrengthLabels = {
  'OUTPERFORMING': 'Endeksten İyi (BIST100)',
  'UNDERPERFORMING': 'Endeksten Kötü (BIST100)',
  'IN_LINE': 'Endeksle Paralel (BIST100)',
  'UNKNOWN': 'Belirsiz',
};

const Map<String, String> _gapClassLabels = {
  'NO_SIGNIFICANT_GAP': 'Belirgin gap yok',
  'GAP_FILLED': 'Gap dolduruldu',
  'GAP_UP_OPEN': 'Yukarı gap (açık)',
  'GAP_DOWN_OPEN': 'Aşağı gap (açık)',
  'UNKNOWN': 'Belirsiz',
};

const Map<String, String> _mtfConsensusLabels = {
  'UP': 'Yukarı (günlük + haftalık uyumlu)',
  'DOWN': 'Aşağı (günlük + haftalık uyumlu)',
  'FLAT': 'Yatay',
  'CONFLICTING': 'Çelişkili (günlük ve haftalık ters yönde)',
  'MIXED': 'Karışık',
  'UNKNOWN': 'Belirsiz',
};

const Map<String, String> _horizonLabels = {
  'KISA_VADELI': 'Kısa Vadeli',
  'ORTA_VADELI': 'Orta Vadeli',
  'UZUN_VADELI': 'Uzun Vadeli',
  'BELIRSIZ': 'Belirsiz',
};

Color _horizonColor(String? horizon) {
  switch (horizon) {
    case 'UZUN_VADELI':
      return Colors.teal;
    case 'ORTA_VADELI':
      return Colors.indigo;
    case 'KISA_VADELI':
      return Colors.orange;
    default:
      return Colors.grey;
  }
}

const Map<String, String> _candlestickLabels = {
  'DOJI': 'Doji',
  'HAMMER': 'Çekiç (Hammer)',
  'SHOOTING_STAR': 'Kayan Yıldız',
  'BULLISH_ENGULFING': 'Yutan Boğa Formasyonu',
  'BEARISH_ENGULFING': 'Yutan Ayı Formasyonu',
};

Color _signalClassColor(String? signalClass) {
  switch (signalClass) {
    case 'STRONG_BULLISH_INITIATION':
    case 'BULLISH_CONFIRMED':
      return Colors.green;
    case 'BULLISH_CANDIDATE':
    case 'WATCHLIST':
      return Colors.lightGreen;
    case 'BEARISH_CANDIDATE':
      return Colors.red;
    default:
      return Colors.grey;
  }
}

// Sekme sırası: Fiyat(0), Teknik(1), Haberler(2), Analistler(3), Karar
// Günlüğü(4), Performans(5) — analistler hub'ından (AŞAMA 64) doğrudan bu
// sekmeye atlamak için kullanılır.
const int assetDetailAnalystsTabIndex = 3;

class AssetDetailScreen extends StatelessWidget {
  final String symbol;
  final int initialTabIndex;

  const AssetDetailScreen({super.key, required this.symbol, this.initialTabIndex = 0});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 6,
      initialIndex: initialTabIndex,
      child: Scaffold(
        appBar: GradientAppBar(
          title: Text(symbol),
          bottom: const TabBar(
            isScrollable: true,
            tabs: [
              Tab(text: 'Fiyat'),
              Tab(text: 'Teknik'),
              Tab(text: 'Haberler'),
              Tab(text: 'Analistler'),
              Tab(text: 'Karar Günlüğü'),
              Tab(text: 'Performans'),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            _PriceTab(symbol: symbol),
            _TechnicalTab(symbol: symbol),
            _NewsTab(symbol: symbol),
            _AnalystsTab(symbol: symbol),
            _HistoryTab(symbol: symbol),
            _PerformanceTab(symbol: symbol),
          ],
        ),
      ),
    );
  }
}

class _TechnicalTab extends StatefulWidget {
  final String symbol;
  const _TechnicalTab({required this.symbol});

  @override
  State<_TechnicalTab> createState() => _TechnicalTabState();
}

class _TechnicalTabState extends State<_TechnicalTab> {
  late Future<TechnicalAnalysisDetail> _future;
  late Future<List<PriceBar>> _historyFuture;
  late Future<Explanation> _explanationFuture;

  @override
  void initState() {
    super.initState();
    _future = AnalysisApi().fetchTechnical(widget.symbol);
    // 6 aylık geçmiş — backend'in destek/direnç bölgelerini hesapladığı
    // AYNI pencere (bkz. engines/technical/engine.py, period="6mo") — grafik
    // ile anlatının aynı veriye dayandığından emin olmak için.
    _historyFuture = MarketDataApi().fetchHistory(widget.symbol, period: '6mo', interval: '1d');
    // Kullanıcı isteği (25.08.2026): "nelere göre AL/SAT diyorsun, hangi
    // verilere dayanıyorsun" — DecisionEngine'in zaten hesapladığı gerekçe
    // ve gerçek ağırlıkları Teknik sekmesine göm (bkz. ExplanationEngine).
    _explanationFuture = DecisionApi().fetchExplanation(widget.symbol);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<TechnicalAnalysisDetail>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(child: Text('Hata: ${snapshot.error}'));
        }
        final data = snapshot.data!;
        final trendColor = data.trend == 'BULLISH'
            ? Colors.green
            : data.trend == 'BEARISH'
            ? Colors.red
            : Colors.grey;
        return ListView(
          padding: const EdgeInsets.all(12),
          children: [
            _DecisionBasisCard(explanationFuture: _explanationFuture),
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Teknik Skor: ${data.technicalScore.toStringAsFixed(1)}',
                          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                        ),
                        Text('Güven: %${(data.confidence * 100).toStringAsFixed(0)}'),
                      ],
                    ),
                    Text(data.trend, style: const TextStyle(fontWeight: FontWeight.bold)),
                  ],
                ),
              ),
            ),
            if (data.signalClass != null) ...[
              const SizedBox(height: 12),
              _SignalSummaryCard(data: data),
            ],
            if (data.narrative.isNotEmpty) ...[
              const SizedBox(height: 12),
              Card(
                color: trendColor.withValues(alpha: 0.08),
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(Icons.insights, color: trendColor, size: 18),
                          const SizedBox(width: 6),
                          const Text('Grafik Neden Bunu Söylüyor?', style: TextStyle(fontWeight: FontWeight.bold)),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(data.narrative, style: const TextStyle(fontSize: 13, height: 1.4)),
                    ],
                  ),
                ),
              ),
            ],
            const SizedBox(height: 12),
            const Text('Destek / Direnç Grafiği', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            FutureBuilder<List<PriceBar>>(
              future: _historyFuture,
              builder: (context, histSnapshot) {
                if (histSnapshot.connectionState != ConnectionState.done) {
                  return const SizedBox(height: 260, child: Center(child: CircularProgressIndicator()));
                }
                if (histSnapshot.hasError || (histSnapshot.data?.length ?? 0) < 2) {
                  return const SizedBox(height: 40, child: Center(child: Text('Grafik için yeterli veri yok')));
                }
                return _SrChartCard(bars: histSnapshot.data!, zones: data.allZones, lineColor: trendColor);
              },
            ),
            const SizedBox(height: 16),
            const Text('Gösterge Katkıları', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            ...data.components.entries.map(
              (e) => Card(
                child: ListTile(
                  title: Text(_technicalLabels[e.key] ?? e.key),
                  trailing: Text(
                    '${e.value >= 0 ? '+' : ''}${e.value.toStringAsFixed(1)}',
                    style: TextStyle(
                      color: e.value >= 0 ? Colors.green : Colors.red,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 16),
            const Text('Ham Gösterge Değerleri', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: data.indicators.entries
                      .map((e) => Padding(
                            padding: const EdgeInsets.symmetric(vertical: 3),
                            child: Text('${e.key}: ${e.value}'),
                          ))
                      .toList(),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

/// Kullanıcı isteği (25.08.2026): "bana AL SAT derken nelere göre AL SAT
/// yapıyorsun, hangi verilere dayanıyorsun bunu Teknik sayfasında göster."
/// ExplanationEngine'in ürettiği (LLM'siz, kural tabanlı) gerekçeyi ve
/// DecisionEngine'in GERÇEKTEN kullandığı ağırlıkları gösterir.
class _DecisionBasisCard extends StatelessWidget {
  final Future<Explanation> explanationFuture;
  const _DecisionBasisCard({required this.explanationFuture});

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Explanation>(
      future: explanationFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Card(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            ),
          );
        }
        if (snapshot.hasError) {
          return const Card(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Text('Henüz bir AL/SAT kararı üretilmedi.', style: TextStyle(color: Colors.grey)),
            ),
          );
        }
        final explanation = snapshot.data!;
        final color = decisionColor(explanation.decision);
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text('AL/SAT Kararının Dayandığı Veriler', style: TextStyle(fontWeight: FontWeight.bold)),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(6)),
                      child: Text(
                        '${decisionLabel(explanation.decision)} (${explanation.finalScore >= 0 ? '+' : ''}'
                        '${explanation.finalScore.toStringAsFixed(1)})',
                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 12),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                ExplanationContent(explanation: explanation),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _SignalSummaryCard extends StatelessWidget {
  final TechnicalAnalysisDetail data;
  const _SignalSummaryCard({required this.data});

  @override
  Widget build(BuildContext context) {
    final signalColor = _signalClassColor(data.signalClass);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(color: signalColor, borderRadius: BorderRadius.circular(6)),
              child: Text(
                _signalClassLabels[data.signalClass] ?? data.signalClass!,
                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 12),
              ),
            ),
            if (data.investmentHorizon != null && data.investmentHorizon != 'BELIRSIZ') ...[
              const SizedBox(height: 10),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: _horizonColor(data.investmentHorizon),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      'Vade: ${_horizonLabels[data.investmentHorizon] ?? data.investmentHorizon!}',
                      style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 12),
                    ),
                  ),
                ],
              ),
              if (data.investmentHorizonReason.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(
                  data.investmentHorizonReason,
                  style: const TextStyle(fontSize: 12, color: Colors.grey),
                ),
              ],
            ],
            const SizedBox(height: 12),
            Wrap(
              spacing: 20,
              runSpacing: 10,
              children: [
                if (data.marketStructure != null)
                  _InfoChip(
                    label: 'Piyasa Yapısı',
                    value: _marketStructureLabels[data.marketStructure] ?? data.marketStructure!,
                  ),
                if (data.trendRegime != null)
                  _InfoChip(label: 'Trend Rejimi', value: _trendRegimeLabels[data.trendRegime] ?? data.trendRegime!),
                if (data.volatilityRegime != null)
                  _InfoChip(
                    label: 'Volatilite',
                    value: _volatilityRegimeLabels[data.volatilityRegime] ?? data.volatilityRegime!,
                  ),
                if (data.relativeVolumeClass != null)
                  _InfoChip(
                    label: 'Göreli Hacim',
                    value: _relativeVolumeLabels[data.relativeVolumeClass] ?? data.relativeVolumeClass!,
                  ),
                if (data.relativeStrengthClass != null && data.relativeStrengthClass != 'UNKNOWN')
                  _InfoChip(
                    label: 'Göreli Güç',
                    value: _relativeStrengthLabels[data.relativeStrengthClass] ?? data.relativeStrengthClass!,
                  ),
                if (data.gapClass != null && data.gapClass != 'NO_SIGNIFICANT_GAP')
                  _InfoChip(label: 'Gap', value: _gapClassLabels[data.gapClass] ?? data.gapClass!),
              ],
            ),
            if (data.candlestickPatterns.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                'Mum Formasyonu: ${data.candlestickPatterns.map((p) => _candlestickLabels[p] ?? p).join(', ')}',
                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
              ),
              Text(
                'Not: mum formasyonları tek başına bir sinyal değildir, bağlamla birlikte değerlendirilmelidir.',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: Colors.grey, fontStyle: FontStyle.italic),
              ),
            ],
            if (data.nearestSupport != null || data.nearestResistance != null) ...[
              const SizedBox(height: 12),
              if (data.nearestSupport != null)
                Text(
                  'En yakın destek: ${data.nearestSupport!.low.toStringAsFixed(2)}–${data.nearestSupport!.high.toStringAsFixed(2)} TL '
                  '(${data.nearestSupport!.touchCount}x test edildi)',
                  style: const TextStyle(fontSize: 13),
                ),
              if (data.nearestResistance != null)
                Text(
                  'En yakın direnç: ${data.nearestResistance!.low.toStringAsFixed(2)}–${data.nearestResistance!.high.toStringAsFixed(2)} TL '
                  '(${data.nearestResistance!.touchCount}x test edildi)',
                  style: const TextStyle(fontSize: 13),
                ),
            ],
            if (data.breakout != null) ...[const SizedBox(height: 12), _BreakoutInfoRow(breakout: data.breakout!)],
            if (data.mtfConsensus != null && data.mtfConsensus != 'UNKNOWN') ...[
              const SizedBox(height: 12),
              Text(
                'Zaman Dilimi Uyumu: ${_mtfConsensusLabels[data.mtfConsensus] ?? data.mtfConsensus!}',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: data.mtfAligned == true ? FontWeight.bold : FontWeight.normal,
                  color: data.mtfConsensus == 'CONFLICTING' ? Colors.orange : null,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _InfoChip extends StatelessWidget {
  final String label;
  final String value;
  const _InfoChip({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: Colors.grey)),
        Text(value, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
      ],
    );
  }
}

class _BreakoutInfoRow extends StatelessWidget {
  final BreakoutInfo breakout;
  const _BreakoutInfoRow({required this.breakout});

  @override
  Widget build(BuildContext context) {
    final directionLabel = breakout.direction == 'BULLISH' ? 'Yukarı yönlü kırılım' : 'Aşağı yönlü kırılım';
    final statusLabel = breakout.confirmed == true
        ? 'teyitli'
        : breakout.confirmed == false
        ? 'geçersiz (fiyat geri döndü)'
        : 'henüz teyit bekliyor';
    final retestLabel = breakout.retestHeld == true
        ? ' Seviye retest edildi ve tutuldu.'
        : breakout.retestHeld == false
        ? ' Retest\'te seviye kırıldı.'
        : '';
    return Text(
      '$directionLabel ($statusLabel), ${breakout.breakoutAtr.toStringAsFixed(2)} ATR büyüklüğünde.$retestLabel',
      style: const TextStyle(fontSize: 13),
    );
  }
}

/// AŞAMA 66: kullanıcı isteği — "grafiklerde nasıl dirençler var, nasıl
/// çizgiler çizip AL diyorsun, bu direnç var onu kırdı o yüzden alman lazım
/// yükselecek gibisinden açıkla." Fiyat çizgisinin üzerine backend'in ZATEN
/// hesapladığı destek/direnç bölgelerini (SrZone) yatay bant olarak çizer —
/// yeni bir sinyal ÜRETMEZ, mevcut hesaplamayı görselleştirir.
class _SrChartCard extends StatelessWidget {
  final List<PriceBar> bars;
  final List<SrZone> zones;
  final Color lineColor;
  const _SrChartCard({required this.bars, required this.zones, required this.lineColor});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              height: 260,
              width: double.infinity,
              child: CustomPaint(painter: _SrChartPainter(bars: bars, zones: zones, lineColor: lineColor)),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 14,
              runSpacing: 6,
              children: [
                _LegendDot(color: Colors.green, label: 'Destek bölgesi'),
                _LegendDot(color: Colors.red, label: 'Direnç bölgesi'),
                _LegendDot(color: lineColor, label: 'Kapanış fiyatı'),
              ],
            ),
            if (zones.isEmpty) ...[
              const SizedBox(height: 6),
              const Text(
                'Son 6 ayda belirgin bir destek/direnç bölgesi tespit edilemedi.',
                style: TextStyle(fontSize: 11, color: Colors.grey),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _LegendDot extends StatelessWidget {
  final Color color;
  final String label;
  const _LegendDot({required this.color, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 10, height: 10, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
        const SizedBox(width: 4),
        Text(label, style: const TextStyle(fontSize: 11, color: Colors.grey)),
      ],
    );
  }
}

class _SrChartPainter extends CustomPainter {
  final List<PriceBar> bars;
  final List<SrZone> zones;
  final Color lineColor;
  _SrChartPainter({required this.bars, required this.zones, required this.lineColor});

  @override
  void paint(Canvas canvas, Size size) {
    if (bars.length < 2) return;
    final closes = bars.map((b) => b.close).toList();
    final zoneValues = zones.expand((z) => [z.low, z.high]);
    final allValues = [...closes, ...zoneValues];
    final minP = allValues.reduce((a, b) => a < b ? a : b);
    final maxP = allValues.reduce((a, b) => a > b ? a : b);
    final range = (maxP - minP) == 0 ? 1.0 : (maxP - minP);
    // Etiketlerin sığması için sağda boşluk bırakılır.
    const labelWidth = 78.0;
    final chartWidth = (size.width - labelWidth).clamp(0.0, size.width);

    double yFor(double price) => size.height - ((price - minP) / range) * size.height;

    for (final zone in zones) {
      final top = yFor(zone.high).clamp(0.0, size.height);
      final bottom = yFor(zone.low).clamp(0.0, size.height);
      final color = zone.type == 'SUPPORT' ? Colors.green : Colors.red;

      canvas.drawRect(
        Rect.fromLTRB(0, top, chartWidth, bottom < top ? top : bottom),
        Paint()..color = color.withValues(alpha: 0.10),
      );

      final midY = (top + bottom) / 2;
      _drawDashedLine(canvas, Offset(0, midY), Offset(chartWidth, midY), color.withValues(alpha: 0.6));

      final label = '${zone.type == 'SUPPORT' ? 'D' : 'R'} ${zone.mid.toStringAsFixed(2)} (${zone.touchCount}x)';
      final painter = TextPainter(
        text: TextSpan(text: label, style: TextStyle(fontSize: 9, color: color, fontWeight: FontWeight.bold)),
        textDirection: TextDirection.ltr,
      )..layout();
      painter.paint(canvas, Offset(chartWidth + 4, (midY - painter.height / 2).clamp(0.0, size.height - painter.height)));
    }

    final path = Path();
    for (var i = 0; i < closes.length; i++) {
      final x = chartWidth * i / (closes.length - 1);
      final y = yFor(closes[i]);
      if (i == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = lineColor
        ..strokeWidth = 2.2
        ..style = PaintingStyle.stroke
        ..strokeJoin = StrokeJoin.round
        ..strokeCap = StrokeCap.round,
    );
  }

  void _drawDashedLine(Canvas canvas, Offset start, Offset end, Color color) {
    const dashWidth = 6.0;
    const dashSpace = 4.0;
    final paint = Paint()
      ..color = color
      ..strokeWidth = 1;
    final totalDist = end.dx - start.dx;
    if (totalDist <= 0) return;
    double drawn = 0;
    while (drawn < totalDist) {
      final segEnd = (drawn + dashWidth) < totalDist ? drawn + dashWidth : totalDist;
      canvas.drawLine(Offset(start.dx + drawn, start.dy), Offset(start.dx + segEnd, start.dy), paint);
      drawn += dashWidth + dashSpace;
    }
  }

  @override
  bool shouldRepaint(covariant _SrChartPainter oldDelegate) =>
      oldDelegate.bars != bars || oldDelegate.zones != zones || oldDelegate.lineColor != lineColor;
}

const Map<String, String> _eventTypeLabels = {
  'earnings': 'Bilanço/Kâr',
  'regulatory': 'Düzenleyici Karar',
  'corporate_action': 'Kurumsal Eylem',
  'macro': 'Makro Haber',
  'market_sentiment': 'Piyasa Algısı',
  'other': 'Diğer',
};

const Map<String, String> _timeHorizonLabels = {
  'short_term': 'Kısa vadeli etki',
  'medium_term': 'Orta vadeli etki',
  'long_term': 'Uzun vadeli etki',
};

class _NewsTab extends StatefulWidget {
  final String symbol;
  const _NewsTab({required this.symbol});

  @override
  State<_NewsTab> createState() => _NewsTabState();
}

class _NewsTabState extends State<_NewsTab> {
  late Future<List<NewsItem>> _newsFuture;
  late Future<List<NewsAnalysis>> _analysisFuture;
  late Future<Decision> _decisionFuture;
  bool _analyzing = false;

  @override
  void initState() {
    super.initState();
    _newsFuture = NewsApi().fetchNews(widget.symbol);
    _analysisFuture = NewsAnalysisApi().fetchAnalysis(widget.symbol);
    _decisionFuture = DecisionApi().fetchDecision(widget.symbol);
  }

  Future<void> _refresh() async {
    setState(() {
      _newsFuture = NewsApi().fetchNews(widget.symbol);
      _analysisFuture = NewsAnalysisApi().fetchAnalysis(widget.symbol);
      _decisionFuture = DecisionApi().fetchDecision(widget.symbol);
    });
    await Future.wait([_newsFuture, _analysisFuture, _decisionFuture]);
  }

  Future<void> _analyzeNow(int newsCount) async {
    setState(() => _analyzing = true);
    try {
      // Ekrandaki HER haberi kapsayacak şekilde analiz iste — zaten analiz
      // edilmiş olanlar backend'de otomatik atlanır, tekrar maliyet oluşturmaz.
      await NewsAnalysisApi().analyze(widget.symbol, limit: newsCount);
      setState(() {
        _analysisFuture = NewsAnalysisApi().fetchAnalysis(widget.symbol);
      });
      await _analysisFuture;
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Analiz hatası: $e')));
      }
    } finally {
      if (mounted) setState(() => _analyzing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: FutureBuilder<List<NewsItem>>(
        future: _newsFuture,
        builder: (context, newsSnapshot) {
          if (newsSnapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (newsSnapshot.hasError) {
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [Center(child: Text('Hata: ${newsSnapshot.error}'))],
            );
          }
          final items = newsSnapshot.data!;
          return FutureBuilder<List<NewsAnalysis>>(
            future: _analysisFuture,
            builder: (context, analysisSnapshot) {
              final analysisById = <String, NewsAnalysis>{
                for (final a in analysisSnapshot.data ?? const <NewsAnalysis>[]) a.newsId: a,
              };
              return ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(12),
                children: [
                  FutureBuilder<Decision>(
                    future: _decisionFuture,
                    builder: (context, decisionSnapshot) {
                      if (decisionSnapshot.connectionState != ConnectionState.done ||
                          !decisionSnapshot.hasData) {
                        return const SizedBox.shrink();
                      }
                      final d = decisionSnapshot.data!;
                      final color = decisionColor(d.decision);
                      return Card(
                        color: color.withValues(alpha: 0.1),
                        margin: const EdgeInsets.only(bottom: 12),
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Row(
                            children: [
                              Icon(Icons.smart_toy_outlined, color: color),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  'AI Kararımız: ${decisionLabel(d.decision)} (skor ${d.finalScore >= 0 ? '+' : ''}'
                                  '${d.finalScore.toStringAsFixed(1)}, güven %${d.confidence.toStringAsFixed(0)})',
                                  style: TextStyle(fontWeight: FontWeight.bold, color: color),
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                  const Text(
                    'Aşağıdaki "Analist" etiketli haberler banka/aracı kurum hedef fiyat ve '
                    'tavsiyelerini yansıtan gerçek kaynaklardır — belirli bir analistin görüşü '
                    'olarak sunulur, AI kararımızla karşılaştırıp kendi değerlendirmenizi yapın.',
                    style: TextStyle(fontSize: 11, color: Colors.grey),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          'Haberler, OpenAI GPT-5.6 Luna ile duygu/etki analizi yapılarak gösterilir.',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey),
                        ),
                      ),
                      const SizedBox(width: 8),
                      OutlinedButton.icon(
                        onPressed: _analyzing ? null : () => _analyzeNow(items.length),
                        icon: _analyzing
                            ? const SizedBox(
                                width: 14,
                                height: 14,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Icon(Icons.psychology_outlined, size: 18),
                        label: const Text('Analiz Et'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  if (items.isEmpty) const Text('Haber bulunamadı.'),
                  ...items.map((item) => _NewsCard(item: item, analysis: analysisById[item.externalId])),
                ],
              );
            },
          );
        },
      ),
    );
  }
}

class _NewsCard extends StatelessWidget {
  final NewsItem item;
  final NewsAnalysis? analysis;
  const _NewsCard({required this.item, required this.analysis});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        onTap: () => openExternalUrl(context, item.url),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (item.isAnalystMention) ...[
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: Colors.indigo.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    item.analystFirm != null ? 'Analist / Hedef Fiyat — ${item.analystFirm}' : 'Analist / Hedef Fiyat',
                    style: const TextStyle(color: Colors.indigo, fontWeight: FontWeight.bold, fontSize: 11),
                  ),
                ),
                const SizedBox(height: 6),
              ],
              Text(item.title, style: const TextStyle(fontWeight: FontWeight.bold)),
              if (item.summary.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(item.summary, maxLines: 3, overflow: TextOverflow.ellipsis),
              ],
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(item.publisher, style: const TextStyle(color: Colors.grey)),
                  Text('Güvenilirlik: %${(item.sourceReliability * 100).toStringAsFixed(0)}'),
                ],
              ),
              const SizedBox(height: 8),
              if (analysis == null)
                const Text(
                  'Bu haber henüz AI ile analiz edilmedi.',
                  style: TextStyle(color: Colors.orange, fontStyle: FontStyle.italic, fontSize: 12),
                )
              else
                _AnalysisBadge(analysis: analysis!),
            ],
          ),
        ),
      ),
    );
  }
}

class _AnalysisBadge extends StatelessWidget {
  final NewsAnalysis analysis;
  const _AnalysisBadge({required this.analysis});

  @override
  Widget build(BuildContext context) {
    // Tek bir haberin duygu skoru, Dashboard'daki AL/TUT/SAT kararıyla AYNI
    // eşiklerle (DecisionEngine.DEFAULT_THRESHOLDS) sınıflandırılır — bu
    // haberin TEK BAŞINA bir varlık kararı olmadığını, yalnızca o haberin
    // yönünü aynı ölçekte gösterdiğini unutmayın.
    final decision = classifyScore(analysis.sentimentScore);
    final color = decisionColor(decision);
    final label = decisionLabel(decision);
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(6)),
                child: Text(
                  label,
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 12),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '${_eventTypeLabels[analysis.eventType] ?? analysis.eventType} · '
                  '${analysis.sentimentScore >= 0 ? '+' : ''}${analysis.sentimentScore.toStringAsFixed(0)} puan',
                  style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 13),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            'Güven %${(analysis.confidence * 100).toStringAsFixed(0)} · Etki %${(analysis.importance * 100).toStringAsFixed(0)} · '
            '${_timeHorizonLabels[analysis.timeHorizon] ?? analysis.timeHorizon}',
            style: const TextStyle(fontSize: 11, color: Colors.grey),
          ),
          const SizedBox(height: 6),
          Text(analysis.reasoning, style: const TextStyle(fontSize: 12, fontStyle: FontStyle.italic)),
        ],
      ),
    );
  }
}

const Map<String, String> _recommendationPeriodLabelsTr = {
  '0m': 'Bu ay',
  '-1m': '1 ay önce',
  '-2m': '2 ay önce',
  '-3m': '3 ay önce',
};

Color _consensusColor(String label) {
  switch (label) {
    case 'GUCLU_AL':
    case 'AL':
      return Colors.green;
    case 'GUCLU_SAT':
    case 'SAT':
      return Colors.red;
    case 'TUT':
      return Colors.orange;
    default:
      return Colors.grey;
  }
}

/// AŞAMA 63: kullanıcı isteği "analistlerin değerlendirmeleri bulunsun, al mı
/// diyorlar sat mı diyorlar, istediğin yerden çekebilirsin" — burada GERÇEK
/// banka/aracı kurum analist verisi (Yahoo Finance üzerinden, engines/analysts/
/// consensus.py) gösterilir; keyword tabanlı bir tahmin DEĞİL, gerçek AL/TUT/SAT
/// sayıları ve hedef fiyat konsensüsüdür. AI kararımızla yan yana karşılaştırma
/// için aynı ekranda Decision de gösterilir.
class _AnalystsTab extends StatefulWidget {
  final String symbol;
  const _AnalystsTab({required this.symbol});

  @override
  State<_AnalystsTab> createState() => _AnalystsTabState();
}

class _AnalystsTabState extends State<_AnalystsTab> {
  late Future<AnalystConsensus> _consensusFuture;
  late Future<Decision> _decisionFuture;
  late Future<List<NewsItem>> _newsFuture;

  @override
  void initState() {
    super.initState();
    _consensusFuture = AnalystApi().fetchConsensus(widget.symbol);
    _decisionFuture = DecisionApi().fetchDecision(widget.symbol);
    _newsFuture = NewsApi().fetchNews(widget.symbol);
  }

  Future<void> _refresh() async {
    setState(() {
      _consensusFuture = AnalystApi().fetchConsensus(widget.symbol);
      _decisionFuture = DecisionApi().fetchDecision(widget.symbol);
      _newsFuture = NewsApi().fetchNews(widget.symbol);
    });
    await Future.wait([_consensusFuture, _decisionFuture, _newsFuture]);
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: FutureBuilder<AnalystConsensus>(
        future: _consensusFuture,
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
          final consensus = snapshot.data!;
          final color = _consensusColor(consensus.consensusLabel);
          return ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(12),
            children: [
              Card(
                color: color.withValues(alpha: 0.1),
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                            decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(8)),
                            child: Text(
                              analystConsensusLabelsTr[consensus.consensusLabel] ?? consensus.consensusLabel,
                              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16),
                            ),
                          ),
                          Text(
                            '${consensus.totalAnalysts} analist',
                            style: const TextStyle(color: Colors.grey, fontWeight: FontWeight.w600),
                          ),
                        ],
                      ),
                      if (consensus.totalAnalysts == 0) ...[
                        const SizedBox(height: 10),
                        const Text(
                          'Bu hisse için Yahoo Finance üzerinde aktif analist takibi bulunmuyor. '
                          'Küçük/orta ölçekli şirketlerde bu normaldir — büyük bankalar genelde '
                          'BIST30/BIST100 ağırlıklı hisseleri takip eder.',
                          style: TextStyle(fontSize: 12, color: Colors.grey),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
              if (consensus.totalAnalysts > 0) ...[
                const SizedBox(height: 12),
                _RecommendationBreakdownCard(consensus: consensus),
              ],
              if (consensus.priceTargetMean != null) ...[
                const SizedBox(height: 12),
                _PriceTargetCard(consensus: consensus),
              ],
              const SizedBox(height: 12),
              FutureBuilder<Decision>(
                future: _decisionFuture,
                builder: (context, decisionSnapshot) {
                  if (decisionSnapshot.connectionState != ConnectionState.done || !decisionSnapshot.hasData) {
                    return const SizedBox.shrink();
                  }
                  final d = decisionSnapshot.data!;
                  final dColor = decisionColor(d.decision);
                  return Card(
                    color: dColor.withValues(alpha: 0.1),
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Row(
                        children: [
                          Icon(Icons.smart_toy_outlined, color: dColor),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              'AI Kararımız: ${decisionLabel(d.decision)} (skor ${d.finalScore >= 0 ? '+' : ''}'
                              '${d.finalScore.toStringAsFixed(1)}, güven %${d.confidence.toStringAsFixed(0)}) — '
                              'yukarıdaki analist konsensüsüyle karşılaştırıp kendi değerlendirmenizi yapın.',
                              style: TextStyle(fontWeight: FontWeight.bold, color: dColor, fontSize: 13),
                            ),
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
              if (consensus.trend.length > 1) ...[
                const SizedBox(height: 16),
                const Text('Zaman İçinde Değişim', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                ...consensus.trend.map((t) => _TrendRow(period: t)),
              ],
              const SizedBox(height: 16),
              const Text('Kim Ne Dedi?', style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 4),
              const Text(
                'Gerçek haber kaynaklarında bulunan, banka/aracı kurum adı geçen hedef fiyat '
                've tavsiye haberleri — isim uydurulmaz, yalnızca başlık/özette geçen gerçek '
                'kurum adı gösterilir.',
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
                    return Text('Hata: ${newsSnapshot.error}');
                  }
                  final mentions = (newsSnapshot.data ?? const <NewsItem>[])
                      .where((n) => n.isAnalystMention)
                      .toList();
                  if (mentions.isEmpty) {
                    return const Text(
                      'Bu hisseyle ilgili analist/hedef fiyat haberi bulunamadı.',
                      style: TextStyle(color: Colors.grey, fontSize: 12),
                    );
                  }
                  return Column(children: mentions.map((n) => _AnalystMentionCard(item: n)).toList());
                },
              ),
              const SizedBox(height: 16),
              Text(
                'Kaynak: Yahoo Finance — banka/aracı kurum analistlerinin gerçek AL/TUT/SAT '
                'oy dağılımı ve hedef fiyat verileri (${consensus.asOf.toLocal().day.toString().padLeft(2, '0')}.'
                '${consensus.asOf.toLocal().month.toString().padLeft(2, '0')}.${consensus.asOf.toLocal().year} itibarıyla).',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _AnalystMentionCard extends StatelessWidget {
  final NewsItem item;
  const _AnalystMentionCard({required this.item});

  static String _fmtDate(DateTime date) {
    final local = date.toLocal();
    final day = local.day.toString().padLeft(2, '0');
    final month = local.month.toString().padLeft(2, '0');
    return '$day.$month.${local.year}';
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        onTap: () => openExternalUrl(context, item.url),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (item.analystFirm != null)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: Colors.indigo.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    item.analystFirm!,
                    style: const TextStyle(color: Colors.indigo, fontWeight: FontWeight.bold, fontSize: 12),
                  ),
                ),
              if (item.analystFirm != null) const SizedBox(height: 6),
              Text(item.title, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
              if (item.summary.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(item.summary, maxLines: 3, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12)),
              ],
              const SizedBox(height: 6),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('${item.publisher} · ${_fmtDate(item.publishedAt)}',
                      style: const TextStyle(fontSize: 11, color: Colors.grey)),
                  Text('Güvenilirlik: %${(item.sourceReliability * 100).toStringAsFixed(0)}',
                      style: const TextStyle(fontSize: 11, color: Colors.grey)),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _RecommendationBreakdownCard extends StatelessWidget {
  final AnalystConsensus consensus;
  const _RecommendationBreakdownCard({required this.consensus});

  @override
  Widget build(BuildContext context) {
    final rows = <(String, int, Color)>[
      ('Güçlü Al', consensus.strongBuy, Colors.green.shade700),
      ('Al', consensus.buy, Colors.green),
      ('Tut', consensus.hold, Colors.orange),
      ('Sat', consensus.sell, Colors.red),
      ('Güçlü Sat', consensus.strongSell, Colors.red.shade700),
    ];
    final maxCount = rows.map((r) => r.$2).fold(0, (a, b) => a > b ? a : b);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Analist Dağılımı', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            ...rows.map((r) {
              final (label, count, color) = r;
              final fraction = maxCount == 0 ? 0.0 : count / maxCount;
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  children: [
                    SizedBox(width: 72, child: Text(label, style: const TextStyle(fontSize: 12))),
                    Expanded(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: LinearProgressIndicator(
                          value: fraction,
                          minHeight: 10,
                          backgroundColor: color.withValues(alpha: 0.1),
                          valueColor: AlwaysStoppedAnimation(color),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    SizedBox(width: 20, child: Text('$count', style: const TextStyle(fontSize: 12))),
                  ],
                ),
              );
            }),
          ],
        ),
      ),
    );
  }
}

class _PriceTargetCard extends StatelessWidget {
  final AnalystConsensus consensus;
  const _PriceTargetCard({required this.consensus});

  @override
  Widget build(BuildContext context) {
    final upside = consensus.upsidePct;
    final upsideColor = upside == null ? Colors.grey : (upside >= 0 ? Colors.green : Colors.red);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Hedef Fiyat Konsensüsü', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            Wrap(
              spacing: 24,
              runSpacing: 10,
              children: [
                _InfoChip(label: 'Güncel Fiyat', value: '${consensus.priceTargetCurrent?.toStringAsFixed(2) ?? '—'} TL'),
                _InfoChip(label: 'Ortalama Hedef', value: '${consensus.priceTargetMean?.toStringAsFixed(2) ?? '—'} TL'),
                _InfoChip(label: 'Medyan Hedef', value: '${consensus.priceTargetMedian?.toStringAsFixed(2) ?? '—'} TL'),
                _InfoChip(label: 'En Düşük', value: '${consensus.priceTargetLow?.toStringAsFixed(2) ?? '—'} TL'),
                _InfoChip(label: 'En Yüksek', value: '${consensus.priceTargetHigh?.toStringAsFixed(2) ?? '—'} TL'),
              ],
            ),
            if (upside != null) ...[
              const SizedBox(height: 12),
              Text(
                'Ortalama hedefe göre potansiyel: ${upside >= 0 ? '+' : ''}${upside.toStringAsFixed(1)}%',
                style: TextStyle(color: upsideColor, fontWeight: FontWeight.bold),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _TrendRow extends StatelessWidget {
  final AnalystRecommendationPeriod period;
  const _TrendRow({required this.period});

  @override
  Widget build(BuildContext context) {
    final label = _recommendationPeriodLabelsTr[period.period] ?? (period.period ?? '-');
    return Card(
      margin: const EdgeInsets.only(bottom: 6),
      child: ListTile(
        dense: true,
        title: Text(label),
        trailing: Text(
          'Al: ${period.strongBuy + period.buy}   Tut: ${period.hold}   Sat: ${period.sell + period.strongSell}',
          style: const TextStyle(fontSize: 12),
        ),
      ),
    );
  }
}

/// AŞAMA 62: "Karar Günlüğü" — kullanıcı isteği: "her test yaptığımızda veri
/// tutsun, hatalarımızdan ders çıkaralım, nerede düştü hangi sebepten."
/// Geçmiş tarihli haber/makro arşivi olmadığından (bkz. AŞAMA 57/60) GEÇMİŞE
/// dönük sahte bir "o zamanki ortam" gösterilmez — bunun yerine BUGÜNDEN
/// İTİBAREN biriken GERÇEK kararlar, gerçek sonraki fiyat hareketiyle (7/30
/// gün ufku) karşılaştırılıp gösterilir; "hangi sebepten" sorusuna da o an
/// hangi skor bileşeninin (teknik/haber/makro) baskın olduğu ile cevap verilir.
class _HistoryTab extends StatefulWidget {
  final String symbol;
  const _HistoryTab({required this.symbol});

  @override
  State<_HistoryTab> createState() => _HistoryTabState();
}

class _HistoryTabState extends State<_HistoryTab> {
  late Future<List<DecisionJournalEntry>> _future;

  @override
  void initState() {
    super.initState();
    _future = DecisionApi().fetchJournal(widget.symbol);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<DecisionJournalEntry>>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(child: Text('Hata: ${snapshot.error}'));
        }
        final entries = snapshot.data!;
        if (entries.isEmpty) {
          return const Center(child: Text('Henüz bir karar kaydı yok.'));
        }
        return ListView.separated(
          padding: const EdgeInsets.all(12),
          itemCount: entries.length,
          separatorBuilder: (_, _) => const SizedBox(height: 8),
          itemBuilder: (context, index) => _JournalEntryCard(entry: entries[index]),
        );
      },
    );
  }
}

class _JournalEntryCard extends StatelessWidget {
  final DecisionJournalEntry entry;
  const _JournalEntryCard({required this.entry});

  static String _fmtDate(DateTime? date) {
    if (date == null) return '-';
    final local = date.toLocal();
    final day = local.day.toString().padLeft(2, '0');
    final month = local.month.toString().padLeft(2, '0');
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '$day.$month $hour:$minute';
  }

  static Color _outcomeColor(String status) {
    switch (status) {
      case 'DOGRU':
        return Colors.green;
      case 'YANLIS':
        return Colors.red;
      case 'BEKLEMEDE':
        return Colors.orange;
      default:
        return Colors.grey;
    }
  }

  Widget _outcomeChip(String horizonLabel, DecisionOutcome? outcome) {
    if (outcome == null) return const SizedBox.shrink();
    final color = _outcomeColor(outcome.status);
    final returnText = outcome.realizedReturnPct != null
        ? ' (${outcome.realizedReturnPct! >= 0 ? '+' : ''}${outcome.realizedReturnPct!.toStringAsFixed(1)}%)'
        : '';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      margin: const EdgeInsets.only(right: 6, top: 4),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(6)),
      child: Text(
        '$horizonLabel: ${outcomeStatusLabelsTr[outcome.status] ?? outcome.status}$returnText',
        style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 11),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final d = entry.decision;
    final label = decisionLabel(d.decision);
    final color = decisionColor(d.decision);
    final factor = entry.dominantFactor;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(label, style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 15)),
                ),
                Text(_fmtDate(d.createdAt), style: const TextStyle(fontSize: 11, color: Colors.grey)),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              'Skor: ${d.finalScore.toStringAsFixed(1)}   Güven: %${d.confidence.toStringAsFixed(0)}'
              '${factor != null ? '   Ağırlıklı sebep: ${dominantFactorLabelsTr[factor] ?? factor}' : ''}',
              style: const TextStyle(fontSize: 12),
            ),
            Wrap(
              children: [
                _outcomeChip('7 gün', entry.outcomes['7']),
                _outcomeChip('30 gün', entry.outcomes['30']),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _PerformanceTab extends StatefulWidget {
  final String symbol;
  const _PerformanceTab({required this.symbol});

  @override
  State<_PerformanceTab> createState() => _PerformanceTabState();
}

class _PerformanceTabState extends State<_PerformanceTab> {
  late Future<BacktestResult> _future;

  @override
  void initState() {
    super.initState();
    _future = BacktestApi().fetchBacktest(widget.symbol);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<BacktestResult>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(child: Text('Hata: ${snapshot.error}'));
        }
        final r = snapshot.data!;
        final color = r.totalReturnPct >= 0 ? Colors.green : Colors.red;
        return ListView(
          padding: const EdgeInsets.all(12),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${r.fromDate} — ${r.toDate}', style: const TextStyle(color: Colors.grey)),
                    const SizedBox(height: 8),
                    Text(
                      'Strateji Getirisi: ${r.totalReturnPct >= 0 ? '+' : ''}${r.totalReturnPct.toStringAsFixed(1)}%',
                      style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 18),
                    ),
                    Text(
                      'Al-Tut Getirisi: ${r.buyAndHoldReturnPct >= 0 ? '+' : ''}${r.buyAndHoldReturnPct.toStringAsFixed(1)}%',
                    ),
                    Text('Maksimum Düşüş: ${r.maxDrawdownPct.toStringAsFixed(1)}%'),
                    Text('İşlem Sayısı: ${r.tradeCount}   Kazanma Oranı: %${r.winRatePct.toStringAsFixed(0)}'),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            const Text('İşlemler', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            Text(
              'Bu strateji her zaman önce alır, sonra satar (açığa satış yok). '
              'Yeşil: satış fiyatı alış fiyatından yüksek — kâr. '
              'Kırmızı: satış fiyatı alış fiyatından düşük — zarar.',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey),
            ),
            const SizedBox(height: 8),
            if (r.trades.isEmpty) const Text('Bu dönemde işlem yapılmadı.'),
            ...r.trades.reversed.map((t) => _TradeCard(trade: t)),
          ],
        );
      },
    );
  }
}

String _fmtTradeDate(String iso) {
  final parsed = DateTime.parse(iso);
  final day = parsed.day.toString().padLeft(2, '0');
  final month = parsed.month.toString().padLeft(2, '0');
  return '$day.$month.${parsed.year}';
}

class _TradeCard extends StatelessWidget {
  final BacktestTrade trade;
  const _TradeCard({required this.trade});

  @override
  Widget build(BuildContext context) {
    final isProfit = trade.returnPct >= 0;
    final color = isProfit ? Colors.green : Colors.red;
    final priceDirection = isProfit ? 'yükseldi' : 'düştü';
    final result = isProfit ? 'kâr edildi' : 'zarar edildi';

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Container(
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: color.withValues(alpha: 0.25)),
        ),
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(isProfit ? Icons.trending_up : Icons.trending_down, color: color, size: 20),
                const SizedBox(width: 6),
                Text(
                  '${isProfit ? '+' : ''}${trade.returnPct.toStringAsFixed(1)}%',
                  style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 16),
                ),
                const Spacer(),
                Text(
                  '${_fmtTradeDate(trade.entryDate)} — ${_fmtTradeDate(trade.exitDate)}',
                  style: const TextStyle(fontSize: 11, color: Colors.grey),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              '${_fmtTradeDate(trade.entryDate)}\'de ${trade.entryPrice.toStringAsFixed(2)} TL\'den alındı, '
              '${_fmtTradeDate(trade.exitDate)}\'de ${trade.exitPrice.toStringAsFixed(2)} TL\'den satıldı. '
              'Fiyat %${trade.returnPct.abs().toStringAsFixed(1)} $priceDirection, $result.',
              style: const TextStyle(fontSize: 13),
            ),
          ],
        ),
      ),
    );
  }
}

class _PriceTab extends StatefulWidget {
  final String symbol;
  const _PriceTab({required this.symbol});

  @override
  State<_PriceTab> createState() => _PriceTabState();
}

class _PriceTabState extends State<_PriceTab> {
  late Future<PriceQuote> _quoteFuture;
  late Future<Map<String, double?>> _changesFuture;
  late Future<List<PriceBar>> _historyFuture;
  String _selectedPeriod = '1A';

  @override
  void initState() {
    super.initState();
    _quoteFuture = MarketDataApi().fetchQuote(widget.symbol);
    _changesFuture = MarketDataApi().fetchChanges(widget.symbol);
    _historyFuture = _fetchHistory();
  }

  Future<List<PriceBar>> _fetchHistory() {
    final opt = _chartPeriods[_selectedPeriod]!;
    return MarketDataApi().fetchHistory(widget.symbol, period: opt.period, interval: opt.interval);
  }

  Future<void> _refresh() async {
    setState(() {
      _quoteFuture = MarketDataApi().fetchQuote(widget.symbol);
      _changesFuture = MarketDataApi().fetchChanges(widget.symbol);
      _historyFuture = _fetchHistory();
    });
    await Future.wait([_quoteFuture, _changesFuture, _historyFuture]);
  }

  void _selectPeriod(String period) {
    setState(() {
      _selectedPeriod = period;
      _historyFuture = _fetchHistory();
    });
  }

  String _fmtTimestamp(DateTime ts) {
    final local = ts.toLocal();
    final day = local.day.toString().padLeft(2, '0');
    final month = local.month.toString().padLeft(2, '0');
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '$day.$month.${local.year} $hour:$minute';
  }

  Future<void> _showQuickBuyDialog(BuildContext context, double lastPrice) async {
    final priceController = TextEditingController(text: lastPrice.toStringAsFixed(2));
    final quantityController = TextEditingController();
    bool saving = false;

    final saved = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (dialogContext, setDialogState) {
            return AlertDialog(
              title: Text('${widget.symbol} — Portföye Ekle'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: priceController,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(labelText: 'Alış Fiyatı (TL)'),
                  ),
                  TextField(
                    controller: quantityController,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(labelText: 'Adet'),
                    autofocus: true,
                  ),
                ],
              ),
              actions: [
                TextButton(
                  onPressed: saving ? null : () => Navigator.pop(dialogContext, false),
                  child: const Text('İptal'),
                ),
                FilledButton(
                  onPressed: saving
                      ? null
                      : () async {
                          final price = double.tryParse(priceController.text);
                          final quantity = double.tryParse(quantityController.text);
                          if (price == null || quantity == null || quantity <= 0) return;
                          setDialogState(() => saving = true);
                          try {
                            await PortfolioApi().createPosition(
                              asset: widget.symbol,
                              buyPrice: price,
                              quantity: quantity,
                              buyDate: DateTime.now(),
                            );
                            if (dialogContext.mounted) Navigator.pop(dialogContext, true);
                          } catch (e) {
                            setDialogState(() => saving = false);
                            if (dialogContext.mounted) {
                              ScaffoldMessenger.of(dialogContext).showSnackBar(
                                SnackBar(content: Text('Eklenemedi: $e')),
                              );
                            }
                          }
                        },
                  child: saving
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('Ekle'),
                ),
              ],
            );
          },
        );
      },
    );

    if (saved == true && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${widget.symbol} portföye eklendi.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: FutureBuilder<PriceQuote>(
        future: _quoteFuture,
        builder: (context, quoteSnapshot) {
          if (quoteSnapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (quoteSnapshot.hasError) {
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [Center(child: Text('Hata: ${quoteSnapshot.error}'))],
            );
          }
          final quote = quoteSnapshot.data!;
          final color = quote.change >= 0 ? Colors.green : Colors.red;

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
                        '${quote.lastPrice.toStringAsFixed(2)} TL',
                        style: const TextStyle(fontSize: 32, fontWeight: FontWeight.bold),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '${quote.change >= 0 ? '+' : ''}${quote.change.toStringAsFixed(2)} '
                        '(${quote.changePercent == null ? '—' : '${quote.changePercent! >= 0 ? '+' : ''}${quote.changePercent!.toStringAsFixed(2)}%'})',
                        style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 16),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Önceki kapanış: ${quote.previousClose.toStringAsFixed(2)} TL',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      Text(
                        'Güncelleme: ${_fmtTimestamp(quote.timestamp)} '
                        '(Yahoo Finance, hafif gecikmeli olabilir)',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey),
                      ),
                      const SizedBox(height: 12),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          style: FilledButton.styleFrom(backgroundColor: Colors.green),
                          onPressed: () => _showQuickBuyDialog(context, quote.lastPrice),
                          icon: const Icon(Icons.add_shopping_cart),
                          label: const Text('AL — Portföye Ekle'),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(child: _MiniStat(label: 'Açılış', value: quote.open.toStringAsFixed(2))),
                  Expanded(child: _MiniStat(label: 'Yüksek', value: quote.high.toStringAsFixed(2))),
                  Expanded(child: _MiniStat(label: 'Düşük', value: quote.low.toStringAsFixed(2))),
                  Expanded(child: _MiniStat(label: 'Hacim', value: _fmtVolume(quote.volume))),
                ],
              ),
              const SizedBox(height: 16),
              const Text('Fiyat Grafiği', style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                children: _chartPeriods.keys
                    .map(
                      (p) => ChoiceChip(
                        label: Text(p),
                        selected: _selectedPeriod == p,
                        onSelected: (_) => _selectPeriod(p),
                      ),
                    )
                    .toList(),
              ),
              const SizedBox(height: 12),
              FutureBuilder<List<PriceBar>>(
                future: _historyFuture,
                builder: (context, histSnapshot) {
                  if (histSnapshot.connectionState != ConnectionState.done) {
                    return const SizedBox(height: 180, child: Center(child: CircularProgressIndicator()));
                  }
                  if (histSnapshot.hasError) {
                    return SizedBox(height: 180, child: Center(child: Text('Hata: ${histSnapshot.error}')));
                  }
                  final bars = histSnapshot.data!;
                  if (bars.isEmpty) {
                    return const SizedBox(height: 180, child: Center(child: Text('Veri yok')));
                  }
                  final closes = bars.map((b) => b.close).toList();
                  return Card(
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          _Sparkline(prices: closes, color: color),
                          const SizedBox(height: 8),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(
                                _fmtTimestamp(bars.first.timestamp),
                                style: const TextStyle(fontSize: 11, color: Colors.grey),
                              ),
                              Text(
                                _fmtTimestamp(bars.last.timestamp),
                                style: const TextStyle(fontSize: 11, color: Colors.grey),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
              const SizedBox(height: 16),
              const Text('Yüzde Değişim', style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              FutureBuilder<Map<String, double?>>(
                future: _changesFuture,
                builder: (context, changesSnapshot) {
                  if (changesSnapshot.connectionState != ConnectionState.done) {
                    return const Padding(
                      padding: EdgeInsets.all(8),
                      child: Center(child: CircularProgressIndicator()),
                    );
                  }
                  if (changesSnapshot.hasError) {
                    return Text('Hata: ${changesSnapshot.error}');
                  }
                  final changes = changesSnapshot.data!;
                  return Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: _changeLabels.entries.map((entry) {
                      final pct = changes[entry.key];
                      final pctColor = pct == null ? Colors.grey : (pct >= 0 ? Colors.green : Colors.red);
                      return Card(
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                          child: Column(
                            children: [
                              Text(entry.value, style: const TextStyle(fontSize: 11, color: Colors.grey)),
                              Text(
                                pct == null ? 'Veri yok' : '${pct >= 0 ? '+' : ''}${pct.toStringAsFixed(2)}%',
                                style: TextStyle(color: pctColor, fontWeight: FontWeight.bold),
                              ),
                            ],
                          ),
                        ),
                      );
                    }).toList(),
                  );
                },
              ),
            ],
          );
        },
      ),
    );
  }

  String _fmtVolume(int volume) {
    if (volume >= 1000000) return '${(volume / 1000000).toStringAsFixed(1)}M';
    if (volume >= 1000) return '${(volume / 1000).toStringAsFixed(1)}K';
    return volume.toString();
  }
}

class _MiniStat extends StatelessWidget {
  final String label;
  final String value;
  const _MiniStat({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: Colors.grey)),
        const SizedBox(height: 2),
        Text(value, style: const TextStyle(fontWeight: FontWeight.bold)),
      ],
    );
  }
}

class _Sparkline extends StatelessWidget {
  final List<double> prices;
  final Color color;
  const _Sparkline({required this.prices, required this.color});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 160,
      width: double.infinity,
      child: CustomPaint(painter: _SparklinePainter(prices: prices, color: color)),
    );
  }
}

class _SparklinePainter extends CustomPainter {
  final List<double> prices;
  final Color color;
  _SparklinePainter({required this.prices, required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    if (prices.length < 2) return;
    final minP = prices.reduce((a, b) => a < b ? a : b);
    final maxP = prices.reduce((a, b) => a > b ? a : b);
    final range = (maxP - minP) == 0 ? 1.0 : (maxP - minP);

    final path = Path();
    for (var i = 0; i < prices.length; i++) {
      final x = size.width * i / (prices.length - 1);
      final y = size.height - ((prices[i] - minP) / range) * size.height;
      if (i == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    }

    final linePaint = Paint()
      ..color = color
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke
      ..strokeJoin = StrokeJoin.round
      ..strokeCap = StrokeCap.round;
    canvas.drawPath(path, linePaint);

    final fillPath = Path.from(path)
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();
    final fillPaint = Paint()
      ..shader = LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [color.withValues(alpha: 0.25), color.withValues(alpha: 0.0)],
      ).createShader(Rect.fromLTWH(0, 0, size.width, size.height));
    canvas.drawPath(fillPath, fillPaint);
  }

  @override
  bool shouldRepaint(covariant _SparklinePainter oldDelegate) =>
      oldDelegate.prices != prices || oldDelegate.color != color;
}

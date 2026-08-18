import 'package:flutter/material.dart';

import '../../utils/decision_style.dart';

class GuideScreen extends StatelessWidget {
  const GuideScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Gösterge Rehberi')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: const [
          Text(
            'Analiz, Portföy, Makro ve varlık detay ekranlarında gördüğün skorları, '
            'yüzdeleri ve etiketleri neyin üzerine hesapladığımızı açıklar. Sırayla '
            'okumana gerek yok — bir bölüme dokunup açabilirsin.',
            style: TextStyle(color: Colors.grey, height: 1.4),
          ),
          SizedBox(height: 16),
          _AnalizSection(),
          _TeknikSection(),
          _HaberlerSection(),
          _GecmisSection(),
          _PerformansSection(),
          _MacroSection(),
          _PortfoySection(),
        ],
      ),
    );
  }
}

class _GuideSection extends StatelessWidget {
  final String tag;
  final String title;
  final String description;
  final List<Widget> children;

  const _GuideSection({
    required this.tag,
    required this.title,
    required this.description,
    required this.children,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: ExpansionTile(
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text(
          tag,
          style: TextStyle(color: Theme.of(context).colorScheme.primary, fontSize: 12),
        ),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(description, style: const TextStyle(color: Colors.black54, height: 1.4)),
          const SizedBox(height: 14),
          ...children,
        ],
      ),
    );
  }
}

class _Term extends StatelessWidget {
  final String term;
  final String? range;
  final String description;
  final String? formula;

  const _Term({required this.term, this.range, required this.description, this.formula});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(child: Text(term, style: const TextStyle(fontWeight: FontWeight.w600))),
              if (range != null)
                Padding(
                  padding: const EdgeInsets.only(left: 8),
                  child: Text(
                    range!,
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 11, color: Colors.grey),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 4),
          Text(description, style: const TextStyle(height: 1.4)),
          if (formula != null) ...[
            const SizedBox(height: 6),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              decoration: BoxDecoration(
                color: Colors.grey.shade100,
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(formula!, style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
            ),
          ],
        ],
      ),
    );
  }
}

class _Note extends StatelessWidget {
  final String text;
  const _Note({required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.amber.shade50,
        border: Border(left: BorderSide(color: Colors.amber.shade700, width: 3)),
        borderRadius: const BorderRadius.only(
          topRight: Radius.circular(6),
          bottomRight: Radius.circular(6),
        ),
      ),
      child: Text(text, style: const TextStyle(fontSize: 13, height: 1.4)),
    );
  }
}

class _ThresholdTable extends StatelessWidget {
  const _ThresholdTable();

  static const _rows = [
    ('+40 ve üzeri', 'BUY'),
    ('+15 … +39', 'WEAK_BUY'),
    ('−14 … +14', 'HOLD'),
    ('−39 … −15', 'WEAK_SELL'),
    ('−40 ve altı', 'SELL'),
  ];

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
      decoration: BoxDecoration(
        border: Border.all(color: Colors.grey.shade300),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        children: _rows.map((r) {
          final (range, decision) = r;
          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(range, style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                  decoration: BoxDecoration(
                    color: decisionColor(decision).withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    decisionLabel(decision),
                    style: TextStyle(
                      color: decisionColor(decision),
                      fontWeight: FontWeight.bold,
                      fontSize: 12,
                    ),
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }
}

class _AnalizSection extends StatelessWidget {
  const _AnalizSection();

  @override
  Widget build(BuildContext context) {
    return _GuideSection(
      tag: 'Alt sekme · Analiz',
      title: 'Piyasa Analizi kartları',
      description:
          'Her kart bir hisse için üretilen AL/SAT/TUT kararını ve bu kararı besleyen üç '
          'ayrı skoru gösterir. Karar, bu skorların ağırlıklı ortalaması olan tek bir "final '
          'skor"a göre belirlenir.',
      children: const [
        Text('Karar eşikleri', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
        SizedBox(height: 8),
        _ThresholdTable(),
        SizedBox(height: 16),
        Text('Kart üzerindeki alanlar', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
        SizedBox(height: 8),
        _Term(
          term: 'Confidence (Güven)',
          range: '%0–100',
          description: 'Karara ne kadar güvenilebileceği. Göstergelerin birbiriyle ne kadar '
              'aynı yönü işaret ettiğine ve kaç veri kaynağının (teknik/haber/makro) mevcut '
              'olduğuna bağlı.',
          formula: 'güven = temel_güven × (mevcut ağırlık / toplam ağırlık) × 100',
        ),
        _Term(
          term: 'Technical',
          range: '−100 … +100',
          description: 'Fiyat hareketinden hesaplanan teknik skor. Varsayılan ağırlığı final '
              'skorun %50\'si.',
        ),
        _Term(
          term: 'News',
          range: '−100 … +100',
          description: 'Haber duygu/etki skoru — varsayılan ağırlığı %30. Bu motor henüz '
              'yazılmadığı için her zaman "Veri yok" görünür.',
        ),
        _Term(
          term: 'Macro',
          range: '−100 … +100',
          description: 'Küresel piyasa koşullarından hesaplanan, tüm hisseler için aynı olan '
              'skor — varsayılan ağırlığı %20.',
        ),
        _Note(
          text: 'Eksik veri ne olur? News skoru hiç dolmadığı için sistem onu yok saymaz — '
              'kalan bileşenlerin ağırlıklarını kendi aralarında yeniden %100\'e tamamlar ve '
              'bunu güven değerine düşürerek yansıtır.',
        ),
      ],
    );
  }
}

class _TeknikSection extends StatelessWidget {
  const _TeknikSection();

  @override
  Widget build(BuildContext context) {
    return _GuideSection(
      tag: 'Varlık Detayı · Teknik sekmesi',
      title: 'Teknik analiz nasıl hesaplanıyor',
      description:
          'Son 6 aylık fiyat verisinden altı klasik teknik göstergenin ağırlıklı ortalaması '
          'alınarak tek bir Teknik Skor üretilir.',
      children: const [
        _Term(
          term: 'Trend',
          range: 'BULLISH / NEUTRAL / BEARISH',
          description: 'Teknik skor +15\'in üzerindeyse BULLISH, −15\'in altındaysa BEARISH, '
              'arası NEUTRAL.',
        ),
        _Term(
          term: 'Güven',
          range: '%0–100',
          description: 'Altı göstergenin ne kadarının aynı yönü işaret ettiği ile işlem '
              'hacminin 20 günlük ortalamaya göre teyit derecesinin birleşimi.',
        ),
        SizedBox(height: 4),
        Text('Gösterge katkıları (−100…+100)', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
        SizedBox(height: 8),
        _Term(term: 'RSI', description: 'Fiyatın ne kadar "aşırı alınmış" ya da "aşırı '
            'satılmış" olduğu — 0–100 RSI değerinin 50 orta noktasına göre ölçeklenmiş hali.'),
        _Term(term: 'MACD', description: 'Kısa ve uzun vadeli ortalamalar arasındaki farkın '
            'hızlanıp hızlanmadığı — oynaklığa göre normalize edilmiş MACD histogramı.'),
        _Term(term: 'EMA Trend (20/50)', description: '20 günlük ortalama 50 günlüğün '
            'üzerindeyse pozitif (yükseliş trendi), altındaysa negatif katkı.'),
        _Term(term: 'Bollinger Bantları', description: 'Fiyat kendi 20 günlük oynaklık '
            'bandının neresinde — üst banda yakınsa pozitif, alt banda yakınsa negatif.'),
        _Term(term: 'Momentum', description: 'Fiyatın 10 gün önceye göre mutlak (TL) '
            'değişimi.'),
        _Term(term: 'ROC (Değişim Oranı)', description: 'Fiyatın 10 gün önceye göre yüzde '
            'değişimi.'),
        SizedBox(height: 4),
        Text('Ham gösterge değerleri', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
        SizedBox(height: 8),
        _Term(term: 'rsi', description: 'Klasik 0–100 skalasında RSI (70 üzeri "aşırı alım", '
            '30 altı "aşırı satım" sayılır).'),
        _Term(term: 'macd_histogram', description: 'MACD çizgisi ile sinyal çizgisi '
            'arasındaki fark.'),
        _Term(term: 'ema_20 / ema_50', description: '20 ve 50 günlük üstel hareketli '
            'ortalama fiyat (TL).'),
        _Term(term: 'bollinger_upper / middle / lower', description: '20 günlük ortalama ± 2 '
            'standart sapma bant sınırları (TL).'),
        _Term(term: 'atr', description: 'Average True Range — günlük ortalama fiyat '
            'oynaklığı (TL).'),
        _Term(term: 'volume / volume_sma', description: 'O günkü işlem hacmi ve 20 günlük '
            'ortalama hacim.'),
      ],
    );
  }
}

class _HaberlerSection extends StatelessWidget {
  const _HaberlerSection();

  @override
  Widget build(BuildContext context) {
    return _GuideSection(
      tag: 'Varlık Detayı · Haberler sekmesi',
      title: 'Haberler ham listelenir',
      description: 'Bu sekmedeki haberler Yahoo Finance\'ten çekilir ama henüz yapay zeka '
          'ile analiz edilmez (duygu/etki puanı yok). Bu yüzden Analiz ekranındaki "News" '
          'skoru hep boş kalır.',
      children: const [
        _Term(
          term: 'Güvenilirlik',
          range: '%30–100',
          description: 'Haberin doğruluğunu değil, kaynağının kategorisini gösterir: Resmi '
              'kurum/KAP %100, Merkez Bankası %98, Haber Ajansı %90, Finansal Medya %80, '
              'Diğer Medya %60, Sosyal Medya %30.',
        ),
      ],
    );
  }
}

class _GecmisSection extends StatelessWidget {
  const _GecmisSection();

  @override
  Widget build(BuildContext context) {
    return const _GuideSection(
      tag: 'Varlık Detayı · Geçmiş sekmesi',
      title: 'Değişmez karar kaydı',
      description: 'Bu ekran, o hisse için üretilmiş tüm AL/SAT/TUT kararlarının kronolojik '
          've değişmez (immutable) bir kaydıdır. Bir karar üretildikten sonra fiyat sonradan '
          'değişse bile o kayıt asla güncellenmez — yeni bir değerlendirme her zaman yeni bir '
          'satır olarak eklenir. Her satırda karar tarihi/saati, final skor, güven ve etiket '
          'yer alır.',
      children: [],
    );
  }
}

class _PerformansSection extends StatelessWidget {
  const _PerformansSection();

  @override
  Widget build(BuildContext context) {
    return _GuideSection(
      tag: 'Varlık Detayı · Performans sekmesi',
      title: 'Backtest: geçmişe dönük simülasyon',
      description: '"Geçmişte bu hissenin sinyallerini takip etseydim ne olurdu?" sorusuna '
          'cevap veren bir simülasyondur — gerçekleşmiş bir işlem değildir. Kural basit: AL '
          'sinyalinde elindeki tüm parayla al, SAT sinyalinde hepsini sat.',
      children: const [
        _Term(term: 'Strateji Getirisi', description: 'Bu basit kuralı son 2 yıl üzerinde '
            'uygulasaydın elde edeceğin toplam getiri yüzdesi.'),
        _Term(term: 'Al-Tut Getirisi', description: 'Karşılaştırma ölçütü: dönem başında '
            'alıp hiç satmadan elde tutsaydın elde edeceğin getiri.'),
        _Term(term: 'Maksimum Düşüş', description: 'Simülasyon boyunca portföy değerinin en '
            'yüksek noktasından en fazla yüzde kaç gerilediği — bir risk göstergesi.'),
        _Term(term: 'İşlem Sayısı / Kazanma Oranı', description: 'Kaç kez alım-satım '
            'tetiklendiği ve bunların yüzde kaçının kârla kapandığı.'),
        _Note(text: 'Sınırlama: Simülasyon yalnızca teknik skora dayanır (haber ve makro '
            'dahil değildir) ve geçmiş performans gelecekteki performansın garantisi '
            'değildir.'),
      ],
    );
  }
}

class _MacroSection extends StatelessWidget {
  const _MacroSection();

  @override
  Widget build(BuildContext context) {
    return _GuideSection(
      tag: 'Alt sekme · Makro',
      title: 'Makro skor ve göstergeleri',
      description: 'Tek bir hisseye değil tüm piyasaya ait bir skor — bu yüzden Analiz '
          'ekranındaki her hissenin "Macro" değeri birbirinin aynısıdır.',
      children: const [
        _Term(
          term: 'Sağdaki puan (+/−)',
          range: '−100 … +100',
          description: 'O göstergenin makro skora katkısı — yön sözleşmesine göre zaten '
              'işaretlenmiş, doğrudan karşılaştırılabilir bir puan.',
        ),
        _Term(
          term: 'Değer ve %',
          description: 'Göstergenin ham son kapanış değeri ve son 20 işlem gününe göre yüzde '
              'değişimi — henüz hesaplanmamış, doğrudan piyasa verisi.',
        ),
        SizedBox(height: 4),
        Text(
          'Yön sözleşmesi: neden bazı göstergelerin yükselmesi eksi puan?',
          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
        ),
        SizedBox(height: 6),
        Text(
          'Beş göstergede YÜKSELİŞ = OLUMSUZ katkı sayılır, çünkü hepsi "risk-off" '
          '(paranın gelişen piyasalardan kaçtığı) dönemlerde birlikte yükselir:',
          style: TextStyle(height: 1.4),
        ),
        SizedBox(height: 10),
        _Term(term: 'Dolar Endeksi (DXY)', description: 'Doların diğer büyük para '
            'birimlerine karşı gücü. Yükselmesi = dolar güçleniyor = gelişen piyasalardan '
            'çıkış riski.'),
        _Term(term: 'ABD 10 Yıllık Tahvil Faizi', description: 'Küresel "risksiz getiri" '
            'ölçütü. Yükselmesi = para gelişen piyasalardan ABD tahviline kayabilir.'),
        _Term(term: 'VIX (Volatilite Endeksi)', description: 'Piyasanın önümüzdeki 30 gün '
            'için beklediği oynaklık — "korku endeksi". Yükselmesi = risk iştahı azalıyor.'),
        _Term(term: 'Petrol', description: 'Türkiye net petrol ithalatçısı — fiyatın '
            'yükselmesi enflasyon ve cari açık baskısı yaratır.'),
        _Term(term: 'USD/TRY', description: 'Doların TL karşısındaki değeri. Yükselmesi '
            '(TL\'nin değer kaybetmesi) enflasyon ve maliyet baskısı yaratır.'),
        _Term(term: 'Altın', description: 'Aynı risk-off mantığıyla değerlendirilir: '
            'yatırımcılar risktense altına sığındığında, bu genelde hisse senedi iştahının '
            'azaldığının işaretidir.'),
      ],
    );
  }
}

class _PortfoySection extends StatelessWidget {
  const _PortfoySection();

  @override
  Widget build(BuildContext context) {
    return _GuideSection(
      tag: 'Alt sekme · Portföy',
      title: 'Portföy özeti ve pozisyonlar',
      description: 'Portföy verisi piyasa analizinden farklıdır — bu senin kendi verin, '
          'istediğin an düzenleyebilir veya silebilirsin.',
      children: const [
        _Term(term: 'Toplam Yatırım', description: 'Tüm pozisyonların alış maliyetlerinin '
            'toplamı (adet × alış fiyatı).'),
        _Term(term: 'Güncel Değer', description: 'Aynı pozisyonların bugünkü piyasa '
            'fiyatıyla toplam değeri.'),
        _Term(term: 'Kâr/Zarar', description: 'Güncel Değer − Toplam Yatırım (TL) ve bunun '
            'Toplam Yatırım\'a oranı (%).'),
        _Term(
          term: 'Ort. Alış',
          description: 'Aynı hisseden birden fazla fiyattan alım yaptıysan, tüm alımların '
              'adet-ağırlıklı ortalama fiyatı — tek satırda birleştirilerek gösterilir.',
          formula: 'ort. alış = Σ(adet × fiyat) / Σ(adet)',
        ),
        _Term(term: '"(N alım)" etiketi', description: 'O pozisyonun kaç ayrı alım '
            'işleminden birleştirildiği. Sistem her alımı ayrı ayrı saklar, yalnızca '
            'görünümde birleştirir.'),
        _Term(term: 'Düzenle (kalem ikonu)', description: 'Ortalama fiyat/adedi elle '
            'düzeltmeni sağlar. Bu, o hisseye ait tüm geçmiş alım kayıtlarının yerine tek '
            'bir yeni kayıt koyar — ayrı alım tarihleri bu işlemde kaybolur.'),
      ],
    );
  }
}

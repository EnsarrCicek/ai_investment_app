# Teknik Analiz Nasıl Çalışıyor?

> Bu döküman, uygulamanın her hisse için gösterdiği fiyat grafiğini, destek/direnç çizgilerini, teknik skoru, "neden bu sinyal" açıklamasını ve kısa/uzun vade etiketini **hangi verilere ve hangi hesaplama mantığına** dayanarak ürettiğini anlatır. Kod tarafındaki karşılıklar (`backend/app/engines/technical/`) parantez içinde belirtilmiştir. Hiçbir adımda uydurma/tahmini veri kullanılmaz — bir şey hesaplanamıyorsa "veri yok" / "belirsiz" olarak işaretlenir.

---

## 1. Fiyat Verisi Nereden Geliyor?

- Kaynak: **Yahoo Finance** (`yfinance` kütüphanesi), sembol formatı `HISSE.IS` (ör. `THYAO.IS`).
- Teknik analiz için çekilen veri: son **6 aylık günlük OHLCV** (Açılış/Yüksek/Düşük/Kapanış/Hacim) barları.
- Bu veri, Borsa İstanbul'un ücretsiz/lisanssız dağıtım için koyduğu standart kural gereği yaklaşık **15-20 dakika gecikmelidir** (25.08.2026'da piyasa açıkken ölçüldü: ~20 dk) — bu Yahoo'nun bir kusuru değil, borsanın kendi kuralı, ücretsiz hiçbir kaynakta bunun önüne geçilemez.
- **Bugünün tamamlanmamış barı** (gün bitmeden) hesaplamalara dahil edilmez — "look-ahead bias" (geleceği görme) hatasını önlemek için. Bu, ayrı bir otomatik testle (`test_indicator_causality.py`) kilit altına alınmıştır: bir göstergenin geçmiş değeri, seriye yeni bar eklendiğinde asla değişmemelidir.

---

## 2. Teknik Skor (`technical_score`, -100 ile +100 arası) Nasıl Hesaplanıyor?

Yedi klasik göstergeden, her biri -100..+100 aralığına ölçeklenip **ağırlıklı ortalaması** alınarak hesaplanır (`engine.py`). Ağırlıklar hard-code değildir, `system_config/technical_indicator_weights`'ten okunur; varsayılanlar:

| Gösterge | Varsayılan Ağırlık | Ne Ölçüyor |
|---|---|---|
| EMA Eğimi (ema_slope) | %20 | EMA(20)'nın son 5 barda ne kadar hızlı/hangi yönde eğildiği |
| ROC (Değişim Oranı) | %20 | Fiyatın 10 bar önceki değerine göre % değişimi |
| EMA Trend (20/50) | %15 | EMA(20) ile EMA(50) arasındaki fark (kısa vade uzun vadenin üstünde mi) |
| Momentum | %15 | Fiyatın 10 bar önceki değerine göre mutlak farkı (ATR'ye bölünerek normalize edilir) |
| RSI | %10 | 14 barlık göreli güç endeksi (aşırı alım/satım) |
| MACD | %10 | EMA(12)-EMA(26) farkının sinyal çizgisinden sapması (histogram) |
| Bollinger Bantları | %10 | Fiyatın 20 barlık ortalama ± 2 standart sapma bandındaki konumu |

Her gösterge kendi formülüyle hesaplanır (ör. MACD = EMA(12)-EMA(26) ve onun 9 barlık sinyal çizgisi), sonra -100..+100 aralığına sıkıştırılır (`_clamp`). `final_score`, bu 7 bileşenin ağırlıklı toplamının, kullanılan ağırlıkların toplamına bölünmesiyle bulunur — yani bir gösterge hesaplanamasa bile geri kalanların ağırlığı otomatik normalize edilir (bkz. bölüm 8, "Missing Data" ilkesi).

**RSI (14 barlık), tam olarak klasik Wilder yöntemiyle hesaplanır** (`indicators.py`, `rsi()` — 25.08.2026'da denetlenip düzeltildi):
- İlk 14 fiyat değişimi (delta) **basit ortalamayla** (SMA) "seed" edilir: `avg_gain = gain[1:15].mean()`, `avg_loss = loss[1:15].mean()`. Bu, ilk geçerli RSI değerinin oluştuğu bardır.
- Sonraki her barda Wilder'ın kendi **recursive düzleştirmesi** kullanılır: `avg_gain = (önceki_avg_gain × 13 + güncel_kazanç) / 14` (kayıp için aynı formül).
- **İlk 14 bar (warm-up) kasıtlı olarak `NaN`'dır** — henüz bir "14 barlık ortalama" tanımlanamayacağından, Missing Data ilkesi gereği nötr (50) veya sıfır bir değer UYDURULMAZ.
- Uç durumlar (14. bardan itibaren): yalnızca kazanç varsa (`avg_loss=0`) → **RSI=100**; yalnızca kayıp varsa (`avg_gain=0`) → **RSI=0**; fiyat tamamen düzse (`avg_gain=avg_loss=0`) → **RSI=50** (gerçekten tanımsız/nötr durum, tek istisna). Normal durumda standart `100 - 100/(1+avg_gain/avg_loss)` formülü kullanılır.
- **Not (önceki sürüm):** 25.08.2026'dan önceki sürüm, seed için `pandas.ewm(alpha=1/14, adjust=False)` kısayolunu kullanıyordu — recursion adımı doğru olsa da seed farklıydı (tek bir gözlemden başlıyordu) ve `avg_loss=0` durumunda yanlışlıkla RSI=50 dönüyordu (olması gereken 100 yerine). Bu, `TechnicalAnalysisEngine`'in `ENGINE_VERSION`'ının `1.0.0`'dan `1.1.0`'a yükseltilmesine yol açtı; eski Firestore kayıtları değiştirilmedi (immutable), yalnızca bu tarihten sonraki yeni analizler düzeltilmiş yöntemi kullanır.

**Güven (`confidence`, %0-100):** Yalnızca skorun büyüklüğüne değil, iki ek şeye bakar:
1. **Yön uyumu:** 7 bileşenden kaçı final skorla aynı yöndeyse (hepsi AL yönündeyse güven yüksek, yarısı ters yöndeyse düşük).
2. **Hacim doğrulaması:** Güncel hacim, 20 günlük ortalama hacme göre ne durumda (düşük hacimli bir hareket daha az güvenilir sayılır).

**Önbellekleme:** Bir sembol için üretilen analiz 15 dakika boyunca (`TECHNICAL_CACHE_TTL_SECONDS`) saklanır ve tekrar istenirse Yahoo'ya gidilmeden aynı sonuç döndürülür — hem hız hem maliyet için.

---

## 3. Fiyat Grafiği ve Destek/Direnç Çizgileri Nasıl Çiziliyor?

Grafikte gördüğünüz yeşil (destek) ve kırmızı (direnç) bantlar, rastgele veya "göze göre" çizilmiş çizgiler değildir — tamamen aşağıdaki adımların matematiksel sonucudur:

### 3.1 Önce "dönüm noktaları" (swing point) bulunur (`market_structure.py`)
Klasik **fraktal pivot** yöntemi: bir bar'ın Yükseği, kendisinden önceki ve sonraki **5'er bar** içinde en yüksekse, o bar bir "swing high"; aynı mantıkla en düşükse "swing low" sayılır. Serinin son 5 barı için bu onay henüz verilemez (gelecekteki barlara bakmak gerektiğinden) — bu kasıtlı bir güvenlik sınırıdır, veri eksikliği değildir.

### 3.2 Piyasa yapısı etiketlenir (HH/HL/LH/LL)
Ardışık swing high'lar ve swing low'lar birbirleriyle karşılaştırılır:
- Yeni tepe bir öncekinden yüksekse **HH** (Higher High), düşükse **LH** (Lower High)
- Yeni dip bir öncekinden yüksekse **HL** (Higher Low), düşükse **LL** (Lower Low)

Son 4 etiketten çoğunluğu HH/HL ise piyasa yapısı **UPTREND**, çoğunluğu LH/LL ise **DOWNTREND**, eşitse **RANGE** (yatay bant) kabul edilir.

### 3.3 Swing noktaları "bölgelere" (zone) kümelenir (`support_resistance.py`)
Tek bir fiyat seviyesi beklemek gerçekçi değildir — bu yüzden birbirine **ATR'nin (ortalama günlük dalgalanma) yarısı kadar** yakın olan swing low'lar tek bir **destek bölgesi**nde, swing high'lar tek bir **direnç bölgesi**nde toplanır. Bir bölge ne kadar çok swing noktasından oluşuyorsa (`touch_count`), o kadar "güçlü/test edilmiş" sayılır — grafikte parantez içindeki "Nx test edildi" sayısı budur.

### 3.4 Kırılım (breakout) ve gerçeklik testi (`breakout.py`)
Fiyat bir direncin üstüne veya desteğin altına kapanışla çıktığında bu **ATR cinsinden büyüklüğüyle** (ör. "2.16 ATR büyüklüğünde") ölçülür. Ardından:
- **Teyit:** Kırılımdan sonraki 3 barın tamamı seviyenin doğru tarafında kaldıysa kırılım "gerçek" (`confirmed=True`); barlar henüz oluşmadıysa "henüz bilinmiyor"; geri döndüyse "yanlış kırılım" (`confirmed=False`).
- **Retest:** Gerçek bir kırılımdan sonra fiyat kırılan seviyeye geri dönüp (artık rolü değişmiş: eski direnç yeni destek) o seviyeyi tutarsa bu ek bir doğrulama sayılır (`retest_held=True`); seviye tekrar kırılırsa doğrulama çöker (`False`).

### 3.5 Grafik nasıl çiziliyor (Flutter, `_SrChartPainter`)
Mobil uygulama, backend'in hesapladığı bölgeleri (`all_zones`, fiyata en yakın 8 tanesi) alıp Fiyat grafiğinin üzerine **yatay, yarı saydam bantlar** olarak çizer (`CustomPainter` ile elle çizim — hazır bir grafik kütüphanesi değil). Yeşil bant = destek, kırmızı bant = direnç, bandın ortasındaki kesik çizgi ve etiket (`D 134.90 (1x)`) bölgenin orta noktasını ve kaç kez test edildiğini gösterir. **Grafik, backend'in hesapladığı bölgelerin bir görselleştirmesidir — Flutter tarafında ayrıca bir sinyal üretilmez.**

### 3.6 "Grafik Neden Bunu Söylüyor?" metni nasıl yazılıyor (`narrative.py`)
Yukarıdaki sayısal sonuç (en yakın destek/direnç, kırılım durumu, teyit, retest), **LLM kullanılmadan**, önceden yazılmış Türkçe şablon cümlelere dökülür (ör. "Fiyat, X-Y TL bandındaki direnci ATR'nin Z katı büyüklüğünde yukarı yönlü kırdı. Bu kırılım teyit edildi..."). Bu metin hiçbir yeni bilgi eklemez, yalnızca zaten hesaplanmış sayıları okunabilir hale getirir.

---

## 4. Ek Bağlam Katmanı (aynı veriden, ek maliyetsiz hesaplanır)

Bunların hiçbiri `technical_score`'u değiştirmez — yalnızca "bu skorun arkasında ne var" sorusuna ek bağlam sağlar:

- **Göreli hacim** (`relative_volume.py`): Güncel hacim, son 20 günün **medyanına** (ortalamaya değil — tek bir aşırı gün ortalamayı bozmasın diye) bölünür. 2.5 kattan fazlaysa "Çok Yüksek Hacim".
- **Volatilite rejimi** (`regime.py`): Güncel ATR'nin son 100 güne göre yüzdelik dilimi (percentile) — Düşük/Normal/Yüksek/Aşırı Yüksek.
- **Trend rejimi** (`regime.py`): Kaufman Verimlilik Oranı (net fiyat hareketi ÷ toplam mutlak hareket). 1'e yakınsa "güçlü/az gürültülü trend" (TRENDING), 0'a yakınsa "gürültülü/yatay" (CHOPPY) — fiyat çok oynamış ama net bir yere gitmemiş demektir.
- **Göreli güç** (`relative_strength.py`): Hissenin BIST100 endeksine (XU100) oranının son 20 gündeki % değişimi. Hem hisse hem endeks düşse bile hisse daha az düşüyorsa oran yine de yükselir → "Endeksten İyi" (OUTPERFORMING).
- **Çoklu zaman dilimi uyumu** (`multi_timeframe.py`): Günlük EMA eğimi yönü ile haftalık EMA eğimi yönü karşılaştırılır (haftalık, zaten çekilmiş günlük veriden türetilir — ek istek yok). İkisi de aynı yöndeyse "uyumlu", biri yukarı biri aşağıysa "çelişkili" (CONFLICTING) — en riskli durum.
- **Gap analizi** (`gap_analysis.py`): Son barın açılışı ile bir önceki kapanış arasındaki fark, ATR'ye göre "önemli" sayılıp sayılmayacağı ve aynı gün içinde "doldurulup doldurulmadığı".
- **Mum formasyonları** (`candlestick_patterns.py`): Doji, Çekiç (Hammer), Kayan Yıldız, Yutan Boğa/Ayı formasyonları — yalnızca **tespit edilir**, tek başına bir sinyal olarak yorumlanmaz (bağlamla birlikte değerlendirilmesi gerektiği UI'da açıkça belirtilir).

### 4.1 Sinyal Sınıflandırması (7 sınıf, `signal_classifier.py`)
Yukarıdaki tüm bağlam bir araya getirilip tek bir etikete indirgenir (öncelik sırasına göre):

`STRONG_BULLISH_INITIATION` (skor≥40 + UPTREND + teyitli kırılım+retest tutmuş + yüksek hacim + haftalık uyumlu) > `BULLISH_CONFIRMED` (skor≥15 + UPTREND) > `BULLISH_CANDIDATE` (skor≥15) > `BEARISH_CANDIDATE` (skor≤-15) > `NO_SIGNAL` (hiç bağlam yok) > `WATCHLIST` (zayıf ama doğru yönde) > `NEUTRAL` (varsayılan).

### 4.2 Yatırım Vadesi Etiketi — Kısa/Orta/Uzun Vadeli (`horizon_classifier.py`, 25.08.2026 eklendi)
Sinyal sınıfı, piyasa yapısı, trend rejimi, göreli güç ve zaman dilimi uyumundan **saf kural tabanlı** (LLM yok, haber/makro karıştırılmaz) şu mantıkla üretilir:

- **Taze bir kırılım/momentum girişi** (`STRONG_BULLISH_INITIATION`) → **Kısa Vadeli**: henüz haftalık trendde kalıcı bir teyit yok, retest süreci belirleyici olacak.
- Yön belli VE **günlük+haftalık uyumlu** VE **trend verimli/gürültüsüz** VE **endeksten güçlü ayrışma** varsa (hepsi birden) → **Uzun Vadeli**: yapısal, çok boyutlu teyitli bir görünüm.
- Yön belli ama kriterlerin yalnızca bir kısmı sağlanıyorsa → **Orta Vadeli**.
- Yön belli ama hiçbir yapısal teyit yoksa (yalnızca skor pozitif/negatif) → **Kısa Vadeli/taktiksel**.
- Yön hiç belli değilse (nötr sinyal) → **Belirsiz** (rozet gösterilmez).

Bu mantık boğa (AL) ve ayı (SAT) tarafında simetrik uygulanır. **Bilinçli olarak haberin kendi vade etiketi (`time_horizon`, Haberler sekmesinde ayrı gösterilir) buraya karıştırılmaz** — ikisini birleştirmek yanlış bir kesinlik hissi verir.

---

## 5. AL/SAT Kararı Teknik Skordan Nasıl Türetiliyor? (`decision/engine.py`)

Teknik skor tek başına AL/SAT kararı değildir — üç bağımsız motorun ağırlıklı toplamıdır:

```
final_score = technical_score × %50 + news_score × %30 + macro_score × %20
```

- **Haber skoru:** Son 10 haberin, OpenAI'nin ürettiği duygu skorlarının **güven-ağırlıklı ortalaması** (bkz. `EventIntelligenceEngine`, yalnızca burada yapay zeka/LLM kullanılır).
- **Makro skoru:** DXY, ABD 10Y faiz, VIX, petrol, altın, USD/TRY'nin piyasa geneline etkisi (varlığa özel değil).
- **Eksik veri varsayılmaz:** Haber veya makro veri yoksa 0 (nötr) kabul edilmez — kalan bileşenlerin ağırlığı kendi aralarında yeniden normalize edilir ve güven oranı da veri eksikliği kadar düşürülür.

Eşikler (varsayılan): final_score ≥ 40 → **AL**, ≥ 15 → **ZAYIF AL**, ≤ -15 → **ZAYIF SAT**, ≤ -40 → **SAT**, arası **TUT**. Bu eşikler de `system_config`'ten okunur, hard-code değildir.

**Teknik sekmesindeki "AL/SAT Kararının Dayandığı Veriler" kartı** (25.08.2026 eklendi), tam olarak bu üç bileşenin **gerçekte kullanılan ağırlıklarını** (eksik veri normalizasyonundan sonraki gerçek yüzdeler) ve her bileşenin en etkili gerekçelerini gösterir — kural tabanlıdır, `AIExplanationEngine` tarafından üretilir, LLM kullanmaz.

---

## 6. Dürüstlük İlkeleri (Özet)

- **Uydurma veri yok:** Bir gösterge hesaplanamıyorsa (yetersiz geçmiş, eksik sütun) skor üretilmez, "veri yok" denir.
- **Geleceğe bakma yok (look-ahead-bias):** Hem swing point onayı hem breakout teyidi hem de göstergelerin kendisi yalnızca o ana kadarki barlara bakar; bu ayrı bir otomatik testle (`test_indicator_causality.py`) her yeni özellik eklendiğinde tekrar doğrulanır.
- **LLM yalnızca haber analizinde:** Teknik analiz, grafik yorumu, sinyal sınıflandırması, vade etiketi ve "neden bu sinyal" anlatısının hiçbiri yapay zeka/LLM kullanmaz — hepsi burada anlatılan sabit, tekrarlanabilir matematiksel kurallardır. Aynı veriyle her zaman aynı sonuç üretilir.
- **Mum formasyonu/gap gibi zayıf sinyaller tek başına karar üretmez** — yalnızca bağlam olarak gösterilir.

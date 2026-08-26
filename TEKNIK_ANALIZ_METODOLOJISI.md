# Teknik Analiz Nasıl Çalışıyor?

> Bu döküman, uygulamanın her hisse için gösterdiği fiyat grafiğini, destek/direnç çizgilerini, teknik skoru, "neden bu sinyal" açıklamasını ve kısa/uzun vade etiketini **hangi verilere ve hangi hesaplama mantığına** dayanarak ürettiğini anlatır. Kod tarafındaki karşılıklar (`backend/app/engines/technical/`) parantez içinde belirtilmiştir. Hiçbir adımda uydurma/tahmini veri kullanılmaz — bir şey hesaplanamıyorsa "veri yok" / "belirsiz" olarak işaretlenir.

---

## 1. Fiyat Verisi Nereden Geliyor?

- Kaynak: **Yahoo Finance** (`yfinance` kütüphanesi), sembol formatı `HISSE.IS` (ör. `THYAO.IS`).
- Teknik analiz için çekilen veri: son **6 aylık günlük OHLCV** (Açılış/Yüksek/Düşük/Kapanış/Hacim) barları.
- Bu veri, Borsa İstanbul'un ücretsiz/lisanssız dağıtım için koyduğu standart kural gereği yaklaşık **15-20 dakika gecikmelidir** (25.08.2026'da piyasa açıkken ölçüldü: ~20 dk) — bu Yahoo'nun bir kusuru değil, borsanın kendi kuralı, ücretsiz hiçbir kaynakta bunun önüne geçilemez.
- **Güncel fiyat, ayrı ve canlı bir akıştır** (`GET /market-data/{symbol}/quote`, Fiyat sekmesinde gösterilir) — piyasa açıkken saniyeler/dakikalar içinde değişebilir, doğrudan Yahoo'nun gün-içi (5dk) verisinden gelir.
- **Günlük TechnicalScore ise yalnızca SON TAMAMLANMIŞ günlük barı kullanır** (`services/market_data/completed_bars.py`, `filter_completed_daily_bars()`, 25.08.2026'da HATA 2A denetimiyle düzeltildi). Piyasa açıkken Yahoo'nun `interval="1d"` verisi "bugünü" hâlâ oluşmakta olan (developing/partial) bir bar olarak döndürür — bu satır, kapanıştan itibaren belirli bir güvenlik payı (`DAILY_BAR_FINALIZATION_DELAY_MINUTES`, varsayılan 30 dk — Yahoo'nun günlük barı kapanıştan tam olarak kaç dakika sonra kesinleştirdiği AYRICA ÖLÇÜLMEDİ, bu bilinçli olarak kolayca kalibre edilebilir bir güvenlik payıdır, kanıtlanmış bir gerçek değil) geçene kadar günlük hesaplamalardan (RSI, MACD, EMA, ROC, Momentum, Bollinger, ATR, Market Structure, Support/Resistance, Breakout, Gap, Candlestick, Regime, Relative Strength, Signal Classifier, Horizon Classifier — TAMAMI) **çıkarılır**. Piyasa içinde oluşmakta olan günlük mum, daily teknik skora HİÇ girmez.
- Haftalık zaman dilimi karşılaştırması (Multi-Timeframe) da aynı ilkeyle çalışır: devam eden (henüz Cuma'sı gelmemiş) hafta, haftalık teyit için kullanılmaz — yalnızca tamamen bitmiş haftalar dikkate alınır (`resample_to_weekly_close()`).
- Her `TechnicalAnalysis` kaydı, motorun hesabı YAPTIĞI anı (`created_at`) ile kullanılan verinin ait olduğu son tamamlanmış barın tarihini (`market_data_as_of`) AYRI alanlar olarak taşır — bunlar aynı şey değildir ve Teknik sekmesinde ikincisi kullanıcıya gösterilir ("Teknik veri: Son tamamlanmış günlük bar — DD.MM.YYYY").
- **İleride ayrı ele alınacak:** Gün-içi (intraday) sinyaller — ör. "fiyat şu an direnci kırdı" gibi anlık tetikleyiciler — bu günlük motorun kapsamında DEĞİLDİR; bilinçli olarak ayrı bir "IntradayTriggerEngine"e bırakılmıştır (henüz yazılmadı).
- **BIST işlem günü eksikse teknik skor ÜRETİLMEZ** (`data_quality.py`, `check_trading_day_continuity()`, HATA 2B — 25.08.2026'da eklendi). Yahoo Finance'in kendi veri hattı, bireysel hisseler için ara sıra BIST'in resmi işlem takviminde açık olduğu bilinen bir günün barını hiç döndürmeyebiliyor (gerçek örnek: 24.08.2026'da BIST100'ün TAMAMI için THYAO/GARAN/ASELS dahil bu şekilde bir gün eksik çıktı, oysa BIST100 endeksinin kendisinde o günün barı vardı — yani piyasa gerçekten açıktı, sorun sağlayıcı kaynaklıydı). Böyle bir boşluk **eksik OHLCV değeri UYDURULARAK** (önceki kapanışla doldurma, hacim=0 varsayma, interpolasyon, nötr kabul etme) ya da yalnızca `confidence` düşürülerek KAPATILMAZ — RSI/MACD/EMA gibi recursive göstergeler sessizce yanlış bir "N gün önce" referansı kullanacağından, analiz o sembol için **HİÇ ÜRETİLMEZ** (`GET /decisions/{symbol}` ve `GET /analysis/{symbol}/technical` bu durumda 422 döner). Kontrol, sembolün **seride gözlemlenen ilk barından**, `now`'a göre beklenen son tamamlanmış BIST seansına kadar olan aralıkla SINIRLIDIR — daha geniş bir "6 aylık geçmişin tamamı eksiksizdir" iddiası YOKTUR.
  - **Operasyonel not (kalıcı bir çözüm DEĞİL, geçici bir durum tespiti):** 25.08.2026 itibarıyla, Yahoo'nun 24.08.2026 için bireysel BIST hisselerinde bıraktığı veri boşluğu, bu tarihi 6 aylık pencerelerinde taşıyan TÜM BIST100 hisselerinde `HARD_VETO`'ya (`MISSING_TRADING_SESSION`) yol açıyor — bu bir algoritma hatası DEĞİL, "eksik gerçek OHLCV ile teknik skor üretmeme" politikasının doğrudan, amaçlanan sonucudur. Yahoo geçmişe dönük veriyi düzeltirse ya da 6 aylık pencere zamanla bu tarihi geride bırakırsa (yaklaşık Şubat 2027) durum kendiliğinden düzelir; ileride güvenilir bir ikincil (secondary) sağlayıcıyla gerçek eksik OHLCV'nin tamamlanması ayrı bir geliştirme konusu olarak değerlendirilebilir.

- **"Leading-gap" (pencere başındaki kör nokta) — pre-roll ile doğrulama (HATA 2C, 25.08.2026):** Yukarıdaki HATA 2B kontrolü tek başına bir kör noktaya sahipti: `analysis_start` (`now - 6 ay`, `relativedelta` ile hesaplanır — sabit gün sayısı DEĞİL) ile başlayan pencerenin **KENDİ ilk barı** (`df.index[0]`), o sembolün kanıtlanmış bir halka arz/listing tarihi olduğu ANLAMINA GELMEZ — yalnızca "verinin bu tarihten önce elimizde olmadığı" gözlemidir. Sağlayıcı, istenen pencerenin tam BAŞINDAKİ günleri sessizce düşürürse, bu gerçek bir boşluk "muhtemelen pre-listing" sanılıp fark edilmeden MASKELENEBİLİR (sentetik testle kanıtlandı: yerleşik bir sembolün ilk birkaç günü düşürülmüş gibi simüle edildiğinde eski kontrol bunu sessizce geçiriyordu).
  - **Çözüm — pre-roll (kanıt) penceresi:** Motor, `analysis_start`'tan **biraz daha ÖNCESİNİ** (`PRE_ROLL_DAYS = 15` takvim günü) de kapsayan TEK bir geniş istek yapar (`history_window.py`, `compute_history_window()`). Bu pre-roll bölgesi **hiçbir zaman** göstergelere (RSI/MACD/EMA/.../Horizon Classifier) veya S/R-breakout/rejim/relative-strength hesaplamalarına girmez — skor, her zaman yalnızca `analysis_start`'tan itibaren ("analysis history") üretilir; pre-roll yalnızca "bu sembol analysis_start'tan önce zaten işlem görüyor muydu?" sorusuna kanıt aramak için vardır.
  - **`PRE_ROLL_DAYS = 15` bir DOĞRULUK GARANTİSİ DEĞİLDİR** ve Yahoo'nun olası bir kesintisinin azami süresi de değildir — yalnızca gözlem/kanıt amaçlı, kolayca kalibre edilebilir bir tampondur (BIST'in 2025-2026 resmi takviminde ölçülen en uzun kesintisiz kapanış bloğuna — 27-31 Mayıs 2026 Kurban Bayramı, 5 takvim günü — makul bir pay eklenerek seçilmiştir).
  - **`history_validation_status` alanı** (`TechnicalAnalysis` modelinde, backward-compatible — eski kayıtlarda `null`), iki değerden birini taşır:
    - `VERIFIED_PRE_WINDOW`: pre-roll bölgesinde `analysis_start`'tan ÖNCEye ait en az bir gerçek bar bulundu — sembolün zaten işlem gördüğü KANITLANDI. Continuity kontrolü doğrudan `analysis_start`'tan başlar; pre-roll'un KENDİ İÇİNDEKİ boşluklar (varsa) hiç sorgulanmaz, çünkü onlar zaten skora hiç girmeyecek bir bölgededir.
    - `LEADING_EDGE_UNVERIFIED`: pre-roll bölgesinde HİÇ bar bulunamadı. Bu durum **artık otomatik olarak "yeni halka arz" (PRE_LISTING) SAYILMAZ ve otomatik `HARD_VETO`'ya da yol AÇMAZ** — çünkü gerçek bir yeni listing ile sağlayıcının pre-roll penceresinin TAMAMINI kaybetmesi, fiyat verisinden AYIRT EDİLEMEZ (bilinçli olarak çözülmemiş, kabul edilmiş bir sınırlama). Bunun yerine, continuity kontrolü sembolün **gözlemlenen ilk barından** itibaren normal şekilde çalışmaya devam eder — o tarihten SONRAKİ gerçek boşluklar hâlâ `HARD_VETO`'ya yol açar, yalnızca o tarihten ÖNCESİ hiç sorgulanmaz.
  - **Yahoo metadata (`firstTradeDate` vb.) KASITLI OLARAK kullanılmadı:** Denetim sırasında ölçüldü — THYAO/GARAN/ASELS gibi eski, köklü hisselerde bile bu alan güvenilmez/paylaşılan bir placeholder tarih (`2000-05-10`) döndürüyor, gerçek listing tarihini YANSITMIYOR. Bu yüzden bu alan `analysis_start`/`expected_start` hesaplamasına hiçbir şekilde DAHİL EDİLMEDİ; `Asset` modeline de bir `listing_date` alanı EKLENMEDİ (Firebase migration YAPILMADI) — resmi BIST/KAP/MKK kaynaklarından ücretsiz erişilebilir, güvenilir bir listing-date kaynağı bulunamadı; bu, ayrı ve şu an kasıtlı olarak açık bırakılmış bir geliştirme konusudur.

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

## 6. Backtest Nasıl Çalışıyor? (`engines/backtest/engine.py`) — Execution Modeli (HATA 3A, 25.08.2026)

Backtest, canlı motorla AYNI teknik skor formülünü (bkz. bölüm 2) geçmiş veri üzerinde vektörize çalıştırıp AL/SAT sinyallerine göre bir "sinyalde pozisyon aç/kapat" stratejisi simüle eder. **Execution modeli: `NEXT_SESSION_OPEN`.**

- **Sinyal:** `T` gününün TAMAMLANMIŞ Close'undan üretilir.
- **İşlem (execution):** Sinyal, aynı `T` gününün Close'undan DEĞİL, **`T+1` seansının Open'ından** gerçekleştirilir. Gerekçe: canlıda `T`'nin Close'u ancak seans kapandıktan SONRA bilinir — o anda artık o fiyattan işlem yapılamaz (bu, HATA 3 denetiminde kanıtlanan "same-bar execution bias"in düzeltmesidir). Kural BUY ve SELL için simetriktir.
- **Overnight gap sahipliği:** BUY'da `Close[T]→Open[T+1]` gece hareketi yatırımcıya AİT DEĞİLDİR (pozisyon henüz açılmamıştır). SELL'de aynı gece hareketi yatırımcıya AİTTİR (pozisyon T+1 açılışına kadar hâlâ elde tutulur).
- **Son barda T+1 yoksa:** Yeni bir sinyal ASLA execute edilmez (`Close`'a sahte fallback YAPILMAZ) — `unexecuted_signal` alanında (`reason: "NO_NEXT_BAR"`) bilgi amaçlı raporlanır, ne pozisyon açılır ne kapanmış bir işlem sayılır.
- **`Open[T+1]` geçersizse** (NaN/inf/≤0): execution yine YAPILMAZ, `skipped_executions` içinde (`reason: "INVALID_NEXT_OPEN"`) raporlanır — bilinmeyen bir fiyat asla uydurulmaz.
- **Backtest sonunda açık kalan pozisyon:** Bu GERÇEK bir SELL execution DEĞİLDİR — `trades[]`'e sahte bir kapanış kaydı EKLENMEZ. Yalnızca `final Close` ile **mark-to-market** değerlenir (`cash + shares × final_close`) ve ayrı bir `open_position` alanında (`status: "OPEN"`, giriş sinyal/execution tarih-fiyatları, `unrealized_return_pct`) raporlanır.
- **Metrik ayrımı:** `trade_count`/`win_rate_pct`/`profit_factor`/`expectancy_pct` **yalnızca gerçek kapanmış (closed round-trip) işlemlerden** hesaplanır — açık pozisyon bu metriklere hiç girmez. Buna karşılık `total_return_pct`/`final_equity`/`equity_curve`/`max_drawdown_pct`/Sharpe/Sortino, açık pozisyonun **gerçekleşmemiş (unrealized) kâr/zararını İÇERİR** (mark-to-market üzerinden). Yani aynı backtest sonucunda getiri unrealized P/L içerebilirken, win_rate yalnızca gerçekleşmiş (realized) işlemlere aittir — bu bilinçli, iki farklı taban alan bir tasarımdır.
- **Trade kaydı alanları:** Geriye dönük uyumluluk için `entry_date`/`exit_date`/`entry_price`/`exit_price` adları KORUNDU, ama artık açıkça **execution** an/fiyatını taşırlar (`entry_date == entry_execution_date`). Sinyalin an/fiyatı ayrıca `entry_signal_date`/`entry_signal_price`/`exit_signal_date`/`exit_signal_price` alanlarında EK olarak taşınır.
- **Sonucun üst seviyesinde** `execution_model: "NEXT_SESSION_OPEN"` ve `terminal_position_policy: "MARK_TO_MARKET"` alanları bulunur — eski (bu değişiklikten önceki, same-bar execution kullanan) sonuçlardan ayırt edilebilmesi için.
- **Bu sürümde HENÜZ UYGULANMAYAN (bilinçli olarak dışarıda bırakılan):** brokerage komisyonu, BSMV, spread, slippage, minimum komisyon, piyasa etkisi (price impact) — backtest sonuçları şu an **maliyetsiz** bir işlem varsayımıyla üretiliyor, gerçek getiriler bu maliyetler kadar daha düşük olacaktır.

### 6.1 Veri sözleşmesi: `COMPLETED_DAILY_ONLY` (HATA 3B, 26.08.2026)

Backtest **canlı/paper-trading DEĞİLDİR** — yalnızca **TAMAMLANMIŞ günlük BIST seansları** üzerinde çalışır. "As-of" sözleşmesi kesindir:

- `latest_expected_completed_date(now)` (bkz. bölüm 1, HATA 2A — kapanış (18:00 TSİ) + `DAILY_BAR_FINALIZATION_DELAY_MINUTES` (30 dk) payı geçmediyse DÜN, geçtiyse BUGÜN), backtest'in veri kabul edebileceği **ÜST SINIRI** belirler — "bugüne kadarki hangi tarihe izin veriyoruz" sorusunun cevabıdır, "provider'da o tarihe kadar her gün gerçekten var" GARANTİSİ DEĞİLDİR. Sonuca eklenen `backtest_data_as_of`, provider'dan (Yahoo) filtre sonrasında GERÇEKTEN dönen ve kullanılan EN SON completed bar tarihidir — provider'ın kendi veri boşlukları (ör. 25.08.2026'da THYAO/GARAN/ASELS'te gözlenen boşluk, bkz. aşağıdaki sınırlama notu) nedeniyle `backtest_data_as_of`, `latest_expected_completed_date(now)`'dan DAHA ESKİ olabilir (`backtest_data_as_of <= latest_expected_completed_date(now)`, eşitlik garanti değildir).
- Piyasa açıkken (veya finalization payı dolmadan) çalıştırılan bir backtest, bugünün satırını **HİÇBİR ALANIYLA** (Open dahil — "Open zaten sabit, execution için kullanılabilir" istisnası BİLİNÇLİ OLARAK YAPILMAZ) kullanmaz: skora girmez, `simulate()`'e girmez, execution fiyatı olarak kullanılmaz, terminal mark-to-market'e girmez, walk-forward'a/compare-strategies'e girmez.
- Bu filtre TEK bir yerde uygulanır (`engines/backtest/completed_history.py`, `prepare_backtest_history()`) ve üç canlı giriş noktasının (`BacktestEngine.run()`, `BacktestEngine.compare_strategies()`, `WalkForwardOptimizer.run()`) HEPSİ tarafından paylaşılır — biri filtrelenip diğerleri ham bırakılmaz. Minimum geçmiş kontrolü (`MIN_HISTORY_DAYS`) RAW değil, bu FİLTRELENMİŞ seri üzerinde çalışır (piyasa açıkken bugünün partial barı minimum-geçmiş şartını sahte şekilde karşılayamaz).
- Sonuca eklenen `backtest_data_as_of` alanı, backtest'in fiilen hesaba kattığı EN SON tamamlanmış günü; `data_policy: "COMPLETED_DAILY_ONLY"` ise bu sözleşmenin adını taşır.
- HATA 3A'nın `Signal[T] → Execution[T+1 Open]` kuralı DEĞİŞMEDİ — yalnızca artık her zaman completed-only bir seri üzerinde çalışıyor. Son tamamlanmış barda oluşan bir sinyal için backtest ufkunda henüz bir T+1 yoksa (piyasa hâlâ açıksa) bu `unexecuted_signal`/`NO_NEXT_BAR` ile doğru şekilde raporlanır — aynı backtest, ertesi günün barı tamamlandıktan sonra yeniden çalıştırılırsa o sinyal artık normal şekilde execute edilir.
- **Bilinçli olarak HENÜZ ÇÖZÜLMEYEN, ayrı bir sınırlama:** Backtest, canlı motorun BIST işlem-günü süreklilik kontrolünü (bkz. bölüm 1, HATA 2B, `check_trading_day_continuity`) HÂLÂ kullanmıyor — sağlayıcı kaynaklı bir günlük boşluk (ör. 25.08.2026'da THYAO/GARAN/ASELS'te gözlenen, canlı motoru HARD VETO ile durduran boşluk) backtest'te sessizce göz ardı edilip iki gün ardışıkmış gibi göstergelere girebilir. Ayrıca transaction cost'lar (komisyon/BSMV/spread/slippage) ve live/backtest zenginleştirme-katmanı parite'si de henüz kapsam dışıdır.

---

## 7. Dürüstlük İlkeleri (Özet)

- **Uydurma veri yok:** Bir gösterge hesaplanamıyorsa (yetersiz geçmiş, eksik sütun) skor üretilmez, "veri yok" denir.
- **Geleceğe bakma yok (look-ahead-bias):** Hem swing point onayı hem breakout teyidi hem de göstergelerin kendisi yalnızca o ana kadarki barlara bakar; bu ayrı bir otomatik testle (`test_indicator_causality.py`) her yeni özellik eklendiğinde tekrar doğrulanır.
- **LLM yalnızca haber analizinde:** Teknik analiz, grafik yorumu, sinyal sınıflandırması, vade etiketi ve "neden bu sinyal" anlatısının hiçbiri yapay zeka/LLM kullanmaz — hepsi burada anlatılan sabit, tekrarlanabilir matematiksel kurallardır. Aynı veriyle her zaman aynı sonuç üretilir.
- **Mum formasyonu/gap gibi zayıf sinyaller tek başına karar üretmez** — yalnızca bağlam olarak gösterilir.

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
  - **Operasyonel not (kalıcı bir çözüm DEĞİL, geçici bir durum tespiti):** 25-26.08.2026'da, Yahoo'nun 24.08.2026 VE 25.08.2026 için bireysel BIST hisselerinde ardı ardına bıraktığı veri boşlukları, bu tarihleri 6 aylık pencerelerinde taşıyan TÜM BIST100 hisselerinde geçici olarak `HARD_VETO`'ya (`MISSING_TRADING_SESSION`) yol açtı — bu bir algoritma hatası DEĞİL, "eksik gerçek OHLCV ile teknik skor üretmeme" politikasının doğrudan, amaçlanan sonucudur. Her iki boşluk da birkaç saat içinde Yahoo tarafından geriye dönük dolduruldu (kendiliğinden düzelme, öngörüldüğü gibi); ileride güvenilir bir ikincil (secondary) sağlayıcıyla gerçek eksik OHLCV'nin tamamlanması ayrı bir geliştirme konusu olarak değerlendirilebilir.
  - **HATA 3C (26.08.2026) ile güçlendirme:** `check_trading_day_continuity()` artık yalnızca eksik (`missing`) günleri değil, takvime göre "expected" OLMAYAN bir günde açıklanamayan bir bar bulunmasını da (`unexpected`, `UNEXPECTED_TRADING_SESSION`) kontrol ediyor — bu, PAYLAŞILAN bir fonksiyon olduğundan canlı motoru da otomatik olarak kapsıyor. Ayrıca Borsa'nın olağanüstü kararla kapattığı/iptal ettiği günler (bkz. bölüm 6.3, `BIST_EXTRAORDINARY_CLOSURES`/`BIST_CANCELLED_SESSIONS`) artık resmi kaynağa dayalı olarak ayrıca tanınıyor.

- **"Leading-gap" (pencere başındaki kör nokta) — pre-roll ile doğrulama (HATA 2C, 25.08.2026):** Yukarıdaki HATA 2B kontrolü tek başına bir kör noktaya sahipti: `analysis_start` (`now - 6 ay`, `relativedelta` ile hesaplanır — sabit gün sayısı DEĞİL) ile başlayan pencerenin **KENDİ ilk barı** (`df.index[0]`), o sembolün kanıtlanmış bir halka arz/listing tarihi olduğu ANLAMINA GELMEZ — yalnızca "verinin bu tarihten önce elimizde olmadığı" gözlemidir. Sağlayıcı, istenen pencerenin tam BAŞINDAKİ günleri sessizce düşürürse, bu gerçek bir boşluk "muhtemelen pre-listing" sanılıp fark edilmeden MASKELENEBİLİR (sentetik testle kanıtlandı: yerleşik bir sembolün ilk birkaç günü düşürülmüş gibi simüle edildiğinde eski kontrol bunu sessizce geçiriyordu).
  - **Çözüm — pre-roll (kanıt) penceresi:** Motor, `analysis_start`'tan **biraz daha ÖNCESİNİ** (`PRE_ROLL_DAYS = 15` takvim günü) de kapsayan TEK bir geniş istek yapar (`history_window.py`, `compute_history_window()`). Bu pre-roll bölgesi **hiçbir zaman** göstergelere (RSI/MACD/EMA/.../Horizon Classifier) veya S/R-breakout/rejim/relative-strength hesaplamalarına girmez — skor, her zaman yalnızca `analysis_start`'tan itibaren ("analysis history") üretilir; pre-roll yalnızca "bu sembol analysis_start'tan önce zaten işlem görüyor muydu?" sorusuna kanıt aramak için vardır.
  - **`PRE_ROLL_DAYS = 15` bir DOĞRULUK GARANTİSİ DEĞİLDİR** ve Yahoo'nun olası bir kesintisinin azami süresi de değildir — yalnızca gözlem/kanıt amaçlı, kolayca kalibre edilebilir bir tampondur (BIST'in 2025-2026 resmi takviminde ölçülen en uzun kesintisiz kapanış bloğuna — 27-31 Mayıs 2026 Kurban Bayramı, 5 takvim günü — makul bir pay eklenerek seçilmiştir).
  - **`history_validation_status` alanı** (`TechnicalAnalysis` modelinde, backward-compatible — eski kayıtlarda `null`), iki değerden birini taşır:
    - `VERIFIED_PRE_WINDOW`: pre-roll bölgesinde `analysis_start`'tan ÖNCEye ait en az bir gerçek bar bulundu — sembolün zaten işlem gördüğü KANITLANDI. Continuity kontrolü doğrudan `analysis_start`'tan başlar; pre-roll'un KENDİ İÇİNDEKİ boşluklar (varsa) hiç sorgulanmaz, çünkü onlar zaten skora hiç girmeyecek bir bölgededir.
    - `LEADING_EDGE_UNVERIFIED`: pre-roll bölgesinde HİÇ bar bulunamadı. Bu durum **artık otomatik olarak "yeni halka arz" (PRE_LISTING) SAYILMAZ ve otomatik `HARD_VETO`'ya da yol AÇMAZ** — çünkü gerçek bir yeni listing ile sağlayıcının pre-roll penceresinin TAMAMINI kaybetmesi, fiyat verisinden AYIRT EDİLEMEZ (bilinçli olarak çözülmemiş, kabul edilmiş bir sınırlama). Bunun yerine, continuity kontrolü sembolün **gözlemlenen ilk barından** itibaren normal şekilde çalışmaya devam eder — o tarihten SONRAKİ gerçek boşluklar hâlâ `HARD_VETO`'ya yol açar, yalnızca o tarihten ÖNCESİ hiç sorgulanmaz.
  - **Yahoo metadata (`firstTradeDate` vb.) KASITLI OLARAK kullanılmadı:** Denetim sırasında ölçüldü — THYAO/GARAN/ASELS gibi eski, köklü hisselerde bile bu alan güvenilmez/paylaşılan bir placeholder tarih (`2000-05-10`) döndürüyor, gerçek listing tarihini YANSITMIYOR. Bu yüzden bu alan `analysis_start`/`expected_start` hesaplamasına hiçbir şekilde DAHİL EDİLMEDİ; `Asset` modeline de bir `listing_date` alanı EKLENMEDİ (Firebase migration YAPILMADI) — resmi BIST/KAP/MKK kaynaklarından ücretsiz erişilebilir, güvenilir bir listing-date kaynağı bulunamadı; bu, ayrı ve şu an kasıtlı olarak açık bırakılmış bir geliştirme konusudur.

- **"Phantom" (Yahoo kaynaklı sahte) non-session bar — authoritative normalizasyon (HATA 3D, 26.08.2026):** HATA 3C-EX'in çözdüğü "seans FİİLEN açıldı ama iptal edildi" (bkz. bölüm 6.3) durumundan AYRI ve daha yaygın bir sorun keşfedildi: Yahoo, **planlı resmi tam gün tatillerinde** (`BIST_FULL_DAY_CLOSURES`) bireysel BIST hisseleri için hiç seans olmamasına rağmen ara sıra "donmuş" bir bar döndürüyor — imzası `Open=High=Low=Close=`bir önceki günün kapanışı VE `Volume=0` (gerçek bir işlem YOK, saf veri artefaktı). Gerçek örnek: **27-29 Mayıs 2026 (Kurban Bayramı)** — 100/100 BIST100 hissesinde bu phantom bar tespit edildi, oysa `^XU100` endeksinde o tarihler için HİÇ satır YOK (endeks bu artefakttan etkilenmiyor — sorunun endeks/piyasa değil, bireysel hisse veri hattı kaynaklı olduğunu doğruluyor).
  - **Karar kriteri KESİNLİKLE takvimdir, OHLC/Volume deseni DEĞİL:** `Volume==0`/`OHLC eşit` gibi bir örüntü hiçbir zaman "bu barı düşür" kararının GEREKÇESİ olarak kullanılmaz — yalnızca **resmi BIST takvimine göre o tarih "expected session" mi değil mi** sorusu karara bağlar (`normalize_bist_daily_sessions()`, `services/market_data/trading_calendar.py`). Bu, hem yanlış-pozitif (gerçek ama sıra dışı bir işlem gününü Volume düşük diye silme) hem yanlış-negatif (farklı bir imzayla gelecek bir phantom'u kaçırma) riskini ortadan kaldırır.
  - **4 sınıf, KESİN öncelik sırasıyla** (`NonSessionClassification`): `CANCELLED_SESSION` (bkz. 6.3) → `EXTRAORDINARY_CLOSURE` (bkz. 6.3) → `PLANNED_FULL_DAY_CLOSURE` → `WEEKEND`. Bu sıralama kasıtlıdır: ör. 08.02.2023 asla genel "planlı tatil" olarak YANLIŞ etiketlenmez, kendi özel provenance'ını korur. **Yarım günler (`BIST_HALF_DAY_SESSIONS`) bu normalizasyonun KAPSAMI DIŞINDADIR** — hiçbir zaman düşürülmez, gerçek bir "expected session"dır (bkz. 6.2).
  - **Paylaşılan (shared) katman:** Bu normalizasyon **HEM canlı motorda HEM backtest'te AYNI fonksiyonla** uygulanır — bkz. `engine.py` (`TechnicalAnalysisEngine.analyze_with_id`) ve `completed_history.py` (`prepare_backtest_history`). Önceki HATA 3C-EX çözümü (`drop_cancelled_sessions()`) yalnızca backtest'e bağlıydı; canlı motor bu korumayı HİÇ almıyordu — HATA 3D bu boşluğu da kapatır.
  - **KRİTİK SIRALAMA:** Canlı motorda normalizasyon, `filter_completed_daily_bars()`'tan HEMEN SONRA ve `resolve_expected_start()` (HATA 2C pre-roll kanıt kontrolü, yukarıda) çalışmadan ÖNCE uygulanır. Aksi halde, pre-roll bölgesine (`analysis_start`'tan önceki gözlem penceresi) düşen bir phantom bar, index'te "analysis_start'tan daha ESKİ bir tarih" olarak göründüğünden, sembolün zaten işlem gördüğüne dair YANLIŞ bir kanıt (`VERIFIED_PRE_WINDOW`) üretebilirdi — bu senaryo doğrudan bir regresyon testiyle kilitlendi (`test_pre_roll_region_with_only_a_phantom_holiday_bar_is_not_verified_pre_window`).
  - **Şeffaflık (provenance):** Düşürülen her bar, `TechnicalAnalysis.session_normalization_policy` (`"AUTHORITATIVE_NON_SESSION_DROP"`) ve `normalized_dropped_sessions` (`[{"date", "classification"}, ...]`) alanlarında görünür kılınır — sessizce kaybolan bir veri YOKTUR. Backtest sonuçlarında aynı alanlar üst seviyede (top-level) taşınır; `compare_strategies()`'te preset başına TEKRARLANMAZ, tek bir yerde raporlanır.
  - **Kasıtlı olarak kullanılmayan:** `yfinance`'in `repair=True` parametresi (ek `scipy` bağımlılığı gerektirir, araştırılmadı/eklenmedi) ve OHLC/Volume tabanlı herhangi bir sezgisel (heuristic) düzeltme.

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

- `latest_expected_completed_date(now)` (bkz. bölüm 1, HATA 2A — kapanış (18:00 TSİ) + `DAILY_BAR_FINALIZATION_DELAY_MINUTES` (30 dk) payı geçmediyse DÜN, geçtiyse BUGÜN), backtest'in veri kabul edebileceği **ÜST SINIRI** belirler.
- Piyasa açıkken (veya finalization payı dolmadan) çalıştırılan bir backtest, bugünün satırını **HİÇBİR ALANIYLA** (Open dahil — "Open zaten sabit, execution için kullanılabilir" istisnası BİLİNÇLİ OLARAK YAPILMAZ) kullanmaz: skora girmez, `simulate()`'e girmez, execution fiyatı olarak kullanılmaz, terminal mark-to-market'e girmez, walk-forward'a/compare-strategies'e girmez.
- Bu filtre TEK bir yerde uygulanır (`engines/backtest/completed_history.py`, `prepare_backtest_history()`) ve üç canlı giriş noktasının (`BacktestEngine.run()`, `BacktestEngine.compare_strategies()`, `WalkForwardOptimizer.run()`) HEPSİ tarafından paylaşılır — biri filtrelenip diğerleri ham bırakılmaz. Minimum geçmiş kontrolü (`INDICATOR_WARMUP_SESSIONS`, HATA 5A ile `MIN_HISTORY_DAYS`'in YERİNE geçti — bkz. bölüm 6.7) RAW değil, bu FİLTRELENMİŞ (VE HATA 3C/3C-EX/3D ile NORMALİZE EDİLMİŞ) seri üzerinde çalışır.
- Sonuca eklenen `backtest_data_as_of` alanı, backtest'in fiilen hesaba kattığı EN SON tamamlanmış günü; `data_policy: "COMPLETED_DAILY_ONLY"` ise bu sözleşmenin adını taşır.
- HATA 3A'nın `Signal[T] → Execution[T+1 Open]` kuralı DEĞİŞMEDİ — yalnızca artık her zaman completed-only, normalize edilmiş bir seri üzerinde çalışıyor. Son tamamlanmış barda oluşan bir sinyal için backtest ufkunda henüz bir T+1 yoksa (piyasa hâlâ açıksa) bu `unexecuted_signal`/`NO_NEXT_BAR` ile doğru şekilde raporlanır — aynı backtest, ertesi günün barı tamamlandıktan sonra yeniden çalıştırılırsa o sinyal artık normal şekilde execute edilir.
- **Period sözleşmesi:** Backend, `SUPPORTED_BACKTEST_PERIODS = {"6mo","1y","2y","3y","5y"}` dışında bir `period` kabul etmez — desteklenmeyen bir değer (`max`, `10y`, `ytd`, keyfi bir string) artık 422 ile reddedilir (`prepare_backtest_history()`'de tek bir yerde doğrulanır, API route'larına ayrı bir whitelist eklenmedi). HATA 3E (26.08.2026) ile `SUPPORTED_BACKTEST_PERIODS`, her period'un takvim-ay/yıl karşılığını taşıyan `BACKTEST_PERIOD_DELTAS` mapping'inin key'lerinden TÜRETİLİR (`frozenset(BACKTEST_PERIOD_DELTAS)`) — artık ayrı, elle-bakımlı iki koleksiyon YOKTUR.

### 6.2 Veri sözleşmesi: `TRADING_SESSION_CONTINUITY` (HATA 3C, 26.08.2026)

HATA 3B ("bugünü kullanma") ile HATA 3C ("**geçmişte** olması gereken tamamlanmış bir seans gerçekten mevcut mu") **AYRI, birbirini tamamlayan iki kavramdır**:

- **HATA 3B — `COMPLETED_DAILY_ONLY`:** gelecekte/şu anda tamamlanmamış (partial, hâlâ oluşmakta olan) bir barı kullanma.
- **HATA 3C — `TRADING_SESSION_CONTINUITY`:** BIST'in resmi takvimine göre olması gereken completed bir session, provider'da (Yahoo) gerçekten var mı? Yoksa (`MISSING_TRADING_SESSION`) VEYA takvime göre "expected" OLMAYAN bir günde provider açıklanamayan bir bar döndürüyorsa (`UNEXPECTED_TRADING_SESSION`) backtest **HİÇ ÜRETİLMEZ** — interpolasyon, önceki kapanışla doldurma, "bir sonraki gözlemlenen satırı T+1 say" gibi HİÇBİR sessiz düzeltme yapılmaz. Bu kontrol `simulate()`'den ÖNCE çalışır; `WalkForwardOptimizer`'da bir middle-gap TÜM optimizasyonu durdurur — gap içeren fold'u atlayıp devam etmek (selection bias riski taşıdığı için) BİLİNÇLİ OLARAK YAPILMAZ.
- **Yarım günler** (`BIST_HALF_DAY_SESSIONS`) tam günlerle AYNI şekilde "expected" sayılır — Yahoo'nun bir yarım günün barını kaçırması (ör. 2024-04-09, Ramazan Bayramı Arefesi — BIST100'ün %58'inde doğrulandı) tam bir günün eksikliği kadar ciddi bir `MISSING_TRADING_SESSION` HARD VETO'dur.
- **Leading-edge (HATA 3E, 26.08.2026 ile ÇÖZÜLDÜ):** Continuity'nin alt sınırı artık sembolün GÖZLEMLENEN İLK barı (`df.index[0]`) DEĞİLDİR — HATA 2C'nin canlı motor için çözdüğü pre-roll/evidence mekanizması (`resolve_expected_start()`, AYNI fonksiyon, backtest için ayrı bir kopyası YAZILMADI) backtest'e taşındı. Bkz. bölüm 6.5.

### 6.3 Veri sözleşmesi: `CANCELLED` / `EXTRAORDINARY SESSION` (HATA 3C-EX, 26.08.2026)

Planlı resmi tatiller (`BIST_FULL_DAY_CLOSURES`) yeterli değildir — Borsa'nın **olağanüstü bir kararla** normal işleyişi bozduğu, yıllık tatil tablolarında YER ALMAYAN durumlar da resmi tarihsel gerçekliğe göre normalize edilir:

- **`BIST_EXTRAORDINARY_CLOSURES`** — Borsa'nın tam gün kapattığı, hiç seans açılmayan günler.
- **`BIST_CANCELLED_SESSIONS`** — seansın FİİLEN AÇILDIĞI ama o güne ait TÜM işlemlerin Borsa'nın kendi kararıyla RESMİ OLARAK İPTAL edildiği günler.

**Örnek — 08.02.2023:** 6 Şubat 2023 Kahramanmaraş depremi sonrası BIST 100 endeksi devre kesicileri (%5 saat 10:12, %7 saat 10:42) tetikledi; Borsa İstanbul, Pay Piyasası'nı saat 11:00'de durdurup 5 iş günü süreyle (14 Şubat 2023 akşamına kadar) kapattı VE **8 Şubat 2023'te gerçekleşen TÜM işlemleri Borsa İstanbul A.Ş. Yönetmeliği'nin "Emir ve İşlemlerin İptali" başlıklı 33. maddesi uyarınca resmi olarak iptal etti** (kaynak: Anadolu Ajansı, KAP duyurusunu doğrudan aktarıyor). Piyasa 15 Şubat 2023'te yeniden açıldı.

Yahoo, 08.02.2023 için **hâlâ bir bar döndürüyor** (Open=High=Low=Close — donmuş tek fiyat — ve ihmal edilebilir hacim, THYAO/GARAN/ASELS/SISE/KCHOL'de doğrudan gözlemlendi). Bu bar GERÇEK bir finalized session DEĞİLDİR — `normalize_bist_daily_sessions()` ile (`CANCELLED_SESSION` sınıflandırmasıyla) authoritative olarak DÜŞÜRÜLÜR; RSI/MACD/EMA/execution'a ASLA girmez. Sonuç: normalize edilmiş history'de 07.02.2023'ü doğrudan 15.02.2023 takip eder — 07.02'de oluşan bir sinyal, 08.02'nin (iptal edilmiş) Open'ından DEĞİL, **15.02'nin Open'ından** execute edilir.

Bu, **GENEL bir "anomali gördüm, sil" mekanizması DEĞİLDİR** — yalnızca `BIST_CANCELLED_SESSIONS`/`BIST_EXTRAORDINARY_CLOSURES`'ta AÇIKÇA, kaynak gösterilerek tanımlanmış tarihler (artı `BIST_FULL_DAY_CLOSURES`'ta tanımlı planlı tatiller — bkz. bölüm 1, HATA 3D) için çalışır. Bilinmeyen/belgelenmemiş herhangi bir başka anomalik bar (ör. hiçbir tatil/hafta sonu kaydına denk gelmeyen, hafta içi açıklanamayan bir Yahoo barı) sessizce düşürülmez — `UNEXPECTED_TRADING_SESSION` ile HARD VETO edilmeye devam eder (bkz. `test_unexpected_bar_on_genuinely_unknown_weekday_is_still_hard_vetoed`).

2021-2026 araştırıldı; bu aralıkta 2023 Şubat dışında doğrulanabilir başka bir olağanüstü tam-gün kapanış/iptal BULUNAMADI.

### 6.4 Backtest BIST100 doğrulama sonuçları (HATA 3D uygulaması sonrası, 26.08.2026)

HATA 3D'nin (bkz. bölüm 1) shared normalizasyon katmanı backtest'e (`prepare_backtest_history()`) entegre edildikten SONRA, gerçek Yahoo verisiyle TÜM BIST100 üzerinde ölçüldü:

| Period | PASS | MISSING (HARD_VETO) | Not |
|---|---|---|---|
| 6mo | 100/100 | 0 | 27-29 Mayıs 2026 phantom'ı normalize edilmeden önce 0/100 idi |
| 1y | 100/100 | 0 | aynı |
| 2y | 100/100 | 0 | aynı |
| 3y | 42/100 | 58 | TAMAMI 2024-04-09 (gerçek, GENUINE yarım gün eksikliği — bkz. bölüm 6.2) — **normalize EDİLMEDİ, bilinçli olarak dokunulmadı** |
| 5y | 41/100 | 59 | 58'i 2024-04-09 (3y ile AYNI 58 sembol), 1'i (GENIL) ayrı/farklı bir tarih (2023-04-06 — gerçek, expected bir Perşembe seansı; Yahoo bu sembolde 04-05'ten 04-07'ye doğrudan atlıyor) — HATA 3D kapsamı DIŞINDA, izole bir tek-sembol provider boşluğu |

**HATA 3E sonrası tekrar ölçüldü (26.08.2026):** explicit-window pipeline'a geçildikten SONRA bu tablo BİREBİR AYNI çıktı (6mo/1y/2y=100/100, 3y=42/100, 5y=41/100) — HATA 3E, mevcut PASS/HARD_VETO popülasyonunu DEĞİŞTİRMEDİ, yalnızca pencerenin BAŞINDaki (o an hiçbir gerçek BIST100 sembolünde rastlanmayan, ama sentetik olarak kanıtlanan) bir kör noktayı kapattı. Ek olarak `history_validation_status` dağılımı ölçüldü: 6mo=100/100 `VERIFIED_PRE_WINDOW`; 1y=99 `VERIFIED_PRE_WINDOW`/1 `LEADING_EDGE_UNVERIFIED`; 2y=96/4; 3y (PASS eden 42 içinde)=31/11; 5y (PASS eden 41 içinde)=20/21 — `LEADING_EDGE_UNVERIFIED` oranının period uzadıkça artması BEKLENEN bir sonuçtur (daha uzun bir period, daha fazla sembolün o kadar geriye giden gerçek işlem geçmişi OLMAMASI ihtimalini artırır).

### 6.5 Backtest Leading-Edge / Explicit Window (HATA 3E, 26.08.2026)

HATA 3C'nin kabul ettiği sınırlama ("middle-gap protected, leading-edge unverified") KAPATILDI. Dört AYRI kavram birbirine KARIŞTIRILMAMALIDIR:

1. **`requested_window`** — kullanıcının/period'un GERÇEKTEN istediği aralık: `target_start`/`target_end`. `target_end = latest_expected_completed_date(now)` (bölüm 6.1'in AYNI as-of'u — wall-clock "bugün" DEĞİL, çünkü `COMPLETED_DAILY_ONLY` altında "bugün" henüz kullanılabilir bir veri noktası olmayabilir); `target_start = target_end - BACKTEST_PERIOD_DELTAS[period]` (`{"6mo": 6 ay, "1y": 1 yıl, ..., "5y": 5 yıl}`, `SUPPORTED_BACKTEST_PERIODS` bu mapping'in key'lerinden TÜRETİLİR, ayrı bir elle-bakımlı liste DEĞİLDİR).
2. **Pre-roll evidence bölgesi** — `target_start`'tan biraz ÖNCESİ (`PRE_ROLL_DAYS=15` takvim günü, canlı motorla PAYLAŞILAN AYNI sabit — 2021-2026 authoritative takviminde ölçülen en uzun ardışık-seans boşluğu 8 takvim günüdür, 07-15.02.2023 deprem bloğu; 15 gün bunun ~2 katı bir marj bırakır). Yalnızca "bu sembol `target_start`'tan önce zaten işlem görüyor muydu?" sorusuna kanıt arar — `resolve_expected_start()` (canlı HATA 2C ile TAMAMEN AYNI fonksiyon, backtest'e özel bir kopyası YOK) `VERIFIED_PRE_WINDOW`/`LEADING_EDGE_UNVERIFIED` döner.
3. **`actual_history`** (a.k.a. analysis history) — normalizasyon + evidence çözümünden SONRA, `expected_start`'tan (VERIFIED ise `target_start`'ın kendisi, UNVERIFIED ise sembolün gözlemlenen ilk barı) itibaren CROP edilmiş seri. Pre-roll barları BURAYA HİÇBİR ZAMAN girmez.
4. **Indicator warm-up** — **HATA 5A (27.08.2026) ile TAMAMEN YENİDEN TASARLANDI, bkz. bölüm 6.7.** Bu maddenin HATA 3E'deki ORİJİNAL hali ("`actual_history`'nin KENDİ İÇİNDEKİ ilk `MIN_HISTORY_DAYS` (60) satırı, `warm_df = df.iloc[MIN_HISTORY_DAYS:]`") artık **YANLIŞTIR ve KALDIRILDI** — warm-up'ı istenen pencerenin İÇİNDEN kesmek, kullanıcının "1y" gibi bir period istediğinde gerçek simülasyonun istenen pencerenin ilk ~3 ayını (60 işlem günü) hiç görmeden başlamasına yol açıyordu (gerçek ölçümle `total_return_pct`'in İŞARETİNİ BİLE değiştirdiği kanıtlandı). Warm-up artık pencerenin DIŞINDAN, ayrıca sağlanır.

**İki AYRI calendar-coverage davranışı, KASITLI OLARAK farklı:**
- **Requested window** (`[target_start, target_end]`) desteklenmeyen bir yıla değerse **FAIL-CLOSED** (`TradingCalendarUnsupportedError`, provider'a HİÇ gidilmez) — `validate_calendar_coverage()` provider fetch'ten ÖNCE, `resolve_expected_start`'tan BAĞIMSIZ çalışır (aksi halde `LEADING_EDGE_UNVERIFIED`'ın `expected_start`'ı ileri taşıması bunu gizleyebilirdi — sentetik olarak kanıtlandı, regresyon testiyle kilitlendi).
- **Pre-roll** yalnızca ADVISORY bir evidence bölgesi olduğundan, desteklenmeyen bir yıla taşarsa authoritative takvimin ilk desteklenen gününe (`EARLIEST_SUPPORTED_CALENDAR_DATE`, `min(SUPPORTED_BIST_CALENDAR_YEARS)`'tan türetilir, hardcode DEĞİLDİR) KIRPILIR — yeni bir hata tipi İCAT EDİLMEZ, kırpılmış bölgede kanıt bulunamazsa zaten mevcut `LEADING_EDGE_UNVERIFIED`'a düşer. Bu ikisinin FARKLI davranmasının nedeni: biri kullanıcının AÇIKÇA istediği bir şeyin doğrulanamamasıdır (ciddi, fail-closed), diğeri yalnızca "ekstra bir kanıt bulamadık" (advisory, zaten var olan bir belirsizlik durumuna düşer).

**Provider fetch artık explicit `start`/`end`'dir, `period=` DEĞİL:** `provider.get_history(symbol, start=provider_start.isoformat(), end=provider_end.isoformat(), interval="1d")` — Yahoo'nun `period=` string'i sunucu tarafında opak yorumlandığından (yfinance kaynağı: `params={"range": period}`, istemci tarafında YENİDEN HESAPLANMAZ) artık backtest fetch sınırının otoritesi DEĞİLDİR. `provider_end = target_end + 1 takvim günü` (Yahoo `end` EXCLUSIVE — gerçek veriyle doğrulandı).

**Sonuç metadata'sı** (top-level, `BacktestEngine.run()`/`compare_strategies()`/`WalkForwardOptimizer.run()`'ın ÜÇÜNDE de, preset/fold başına KOPYALANMADAN): `requested_window_start` (kullanıcının istediği, HİÇBİR ZAMAN geriye yazılmayan `target_start`), `actual_history_start` (gerçekte kullanılan ilk bar), `history_validation_status` (`VERIFIED_PRE_WINDOW`/`LEADING_EDGE_UNVERIFIED`, canlı ile AYNI string'ler). Örnek: `period="5y"` istenip sembolün yalnızca 17 aylık gerçek geçmişi varsa, `period` alanı **hiçbir zaman** `"1y"` gibi geriye YAZILMAZ — `requested_window_start`/`actual_history_start` arasındaki fark bunu şeffaf gösterir.

**`prepare_backtest_history()` artık bir `PreparedBacktestHistory` (typed dataclass) döner** — eski 3-tuple (`df, backtest_data_as_of, normalization_result`) HATA 3E ile 6 alana çıktığından pozisyonel tuple okunaksız hale gelirdi.

**Yeni-listing tahmini YAPILMAZ:** `resolve_expected_start()` hiçbir gün-farkı eşiği KULLANMAZ, `Yahoo firstTradeDate` kullanılmaz, `Asset.listing_date` migration'ı yapılmaz — yalnızca pre-roll'da GERÇEK bir bar bulunup bulunmadığına bakılır.

Canlı motor tarafında (`analyze_with_id`, 6 aylık pencere) aynı ölçüm: **100/100 PASS**, tamamı 27-29 Mayıs 2026 için phantom normalizasyonu uyguladı (önceki durumda tamamı `UNEXPECTED_TRADING_SESSION` ile HARD VETO ediliyordu).

---

### 6.6 Breakout Event Timeline (HATA 4A/4B, 27.08.2026)

**HATA 4A** (audit-only): `market_structure.find_swing_points()`/`breakout.py` fonksiyonları **delayed-causal**'dır — bir swing point'in `event_at=T`'de gerçekleşmiş sayılması ile bunun `known_at=T+right_bars`'ta ONAYLANABİLMESİ ayrı şeylerdir; kod bunu yapısal olarak zaten doğru uyguluyor (`find_swing_points`'in penceresi `[i-left, i+right]`'in ÖTESİNE hiçbir zaman bakmaz). **Bugün hiçbir look-ahead leak YOKTUR** çünkü bu fonksiyonlar `technical_score_series()`/`DecisionEngine`'e HİÇ BAĞLI DEĞİLDİR (yalnız `signal_class`/`investment_horizon` gibi display/enrichment alanlarını besler) — **ama gelecekte historical bir score serisine bağlanırlarsa `known_at` gating ZORUNLU olacaktır**, aksi halde tam bu audit'in kanıtladığı repaint riski gerçekleşir (bir T günü için "row T"yi full-history'den okumak, T'de henüz bilinmeyen bir swing/zone'u geri sızdırabilir).

**HATA 4B** (kök neden + düzeltme): `TechnicalAnalysisEngine._compute_enrichment()`'in eski breakout çağrı deseni (`detect_breakout(..., index=len(df)-1)` HER GÜN "bugün"e yeniden ankorlanıyordu) `confirm_breakout()`'un ihtiyaç duyduğu gelecek barları hiçbir zaman "bugün"ün ÖTESİNDE bulamıyordu — bu bir look-ahead LEAK DEĞİL, TAM TERSİ: event lifecycle/state persistence YOKLUĞU. Sonuç: `breakout.confirmed` production'da DAİMA `None` kalıyordu, dolayısıyla `STRONG_BULLISH_INITIATION` (ve buna bağlı `notify_if_new_opportunity()` push bildirimi) **hiçbir zaman erişilemiyordu** — gerçek 5-sembol BIST taramasıyla kanıtlandı (retrospektif olarak %20-50 confirm oranı varken, production'ın "bugün-only" çağrı deseni her zaman `None` görüyordu).

**Çözüm — `breakout_timeline.py`, stateless (Firestore'a HİÇBİR ŞEY YAZILMAZ):**
- **Breakout = TRANSITION, state değil**: `previous_close<=zone.high<current_close` (bullish, bearish ayna simetrik) — bir seviyenin üstünde N gün kalmak N event ÜRETMEZ, yalnız seviyeyi YENİ GEÇEN bar event üretir.
- **Strict causal zone**: T günündeki bir event için zone, YALNIZ `T-1`'e kadar bilinen swing point'lerden (`known_at<=T-1`) VE `ATR[T-1]` ile kurulur — gerçek kodla kanıtlandı: aynı iki swing point, düşük ATR'de iki ayrı zone, yüksek ATR'de (ör. gelecekte oluşacak volatilite) TEK birleşmiş zone üretebiliyor; bu future-volatility leak'i T-1 kilitlemesiyle önlenir.
- **ATR ayrımı**: zone clustering ATR'si (`ATR[T-1]`) ile breakout GÜCÜ ATR'si (`ATR[T]`, `T` kapanışı itibarıyla zaten bilindiği için causal) FARKLI tutulur.
- **Frozen snapshot**: event T'de oluştuğunda `level`/`zone_snapshot` dondurulur; confirmation/retest hesaplaması zone'u ASLA yeniden cluster ETMEZ.
- **Directional scan**: eski tip-agnostik `nearest_zone()` (fiyata en yakın TEK zone, tipi ne olursa olsun) breakout tespiti için KULLANILMAZ — gerçek false-negative kanıtlandı (resistance kırılmışken en yakın support seçilip kırılım hiç görülemiyordu). Bullish yalnız RESISTANCE, bearish yalnız SUPPORT zone'larını tarar; aynı gün/yönde birden fazla zone kırılırsa en DIŞTAKİ "dominant" event seçilir.
- **Confirmation state machine**: `PENDING_CONFIRMATION` / `CONFIRMED` (`confirmed_at=T+confirm_bars`, varsayılan 3) / `INVALIDATED` (`invalidated_at`=İLK ihlal barı — üçünden biri yeter). INVALIDATED bir event, gelecekteki bağımsız bir crossing'i bloklamaz (re-break serbesttir).
- **Retest state machine**: `PENDING` / `HELD` / `FAILED` / `EXPIRED` — pencere `confirmed_at+1`'de BAŞLAR (confirmation penceresiyle ASLA çakışmaz), `RETEST_BARS` (10) sürer. `EXPIRED` ("hiç retest gelmedi") ile `FAILED` ("retest geldi, tutmadı") KASITLI OLARAK ayrı state'lerdir — eski `True/False/None` üçlüsü bu ikisini `None`'da birleştiriyordu.
- **Live selection**: `select_live_breakout_event()` önce en yeni AÇIK event'i (`PENDING_CONFIRMATION` veya `CONFIRMED`+retest `PENDING`), yoksa `MAX_EVENT_AGE_SESSIONS=15` (tamamlanmış seans, takvim günü DEĞİL; `event_at`'tan itibaren, T+15 dahil T+16 hariç) içindeki en yeni RESOLVED event'i seçer. **`INVALIDATED` event'ler live seçimde HİÇ gösterilmez** (timeline/geçmişte kalırlar) — başarısız bir setup'ı güncelmiş gibi göstermenin değeri yok.
- **Legacy API mapping** (`to_legacy_breakout_event()`, `signal_classifier.py`/API şeması HİÇ DEĞİŞMEDİ): `PENDING_CONFIRMATION→confirmed=None`, `CONFIRMED→True`, `INVALIDATED→False`; retest `PENDING/EXPIRED→retest_held=None`, `HELD→True`, `FAILED→False` (`EXPIRED≠FAILED`: "hiç gelmedi" "başarısız oldu" değildir).
- **Performans**: naif "her T için swing tespitini yeniden hesapla" yaklaşımı 5 yıllık veride **~98 saniye** sürer (kullanılamaz). Üretim algoritması, `find_swing_points()`'in `i` için penceresinin `[i-left,i+right]`'ın ÖTESİNE asla bakmadığı gerçeğini kullanarak swing tespitini VE ATR serisini TEK SEFERDE hesaplar, sonra her `T` için `known_at<=T-1` filtresi uygular — bu, per-T recompute ile UÇTAN UCA (event_id/state/confirmed_at/invalidated_at/retest alanlarının TAMAMI) MATEMATİKSEL OLARAK KANITLANMIŞ eşdeğerdir ve ~5y için **~280ms**'dir (`test_breakout_timeline.py::test_reference_prefix_matches_optimized_production_synthetic`).
- **Notification event-specific, atomic-claim dedupe**: `notify_if_new_opportunity()` artık `notify_if_strong_decision()`'ın PAYLAŞILAN `(user_id,asset)->son karar` dedupe'unu KULLANMIYOR (cross-suppression riski, gerçek kodla kanıtlandı). İlk sürüm (`(user_id,asset)->son event_id`, TEK doküman) da pre-commit audit'inde BUG çıktı: event2'nin kaydı event1'inkini overwrite ettiğinden, `select_live_breakout_event()` (event2 INVALIDATED olup düştüğünde) event1'e GERİ DÖNERSE event1 zaten bildirilmiş olmasına rağmen TEKRAR gönderiliyordu — gerçek repository sınıfıyla kanıtlandı. **Nihai tasarım**: `NewOpportunityNotificationRepository`, her `(user_id, asset, event_id)` ÜÇLÜSÜ için AYRI bir Firestore dokümanı tutar (doc id = `sha256(user_id + "\0" + asset.upper() + "\0" + event_id)` — ham concat DEĞİL, delimiter-collision riski taşımaz), `PENDING`/`SENT` durumlu ve `claim_token`'lı (UUID4) bir state machine ile: `claim_new_opportunity()` Firestore'un `DocumentReference.create()`'ının ATOMİK precondition'ını kullanır (doküman zaten varsa `AlreadyExists`) — bu, `GET /decisions/{symbol}` route'u ile günlük job'ın aynı event için eşzamanlı çalışması durumundaki duplicate riskini KAPATIR (yalnız BİRİ claim'i kazanabilir). `mark_new_opportunity_sent()`/`release_new_opportunity_claim()` bir Firestore transaction'ı İÇİNDE okuyup yalnız `status==PENDING AND claim_token` eşleşiyorsa günceller/siler — `SENT` bir doküman asla (yanlış/eski bir token'la bile) release edilemez. **Dürüst delivery semantiği (bilinçli v1 tercihi)**: Firestore transaction'ı ile harici FCM çağrısı TEK bir atomik işleme alınamayacağından "exactly-once" iddia edilmez; yalnız FCM'in AÇIKÇA (senkron) başarısız olduğu durumda claim release edilip retry mümkün kılınır — process crash nedeniyle belirsiz kalan bir `PENDING` bu sürümde OTOMATİK reclaim EDİLMEZ (DUPLICATE-AVERSE/AT-MOST-ONCE: nadir bir crash'te bildirim kaybolabilir, ama aynı event asla iki kez gönderilmez). `notify_if_strong_decision()`'ın kendi (mevcut) dedupe contract'ı HİÇ DEĞİŞMEDİ.

**Bilinçli olarak DEĞİŞTİRİLMEDİ**: `technical_score`/`components`/`DecisionEngine` ağırlıkları (breakout hiçbir zaman skora girmiyordu), backtest'in breakout'u kullanması (bugün hâlâ kullanmıyor — `technical_score_series()` yalnız RSI/MACD/EMA/Bollinger/momentum/ROC kullanır), bildirim metni/title tasarımı, genel BUY/SELL dedupe sistemi, Firestore'da tam breakout state machine persistence'ı (stateless kalır — yalnız event-specific dedupe dokümanı persist edilir, timeline'ın kendisi değil), stale-`PENDING` otomatik recovery (ayrı bir reliability konusu, bu HATA'nın kapsamı dışında).

---

### 6.7 External 60-Session Indicator Warm-up (HATA 5A, 27.08.2026)

**Bulgu:** `BacktestEngine`/`WalkForwardOptimizer`, mandatory 60 barlık warm-up geçmişini (`INDICATOR_WARMUP_SESSIONS = 60` — mevcut proje warm-up contract/buffer'ı; bkz. aşağıdaki "60'ın anlamı" notu), **istenen backtest penceresinin KENDİ İLK 60 SATIRINDAN** kesiyordu (eski `df.iloc[MIN_HISTORY_DAYS:]`). Sonuç: kullanıcı "1y" istediğinde gerçek simülasyon, istenen pencerenin **ilk ~3 ayını (60 işlem günü) hiç görmeden**, o kadar geriden başlıyordu — `requested_window_start` ile fiili simülasyonun başladığı tarih SESSİZCE FARKLIYDI. Gerçek THYAO/GARAN/AKBNK/ASELS/SISE 6mo/1y/2y ölçümüyle kanıtlandı: bu yalnızca birkaç günlük bir kayma değil, **`total_return_pct`'in İŞARETİNİ DEĞİŞTİREBİLEN** bir hataydı (THYAO 1y: düzeltmeden önce +3.52%, düzeltmeden sonra -11.97% — aynı sembol, aynı config, aynı `now`).

**60'ın anlamı (netleştirme, 27.08.2026 final commit gate):** `INDICATOR_WARMUP_SESSIONS = 60` — mevcut proje warm-up contract/buffer'ıdır. HATA 5A kapsamında sayısal değeri DEĞİŞTİRİLMEMİŞ, yalnızca requested simulation window'ın İÇİNDEN DIŞINA taşınmıştır. Bu **"matematiksel minimum"**, **"bilimsel olarak gerekli"** veya **"optimum"** bir değer OLDUĞU İDDİA EDİLMEZ — önceki bir HATA 5A audit turunda ayrıca incelendi: RSI'ın kendi binding matematiksel hazırlık noktası ~14 bar (bkz. bölüm 2), diğer göstergeler (MACD, EMA(20/50), Bollinger(20)) farklı, daha kısa lookback'ler taşır; EMA/EWM'nin pratik stabilizasyonu ayrı, kalibre edilmemiş bir konudur. 60'ın kendisinin doğru/yeterli/fazla-muhafazakar olup olmadığı bu HATA'nın kapsamı DIŞINDADIR — metodolojik değişikliği (warm-up'ın pencere dışına taşınması) İZOLE etmek için sabit tutulmuştur. 60'ın kalibrasyonu (gerekirse düşürülmesi/artırılması) ayrı, gelecekteki bir methodology audit'inin konusudur.

**Çözüm — üç AYRI, birbirine karışmayan bölge:**

**Evidence** (advisory, opsiyonel):
- `warmup_history_start`'ın (aşağıda tanımlı) ÖNCESİNDE `PRE_ROLL_DAYS=15` takvim günlük bir bölge.
- YALNIZCA leading-edge provenance içindir — "bu sembol `warmup_history_start`'tan önce zaten işlem görüyor muydu?" sorusuna kanıt arar (`resolve_expected_start()`, HATA 2C ile AYNI fonksiyon).
- **Indicator hesabına HİÇBİR ZAMAN girmez** — yalnızca `history_validation_status` (`VERIFIED_PRE_WINDOW`/`LEADING_EDGE_UNVERIFIED`) metadata'sını üretir.

**Indicator warm-up** (mandatory):
- Authoritative takvime göre `simulation_start`'tan HEMEN ÖNCEki **TAM 60 expected completed BIST session** (`previous_expected_sessions(simulation_start, 60)` — calendar-day yaklaşık DEĞİL, off-by-one'a dikkat edilerek: `simulation_start`'ın kendisi bu 60'a DAHİL DEĞİLDİR).
- `simulation_start`'tan HEMEN ÖNCE gelir; `warmup_history_start`'tan `simulation_start-1`'e kadar.
- `technical_score_series()`'in girdisidir — RSI/MACD/EMA gibi göstergelerin ısınması burada tüketilir.
- **Trade/P&L/equity/benchmark'a HİÇBİR ZAMAN girmez.**

**Simulation**:
- `simulation_start` = kullanıcının istediği `requested_window_start`'ın (bir `relativedelta` hesabı, hafta sonu/tatile denk gelebilir) KENDİSİ ÜZERİNDEKİ veya SONRASINDAKİ **ilk expected BIST session**.
- `simulation_start → target_end`.
- Backtest performansı (trade/P&L/equity/benchmark/`total_return_pct`) **YALNIZCA bu aralıkta** ölçülür.

**Kesin tarih sözleşmesi (eşitlik İDDİA EDİLMEZ — netleştirme, final commit gate):**
- `requested_window_start` = saf takvim hesabı (`target_end - BACKTEST_PERIOD_DELTAS[period]`, bir `relativedelta` sonucu) — hafta sonuna/tatile denk gelebilir, GERÇEK bir işlem günü olmak ZORUNDA DEĞİLDİR.
- `simulation_start` = `requested_window_start`'IN KENDİSİ ÜZERİNDEKİ veya SONRASINDAKİ **ilk expected BIST session**.
- `from_date` = `simulation_start` (`requested_window_start` DEĞİL).
- `to_date` = `target_end`.

Dolayısıyla `requested_window_start` bir hafta sonu/resmi tatile denk gelirse **`from_date > requested_window_start` OLABİLİR** (`simulation_start` bir sonraki gerçek seansa yuvarlanır) — bu SESSİZCE bir kayma DEĞİLDİR, `requested_window_start` alanı HİÇBİR ZAMAN geriye yazılmadığından fark her zaman şeffaf gözlemlenebilir (bkz. `test_target_start_on_weekend_resolves_to_next_valid_session`). Warm-up'ın pencere DIŞINA taşınması bu iki tarihin birbirinden AYRI kalmasını sağlar — eski hatadaki gibi warm-up'ın kesilmesiyle `from_date`'in SESSİZCE (kullanıcıya hiç yansımadan) aylarca ileri kayması artık MÜMKÜN DEĞİLDİR.

**Kritik netleştirme — evidence, mandatory warm-up'ı GEVŞETMEZ:** `LEADING_EDGE_UNVERIFIED` (yani `warmup_history_start`'ın ÖNCESİNDE kanıt bulunamadı) **mandatory warm-up completeness şartını HİÇBİR ŞEKİLDE gevşetmez** — bu yalnızca "ekstra kanıt bulamadık" bilgisidir. Mandatory warm-up aralığının (`[warmup_history_start, target_end]`) İÇİNDE beklenen ama provider'da bulunmayan **TEK bir işlem günü bile** (evidence durumu ne olursa olsun, W1 = warm-up'ın İLK seansı dahil) **HARD VETO**'dur (`TradingDayContinuityError`, `MISSING_TRADING_SESSION`). Pre-commit denetiminde gerçek kodla kanıtlanan bir tasarım hatası ("final blocker"): eğer evidence durumu bu alt sınırı belirleseydi, warm-up'ın TAM BAŞINDAKİ bir gerçek boşluk "muhtemelen kanıtsız, elimizdekiyle devam et" sanılıp SESSİZCE MASKELENEBİLİRDİ — düzeltme SONRASI bu her zaman deterministik olarak HARD VETO'dur (bkz. `test_missing_first_warmup_session_is_hard_vetoed_regardless_of_evidence_status`).

**Bilinçli trade-off:** Bu, gerçek işlem geçmişi periyodun warm-up+simulation gereksiniminden KISA olan bir sembolün (ör. gerçekten yeni bir halka arz + uzun bir period) artık zarif biçimde `LEADING_EDGE_UNVERIFIED`'a düşüp devam ETMEYECEĞİ, bunun yerine `MISSING_TRADING_SESSION` ile HARD VETO edileceği anlamına gelir — bu, DELİBERATE bir karardır (fail-closed > sessiz kısaltma), "kısa geçmiş her zaman güvenle geçer" garantisi HATA 5A ile BİLİNÇLİ OLARAK kaldırıldı.

**Eski davranışın kaldırılması:** İstenen pencerenin (`requested_window`) kendi ilk 60 satırını warm-up için kesme davranışı (`df.iloc[MIN_HISTORY_DAYS:]`) **tamamen kaldırıldı** — `BacktestEngine`, `BacktestEngine.compare_strategies()` ve `WalkForwardOptimizer` üçü de artık `prepare_backtest_history()`'nin döndürdüğü ayrı `indicator_history`/`simulation_history` çiftini kullanır; `technical_score_series()` `indicator_history` üzerinde TEK SEFERDE hesaplanır (HATA 4A prefix invariance — causal/rolling/EWM göstergeler hiçbir gelecek satıra bakmaz), sonra `simulation_history.index`'e kırpılır. `compare_strategies()`'te de her preset AYNI `indicator_history`/`simulation_history` çiftini paylaşır, ama kendi ağırlıklarıyla KENDİ skor serisini hesaplar (weights preset'ten preset'e farklı olduğundan skor serisi ASLA tek preset'ten diğerlerine reuse edilmez).

**Simulation-start arama ufku — arbitrary bound YOK (final pre-commit temizliği):** `first_expected_session_on_or_after(day, search_end)` artık `search_end`'i çağırandan alır (`completed_history.py`'de `target_end`, `validate_calendar_coverage(target_start, target_end)`'den zaten GEÇMİŞ bir üst sınır) — "bilinen en uzun kapanış bloğu N gün, M gün arasak yeter" gibi bir correctness varsayımına (eski, kaldırılan 14-günlük arama ufku) DAYANMAZ.

**Operational ölçüm (THYAO, gerçek `SystemConfigRepository()` config'i, aynı `now`):**

| Period | CURRENT (düzeltme öncesi) `from_date` | NEW (düzeltme sonrası) `from_date` | CURRENT return | NEW return |
|---|---|---|---|---|
| 6mo | 2026-06-01 | 2026-02-26 (=simulation_start) | -3.57% | -3.09% |
| 1y | 2025-11-19 | 2025-08-26 (=simulation_start) | **+3.52%** | **-11.97%** ⚠️ işaret değişti |
| 2y | 2024-11-20 | 2024-08-26 (=simulation_start) | -7.40% | -7.08% |

(Bu üç örnekte `requested_window_start`, kendisi de zaten expected bir BIST session'a denk geldiğinden `simulation_start`'a EŞİTTİR — bu bir genel kural DEĞİLDİR, yukarıdaki "kesin tarih sözleşmesi" notuna bkz.)

---

## 7. Dürüstlük İlkeleri (Özet)

- **Uydurma veri yok:** Bir gösterge hesaplanamıyorsa (yetersiz geçmiş, eksik sütun) skor üretilmez, "veri yok" denir.
- **Geleceğe bakma yok (look-ahead-bias):** Hem swing point onayı hem breakout teyidi hem de göstergelerin kendisi yalnızca o ana kadarki barlara bakar; bu ayrı bir otomatik testle (`test_indicator_causality.py`) her yeni özellik eklendiğinde tekrar doğrulanır.
- **LLM yalnızca haber analizinde:** Teknik analiz, grafik yorumu, sinyal sınıflandırması, vade etiketi ve "neden bu sinyal" anlatısının hiçbiri yapay zeka/LLM kullanmaz — hepsi burada anlatılan sabit, tekrarlanabilir matematiksel kurallardır. Aynı veriyle her zaman aynı sonuç üretilir.
- **Mum formasyonu/gap gibi zayıf sinyaller tek başına karar üretmez** — yalnızca bağlam olarak gösterilir.

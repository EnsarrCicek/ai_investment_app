# POSITION-EXIT-1 — Sonraki karşılaştırmanın değerlendirme sözleşmesi

Durum: TASLAK. Bu turda tarihsel tarama, eşik optimizasyonu veya politika seçimi YAPILMADI.
Mekanizma testleri geçmiştir; bu, herhangi bir politikanın yatırım başarısının kanıtı değildir.

## 1. Kapsam ve girişler
- Tüm politikalar (Referans, A, B, C) AYNI giriş listesiyle (sembol, giriş seansı, giriş fiyatı,
  miktar, giriş masrafı) ve AYNI ortak veri kapsamıyla çalıştırılır. Bir politikada eksik veri
  nedeniyle değerlendirilemeyen giriş, tüm politikalardan birlikte çıkarılır ve sayısı raporlanır.
- Giriş kuralı sonuçlar görülmeden önce sabitlenir; çıkış politikası girişleri değiştiremez.
- Veri: yalnızca tamamlanmış günlük barlar; takvimde olmayan yıl tahminle doldurulmaz.
- Gerçek fiyatla yapılacak her değerlendirme mevcut `position_review` engellerine tabidir
  (fiyat temeli, kurumsal işlem kontrolü); engel aşılmaz.

## 2. Referans
- "Çıkış eklenmemiş mevcut strateji": aynı girişler, kendi mevcut çıkış davranışıyla (yoksa
  yalnızca değerlendirme penceresi sonunda açık pozisyon olarak işaretlenir; sanal satış
  varsayılmaz).

## 3. Gerçekleşme varsayımı (önceden sabitlenir)
- Tarihsel OHLC'den otomatik gerçekleşme üretimi ayrı ve önceden yazılmış bir kural gerektirir
  (ör. T isteği -> T+1 açılış, kayma varsayımı, tabanda/işlem durdurmada gerçekleşmeme).
  Bu kural yazılmadan karşılaştırma çalıştırılmaz. Tavan/taban kilidi ve durdurma günleri
  gerçekleşmemiş sayılır.
- Komisyon oranı, asgari komisyon ve kayma varsayımı çıktıda açıkça yazılır; sonuçlar
  VARSAYIMA_DAYALI olarak etiketlenir.
- Masraf modeli (TEMSİLİ; gerçek kurum tarifesi bilinmiyor): asgari komisyon İSTEK (emir)
  başına, istekteki kümülatif brüt üzerinden uygulanır; parçalı dolumlar asgari komisyonu
  tekrar yüklemez. Raporda gerçek komisyon varsa o kullanılır. Kayma varsayımı yalnızca
  planlamada kullanılır; raporlanan dolum fiyatına ikinci kez uygulanmaz.
- İstek yaşam döngüsü: tam çıkış gerekçesi (zarar/iz süren/azami süre) aktif kısmi istek
  nedeniyle atlanmaz; çıkış niyeti kaydedilir, eski isteğe iptal talebi yazılır ve yeni tam
  çıkış isteği ancak eski istek raporla kapandıktan veya iptali onaylandıktan sonra güncel
  kalan adet için oluşturulur. Karşılaştırmada gerçekleşmeyen ve iptal beklenen istekler de
  raporlanır.

## 4. Raporlanacak ölçüler (hepsi, seçici değil)
- Masraf sonrası toplam özsermaye eğrisi (gerçekleşmiş + gerçekleşmemiş, aynı tarih ekseninde).
- Azami düşüş (özsermaye eğrisi üzerinden).
- Gerçekleşmiş kâr/zarar ve pencere sonundaki gerçekleşmemiş kâr/zarar ayrı ayrı.
- Anapara geri kazanım süresi (seans) ve geri kazanılamayan pozisyon sayısı.
- Pozisyonda kalma süresi dağılımı (seans).
- Gerçekleşmeyen / kısmen gerçekleşen çıkış istekleri sayısı ve oranı.
- Çıkış nedenlerinin dağılımı (STOP_LOSS, TRAILING_STOP, MAX_HOLD, TARGET).

## 5. Yasak raporlama biçimleri
- Yalnızca kapanmış kazançlı işlemleri raporlamak; açık zararları veya kapanmamış
  pozisyonları dışlamak.
- "Kazanma oranı"nı özsermaye ve düşüş ölçüleri olmadan tek başına sunmak.
- Sonuç görüldükten sonra hedef, zarar sınırı, iz süren mesafe veya azami süre değiştirip
  aynı veride yeniden raporlamak (yapılırsa keşifsel olarak ayrıca etiketlenir).

## 6. Veri bölmesi
- 2024–2025 bu projede daha önce incelendi; bağımsız holdout DEĞİLDİR. Bu dönemdeki her sonuç
  keşifsel olarak etiketlenir.
- Bağımsız değerlendirme ancak sonuçlar görülmeden önce ayrılmış ve daha önce incelenmemiş bir
  dönemle yapılabilir.

## 7. Karar kuralı
- Hiçbir sonuç çıkmadan "en iyi politika" seçilmez. Seçim kriteri (ör. masraf sonrası özsermaye
  ve azami düşüş birlikte) karşılaştırma çalıştırılmadan önce bu belgeye eklenir.
- %10 hedef kullanıcı deney parametresidir; doğrulanmış optimum değildir.

## Kaynak notları
Aşağıdaki kaynaklar mekanizma ve davranışsal arka plan içindir; belirli bir yüzdeyi veya BIST
stratejisinin başarısını KANITLAMAZ:
- SEC Investor Bulletin (stop/stop-limit emir mekaniği; stop fiyatı gerçekleşme fiyatını garanti etmez):
  https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-15
- Kaminski & Lo, "When do stop-loss rules stop losses?":
  https://dspace.mit.edu/entities/publication/bb69ca4b-0cdc-487f-831d-63b2e84fafee
- Odean, "Are Investors Reluctant to Realize Their Losses?" (elden çıkarma etkisi):
  https://faculty.haas.berkeley.edu/odean/papers/disposition/disposition.html
- Borsa İstanbul Pay Piyasası işleyişi:
  https://www.borsaistanbul.com/piyasalar/pay-piyasasi/piyasa-isleyisi

---

# EXIT-EXP-1 — Önerilen tek deney (29.09.2026, sonuçlara BAKILMADAN yazıldı)

## A. Veri yeterliliği (dosya/alan düzeyinde doğrulandı)
- Kaynak: `app/research/market_risk_shadow/runs/universe_20260925/` (yerel, git'e alınmamış).
  `universe_manifest.json`: 100 sembol, 09.09.2026 tarihli (universe_as_of_date) dondurulmuş V2 listesi; 2024–2025
  tarihsel BIST100 üyeliği DEĞİL (hayatta kalma yanlılığı mümkün).
- Fiyat: `inputs/{SYM}_provider_ohlcv.csv` (Date, Open, High, Low, Close, Volume).
  `fetch_manifest.json` → `price_adjustment`: yfinance `auto_adjust=True` (bölünme+temettü
  düzeltmeli, 25.09.2026 referanslı). Bu fiyatlar o günkü gerçek işlem fiyatı DEĞİLDİR;
  RAW_UNADJUSTED etiketlenemez; gerçek tam lot, TL maliyet ve asgari komisyon hesabını
  DESTEKLEMEZ. Yerelde ham (düzeltilmemiş) OHLC yok.
- Kurumsal işlem: `inputs/{SYM}_corporate_actions.csv` Yahoo'nun bildirdiği Dividends/Stock
  Splits kayıtlarıdır (tamlığı doğrulanmadı); 8 sembolde dosya YOK (AKBNK, ASELS, BIMAS, EREGL,
  KCHOL, TCELL, TUPRS, THYAO — sepet çalışmasından yeniden kullanılan girdiler). Bedelli/bedelsiz
  sermaye artırımı kaydı yok.
- Sinyal: `results/{SYM}.json` → `rows[]` (session, technical_status, raw_class_technical_only,
  technical_score); 2024-01-02..2025-12-31, 501 beklenen seans × 100 sembol. Sınıf
  `_classify(score, DEFAULT_THRESHOLDS)` ile üretildi (üretim BacktestEngine eşikleri config'ten
  okur; farklı olabilir). 10.423 sembol-günde teknik sınıf yok (TECHNICAL_UNAVAILABLE).
- Sonraki seans açılışı: 50.100 beklenen sembol-seansın 2.011'inde bar YOK; 72 günde hacim 0;
  69 günde O=H=L=C (tek fiyat). Bu günler kesin "taban/tavan kilidi" olarak YORUMLANMAZ.
- Referans giriş sinyali sayısı (yalnızca sayım): 2024: 266, 2025: 402.

## B. Sonuç: iki deneyden yalnızca biri çalıştırılabilir
- Gerçek TL / tam lot / anapara tahsilatı deneyi: ÇALIŞTIRILAMAZ. Engelleyen somut eksik:
  (1) 100 sembol için 2024–2025 ham (auto_adjust=False) günlük OHLC; (2) aynı dönem için
  yürürlük/hak kullanım tarihli, tamlığı doğrulanmış bölünme/bedelsiz/bedelli kayıtları.
  Bunlar olmadan `position_review` engelleri aşılmaz.
- Önerilen tek deney: **EXIT-EXP-1, getiri bazında normalize edilmiş KEŞİFSEL karşılaştırma**
  (düzeltilmiş fiyatlarla). Gerçek portföy deneyinin YERİNE GEÇMEZ.

## C. Cevapladığı soru
"Mevcut referans stratejinin AYNI girişleri sabitken, A/B/C çıkış kurallarını eklemek, giriş
başına masraf sonrası normalize getiri yolunu, açık zararları, düşüşü ve pozisyonda kalma
süresini referansa göre nasıl değiştirir?"
Cevaplayamadıkları: tam lot yuvarlaması (B'nin tam lot ihtiyacı), asgari komisyon, gerçek TL
komisyon/nakit, gerçek anapara tahsilat tutarı, temettünün nakit olarak ayrı alınması
(düzeltilmiş seride temettü fiyata gömülüdür), gerçek dolum/kısmi dolum, fiyat adımı ve
tavan/taban kilidi.

## D. Referans (koddan: `app/engines/backtest/engine.py::simulate`)
- T kapanışında sınıf BUY/WEAK_BUY ve pozisyon yoksa → T+1 açılışında giriş; eldeyken
  SELL/WEAK_SELL → T+1 açılışında tam çıkış. HOLD veya sınıf yoksa pozisyon sürer. Zarar sınırı,
  hedef, azami süre ve komisyon YOK.
- Bu deneyde referans aynı kuralla, kayıtlı `raw_class_technical_only` üzerinden uygulanır.
  Fark (bilinçli): mevcut `simulate` eksik satırda bir sonraki MEVCUT satıra geçer; bu deneyde
  T+1 BEKLENEN BIST seansıdır (aşağıdaki gerçekleşme kuralı).

## E. Giriş, ufuk ve politikalar
- Girişler: yalnızca referansın girişleri (sembol başına referans sıra ile). A/B/C'nin erken
  çıkışı YENİ giriş üretmez.
- Ortak ufuk (epizot): giriş gerçekleşmesinden referans çıkış gerçekleşmesine kadar; referans
  2025-12-31'e kadar çıkmadıysa son kapanışta açık (gerçekleşmemiş) olarak işaretlenir.
- A/B/C referansın ÜZERİNE eklenir: her biri kendi çıkış kuralıyla veya referans çıkışıyla
  (hangisi önceyse) çıkar; çıktıktan sonra epizot sonuna kadar nakitte (getiri 0) kalır.
- Parametreler (başlangıç deney varsayımı; optimum DEĞİL, bu turda tarama YOK): hedef %10,
  zarar sınırı %8, iz süren %5 (yalnızca C), azami süre 20 tamamlanmış seans.
- Hedef tanımı (koddan): tamamlanmış kapanış >= giriş gerçekleşme fiyatı × 1,10 — BRÜT fiyat
  artışı, masraf sonrası getiri DEĞİL. Zarar sınırı ve iz süren sınır da kapanışla ölçülür.
- B (koddan): hedefte, tahmini net tahsilatla başlangıç anaparasını karşılayan en küçük miktar;
  anapara geri kazanıldıktan sonra kalan miktara hedef bir daha uygulanmaz, iz süren sınır YOK;
  kalan yalnızca zarar sınırı (giriş fiyatına göre), azami süre ve referans çıkışıyla çıkar.
- C (koddan): hedefte başlangıç miktarının %50'si bir kez; iz süren sınır hedef görüldüğü
  seansta etkinleşir; tepe, girişten sonraki tamamlanmış kapanışlardan hesaplanır.
- Motor değerlendirmeyi giriş seansından SONRAKİ kapanıştan başlatır (mevcut sözleşme).
- Normalizasyon: her epizot sabit 100.000 birimlik miktarla (lot_size 1) çalıştırılır;
  sonuçlar giriş anaparasına oranla (%) raporlanır. Bu gerçek lot/TL anlamı taşımaz.

## F. Gerçekleşme sözleşmesi (varsayımsal, çevrimdışı)
- T kapanışındaki istek → en erken sonraki BEKLENEN seans T+1'in Open fiyatında TAM dolum
  VARSAYIMI; koşul: T+1 barı var, Open sonlu ve > 0, hacim > 0.
- Koşul sağlanmazsa: sonraki mevcut bara ATLANMAZ; istek GERCEKLESME_BELIRSIZ olur ve epizot
  TÜM politikalar için birlikte "belirsiz" sınıfına alınır; sayıları ve listesi raporlanır
  (sessizce çıkarılmaz). Aynı kural referans giriş ve çıkışına da uygulanır.
- Günlük OHLC emir sırasını, alıcı miktarını ve gerçek dolumu KANITLAMAZ; tek fiyatlı
  (O=H=L=C) günlerdeki dolumlar ayrıca işaretlenip sayılır, kesin kilit sayılmaz.
- Gerçekleşme raporları motor dışında bu kurala göre önceden üretilir; motorda rapor alınma
  zamanı olmadığı için bu yalnızca olay sıralı çevrimdışı simülasyondur, canlı emir güvenliği
  iddiası taşımaz.

## G. Masraf
- TEMSİLİ: her alım ve satım dolumunda %0,1 komisyon; asgari komisyon 0 (normalize deneyde
  anlamsız); dolum fiyatına ayrıca kayma uygulanmaz. Tüm sonuçlar VARSAYIMA_DAYALI.

## H. Raporlama (yıl bazında 2024 ve 2025 ayrı + birlikte; hepsi zorunlu)
- Referans, A, B, C için aynı epizot kümesi: epizot sayısı, belirsiz epizot sayısı.
- Masraf sonrası toplam normalize getiri ve dağılımı (medyan, alt %10), açık (gerçekleşmemiş)
  zararlar ayrı.
- Azami düşüş: eşit birimli epizotların günlük birleşik P&L eğrisi üzerinden; aynı anda açık
  azami epizot sayısı ve bunun gerektirdiği sermaye ayrıca raporlanır (bağımsız işlem
  karşılaştırması, 1.000 TL'lik portföy performansı DEĞİLDİR).
- Anapara geri kazanım süresi (seans) ve geri kazanılamayan epizot sayısı.
- Pozisyonda kalma süresi (seans) dağılımı; çıkış nedenleri dağılımı.
- Gerçekleşmeyen/belirsiz çıkış istekleri; tek fiyatlı günde dolum sayısı.
- Yasak: yalnızca kazançlı kapanmış işlemleri raporlamak; açık zararları dışlamak.

## I. Dönem ve karar
- 2024–2025 daha önce MARKET-RISK çalışmalarında incelendi; bağımsız holdout DEĞİLDİR.
  Sonuçlar keşifseldir.
- Sonuç görülmeden seçim kriteri: yok. "En iyi politika" seçilmez; parametre değiştirilip aynı
  veride yeniden raporlanırsa ayrı keşifsel etiket alır.

## J. Çalıştırılabilirlik
- EXIT-EXP-1 için VERİ engeli yok (yerel veri yeterli). Çalıştırmak için henüz YAZILMAMIŞ
  bir yerel koşucu gerekir: (1) referans epizotlarını ve F kuralına göre gerçekleşme
  raporlarını üretmek, (2) motora "referans çıkışı" gerekçesini eklemek (şu an motorda yok).
- Gerçek TL/lot deneyi: B bölümündeki iki veri eksikliği giderilmeden ÇALIŞTIRILAMAZ.

## K. EXIT-EXP-1 uygulama kararları (29.09.2026, sonuçlar HESAPLANMADAN yazıldı)
Kapsam: düzeltilmiş fiyatlarla KESİRLİ miktarlı normalize araştırma. Gerçek TL, tam lot, gerçek
anapara tahsilatı veya uygulanabilir emir sonucu DEĞİLDİR; `position_review` kapılarından
geçmez ve geçirilmez. Tam lot motoru (`engine.py`) kullanılmaz ve değiştirilmez; ayrı
`normalized.py` hesaplayıcısı kullanılır.

1. Sermaye: her epizot 1 birim (alış komisyonu dahil): miktar q0 = 1 / (P0 × 1,001). Satış
   nakdi ufuk sonuna kadar getirisi 0 olarak tutulur; yeniden yatırım yok.
2. Parametreler (sabit, araştırma varsayımı): brüt hedef kapanış >= P0 × 1,10; zarar sınırı
   kapanış <= P0 × 0,92; C iz süren: kapanış <= tepe × 0,95 (tepe = girişten itibaren
   tamamlanmış kapanışların en yükseği, hedef görüldüğü seans etkinleşir, o seansın
   kapanışında tetiklenmez); azami süre: giriş seansı 1. seans sayılır, 20. seans kapanışında
   istek; komisyon alış ve satışta %0,1, asgari yok, ek kayma yok.
3. Giriş açılışta bilindiği için giriş seansının KAPANIŞI da değerlendirilir (tam lot motorundan
   bilinçli fark).
4. B: anapara hedefi 1 birim. Hedef kapanışında kesirli miktar = (1 − kümülatif net tahsilat) /
   (T kapanışı × 0,999), kalanla sınırlı; T+1 açılışı KULLANILMAZ. Gerçekleşen net tahsilat
   1'e ulaşmazsa "geri alındı" sayılmaz; hedef sonraki bir kapanışta yeniden sağlanırsa kalan
   eksik için yeniden planlanır. Geri kazanımdan sonra kalan: zarar sınırı, azami süre,
   referans çıkışı (iz süren yok).
5. C: hedefte başlangıç miktarının tam %50'si bir kez (kesirli); kalan iz süren sınırla.
6. Olay sırası (her beklenen seans): (a) önceki kapanıştan gelen istek bu seansın açılışında
   VARSAYIMSAL dolar; (b) bu seansın kapanışı değerlendirilir. Aynı kapanıştan dolum yok.
7. Dolum koşulu: bar var, Open sonlu > 0, hacim > 0. Değilse sonraki bara ATLANMAZ →
   GERCEKLESME_BELIRSIZ. Pozitif günlük hacim gerçek açılış dolumunu kanıtlamaz; tüm dolumlar
   VARSAYIMSAL. Tek fiyatlı (O=H=L=C) günde dolum dahil edilir ama bayraklanır ve sayılır;
   taban/tavan olarak etiketlenmez.
8. Referans (backtest `simulate` mantığı, kayıtlı `raw_class_technical_only`, DEFAULT_THRESHOLDS;
   canlı config okunmaz): 2024-01-02'de DÜZ başlar. Gözlenen sinyal = sınıf var VE geçerli
   kapanışlı bar var. Düzken AL/ZAYIF AL → T+1 açılışında giriş; eldeyken SAT/ZAYIF SAT →
   T+1 açılışında çıkış.
9. Belirsizlik (HOLD sayılmaz): düzken veya eldeyken sinyal gözlenemezse referans durumu
   BİLİNMİYOR olur; eldeki epizot BELİRSİZ (SIGNAL_MISSING_WHILE_HOLDING). Giriş/çıkış dolumu
   belirsizse durum yine BİLİNMİYOR. BİLİNMİYOR durumundaki AL günleri giriş SAYILMAZ, ayrıca
   sayılır. Durum yalnızca gözlenen SAT/ZAYIF SAT gününden sonraki seans açılışı dolum
   koşulunu sağlarsa o seansta DÜZ'e döner (hayali elde tutma dalında da çıkış olurdu).
10. Ortak küme: referans epizodu belirli VE Referans/A/B/C'nin hiçbirinde gerçekleşme belirsizliği
   yok. Hariç tutulanlar kimlik, neden ve politika ile ayrıca listelenir; sıfır getirili
   sayılmaz; ortak küme sonuçları bütün girişlere genellenmez.
11. Ufuk: referans çıkışı gerçekleştiyse o açılışta biter (A/B/C'nin kalanı aynı açılışta
   REFERENCE_EXIT ile çıkar). Dönem sonunda açıksa son kapanışla değerlenir; zorunlu satış yok;
   son seans kapanışındaki istek UNEXECUTED_AT_WINDOW_END olarak sayılır.
12. Aynı açılışta birden çok neden: öncelik STOP_LOSS > TRAILING_STOP > MAX_HOLD >
   REFERENCE_EXIT > TARGET; tam çıkış nedeni varsa kalanın tamamı satılır.
13. Ölçüler: getiri = son değer − 1 (açık kalan: nakit + miktar × son kapanış, satış masrafı
   düşülmeden); gerçekleşmemiş = miktar × (son kapanış − 1/q0). Epizot içi azami düşüş: 1'den
   başlayan günlük değer yolunda (nakit + miktar × kapanış) tepeden en büyük düşüş. Tam çıkış
   süresi = giriş ile tam çıkış açılışı arası seans. Kaçırılan yükseliş = tam çıkıştan sonra
   ufuk içindeki en yüksek kapanış / çıkış fiyatı − 1 (yalnızca ufuktan önce çıkanlar).
   Yıl = giriş sinyali seansının yılı. Örtüşen epizotlar bağımsız gözlem değildir; aynı anda
   açık azami epizot sayısı raporlanır. Portföy toplam/yıllık getiri veya portföy düşüşü
   ÜRETİLMEZ.

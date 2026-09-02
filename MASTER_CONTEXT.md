# MASTER_CONTEXT.md — AI Destekli Yatırım Analiz Uygulaması

> Bu dosya, `KURULUM_GUNLUGU.md` (2153 satır, AŞAMA 1-70 + kurulum kayıtları) yerine yeni oturumlarda hızlı bağlam yüklemek için hazırlanmıştır. Kurulum/araç kurulumu detayları (Git, Flutter SDK, Android Studio, Python, Firebase CLI, gcloud vb.) bilerek dışarıda bırakılmıştır — gerekirse `KURULUM_GUNLUGU.md` bölüm 1-14 ve 27'ye bakın. Ayrıntılı geliştirme geçmişi (her AŞAMA'nın tam hikayesi, hata/çözüm zincirleri) için de aynı dosyaya bakılabilir; burada yalnızca güncel/özet durum var.

## 1. Projenin Amacı

BIST (Borsa İstanbul) hisseleri ve TEFAS fonları için gerçek piyasa/haber/makro verisine dayanan, **uydurma veri kullanmayan** bir AI destekli yatırım analiz mobil uygulaması (Flutter). Kullanıcıya her varlık için AL/ZAYIF AL/TUT/ZAYIF SAT/SAT kararı, bu kararın gerekçesini, portföy takibi/kâr-zarar, risk metrikleri, backtest, fon önerileri, halka arz takibi ve push bildirimleri sunar. Temel ilke: her sayı gerçek bir kaynaktan gelir, veri eksikse dürüstçe "veri yok" denir, hiçbir zaman fabrikasyon yapılmaz. Kararlar (`ai_decisions`, `technical_analyses`, `news_analyses`) immutable (değiştirilemez/silinemez) kayıtlardır — denetlenebilirlik için.

## 2. Güncel Mimari (Genel Resim)

```
Flutter (Android, gerçek cihaz + emulator)
   │  HTTPS + Firebase ID token (Authorization: Bearer ...)
   ▼
FastAPI backend (Google Cloud Run, europe-west1)
   │  Firebase Admin SDK (ApplicationDefault credentials)
   ▼
Firestore (native mode, eur3) ──┬── system_config (ağırlıklar/eşikler, hard-code değil)
                                 └── tüm append-only/immutable koleksiyonlar
   │
   ├─ Yahoo Finance (yfinance) → BIST fiyat/geçmiş/haber/makro/analist verisi
   ├─ Google News RSS         → Türkçe haber
   ├─ Foreks RSS (resmi)      → Borsa haberleri
   ├─ TEFAS JSON API (pytefas)→ Fon verisi
   ├─ halkarz.com (HTML)      → Halka arz verisi
   ├─ OpenAI API              → EventIntelligenceEngine (haber duygu analizi)
   └─ Firebase Cloud Messaging→ Push bildirimleri

Google Cloud Scheduler → her gün 08:00 (Europe/Istanbul) → POST /jobs/daily-analysis
   (X-Job-Secret header ile korunur) → BIST100'ün tamamını otomatik analiz eder
```

Motorlar arasında **provider mimarisi** ilkesi hâkim: veri kaynakları (`MarketDataProvider`, `NewsProvider`, `MacroDataProvider`) soyut arayüzler arkasına gizlenir, somut implementasyon (Yahoo/Google/Foreks/TEFAS) değişirse motor kodu etkilenmez.

**Scheduler/otomasyon kısıtı:** Proje başlangıçta hiç zamanlayıcı içermiyordu — her motor yalnızca bir HTTP isteği geldiğinde çalışıyordu (maliyet/basitlik). AŞAMA 70 ile TEK bir otomasyon eklendi: günlük toplu analiz job'ı. Bunun dışında hâlâ "kullanıcı isteği tetikler" modeli geçerli (ör. macro/technical/news skorları belirli TTL'lerle cache'lenip son kaydedilen okunur, otomatik arka planda sürekli yeniden hesaplanmaz).

## 3. Flutter / FastAPI / Firebase / Cloud Run Yapısı

- **Flutter (mobil, Android odaklı):** `lib/features/<özellik>/*.dart` (ekranlar), `lib/models/*.dart` (JSON parse modelleri), `lib/services/api/*.dart` (her biri backend'in bir alt kaynağına karşılık gelen HTTP istemcisi), `lib/utils/*.dart` (ortak yardımcılar: `decision_style.dart`, `app_gradients.dart`, `url_launch.dart`).
  - Giriş noktası `lib/main.dart`: `AuthGate` → `authStateChanges()`'e göre `LoginScreen`/`RootScreen`. `RootScreen`, `NavigationBar` ile 5 sekme: Analiz (Dashboard) / Portföy / Fonlar / Makro / Ayarlar.
  - API taban adresi: `lib/services/api/api_config.dart` içindeki tek `apiBaseUrl` sabiti (şu an gerçek Cloud Run URL'i).
  - Tüm ekranlarda `GradientAppBar` (mavi gradyan tema, AŞAMA 68).
- **Backend (FastAPI, Python 3.13):** `backend/app/` altında katmanlı yapı:
  - `api/` — route handler'lar (ince, iş mantığı yok)
  - `engines/<isim>/engine.py` — asıl hesaplama/karar mantığı (technical, macro, decision, explanation, event_intelligence, risk, backtest, funds, analysts, journal)
  - `services/<kaynak>/` — dış veri sağlayıcı adaptörleri (market_data, news, macro, funds, ipo, analysts, notifications, jobs)
  - `repositories/` — Firestore CRUD, her koleksiyon için ayrı dosya
  - `models/` — Pydantic veri modelleri
  - `schemas/` — API girdi/çıktı şemaları (modelle birebir aynı olmayabilir)
  - `core/` — `config.py` (.env okuma), `firebase.py` (Firestore client), `auth.py` (Firebase ID token doğrulama)
  - `main.py` — FastAPI app + router bağlama
  - `tests/` — pytest, 407+ test (bkz. bölüm 14)
- **Firebase:** Proje ID `ai-investment-app-2026`. Auth (e-posta/şifre), Firestore (native, eur3), Cloud Messaging (push), Firestore Security Rules (yalnızca ileride doğrudan istemci-Firestore erişimi olursa devreye girecek savunma katmanı — backend Admin SDK kullandığından şu an bypass ediliyor, gerçek güvenlik sınırı backend'in ID token doğrulamasıdır).
- **Cloud Run:** Backend `https://ai-investment-backend-244094132223.europe-west1.run.app` adresinde çalışıyor (`backend/Dockerfile`, `python:3.13-slim`). Sırlar (`OPENAI_API_KEY`, `DAILY_JOB_SECRET`) Secret Manager / env var, kaynak kodda hiç yok. Timeout 1800s (günlük toplu analiz job'ı için yükseltildi).

## 4. TechnicalAnalysisEngine

Dosya: `backend/app/engines/technical/engine.py` (+ aynı klasördeki 15+ yardımcı modül: `indicators.py`, `data_quality.py`, `market_structure.py`, `support_resistance.py`, `breakout.py`, `relative_volume.py`, `regime.py`, `relative_strength.py`, `multi_timeframe.py`, `signal_classifier.py`, `gap_analysis.py`, `candlestick_patterns.py`, `chart_patterns.py`, `vwap.py`, `session_timing.py`, `narrative.py`).

- Girdi: Yahoo Finance (`BistProvider`) OHLCV geçmişi.
- Çekirdek skor bileşenleri (ağırlıklı toplam → `technical_score`, -100..+100): RSI, MACD, EMA trend, Bollinger, Momentum, ROC, EMA slope. Ağırlıklar `system_config/technical_indicator_weights`'ten okunur (hard-code değil), `final_score` ağırlık toplamına bölünerek normalize edilir.
- `confidence`: alt-skorların yön uyumu + hacim doğrulaması (yalnızca skor büyüklüğünden üretilmez).
- **Zenginleştirme katmanı** (aynı veriden, ek ağ isteği olmadan hesaplanır, skoru DEĞİŞTİRMEZ, `TechnicalAnalysis`'e ek alan olarak eklenir): market structure (HH/HL/LH/LL), destek/direnç bölgeleri (`all_zones`, en yakın 8 bölge), breakout/false-breakout/retest durumu, göreli hacim, volatilite/trend rejimi, göreli güç (XU100'e göre, paylaşımlı/cache'li benchmark servisiyle N+1 sorunu olmadan), çoklu zaman dilimi uyumu (günlük+haftalık, haftalık günlükten türetilir — ek istek yok), 7 sınıflı sinyal taksonomisi (`signal_classifier`, STRONG_BULLISH_INITIATION..NO_SIGNAL), gap analizi, mum formasyonları (Doji/Hammer/Engulfing — yalnızca tespit, yorum yok), grafik formasyonları (Double Top/Bottom, neckline onaylı), kural tabanlı Türkçe "neden bu sinyal" anlatısı (`narrative.py`, LLM yok).
- **Yatırım vadesi sınıflandırması** (`horizon_classifier.py`, AŞAMA 71): `signal_class`/`market_structure`/`trend_regime`/`relative_strength_class`/`mtf_aligned`/`mtf_consensus`'tan saf kural tabanlı (LLM yok, haber/makro karıştırılmaz) `investment_horizon` (KISA_VADELI/ORTA_VADELI/UZUN_VADELI/BELIRSIZ) + `investment_horizon_reason` üretir ve `TechnicalAnalysis`/API'de hâlâ mevcuttur. **HATA 8C (02.09.2026): artık Teknik sekmesinde GÖSTERİLMİYOR** — HATA 8/8A empirik doğrulaması bu etiketlerin gerçek bir yatırım vadesi olarak kalibre edilmediğini kanıtladı (KISA_VADELI, 40-90 günde UZUN_VADELI'den daha iyi performans gösteriyor); alan geriye dönük uyumluluk/araştırma için backend'de kalmaya devam ediyor, yeniden tasarım HATA 8B'de planlandı.
- **Cache:** `TECHNICAL_CACHE_TTL_SECONDS = 900` (15 dk) — Firestore'da en son hesaplanmış kayıt varsa yfinance'e hiç gidilmez (Dashboard'un 100 sembollük yüklemesini 60-80 sn'den birkaç saniyeye indirdi).
- **Veri kalitesi hard-veto'ları:** `data_quality.py` — eksik sütun/yetersiz geçmiş/bayat veri durumunda skor üretilmez.
- **Look-ahead-bias önlemi:** Bugünün tamamlanmamış barı hesaba katılmaz; `test_indicator_causality.py` regresyon testiyle kilitli.
- Bilinçli olarak skora/UI'ya bağlanmayan: `vwap.py`/`session_timing.py` (intraday veri birikimi otomatik değil, gerçekte veri yok).

## 5. EventIntelligenceEngine

Dosya: `backend/app/engines/event_intelligence/engine.py` (+ `usage.py` maliyet takibi).

- Sağlayıcı: **OpenAI**. Model adı hard-code değil, `.env`'den (`EVENT_INTELLIGENCE_PRIMARY_MODEL`, varsayılan `gpt-5.6-luna`). İkinci, daha güçlü model için fallback mimarisi (`gpt-5.6-terra`, `_should_escalate()`) tasarlanmış ama gerçek ikinci çağrı henüz YAPILMIYOR — bilinçli erteleme.
- Yapılandırılmış çıktı: OpenAI structured outputs (`json_schema`, `strict: True`) + Pydantic `NewsAnalysis` ile ikinci doğrulama — serbest metin asla saklanmaz.
- Çıktı alanları: `sentiment_score` (-100..+100), `confidence` (0-1), `importance` (0-1), `event_type`, Türkçe `reasoning`, `time_horizon` (`short_term`/`medium_term`/`long_term`, AŞAMA 69), `sentiment_label` (sentiment_score'dan türetilmiş computed field).
- Maliyet kontrolü: her çağrı `token_usage_logs`'a gerçek token sayısı + tahmini maliyet (fiyat tarifesi `usage.py`'de) yazar. Bütçe `system_config`'ten (`EVENT_INTELLIGENCE_BUDGET_USD`, varsayılan $5). Aynı haber tekrar analiz edilmez (`get_by_news_id` + `asset` filtresi — AŞAMA 69'da çoklu-varlık karışması hatası düzeltildi).
- **Maliyet ilkesi:** `GET /decisions/{symbol}` (Dashboard her açılışta çağırır) YENİ bir OpenAI çağrısı yapmaz — yalnızca daha önce `POST /news/{symbol}/analyze` ile üretilmiş kayıtları okur. Analiz yalnızca kullanıcı "Analiz Et" butonuna bastığında veya günlük otomatik job çalıştığında tetiklenir.
- Prompt kalitesi: boş özet alanı prompta hiç eklenmiyor, sistem promptu yalnızca başlığa dayanarak "yeterli bilgi yok" gibi kaçamak cevaplar üretmemesi için netleştirildi; mümkün olduğunda gerçek makale gövdesi de (`article_fetcher.py`, BeautifulSoup) eklenir.

## 6. MacroAnalysisEngine

Dosya: `backend/app/engines/macro/engine.py`.

- Kaynak: Yahoo Finance, anahtarsız. Göstergeler: DXY, ABD 10Y tahvil faizi, VIX, petrol (WTI), altın, USD/TRY.
- Yön sözleşmesi: TÜM göstergelerde yükseliş = risk-off/BIST için negatif.
- `macro_score`: her göstergenin N-günlük (varsayılan 20g) yüzde değişimi × ölçek faktörü × `system_config/macro_indicator_weights` ağırlığı.
- Varlığa özel değildir (piyasa geneli) — `GET /analysis/macro` ile ayrı tetiklenir, en son kaydedilmiş `macro_snapshots` kaydı `DecisionEngine` tarafından okunur (otomatik yeniden hesaplama yok).
- Bilinçli eksik: Fed/TCMB faiz kararları, enflasyon/istihdam verileri (FRED/TCMB EVDS gibi API anahtarı gerektiren kaynaklar) henüz yok.

## 7. DecisionEngine

Dosya: `backend/app/engines/decision/engine.py`.

- `decide_for_asset()`: technical_score (ağırlık 0.50) + news_score (0.30, `_aggregate_news_score()` — son 10 analizin confidence-ağırlıklı ortalaması) + macro_score (0.20) → `final_score`.
- **Missing Data Davranışı** (mimarinin çekirdek ilkesi): eksik skorlar 0 varsayılmaz, mevcut skorların ağırlığı kendi aralarında normalize edilir; `confidence` de veri tamlık oranıyla çarpılarak düşürülür.
- Eşikler (`system_config/decision_thresholds`, varsayılan): AL≥40, ZAYIF AL≥15, ZAYIF SAT≤-15, SAT≤-40, arası TUT.
- Kayıt: `ai_decisions` koleksiyonuna **immutable** (yalnızca `add`, update/delete yok) yazılır; `technical_analysis_id`/`news_analysis_ids`/`macro_snapshot_id` ile izlenebilirlik sağlanır.
- Haber tek başına asla AL/SAT üretmez — her zaman teknik+makro ile birlikte ağırlıklandırılır (AŞAMA 69'da Foreks eklenirken bu ilke açıkça korundu).

## 8. AIExplanationEngine

Dosya: `backend/app/engines/explanation/engine.py`.

- **LLM kullanmaz** — kural tabanlı. Technical/Macro/News bileşen kırılımını en etkili faktörlere göre sıralayıp Türkçe cümlelere çevirir (`GET /decisions/{symbol}/explanation`, `persist=False` — yeni bir resmi karar kaydı oluşturmaz).
- `news_reasons`: en önemli (importance×confidence) haberleri gerekçeleriyle listeler.
- **Gerçek kullanılan ağırlıklar** (`technical_weight`/`news_weight`/`macro_weight` — missing-data normalizasyonundan SONRAKİ gerçek değerler, AŞAMA 71) de yanıta dahil edilir.
- **UI:** Bu çıktı artık yalnızca Dashboard'daki "Karar Gerekçesi" diyaloğunda değil, Asset Detail'in **Teknik sekmesine gömülü** "AL/SAT Kararının Dayandığı Veriler" kartında da gösteriliyor (`lib/widgets/explanation_content.dart` — paylaşılan widget, AŞAMA 71, kullanıcı isteği "nelere göre AL/SAT diyorsun bunu Teknik sayfasında göster").
- İlişkili ama ayrı motorlar: `engines/journal/outcome_evaluator.py` (Karar Günlüğü — geçmiş kararların 7/30 gün sonraki gerçek fiyat hareketiyle DOĞRU/YANLIŞ/BEKLEMEDE etiketlenmesi + `dominant_factor()`, LLM yok, sayısal), `engines/technical/narrative.py` (destek/direnç/breakout anlatısı), `engines/funds/explanation.py` (fon "neden bu fon" açıklaması, LLM yok).

## 9. Haber Kaynakları

Tüm kaynaklar `services/news/` altında, ortak `NewsProvider` arayüzüne (tekil-varlık sorgusu) uyar ya da (Foreks gibi) ayrı bir genel-liste yöntemiyle entegre olur:

1. **Yahoo Finance** (`yahoo_news_provider.py`) — `Ticker.news`, çoğunlukla İngilizce/uluslararası, BIST kapsamı zayıf.
2. **Google News RSS** (`google_news_rss_provider.py`) — `{sembol} hisse` (ve fonlar için `{kod} fon`, analistler için `{sembol} hedef fiyat OR tavsiye OR analist`) sorgusuyla arama; Türkçe finans medyasının (Bloomberght, Mynet, Foreks, Investing.com TR, Bigpara vb.) ana kaynağı. Kişisel/ticari-olmayan kullanım sınırına dikkat edilerek (tek kullanıcılı MVP) kabul edildi.
3. **Foreks Borsa Haberleri** (`foreks_news_provider.py`, AŞAMA 69) — `foreks.com`'un resmi `/rss` akışı (robots.txt'te izinli, `llms.txt`'te belgeli). `get_market_news()`: RSS çeker → bilinen BIST sembollerine değinen haberleri seçer (100 sembole karşı metin eşleşmesi, uydurma yok) → Jaccard benzerliğiyle (≥0.82) neredeyse-aynı haberleri eleyip token tasarrufu sağlar → dedup ile Firestore'a yazar (`foreks:{haber_id}`).
4. Ortak sınıflandırma: `source_reliability.py` (yayıncı → güvenilirlik kategorisi), `firm_extraction.py` (başlıkta geçen ~35 banka/aracı kurum adını deterministik tespit eder, uydurmaz), `merge.py` (analist-etiketli haberleri öncelikli birleştirir), `article_fetcher.py` (mümkünse gerçek makale gövdesini çeker), `news_aggregator.py` (tüm kaynakları birleştirip Firestore'a yazan ortak fonksiyon, hem `api/news.py` hem `services/jobs/daily_analysis.py` kullanır).
5. Haberler sekmesi maliyetsiz gösterim (`GET /news/{symbol}/analysis`) ile AI analizini (varsa) gösterir; "Analiz Et" butonu yeni OpenAI çağrısı tetikler.

## 10. BIST / Fon Veri Kaynakları

- **BIST fiyat/geçmiş/gün-içi veri:** `services/market_data/bist_provider.py` — Yahoo Finance (`yfinance`), semboller `SEMBOL.IS`. Güncel fiyat, geçmiş OHLCV, gün-içi (5dk) bar, otomatik retry (`_fetch_with_retry`, rate-limit için), gün-içi veri boşsa günlük bara fallback (422 hatası düzeltmesi).
- **Analist konsensüsü:** `services/analysts/yahoo_analyst_provider.py` — `Ticker.recommendations` (AL/TUT/SAT dağılımı, trend) + `Ticker.analyst_price_targets`. 6 saatlik TTL cache (`system_cache`).
- **Fonlar (TEFAS):** `services/funds/tefas_provider.py` — `pytefas` kütüphanesi ile TEFAS'ın Next.js tabanlı resmi JSON API'si (`tefas.gov.tr` ana sitesi bot korumalı, API ayrı ve açık). Tek istekte TÜM fonların anlık görüntüsü (~2000 fon) çekilir; yalnızca 5 referans tarih (son gün, -1a, -3a, -6a, -1y) kalıcı önbelleğe alınır (`fund_snapshots` — geçmiş fiyat asla değişmez, TTL yok). Fon portföy dağılımı (risk hesabı için) `get_breakdown_snapshot()` ile (`fund_breakdown_snapshots`).
- **Halka arzlar:** `services/ipo/halkarz_provider.py` — `halkarz.com` statik HTML'i (BeautifulSoup), liste + detay (fiyat/tarih/talep sonuçları). 6 saatlik TTL cache (`system_cache`).

## 11. OpenAI Entegrasyonu

- **Model:** `gpt-5.6-luna` (birincil, tüm normal haber analizleri), `gpt-5.6-terra` (fallback için tasarlanmış ama henüz gerçek çağrısı yok), model adları `.env`'den okunur, hard-code değil.
- **Kullanım amacı:** SADECE haber duygu/etki analizi (`EventIntelligenceEngine`). Projedeki HİÇBİR başka motor (technical, macro, decision, explanation, risk, backtest, funds, analysts, journal) LLM kullanmaz — hepsi deterministik/kural tabanlı, bilinçli bir tasarım tercihi (denetlenebilirlik, maliyet, halüsinasyon riskinden kaçınma).
- **Maliyet:** Bütçe $5 (varsayılan, `system_config`), `token_usage_logs`'a her çağrı loglanır, `GET /usage` ile mobil "API Kullanımı" ekranında gösterilir.
- **Güvenlik:** `OPENAI_API_KEY` yalnızca `.env`/Cloud Run Secret Manager'da, asla kod/commit'te değil.

## 12. Firestore Koleksiyonları

| Koleksiyon | İçerik | Not |
|---|---|---|
| `assets` | BIST100'ün tamamı (sembol, ad, market, tip) | doc ID = sembol |
| `market_data` | Geçmiş OHLCV kayıtları | append-only |
| `technical_analyses` | TechnicalAnalysisEngine çıktıları | immutable, append-only, 15dk cache |
| `macro_snapshots` | MacroAnalysisEngine çıktıları | append-only, "son kayıt okunur" deseni |
| `news_raw` | Ham haberler (Yahoo+Google+Foreks birleşik) | doc ID = external_id / `foreks:{id}`, upsert-dedup |
| `news_analyses` | EventIntelligenceEngine (OpenAI) çıktıları | immutable, news_id+asset ile sorgulanır |
| `ai_decisions` | DecisionEngine kararları | immutable, `technical_analysis_id`/`news_analysis_ids`/`macro_snapshot_id` ile izlenebilir |
| `token_usage_logs` | OpenAI token/maliyet kayıtları | immutable |
| `system_config` | Tüm ağırlıklar/eşikler/bütçe/bildirim ayarları | hard-code YOK, otomatik seed edilir |
| `system_cache` | 6 saatlik TTL cache'ler: benchmark (XU100 kapanış serisi), fon analiz sıralaması, analist konsensüsü, IPO liste/detay | doküman ID prefix'leriyle ayrışır |
| `portfolio_positions` | Kullanıcı hisse pozisyonları | mutable (kullanıcı verisi), ortalama maliyet birleştirme sunum katmanında |
| `portfolio_transactions` | Kapatılmış pozisyon işlemleri (gerçekleşen K/Z) | immutable |
| `fund_positions` | Kullanıcı fon pozisyonları | mutable |
| `fund_snapshots` | TEFAS referans tarih fiyat görüntüleri | kalıcı, TTL yok (geçmiş fiyat değişmez) |
| `fund_breakdown_snapshots` | Fon portföy dağılım (risk) verisi | kalıcı |
| `fund_investment_settings` | Kullanıcı aylık gelir/bütçe ayarı | doc ID = user_id |
| `fund_notification_log` | Fon bildirimi dedup kaydı (aylık/switch) | |
| `notification_log` | Hisse AL/SAT bildirimi dedup kaydı ("son bildirilen karar") | doc ID = `{user_id}_{asset}` |
| `notification_records` | Kullanıcıya GERÇEKTEN gönderilmiş her bildirimin kalıcı geçmişi | immutable, `notification_log`'dan farklı amaç |
| `fcm_tokens` | Kullanıcı başına FCM cihaz token'ı | doc ID = user_id |
| `intraday_bars` | Gün-içi bar biriktirme altyapısı | var ama otomatik doldurma YOK (elle tetiklenen script) |
| `strategy_lab_runs` | Strateji Laboratuvarı test geçmişi | kalıcı |
| `ipo_notes` | Kullanıcının halka arz notları | kullanıcı verisi, silinebilir |

`system_config`'teki bilinen doküman ID'leri: `technical_indicator_weights`, `macro_indicator_weights`, `decision_weights`, `decision_thresholds`, `source_reliability`, `notification_settings`, `EVENT_INTELLIGENCE_BUDGET_USD` vb.

## 13. Önemli Mimari Kararlar

- **Provider mimarisi:** Tüm dış veri kaynakları soyut arayüz arkasında (`MarketDataProvider`, `NewsProvider`, `MacroDataProvider`) — kaynak değişse motor kodu değişmez.
- **Immutability:** AI'ın ürettiği her kayıt (`ai_decisions`, `technical_analyses`, `news_analyses`, `token_usage_logs`, `notification_records`, `portfolio_transactions`) yalnızca `add()`, hiçbir update/delete metodu yok — denetlenebilirlik. Kullanıcı verisi (`portfolio_positions`, `fund_positions`, `ipo_notes`) ise mutable, kullanıcı kendi verisini düzenleyebilir/silebilir.
- **Missing Data Davranışı:** Eksik veri asla 0/nötr olarak varsayılmaz; ağırlıklar mevcut veriye göre normalize edilir, confidence veri tamlığıyla çarpılır. DecisionEngine, FundAnalysisEngine'de aynı ilke tekrarlanır.
- **LLM yalnız haber analizinde:** Maliyet, halüsinasyon riski ve denetlenebilirlik nedeniyle yalnızca `EventIntelligenceEngine` OpenAI kullanır; diğer tüm "neden" açıklamaları (teknik anlatı, fon açıklaması, karar günlüğü sebep analizi) kural tabanlı/sayısaldır.
- **Cache/TTL deseni (tekrarlanan bir mimari örüntü):** "Son kaydedilmiş sonucu oku, otomatik yeniden hesaplama yapma" — technical (15dk), macro (talep üzerine), fon sıralaması/analist konsensüsü/IPO (6 saat), benchmark XU100 serisi (15dk, paylaşımlı). Bu, hem maliyeti hem N+1 istek sorunlarını (100 sembollük Dashboard) önler.
- **N+1 istek çözümleri:** Dashboard 100 sembolü 10'luk gruplar hâlinde ister (Cloud Run bağlantı kopmalarını önlemek için); relative_strength paylaşımlı/cache'li XU100 serisiyle; multi_timeframe zaten çekilmiş günlük seriden haftalık türeterek; fon/IPO/analist verisi TTL cache ile.
- **Gerçek alım-satım YOK:** Ne hisse ne fon için otomatik emir API'si var — TEFAS'ta genel kullanıcıya açık işlem API'si yok, hisse tarafında da bilinçli olarak "yarı-otomatik" (AI önerir, kullanıcı onaylar, bildirim gönderilir) yaklaşım seçildi.
- **Scheduler minimalizmi:** Tek otomasyon günlük toplu analiz job'ı (AŞAMA 70); geri kalan her şey kullanıcı eylemiyle (Dashboard açma, buton basma) tetiklenir.
- **Sektör riski, gerçek geçmiş haber/makro arşivi:** Kasıtlı olarak eklenmedi — güvenilir/gerçek bir veri kaynağı bulununcaya kadar uydurma veri üretilmeyecek.

## 14. Çalışan Özellikler (Gerçekten Çalışıyor)

- BIST100'ün tamamı için: güncel fiyat, geçmiş grafik (1G/1H/1A/3A/6A/1Y), teknik analiz (gösterge kırılımı + Sinyal Özeti kartı [yatırım vadesi rozeti HATA 8C ile gizlendi, bkz. bölüm 6] + destek/direnç grafiği + "neden bu sinyal" anlatısı + gömülü "AL/SAT Kararının Dayandığı Veriler" kartı [gerçek ağırlıklar + teknik/haber/makro gerekçeleri, AŞAMA 71]), haberler (Yahoo+Google+Foreks birleşik, AL/TUT/SAT rozetli, AI duygu analizi opsiyonel), analist konsensüsü + hedef fiyat, karar günlüğü (7/30 gün başarı takibi), backtest + walk-forward + Strateji Laboratuvarı (5 ön ayar karşılaştırma) + test geçmişi.
- Dashboard: arama, final_score'a göre sıralama, final_score/AL-SAT/TUT etiketi.
- Portföy: ekle/düzenle/sat (kapatma+gerçekleşen K/Z)/geçmiş, AL butonuyla hızlı ekleme, otomatik ortalama maliyet birleştirme.
- Fonlar: TEFAS tabanlı sıralama, risk seviyesi, "neden bu fon", aylık bütçe dağıtım önerisi + anlık önizleme, "Ekstra Para Yatır" bildirimi, fon değiştirme önerisi bildirimi.
- Halka Arzlar: gerçek takvim/fiyat/talep verisi + kullanıcı notları.
- Bildirimler: FCM push (gerçek cihazda doğrulandı — `fid`→`token` hatası düzeltildikten sonra), test bildirimi butonu, bildirim geçmişi ekranı, portföy-sahipliğine göre kapsam daraltma, somut miktar önerili yarı-otomatik AL/SAT bildirimleri.
- Günlük otomatik analiz: her gün 08:00 (Europe/Istanbul) BIST100'ün tamamı otomatik işlenip karar üretiliyor ve bildirim gönderiliyor (Cloud Scheduler).
- Auth: Firebase e-posta/şifre girişi, backend ID token doğrulaması zorunlu.
- API Kullanımı ekranı, Gösterge Rehberi ekranı, Analistler Hub'ı ("kim ne demiş" — gerçek kurum adı tespitiyle), modern mavi gradyan tema (tüm ekranlar).
- Test kapsamı: 416 backend (pytest) + 49 Flutter (flutter_test) testi, hepsi yeşil (25.08.2026 itibarıyla).

## 15. Bilinen Eksikler ve Hatalar

- **Gerçek geçmiş haber/makro arşivi yok** — Strateji Laboratuvarı ve Karar Günlüğü'nde "o tarihte hangi haberler vardı" sorgulanamıyor; yalnızca teknik sinyal geriye dönük test edilebiliyor.
- **Sektör riski** hesaplanmıyor (RiskEngine'de) — güvenilir/ücretsiz bir sektör sınıflandırma kaynağı yok.
- **EventIntelligenceEngine Terra fallback'i** tasarlanmış ama gerçek ikinci LLM çağrısı yapılmıyor (`_should_escalate()` yalnızca hesaplanıyor, tetiklenmiyor).
- **intraday_bars** koleksiyonu/altyapısı var ama otomatik doldurma yok — VWAP/session_timing motorları pratikte veri birikmediği için gerçek anlamda kullanılamıyor.
- **relative_strength / multi_timeframe** yalnızca "Sinyal Özeti" zenginleştirmesinde kullanılıyor, TechnicalScore'un kendisine (skora) katkı yapmıyor.
- **Firestore Security Rules** yalnızca `portfolio_positions` için yazılmış ve şu an devrede değil (backend Admin SDK ile bypass ediyor) — yalnızca ileride doğrudan istemci-Firestore erişimi eklenirse anlamlı olacak.
- **E-posta doğrulama / şifre sıfırlama** akışı yok (MVP, tek kullanıcı için gerek görülmedi).
- Google News RSS kullanımı kişisel/ticari-olmayan kullanım sınırına giriyor — çok kullanıcılı/ticari bir gelecek senaryosunda gözden geçirilmeli.
- Uygulama hâlâ tek kullanıcı (kullanıcının kendi hesabı: ensarcckk@gmail.com) varsayımıyla test edilmiş; çoklu kullanıcı yükü altında Cloud Run/Firestore/OpenAI maliyet davranışı doğrulanmadı.
- Windows/macOS/Linux masaüstü Firebase platformları hiç eklenmedi (yalnızca android/ios/web).
- **Fiyat verisi gerçek zamanlı değil, ~20 dk gecikmeli** — 25.08.2026'da piyasa açıkken (10:29 TSİ) THYAO/GARAN/ASELS için Yahoo Finance'in son barı 10:10 TSİ ölçüldü (bkz. bölüm 18 madde 8, ölçüm komutu ve tarihi orada). Bu, Yahoo'nun teknik kusuru değil, BIST'in ücretsiz/lisanssız veri dağıtımı için koyduğu standart gecikme kuralı — kodda düzeltilemez. Ayrıca Asset Detail ekranındaki Fiyat sekmesi (`lib/features/asset_detail/asset_detail_screen.dart` `_PriceTab`) otomatik yenileme yapmıyor, yalnızca ekran ilk açıldığında veya manuel pull-to-refresh'te veri çekiyor.
- Proje `https://github.com/EnsarrCicek/ai_investment_app.git` (GitHub, `ensarcckk@gmail.com` hesabı) uzak deposuna bağlı — private repo (bkz. KURULUM_GUNLUGU.md bölüm 0.0).

## 16. Son Tamamlanan Geliştirmeler (AŞAMA 66-71, 21-25.08.2026)

- **AŞAMA 66:** Teknik sekmede destek/direnç grafiği (`CustomPainter`, backend'in `all_zones` alanı) + kural tabanlı "Grafik Neden Bunu Söylüyor?" anlatı kartı (`narrative.py`).
- **AŞAMA 67:** Halka Arzlar sayfası — `halkarz.com`'dan gerçek takvim/fiyat/talep verisi + kullanıcının kendi gözlem notları (kalıcı, AI yorumu yok).
- **AŞAMA 68:** Uygulama geneli modern mavi gradyan tema — `AppGradients`, `GradientAppBar` (15 ekranın tamamına uygulandı), Material 3 bileşen temaları, login ekranı tam gradyan.
- **AŞAMA 69:** Foreks Borsa Haberleri kaynağı (resmi RSS akışı, robots.txt uyumlu) + haber analizine `time_horizon` (kısa/orta/uzun vadeli etki) ve türetilmiş `sentiment_label` eklendi; çoklu-varlık haber analizi karışması hatası düzeltildi (aynı haberin farklı hisseler için farklı skor alması gerekirken aynı skoru paylaşması).
- **AŞAMA 70:** Google Cloud Scheduler ile günlük (08:00 Europe/Istanbul) otomatik toplu analiz job'ı — `POST /jobs/daily-analysis` (secret korumalı), BIST100'ün tamamını haber+teknik+makro ile analiz edip karar kaydeder ve bildirim gönderir; projenin ilk ve tek gerçek otomasyonu.
- **AŞAMA 71 (25.08.2026):** Kullanıcı isteği "AL/SAT derken nelere göre karar veriyorsun, hangi verilere dayanıyorsun — bunu Teknik sayfasında göster; ayrıca hangi hisse kısa/uzun vadeli" üzerine iki değişiklik: (1) `ExplanationEngine`'in çıktısına gerçek kullanılan ağırlıklar (`technical_weight`/`news_weight`/`macro_weight`) eklendi ve bu açıklama artık Teknik sekmesine gömülü yeni bir "AL/SAT Kararının Dayandığı Veriler" kartında gösteriliyor (paylaşılan `ExplanationContent` widget'ı, Dashboard'daki eski diyalogla aynı kod); Flutter `Explanation` modelindeki `news_reasons` eksikliği (backend gönderiyordu, UI hiç okumuyordu) da bu sırada düzeltildi. (2) Yeni, saf teknik yapıya dayanan kural tabanlı `horizon_classifier.py` — her hisse için KISA_VADELI/ORTA_VADELI/UZUN_VADELI/BELIRSIZ etiketi üretir, yalnızca Teknik sekmesindeki Sinyal Özeti kartında rozet olarak gösterilir (kullanıcı onayıyla kapsam: Dashboard/AIDecision şemasına dokunulmadı). Ayrıca bu görüşmede fiyat verisinin ~20 dk gecikmeli olduğu ölçüldü ve doğrulandı (bkz. bölüm 15/18 madde 8) — BIST'in ücretsiz veri dağıtımı için koyduğu standart kural, henüz çözülmedi.

## 17. Şu Anda Nerede Kalındığı

25.08.2026 itibarıyla AŞAMA 71 tamamlandı, tüm testler yeşil (416 backend + 49 Flutter), `flutter analyze` temiz. Cloud Run'a henüz DEPLOY EDİLMEDİ (bu oturumda yalnızca kod değişikliği yapıldı, dağıtım kullanıcının onayını bekliyor). Cloud Scheduler job'ı `ENABLED` ve canlıda çalışıyor (AŞAMA 70'ten beri değişmedi). Kullanıcının gerçek cihazındaki release APK hâlâ AŞAMA 70 sürümü — yeni Teknik sekmesi kartı/rozeti cihazda henüz görünmüyor, yeni bir build+deploy+APK güncellemesi gerekiyor.

## 18. Sıradaki Mantıklı İşler (Öneri)

`KURULUM_GUNLUGU.md` içinde açık, tek bir "sıradaki adım" listesi yok (her AŞAMA kullanıcı isteğiyle organik ilerlemiş) — ama dosya genelinde tekrar eden, bilinçli ertelenmiş konular şunlar (bölüm 15'teki eksiklerle örtüşüyor):

1. Gerçek bir geçmiş haber/makro arşivi kaynağı bulup Strateji Laboratuvarı'nı "o tarihteki haber/makro ortamıyla" test edilebilir hale getirmek (ücretli bir arşiv API'si araştırılabilir).
2. Sektör riski için güvenilir, gerçek bir sınıflandırma kaynağı bulmak.
3. EventIntelligenceEngine'in Terra fallback'ini gerçekten tetiklemek (yüksek importance/düşük confidence durumlarında ikinci LLM çağrısı).
4. Firestore Security Rules'ı diğer koleksiyonlara (yalnızca `portfolio_positions` değil) genişletmek — ileride doğrudan istemci erişimi düşünülürse.
5. Çoklu kullanıcı senaryosunda Cloud Run/Firestore/OpenAI maliyet ve performans davranışını test etmek (şu an tek kullanıcı doğrulanmış).
6. E-posta doğrulama / şifre sıfırlama akışlarını eklemek (çoklu kullanıcıya geçilirse gerekli olur).
7. Kullanıcının daha önce gündeme getirdiği ama ayrı oturuma ertelenen "tema bazlı hisse önerisi" (ör. gündemdeki sektöre göre öneri) fikri.
8. **Gerçek zamanlı (anlık) fiyat verisi** (25.08.2026'da kullanıcıyla konuşuldu, bkz. bölüm 15): Şu an Yahoo Finance ~20 dk gecikmeli (ölçüldü: piyasa açıkken THYAO/GARAN/ASELS'in son barı 20 dk eskiydi) — bu, BIST'in ücretsiz veri için koyduğu standart lisans kuralı, Yahoo'ya özgü değil. ForInvest araştırıldı (25.08.2026): geliştirici API'si YOK, yalnızca tüketici uygulaması + kurumsal lisanslı entegrasyon, ücretsiz katmanı da kişisel kullanım şartıyla sınırlı — sunucu tarafında kullanılamaz, elendi. Kullanıcının onayladığı iki yönlü çözüm yolu:
   - **(a) Kendi "anlık veri" altyapımızı kurmak** — ör. bir kaynağı (resmi/yarı-resmi, TOS'a uygun) kendimiz sürekli çekip/scrape edip Firestore'da güncel tutmak. Böyle bir kaynak henüz BULUNAMADI; araştırma gerekiyor (BIST'in kendi veri lisanslama sayfası, aracı kurumların herkese açık uç noktaları vb.).
   - **(b) Ücretli, lisanslı gerçek zamanlı veri API'sine abone olmak** (Foreks pro feed, Matriks, İş Yatırım API gibi) — maliyet kabul edilecek.
   Ayrıca ücretsiz/hızlı bir ara adım olarak Asset Detail Fiyat sekmesine otomatik periyodik yenileme (örn. 30-60 sn) eklenmesi konuşuldu ama henüz UYGULANMADI — Yahoo'nun kendi 20 dk'lık verisini en azından ekran açıkken taze tutar, gerçek gecikmeyi gidermez.

Yeni oturumda kullanıcıya doğrudan "sırada ne yapalım" diye sormak, bu listeyi zorla uygulamaktan daha doğru olur — proje tüm gelişimini kullanıcı talepleriyle organik olarak ilerletmiş.

## 19. Gerekli Önemli Dosya Yolları

**Backend kök:** `backend/app/`
- Giriş: `backend/app/main.py`
- Config/Auth: `backend/app/core/config.py`, `backend/app/core/firebase.py`, `backend/app/core/auth.py`
- Engine'ler: `backend/app/engines/technical/engine.py`, `backend/app/engines/macro/engine.py`, `backend/app/engines/decision/engine.py`, `backend/app/engines/explanation/engine.py`, `backend/app/engines/event_intelligence/engine.py` (+ `usage.py`), `backend/app/engines/risk/engine.py`, `backend/app/engines/backtest/engine.py` (+ `walk_forward.py`, `weight_walk_forward.py`, `strategy_presets.py`, `metrics.py`), `backend/app/engines/funds/analysis_engine.py` (+ `risk.py`, `explanation.py`), `backend/app/engines/analysts/consensus.py`, `backend/app/engines/journal/outcome_evaluator.py`
- Teknik alt modüller: `backend/app/engines/technical/{indicators,data_quality,market_structure,support_resistance,breakout,relative_volume,regime,relative_strength,multi_timeframe,signal_classifier,horizon_classifier,gap_analysis,candlestick_patterns,chart_patterns,vwap,session_timing,narrative}.py`
- Servisler: `backend/app/services/market_data/bist_provider.py`, `backend/app/services/news/{yahoo_news_provider,google_news_rss_provider,foreks_news_provider,merge,source_reliability,firm_extraction,article_fetcher,news_aggregator}.py`, `backend/app/services/funds/tefas_provider.py`, `backend/app/services/ipo/halkarz_provider.py`, `backend/app/services/analysts/yahoo_analyst_provider.py`, `backend/app/services/notifications/{fcm_sender,fund_notifier}.py`, `backend/app/services/jobs/daily_analysis.py`
- API route'lar: `backend/app/api/{assets,analysis,decisions,risk,portfolio,market_data,news,news_analysis,backtest,funds,ipo,analysts,notifications,usage,jobs}.py`
- Repositories: `backend/app/repositories/*.py` (koleksiyon listesi için bkz. bölüm 12)
- Testler: `backend/tests/` (pytest)
- Bağımlılıklar: `backend/requirements.txt`, ortam: `backend/.env` (izlenmiyor, elle oluşturulmalı), `backend/.env.example` (şablon)
- Deploy: `backend/Dockerfile`, `backend/.dockerignore`

**Flutter kök:** `lib/`
- Giriş: `lib/main.dart`
- Ekranlar: `lib/features/{dashboard,portfolio,funds,macro,settings,asset_detail,fund_detail,ipo,notifications,strategy_lab,usage,guide,analysts,auth}/*.dart`
- Modeller: `lib/models/*.dart`
- API istemcileri: `lib/services/api/*.dart` (özellikle `api_config.dart` — taban URL)
- Yardımcılar: `lib/utils/{decision_style,app_gradients,url_launch}.dart`, `lib/widgets/{gradient_app_bar,explanation_content}.dart`
- Bildirim: `lib/services/notification_service.dart`
- Firebase config: `lib/firebase_options.dart`, `android/app/google-services.json`
- Testler: `test/`

**Diğer:** `KURULUM_GUNLUGU.md` (tam geçmiş, 2153 satır), `TECHNICAL_ANALYSIS_RESEARCH1.md` (AŞAMA 48'in kaynağı olan araştırma dokümanı, proje kökünde), Firestore rules: `firestore.rules`.

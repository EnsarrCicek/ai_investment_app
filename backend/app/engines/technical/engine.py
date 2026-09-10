"""TechnicalAnalysisEngine — ana doküman bölüm 5.

Kapsam notu: RSI, MACD, EMA trend (kesişim), Bollinger Bands, Momentum, ROC
ve EMA eğimi (AŞAMA 48/9) göstergeleri TechnicalScore'a doğrudan katkı
sağlar; ATR volatilite normalizasyonu için, Volume/Volume SMA ise yön değil
"doğrulama" (confidence) amacıyla kullanılır. ADX, Stochastic RSI ve rejim
tabanlı DİNAMİK ağırlıklandırma bu sürümde YOKTUR.

AŞAMA 48/15 — zenginleştirme katmanı: market_structure/support_resistance/
breakout/relative_volume/regime/gap_analysis/candlestick_patterns/
signal_classifier modülleri artık her analyze_with_id() çağrısında
hesaplanıp TechnicalAnalysis'e EK, AYRI alanlar (market_structure,
signal_class, nearest_support/resistance, breakout, vb.) olarak ekleniyor —
final_score/components hesaplamasını HİÇ ETKİLEMEZ, yalnızca UI'da
gösterilecek açıklayıcı bağlam sağlar. Bilinçli olarak DAHİL EDİLMEYEN:
VWAP/session_timing (intraday bar biriktirme altyapısı henüz otomatik
çalışmıyor, bkz. scripts/fetch_intraday_bars.py).

AŞAMA 48/17 — relative_strength eklendi: XU100'e göre göreli güç, ilk
sürümde "ek yfinance isteği N+1 sorununu geri getirir" gerekçesiyle bilinçli
olarak dışarıda bırakılmıştı. Çözüm: XU100'ün kapanış serisi TÜM semboller
için ortak olduğundan, benchmark_service.get_benchmark_close_series() bunu
technical_analyses ile aynı TTL'li (15 dk), TEK bir Firestore belgesinde
önbellekliyor — Dashboard'un 100 sembolünün ilkinde bir kez çekilir, geri
kalan 99'u önbellekten okur (yeniden N+1 istek oluşturmaz). Benchmark
fetch'i başarısız olursa (ValueError) relative_strength_class sessizce
"UNKNOWN" kalır — bu, tüm sembolün analizini düşürecek kritik bir hata
DEĞİLDİR (Missing Data Davranışı).

AŞAMA 48/18 — multi_timeframe eklendi: haftalık zaman dilimi, relative_
strength'in aksine sembole özeldir (paylaşılamaz) ama ek bir yfinance
isteği de GEREKTİRMEZ — multi_timeframe.resample_to_weekly_close(), zaten
çekilmiş günlük Close serisini haftalık kapanışlara indirger (pandas
resample, saf hesaplama). Günlük ve haftalık EMA eğimi yönü uyuşuyorsa
mtf_aligned=True olur. Bu, signal_classifier.classify_signal()'ın
STRONG_BULLISH_INITIATION dalını GERÇEKTEN ulaşılabilir hale getiriyor —
önceden mtf_aligned hep sabit False varsayıldığından bu en üst sınıf hiçbir
sembol için hiç tetiklenemiyordu.

AŞAMA 48/9 — RSI/MACD/Bollinger ağırlığı düşürüldü: TECHNICAL_ANALYSIS_
RESEARCH1.md, bu göstergelerin bağımsız birincil sürücü değil "doğrulama"
amaçlı kullanılmasını öneriyor (ör. RSI>70 tek başına SAT değildir — rejime
göre değişir). Tam rejim-bağımlı dinamik ağırlıklandırma henüz kalibre
edilmediğinden (regime.py bilinçli olarak henüz buraya bağlanmadı), bunun
yerine STATİK bir yeniden ağırlıklandırma yapıldı: RSI/MACD/Bollinger payı
azaltıldı, trend-takip eden bileşenler (trend, ema_slope, momentum, roc)
payı artırıldı; yeni "ema_slope" bileşeni eklendi (mevcut "trend" bileşeni
yalnızca anlık EMA20-EMA50 farkını alıyordu, zaman içindeki EĞİMİ değil).
Eski/yeni ağırlıklandırma BacktestEngine ile karşılaştırılarak doğrulandı
(bkz. KURULUM_GUNLUGU.md).

Ağırlık toplamı artık 1.0'a EŞİT OLMAK ZORUNDA DEĞİL: final_score, ağırlık
toplamına bölünerek normalize edilir (DecisionEngine'deki "Missing Data
Davranışı" ile aynı desen). Bu, Firestore'da önceden kaydedilmiş eski (6
anahtarlı) bir "technical_indicator_weights" belgesinin, yeni eklenen
"ema_slope" anahtarını distorse etmeden güvenle birleşebilmesini sağlar.

Performans (AŞAMA 44): analyze_with_id() her çağrıldığında yfinance'e taze
bir istek atardı — Dashboard tüm BIST100'ü (100 sembol) her açılışta yeniden
hesaplıyordu, bu da ~60-80 saniyelik yükleme süresine yol açıyordu. Şimdi
macro/news ile aynı ilke uygulanıyor: TECHNICAL_CACHE_TTL_SECONDS'tan daha
taze bir TechnicalAnalysis zaten Firestore'da varsa, yfinance'e HİÇ
gidilmeden o kayıt döner. BIST günlük bar kullandığından (gün içi anlık
tick değil), birkaç dakikalık bir gecikme kararın doğruluğunu etkilemez.
"""

from datetime import datetime, timezone

import pandas as pd

from app.engines.technical import indicators as ind
from app.engines.technical.breakout import BreakoutEvent
from app.engines.technical.breakout_timeline import (
    build_breakout_timeline,
    select_live_breakout_event,
    select_live_breakout_event_by_direction,
    to_legacy_breakout_event,
)
from app.engines.technical.narrative import build_narrative
from app.engines.technical.candlestick_patterns import detect_patterns as detect_candlestick_patterns
from app.engines.technical.data_quality import check_data_quality, check_raw_ohlcv_integrity, check_trading_day_continuity
from app.engines.technical.gap_analysis import classify_gap, is_gap_filled, latest_gap
from app.engines.technical.horizon_classifier import HorizonInputs, classify_horizon, horizon_reason
from app.engines.technical.history_window import compute_history_window, resolve_expected_start
from app.engines.technical.scoring import (
    FAMILY_MEMBERSHIP,
    aggregate_available_scores,
    clamp_component,
    compute_evidence_coverage,
    compute_family_agreement,
    compute_scoring_config_hash,
    is_available,
    resolve_family_weights,
    resolve_indicator_weights,
    safe_ratio,
    technical_direction,
)
from app.engines.technical.market_structure import analyze_market_structure
from app.services.market_data.completed_bars import filter_completed_daily_bars
from app.engines.technical.multi_timeframe import (
    WEEKLY_DIRECTION_MIN_OBSERVATIONS,
    check_alignment,
    resample_to_weekly_close,
    timeframe_direction,
)
from app.engines.technical.regime import (
    atr_percentile,
    classify_trend_regime,
    classify_volatility_regime,
    efficiency_ratio,
)
from app.engines.technical.relative_strength import (
    classify_relative_strength,
    relative_strength_ratio,
    relative_strength_score,
)
from app.engines.technical.relative_volume import classify_relative_volume, relative_volume_series
from app.engines.technical.signal_classifier import SignalInputs, classify_signal
from app.engines.technical.support_resistance import SRZone, build_zones, is_display_role_invalid, nearest_zone
from app.models.technical_analysis import TechnicalAnalysis
from app.repositories.benchmark_cache_repository import BenchmarkCacheRepository
from app.repositories.system_config_repository import SystemConfigRepository
from app.repositories.technical_analysis_repository import TechnicalAnalysisRepository
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.benchmark_service import get_benchmark_close_series
from app.services.market_data.bist_provider import BistProvider
from app.services.market_data.trading_calendar import normalize_bist_daily_sessions, session_normalization_to_dict

# 25.08.2026: 1.0.0 -> 1.1.0 — RSI hesaplaması gerçek Wilder yöntemine
# (SMA seed + recursive smoothing, warm-up=NaN) düzeltildi; aynı sembol/tarih
# için üretilen technical_score artık eskisinden (yaklaşık-Wilder/EWM) farklı
# olabilir. Eski kayıtlar (Firestore'daki immutable technical_analyses) HİÇ
# değiştirilmedi/silinmedi — yalnızca bu tarihten SONRA üretilecek yeni
# kayıtlar "1.1.0" taşıyacak, denetim izi (audit trail) bozulmadı.
#
# 25.08.2026: 1.1.0 -> 1.2.0 — HATA 2A: günlük teknik analiz artık yalnızca
# TAMAMLANMIŞ günlük barları kullanıyor (piyasa açıkken "bugünün" hâlâ
# oluşmakta olan/partial barı çıkarılıyor, bkz. completed_bars.py); haftalık
# MTF karşılaştırması da devam eden (henüz Cuma'sı gelmemiş) haftayı artık
# kullanmıyor. Piyasa açıkken üretilen technical_score, eskisinden (bugünün
# canlı fiyatını içeren) FARKLI olabilir — genellikle bir önceki tamamlanmış
# günün skorüne eşittir. Eski kayıtlar değiştirilmedi/silinmedi.
#
# 25.08.2026: 1.2.0 -> 1.3.0 — HATA 2B: BIST'in resmi işlem takvimine göre
# beklenen ama seride bulunmayan bir işlem günü varsa (bkz. data_quality.py,
# check_trading_day_continuity — ör. 24.08.2026'da tüm BIST100'ü etkileyen
# Yahoo veri boşluğu) artık analiz HİÇ ÜRETİLMEZ (HARD VETO) — eskiden bu
# durum hiç tespit edilmiyor, boşluk sessizce göz ardı ediliyordu. Bazı
# semboller için (gerçek bir boşluk sürdüğü sürece) `GET /decisions/{symbol}`
# ve `GET /analysis/{symbol}/technical` artık 422 dönebilir. Eski kayıtlar
# değiştirilmedi/silinmedi.
#
# 25.08.2026: 1.3.0 -> 1.4.0 — HATA 2C: `analysis_start`'tan (df.index[0])
# ÖNCEYE uzanan bir "pre-roll" penceresi artık her istekte AYRICA çekiliyor
# — yalnızca sembolün analysis_start'tan ÖNCE zaten işlem gördüğünü
# KANITLAMAK için (bkz. history_window.py); pre-roll barları göstergelere
# ASLA girmez. Pre-roll'da kanıt yoksa analiz artık otomatik veto edilmiyor
# (yeni yürürlüğe giren yanlış varsayım riski önlendi) — bunun yerine
# `history_validation_status="LEADING_EDGE_UNVERIFIED"` ile işaretlenip
# sembolün gözlemlenen ilk barından itibaren normal continuity kontrolüne
# tabi tutuluyor. Bu, bazı sembollerde (özellikle pre-roll penceresinde
# Yahoo'nun hiç veri döndürmediği durumlarda) `expected_start`'ı eskisinden
# daha ileri bir tarihe kaydırabilir — technical_score hesaplamasının
# GİRDİSİ (kaç günlük veri kullanıldığı) bu sembollerde değişebilir. Eski
# kayıtlar değiştirilmedi/silinmedi.
#
# 26.08.2026: 1.4.0 -> 1.5.0 — HATA 3D: authoritative BIST takvimine göre
# "expected session" OLMAYAN (hafta sonu/planlı tatil/olağanüstü kapanış/
# iptal edilmiş seans) hiçbir tarihteki provider barı — OHLC/Volume
# içeriğine BAKILMADAN — artık normalize aşamasında ÖNCEDEN düşürülüyor
# (bkz. `trading_calendar.normalize_bist_daily_sessions()`). Önceden bu
# barlar ya HATA 3C'nin `UNEXPECTED_TRADING_SESSION` kontrolüne takılıp
# analizi TAMAMEN veto ediyordu (ör. 27-29 Mayıs 2026 Kurban Bayramı'nda
# Yahoo'nun bireysel hisselerde döndürdüğü phantom barlar YÜZÜNDEN BIST100'ün
# TAMAMI HARD_VETO alıyordu) ya da (normalize edilmeden önce) sessizce
# göstergelere sızabiliyordu. Artık analiz, bu tarihler HİÇ VARMIŞ GİBİ,
# yalnızca gerçek completed session'lar üzerinden üretiliyor — bazı
# sembollerde bu, önceden HARD_VETO edilen bir analizin artık BAŞARIYLA
# üretilmesi VEYA technical_score'un girdisinin (kaç/hangi bar kullanıldığı)
# değişmesi anlamına gelebilir. Düşürülen her tarihin provenance'ı
# (`session_normalization_policy`/`normalized_dropped_sessions`) yeni,
# backward-compatible alanlarla sonuca şeffaf şekilde eklendi. Eski kayıtlar
# değiştirilmedi/silinmedi.
#
# 27.08.2026: 1.5.0 -> 1.6.0 — HATA 4B: `breakout` artık her çağrıda "bugün"e
# yeniden ankorlanan tek-anlık bir `detect_breakout()` kontrolü DEĞİL,
# stateless bir zaman çizelgesinden (`breakout_timeline.build_breakout_
# timeline()`) seçilen, `event_at`'ından itibaren en fazla 15 tamamlanmış
# seans boyunca "yaşayan" bir event'tir (bkz. breakout_timeline.py modül
# docstring'i). Kanıtlanan kök neden: eski çağrı deseni `confirm_breakout()`
# için gereken gelecek barları hiçbir zaman "bugün"ün ötesinde bulamadığından
# `breakout.confirmed` DAİMA `None` kalıyor, dolayısıyla `STRONG_BULLISH_
# INITIATION`/`notify_if_new_opportunity()` production'da asla erişilemiyordu
# (look-ahead LEAK değil, event lifecycle/state persistence eksikliği). Yeni
# alan: `breakout_event_id` (bildirim dedupe'u için, bkz. fcm_sender.py).
# `technical_score`/`components`/DecisionEngine hiç etkilenmedi (breakout
# hiçbir zaman skora girmiyordu, bkz. HATA 4A audit'i). Eski kayıtlar
# değiştirilmedi/silinmedi.
#
# 27.08.2026: 1.6.0 -> 1.7.0 — HATA 5B2D: `technical_score` artık FLAT
# 7-component ağırlıklı ortalama DEĞİL, İKİ SEVİYELİ (component -> family ->
# technical_score) bir aggregation'dır (bkz. `scoring.FAMILY_MEMBERSHIP`).
# Kök gerekçe (HATA 5B2/5B2A/5B2B audit'leri, 92 sembol × 2 yıl gerçek
# veriyle): 7 nominal component istatistiksel olarak yalnızca ~2 efektif
# bağımsız boyut taşıyor (PCA), momentum/ROC yönü matematiksel bir özdeşlik
# (`sign` ikisinde de AYNI `Close[T]-Close[T-10]` payından geliyor) —
# flat ağırlıklı ortalama bu redundancy'i SESSİZCE tekrar tekrar sayıyordu.
# Yeni contract: `trend`/`oscillator_position`/`momentum_rate` (3 family,
# versioned kod sabiti — Firestore'da kullanıcı-tunable DEĞİL), her family
# İÇİNDE mevcut `technical_indicator_weights`'in relative oranlarıyla
# (DEĞİŞMEDİ), family'ler ARASINDA ise `technical_family_weights`'ten
# (varsayılan: eşit 1/3 — "bilimsel olarak optimal" İDDİA EDİLMİYOR, minimal
# parametreli nötr bir prior) ağırlıklandırılır. HATA 5B1'in TÜM missing-data
# contract'ı (finite-0 available, None/NaN/±inf unavailable, kalan ağırlıklar
# renormalize, tümü unavailable ise `None`) HER İKİ SEVİYEDE de RECURSIVE
# olarak (aynı `scoring.py` fonksiyonları yeniden kullanılarak) korunur.
# Component ham formülleri (RSI/MACD/trend/EMA slope/Bollinger/Momentum/ROC)
# ve skala katsayıları (25/1000/15/100/20/8) HİÇ DEĞİŞMEDİ; threshold'lar
# (±15/±40) BİLİNÇLİ OLARAK korundu (conservative migration policy, bilimsel
# kalibrasyon İDDİASI YOK — bkz. TEKNIK_ANALIZ_METODOLOJISI.md). MACD'nin
# family içinde göreli payının artması (~2%→~8%, bkz. audit) BİLİNEN, bu
# ticket'ta BİLİNÇLİ OLARAK dokunulmayan bir side-effect'tir (MACD'nin kendi
# amplitude/scaling sorunu AYRI bir ticket). Eski (1.6.0 ve öncesi) kayıtlar
# DEĞİŞTİRİLMEDİ/SİLİNMEDİ — migration YOK; 15 dakikalık cache artık yalnızca
# `engine_version == ENGINE_VERSION` olan kayıtları geçerli sayar (aşağıda,
# `analyze_with_id`).
#
# HATA 5C3A (28.08.2026): 1.7.0 -> 1.8.0 -- technical_score'un FORMULU
# (component/family aggregation, scoring_config_hash'in kapsadigi her sey)
# DEGISMEDI; yalnizca confidence'in semantics'i degisti (eski component
# sign-count + volume heuristic -> yeni "Sinyal Mutabakati" = weighted family
# directional agreement, bkz. scoring.py::compute_family_agreement) ve yeni
# evidence_coverage ("Veri Kapsami") alani eklendi. scoring_config_hash
# BILINCLI OLARAK DEGISMEDI (score'u etkileyen hicbir sey degismedi) --
# "ayni scoring hash + yeni engine_version" kombinasyonu KABUL EDILEBILIR
# (bkz. HATA 5C2A). Eski 1.7.0 kayitlari AYNEN kalir (migration YOK); cache
# bu bump nedeniyle onlari otomatik MISS eder.
#
# HATA 7C-FIX (01.09.2026): 1.8.0 -> 1.9.0 -- technical_score'un FORMULU
# (component/family aggregation, scoring_config_hash'in kapsadigi her sey)
# YINE DEGISMEDI; degisen `multi_timeframe.py::check_alignment()`'in eksik
# (UNKNOWN) bir zaman dilimini artik "diger zaman dilimiyle uyumlu" SAYMAMASI
# -- bu, persist edilen/kullaniciya gosterilen enrichment alanlarini
# (`signal_class`, `investment_horizon`, `investment_horizon_reason`,
# `mtf_aligned`, `mtf_consensus`) GERIYE-GORUNUR sekilde degistirebilir (ör.
# eskiden dejenere tek-zaman-dilimli "uyum" ile STRONG_BULLISH_INITIATION/
# UZUN_VADELI uretebilen bir kayit, artik uretemeyebilir). scoring_config_hash
# BILINCLI OLARAK DEGISMEDI (indicator/family weights'e dokunulmadi) -- "ayni
# scoring hash + yeni engine_version" kombinasyonu yine KABUL EDILEBILIR (bkz.
# HATA 5C2A emsali). Eski 1.8.0 kayitlari AYNEN kalir (migration YOK); cache
# bu bump nedeniyle onlari otomatik MISS eder.
#
# HATA 9A-FIX (02.09.2026): 1.9.0 -> 1.10.0 -- technical_score'un FORMULU
# YINE DEGISMEDI; degisen `signal_classifier.py::classify_signal()`'in
# bullish `breakout_confirmed`/`breakout_not_broken` kontrollerinin artik
# secili kirilim olayinin `direction=="BULLISH"` olmasini da ZORUNLU KILMASI
# (HATA 9/9A audit'leri: `select_live_breakout_event()` en son olayi yonden
# BAGIMSIZ sectigi icin, confirmed+retest-held bir BEARISH cokusun bullish
# dallari -- STRONG_BULLISH_INITIATION/BULLISH_CONFIRMED -- YANLISLIKLA
# tetikleyebildigi gercek production-exact tarihsel veride 15/7833 barda
# KANITLANDI). `breakout is None` semantigi KASITLI OLARAK DEGISMEDI ("hic
# kirilim yok" ile "BEARISH bir olay var ama bullish onay saglamiyor" hala
# AYRI durumlar). Bu, persist edilen/kullaniciya gosterilen enrichment
# alanlarini (`signal_class`, dolayisiyla `investment_horizon`/
# `investment_horizon_reason` ve new-opportunity bildirim uygunlugu) GERIYE-
# GORUNUR sekilde degistirebilir. `select_live_breakout_event()`,
# market_structure, MTF, relative_volume, technical_score HIC DEGISMEDI.
# scoring_config_hash BILINCLI OLARAK DEGISMEDI (ayni HATA 5C2A/7C-FIX emsali).
# Eski 1.9.0 kayitlari AYNEN kalir (migration YOK); cache bu bump nedeniyle
# onlari otomatik MISS eder.
#
# HATA 9B-FIX (02.09.2026): 1.10.0 -> 1.11.0 -- technical_score'un FORMULU
# YINE DEGISMEDI; degisen `classify_signal()`'in artik GENEL en son canli
# breakout olayi (`select_live_breakout_event()`, yon-bagimsiz -- `breakout`/
# `breakout_event_id` alanlari icin HALA ayni GENEL anlami tasir) yerine AYRI,
# yon-ozel bir secimden (`select_live_breakout_event_by_direction(...,
# "BULLISH")`) beslenmesi (HATA 9B audit'i: karsit yonlu daha yeni bir
# BEARISH olay, halen canli/gecerli bir BULLISH teyidini TAMAMEN
# GOLGELEYEBILIYORDU -- gercek production-exact tarihsel veride 13/7833
# barda kaybedilen BULLISH_CONFIRMED teyidi KANITLANDI). Yeni persist edilen
# alan: `signal_breakout_event_id` (breakout kaniti signal_class'a GERCEKTEN
# katkida bulundugunda set edilir, yalnizca bir olay VAR diye DEGIL) --
# `notify_if_new_opportunity()` artik dedupe icin BUNU kullanir, GENEL
# `breakout_event_id`'yi DEGIL (aksi halde provenance yanlis event'e
# baglanabilirdi, bkz. HATA 9B2 audit'i). scoring_config_hash BILINCLI
# OLARAK DEGISMEDI (ayni HATA 5C2A/7C-FIX/9A-FIX emsali). Eski 1.10.0
# kayitlari AYNEN kalir (migration YOK, `signal_breakout_event_id` bu
# kayitlarda yoktur -- `None` bunu geriye donuk uyumlu sekilde ifade eder);
# cache bu bump nedeniyle onlari otomatik MISS eder.
#
# HATA 10D (03.09.2026): 1.11.0 -> 1.12.0 -- technical_score'un FORMULU
# YINE DEGISMEDI; degisen `multi_timeframe.timeframe_direction()`'in artik
# haftalik cagri icin acik bir `min_observations=WEEKLY_DIRECTION_MIN_
# OBSERVATIONS` (25 TAMAMLANMIS haftalik kapanis) sozlesmesi tasimasi --
# eskiden yalnizca 6 gozlemden sonra MATEMATIKSEL olarak hesaplanabilir olan
# haftalik EMA egimi (istatistiksel olgunluktan BAGIMSIZ), etkilenen gercek
# popülasyon ->  `>= MIN_HISTORY_DAYS(60)` GECER (motor calisir, `<60` zaten
# `check_data_quality()` tarafindan HARD VETO edilir -- BU DEGISMEDI) AMA
# HALA `< WEEKLY_DIRECTION_MIN_OBSERVATIONS(25)` tamamlanmis haftaya sahip
# kisa-gecmisli bir sembol -- ~12 tamamlanmis haftada bile UP/DOWN/FLAT
# donduruyordu -- gercek tarihsel veride bunun %0.6-2.5 ters-yon (UP<->DOWN)
# uyusmazligina yol actigi KANITLANDI (HATA 10/10A/10B/10C audit'leri).
# 25, KILITLI,
# formul-turevli (EMA window=20 + slope_lookback=5) bir UYGUNLUK
# esigidir -- "gercek EMA olgunlugu" veya "tam-gecmis EMA ile yakinsama
# garantisi" IDDIA ETMEZ (26 KASITLI OLARAK reddedildi, bkz. multi_
# timeframe.py yorumu). GUNLUK cagri (`timeframe_direction(close)`,
# parametresiz) HIC DEGISMEDI -- yalnizca haftalik cagri etkilenir. Bu,
# kisa-gecmisli semboller icin `mtf_aligned`/`mtf_consensus` (dolayisiyla
# `signal_class`, `investment_horizon`, `investment_horizon_reason`, ve
# STRONG_BULLISH_INITIATION'a bagli new-opportunity bildirim uygunlugu)
# alanlarini GERIYE-GORUNUR sekilde degistirebilir -- kurulu (>=25 hafta)
# semboller icin OLCULEN ETKI SIFIRDIR (HATA 10C, PROD_EXACT hicbir
# ornekte 26'nin altina inmedi). Cuma-tatil tamamlanma gecikmesi ve
# 6-aylik rolling-window EMA yeniden-baslatma bulgulari BU TURDA
# DOKUNULMADI (ayri, acik bulgular olarak kalir). scoring_config_hash
# BILINCLI OLARAK DEGISMEDI (ayni HATA 5C2A/7C-FIX/9A-FIX/9B-FIX emsali).
# Eski 1.11.0 kayitlari AYNEN kalir (migration YOK); cache bu bump
# nedeniyle onlari otomatik MISS eder.
#
# HATA 10E (03.09.2026): 1.12.0 -> 1.13.0 -- `multi_timeframe._is_last_week_
# complete()` artik "hafta = Cuma biter" varsayimi yerine authoritative BIST
# takviminin o haftanin SON BEKLENEN islem gunu olarak dondurdugu tarihi
# kullanir (`trading_calendar.last_expected_trading_session_of_week()`) --
# Cuma resmi tatil oldugu haftalarda (ör. bayram) hafta artik Persembe'de
# (hatta cok gunlu kapanislarda daha erken) tamamlanmis sayilir, eskiden
# olduğu gibi bir sonraki ISO haftaya kadar YANLISLIKLA "tamamlanmamis"
# GORUNMEZ. Bu, `mtf_aligned`/`mtf_consensus`/`signal_class`/`investment_
# horizon` alanlarini yalnizca tatille kisalmis haftalara denk gelen
# kayitlarda GERIYE-GORUNUR sekilde degistirebilir (bkz. HATA 10E audit'i).
# W25 (`WEEKLY_DIRECTION_MIN_OBSERVATIONS`) sozlesmesi DEGISMEDI. GUNLUK
# cagri, W25 esigi, ±0.5 deadband HIC DEGISMEDI. scoring_config_hash
# BILINCLI OLARAK DEGISMEDI. Eski 1.12.0 kayitlari AYNEN kalir (migration
# YOK); cache bu bump nedeniyle onlari otomatik MISS eder.
#
# HATA 11J (07.09.2026): 1.13.0 -> 1.14.0 -- nearest_support/nearest_
# resistance artik SADECE mevcut fiyatin dogru tarafinda kalan ("aktif")
# zone'lar arasindan seciliyor (nearest_zone(..., active_only=True),
# support_resistance.is_display_role_invalid()) -- HATA 11D-11I audit
# serisinin kanitladigi "mevcut fiyatin kendi yapisal rolüyle uyumsuz
# tarafinda kalan bir zone hala 'en yakin destek/direnc' olarak
# gosterilebiliyor" bulgusunun minimum, tarihsel-lineage GEREKTIRMEYEN
# (salt bugünün kapanışına göre anlık geometri) duzeltmesi. Gecerli aday yoksa None doner (sahte zone
# UYDURULMAZ). Yapisal `zones`/`all_zones` DEGISMEDI -- gecersiz zone'lar
# hala orada, yalnizca her serialized zone'a `display_role_invalid: bool`
# eklendi (breakout.zone HARIC -- o, breakout_timeline'in DONDURULMUS
# tarihsel snapshot'u, bkz. _zone_to_dict()/_breakout_to_dict() yorumlari).
# Technical Score/components, signal_classifier, horizon_classifier,
# breakout_timeline, scoring_config_hash HIC DEGISMEDI. Eski 1.13.0
# kayitlari AYNEN kalir (migration YOK); cache bu bump nedeniyle onlari
# otomatik MISS eder.
ENGINE_VERSION = "1.14.0"

# HATA 5B2D FINAL COMMIT GATE (27.08.2026): bu sabit ARTIK production'da bir
# "missing config fallback" DEĞİLDİR -- `technical_indicator_weights`
# Firestore dokümanı HATA 5B2C ile bilinçli olarak 7/7 explicit/complete hale
# getirilmiş, 1.7.0 family mimarisi için REQUIRED bir config/methodology
# source-of-truth'tur (gerçek production değerleri bu sabitten DEĞERCE
# FARKLIDIR -- bkz. TEKNIK_ANALIZ_METODOLOJISI.md). Doküman eksikse/kısmi ise
# `resolve_indicator_weights()` FAIL-FAST olur, bu sabite SESSİZCE düşülmez.
# `DEFAULT_WEIGHTS`'in kalan kullanım alanı: testlerde/scratch araçlarda
# (ör. dormant `weight_walk_forward.py`, backtest strateji karşılaştırmaları)
# "geçerli, tam 7-key bir referans config" olarak.
DEFAULT_WEIGHTS = {
    "rsi": 0.10,
    "macd": 0.10,
    "trend": 0.15,
    "ema_slope": 0.20,
    "bollinger": 0.10,
    "momentum": 0.15,
    "roc": 0.20,
}

MIN_HISTORY_DAYS = 60
TECHNICAL_CACHE_TTL_SECONDS = 900  # 15 dakika


# Grafikte çizilecek destek/direnç bölgesi sayısı — kullanıcı isteği: "grafikte
# nasıl dirençler var, nasıl çizgiler çiziyorsun" — tüm zone'ları değil,
# güncel fiyata en yakın olanları göstermek grafiği okunaklı tutar.
MAX_CHART_ZONES = 8


def _zone_to_dict(zone: SRZone | None, price: float | None = None) -> dict | None:
    """HATA 11J: `price` verilirse (yalnız DISPLAY zone'ları -- nearest_
    support/resistance/all_zones -- için, aşağıda çağrılan yerlerde) sözlüğe
    `display_role_invalid` eklenir. `price=None` (varsayılan) bu alanı hiç
    EKLEMEZ -- bu, `_breakout_to_dict()`'in kullandığı `event.zone_snapshot`
    (breakout_timeline.py'nin DONDURULMUŞ, T-1 nedensel geçmiş zone'u) için
    KASITLI: o, mevcut fiyata göre "geçerli/geçersiz" bir DISPLAY zone'u
    DEĞİLDİR, ayrı bir nedensel mimarinin tarihsel anlık görüntüsüdür (bkz.
    HATA 11H/11I audit'leri) -- ona bugünün fiyatına dayalı bir alan
    ENJEKTE ETMEK yanlış bir semantik iddia olurdu.
    """
    if zone is None:
        return None
    zone_dict = {
        "type": zone.type,
        "low": round(zone.low, 4),
        "high": round(zone.high, 4),
        "touch_count": zone.touch_count,
    }
    if price is not None:
        zone_dict["display_role_invalid"] = is_display_role_invalid(zone, price)
    return zone_dict


def _breakout_to_dict(event: BreakoutEvent | None) -> dict | None:
    if event is None:
        return None
    return {
        "direction": event.direction,
        "breakout_atr": event.breakout_atr,
        "confirmed": event.confirmed,
        "retest_held": event.retest_held,
        "zone": _zone_to_dict(event.zone),
    }


def _compute_enrichment(
    df: pd.DataFrame,
    symbol: str,
    atr_val: float,
    close_val: float,
    final_score: float | None,
    provider: MarketDataProvider | None = None,
    benchmark_cache_repo: BenchmarkCacheRepository | None = None,
    now: datetime | None = None,
    benchmark_close_series: pd.Series | None = None,
) -> dict:
    """market_structure/S-R/breakout/hacim/rejim/gap/mum/göreli güç/sinyal
    sınıfı katmanı — relative_strength dışındaki her şey, `analyze_with_id`'nin
    zaten çekmiş olduğu AYNI df üzerinden hesaplanır (ek bir yfinance isteği
    YOK). relative_strength ise önbelleklenmiş, paylaşılan bir XU100 serisi
    kullanır (bkz. modül docstring'i, AŞAMA 48/17).

    HATA 4B (27.08.2026): breakout artık `detect_breakout()`'un HER GÜN
    "bugün"e yeniden ankorladığı tek-anlık bir kontrol DEĞİL, stateless bir
    `build_breakout_timeline()` zaman çizelgesinden `select_live_breakout_event()`
    ile seçilen TEK event'tir — bu event, `event_at`'ından itibaren en fazla
    `MAX_EVENT_AGE_SESSIONS` boyunca (confirmation/retest lifecycle'ı boyunca)
    "bugün"ün breakout'u olarak yaşamaya devam eder (bkz. breakout_timeline.py
    modül docstring'i). Support/Resistance DISPLAY zone'ları (aşağıdaki
    `zones`/`support`/`resistance`/`chart_zones`) bundan ETKİLENMEZ — onlar
    hâlâ "bugün itibarıyla bilinen her şeyi" (ATR[T] dahil) kullanan bir anlık
    görüntüdür; yalnız BREAKOUT TESPİTİ kendi ayrı, T-1 ile sınırlı nedensel
    zone/ATR sözleşmesini kullanır.

    HATA 11J (07.09.2026): `support`/`resistance` (dolayısıyla `nearest_
    support`/`nearest_resistance`) artık YALNIZ mevcut fiyatın (bugünün
    tamamlanmış kapanışı) DOĞRU tarafında kalan zone'lar arasından seçilir
    (`nearest_zone(..., active_only=True)`, bkz. support_resistance.py) --
    mevcut fiyatın, zone'un yapısal rolüyle (kendi low/high sınırıyla)
    uyumsuz tarafında kalan bir zone bir daha ASLA "en yakın destek/direnç"
    olarak dönmez (geçerli aday yoksa `None` döner, sahte bir zone
    UYDURULMAZ) -- bu, tarihsel bir kırılım/breakout OLAYI TESPİTİ DEĞİLDİR,
    salt bugünün kapanışına göre anlık geometri kontrolüdür. Yapısal
    `zones`/`all_zones` listesi
    DEĞİŞMEDİ -- geçersiz zone'lar hâlâ grafik bağlamı için ORADA, yalnız
    her birine mevcut-fiyata göre `display_role_invalid` bilgisi eklendi
    (`_zone_to_dict(..., price=...)`). Bu tarihsel breakout lineage/Jaccard
    DEĞİLDİR (bilinçli olarak kapsam dışı bırakıldı, bkz. HATA 11D-11I audit
    serisi) -- salt mevcut geometri.

    HATA 12M (10.09.2026): `benchmark_close_series` verilirse (yalnızca
    prospective evidence-capture yolu, bkz. `compute_technical_analysis()`),
    `get_benchmark_close_series()` HİÇ ÇAĞRILMAZ -- ne `provider` ne
    `benchmark_cache_repo` dokunulur (ikisi de bu durumda kullanılmadan
    kalabilir). Bu, evidence yolunun HANGİ benchmark verisinin tüketildiğini
    ÇAĞIRANIN ZATEN MATERYALİZE ETTİĞİ, dış bir kaynaktan (önbellek dahil)
    tekrar OKUNAMAYACAK şekilde garanti eder (bkz. HATA 12J/12K audit'leri,
    benchmark cache kimlik riski). `None` (varsayılan) mevcut/production
    davranışını AYNEN korur.
    """
    close, volume = df["Close"], df["Volume"]

    structure_result = analyze_market_structure(df)
    zones = build_zones(structure_result["swing_points"], atr=atr_val)
    # HATA 11J: `active_only=True` -- nearest_support/resistance artık YALNIZ
    # mevcut fiyatın DOĞRU tarafında kalan (is_display_role_invalid()==False)
    # zone'lar arasından seçilir; geçersiz bir zone'a asla DÜŞMEZ (yoksa None
    # döner, bkz. HATA 11I audit'i). Yapısal `zones` listesinin KENDİSİ
    # (aşağıdaki `chart_zones`/`all_zones`) DEĞİŞMEDEN, geçersiz zone'lar da
    # DAHİL kalır -- yalnız "en yakın" SEÇİMİ bu kısıtı alır.
    support = nearest_zone(zones, price=close_val, zone_type="SUPPORT", active_only=True)
    resistance = nearest_zone(zones, price=close_val, zone_type="RESISTANCE", active_only=True)

    timeline = build_breakout_timeline(df, symbol)
    live_event = select_live_breakout_event(timeline, today_index=len(df) - 1)
    breakout_event: BreakoutEvent | None = to_legacy_breakout_event(live_event)
    breakout_event_id = live_event.event_id if live_event is not None else None

    # HATA 9B-FIX (02.09.2026): `live_event` (yukarıda) yön ne olursa olsun
    # "en son canlı" event'tir -- `breakout`/`breakout_event_id` alanları için
    # GENEL anlamı HİÇ DEĞİŞMEDEN korunur. `classify_signal()`'in bullish onay
    # dalları ise artık AYRI, yön-özel bir seçimden beslenir -- karşıt yönlü
    # (BEARISH) daha yeni bir event, hâlâ canlı/geçerli bir bullish teyidini
    # ARTIK GÖLGELEYEMEZ (bkz. HATA 9B audit'i, breakout_timeline.py::
    # select_live_breakout_event_by_direction() docstring'i).
    bullish_live_event = select_live_breakout_event_by_direction(timeline, today_index=len(df) - 1, direction="BULLISH")
    bullish_breakout_event: BreakoutEvent | None = to_legacy_breakout_event(bullish_live_event)

    # HATA 9B-FIX PRE-COMMIT BLOCKER (02.09.2026): `bullish_breakout_event`
    # (yukarıda) BULLISH bir canlı olay yoksa `None` olur -- bunu DOĞRUDAN
    # `SignalInputs.breakout_event`e verseydik, "canlı bir BEARISH olay var"
    # durumu "hiç breakout kanıtı yok" (`breakout=None`) durumuna
    # İNDİRGENİRDİ; bu da HATA 9A'nın `breakout is None OR breakout_confirmed`
    # dalındaki `None` yolunu YANLIŞLIKLA açıp, salt BEARISH bir olayın (yön
    # kontrolüne hiç uğramadan) `BULLISH_CONFIRMED` üretmesine yol açardı --
    # HATA 9A'nın "BEARISH bir olay bullish teyit SAYILAMAZ" invariant'ının
    # DOLAYLI bir ihlali (kanıtlandı: pre-commit regresyon testi). Düzeltme:
    # canlı BULLISH olay yoksa GENEL `breakout_event`e (olduğu gibi, yönü
    # DEĞİŞTİRİLMEDEN) düş -- bu, `classify_signal()`'in KENDİ (HATA 9A'da
    # eklenen) `direction=="BULLISH"` kontrolünün BEARISH olayı doğru şekilde
    # reddetmesine izin verir, ama `breakout is None` dalını YANLIŞLIKLA
    # tetiklemez. Yalnız iki yönde de canlı olay yoksa (`breakout_event` de
    # `None`) gerçek `breakout=None` semantiği (mevcut, değişmeyen politika)
    # korunur.
    classifier_breakout_event: BreakoutEvent | None = (
        bullish_breakout_event if bullish_breakout_event is not None else breakout_event
    )

    rv_series = relative_volume_series(volume)
    rv_ratio = rv_series.iloc[-1]
    rv_class = classify_relative_volume(rv_ratio)

    vol_percentile = atr_percentile(ind.atr(df)).iloc[-1]
    vol_regime = classify_volatility_regime(vol_percentile)
    er = efficiency_ratio(close).iloc[-1]
    trend_regime_val = classify_trend_regime(er)

    gap = latest_gap(df, atr=atr_val)
    filled = is_gap_filled(df)
    gap_class = classify_gap(gap, filled)

    candlestick = detect_candlestick_patterns(df)

    try:
        benchmark_close = (
            benchmark_close_series
            if benchmark_close_series is not None
            else get_benchmark_close_series(provider=provider, cache_repo=benchmark_cache_repo)
        )
        asset_close_by_date = close.copy()
        asset_close_by_date.index = [ts.date() for ts in asset_close_by_date.index]
        rs_score = relative_strength_score(relative_strength_ratio(asset_close_by_date, benchmark_close))
    except ValueError:
        rs_score = None  # XU100 verisi geçici olarak alınamadı — sembolün asıl analizini düşürmez
    rs_class = classify_relative_strength(rs_score)

    daily_direction = timeframe_direction(close)
    weekly_close = resample_to_weekly_close(close, now=now)
    # HATA 10D (03.09.2026): gunluk cagri (yukarida) HICBIR degisiklik
    # almadi -- MIN_HISTORY_DAYS=60 zaten gunluk seriyi guvenceye alir.
    # Haftalik cagri ise artik en az WEEKLY_DIRECTION_MIN_OBSERVATIONS
    # (25) TAMAMLANMIS haftalik kapanis ister -- daha azi UNKNOWN doner
    # (bkz. multi_timeframe.py yorumu, HATA 10/10A/10B/10C audit'leri).
    weekly_direction = timeframe_direction(weekly_close, min_observations=WEEKLY_DIRECTION_MIN_OBSERVATIONS)
    alignment = check_alignment({"1d": daily_direction, "1wk": weekly_direction})

    # HATA 5B1 (27.08.2026): `technical_score` unavailable (`None`) olduğunda
    # `classify_signal()`/`classify_horizon()` sayısal threshold karşılaştırması
    # (`score >= 40` vb.) YAPAMAZ -- `None`'ı sahte bir "0"/"WATCHLIST"/
    # "BULLISH" sınıfına ÇEVİRMEK invented bir semantik olurdu. Bu iki alan
    # skorun kendisi kadar dürüst biçimde `None` kalır; breakout/market_
    # structure/relative_volume/relative_strength/mtf_alignment gibi
    # technical_score'dan BAĞIMSIZ enrichment alanları ETKİLENMEZ (aşağıda
    # DEĞİŞMEDEN hesaplanmaya devam eder).
    if final_score is not None:
        signal_inputs = SignalInputs(
            technical_score=final_score,
            market_structure=structure_result["structure"],
            breakout_event=classifier_breakout_event,
            relative_volume_class=rv_class,
            relative_strength_class=rs_class,
            mtf_aligned=alignment["aligned"],
            mtf_consensus=alignment["consensus"],
        )
        signal_class = classify_signal(signal_inputs)

        # HATA 9B-FIX: provenance yalnızca breakout kanıtı signal_class'a
        # GERÇEKTEN katkıda bulunduysa set edilir -- event VAR diye DEĞİL.
        # `bullish_confirmed` `classify_signal()`nin kendi `breakout_confirmed`
        # hesabıyla AYNI şarttır (bullish_breakout_event zaten yön-filtrelenmiş
        # olduğundan burada `direction` kontrolüne TEKRAR gerek yoktur).
        # STRONG_BULLISH_INITIATION zaten bunu ZORUNLU kılar (aksi imkansız);
        # BULLISH_CONFIRMED ise `breakout is None` yoluyla da ulaşılabilir --
        # o durumda provenance YOKTUR (`bullish_confirmed=False`).
        bullish_confirmed = bool(bullish_breakout_event and bullish_breakout_event.confirmed is True)
        if signal_class in ("STRONG_BULLISH_INITIATION", "BULLISH_CONFIRMED") and bullish_confirmed:
            signal_breakout_event_id = bullish_live_event.event_id
        else:
            signal_breakout_event_id = None

        horizon_inputs = HorizonInputs(
            signal_class=signal_class,
            market_structure=structure_result["structure"],
            trend_regime=trend_regime_val,
            relative_strength_class=rs_class,
            mtf_aligned=alignment["aligned"],
            mtf_consensus=alignment["consensus"],
        )
        investment_horizon = classify_horizon(horizon_inputs)
        investment_horizon_reason = horizon_reason(investment_horizon, horizon_inputs)
    else:
        signal_class = None
        signal_breakout_event_id = None
        investment_horizon = None
        investment_horizon_reason = ""

    nearest_support_dict = _zone_to_dict(support, price=close_val)
    nearest_resistance_dict = _zone_to_dict(resistance, price=close_val)
    breakout_dict = _breakout_to_dict(breakout_event)

    chart_zones = sorted(zones, key=lambda z: abs(z.mid - close_val))[:MAX_CHART_ZONES]

    return {
        "market_structure": structure_result["structure"],
        "signal_class": signal_class,
        "investment_horizon": investment_horizon,
        "investment_horizon_reason": investment_horizon_reason,
        "relative_volume_class": rv_class,
        "relative_strength_class": rs_class,
        "volatility_regime": vol_regime,
        "trend_regime": trend_regime_val,
        "gap_class": gap_class,
        "candlestick_patterns": candlestick,
        "nearest_support": nearest_support_dict,
        "nearest_resistance": nearest_resistance_dict,
        "breakout": breakout_dict,
        "breakout_event_id": breakout_event_id,
        "signal_breakout_event_id": signal_breakout_event_id,
        "all_zones": [_zone_to_dict(z, price=close_val) for z in chart_zones],
        "narrative": build_narrative(nearest_support_dict, nearest_resistance_dict, breakout_dict),
        "mtf_aligned": alignment["aligned"],
        "mtf_consensus": alignment["consensus"],
    }


def compute_technical_analysis(
    df: pd.DataFrame,
    symbol: str,
    weights: dict,
    family_weights: dict,
    scoring_config_hash: str,
    history_validation_status: str,
    session_normalization_fields: dict,
    provider: MarketDataProvider | None = None,
    benchmark_cache_repo: BenchmarkCacheRepository | None = None,
    benchmark_close_series: pd.Series | None = None,
    now: datetime | None = None,
) -> TechnicalAnalysis:
    """HATA 12M (10.09.2026): `analyze_with_id()`'in girdi-sözleşmesi (provider
    fetch -> completed-bar filtreleme -> session normalizasyonu -> continuity/
    integrity/data-quality kontrolleri) TAMAMLANDIKTAN SONRAKİ tüm skorlama/
    zenginleştirme/model-birleştirme mantığını içerir -- üretim (cache/provider)
    yolu ile prospective evidence-capture yolu (ayrı bir modülde, henüz
    yazılmadı) birebir AYNI formülleri kullansın diye tek, paylaşılan bir
    implementasyonda tutulur (formül kopyası YOK). Çağıran `df`/`weights`/
    `family_weights`/`scoring_config_hash`/`history_validation_status`/
    `session_normalization_fields`'i ZATEN hesaplanmış/resolve edilmiş olarak
    verir -- bu fonksiyon kendi başına ne provider'dan veri çekimi ne config
    resolve işlemi yapar. Persist etme (`TechnicalAnalysisRepository.add`) bu
    fonksiyonun SORUMLULUĞUNDA DEĞİLDİR -- yalnızca `analyze_with_id()`
    (üretim yolu) bu fonksiyonu çağırdıktan SONRA kendisi persist eder.
    """
    close, volume = df["Close"], df["Volume"]

    rsi_val = float(ind.rsi(close).iloc[-1])
    _, _, macd_hist = ind.macd(close)
    macd_hist_val = float(macd_hist.iloc[-1])
    ema_short_val = float(ind.ema(close, 20).iloc[-1])
    ema_long_val = float(ind.ema(close, 50).iloc[-1])
    ema_slope_val = float(ind.ema_slope(close, window=20, slope_lookback=5).iloc[-1])
    upper, middle, lower = ind.bollinger_bands(close)
    upper_val, middle_val, lower_val = float(upper.iloc[-1]), float(middle.iloc[-1]), float(lower.iloc[-1])
    atr_val = float(ind.atr(df).iloc[-1])
    momentum_val = float(ind.momentum(close).iloc[-1])
    roc_val = float(ind.roc(close).iloc[-1])
    volume_sma_val = float(ind.volume_sma(volume).iloc[-1])
    current_volume = float(volume.iloc[-1])
    close_val = float(close.iloc[-1])

    band_width = upper_val - middle_val

    # HATA 5B1 (27.08.2026): eski `if atr_val else 0.0` deseni yalnızca
    # LİTERAL sıfır paydayı yakalıyordu — NaN Python'da TRUTHY olduğundan
    # (`bool(float('nan'))==True`) bu guard NaN'ı HİÇ yakalamıyordu, sonuç
    # `_clamp(nan)` (Python `max`/`min`'in NaN karşılaştırma davranışı
    # nedeniyle) DETERMİNİSTİK olarak `+100.0` oluyordu — eksik bir
    # component sahte bir "maksimum bullish" sinyaline dönüşüyordu.
    # `safe_ratio()`/`clamp_component()` (bkz. `scoring.py`) hem NaN hem
    # `x/0` hem `0/0` durumunu AYNI, tutarlı NaN sonucuna götürür; RSI'ın
    # düz-seri `50.0`'ı (component `0.0`) `indicators.rsi()`'ın KENDİ
    # kasıtlı tanımıdır — GERÇEK bir geçerli sıfırdır, bu değişiklikten
    # ETKİLENMEZ. Component formülleri/skala katsayıları (25/1000/15/
    # 100/20/8) HİÇ DEĞİŞMEDİ.
    raw_components = {
        "rsi": (rsi_val - 50) * 2,
        "macd": safe_ratio(macd_hist_val, atr_val) * 25,
        "trend": safe_ratio(ema_short_val - ema_long_val, ema_long_val) * 1000,
        "ema_slope": ema_slope_val * 15,
        "bollinger": safe_ratio(close_val - middle_val, band_width) * 100,
        "momentum": safe_ratio(momentum_val, atr_val) * 20,
        "roc": roc_val * 8,
    }
    components = {k: clamp_component(v) for k, v in raw_components.items()}

    # HATA 5B2D — LEVEL 1 (component -> family): her family KENDİ
    # İÇİNDEKİ (finite) available component'lerin, `technical_indicator_
    # weights`'teki relative oranlarıyla ağırlıklı ortalamasıdır. HATA
    # 5B1 contract'ı RECURSIVE olarak burada da geçerlidir: finite 0.0
    # available'dır (ağırlığı korunur), None/NaN/±inf unavailable'dır
    # (hem numerator hem weight-denominator'dan çıkar), family'nin TÜM
    # member'ları unavailable ise `family_score=None` (0.0 UYDURULMAZ) --
    # `aggregate_available_scores` (== `aggregate_available_components`,
    # bkz. scoring.py) İKİNCİ bir bağımsız implementasyon YAZILMADAN
    # yeniden kullanılır.
    #
    # FINAL PRE-COMMIT GATE (27.08.2026, madde 4/5) — `round_digits=None`:
    # bu adım TAM HASSASİYETLE (yuvarlanmadan) hesaplanır -- aksi halde
    # Level 2 YUVARLANMIŞ family değerleri üzerinden çalışırdı ("double
    # rounding"), final `technical_score` gerçek tam-hassasiyetli
    # sonuçtan nadiren ama gerçek şekilde sapabilirdi.
    raw_family_scores: dict[str, float | None] = {
        family: aggregate_available_scores(
            {member: components[member] for member in members},
            {member: weights.get(member, 0.0) for member in members},
            round_digits=None,
        )
        for family, members in FAMILY_MEMBERSHIP.items()
    }

    # HATA 5B2D — LEVEL 2 (family -> technical_score): AYNI contract, TAM
    # HASSASİYETLİ `raw_family_scores` üzerinde -- unavailable (`None`)
    # bir family hem numerator hem weight-denominator'dan çıkar, KALAN
    # available family'lerin ağırlığı renormalize edilir. `aggregate_
    # available_scores` zaten `is_available()` ile `None` değerleri doğru
    # filtreler -- family_scores'u AYRICA filtrelemeye GEREK YOK. Bu
    # ÇAĞRI, EN SON (`round_digits=2`, varsayılan) yuvarlamanın YAPILDIĞI
    # TEK yerdir.
    final_score = aggregate_available_scores(raw_family_scores, family_weights)

    # Firestore'a/API'ye giden `components` dict'i unavailable component'leri
    # OMIT eder (None/NaN sentinel TUTMAZ) — hem "bu component için skor
    # yok" anlamını en dürüst şekilde taşır hem de downstream tüketicilerde
    # (ör. ExplanationEngine._top_reasons'ın `abs()` çağrısı) bir sentinel
    # değer nedeniyle crash riski oluşturmaz.
    stored_components = {k: v for k, v in components.items() if is_available(v)}
    # Aynı omit-unavailable/keep-valid-zero sözleşmesi `family_scores` için
    # de geçerli (HATA 5B2D, madde 8) -- debugging/explanation/historical
    # provenance için persist edilir. FINAL PRE-COMMIT GATE madde 7: bu
    # yuvarlama YALNIZCA display/provenance'tır -- `final_score` KENDİ
    # tam-hassasiyetli `raw_family_scores`'undan gelir, bu (yuvarlanmış)
    # dict'ten ASLA yeniden hesaplanmaz/okunmaz.
    stored_family_scores = {k: round(v, 2) for k, v in raw_family_scores.items() if is_available(v)}

    # HATA 5C3A (28.08.2026): "Veri Kapsamı" (evidence_coverage) skor/
    # confidence'tan BAĞIMSIZ, HER ZAMAN hesaplanabilir bir orandır (config
    # geçerli olduğu sürece None ASLA üretilmez, bkz. scoring.py::
    # compute_evidence_coverage) -- final_score None olsa BİLE (7/7
    # component unavailable) coverage=0.0 dürüst bir değerdir.
    evidence_coverage = compute_evidence_coverage(stored_components, weights, family_weights)

    if final_score is None:
        # Tüm 7 component birden unavailable — son derece nadir (HATA 5B1
        # audit'i: gerçek 5-sembol/2-yıl veri setinde 0 gözlem), ama
        # skor-bağımlı türetilmiş alanlar (confidence/trend) sahte bir
        # sayı UYDURMAZ. FINAL PRE-COMMIT GATE (27.08.2026, madde 2):
        # `trend="NEUTRAL"` da bir UYDURMAdır -- NEUTRAL, skorun
        # HESAPLANDIĞI ama [-15, 15] aralığında kaldığı GERÇEK bir teknik
        # yön bilgisidir; skor hiç hesaplanamadığında `trend=None` (bkz.
        # models/technical_analysis.py, `trend: str | None`).
        #
        # HATA 5C3A: `confidence=None` -- "Sinyal Mutabakatı" ("mevcut
        # kanıt final yönle ne kadar uyuşuyor") hesaplanacak KULLANILABİLİR
        # weighted family evidence yok. `0.0` (gerçek, ölçülmüş TAM
        # uyuşmazlık) ile KARIŞTIRILMAZ -- HATA 5B1'in "0.0 valid / None
        # unavailable" sözleşmesi confidence tarafında da AYNEN korunur
        # (bkz. HATA 5C2B, madde 1).
        confidence = None
        trend = None
    else:
        # HATA 5C3A: eski component sign-count agreement + volume
        # confirmation heuristic (0.4 taban, 0.4/0.2 katsayılar) TAMAMEN
        # KALDIRILDI. Yeni confidence yalnızca mevcut family'lerin
        # `technical_family_weights` ile ağırlıklandırılmış directional
        # agreement'ıdır (bkz. scoring.py::compute_family_agreement) --
        # skor büyüklüğüne VE volume'e bağlı DEĞİLDİR (HATA 5C2/5C2A audit
        # zincirinin kilitlediği contract). Volume, `relative_volume_class`
        # zenginleştirmesinde (aşağıda, `_compute_enrichment`) AYRI bir
        # sinyal/context olarak kalmaya devam ediyor -- yalnızca
        # confidence'la bağlantısı kesildi, volume analizi SİLİNMEDİ.
        agreement = compute_family_agreement(raw_family_scores, final_score, family_weights)
        confidence = round(agreement, 2)
        # `trend` alanı AYNI `technical_direction()` helper'ından üretilir
        # -- dış sözleşme (BULLISH/BEARISH/NEUTRAL string'leri) DEĞİŞMEDİ,
        # yalnızca +15/-15 sınırının tekilleştirilmiş (tek yerde tanımlı)
        # hali kullanılıyor (bkz. HATA 5C2B, madde 3).
        trend = {"POSITIVE": "BULLISH", "NEGATIVE": "BEARISH", "NEUTRAL": "NEUTRAL"}[
            technical_direction(final_score)
        ]

    enrichment = _compute_enrichment(
        df,
        symbol,
        atr_val,
        close_val,
        final_score,
        provider=provider,
        benchmark_cache_repo=benchmark_cache_repo,
        benchmark_close_series=benchmark_close_series,
        now=now,
    )

    analysis = TechnicalAnalysis(
        asset=symbol,
        technical_score=final_score,
        trend=trend,
        confidence=confidence,
        evidence_coverage=evidence_coverage,
        components=stored_components,
        family_scores=stored_family_scores,
        scoring_config_hash=scoring_config_hash,
        market_data_as_of=df.index[-1].to_pydatetime(),
        history_validation_status=history_validation_status,
        **session_normalization_fields,
        **enrichment,
        indicators={
            "rsi": round(rsi_val, 2),
            "macd_histogram": round(macd_hist_val, 4),
            "ema_20": round(ema_short_val, 2),
            "ema_50": round(ema_long_val, 2),
            "ema_slope": round(ema_slope_val, 4),
            "bollinger_upper": round(upper_val, 2),
            "bollinger_middle": round(middle_val, 2),
            "bollinger_lower": round(lower_val, 2),
            "atr": round(atr_val, 4),
            "momentum": round(momentum_val, 4),
            "roc": round(roc_val, 4),
            "volume": int(current_volume),
            "volume_sma": round(volume_sma_val, 2),
        },
        created_at=datetime.now(timezone.utc),
        engine_version=ENGINE_VERSION,
    )

    return analysis


class TechnicalAnalysisEngine:
    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        config_repo: SystemConfigRepository | None = None,
        analysis_repo: TechnicalAnalysisRepository | None = None,
        benchmark_cache_repo: BenchmarkCacheRepository | None = None,
    ):
        self._provider = provider or BistProvider()
        self._config_repo = config_repo or SystemConfigRepository()
        self._analysis_repo = analysis_repo or TechnicalAnalysisRepository()
        self._benchmark_cache_repo = benchmark_cache_repo or BenchmarkCacheRepository()

    def analyze(self, symbol: str, persist: bool = True) -> TechnicalAnalysis:
        analysis, _doc_id = self.analyze_with_id(symbol, persist=persist)
        return analysis

    def analyze_with_id(
        self,
        symbol: str,
        persist: bool = True,
        max_age_seconds: int = TECHNICAL_CACHE_TTL_SECONDS,
        now: datetime | None = None,
    ) -> tuple[TechnicalAnalysis, str | None]:
        # HATA 5B2D TRUE FINAL COMMIT GATE (27.08.2026): CURRENT scoring
        # config'i (indicator + family weights) CACHE KONTROLÜNDEN ÖNCE
        # resolve/validate edilir -- iki nedenle:
        #   (1) REQUIRED `technical_indicator_weights` silinmiş/bozulmuşsa
        #       bu, FRESH bir cache kaydı tarafından ASLA bypass edilemez
        #       (aksi halde config corruption sessizce maskelenirdi).
        #   (2) AYNI `engine_version` altında config DEĞİŞTİYSE (T0'da
        #       CONFIG_A ile cache'lenmiş, T1'de <TTL içinde CONFIG_B'ye
        #       geçilmiş) cache artık GEÇERSİZ sayılmalı -- yalnızca
        #       `engine_version` kontrolü bunu YAKALAYAMAZDI.
        # Aynı resolved dict'ler aşağıda (cache miss durumunda) TEKRAR
        # KULLANILIR -- ikinci bir Firestore read YAPILMAZ.
        weights = resolve_indicator_weights(self._config_repo.get_raw("technical_indicator_weights"))
        family_weights = resolve_family_weights(self._config_repo.get_raw("technical_family_weights"))
        current_scoring_config_hash = compute_scoring_config_hash(weights, family_weights)

        cached, cached_id = self._analysis_repo.get_latest_with_id(symbol)
        if cached is not None:
            age = (datetime.now(timezone.utc) - cached.created_at).total_seconds()
            # HATA 5B2D (27.08.2026, madde 20): `ENGINE_VERSION` bump'ı (1.6.0
            # -> 1.7.0, family-level scoring) structural bir score semantics
            # değişikliğidir -- eski `engine_version` taşıyan bir kayıt cache
            # hit olarak dönerse, deployment sonrası ilk 15 dakika boyunca
            # ESKİ flat-weighted skor YENİ family-scored bir sonuçmuş gibi
            # servis edilirdi. TRUE FINAL COMMIT GATE: cache artık AYRICA
            # `scoring_config_hash` da eşleşmedikçe geçerli sayılmaz -- eski
            # (bu alan eklenmeden önceki) kayıtlarda `None` olduğundan bu
            # karşılaştırma KASITLI OLARAK her zaman "eşleşmez" (cache MISS).
            if (
                age < max_age_seconds
                and cached.engine_version == ENGINE_VERSION
                and cached.scoring_config_hash == current_scoring_config_hash
            ):
                return cached, cached_id

        # HATA 2C (25.08.2026): analiz penceresinden (analysis_start) BİRAZ
        # daha ÖNCESİNİ ("pre-roll") de kapsayan TEK bir geniş istek yapılır
        # — pre-roll, sembolün analysis_start'tan ÖNCE zaten işlem gördüğünü
        # KANITLAMAK içindir, göstergelere ASLA girmez (bkz. history_window.py).
        history_window = compute_history_window(now)
        provider_history = self._provider.get_history(
            symbol,
            start=history_window.provider_request_start.isoformat(),
            end=history_window.provider_request_end.isoformat(),
        )
        # HATA 2A (25.08.2026): piyasa açıkken "bugün" satırı hâlâ oluşuyor
        # olabilir (developing/partial bar) — günlük teknik analiz yalnızca
        # TAMAMLANMIŞ barlarla üretilir (bkz. services/market_data/completed_bars.py).
        provider_history = filter_completed_daily_bars(provider_history, now=now)

        # HATA 3D (26.08.2026): authoritative takvime göre "expected session"
        # OLMAYAN (hafta sonu/planlı tatil/olağanüstü kapanış/iptal edilmiş
        # seans) hiçbir tarihteki bar — OHLC/Volume içeriğine BAKILMADAN —
        # düşürülür (ör. 27-29 Mayıs 2026 Kurban Bayramı'nda Yahoo'nun
        # bireysel hisselerde döndürdüğü, Open=High=Low=Close=önceki kapanış
        # + Volume=0 "phantom" barlar — BIST100'ün TAMAMINDA gözlemlendi).
        # KRİTİK SIRALAMA: bu adım `resolve_expected_start()`'TAN (aşağıda)
        # ÖNCE çalışmalı — aksi halde pre-roll bölgesine denk gelen bir
        # phantom bar, sembolün gerçekten `analysis_start`'tan önce işlem
        # gördüğüne dair SAHTE bir "kanıt" (VERIFIED_PRE_WINDOW) üretebilirdi.
        provider_history, session_normalization_result = normalize_bist_daily_sessions(
            provider_history, symbol=symbol, provider="yahoo_finance"
        )

        # Pre-roll bölgesinde en az bir bar varsa (analysis_start'tan ÖNCE),
        # sembolün zaten işlem gördüğü KANITLANMIŞTIR (VERIFIED_PRE_WINDOW) —
        # continuity kontrolü analysis_start'tan başlar. Yoksa (LEADING_EDGE_
        # UNVERIFIED) ne "PRE_LISTING" varsayılır ne otomatik HARD VETO
        # uygulanır — yalnızca sembolün gözlemlenen ilk barından itibaren
        # kontrol edilir (o tarihten SONRAKİ gerçek boşluklar hâlâ veto sebebidir).
        expected_start, validation_status = resolve_expected_start(provider_history, history_window.analysis_start)

        # HATA 2B (25.08.2026): "bugünü çıkar" yeterli değil — serinin
        # İÇİNDE de BIST'in resmi takvimine göre beklenen ama Yahoo'da
        # bulunmayan bir işlem günü olabilir (bkz. 24.08.2026 örneği, tüm
        # BIST100'ü aynı anda etkiledi). Böyle bir boşluk varsa, RSI/MACD/
        # EMA gibi recursive göstergeler sessizce yanlış bir "N gün önce"
        # referansı kullanacağından, eksik veri UYDURULMAZ/yoksayılmaz —
        # analiz hiç ÜRETİLMEZ (HARD VETO).
        check_trading_day_continuity(provider_history, symbol, now=now, expected_start=expected_start)

        # Pre-roll barları ASLA göstergelere girmez — skorlama yalnızca
        # analysis_start'tan itibaren çalışır. `MIN_HISTORY_DAYS` kontrolü de
        # BİLİNÇLİ OLARAK bu kırpılmış seri üzerinde yapılır (pre-roll'un
        # kendisi minimum-geçmiş şartını "sahte" karşılamasın diye).
        df = provider_history[provider_history.index.date >= expected_start]

        # HATA 5B1 (27.08.2026) — LAYER 1: mandatory analiz penceresi İÇİNDE
        # (yalnızca son bar DEĞİL) NaN/±inf/geçersiz fiyat/negatif hacim/
        # imkânsız OHLC ilişkisi varsa HARD VETO — component-seviyesi
        # "unavailable" renormalizasyonu (aşağıda) bozuk market datayı ASLA
        # gizlemez. Pre-roll bu kontrolün DIŞINDA kalır (`df` zaten yalnızca
        # `expected_start` ve SONRASINI içerir).
        check_raw_ohlcv_integrity(df, symbol)
        check_data_quality(df, symbol, min_history_days=MIN_HISTORY_DAYS, now=now)

        # `weights`/`family_weights` YUKARIDA (cache kontrolünden ÖNCE) zaten
        # resolve/validate edildi -- burada TEKRAR okunmaz/hesaplanmaz (ikinci
        # bir Firestore read YOK), aynı dict'ler doğrudan kullanılır.

        # HATA 12M (10.09.2026): girdi-sözleşmesi (yukarıda) TAMAMLANDIKTAN
        # SONRAKİ tüm skorlama/zenginleştirme/model-birleştirme mantığı artık
        # `compute_technical_analysis()`'te -- bkz. o fonksiyonun docstring'i.
        # Bu, prospective evidence-capture yolunun (ayrı bir modül, henüz
        # yazılmadı) AYNI formülleri, formül kopyası OLMADAN kullanabilmesi
        # içindir; bu satırdan sonrası artık yalnızca persist adımıdır.
        analysis = compute_technical_analysis(
            df,
            symbol,
            weights,
            family_weights,
            current_scoring_config_hash,
            validation_status.value,
            session_normalization_to_dict(session_normalization_result),
            provider=self._provider,
            benchmark_cache_repo=self._benchmark_cache_repo,
            now=now,
        )

        doc_id = self._analysis_repo.add(analysis) if persist else None
        return analysis, doc_id

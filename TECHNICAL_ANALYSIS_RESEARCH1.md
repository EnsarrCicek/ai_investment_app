# TECHNICAL_ANALYSIS_RESEARCH.md

## BIST Hisselerinde Teknik Analiz, Grafik Okuma ve “Yükseliş Başlayabilir” Sinyali İçin Araştırma Notları

> Bu doküman, `TechnicalAnalysisEngine` geliştirilirken ana teknik referans olarak kullanılmak üzere hazırlanmıştır.
>
> Amaç geleceği kesin bilmek değil; fiyat yapısı, destek/direnç, hacim, momentum, volatilite ve çoklu zaman dilimi doğrulamalarını kullanarak **olasılıksal, açıklanabilir ve backtest edilebilir** teknik sinyaller üretmektir.
>
> Bu dokümandaki `0.25 ATR`, `1.5x hacim`, `RSI 50` gibi eşikler **evrensel doğrular değildir**. Bunlar yalnızca başlangıç parametreleridir. Nihai değerler BIST verileri üzerinde backtest ve walk-forward optimization ile doğrulanmalıdır.

---

# 1. Ana sonuç

Bir hissede sürdürülebilir yükseliş başlangıcını yakalamak için en güçlü yaklaşım tek bir indikatör değildir. Sistem aşağıdaki yapıyı birlikte değerlendirmelidir:

1. Fiyat yapısı
2. Swing high / swing low
3. Higher High / Higher Low / Lower High / Lower Low
4. Destek ve direnç bölgeleri
5. Direnç kırılımının kalitesi
6. Hacim doğrulaması
7. ATR ile normalize edilmiş breakout
8. Retest
9. Çoklu zaman dilimi
10. VWAP / Anchored VWAP
11. RSI / MACD gibi momentum araçları
12. Volatilite rejimi
13. Relative Strength
14. Piyasa / sektör bağlamı
15. Veri tazeliği ve likidite

Özet akış:

```text
PRICE STRUCTURE
      ↓
SUPPORT / RESISTANCE
      ↓
BREAKOUT QUALITY
      ↓
ATR NORMALIZATION
      ↓
VOLUME CONFIRMATION
      ↓
RETEST
      ↓
MULTI-TIMEFRAME
      ↓
VWAP / AVWAP
      ↓
MOMENTUM
      ↓
REGIME / MARKET CONTEXT
      ↓
TECHNICAL SCORE
```

**RSI ve MACD ana karar motoru değil, teyit araçları olmalıdır.**

---

# 2. Tepeler ve dipler ne anlatır?

Tek bir tepe veya dip yerine bunların birbirine göre konumu önemlidir.

## Higher High / Higher Low

```text
Dipler:   90 → 94 → 98
Tepeler: 100 → 105 → 110
```

Bu yapı klasik yükseliş trendidir.

## Lower High / Lower Low

```text
Tepeler: 120 → 115 → 108
Dipler:  110 → 100 → 95
```

Bu yapı düşüş trendidir.

## Trend dönüşü

Düşüş yapısı:

```text
LH → LL → LH → LL
```

şeklindeyken ilk kez:

```text
Higher Low
+
Higher High
```

oluşması trend dönüşü için önemli adaydır. Sistem bunu örneğin `TREND_REVERSAL_CANDIDATE` olarak işaretleyebilir.

---

# 3. Swing High / Swing Low ve look-ahead bias

Swing noktaları destek/direnç ve market structure için temel girdidir. Ancak burada **look-ahead bias** riski vardır.

Bir mumun swing high olduğunu söylemek için sağında 3 mum bekleniyorsa, sistem o swing bilgisini ancak 3 mum sonra kullanabilir.

Yanlış:

```text
14:00 mumunu swing high olarak işaretle
ve 14:00 kararında kullan
```

Doğru:

```text
14:00 swing high
ancak 14:15'te doğrulandıysa
14:15 ve sonrasında kullanılabilir
```

Başlangıç yöntemleri:

- Fractal swing: sağ/sol 2, 3, 5 bar
- ZigZag benzeri ATR tabanlı swing
- Yüzde tabanlı swing threshold
- Volatiliteye uyarlanmış swing threshold

Parametreler config üzerinden değiştirilebilir olmalıdır.

---

# 4. Destek ve direnç

Direnç, fiyatın daha önce satış baskısıyla karşılaştığı bölgedir. Destek, fiyatın daha önce alıcı bulduğu bölgedir.

**Tek bir çizgi yerine bölge olarak ele alınmalıdır.**

Örnek:

```text
Direnç çizgisi: 100.00
```

yerine:

```text
Direnç bölgesi: 99.50 – 100.50
```

Bölge genişliği ATR, yüzde veya tick size ile normalize edilebilir. Başlangıçta `0.25–0.50 ATR` gibi aralıklar test edilebilir; kesin kural değildir.

## Algoritmik tespit

- Yakın swing high/low kümeleri
- Touch count
- Recency
- Volume at level
- ATR-normalized distance
- Fiyat kümelenmesi

Örneğin `99.80, 100.10, 100.25, 99.95` aynı direnç kümesi sayılabilir.

---

# 5. Dirence gelmek ile direnci kırmak aynı şey değildir

Önemli prensip:

> **Dirence gelmek bullish değildir. Direncin üzerinde kabul görmek bullish olabilir.**

Örnek:

```text
Resistance = 100
High = 101.50
Close = 99.80
```

Bu güçlü breakout değildir. Çünkü fiyat direncin üstünde kalamamıştır.

Daha doğru kontrol:

```text
close > resistance
```

Daha güçlü kontrol:

```text
close > resistance + volatility_buffer
```

---

# 6. ATR ile breakout kalitesi

Aynı yüzde fark her hisse için aynı anlamı taşımaz.

```text
breakout_distance = close - resistance
breakout_atr = breakout_distance / ATR
```

Örnek:

```text
Resistance = 100
Close = 102
ATR = 4
breakout_atr = 0.50
```

Başlangıç grid'i:

```text
0.00 ATR
0.10 ATR
0.25 ATR
0.50 ATR
0.75 ATR
```

Örnek yorum:

```text
0–0.25 ATR   → zayıf
0.25–0.50    → geçerli aday
0.50+        → güçlü aday
```

Bu seviyeler heuristiktir ve backtest edilmelidir.

---

# 7. False breakout / fakeout

Örnek:

```text
Resistance = 100
High = 103
Close = 99.50
```

Fakeout riskini artıran durumlar:

- yalnız wick ile kırılım
- düşük hacim
- breakout sonrası direnç altına hızlı dönüş
- üst timeframe'de güçlü düşüş trendi
- haber kaynaklı tek mum spike
- düşük likidite

Sistem ayrı durumlar üretebilir:

```text
BREAKOUT
CONFIRMED_BREAKOUT
FAILED_BREAKOUT
FALSE_BREAKOUT_CANDIDATE
```

---

# 8. Breakout + retest

En önemli setup'lardan biridir.

```text
Resistance = 100
97 → 99 → 101 → 104 → 101 → 106
```

Eski direnç `100–101` bölgesi yeni destek gibi çalışıyorsa yapı daha güçlü kabul edilebilir.

Retest sırasında:

- retest derinliği
- kapanış
- retest hacmi
- yeniden yükselişte hacim
- fiyat yapısı
- üst timeframe

birlikte değerlendirilmelidir.

Başlangıç test aralıkları:

```text
Retest tolerance:
0.10 ATR
0.25 ATR
0.50 ATR

Retest window:
3
6
12
24 candle
```

---

# 9. Hacim ve Relative Volume

Breakout hacimle destekleniyorsa sinyal daha anlamlı olabilir.

```text
volume_ratio = current_volume / baseline_volume
```

Baseline seçenekleri:

- SMA20 volume
- Median volume 20
- aynı saat slotunun son N günlük medyanı
- percentile yaklaşımı

BIST intraday için aynı saat slotu kıyaslaması önemlidir; açılış ve kapanış hacmi doğal olarak daha farklı olabilir.

Başlangıç grid'i:

```text
1.0x
1.2x
1.5x
1.75x
2.0x
```

Bunlar kesin eşikler değildir.

## Hacim artıyor ama fiyat ilerlemiyorsa

```text
Volume: 10M → 15M → 25M → 35M
Price:  100 → 101 → 101.2 → 101.1
```

Bu durumda distribution / absorption ihtimali araştırılmalıdır. `Volume ↑` tek başına bullish değildir.

Ek feature adayları:

```text
relative_volume
same_slot_relative_volume
volume_percentile
OBV
Accumulation/Distribution
Chaikin Money Flow
Money Flow Index
```

---

# 10. VWAP ve Anchored VWAP

VWAP formülü:

```text
VWAP = Σ(typical_price × volume) / Σ(volume)
```

Typical price:

```text
(high + low + close) / 3
```

Bullish aday:

```text
fiyat VWAP altındaydı
→ VWAP üstüne çıktı
→ VWAP retest
→ VWAP üstünde kaldı
```

Feature'lar:

```text
price_above_vwap
distance_from_vwap_atr
vwap_slope
vwap_retest
```

Anchored VWAP için anchor adayları:

- önemli swing low/high
- breakout başlangıcı
- bilanço günü
- önemli haber günü
- gap günü

Yanlış anchor seçimi anlamsız sonuç verebilir; anchor seçim kuralları deterministik olmalıdır.

---

# 11. Volume Profile

Volume Profile hacmi zamana göre değil fiyat seviyesine göre incelemeye çalışır.

Kavramlar:

```text
POC
VAH
VAL
HVN
LVN
```

Ancak önemli sınırlama:

> 5 dakikalık OHLCV candle gerçek trade-by-price dağılımını içermez.

Bu nedenle yfinance OHLCV'den oluşturulan Volume Profile **yaklaşık profil** olur. Gerçek hassas Volume Profile için tick/trade-level veya uygun exchange feed gerekir.

---

# 12. RSI

Klasik yorum:

```text
RSI > 70 → overbought
RSI < 30 → oversold
```

Ama kritik hata:

```text
RSI > 70 → SAT
```

şeklinde kesin karar vermektir. Güçlü trendlerde RSI uzun süre yüksek kalabilir.

RSI şu bağlamlarla kullanılmalıdır:

- trend
- slope
- divergence
- 50 seviyesi
- geçmiş RSI range

Bullish aday olarak `RSI > 50 ve yükseliyor` test edilebilir; kesin kural değildir.

## RSI divergence

```text
Price: 100 → 110
RSI:    78 → 67
```

Fiyat yeni tepe yaparken RSI daha düşük tepe yapıyorsa momentum zayıflaması olabilir. Divergence tek başına işlem sinyali olmamalıdır.

---

# 13. MACD

Standart:

```text
MACD = EMA12 - EMA26
Signal = EMA9(MACD)
```

Bullish teyit adayları:

```text
MACD > Signal
Histogram rising
MACD > 0
```

Ancak yatay piyasada MACD whipsaw üretebilir. Bu nedenle market regime filtresi gereklidir.

---

# 14. Moving Average ve slope

Adaylar:

```text
EMA20
EMA50
EMA200
SMA20
SMA50
SMA200
```

Feature'lar:

```text
close_above_ema20
close_above_ema50
close_above_ema200
ema20_slope
ema50_slope
ema200_slope
```

Sadece crossover yeterli değildir. Örneğin EMA20 > EMA50 olsa bile iki EMA da aşağı eğimliyse ideal bullish yapı değildir.

---

# 15. ADX ve Stochastic

ADX trend gücünü ölçer, yön göstermez. Bu nedenle `ADX + DI+ + DI- + market structure` birlikte incelenmelidir.

Stochastic range/mean-reversion ortamında daha anlamlı olabilir. Trend piyasasında overbought/oversold uzun sürebilir.

---

# 16. Bollinger, Keltner ve volatilite sıkışması

Bollinger Band Width volatilite sıkışmasını ölçmek için kullanılabilir.

```text
Bollinger Squeeze
```

güçlü hareket öncesi sıkışmaya işaret edebilir, ancak yönü söylemez.

Daha anlamlı kombinasyon:

```text
squeeze
+
resistance breakout
+
volume confirmation
```

Bollinger + Keltner kombinasyonları da volatility compression için test edilebilir.

---

# 17. Volatilite rejimi

Aynı strateji her rejimde çalışmayabilir.

Örnek rejimler:

```text
LOW_VOLATILITY
NORMAL_VOLATILITY
HIGH_VOLATILITY
SHOCK
```

Feature adayları:

```text
ATR / close
ATR percentile
realized volatility
Bollinger bandwidth
```

---

# 18. Trend vs range rejimi

Sistem önce piyasa durumunu anlamalıdır.

```text
TRENDING_UP
TRENDING_DOWN
RANGING
VOLATILE_RANGE
BREAKOUT_TRANSITION
```

Trend rejiminde structure, EMA slope, ADX ve breakout; range rejiminde support/resistance, RSI, Stochastic ve VWAP deviation daha anlamlı olabilir.

---

# 19. Relative Strength

Bir hisse yalnız kendi grafiğine göre değerlendirilmemelidir.

```text
THYAO +2%
BIST30 +4%
```

Hisse yükselse bile endekse göre zayıftır.

Feature'lar:

```text
relative_strength_1d
relative_strength_1w
relative_strength_1m
rs_vs_bist30
rs_vs_bist100
rs_vs_sector
```

Sektör ve endeks aynı yönde destekliyorsa confidence artabilir.

---

# 20. Market breadth

İleride eklenebilecek feature'lar:

```text
BIST30 advance/decline
% above EMA20
% above EMA50
new highs / new lows
sector breadth
```

Amaç tek hisse sinyalini piyasa geneliyle kıyaslamaktır.

---

# 21. Gap analizi

Gap'ler haber veya gece gelişmeleri nedeniyle oluşabilir.

Feature'lar:

```text
gap_pct
gap_atr
gap_fill_percent
```

Haber kaynaklı büyük gap sonrası ilk birkaç candle klasik setup'lardan ayrı değerlendirilebilir.

---

# 22. Candlestick patternleri

Takip edilebilir:

- Hammer
- Shooting Star
- Engulfing
- Doji
- Morning Star
- Evening Star

Ancak:

```text
hammer → AL
```

şeklinde tek başına kullanılmamalıdır.

Daha güçlü bağlam:

```text
Hammer
+
Major support
+
High relative volume
+
Bullish divergence
```

---

# 23. Trendline, channel ve klasik patternler

Takip edilebilecek yapılar:

- Double Top / Bottom
- Head & Shoulders
- Inverse H&S
- Triangle
- Ascending / Descending Triangle
- Symmetrical Triangle
- Flag
- Pennant
- Wedge
- Cup & Handle

Pattern tamamlanmadan sinyal verilmemelidir. Örneğin Double Bottom için yalnız iki dip değil, neckline breakout da aranmalıdır.

Pattern engine şu ayrımı yapabilir:

```text
pattern_detected
pattern_confirmed
pattern_failed
pattern_confidence
```

---

# 24. Multi-Timeframe Analysis

Örnek kullanım:

```text
5m     → entry timing
15m    → momentum
1h     → setup
Daily  → ana trend
Weekly → büyük yapı
```

Bu kesin standart değildir. Önemli olan alt timeframe sinyali ile üst timeframe'in ciddi şekilde çelişip çelişmediğini ölçmektir.

Örnek:

```text
5m bullish breakout
1h bearish
daily strong bearish
```

Bu durumda confidence düşürülmelidir.

---

# 25. “Yükseliş başlayabilir” framework'ü

```text
Yeni candle kapandı
        ↓
Veri taze mi?
        ↓
Market structure iyileşti mi?
        ↓
Higher Low var mı?
        ↓
Higher High veya bearish structure break var mı?
        ↓
Önemli direnç var mı?
        ↓
Direnç kapanışla aşıldı mı?
        ↓
ATR'ye göre anlamlı mesafe var mı?
        ↓
Hacim destekliyor mu?
        ↓
VWAP / trend ile uyumlu mu?
        ↓
RSI / MACD momentum teyidi var mı?
        ↓
Üst timeframe ciddi şekilde çelişiyor mu?
        ↓
Retest oldu mu?
        ↓
Retest başarılı mı?
        ↓
BULLISH_INITIATION_CANDIDATE / CONFIRMED
```

---

# 26. Ne zaman AL sinyali vermemeli?

## Hard veto adayları

```text
STALE_DATA
MISSING_OHLCV
INVALID_PRICE_DATA
PROVIDER_ERROR
LOOK_AHEAD_RISK
```

## Teknik confidence cap / veto

```text
breakout failed
close resistance altına döndü
çok düşük relative volume
çok düşük likidite
yüksek spread
üst timeframe güçlü bearish
haber sonrası aşırı gap
çok az historical data
```

---

# 27. Likidite, spread, slippage ve order flow sınırı

Teknik sinyal iyi görünse bile düşük likidite gerçek işlem sonucunu bozabilir.

İzlenebilecekler:

```text
average traded value
average volume
spread
turnover
zero-volume bars
```

Ücretsiz OHLCV veri gerçek bid/ask spread, order book imbalance, queue position, aggressor side veya exact trade-by-price vermez. Bu nedenle OHLCV tabanlı analiz **order-flow analizi gibi sunulmamalıdır**.

Backtestte commission, spread ve slippage mutlaka düşünülmelidir.

---

# 28. BIST'e özel veri ve seans konuları

Türkiye saat dilimi:

```text
Europe/Istanbul
```

Tam işlem günlerinde sürekli işlem yaklaşık 10:00–18:00 aralığındadır. Açılış seansı, kapanış süreçleri, yarım günler ve resmi tatiller ayrıca yönetilmelidir.

Açılışta:

- hacim
- gap
- spread
- volatilite

normalden farklı olabilir. Bu nedenle `OPENING_VOLATILITY`, `NORMAL_SESSION`, `CLOSING_SESSION` gibi seans rejimleri faydalı olabilir.

Devre kesici ve fiyat limitleri de grafiğin normal davranışını bozabilir. Veri kaynağı bu bilgiyi sağlamıyorsa sistem uydurmamalıdır.

---

# 29. TechnicalScore nasıl tasarlanmalı?

Ağırlıkları baştan kesin doğru kabul etmek yanlış olur.

Yanlış yaklaşım:

```text
RSI = %20
MACD = %20
EMA = %20
Volume = %20
Breakout = %20
```

Daha doğru yaklaşım:

```text
Feature üret
↓
Market regime belirle
↓
Confirmation logic
↓
Backtest
↓
Walk-forward optimization
↓
Out-of-sample test
↓
Production
```

Ağırlıklar config/model üzerinden değiştirilebilir olmalıdır.

---

# 30. Önerilen feature set

## Structure

```text
market_structure
higher_high
higher_low
lower_high
lower_low
structure_break
bars_since_structure_break
```

## Support / Resistance

```text
nearest_support
nearest_resistance
support_strength
resistance_strength
support_distance_atr
resistance_distance_atr
```

## Breakout / Retest

```text
breakout_status
breakout_atr
breakout_pct
breakout_hold_bars
failed_breakout
retest_status
retest_depth_atr
retest_volume_ratio
retest_success
```

## Volume

```text
volume_ratio
same_slot_volume_ratio
volume_percentile
obv
cmf
```

## Momentum

```text
rsi14
rsi_slope
rsi_divergence
macd
macd_signal
macd_histogram
macd_histogram_slope
```

## Trend

```text
ema20
ema50
ema200
ema20_slope
ema50_slope
ema200_slope
```

## Volatility

```text
atr14
atr_percent
atr_percentile
bollinger_bandwidth
volatility_regime
```

## VWAP

```text
vwap
distance_to_vwap_atr
vwap_slope
vwap_reclaim
avwap
```

## Relative Strength

```text
rs_vs_bist30
rs_vs_bist100
rs_vs_sector
```

## Multi-Timeframe

```text
trend_5m
trend_15m
trend_1h
trend_1d
mtf_alignment
```

## Data Quality

```text
data_age_seconds
data_status
missing_bar_count
provider
is_delayed
```

---

# 31. Confidence ile TechnicalScore aynı şey değildir

Örnek:

```text
TechnicalScore = +75
Confidence = %55
```

mümkündür.

Çünkü skor bullish olsa bile veri eksik, retest yok veya üst timeframe çelişkili olabilir.

Confidence için aday girdiler:

- data completeness
- confirmation count
- signal agreement
- regime stability
- liquidity
- historical out-of-sample performance

---

# 32. LLM'nin rolü

LLM şunları yapmamalıdır:

```text
OHLCV'den RSI hesaplamak
MACD hesaplamak
destek/direnç uydurmak
geleceği kesin biliyormuş gibi konuşmak
```

Deterministik motor:

```text
OHLCV
↓
Features
↓
TechnicalScore
```

üretmelidir.

LLM yalnız gerçek hesaplanmış sonuçları açıklamalıdır.

Örnek structured output:

```json
{
  "symbol": "THYAO",
  "timeframe": "5m",
  "market_structure": "HL_HH",
  "support": 306.80,
  "resistance": 312.50,
  "close": 315.10,
  "atr14": 5.30,
  "breakout_atr": 0.49,
  "volume_ratio": 1.83,
  "rsi14": 61.4,
  "macd_bullish": true,
  "above_vwap": true,
  "hourly_regime": "BULLISH",
  "daily_regime": "NEUTRAL",
  "retest_status": "NOT_YET",
  "technical_score": 76,
  "confidence": 0.71,
  "signal": "BULLISH_CANDIDATE"
}
```

---

# 33. Kullanıcıya verilecek açıklama örneği

Uygulama yalnızca:

```text
RSI = 61
MACD = AL
```

göstermemelidir.

Daha doğru örnek:

```text
Son düşüş yapısı bozuldu.
Higher Low ve ardından Higher High oluştu.

312.50 TL direnç bölgesi kapanışla kırıldı.
Breakout mesafesi 0.49 ATR.
Relative Volume 1.83x.

Fiyat VWAP üzerinde.
RSI 61 ile pozitif momentum gösteriyor.
MACD bullish.

1 saatlik trend olumlu.
Günlük trend nötr.

Henüz retest oluşmadığı için sinyal tamamen doğrulanmış değil.
Teknik Güven: %71
```

---

# 34. Backtest olmadan güvenilir sayılmamalı

Teknik analiz araştırmalarında kritik riskler:

- data snooping
- overfitting
- ex-post parameter selection
- transaction costs
- survivorship bias
- look-ahead bias

Her yeni feature doğrudan kabul edilmemelidir.

---

# 35. Look-ahead bias

```text
14:35'te verilen karar
```

yalnızca:

```text
timestamp <= 14:35
```

olan verileri kullanmalıdır.

Gelecekteki candle geçmiş kararı değiştiremez.

---

# 36. Survivorship bias

Bugünkü BIST30 listesini 2020 backtestine uygulamak hatalı olabilir. Endeks bileşenleri zamanla değişir.

Doğru yaklaşım:

```text
2020'de hangi hisseler BIST30'daydı?
```

sorusunu kullanmaktır.

---

# 37. Data snooping ve walk-forward

Çok sayıda strateji test edip en iyi görüneni seçmek şans eseri iyi model bulabilir.

Bu nedenle random split yerine zaman sıralı test kullanılmalıdır.

Örnek:

```text
TRAIN      2021–2023
VALIDATION 2024
TEST       2025
```

Sonra ileri kaydır:

```text
TRAIN      2022–2024
VALIDATION 2025
TEST       2026
```

---

# 38. Başlangıç parameter grid

```text
Resistance lookback:
20, 40, 50, 75, 100

Swing confirmation:
2, 3, 5, 8 bars

Breakout ATR:
0, 0.10, 0.25, 0.50, 0.75

Price band:
0%, 0.25%, 0.50%, 1%

Volume ratio:
1.0, 1.2, 1.5, 1.75, 2.0

Retest tolerance:
0.10, 0.25, 0.50 ATR

Retest window:
3, 6, 12, 24 bars

RSI floor:
45, 50, 55

Higher timeframe:
none
1h
1h + daily
```

---

# 39. Backtest hedefi

Hedef yalnızca:

```text
next candle green?
```

olmamalıdır.

Daha anlamlı hedef:

```text
bu breakout sonrası sürdürülebilir yükseliş oluştu mu?
```

Triple-barrier benzeri başlangıç örneği:

```text
Entry:
breakout close

Success:
+1.5 ATR veya +2 ATR

Failure:
-0.75 ATR veya -1 ATR

Timeout:
belirli bar sayısı
```

Bunlar başlangıç parametreleridir.

---

# 40. Backtest ölçümleri

Yalnız toplam kâr yeterli değildir.

```text
Precision
Recall
F1
Win Rate
Profit Factor
Max Drawdown
Sharpe
Sortino
Expectancy
Average Win
Average Loss
MFE
MAE
Turnover
Exposure
Number of Trades
```

Özellikle **precision** önemlidir. Sürekli yanlış “yükseliş başlayabilir” sinyali kullanıcı güvenini azaltır.

---

# 41. yfinance ve veri arşivi

MVP için yfinance kullanılabilir; ancak resmi BIST real-time vendor değildir ve intraday history sınırlıdır.

Bu nedenle bugünden itibaren çekilen 5m candle'lar kalıcı olarak saklanmalıdır.

```text
BIST30 × 5m × her işlem günü
```

uzun vadede özel backtest veri setimizi oluşturabilir.

---

# 42. Firestore için örnek alanlar

```text
symbol
interval
market_timestamp
received_at
provider_timestamp
open
high
low
close
volume
atr14
rsi14
macd
macd_signal
macd_hist
ema20
ema50
ema200
support
resistance
volume_ratio
vwap
breakout_atr
market_structure
retest_status
timeframe_1h_regime
timeframe_1d_regime
relative_strength
technical_score
confidence
signal
data_source
data_status
feature_version
strategy_version
parameter_version
```

Duplicate kimliği:

```text
symbol + interval + market_timestamp
```

Örnek:

```text
THYAO_5m_20260819T143500
```

---

# 43. AI karar kayıtları değiştirilemez

Örneğin:

```text
19.08.2026 14:35
THYAO
TechnicalScore = 76
Decision = BULLISH_CANDIDATE
```

kaydedildiyse fiyat daha sonra düşse bile bu kayıt değiştirilmemelidir. Yeni değerlendirme yeni kayıt olmalıdır.

---

# 44. Örnek sinyal sınıfları

```text
STRONG_BULLISH_INITIATION
BULLISH_CONFIRMED
BULLISH_CANDIDATE
WATCHLIST
NEUTRAL
BEARISH_CANDIDATE
NO_SIGNAL
```

Kesin `AL / SAT / TUT` etiketi DecisionEngine seviyesinde üretilmelidir.

```text
TechnicalAnalysisEngine → TechnicalScore
EventIntelligenceEngine → NewsScore
MacroAnalysisEngine     → MacroScore
DecisionEngine          → FinalScore → AL/SAT/TUT/NO_SIGNAL
```

Teknik motor haber veya makro bilgiyi kendi skoruna karıştırmamalıdır.

---

# 45. Risk / Reward, invalidation ve stop

İyi teknik setup bile kötü risk/reward ile işlem yapılmaması gereken hale gelebilir.

Örnek:

```text
Entry = 100
Invalidation = 97
Target = 102
Risk = 3
Reward = 2
R/R = 0.67
```

Her setup “hangi şartta yanlış sayılacak?” sorusuna cevap vermelidir.

Stop adayları:

- ATR
- destek
- swing low
- structure invalidation
- volatility-adjusted stop

Position sizing risk motoruna bırakılmalıdır.

---

# 46. Akademik ve kurumsal kaynaklar

## Akademik

### Lo, Mamaysky & Wang — Foundations of Technical Analysis
https://www.nber.org/papers/w7613

Grafik patternlerinin sistematik ve algoritmik incelenmesi için temel akademik kaynaklardan biridir.

### Brock, Lakonishok & LeBaron — Simple Technical Trading Rules
https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1992.tb04681.x

Moving average ve trading range breakout kurallarının ampirik testi.

### Park & Irwin — What Do We Know About the Profitability of Technical Analysis?
https://experts.illinois.edu/en/publications/what-do-we-know-about-the-profitability-of-technical-analysis/

Data snooping, metodoloji ve teknik analiz kârlılığı literatürü için önemli.

### Big data-enabled sign prediction for Borsa Istanbul intraday equity prices
https://research.itu.edu.tr/en/publications/big-dataenabled-sign-prediction-for-borsa-istanbul-intraday-equit/

BIST intraday 5 dakikalık yön tahmini üzerine çalışma.

### Intraday prediction of Borsa Istanbul
https://www.sciencedirect.com/science/article/abs/pii/S0950705117304252

BIST100 intraday yön tahmini ve teknik feature kullanımı.

## Charles Schwab

Support / Resistance / Patterns:
https://www.schwab.com/learn/story/how-to-read-stock-charts-and-trading-patterns

Volume:
https://www.schwab.com/learn/story/ways-volume-can-help-confirm-price-trends

VWAP:
https://www.schwab.com/learn/story/how-to-use-volume-weighted-indicators-trading

Volume Profile:
https://www.schwab.com/learn/story/using-volume-profile-indicator

Multiple Timeframes:
https://www.schwab.com/learn/story/swing-trading-strategies

## Fidelity

RSI:
https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI

MACD:
https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/macd

ATR:
https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr

Multiple Timeframes:
https://www.fidelity.com/viewpoints/active-investor/how-to-set-up-your-charts

## CMT Association

Anchored VWAP:
https://cmtassociation.org/podcast/fill-the-gap-episode-sixty-one-anchored-vwap-legend-brian-shannon-cmt/

## Borsa İstanbul

Data Dissemination:
https://www.borsaistanbul.com/en/data/data-dissemination

Market Data Products:
https://www.borsaistanbul.com/en/data/data-dissemination/market-data-products

Trading Hours:
https://www.borsaistanbul.com/en/markets/equity-market/trading-hours

Official Holidays:
https://www.borsaistanbul.com/en/official-holidays

Index Methodologies:
https://www.borsaistanbul.com/en/indices/methodologies-and-changes

## yfinance

Download API:
https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html

Repository:
https://github.com/ranaroussi/yfinance

---

# 47. Claude Code'a verilecek kullanım promptu

Bu dosyayı projede örneğin:

```text
docs/TECHNICAL_ANALYSIS_RESEARCH.md
```

olarak tut.

Claude Code'a şu prompt verilebilir:

```text
docs/TECHNICAL_ANALYSIS_RESEARCH.md dosyasını baştan sona dikkatlice oku.

Bu dosya projenin TechnicalAnalysisEngine tarafındaki ana teknik referans dokümanıdır.

Mevcut TechnicalAnalysisEngine kodlarını ve ilgili market data modellerini incele.
Dokümandaki özellikleri körü körüne ekleme.

Önce şu raporu çıkar:

1. Şu anda sistemde bulunan feature'lar
2. Eksik feature'lar
3. Hatalı veya aşırı basitleştirilmiş hesaplamalar
4. Look-ahead bias riski olan yerler
5. Eklenmesi gereken servis/modüller
6. Değiştirilecek dosyalar
7. Önerilen geliştirme sırası

Özellikle şu özelliklere öncelik ver:

- Market Structure
- Swing High / Swing Low
- HH / HL / LH / LL
- Support / Resistance Zones
- Breakout Quality
- False Breakout
- Retest
- Relative Volume
- ATR-normalized breakout
- EMA slope
- RSI
- MACD
- VWAP
- Multi-Timeframe
- Relative Strength
- Volatility Regime
- Data Freshness

0.25 ATR, 1.5x volume gibi değerlerin kesin piyasa kuralları olmadığını unutma.
Bunları config üzerinden değiştirilebilir başlangıç parametreleri olarak tut.
İleride backtest ve walk-forward optimization ile optimize edilebilir hale getir.

LLM teknik göstergeleri hesaplamasın.
OHLCV → feature → TechnicalScore hesapları deterministik Python kodunda yapılsın.
AI yalnızca gerçek hesaplanmış verileri açıklamak için kullanılsın.

Look-ahead bias oluşturma.
Gelecekteki candle hiçbir geçmiş kararda kullanılmasın.
Mevcut çalışan kodu gereksiz yere yeniden yazma.

Önce analiz raporunu göster.
Kod değişikliğine rapordan sonra başla.
```

---

# 48. Sonuç

`TechnicalAnalysisEngine` yalnızca RSI/MACD/EMA hesaplayan bir motor olmamalıdır.

Ana yaklaşım:

```text
PRICE ACTION
+
MARKET STRUCTURE
+
SUPPORT / RESISTANCE
+
BREAKOUT
+
VOLUME
+
RETEST
+
VOLATILITY
+
MULTI-TIMEFRAME
+
RELATIVE STRENGTH
+
MOMENTUM CONFIRMATION
```

En önemli prensip:

> Teknik analiz “kesin yükselecek” dememelidir.

Doğru çıktı:

```text
Mevcut teknik kanıtlar yükseliş olasılığını artırıyor.
```

ve sistem bu sonucu hangi gerçek verilerden çıkardığını açıkça gösterebilmelidir.

Gerçek başarının ölçüsü grafikte güzel görünmek değil:

```text
out-of-sample backtest
+
walk-forward test
+
işlem maliyetleri
+
gerçek zamanlı immutable karar kayıtları
```

olmalıdır.

# 49. HATA 12 — Technical V1 Prospective Validation Provenance Kapanışı (17.09.2026)

Bu bölüm, HATA 12 numaralı çok-haftalık denetim/implementasyon zincirinin (HATA
12N2A...12N3C2-E2-B-R1) CAPTURE-ÖNCESİ araştırma/provenance/taksonomi
sözleşmelerini kapatan özet referanstır. **Hiçbir üretim aktivasyonu, deploy,
scheduler ya da controller bu zincirde inşa EDİLMEDİ** — kapsam, henüz
inşa edilmemiş bir attempt-execution servisinin uyacağı sözleşmelerdir.

**Dondurulmuş protokol kimliği:** `TECHNICAL_V1_PROTOCOL_V1`,
`protocol_sha256 = ee13afdde2a251bd86fc684e0786f01a9d0b12f7a52ebb2b7771693cb1d38f79`
(`backend/app/research/resources/technical_v1_protocol_v1.json`, `content_sha256`
ile hesaplanır, ham dosya byte'ları ile DEĞİL).

**Dondurulmuş freeze-manifest kimliği:**
`freeze_manifest_sha256 = 6556f7a9c9b9eedcc4b789c861cc2e1b5b2d4a13be1be75605162f0e578bdc97`
(`backend/app/research/resources/technical_v1_freeze_manifest.json`, AYNI
`content_sha256` algoritmasıyla, protokolün `methodology_references` alanında
da kayıtlıdır).

**Kapsam:** yalnızca `TechnicalAnalysisEngine` çıktıları (`technical_score`/
`signal_class`/family-component'ler) — DecisionEngine'in tam AL/SAT sistemi ya
da haber/makro kanalları DEĞİL (protokolün kendi `scope_note`'u).

**İmmutable evidence mimarisi:** content-addressed hash'ler
(`canonical_hash.content_sha256`), physical-ID-from-logical-identity deseni,
`AttemptClaim`/`AttemptResult` arasında zorunlu `activation_lock_id` eşleşmesi
(`ProvenanceConflictError` ile korunur), `input_snapshot_sha256`'ın
asset+benchmark hash'lerinden zorunlu türetilmesi.

**Activation-lock mimarisi:** `TechnicalV1ActivationLock` — CONFIG/
METHODOLOGY/RUNTIME/UNIVERSE kimliklerinin tek, tutarlı bir "aktivasyon anı"na
bağlanması; `runtime_fingerprint`'in `K_SERVICE`/`K_REVISION`/
`FIREBASE_PROJECT_ID`'den GERÇEKTEN gözlemlenmesi (asla `"local"`/`"unknown"`
gibi uydurma fallback YOK).

**Session/final-evaluation sözleşmeleri:** `final_evaluation_selector.py`'nin
claim/result identity + activation-lock tutarlılığı, `_qualifying_at_attempt2_
decision()`'ın YALNIZCA `VALID_CANDIDATE`'i "attempt2 gerekmez" sayması,
`ResultState.NO_RESULT` — beklenmeyen bir internal defect/crash'in HİÇBİR
ZAMAN uydurma bir terminal `AttemptResultClassification`'a dönüştürülmemesi.

**Dört kimlik-kapısı** (`app/research/identity_gates.py`, saf, I/O'suz
karşılaştırma fonksiyonları — `IdentityGateEvaluation`, PASS⟺reason_code=None
değişmezi):

| Kapı | FAIL reason-code | Beklenen `AttemptResultClassification` |
|---|---|---|
| CONFIG | `SCORING_CONFIG_HASH_MISMATCH` | `BLOCKED_CONFIG_DRIFT` |
| METHODOLOGY | `METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH` | `BLOCKED_METHODOLOGY_DRIFT` |
| RUNTIME | `RUNTIME_IDENTITY_UNAUTHORIZED` | `BLOCKED_RUNTIME_IDENTITY` |
| UNIVERSE | `SYMBOL_NOT_IN_FROZEN_UNIVERSE` | `BLOCKED_UNIVERSE_OR_ASSET_CONFIG` |

**Exclusion taksonomisi** (protokolün `missing_data_policy.excluded_
categories`'i, `app/research/exclusion_policy.py`'deki saf evaluator'larla):

| Kategori (protokol metni) | Faz | Koşul / reason-code | Sınıflandırma |
|---|---|---|---|
| technical_score is None | ANALYSIS-TIME (post-analysis) | `TechnicalAnalysis.technical_score is None` → `TECHNICAL_SCORE_NONE` | EXCLUSION |
| leading-edge unverified handling | ANALYSIS-TIME (post-analysis, tek başına hard-veto DEĞİL) | başarılı analiz VE `history_validation_status == "LEADING_EDGE_UNVERIFIED"` → `LEADING_EDGE_UNVERIFIED` | EXCLUSION |
| trading-day continuity hard-veto | CAPTURE-TIME (hard veto, `TechnicalAnalysis` hiç oluşmaz) | `MISSING_TRADING_SESSION` / `UNEXPECTED_TRADING_SESSION` (reuse, `data_quality.py`) | EXCLUSION |
| raw OHLCV integrity failure | CAPTURE-TIME (hard veto) | `INVALID_OHLCV` (reuse) | EXCLUSION |
| insufficient MIN_HISTORY_DAYS | CAPTURE-TIME (hard veto) | `INSUFFICIENT_HISTORY` (reuse) | EXCLUSION |
| incomplete input snapshot | DEFERRED TO ATTEMPT SERVICE | henüz hiçbir kod bunu üretmiyor (`freeze_manifest.input_snapshot_evidence_design = "TO_BE_DEFINED_BEFORE_HOLDOUT"`) | tanım netleştiğinde belirlenecek — HATA 12 correctness blocker DEĞİL |
| forward horizon lacking sufficient completed future sessions | OUTCOME-EVALUATION ONLY | E10 olgunlaşmamış — capture-time `AttemptResult` reddi DEĞİL | capture-time reason-code YOK, olgunlaşma bekler |

**Tek-neden (single-reason) öncelik kuralı:** `AttemptResult.native_reason_code`
TEK bir skaler `str | None` olarak kalır (multi-reason şema GENİŞLEMESİ YOK).
Sıralı pipeline'da spesifik bir downstream hard-veto (continuity/raw-OHLCV/
insufficient-history) her zaman `LEADING_EDGE_UNVERIFIED`'dan ÖNCELİKLİDİR —
çünkü böyle bir veto zaten `TechnicalAnalysis` nesnesinin OLUŞMASINI
engeller. Analiz başarıyla tamamlanırsa VE aynı anda hem `technical_score is
None` hem `history_validation_status == LEADING_EDGE_UNVERIFIED` ise (yapısal
olarak bağımsız iki koşul, nadiren birlikte oluşabilir —
`resolve_post_analysis_exclusion()` testleriyle kanıtlanmıştır),
`TECHNICAL_SCORE_NONE` tek persisted neden olarak SEÇİLİR (analiz çıktısının
kendisinin yokluğu, bir provenance bayrağından daha doğrudan sonuç-geçersiz-
kılıcıdır).

**Kalan iş — HATA 12 correctness blocker DEĞİL, implementasyon/operasyon
kilometre taşları:** attempt-execution servisi, claim/controller/scheduler,
production deploy/aktivasyon, evidence-upload orkestrasyonu, outcome-
maturation worker, uzun-vadeli parametre kalibrasyonu, ikincil provider işi.
Bunların hiçbiri HATA 12'yi açık TUTMAZ — bilimsel/provenance sözleşmeleri
zaten TAM ve test edilmiş.

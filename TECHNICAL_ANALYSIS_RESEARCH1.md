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

# 50. HATA 13 — ORCHESTRATION IMPLEMENTATION COMPLETE (18.09.2026)

HATA 12'nin kapattığı bilimsel/provenance sözleşmelerini GERÇEK, çalışan bir
boru hattına bağlayan dört implementasyon bileti (13B-13E) TAMAMLANDI. Bu,
KOD SEVİYESİNDE bir tamamlanmadır — production aktivasyonu/deploy/scheduler
AYRI, henüz YAPILMAMIŞ bir sonraki adımdır (aşağıya bkz.).

**13B — activation event + pre-claim authorization:** `TechnicalV1
ActivationEvent` (`INITIAL`/`LOCK_AUTHORIZED`, aktivasyon KİLİDİNDEN AYRI bir
yetkilendirme kaydı) + create-only repository'si + saf `authorize_pre_claim()`
(aktivasyon yetkisi × protokol kimliği × dondurulmuş evren üyeliğini,
`claim_attempt()`'ten HEMEN ÖNCE, GCS'siz olarak doğrular).

**13C — tek-deneme (single-attempt) yürütme:** `TechnicalV1AttemptExecution
Service.execute_attempt()` — pre-claim yetkilendirme → claim → post-claim
dört kimlik-kapısı (provider işinden ÖNCE) → provider fetch/normalizasyon →
GENİŞ (pre-roll dahil) asset evidence → continuity/OHLCV/insufficient-history
hard-veto exclusion'ları → benchmark bir KEZ çekilip enjekte edilir →
`compute_technical_analysis()` (paylaşılan, değiştirilmemiş) → benchmark/
output evidence → `TECHNICAL_SCORE_NONE`/`LEADING_EDGE_UNVERIFIED`
post-analysis exclusion → `AttemptResult` yayınlama.

**13D — attempt2 + finalizasyon:** `TechnicalV1Attempt2Orchestrator`,
seçicinin KENDİ, GCS'siz 09:00 tarihsel önyargısını (`_qualifying_at_
attempt2_decision`) yeniden kullanır, 09:00-09:45 penceresinde 13C'ye delege
eder. `TechnicalV1Finalizer.finalize()`, formal cutoff'tan (09:45) SONRA
`select_final_evaluation()`'ı çağırıp `TechnicalV1EvaluationRepository.
create()` ile persist eder — ve (final fix) bu evaluation_id için ZATEN
doğrulanmış bir `FinalEvaluation` varsa, attempt'leri HİÇ yeniden okumadan
koşulsuz `IDEMPOTENT_REUSE` döner: **ilk başarıyla oluşturulmuş, doğrulanmış
FinalEvaluation kanoniktir**, geç (audit-only) bir attempt yazımı onu ASLA
yeniden hesaplatamaz.

**13E — session controller:** `TechnicalV1SessionController`, dondurulmuş
TAM 100 sembolü (`TrustedTechnicalV1Protocol.frozen_symbol_list`, canlı
BIST100 DEĞİL) üzerinde dört faz sunar: `run_attempt1_phase`/
`run_attempt2_phase`/`run_finalization_phase`/`build_session_manifest_if_
complete`. Her faz 100 sembolün TAMAMINI dener; bir sembolün operasyonel
hatası (per-symbol yalıtım, KASITLI OLARAK GENİŞ) diğer 99'u durdurmaz.
Manifest'in KENDİSİ (`build_session_manifest()`, değiştirilmemiş), 100
`FinalEvaluation`'ın TAMAMI doğrulanmadan (`SessionAccountingStatus.
COMPLETE`) ÇAĞRILMAZ — eksik/çakışan kayıt varsa manifest HİÇ persist
edilmez (`MISSING_FINAL_RECORDS`/`REPOSITORY_PROVENANCE_CONFLICT`).
`TechnicalV1SessionRunSnapshot` (mutable, bilimsel kanıt DEĞİL) her
finalizasyon geçişinde SIFIRDAN yeniden inşa edilir.

**HENÜZ YAPILMAYANLAR (bilinçli, bu HATA'nın kapsamı dışında):**
  - Cloud Scheduler/cron/Cloud Run zamanlanmış tetikleyici OLUŞTURULMADI.
    Gelecekte planlanan çağrı noktaları (Europe/Istanbul, T_session_date'ten
    SONRAKİ ilk BIST işlem gününe ankorlu): 08:00 attempt1 fazı, 09:00
    attempt2 fazı, 10:15 operasyonel finalizasyon/manifest fazı.
  - Production activation event/lock OLUŞTURULMADI.
  - `evidence_capture_ready`/`prospective_holdout_started`/`effective_
    holdout_start` HÂLÂ `false`/`false`/`null`.
  - Gerçek Firestore/GCS'e HİÇBİR yazma yapılmadı — tüm testler sahte
    (fake) Firestore + `FakeEvidenceObjectStore` + sahte provider ile
    çalışır.

Bu bölüm, KOD'un mevcut olduğunu belgeler — prospective holdout'un
BAŞLADIĞINI İDDİA ETMEZ.

# 51. PROD-2 — TECHNICAL V1 PRODUCTION WIRING (18.09.2026)

HATA 13'te tamamlanan `TechnicalV1SessionController`'ın dört fazı, GERÇEK
HTTP üzerinden çağrılabilir hale getirildi — hiçbir aktivasyon/scheduler/
prospective-holdout ADIMI ATILMADAN. Yeni internal endpoint'ler (`app/api/
technical_v1_internal.py`, prefix `/internal/technical-v1`):
`POST /attempt1`, `POST /attempt2`, `POST /finalize`, `POST /manifest`.
Auth, `app/api/jobs.py`'deki `DAILY_JOB_SECRET` deseninin BİREBİR AYNISı
— ayrı bir sabit (`TECHNICAL_V1_JOB_SECRET`) ile, `X-Job-Secret` header'ı
üzerinden. Evidence yazımları `TECHNICAL_V1_EVIDENCE_BUCKET` env var'ından
okunan bucket'a gider — kod içinde hiçbir varsayılan/hardcoded bucket adı
YOKTUR; ayarlı değilse endpoint'ler 503 döner, ordinary `import app.main`
ETKİLENMEZ. Tüm bilimsel/orkestrasyon mantığı (09:00/09:45 kararları,
evidence doğrulama/seçim, dondurulmuş 100-sembol evreni) DEĞİŞTİRİLMEDEN
HATA 12/13'e delege edilir — bu router SADECE ince bir HTTP/loglama
katmanıdır.

**Gelecekte planlanan (bu ticket'ta OLUŞTURULMAYAN) Cloud Scheduler
hedefleri** (Europe/Istanbul, T_session_date'ten SONRAKİ ilk BIST işlem
gününe ankorlu, HATA 13'ün zaten belgelediği saatlerle TUTARLI):
  - 08:00 → `POST /internal/technical-v1/attempt1`
  - 09:00 → `POST /internal/technical-v1/attempt2`
  - 10:15 → `POST /internal/technical-v1/finalize`, ardından
    `POST /internal/technical-v1/manifest`

**Bu ticket'ta KASITLI OLARAK YAPILMAYANLAR:** activation lock/event
oluşturma endpoint'i yok; gerçek bir Cloud Scheduler job'ı oluşturulmadı;
`evidence_capture_ready`/`prospective_holdout_started`/`effective_holdout_
start` HÂLÂ `false`/`false`/`null`; gerçek Firestore/GCS'e hiçbir production
yazma denenmedi (yalnızca sahte/stub bağımlılıklarla test edildi).

# PROD-3 — PRODUCTION DEPLOYMENT DEFERRED

Technical V1 kodu production deployment aşamasına kadar hazırlanmıştır.
Ancak `ai-investment-app-2026` Google Cloud projesinde Cloud Billing
devre dışıdır.

Cloud Build, Artifact Registry, Cloud Run deployment, Cloud Scheduler,
Secret Manager ve production evidence-storage altyapısının ilgili
kısımlarının kullanılabilmesi için aktif bir Google Cloud Billing hesabı
gerekmektedir.

Bu nedenle production deployment ve prospective validation activation
şimdilik bilinçli olarak ERTELENMİŞTİR.

Bu durum:
- kod correctness problemi değildir,
- Technical V1 bilimsel/provenance blocker'ı değildir,
- HATA 12/13 çalışmalarını yeniden açmaz.

İleride production deployment istenirse:
1. Cloud Billing kullanıcı tarafından bilinçli olarak etkinleştirilecek,
2. PROD-3 kontrollü deployment adımlarından devam edilecek,
3. deploy sonrasında runtime/IAM/GCS doğrulamaları yapılacak,
4. activation lock/event bundan SONRA oluşturulacak,
5. scheduler en son etkinleştirilecek,
6. prospective holdout ancak tüm production kontrolleri geçtikten sonra
   başlayacaktır.

Şu an durum:

PROD-2 = COMPLETE
PROD-3 = DEFERRED — BILLING REQUIRED
Production deploy = YOK
Production activation = YOK
Scheduler = YOK
evidence_capture_ready = false
prospective_holdout_started = false
effective_holdout_start = null

Not:
Billing etkinleştirilmesi gelecekte Google Cloud kullanım ücretlerinin
oluşmasına neden olabilir. Kullanıcının açık kararı olmadan billing
etkinleştirilmeyecektir.

# HATA 15B — CROSS-SOURCE EVENT DEDUP COMPLETE

HATA 15A denetiminin #2 bulgusu (aynı gerçek-dünya olayının Yahoo/Google/
Foreks'ten AYRI `external_id`'lerle gelip hiçbir yerde birleştirilmemesi,
son-10 haber penceresinde orantısız ağırlık yaratması) düzeltildi.

**Makale kimliği (`external_id`) DEĞİŞMEDİ** — hâlâ ham veri
provenance/idempotency için tek kaynak. Ayrı, YENİ bir mantıksal-olay
kümeleme katmanı eklendi (`backend/app/services/news/event_dedup.py`):
asset-sınırlı, 48 saatlik zaman penceresi ile sınırlı, deterministik
başlık-normalizasyonu (rakamlar KORUNUYOR) + Jaccard≥0.82 near-duplicate
eşiği (Foreks'in mevcut intra-batch eşiğiyle aynı, cross-provider için
yeniden test edildi).

Bilinçli tasarım kararı: kalıcı/tekil bir `event_id` ÜRETİLMEDİ — Jaccard
benzerliği geçişli olmadığından ve yeni bir yakın-tekrar makale geldiğinde
kümelenme kompozisyonu teorik olarak değişebileceğinden, kümeleme HER
ÇAĞRIDA (analiz tetikleme anında VE skorlama anında) mevcut girdi kümesi
üzerinden deterministik olarak yeniden hesaplanıyor — "article fingerprint"
(external_id, kalıcı) ile "scoring-time cluster identity" (yeniden
hesaplanan, kalıcı değil) kasıtlı olarak AYRI tutuldu.

Durum:
- article identity remains external_id: EVET
- logical event dedup is separate: EVET (event_dedup.py, ayrı katman)
- raw provider records preserved: EVET (news_raw hiçbir zaman silinmiyor,
  yalnızca hangi maddenin LLM'e gönderileceği kısıtlanıyor)
- scoring uses unique logical events: EVET (`DecisionEngine.
  _deduplicate_news_analyses`, `_aggregate_news_score()`'un formülü
  DEĞİŞMEDİ — yalnızca girdi kümesi tekilleştirildi)
- source_reliability still not wired: EVET (HATA 15A bulgu #1, bu ticket'ın
  kapsamı DIŞINDA, ayrı bir ticket'ta ele alınacak)
- no time decay/historical similarity added: EVET (bu ticket'ın kapsamı
  dışında bırakıldı)
- no deployment performed: EVET

Bilinen sınırlama (gizlenmiyor): bu, yerel/deterministik bir token-Jaccard
algoritmasıdır — aynı olayın FARKLI DİLLERDE (İngilizce Yahoo başlığı vs
Türkçe Foreks başlığı) yazılmış başlıkları birbirine eşleşmez (embedding/
LLM tabanlı çeviri bu ticket kapsamı dışında). Aynı dil içindeki gerçek
ifade farklılıklarını (cross-provider near-duplicate) güvenilir şekilde
yakalar.

Test: `backend/tests/test_event_dedup.py` (26 yeni test) + mevcut
`test_event_intelligence_engine.py`/`test_decision_engine.py`/
`test_foreks_news_provider.py` regresyonsuz geçti. Tam backend paketi:
2054 passed, 0 failed, 0 skipped, 0 xfail (2028 mevcut + 26 yeni).

## HATA 15B FINAL — "son 10 BENZERSİZ olay" penceresi kilitlendi

Denetim `DecisionEngine.decide_for_asset()`'in gerçek okuma sırasını
doğruladı: `NewsAnalysisRepository.list_for_asset(asset, limit=NEWS_SCORE_
LIMIT)` limiti dedup'tan ÖNCE uyguluyordu (RAW-10-THEN-DEDUP) — bu, çoklu-
sağlayıcı tekrarı en yeni 10 ham slot'u işgal ettiğinde, ondan eskiye giden
BAĞIMSIZ olayların hiç okunmadan pencereden dışarı kalmasına yol açan
GERÇEK bir correctness hatasıydı. Düzeltme: decision scoring window is the
last 10 unique logical events; the repository continues reading older
analyses (artık `list_for_asset(asset, limit=None)` ile TÜM geçmiş
okunuyor, `_deduplicate_news_analyses()` TAMAMI üzerinde çalışıyor, ve
`NEWS_SCORE_LIMIT` yalnızca dedup SONRASI uygulanıyor) when duplicate raw
records consume newer slots. Cross-language limitation (İngilizce/Türkçe
başlık eşleşmemesi) DEĞİŞMEDEN belgeli kalıyor — bu ticket kapsamı dışında.

Test: `backend/tests/test_event_dedup.py`'ye 3 yeni test eklendi (12-kayıt
backfill + tam sayısal skor kilidi, 20 kopyalı-çalışma sabit-limit-yok
kanıtı, 10'dan az mevcut olay durumu). Rigor check: eski (hatalı) davranış
geçici olarak geri getirildi, 3 yeni test kırıldı (regresyon kilidi
doğrulandı), düzeltme geri yüklendi (dosya byte-identical), tüm testler
tekrar yeşil. Tam backend paketi: 2057 passed, 0 failed, 0 skipped, 0
xfail (2054 mevcut + 3 yeni). No deployment performed.

# HATA 15C — SOURCE RELIABILITY SCORING COMPLETE

HATA 15A bulgu #1 (`source_reliability` sağlayıcılar tarafından hesaplanıp
saklanıyor ama skorlamada hiç okunmuyordu — ölü veri) düzeltildi.

Formül: `effective_weight = confidence * source_reliability` (mevcutsa),
`news_score = sum(sentiment_score * effective_weight) / sum(effective_weight)`
(HATA 15B'nin kümeleme/temsilci-seçim SIRASI DEĞİŞMEDİ — reliability her
BENZERSİZ olayın yalnızca deterministik temsilcisinden okunuyor, kümenin
diğer üyeleri ASLA toplanmıyor/ortalanmıyor).

Config kaynağı DEĞİŞMEDİ: reliability değerleri hâlâ sağlayıcı tarafında
`system_config` (`source_reliability` dokümanı, `DEFAULT_SOURCE_RELIABILITY`
fallback'i ile) üzerinden `NewsRawItem.source_reliability`'ye yazılıyor —
DecisionEngine bunu ham kayıttan OKUYOR, ikinci bir config mekanizması
oluşturulmadı.

Eksik-reliability semantiği (bilinçli seçim, bölüm 9): ham makale kaydı
bulunamayan (silinmiş/legacy provenance) bir temsilci için reliability
`None` kalır — fabrike bir OTHER_MEDIA=0.60 değeri ASLA ATANMAZ. Bu durumda
o olay için reliability boyutu skorlamadan DIŞLANIR, `effective_weight`
sadece `confidence`'a düşer ("mevcut boyutlarla ağırlıklandırma"). Bilinen
bir yayıncı kategorisi (OTHER_MEDIA dahil) GERÇEK configured bir değerdir —
bu durum "eksik" ile KARIŞTIRILMAZ ve normal şekilde ağırlıklandırmaya
katılır.

Durum:
- reliability now affects unique-event weighting: EVET
- exact formula: `confidence * source_reliability` (mevcutsa), yoksa
  `confidence` (reliability boyutu dışlanır, icat edilmez)
- config source: `system_config.source_reliability` (DEĞİŞMEDİ, ikinci bir
  mekanizma oluşturulmadı)
- missing reliability semantics: ham kayıt bulunamazsa `None` → reliability
  dışlanır, fabrike OTHER_MEDIA=0.60 ATANMAZ
- known OTHER_MEDIA semantics: gerçek configured kategori, ağırlıklandırmayı
  etkiler (eksik provenance ile karıştırılmaz)
- no duplicate-source amplification: EVET (yalnızca temsilcinin reliability'si
  kullanılır, kümenin diğer üyelerininki toplanmaz)
- last-10-unique rule unchanged: EVET (HATA 15B FINAL semantiği korunuyor)
- no time decay/historical similarity added: EVET (bu ticket'ın kapsamı
  dışında bırakıldı)
- ExplanationEngine dedup/reliability issue remains separately open: EVET
  (bilinen, dokümante, ayrı bir ticket'ta ele alınacak — `explain()` hâlâ
  ham son-10 kaydı okuyor, HATA 15B/15C katmanına bağlı değil; bu ticket
  yalnızca paylaşılan `_aggregate_news_score()` imzasına uyum için
  `source_reliability=None` ile mevcut confidence-only davranışını
  DEĞİŞTİRMEDEN plumbing güncellemesi aldı)
- no deployment performed: EVET

Geçersiz (negatif/NaN/±inf/1'den büyük) bir `source_reliability` sessizce
clamp/coerce edilmez — fail-fast `ValueError` (bu projenin
`resolve_decision_weights`/`resolve_decision_thresholds` ile aynı ilkesi).
"Yanlış tip" senaryosu production'da fiilen erişilemez -- `NewsRawItem.
source_reliability: float` Pydantic tarafından zaten garanti ediliyor;
sayısal aralık/finite kontrolü savunma amaçlı kalıyor.

Test: `backend/tests/test_news_reliability_scoring.py` (15 yeni test —
sayısal reliability etkisi, eşit-reliability kontrolü, confidence hâlâ
çarpan, sıfır/geçersiz reliability, bilinmeyen-kaynak/None semantiği,
bilinen OTHER_MEDIA ağırlıklandırması, config-değişikliği hassasiyeti,
çoklu-sağlayıcı amplifikasyon-yok, son-10-benzersiz pencere regresyonu).
Rigor check A/B/C (reliability boyutu kaldırıldı / eksik kaynak fabrike
OTHER_MEDIA'ya düşürüldü / kümenin tüm üyelerinin reliability'si toplandı)
üçü de ilgili testleri gerçekten kırdı, restore sonrası tekrar yeşil. Tam
backend paketi: 2072 passed, 0 failed, 0 skipped, 0 xfail (2057 mevcut +
15 yeni). No deployment performed.

## HATA 15C SON DÜZELTME — UNKNOWN PUBLISHER ≠ FAKE OTHER_MEDIA

`classify_publisher()` eşleşmeyen/eksik/boş bir yayıncı için artık icat
edilmiş bir `OTHER_MEDIA=0.60` DEĞİL, sayısal değer taşımayan `None` döner.

Kesinleşen kural:

> Eşleşmeyen/eksik yayıncı provenance'ı OTHER_MEDIA reliability ağırlığını
> ALMAZ. Reliability `None`'dır ve olay confidence-only "available-dimension
> weighting"i kullanır.

Denetim bulgusu (bölüm 1/12): kod tabanında şu anda hiçbir yayıncıyı
BİLEREK/açıkça OTHER_MEDIA'ya eşleyen bir kural YOK — `_PUBLISHER_CATEGORY`
yalnızca KAP/NEWS_AGENCY/FINANCIAL_MEDIA tanır; OTHER_MEDIA daima
"eşleşmedi" fallback'ıydı. Bu nedenle "bilinen OTHER_MEDIA" ile "tarihsel
fallback" şu an production kodunda ayırt edilemez; sahte bir production
eşlemesi İCAT EDİLMEDİ, bu ayrım gelecekte gerçek bir OTHER_MEDIA kuralı
eklenirse mümkün olacak.

Provider zinciri (Yahoo/Google/Foreks) güncellendi: eşleşmeyen/eksik
yayıncı → `NewsRawItem.source_reliability = None` (alan artık `float | None`).
Foreks'in sabit `PUBLISHER="Foreks"` değeri gerçekten bilinen bir kategoriye
(FINANCIAL_MEDIA) eşleşiyor — bu icat edilmiş bir fallback değil, gerçek
sınıflandırma bilgisi, dolayısıyla Foreks'te davranış değişmedi.

Legacy kayıt belirsizliği (bölüm 8, göç YAPILMADI): bu düzeltmeden ÖNCE
yazılmış eski `news_raw` kayıtları hâlâ `source_reliability=0.60`
içerebilir ve bu değerin gerçekten bilinen bir OTHER_MEDIA sınıflandırması
mı yoksa eski fallback mi olduğu, mevcut provenance'tan artık geriye dönük
AYIRT EDİLEMEZ. Bu belirsizlik bilinçli olarak kabul edildi, sahte bir
kesinlik iddia edilmedi.

DecisionEngine'in HATA 15C confidence-only fallback mekanizması
DEĞİŞMEDİ — bu düzeltme yalnızca `classify_publisher()`'ın hangi
durumlarda `None` üreteceğini düzeltti.

Test: `test_source_reliability.py` (+3), `test_yahoo_news_provider.py`
(yeni dosya, 3 test), `test_google_news_rss_provider.py` (+1),
`test_foreks_news_provider.py` (+1), `test_news_reliability_scoring.py`
(+1 end-to-end). Rigor check: eski `unknown → OTHER_MEDIA` fallback'ı
geçici olarak geri getirildi, 4 test kırıldı, restore sonrası tekrar
yeşil. Tam backend paketi: 2080 passed, 0 failed, 0 skipped, 0 xfail
(2072 mevcut + 8 yeni). No deployment performed.

# HATA 15D — EVENT ANALYSIS PROVENANCE COMPLETE

Denetim bulgusu (HATA 15A): EventIntelligenceEngine'in LLM çağrısı, hangi
GERÇEK metnin/prompt'un/şemanın/modelin bir NewsAnalysis'i ürettiğini
kanıtlayacak explicit bir provenance/reproducibility izi taşımıyordu.

Uygulanan çözüm — her YENİ NewsAnalysis artık şunları taşır:

- `analyzed_text`: LLM'e GERÇEKTEN gönderilen son metin (başlık/özet/
  makale-gövdesi seçimi + kırpma sonrası, ham web sayfası DEĞİL). Canlı
  sayfa daha sonra değişse bile bu alan SABİT kalır (immutable, add-only
  kayıt) — `test_live_article_change_after_persist_does_not_mutate_
  historical_provenance` bunu kanıtlar.
- `analyzed_text_sha256`: yukarıdaki metnin SHA-256 hex digest'i
  (canonical UTF-8 bytes, Python `hash()` DEĞİL — süreçler arası kararlı).
- `prompt_version` = `"event_intelligence_v1"` (dosya mtime'ından
  TÜRETİLMEDİ — elle bump edilen sabit bir string, `ENGINE_VERSION` ile
  aynı sözleşme).
- `prompt_sha256`: sistem prompt'unun SHA-256'sı (insan-okunur
  `prompt_version`'ın YERİNE değil, ONUNLA BİRLİKTE).
- `output_schema_version` = `"event_intelligence_output_v1"` (Pydantic
  sınıf adından AYRI, açıkça persist edilen bir sürüm etiketi).
- `model_used`: zaten (bu ticket'tan ÖNCE de) gerçekten invoke edilen
  modeldi — `analyze_item`'daki `model=self._primary_model` ile
  `model_used=self._primary_model` AYNI değişkeni kullanıyordu; bu ticket
  bunu test ile KİLİTLEDİ. `_should_escalate()` hâlâ hiç çağrılmıyor
  (bkz. HATA 15A/engine.py modül docstring'i) — gerçek bir fallback/
  invoked-model ayrımı bu sürümde test edilebilir DEĞİL (N/A, bölüm 32).

Determinism: `temperature=0.0` ve `seed=0` artık her çağrıda gönderiliyor
— Chat Completions API'sinin gerçekten desteklediği en deterministik iki
parametre. **Bitwise-deterministik bir GARANTİ iddia edilmiyor**: OpenAI
`seed`'i kendi dokümantasyonunda "best-effort" olarak tanımlıyor
(`system_fingerprint` değişimi/backend güncellemeleri aynı seed'in aynı
çıktıyı garanti etmediği anlamına gelir). Bu ticket yalnızca API'nin
sunduğu en güçlü reproducibility sinyalini kullanıyor ve bunu dürüstçe
"best-effort" olarak belgeliyor.

Immutability korundu: `NewsAnalysis` hâlâ add-only; yeni alanlar
`NewsAnalysis(...)` construction'ı (Pydantic doğrulaması dahil) SIRASIYLA
`repo.add()`'dan ÖNCE set ediliyor — geçersiz/malformed LLM çıktısı
(bozuk JSON veya şema-dışı `data`) hiçbir zaman (ne tam ne kısmi) bir
NewsAnalysis persist ETMEZ; bu, kod değişikliği gerektirmeyen zaten var
olan doğru bir sıralamaydı, bu ticket'ta test ile KİLİTLENDİ
(`test_invalid_json_llm_output_does_not_persist_any_analysis`,
`test_schema_invalid_llm_output_does_not_persist_any_analysis`).

Analiz kimliği (bölüm 13): `news_id + asset` DEĞİŞMEDİ — mevcut add-only/
immutable + `get_by_news_id` skip sözleşmesi zaten aynı kaydın sessizce
üzerine yazılmasını engelliyor; gereksiz bir versiyonlama şeması İCAT
EDİLMEDİ.

Legacy uyumluluk: yeni alanların TÜMÜ `str | None = None` — bu alanlar
eklenmeden ÖNCE yazılmış kayıtlar hiç içermez, destructive migration
YAPILMADI, eski kayıtlar güvenle okunmaya devam ediyor. Mevcut olduklarında
strict doğrulanıyorlar (`analyzed_text_sha256`/`prompt_sha256`: 64
küçük-harf hex; `prompt_version`/`output_schema_version`: boş/whitespace-
only olamaz).

Kapsam dışı bırakılanlar (kasıtlı, bu ticket'ta DOKUNULMADI): HATA 15B
cross-source dedup/last-10-unique penceresi, HATA 15C source-reliability
ağırlıklandırma formülü, sentiment/confidence/importance şeması, time
decay, historical similarity, embeddings, ExplanationEngine'in ayrı açık
kalan dedup exposure'ı (bkz. HATA 15C raporu). `DecisionEngine` skorlaması
BYTE-FOR-BYTE aynı kaldı —
`test_decision_engine_score_unaffected_by_new_provenance_fields` bunu
kanıtlıyor.

Test: `test_event_analysis_provenance.py` (yeni dosya, 17 test). Rigor
check A (snapshot/hash persistence geçici kaldırıldı → 7 provenance testi
kırıldı, restore sonrası yeşil). Rigor check B: N/A (gerçek bir fallback/
invoked-model ayrımı bu sürümde YOK, sahte bir fallback yolu İCAT
EDİLMEDİ). Rigor check C (geçersiz JSON çıktısına geçici olarak fake bir
başarılı kayıt persist ettirildi → invalid-output testi kırıldı, restore
sonrası yeşil). Tam backend paketi: 2097 passed, 0 failed, 0 skipped,
0 xfail (2080 mevcut + 17 yeni). No deployment performed.

# HATA 15E — EXPLANATION NEWS CONSISTENCY COMPLETE

Denetim bulgusu (HATA 15A, HATA 15C FINAL raporunda disclosed ayrı açık
konu olarak bırakılmıştı): `ExplanationEngine.explain()` haber tarafında
doğrudan ham `news_repo.list_for_asset(asset, limit=NEWS_SCORE_LIMIT)`
okuyordu — HATA 15B cross-source event dedup'ına ve HATA 15C source-
reliability ağırlıklandırmasına HİÇ bağlı DEĞİLDİ. Sonuç:
`DecisionEngine.decide_for_asset()` skorunu "son 10 BENZERSİZ mantıksal
olay" üzerinden üretirken, `ExplanationEngine` "son 10 HAM kayıt"
üzerinden açıklama üretebiliyordu — üyelik/temsilci tutarsızlığı.

Uygulanan çözüm: seçim mantığının kendisi (dedup + backfill semantiği +
temsilci-reliability eşleme, eski `DecisionEngine._deduplicate_news_
analyses`) `app.services.news.news_selection` modülüne (`_WeightedNews
Analysis`, `_aggregate_news_score`, `_deduplicate_news_analyses`,
`NEWS_SCORE_LIMIT`, ve yeni `select_recent_unique_news_analyses`)
ayıklandı. `DecisionEngine.decide_for_asset()` VE `ExplanationEngine.
explain()` artık İKİSİ DE bu TEK paylaşımlı fonksiyonu çağırıyor — aynı
repo verisiyle çağrıldıklarında birebir aynı üyeliği/temsilciyi
ürettikleri `test_decision_and_explanation_membership_parity` ile
kilitlendi (`ExplanationEngine.explain()`'in döndürdüğü dict'e yalnızca
kimlik listesi olan `news_analysis_ids` alanı eklendi — HATA 15D
provenance hash'leri/ham snapshot'lar BURADA sızdırılmıyor).

Özet:

- Makale kimliği (`external_id`/`news_id`) DEĞİŞMEDİ.
- Etkin pencere DEĞİŞMEDİ: son `NEWS_SCORE_LIMIT` (=10) BENZERSİZ
  mantıksal olay — artık her iki motor için de aynı.
- Aynı deterministik temsilci: `ExplanationEngine` bir kümeden farklı bir
  üyeyi "beğenip" seçemez, tamamen DecisionEngine ile aynı seçimi kullanır.
- HATA 15C source-reliability skorlama formülü DEĞİŞMEDİ — yalnızca
  `ExplanationEngine`'in `_aggregate_news_score()`'a verdiği girdi kümesi
  artık HATA 15B/15C'nin dedup+reliability katmanından geçiyor (önceden
  `source_reliability=None` sabit varsayımıyla confidence-only formül
  kullanılıyordu).
- `ExplanationEngine` HİÇBİR ZAMAN canlı makale fetch'i
  (`fetch_article_text`) veya yeniden LLM analizi
  (`EventIntelligenceEngine.analyze_item`) tetiklemez — yalnızca zaten
  persist edilmiş `NewsAnalysis`/`NewsRawItem` kayıtlarını okur
  (`test_explanation_engine_never_fetches_live_article_or_calls_llm`
  ile kilitlendi).
- `published_at` vs `created_at` causality sorusu (HATA 15A'dan beri
  bilinen, ayrı açık konu) bu ticket'ta ÇÖZÜLMEDİ — sıralama semantiği
  aynen korundu.
- Legacy kayıtlar (HATA 15D provenance alanları olmayan) ve eksik ham
  provenance (savunma amaçlı tekil-küme fallback) iki motorda da AYNI
  güvenli davranışı üretir — crash yok, bağımsız gruplama icat edilmedi.
- Sabit over-fetch limiti YOK: dedup TAM geçmiş üzerinde çalışır, `limit`
  yalnızca SONUÇTA uygulanır (HATA 15B FINAL semantiği korunuyor).

Test: `test_explanation_news_consistency.py` (yeni dosya, 11 test) +
`test_explanation_engine.py`'ye `news_raw_repo` fake'i eklendi (4 test
güncellendi, davranış DEĞİŞMEDİ). Rigor check A (ExplanationEngine geçici
olarak paylaşımlı seçiciyi bypass edip eski ham `list_for_asset(limit=10)`
davranışına döndürüldü → parity testi dahil 9 test kırıldı, restore
sonrası yeşil). Rigor check B (ExplanationEngine'in temsilci seçimi
geçici olarak TERS ÇEVRİLDİ — gerçek kural "gövde var + en eski" yerine
"gövde yok + en yeni" → yalnızca >1 üyeli kümeleri içeren 3 test kırıldı,
tekil-olay testleri etkilenmedi, restore sonrası yeşil). Rigor check C
(paylaşımlı seçici geçici olarak limit'i dedup'tan ÖNCE uygulayacak
şekilde değiştirildi → hem mevcut HATA 15B backfill testleri hem yeni
HATA 15E parity/backfill testleri kırıldı, restore sonrası yeşil). Tam
backend paketi: 2108 passed, 0 failed, 0 skipped, 0 xfail (2097 mevcut +
11 yeni). No deployment performed.

# HATA 15F — NEWS TIMESTAMP CAUSALITY COMPLETE

Bu ticket, HATA 15 EventIntelligence correctness serisinin (15A denetim,
15B cross-source dedup, 15C source-reliability, 15D LLM provenance, 15E
explanation-consistency) SON parçası ve KAPANIŞ raporudur.

Denetim (kod okunarak, varsayım YAPILMADAN) iki ayrı sorun buldu ve
İKİSİNİ de minimal biçimde düzeltti — sınıflandırma: **C) CONFIRMED
CAUSALITY/ORDERING BUG**:

**1) `received_at` immutable DEĞİLDİ.** `NewsRawItem.received_at`
("sistem bu makaleyi İLK ne zaman gözlemledi") kavramsal olarak zaten
mevcuttu, ama `NewsRawRepository.upsert()` her seferinde TÜM dokümanı
`.set()` ile üzerine yazıyordu ve her provider cron çalışmasında
`received_at = datetime.now(...)` YENİDEN üretiyordu (bkz. yahoo/google/
foreks_news_provider.py) — yani aynı `external_id` ikinci kez fetch
edilince ilk-gözlem zamanı SESSİZCE en son fetch anına ilerliyordu.
Düzeltme: `upsert()` artık önce mevcut kaydı okuyor, varsa onun
`received_at`'ini yeni değerin üzerine YAZIYOR (diğer tüm alanlar —
title/summary/source_reliability/published_at — normal şekilde
güncellenmeye devam ediyor).

**2) Son-10-benzersiz-olay penceresi `NewsAnalysis.created_at`'e (LLM
işleme TAMAMLANMA anı) göre sıralanıyordu, olayın gerçek yayın
kronolojisine (`published_at`) göre DEĞİL.** Ticket'ın "delayed analysis"
örneğiyle (bölüm 9) kanıtlandı: 09:00'da yayınlanıp 12:00'de (backlog
yüzünden) analiz edilen bir haber, 10:00'da yayınlanıp 10:05'te analiz
edilen bağımsız bir haberden "daha yeni" görünüyordu — işleme gecikmesi,
gerçek haber kronolojisiyle karışıyordu. Düzeltme:
`app/services/news/event_dedup.py`'ye `EventCluster.event_recency`
(temsilcinin `published_at`'i) eklendi; `news_selection.py`
`_deduplicate_news_analyses()` artık kümeleri bu alana göre azalan sırada
döndürüyor — `analyses` girdi listesinin (created_at azalan) sırasını
KORUMA davranışı kaldırıldı. `_aggregate_news_score()` FORMÜLÜ
DEĞİŞMEDİ; yalnızca hangi 10 olayın pencereye GİRECEĞİNİ/hangi sırada
DÖNECEĞİNİ belirleyen anahtar düzeltildi. `DecisionEngine` ve
`ExplanationEngine` HATA 15E'nin paylaşımlı `select_recent_unique_news_
analyses()`'ini kullanmaya devam ediyor — düzeltme TEK bir yerde
yapıldığı için ikisi arasında yeni bir sapma riski YOK.

**Dokümante edilen zaman-damgası sözleşmesi (bölüm 26, seri için kapanış
tanımı):**

- `NewsRawItem.published_at`: yayıncının beyan ettiği yayın zamanı —
  provider parse anında UTC-aware olarak normalize edilir (Yahoo:
  ISO+`Z`→`+00:00`; Google/Foreks: `parsedate_to_datetime` + naive→UTC
  fallback), eksikse ilgili öğe ingestion'da EXCLUDE edilir (`if not ...
  pub_date_text: continue` — Foreks'te doğrulandı, `test_skips_items_
  missing_pub_date` ile zaten kilitli, DEĞİŞMEDİ).
- `NewsRawItem.received_at`: sistemin bu makaleyi İLK gözlemlediği an —
  artık (bu ticket'tan sonra) upsert boyunca IMMUTABLE. Şu an hiçbir
  canlı skorlama/seçim yolu tarafından OKUNMUYOR (yalnızca gelecekte bir
  historical/as-of sorgu inşa edilirse eligibility/causality gate'i için
  kullanılacak otorite alan budur — bu ticket öyle bir sorgu İNŞA ETMEDİ,
  yalnızca alanın anlamını sabitledi).
- `NewsAnalysis.created_at`: LLM analizinin TAMAMLANDIĞI an (işleme
  kronolojisi/audit — HATA 15D provenance ile aynı ruhta). Artık son-N-
  benzersiz-olay SEÇİM/SIRALAMA anahtarı OLARAK KULLANILMIYOR (yalnızca
  `NewsAnalysisRepository.list_for_asset()`'in HAM getirme sırasını
  belirliyor — dedup katmanı sonucu published_at'e göre yeniden sıralıyor).
- **Eligibility (bir haber ne zaman "sistem tarafından bilinebilir" hale
  gelir):** `received_at` — ama bugünkü canlı mimaride bu HİÇBİR ZAMAN
  ihlal edilemez, çünkü analiz yalnızca zaten `news_raw`'a yazılmış
  (= zaten gözlemlenmiş) kayıtlar üzerinde çalışır. Historical/backtest
  bir özellik YOK ve bu ticket'ta İNŞA EDİLMEDİ.
- **Canlı recency sıralaması (son-N-benzersiz-olay penceresi):**
  `published_at` (temsilci üzerinden, `EventCluster.event_recency`).
- **Gelecekte bir historical/as-of analiz özelliği inşa edilirse** o da
  `received_at`'i (as-of zamanında zaten gözlemlenmiş miydi) eligibility
  gate'i, `published_at`'i kronoloji/sıralama için kullanmalıdır —
  `NewsAnalysis.created_at`'i ASLA yayın zamanı yerine kullanmamalıdır.

**Disclosed, düzeltilmeyen kalan boşluk:** Yahoo provider'da `pub_date =
content.get("pubDate") or content.get("displayTime")` her ikisi de eksik
olursa `None.replace(...)` ile crash eder (sessiz veri bozulması değil,
gürültülü hata — provider yeniden tasarımı bu ticket kapsamı dışında
bırakıldı, bkz. bölüm "DO NOT: redesign providers"). Gelecekte
malformed/future-dated `published_at` değerlerine karşı açık bir
doğrulama da YOK (ör. `published_at > received_at`) — mevcut kodda somut
bir kanıt/olay bulunamadı, bu yüzden İCAT EDİLMİŞ bir doğrulama
EKLENMEDİ; residual, belgelenmiş bir gözlem olarak bırakıldı.

Test: `test_event_intelligence_causality.py` (yeni dosya, 11 test) —
`received_at` immutability + ilk-upsert normal davranış, delayed-analysis
kritik testi (+ `limit=1` varyantı), created_at/published_at BİLEREK
karıştırılmış 10-bağımsız-olay backfill regresyonu, çoklu-sağlayıcı
temsilci kimliği DEĞİŞMEDİ testi, Decision/Explanation sıralama parity
(HATA 15E üzerine), timezone-offset doğru sıralama, ham-provenance-yok
fallback (crash yok), ve iki rigor-check testi (eski `created_at`-sıralı
dedup'ı ve eski `.set()`-tabanlı upsert'i test dosyası içinde geçici
monkeypatch ile simüle edip YANLIŞ sonucu ürettiklerini kanıtlıyor —
production kodu bu testler için hiç değiştirilmedi/geri alınmadı).

HATA 15B (cross-source dedup/48s pencere/0.82 eşik/asset sınırı) / 15C
(source-reliability formülü) / 15D (LLM provenance mekanizması) semantiği
tamamen KORUNDU — yalnızca son-10-benzersiz-olay SIRALAMA anahtarı ve
`received_at` immutability'si düzeltildi. Yeni bir historical/backtest
pipeline'ı EKLENMEDİ. No deployment performed.

# HATA 16B — MACRO CONFIG / FAKE-NEUTRAL FIX COMPLETE

HATA 16A denetiminin (salt okunur, kod değiştirilmedi) doğruladığı iki
bağlantılı production hatası düzeltildi:

1. `MacroAnalysisEngine` artık `macro_indicator_weights`/
   `macro_indicator_scales` config'lerini `SystemConfigRepository.get()`
   (auto-seed + sessiz partial-merge, HATA 5B2C'nin kök nedeni) İLE DEĞİL,
   `get_raw()` + yeni fail-fast `resolve_macro_weights()`/
   `resolve_macro_scales()` resolver'ları İLE okuyor —
   `decision/engine.py::resolve_decision_weights()`/
   `resolve_decision_thresholds()` (HATA 5C3B) ile AYNI desen. Resolver'lar
   provider fetch'ten ÖNCE çağrılır: eksik/geçersiz config, hiçbir Yahoo
   çağrısı yapılmadan fail-fast eder, Firestore'a hiçbir auto-seed/write
   YAPILMAZ.
2. Bir RUN'da mevcut göstergelerin TAMAMI sıfır ağırlıklı kanallara denk
   gelirse (`available_weight == 0` — config toplamda geçerli/pozitif
   olsa bile, ör. `dxy=0` + o an yalnızca dxy verisi mevcut), engine artık
   `macro_score = 0.0` UYDURMUYOR — `ValueError` (`NO_POSITIVE_WEIGHT_
   AVAILABLE`, `DecisionEngine.decide()`'daki aynı desenle simetrik)
   fırlatıyor ve hiçbir `MacroSnapshot` kaydedilmiyor. Gerçek/hesaplanmış
   nötr sonuç (mevcut bileşenlerin ağırlıklı toplamı tam olarak 0'a denk
   gelmesi, `available_weight > 0` iken) KORUNDU — bu durumda
   `macro_score == 0.0` hâlâ başarıyla persist edilir (gerçek bir nötr
   sonuçtur, uydurma değildir).

Config kuralları: her weight finite + `>= 0` olmalı (tek tek sıfır
SERBEST), toplam config weight'i `> 0` olmalı (tümü-sıfır config GEÇERSİZ);
her scale finite + STRICTLY `> 0` olmalı (weight'in aksine, tek tek sıfır
scale de GEÇERSİZ — 0 scale o göstergeyi ölçek üzerinden sessizce devre
dışı bırakırdı). Beklenen anahtar seti tam eşleşmeli (eksik/fazla anahtar
fail-fast, HATA 5B2C'deki sessiz partial-merge deseni TEKRARLANMIYOR).
Weight'lerin toplamının tam olarak 1'e eşit olması ZORUNLU DEĞİL (engine
zaten mevcut göstergeler üzerinden renormalize ediyor).

Eksik gösterge renormalizasyonu (bir gösterge tamamen mevcut değilse,
yalnızca mevcut olanlar üzerinden ağırlıklandırma) DEĞİŞMEDİ — doğru
davranıyordu, HATA 16A'da zaten G (no issue) olarak sınıflandırılmıştı.

Bulgu #1 ve #2 (HATA 16A) için 41 yeni dedicated test eklendi (daha önce
`MacroAnalysisEngine`/`YahooMacroProvider`/`MacroSnapshotRepository` için
SIFIR test coverage vardı) — resolver validasyon testleri (eksik/partial/
extra-key/bool/string/NaN/±inf/negatif/tümü-sıfır), engine-seviyesi
config-öncesi-provider-fetch testi, available-weight-zero reprodüksiyonu
(HATA 16A'nın confirmed bug'ı, artık `MacroSnapshot` kaydedilmediği
kanıtlanmış), gerçek-nötr-0.0 persist testi, kısmi-veri renormalizasyon
tam sayısal testi, HATA 16A'nın audit örneğinin kilitlenmesi
(`macro_score == -13.75`, regresyon yok), config weight/scale source-
sensitivity testleri (resolved config'in gerçekten kullanıldığını,
`DEFAULT_WEIGHTS`/`DEFAULT_SCALES`'in sessizce gölgelenmediğini kanıtlıyor)
ve `YahooMacroProvider` için 20-bar pct_change/insufficient-history/
per-ticker partial-failure testleri (provider davranışı DEĞİŞMEDİ, yalnızca
test edildi). Üç rigor-check (eski fake-`0.0` davranışını, eski `get()`
partial-merge yolunu ve `DEFAULT_WEIGHTS`/`DEFAULT_SCALES` gölgelemesini
test dosyası içinde geçici olarak geri getirip ilgili testlerin gerçekten
FAIL ettiğini kanıtlayıp geri almak) production kodu hiç değiştirmeden
yapıldı.

Freshness/staleness (HATA 16A bulgu #3) ve macro provenance/config-hash
persistansı (HATA 16A bulgu #4) BİLEREK bu tickette ele alınmadı — ayrı,
gelecekteki HATA 16 ticket'ları için açık bırakıldı. `DecisionEngine`'in
eksik-macro renormalizasyon davranışı DEĞİŞMEDİ (regression testleriyle
doğrulandı). No deployment performed.

# HATA 16C — MACRO DATA FRESHNESS COMPLETE

HATA 16A bulgu #3'ü (`YahooMacroProvider` yalnızca `len(history) >=
window+1` kontrol ediyordu, gözlemin GÜNCEL olup olmadığına hiç bakmıyordu
— SILENT ACCEPT) kapatır. `MacroAnalysisEngine.analyze()` artık her
göstergeyi component hesaplamasına girmeden ÖNCE, gösterge bazında
(gösterge başına AYRI, tek bir global snapshot zaman damgası DEĞİL)
freshness kontrolünden geçirir.

Seçilen kural (`MAX_OBSERVATION_AGE_DAYS = 5`, tek/paylaşılan bir eşik —
gösterge başına ayrı değil, çünkü 6 gösterge de benzer günlük granülariteli
piyasa fiyatları): en son gözlemin analiz anına göre kaç TAKVİM günü eski
olduğuna bakılır (tam datetime farkı değil — günlük bar'lar bir seans
tarihini temsil eder, kesin bir kapanış saatini değil; her iki taraf da
önce UTC'ye normalize edilip `.date()` bazında karşılaştırılır, bu da
timezone-safe'dir ve gün sınırına yakın saatlerde yanlış sınıflandırmayı
önler). 5 gün: sıradan 2 günlük hafta sonunu (Cuma->Pazartesi = 3 takvim
günü) VE borsa tatiliyle birleşen bir hafta sonunu (ör. Perşembe kapanışı
-> Salı analizi = 5 takvim günü) rahatça kapsar, +1 gün pay bırakır; buna
karşın ~1 hafta veya daha eski gerçekten stale/cache'lenmiş bir feed yine
de YAKALANIR (excluded). Sınır DAHİLDİR (`age_days == 5` fresh, `== 6`
stale). Eksik/geçersiz `observed_at` (`None`) VEYA analiz anına göre
GELECEK tarihli bir gözlem asla "fresh" olarak KABUL EDİLMEZ — sessizce
güncelmiş gibi kullanılmaz. (HATA 16D netleştirmesi: tz-naive bir
`observed_at`'ın iki AYRI katmanda farklı bir karşılığı vardır —
provider'daki `_extract_observed_at()` naive bir `pd.Timestamp`'i asla
`None`'a çevirmez, UTC olarak KABUL EDER [aşağıya bakınız]; engine'deki
`_is_fresh_observation()` ise KENDİSİNE ayrıca savunma amaçlı bir
tz-naive-reddetme kontrolü taşır, ama gerçek `YahooMacroProvider` yolunda
bu kontrol asla naive bir değerle karşılaşmaz çünkü extraction katmanı
zaten her zaman tz-aware döner — bu kontrol yalnızca varsayımsal/gelecekte
naive bir `datetime`'ı doğrudan `_is_fresh_observation()`'a geçirebilecek
farklı bir provider'a karşı savunma amaçlıdır.)

Stale bir gösterge bu run için TAMAMEN ELENİR: sıfıra/nötre çevrilmez,
skorlanmaz, `MacroSnapshot.components`/`indicators`'a hiç girmez. Kalan
FRESH göstergeler üzerinden HATA 16B'nin available-weight renormalizasyonu
DEĞİŞMEDEN çalışır (stale bir göstergenin ağırlığı "kayıp" gibi
cezalandırılmaz). Kısmi fresh/stale karışık durumda (ör. 3 fresh + 3
stale) skor yalnızca fresh 3 üzerinden hesaplanır. TÜM göstergeler stale
ise (veya sadece fresh kalanların TAMAMI sıfır ağırlıklı kanallara denk
geliyorsa — HATA 16B'nin `NO_POSITIVE_WEIGHT_AVAILABLE` deseniyle
simetrik) `macro_score`/`confidence` UYDURULMAZ, hiçbir `MacroSnapshot`
kaydedilmez — HATA 16B'nin "0 = gerçek nötr, missing asla fake-neutral
olmaz" ilkesi korunur.

`YahooMacroProvider.get_indicator_changes()` artık her gösterge için
`observed_at` (UTC-aware `datetime`, `history.index`'in son elemanından
çıkarılır; tz-naive index UTC kabul edilir, tanınmayan tip için `None`)
döner. Bu, `MacroSnapshot.indicators` içinde (yeni bir paralel şema
icat edilmeden, mevcut generic `dict` alanı üzerinden) fresh olarak
KULLANILAN göstergeler için saklanır — bir operatör daha sonra hangi
gözlemlerin kullanıldığını görebilir. Tam provenance/config-hash
(HATA 16A bulgu #4) hâlâ AYRI, gelecekteki bir tickete ERTELENMİŞTİR — bu
ticket yalnızca gözlem zamanı görünürlüğünü ekler.

Confidence formülü DEĞİŞMEDİ; `completeness = len(components)/len(weights)`
zaten fresh gösterge sayısını doğal olarak yansıtıyor (doğrulandı, yeniden
tasarlanmadı). `DecisionEngine`, HATA 15, Technical/Event engine'leri,
HATA 16B'nin config/weight/scale semantiği DEĞİŞMEDİ. 17 yeni dedicated
test eklendi (9 `_is_fresh_observation()` unit testi + 5
`MacroAnalysisEngine.analyze()` freshness entegrasyon testi + 3
`YahooMacroProvider` observed_at/timezone testi) — üç rigor-check (freshness
kontrolünü tamamen bypass etmek, eşiği hafta sonu/Pazartesi senaryosunu
yanlış sınıflandıracak kadar sıkılaştırmak, eksik/gelecek zaman damgasını
sessizce fresh kabul etmek) geçici mutasyonlarla production kodu üzerinde
gerçekten yapılıp ilgili testlerin FAIL ettiği kanıtlanıp geri alındı. No
deployment performed.

# HATA 16D — MACRO PROVENANCE COMPLETE

HATA 16A bulgu #4'ü (`MacroSnapshot` hangi indicator gözlemleri/weights/
scales/provider/config sürümünün bir `macro_score` ürettiğini bağlamıyordu
— historical reproducibility gap) kapatır. Her yeni `MacroSnapshot` artık
YALNIZCA kendi persisted alanlarından — Yahoo'ya yeniden sorgu atmadan,
GÜNCEL Firestore config'i okumadan — yeniden üretilebilir.

Eklenen alanlar (`MacroSnapshot`, hepsi `None` varsayılanlı — eski kayıtlar
DESTRUCTIVE migration olmadan güvenle okunur, "provenance mevcut değil"
dürüstçe temsil edilir, eski weights/scales/provider/hash UYDURULMAZ):
`provider_id` (`YahooMacroProvider.PROVIDER_ID = "yahoo_macro_v1"` —
`SOURCE`'tan [`"yahoo_finance"`, insan-okunabilir] KASITLI OLARAK ayrı,
sürümlenebilir bir kimlik), `window` (`YahooMacroProvider.WINDOW = 20`,
provider'dan `getattr` ile okunur — engine `window=` argümanını AÇIKÇA
geçirmez, mevcut fake-provider testlerinin imzasını bozmamak için;
attribute yoksa `DEFAULT_PROVIDER_WINDOW=20` fallback), `max_observation_age_days`
(HATA 16C'nin `MAX_OBSERVATION_AGE_DAYS`'i — o run'da GERÇEKTEN kullanılan
değer), `resolved_weights`/`resolved_scales` (bu run için resolve edilmiş
TAM 6-anahtarlı config, Firestore doküman referansı DEĞİL — config zaman
içinde değişebileceğinden ham değerler gömülür), `macro_config_sha256`,
`macro_input_sha256`.

İki AYRI hash, iki AYRI soruya cevap verir: `macro_config_sha256` yalnızca
METODOLOJİ parametreleri (weights + scales + window + freshness-eşiği)
üzerinden — hangi piyasa verisi geldiğinden BAĞIMSIZ olarak iki run'ın AYNI
config'i kullanıp kullanmadığını tespit eder. `macro_input_sha256` daha
GENİŞ — provider kimliği + metodoloji parametreleri + resolved config +
GERÇEKTEN KULLANILAN (fresh) gözlem kümesi (`pct_change` + UTC'ye normalize
edilmiş ISO-8601 `observed_at` — aynı ANI temsil eden farklı UTC offset'li
timestamp'ler AYNI hash'i üretir) + `engine_version` üzerinden — bu
spesifik snapshot'ın tam bilimsel imzası. `created_at` gibi bilimsel
olmayan runtime metadata'sı hash'e HİÇ dahil edilmez. Her ikisi de proje-
genelindeki TEK paylaşılan kanonik ilkel (`app.research.canonical_hash.
content_sha256`, HATA 12N2A — sıralı anahtarlar + UTF-8 + `hashlib.sha256`,
Python `hash()` KULLANILMAZ) ile hesaplanır; yeniden kullanıldı, tekrar
icat edilmedi.

`ENGINE_VERSION` `"1.0.0"` → `"1.1.0"`'a BİLEREK artırıldı: HATA 16B
(fail-fast config resolution) ve HATA 16C (freshness exclusion) gerçek,
production skorlama davranışını değiştiren bilimsel değişikliklerdi ama
o ticket'ların kapsamı bir sürüm artışı içermiyordu; bu ticket (kendisi
provenance-only, skor DAVRANIŞI değiştirmiyor) bu BİRİKMİŞ sözleşme farkını
dürüstçe yansıtmak için TEK bir artış yapar — `"1.0.0"` damgalı eski bir
kayıt artık auto-seed/fake-neutral/freshness-kontrolsüz bir sözleşme
altında üretilmiş olarak okunmalı, `"1.1.0"` ve sonrası fail-fast+
freshness+tam-provenance sözleşmesini işaret eder. Çekirdek formül/
gösterge seti/yön semantiği DEĞİŞMEDİĞİ için major artış (`"2.0.0"`)
YAPILMADI.

tz-naive `observed_at` netleştirmesi (HATA 16C raporundaki çelişkili
ifadeyi düzeltir — yukarıdaki HATA 16C bölümüne inline not eklendi): iki
AYRI katman var. Provider katmanı (`_extract_observed_at()`) naive bir
`pd.Timestamp`'i ASLA `None`'a çevirmez — UTC olarak KABUL EDER. Engine
katmanı (`_is_fresh_observation()`) KENDİSİ ayrıca savunma amaçlı bir
tz-naive-reddetme kontrolü taşır, ama gerçek `YahooMacroProvider` yolunda
bu kontrol asla naive bir değerle karşılaşmaz (extraction her zaman
tz-aware döner) — yalnızca varsayımsal bir gelecekteki provider'a karşı
savunma. Kod/testler DEĞİŞMEDİ, yalnızca dokümantasyon netleştirildi.

`MacroSnapshotRepository.add()`'in append-only semantiği KORUNDU (update/
overwrite path eklenmedi). Aynı gözlemler + aynı config verildiğinde
`macro_score`/`confidence` HATA 16D öncesi/sonrası SAYISAL OLARAK
BİREBİR AYNI — bu ticket yalnızca alan ekler, skorlama matematiğini
DEĞİŞTİRMEZ (regresyon testleriyle doğrulandı: -13.75 örneği, kısmi-
gösterge -18.82 örneği, weight/scale duyarlılık örnekleri hepsi aynen
korundu). `DecisionEngine` DEĞİŞMEDİ — hâlâ yalnızca `macro_score`/
`macro_id` tüketiyor, yeni provenance alanları ona kablolanmadı (ihtiyaç
yok). 15 yeni dedicated test eklendi (`test_macro_provenance.py`) — üç
rigor-check (weights'i hash'ten çıkarmak, self-contained reproduction
yerine GÜNCEL/mutasyona uğramış config okumanın YANLIŞ bir skor ürettiğini
kanıtlamak, window/freshness-eşiğini hash'ten çıkarmak) geçici
mutasyonlarla gerçekten yapılıp ilgili testlerin FAIL ettiği kanıtlanıp
geri alındı (engine.py mutasyon-öncesi haliyle byte-birebir aynı olarak
doğrulandı). No deployment performed.

# HATA 17B — DECISION CLASSIFICATION PRECISION COMPLETE

HATA 17A audit'inin tek confirmed correctness bulgusu (round-before-
classify): `DecisionEngine.decide()` `final_score`'u `_classify()`'a
geçirmeden ÖNCE 2 ondalığa yuvarlıyordu (`round(raw, 2)` → `_classify
(rounded, ...)`). Örnek: raw=39.996 bilimsel olarak BUY eşiği 40.0'ın
ALTINDA (WEAK_BUY olmalı), ama `round(39.996, 2) == 40.0` olduğundan
YANLIŞLIKLA BUY'a sınıflandırılıyordu.

Düzeltme: sınıflandırma ARTIK ham (unrounded) bilimsel skoru kullanıyor
— `final_score = sum(scores[k]*weights[k] for k in available) /
available_weight` (round() YOK) → `decision = _classify(final_score,
thresholds)`. Persisted `AIDecision.final_score` de AYNI ham değerdir —
sınıflandırma ile persist edilen skor ARTIK farklı değerler OLAMAZ (ör.
final_score=40.00 yanında decision=WEAK_BUY gibi bir tutarsızlık
yapısal olarak imkânsız hale geldi). İkinci bir "raw_final_score"/
"rounded_final_score"/"display_score" alanı EKLENMEDİ — mevcut public
API/serileştirme katmanında `final_score` için var olan bir 2-ondalık
sunum sözleşmesi bulunmadığından (FastAPI/Pydantic ham float'ı olduğu
gibi döndürüyor), tek bir bilimsel `final_score` alanı yeterli.

Eşik dahil-etme/hariç-tutma semantiği (`>=`/`<=`, dört eşik: buy/
weak_buy/weak_sell/sell) DEĞİŞMEDİ. `_classify()`'ın kendisi hiç
değiştirilmedi — yalnızca ona geçirilen değerin ne zaman yuvarlandığı
değişti. Epsilon-tolerans HİÇ eklenmedi (ticket'ın açık yasağı) — bu
fixture'larda (39.996/14.996/-14.996/-39.996 vb.) gözlenen float
aritmetiği tam beklenen değerleri üretti, ekstra bir temsil artefaktı
GÖZLENMEDİ.

Confidence ("Sinyal Mutabakatı") formülünün KENDİSİ değişmedi, ama
final kararın yönü (NEUTRAL/POSITIVE/NEGATIVE) artık doğru
hesaplandığından, eşiğe çok yakın (weak_buy/weak_sell ↔ HOLD) durumlarda
agreement/confidence SONUCU da düzeliyor — bu formül değişikliği değil,
sınıflandırma düzeltmesinin doğal bir sonucu (kilitlendi: technical=
news=14.996/−14.996 çift-kanal fixture'ları, eski davranışta confidence
%0 üretirken düzeltmeyle %100 üretiyor, çünkü final yön artık doğru
NEUTRAL).

None/0.0 semantiği, weight renormalizasyonu ve `NO_POSITIVE_WEIGHT_
AVAILABLE` guard'ı DEĞİŞMEDİ (mevcut testler regresyon kanıtı).
`ExplanationEngine` ayrı bir kod yolu TAŞIMIYOR — aynı `DecisionEngine.
decide()`'ı çağırdığından düzeltmeyi otomatik devralıyor. Bildirim
tüketicileri (`fcm_sender.py`) yalnızca `decision.decision` etiketini
okuyor, skordan yeniden sınıflandırma YAPMIYOR — etkilenmedi.
`outcome_evaluator.dominant_factor()` da `final_score`'dan bağımsız
şekilde ham kanal katkılarını kıyaslıyor, yeniden sınıflandırma
YAPMIYOR — etkilenmedi.

Disclosed (bilinçli olarak bu ticket'ta ÇÖZÜLMEDİ) bir sunum endişesi:
`ExplanationEngine.explain()`'in özet metni ve `fcm_sender.py`'nin
bildirim gövdesi, final_score'u `f"{value:+.1f}"` (1 ondalık) ile
gösteriyor — ör. raw=39.996 "+40.0" olarak görünür, "ZAYIF AL" (WEAK_BUY)
etiketinin YANINDA biraz kafa karıştırıcı olabilir (görsel BUY eşiğine
çok yakın görünür). Bu, bilimsel depoyu/sınıflandırmayı BOZMADAN
çözülemeyecek, ayrı bir sunum kararı — bu ticket'ta bilinçli olarak
raporlanıp ÇÖZÜLMEDİ (kapsam dışı).

Eşik provenance/hash (hangi threshold config'in geçerli olduğunun
persisted kaydı) ve DecisionEngine seviyesinde cross-channel freshness/
as-of kontrolü (HATA 17A bulgu #2/#3) HÂLÂ AÇIK — ayrı, gelecekteki
ticket'lar. No deployment performed.

# HATA 17C — DECISION INPUT FRESHNESS COMPLETE

HATA 17A bulgu #3 (cross-channel as-of/freshness eksikliği): `Decision
Engine`, Technical/News/Macro kanallarını tek bir ortak "bu an" referansına
bağlamıyordu ve haftalarca eski, sessizce kırılmış bir scheduler'dan kalan
bir `MacroSnapshot`, tazesiyle AYNI şekilde tüketilebiliyordu. Bu ticket
SADECE tüketim-anı freshness/as-of güvenliğini kapatır — HATA 17B
(precision), HATA 15 (dedup/last-10-unique/source-reliability/causality)
ve HATA 16 (macro üretim-anı freshness/provenance) semantiği DEĞİŞMEDİ.

`decision_as_of`: `decide_for_asset()` (ve bağımsız olarak `Explanation
Engine.explain()`) her çalıştırmada TEK bir `datetime.now(timezone.utc)`
yakalar; bu AYNI değer HEM macro tüketim-tazeliği kontrolünde HEM haber
`as_of`/causality filtresinde HEM `AIDecision.created_at`/yeni
`decision_as_of` alanında kullanılır — macro/news için AYRI `now()`
çağrısı YOK (sınır tutarsızlığı riski yok, mutasyon-tabanlı bir rigor
check'le kanıtlandı: simüle edilmiş ikinci/sürüklenmiş bir zaman kaynağı
4 testi FAIL ettirdi). `decide_for_asset()`'in kendi `decision_as_of`'u
ile `ExplanationEngine.explain()`'inki BİLİNÇLİ olarak PAYLAŞILMAZ (ikisi
tasarım gereği bağımsız, her biri kendi "şu an"ı için — modül docstring'i).

Technical kanalı: her çağrıda LIVE yeniden hesaplandığı doğrulandı
(cache/TTL yok) — bu yüzden hiçbir yaş kontrolü EKLENMEDİ, gereksiz olurdu.

Macro tüketim-tazeliği (YENİ katman, HATA 16C'nin üretim-anı gösterge
tazeliğinden AYRI): `_is_macro_snapshot_fresh_for_consumption(created_at,
decision_as_of)` — `MacroSnapshot.created_at`, `decision_as_of`'a göre en
fazla `MAX_MACRO_SNAPSHOT_CONSUMPTION_AGE_DAYS=5` takvim günü eski
olabilir (sınır DAHİL, takvim-tarihi/UTC bazlı, HATA 16C ile AYNI stil).
5 gün: `MacroAnalysisEngine` sabit bir scheduler cadence'i OLMADAN talep
üzerine/API-tetiklemeli çalıştığından (repo'da macro için cron/Cloud
Scheduler config YOK — dürüstçe doğrulandı), istatistiksel bir cadence'ten
türetilemedi; bunun yerine HATA 16C'nin ZATEN gerekçelendirilmiş
muhafazakâr eşiğiyle KASITLI olarak AYNI büyüklük kullanıldı (bir
snapshot'ın "bu haftaki" görünümü temsil etmeyi bıraktığı an, tek bir
göstergenin stale olduğu andan daha az şüpheli değildir). Stale bir
snapshot ne silinir ne mutasyona uğrar (üretildiği an geçerliydi) — o
KARAR için `None`'a düşürülür, `macro_snapshot_id` katkı sağlamamış bir
referans olarak PERSIST EDİLMEZ, kalan kanallar HATA 5C3B'nin mevcut
renormalizasyonuyla (değişmedi) devam eder.

Haber `as_of`/causality: `select_recent_unique_news_analyses()`'e
opsiyonel `as_of` parametresi eklendi — HATA 15F `received_at`
(eligibility) `as_of`'tan SONRA olan kayıtlar, dedup/backfill'den ÖNCE
(HATA 15B FINAL'in "limit dedup'tan önce" hatasını farklı bir yüzeyde
yeniden açmamak için doğru sırada) elenir. `as_of=None` (varsayılan)
davranışı TAMAMEN korur. Ham kaydı çözümlenemeyen analizler as_of
filtresiyle ELENMEZ (17C-öncesi güvenli fallback korunur). LIVE haber
maksimum-yaş eşiği İSTENEREK EKLENMEDİ: haber sıklığı düzensiz/olay-
tabanlıdır (macro'nun sürekli piyasa fiyatı doğasının AKSİNE), repo'da
"haber geçerlilik süresi" kavramına dair hiçbir kanıt/dokümantasyon
bulunmadı ve düşük hacimli bir BIST hissesi için günler/haftalar haber
sessizliği NORMALDİR — bu koşullarda keyfi bir eşik icat etmek ticket'ın
kendi yasağını ("do not choose arbitrary numbers without documenting
why") ihlal ederdi; bu NET, dürüst bir N/A kararıdır, gizlenen bir
konu DEĞİL.

`ExplanationEngine.explain()` AYNI iki mekanizmayı (macro tüketim-tazeliği
+ haber `as_of`) KENDİ bağımsız `decision_as_of`'uyla çağırır — `Decision
Engine`/`ExplanationEngine` üyelik/temsilci paritesi (HATA 15E) freshness
filtresi altında da KORUNUR (parity testiyle kilitlendi).

`AIDecision.decision_as_of` (yeni, opsiyonel, `None` varsayılan — 17C-
öncesi kayıtlarda YOK, migration YOK) yalnızca "freshness hangi anda
değerlendirildi" sorusuna cevap verir — eşik/config provenance'ı (HATA
17A bulgu #2, hâlâ AYRI açık konu) KAPSAMAZ.

None/0.0 semantiği, weight renormalizasyonu, `NO_POSITIVE_WEIGHT_
AVAILABLE` guard'ı, HATA 17B'nin unrounded classification'ı ve HATA
15B/15C/15D/15E/16C/16D'nin TÜMÜ regresyon testleriyle DOĞRULANDI —
DEĞİŞMEDİ. 20 yeni dedicated test eklendi
(`test_decision_input_freshness.py`) — üç rigor-check (macro tüketim-
tazeliği filtresini bypass etmek, haber `as_of`/causality gate'ini bypass
etmek, tek `decision_as_of`'u simüle edilmiş sürüklenmiş bir ikinci zaman
kaynağıyla değiştirmek) geçici mutasyonlarla gerçekten yapılıp ilgili
testlerin FAIL ettiği kanıtlanıp geri alındı (dosyalar mutasyon-öncesi
haliyle byte-birebir aynı olarak doğrulandı). Eşik/config provenance
(HATA 17A bulgu #2) hâlâ AYRI, gelecekteki bir ticket. No deployment
performed.

# HATA 17D — DECISION CONFIG PROVENANCE COMPLETE

HATA 17A bulgu #2'nin kapanışı ve HATA 17 DecisionEngine correctness
serisinin (17A audit → 17B precision → 17C freshness → 17D provenance)
son ticket'ı. `final_score` zaten (weights+scores her zaman persist
edildiği için) reproducible'dı, ama `decision` LABEL'ı — threshold
config'e bağımlı — mevcut Firestore config'i okumadan yeniden
üretilemiyordu, çünkü HANGİ threshold'ların kullanıldığı hiç persist
edilmiyordu.

`AIDecision`'a iki yeni, opsiyonel (`None` varsayılan — 17D-öncesi
kayıtlarda YOK, destructive migration YOK, eski kayıt için "provenance
mevcut değil" dürüstçe temsil edilir, eski threshold/hash UYDURULMAZ)
alan eklendi:

- `decision_thresholds`: o kararda GERÇEKTEN kullanılan resolved
  `{buy, weak_buy, weak_sell, sell}` sözlüğü — bir config doküman
  referansı DEĞİL, ham değerlerin kendisi (Firestore config zaman
  içinde değişebilir).
- `decision_config_sha256`: yalnızca `{resolved decision_weights,
  resolved decision_thresholds}` üzerinden — config KİMLİĞİ, hangi
  skorların geldiğinden BAĞIMSIZ; `created_at`/`decision_as_of`/input
  skorları/doküman ID'leri kasıtlı olarak DAHİL DEĞİL (bunlar runtime/
  input provenance'tır, config kimliği değil). `app.research.
  canonical_hash.content_sha256` (proje-genelindeki TEK paylaşılan
  kanonik JSON/SHA-256 ilkeli, HATA 12N2A/16D ile AYNI) ile hesaplanır
  — sıralı anahtarlar + UTF-8, dict ekleme sırasından bağımsız, Python
  `hash()` KULLANILMAZ. Model-seviyesinde 64-küçük-harf-hex format
  validasyonu var (HATA 15D'nin `analyzed_text_sha256` deseniyle AYNI),
  `None` her zaman serbest.

`decision_input_sha256` (ayrı, daha geniş bir hash) KASITLI OLARAK
EKLENMEDİ: bu hash'in bağlayacağı HER alan (technical/news/macro
skorları+ID'leri, decision_as_of, weights, thresholds, engine_version)
zaten ayrı ayrı, doğrudan, dönüşümsüz alanlar olarak persist ediliyor
(macro'nun `indicators` sözlüğünün aksine — orada normalize edilmiş bir
iç-içe yapı vardı, hash gerçek bir değer katıyordu). İkinci bir hash
burada yeni bir reproducibility yeteneği eklemezdi, yalnızca zaten
mevcut alanları tekrar ederdi.

Weight snapshot semantiği doğrulandı (değişmedi): `technical_weight`/
`news_weight`/`macro_weight` HER ZAMAN (17D-öncesi dahil) config-
resolution-sonrası ama availability-renormalization-ÖNCESİ configured
değerlerdir — teknik-only bir kararda bile persisted weight alanları
HALA orijinal `{0.5, 0.3, 0.2}`, çökmüş effective-1.0 DEĞİL. Bu, geçmiş
reproduction'ın kendi renormalizasyonunu persisted configured
weight'lerden doğru şekilde yapabilmesini sağlar.

`ENGINE_VERSION`: HATA 5C3B'nin `"1.1.0"`'ı sonrasında HATA 17B
(round-before-classify düzeltmesi) ve HATA 17C (macro tüketim-tazeliği +
haber as_of/causality) ikisi de GERÇEK bilimsel/uygunluk davranışı
değiştirdi ama versiyon bump'lamadı (o ticket'ların kapsamı buydu,
geriye dönük düzeltilmiyor). 17D bunun üstüne yalnızca provenance
alanları ekliyor (davranış değişikliği YOK) ama "düzeltilmiş metodoloji"
(17B+17C+17D) altında üretilen kararları eski `"1.1.0"` kararlarından
ayırt etmek için TEK, kasıtlı bir yakalama bump'ı yapıldı: `"1.2.0"`.

Reproducibility kanıtlandı: final_score/decision/confidence/channel_
completeness'ın TAMAMI, yalnızca persisted `AIDecision` alanlarından
(hiçbir `SystemConfigRepository`/provider erişimi OLMADAN) yeniden
üretilebiliyor — normal 3-kanal (32.0/WEAK_BUY), 2-kanal (45.0/BUY),
technical-only (renormalizasyon persisted TAM configured weight'lerden
doğru yapılıyor), genuine-zero (0.0/HOLD), ve HATA 17B'nin near-
threshold örneği (39.996/WEAK_BUY, threshold snapshot buy=40.0 içeriyor)
dahil. Load-bearing invariant testi: CONFIG A ile bir karar persist
edilip SONRA fake config CONFIG B'ye mutasyona uğratıldığında,
reproduction (yalnızca persisted kayıttan) HALA CONFIG A sonuçlarını
üretiyor — mevcut config değişiklikleri geçmiş kararların audit'ini
ETKİLEMEZ (rigor check'le de doğrulandı: reproduction CURRENT config'i
okusaydı `BUY` üretirdi, doğrusu `WEAK_BUY`).

None/0.0 semantiği (unavailable kanal ASLA 0 olarak serialize edilmez),
weight renormalizasyonu, `NO_POSITIVE_WEIGHT_AVAILABLE` guard'ı, HATA
17B'nin unrounded classification'ı, HATA 17C'nin freshness/as-of
davranışı ve HATA 15/16 serisinin TAMAMI regresyon testleriyle
DOĞRULANDI — DEĞİŞMEDİ. `ExplanationEngine` "her zaman canlı" mimarisine
dokunulmadı (bu ticket yalnızca PERSISTED `AIDecision`'ı auditable
yapar, geçmiş explanation replay'i denemez); notifications/outcome_
evaluator yalnızca `decision.decision` (persisted label) okur, yeni
alanlardan etkilenmez. `AIDecisionRepository` append-only semantiği
(no update/delete) korundu.

17 yeni dedicated test eklendi (`test_decision_config_provenance.py`) —
iki rigor-check (config hash'inden threshold'ları çıkarmak, reproduction'ı
persisted snapshot yerine current config okuyacak şekilde mutasyona
uğratmak) geçici mutasyonlarla gerçekten yapılıp ilgili testlerin FAIL
ettiği kanıtlanıp geri alındı; üçüncü rigor-check (unavailable kanalı 0
olarak serialize etmek) HATA 15/16/17 serisinin TAMAMINDAKİ None-vs-zero
testlerinin geniş çaplı FAIL ettiğini kanıtladı (beklenenden de güçlü bir
kanıt). No deployment performed.

# HATA 18B — THRESHOLD-SAFE SCORE PRESENTATION COMPLETE

HATA 18A audit bulgu #1'in (highest-priority) düzeltmesi. `ExplanationEngine`
özeti ve `fcm_sender.py` bildirim body'si, `AIDecision.final_score`'u sabit
`:+.1f` (1 ondalık) ile gösteriyordu — bu, eşiğe yeterince yakın bir skoru
YANLIŞ katmana yuvarlayabiliyordu: final_score=39.996 (bilimsel olarak
WEAK_BUY, HATA 17B'nin düzelttiği ham-skor sınıflandırmasıyla DOĞRU) "+40.0"
gösteriyordu — bu, kullanıcıya BUY eşiğini geçmiş gibi GÖRÜNÜYORDU, tam da
HATA 17B'nin bilimsel katmanda kapattığı çelişkinin sunum katmanında geri
sızması.

`AIDecision.final_score`'un KENDİSİ (scientific value, API serialization
dahil) HİÇBİR ŞEKİLDE değişmedi — bu ticket SADECE insan-okunur metin
(Explanation özeti, FCM bildirim body'si) katmanını değiştirir.

Yeni paylaşımlı sunum yardımcısı: `app.utils.decision_score_format.
format_decision_score(final_score, decision, decision_thresholds)`.
`ExplanationEngine` ve `fcm_sender.py` ARTIK YALNIZCA bu fonksiyonu
kullanır — ikisinin de bağımsız `:+.1f` (veya başka sabit hassasiyetli)
formatlaması YOK; iki sunum yüzeyi bir daha SESSİZCE ayrı mantığa
sürüklenemez (dedicated parity testiyle kilitlendi).

**Adaptif hassasiyet** (sabit 2/3 ondalığa geçmek YERİNE — ticket'ın
açıkça yasakladığı sahte çözüm, bir skor her zaman herhangi bir sabit
hassasiyette bile eşiğe yeterince yakın olabilir): 1 ondalıktan başlar,
gösterilecek string'i DecisionEngine'in TEK gerçek sınıflandırma
mantığıyla (`_classify()` — İKİNCİ KEZ YAZILMADI, doğrudan `app.engines.
decision.engine`'den import edilir) yeniden sınıflandırıp persisted
`decision` ile eşleşene kadar hassasiyeti artırır (`_MAX_ADAPTIVE_DECIMALS
= 6`). Sınırlı deneme dizisi tükenirse (patolojik durum), `final_score`'un
TAM, round-trip-safe temsiline (`repr()`) düşer — bu, `decision`'ı ÜRETEN
değerin ta kendisi olduğundan, sınıflandırması TANIM GEREĞİ eşleşir
(epsilon/tolerans hack'i YOK).

Eşikler DAİMA persisted `AIDecision.decision_thresholds` (HATA 17D)
snapshot'ından gelir — canlı `SystemConfigRepository`'den ASLA okunmaz
(config drift, zaten hesaplanmış bir kararın sunumunu SESSİZCE
değiştirmemeli). **Legacy (17D-öncesi) kayıtlar**: `decision_thresholds
=None` — güncel eşikler UYDURULMAZ, doğrudan `final_score`'un round-trip-
safe temsili gösterilir (ne config lookup, ne crash, ne sabit lossy 1-
ondalık yuvarlama).

Kozmetik: `-0.0` (ör. final_score=-0.04, 1 ondalıkta) "+0.0"'a normalize
edilir — bilimsel işaret hiçbir şekilde değişmez, yalnızca zaten sıfıra
yuvarlanmış bir STRING üzerinde çalışır; +0.04/-0.04 ikisi de meşru HOLD/
nötr bandında, bu bir eşik-çelişkisi DEĞİL. Normal skorlar (32.0, 45.0,
0.0, -18.5) ve tam eşik değerleri (score==buy/weak_buy/weak_sell/sell)
kompakt 1-ondalık formatta kalmaya devam eder — adaptif hassasiyet
yalnızca gerçekten gerektiğinde tetiklenir.

Üç rigor-check GERÇEKTEN yapıldı: (A) eski sabit `:+.1f`'e dönüldü →
39.996 dahil 8 test FAIL etti, geri alındı. (B) koşulsuz sabit `:+.2f`'e
(fallback'siz) dönüldü → 39.996 dahil 12 test FAIL etti (ilk denemede
yalnızca kompaktlık testleri FAIL etmişti çünkü güvenli fallback hâlâ
devredeydi — bu, rigor check'in KENDİSİNİN de yeterince agresif olması
gerektiğini gösterdi, ikinci, daha sert mutasyonla asıl eşik-güvenliği
testleri de FAIL ettirildi). (C) `fcm_sender.py` eski formatlamaya
döndürülüp `ExplanationEngine` yeni yardımcıda bırakıldı → parity testi
(round OLMAYAN bir threshold config'i — buy=45.04 — kullanılarak GERÇEK
bir escalation senaryosuyla) FAIL etti ("+45.04" beklenirken "+45.0"
alındı). Üçü de geri alındı, suite yeniden yeşil.

16 yeni dedicated test eklendi (`test_decision_score_format.py`) — HATA
17B/17C/17D regresyonu, tüm dört eşik sınırı (buy/weak_buy/weak_sell/
sell) için hem "az altı/üstü" hem "tam eşit" fixture'ları, yük taşıyan
display-classification-parity invariant'ı (her fixture için gösterilen
string parse edilip AYNI eşiklerle sınıflandırıldığında persisted
`decision` ile TAM eşleşir), legacy no-threshold fallback, config-drift
bağımsızlığı, ve Explanation/FCM parity dahil. No deployment performed.

# HATA 18C — DECISION-BOUND EXPLANATION COMPLETE

HATA 18A audit bulgu #2'nin (`GET /decisions/{symbol}/explanation`'ın her
zaman YENİ bir canlı karar hesapladığı, hiçbir kimlik/as-of maruz
bırakmadığı) düzeltmesi ve HATA 18 ExplanationEngine correctness serisinin
(18A audit → 18B sunum → 18C kimlik) KAPANIŞ ticket'ı.

`ExplanationEngine.explain(asset, decision_id=None)` artık İKİ AYRI,
mimari olarak ayrık mod sunar:

- **`decision_id=None`** (varsayılan) — `_explain_current()`: MEVCUT canlı
  yeniden-hesaplama davranışı TAM olarak korunur (canlı Technical, HATA
  17C tazelik-kontrollü Macro, HATA 15E/15F paylaşımlı seçici ile
  causality-valid News, `DecisionEngine.decide(persist=False)`). Var olan
  HİÇBİR çağıran (route dahil) etkilenmez — geriye dönük uyumluluk
  zorunluydu, test edildi. Tek katkı: yanıt artık kendi `decision_as_of`'unu
  ve `mode: "live"`'ı da (additive alanlar) sızdırıyor — daha önce
  (18C-öncesi) bu hiç maruz bırakılmıyordu (HATA 18A bulgu #2).

- **`decision_id=<id>`** — `_explain_decision()`: persisted `AIDecision`'ın
  gerekçesini üretir. `final_score`/`decision`/`confidence`/
  `channel_completeness`/`weights`/`decision_thresholds` BURADA ASLA
  yeniden hesaplanmaz — `AIDecision`'ın kendi alanları KOŞULSUZ kullanılır
  (`DecisionEngine.decide()`/`decide_for_asset()`, canlı
  `TechnicalAnalysisEngine`, paylaşımlı haber seçici,
  `MacroSnapshotRepository.get_latest_with_id()` bu modda HİÇ çağrılmaz —
  mock-tabanlı "no recomputation" testiyle kilitlendi).

Referanslı Technical/News/Macro DETAY kayıtları (zenginleştirilmiş gerekçe
metni için) yeni salt-okunur repository metotlarıyla (`AIDecisionRepository.
get_by_id`, `TechnicalAnalysisRepository.get_by_id`,
`MacroSnapshotRepository.get_by_id`, mevcut `NewsAnalysisRepository.
get_by_news_id`) TEK TEK, `AIDecision`'ın kendi ID'leriyle geri çağrılır —
BUGÜNKÜ "en son"/tazelik durumundan tamamen BAĞIMSIZ. Bir detay kaydı
artık bulunamıyorsa (legacy/silinmiş) CANLI/GÜNCEL veriyle SESSİZCE İKAME
EDİLMEZ — bunun yerine persisted skorla birlikte açık bir "ayrıntılı kayıt
artık erişilebilir değil" notu eklenir; persisted `AIDecision` zaten
final_score/decision/confidence/completeness için YETERLİ olduğundan hiçbir
detay-kaydı eksikliği bu modu başarısız KILMAZ. `macro_score`/`news_score
is None` (kanal hiç kullanılmadı) ile "detay kaydı artık erişilemiyor"
(kanal kullanıldı ama zenginleştirilmiş kayıt kayıp) AÇIKÇA ayrı notlarla
temsil edilir — None-vs-zero doktrini bu modda da korunur (macro_score=None
asla "makro nötr" olarak gösterilmez).

Bilinmeyen `decision_id` veya sembol-uyuşmazlığı (`decision.asset !=
route symbol`) → `LookupError` → API'de 404 — canlı moda SESSİZCE
düşülmez (bu, bir kimlik hatasını gizlerdi). Route: opsiyonel
`decision_id` query parametresi eklendi (`GET /decisions/{symbol}/
explanation?decision_id=...`), eski çağrı şekli (parametre yok) davranış
DEĞİŞTİRMEDEN çalışır.

Üç rigor-check GERÇEKTEN yapıldı (mutasyon → test FAIL → geri alma →
suite yeşil): (A) `decision_id`'yi yok sayıp sabit bir kayda bakıldı →
D1-vs-D2 kimlik testi FAIL etti. (B) persisted `news_analysis_ids` yerine
canlı paylaşımlı seçici kullanıldı → news-drift testi, fake repo'nun
kendi guard'ı üzerinden FAIL etti. (C) `macro_snapshot_id` yerine
`get_latest_with_id()` kullanıldı → macro-drift testi aynı şekilde FAIL
etti. Üçü de geri alındı, dosya mutasyon-öncesiyle byte-birebir aynı
doğrulandı.

14 yeni dedicated test eklendi (`test_explanation_decision_bound.py`):
exact decision-ID kimliği (D1≠D2/"latest"), karar-sonrası piyasa
değişikliğine bağışıklık, canlı modun GERÇEKTEN değişmediği (backward-
compat kilidi), config-drift bağımsızlığı, news-drift ve macro-drift
bağımsızlığı, `macro_snapshot_id=None`'ın güncel bir snapshot varken bile
"kullanılmadı" kalması, eksik detay-kaydında zarif bozulma (skor/etiket/
confidence/completeness DEĞİŞMEDEN), yanlış-sembol reddi, bilinmeyen-ID
reddi (canlı fallback YOK), iki modun kimlik metadatasıyla ayırt
edilebilirliği, "no recomputation" mock-tabanlı regresyon, HATA 18B
threshold-safe sunum regresyonu (decision-bound modda da 39.996 asla
"+40.0" göstermez), ve None-vs-zero regresyonu.

**Bilinçli kapsam sınırı**: açıklama METNİNİN kendisi bu ticket'ta HÂLÂ
persist/versiyonlanmıyor (yalnızca zaten var olan `AIDecision` provenance'ı
kullanılıyor) — bu, HATA 18A bulgu #3'ün (explanation reproducibility gap)
TAM kapanışı değil, yalnızca historical FACT tutarlılığının (skor/etiket/
girdi-üyeliği) garantilenmesidir; bu, 18C'nin kapsamı için YETERLİDİR.
`ExplanationEngine`'in decisions API'de dedicated bir HTTP-seviyeli test
dosyası (`test_decisions_api.py` tarzı) hâlâ yok (HATA 18A'da da
disclosed edilmiş bir boşluk) — route'un kendisi ince bir sarmalayıcı
olduğundan ve tüm gerekli senaryolar engine-seviyesinde kilitlendiğinden,
bu ticket'ta yeni bir API-test altyapısı kurulmadı.

No deployment performed.

# TECHNICAL V2-R1 — AKTİVASYON SÖZLEŞMESİ YEREL KAPANIŞ (24.09.2026)

Durum: YEREL OLARAK TAMAMLANDI, COMMIT EDİLMEDİ. Canlı işlem yok.

Yerelde tamamlananlar:
- Read-only, fail-closed V2 pre-activation readiness kapısı + CLI
  (`technical_v2_readiness.py`; LOCAL/PRODUCTION modları).
- Aktivasyon orkestrasyonu (`technical_v2_activation.py`): create-only
  kilit + INITIAL olay; aynı isteğin tekrarı (ALREADY_ACTIVATED, yalnızca
  mevcut kaydı bildirir), kısmi kurtarma (tam eşleşen aday kilit + taze
  readiness), yarışı kaybeden kilidin silinmemesi ve yetki vermemesi.
- Revision geçişi: mevcut `LOCK_AUTHORIZED` sözleşmesiyle, INITIAL kilitten
  yalnızca runtime revision'ı farklı kilit; INITIAL ve holdout başlangıcı
  değişmez. Eski kilidin yetkisini geri alma sözleşmede tanımsız.
- Holdout başlangıcı tek yerde (`technical_holdout.py`): protokol
  `holdout_status.activation_note` kuralı -- INITIAL olayın Firestore
  create_time'ından KESİNLİKLE sonra market open'ı (10:00 Europe/Istanbul)
  olan ilk BIST seansı. Attempt execution claim'den önce uygular.
  Gerçek create_time takvim dışındaysa ACTIVATED_HOLDOUT_START_UNDETERMINABLE
  (başarı değil; kayıt silinmez, başlangıç kaymaz).
- Proje kimliği: açık FIREBASE_PROJECT_ID == beklenen == Firestore
  istemcisinin projesi; aksi halde hiçbir okuma/yazma yok.

Son bildirilen doğrulama: tam backend regresyonu 2587 passed, 0 failed.
Sahte veritabanı testleri gerçek Firestore eşzamanlılığının kanıtı değildir.

Commit edilmemiş dosyalar (backend/):
- değişen: app/repositories/technical_v1_activation_event_repository.py,
  app/research/technical_v1_attempt_execution.py,
  app/research/technical_v2_readiness.py,
  tests/test_technical_v1_activation_event_repository.py,
  tests/test_technical_v1_attempt_execution.py,
  tests/test_technical_v1_finalization_orchestration.py,
  tests/test_technical_v2_readiness.py
- yeni: app/research/technical_holdout.py,
  app/research/technical_v2_activation.py, tests/test_technical_holdout.py,
  tests/test_technical_v2_activation.py

Canlı kontroller NOT RUN: production readiness, Firestore projesi, runtime
kimliği, canlı scoring config, Docker imaj fingerprint'i, gerçek create_time
ve Firestore eşzamanlılığı.

Bekleyen kararlar:
1. BEKLEYEN MADDE — 2027 BIST takvimi / protokol-manifest geçişi
   (projenin geri kalanını durdurmaz):
   - `trading_calendar.py` metodoloji fingerprint kapsamında; 2027'yi
     eklemek fingerprint'i, dolayısıyla manifest ve protokol bağını değiştirir.
   - Resmi 2027 Pay Piyasası Tatil Tablosu 24.09.2026 tarihli aramada
     BULUNAMADI (resmi tatiller sayfası 2012-2026'yı listeliyor; tahmin
     edilen tek bir PDF URL'si 404 verdi). Bu, yayımlanmadığının kesin
     kanıtı DEĞİLDİR.
   - "TECHNICAL_V2_PROTOCOL_V2 + manifest r2" yalnızca ÖNERİDİR; protokol/
     manifest değişikliği ONAYLANMADI.
   - AÇIK TASARIM KARARI: 2027'yi eklemek mevcut 6 aylık pencereye yardımcı
     olabilir, ancak üst bitiş tarihi olmayan bir deneyde ileriki her yıllık
     takvim güncellemesi aynı fingerprint/sürüm sorununu yeniden doğurur.
     Kalıcı çözüm bu turda tasarlanmadı/uygulanmadı.
   - Farklı protokollerin kanıtları BİRLEŞTİRİLMEZ.
   - TECHNICAL_V2_PROTOCOL_V1 bu turda aktive EDİLMEDİ.
2. Çağrı yolu: internal router'daki "aktivasyon uç noktası yok" sınırının
   kaldırılıp kaldırılmayacağı (öneri: ayrı secret'lı internal route,
   revision tag URL'i üzerinden tek seferlik manuel çağrı).
3. PROD-3: deploy/billing onayı (DEFERRED — BILLING REQUIRED).

evidence_capture_ready = false
prospective_holdout_started = false
effective_holdout_start = null

# EVENT INTELLIGENCE — MERKEZİ OPENAI BÜTÇE KONTROLÜ YEREL KAPANIŞ (24.09.2026)

Durum: YEREL OLARAK TAMAMLANDI, COMMIT EDİLMEDİ, DEPLOY EDİLMEDİ.

- Merkezi rezervasyon/uzlaştırma (`app/engines/event_intelligence/budget.py`,
  `app/repositories/event_intelligence_budget_repository.py`): her OpenAI
  çağrısından hemen önce Firestore transaction'ıyla ihtiyatlı rezervasyon,
  sonra gerçek `usage` ile uzlaştırma (kullanım kaydı rezervasyon kimliğiyle,
  tek sefer). Günlük job ve `POST /news/{symbol}/analyze` aynı kapıdan geçer.
  Bütçe anlamı değişmedi: tüm zamanlar toplamı; defter ilk kullanımda mevcut
  `token_usage_logs` toplamıyla BİR KEZ tohumlanır.
- Belirsiz çağrılar (timeout/hata/usage yok) ve çöken süreçlerin rezervasyonları
  serbest bırakılmaz; tekrar deneme yeni rezervasyon açar.
- OpenAI SDK otomatik tekrarları kapatıldı (`max_retries=0`); kurulu openai
  3.2.0'ın varsayılanı tek rezervasyon altında 3 HTTP denemesiydi.
- İstekte `max_completion_tokens=4096` gönderiliyor (rezervasyon sınırı için).

Son bildirilen doğrulama: tam backend regresyonu 2609 passed, 0 failed.
Sahte Firestore testleri gerçek Firestore eşzamanlılığının kanıtı değildir.

Sınır: rezervasyon YEREL bir tahmindir (UTF-8 bayt + 256 girdi varsayımı,
4096 çıktı sınırı, yerel fiyat tablosu) — gerçek sağlayıcı faturasının üst
sınırı DEĞİLDİR. Güvence yalnızca ortak defteri kullanan çağrılar içindir;
eski revision, yerel geliştirme backend'i veya aynı OpenAI anahtarını
kullanan başka herhangi bir çağrı defter dışında kalır.

Bekleyen: operasyonel geçiş (eski ücretli yolların kapatılması, eski anahtarın
iptali, sağlayıcı kullanımıyla mutabakat, defterin ilk oluşumu) ve açılış
mutabakatı için eksik mekanizma kararı. Billing kapalı; deploy yok.

## Ek (24.09.2026): Bütçe mutabakat düzeltmesi CLI'ı + düzeltilmiş geçiş planı

Yerel olarak eklendi (commit/deploy yok): `app/engines/event_intelligence/budget_adjustment.py`
(yalnızca `python -m` ile çalışan operatör CLI'ı, endpoint yok). Varsayılan dry-run; yazma
yalnızca `--apply` ile. Pozitif, en fazla 6 ondalıklı tutarı (mikro-USD) `committed_usd`'ye
ekler; düzeltme kaydı ve defter güncellemesi tek transaction'dadır; aynı kimlik+içerik tekrar
eklenmez, aynı kimlik+farklı içerik reddedilir. Defter yoksa ortak tohumlama mantığıyla
geçmiş `token_usage_logs` toplamı bir kez eklenir. Tutar otomatik türetilmez (bkz. modül
docstring'i); bu kesin fatura eşitliği değildir. Son doğrulama: 2628 passed.

Geçiş planı (UYGULANMADI). Eski anahtarın iptali gelecekteki çağrıların KABULÜNÜ engeller;
kabul edilmiş çağrıların tamamlandığını veya sağlayıcı kullanım raporlarının kesinleştiğini
KANITLAMAZ. Instance sayısı ve kullanım raporları destekleyici kanıttır, mutlak tamamlanma
kanıtı değildir; geç kesinleşen kullanım sonradan yeni kimlikli ek bir pozitif düzeltmeyle
işlenir.

1. Önkoşul: kararlar alındı, kod commit'lendi. İşlem: billing KAPALIYKEN eski OpenAI anahtarını
   OpenAI tarafında iptal et (eski revision, yerel .env ve bilinmeyen girişler için kabul
   penceresini kapatır). Doğrulama: anahtar listesinde iptal görünür. Başarısızsa: dur, billing açma.
2. Önkoşul: 1. İşlem: yeni anahtar oluştur (henüz hiçbir yere bağlanmaz). Başarısızsa: dur.
3. Önkoşul: 1-2. İşlem: billing'i aç. Doğrulama: billingEnabled=true. Eski revision ücretli
   çağrı yapmaya çalışırsa iptal edilmiş anahtarla reddedilir. Başarısızsa: dur (billing'i
   otomatik kapatma adımı önerilmez).
4. İşlem: scheduler'ı duraklat. Doğrulama: PAUSED. Başarısızsa: dur.
5. İşlem: bekleme payı + 00029 instance sayısı 0 + iptal sonrası eski anahtarda kullanım
   görülmemesi (destekleyici kanıt). Başarısızsa: bekle.
6. İşlem: sağlayıcı kullanımı ile defterde sayılacak tutarı (log toplamı + tutulan
   rezervasyonlar) aynı dönem/kapsam için karşılaştır; fark varsa CLI'ı önce dry-run, sonra
   --apply ile çalıştır. Doğrulama: çıktı APPLIED/ALREADY_APPLIED. Başarısızsa: dur.
7. İşlem: yeni anahtarı yeni secret sürümü olarak ekle; yeni kodu bu sürüme sabitleyerek
   --no-traffic deploy et; tag URL'de yalnızca /health. Başarısızsa: trafik 00029'da kalır
   (anahtarı iptal edilmiş; ücretli çağrı kabul edilmez).
8. İşlem: trafiği açıkça yeni revision'a geçir. Doğrulama: defter mevcut, değerler dry-run
   özetiyle tutarlı. Başarısızsa: aşağıdaki rollback.
9. İşlem: scheduler'ı yeniden aç. Doğrulama: job çıktısında news_analysis_stop_reason.

Rollback: eski imajı anahtarsız çalıştırmak (diğer işlevler açık, ücretli yollar kapalı)
DOĞRULAMA BEKLİYOR — anahtarsız eski imajın diğer işlevleri çalıştırdığı ve imajda .env
olmadığı henüz doğrulanmadı. Defter silinmez/sıfırlanmaz; açık/belirsiz rezervasyonlar
korunur. Eski sürümde ücretli çağrı gerçekleşirse yeniden geçiş öncesi ayrıca mutabakat
(CLI ile ek düzeltme) gerekir.

Geçiş planı açıklamaları (24.09.2026):
- Eski OpenAI anahtarının iptali AYRICA onay gerektirir; anahtarın başka
  uygulamalarda kullanılıp kullanılmadığı bilinmeden uygulanmaz.
- Anahtarsız eski imaj doğrulanmış bir rollback hedefi DEĞİLDİR.
- Yeni secret sürümü yayımlanırken eski revision'ın `latest` referansı
  üzerinden yeni anahtarı alması önlenmelidir (00029 şu an
  `openai-api-key:latest` referansı taşıyor); sürüm bağları canlıda
  doğrulanmadan geçiş yapılmaz.
- Bu plan henüz uygulanmış veya tamamen doğrulanmış DEĞİLDİR.

# GÜNCEL DURUM ÖZETİ (24.09.2026) — commit edilmemiş yerel çalışmalar

Önceki bölümlerdeki test sayıları kendi tarihlerindeki sonuçlardır; son durum:
- Backend: son bildirilen tam regresyon 2628 passed, 0 failed.
- Flutter: son bildirilen 99 passed, `flutter analyze` temiz.
- Gerçek cihaz kontrolü, gerçek Firestore eşzamanlılığı ve canlı geçiş: NOT RUN.
- Billing: son salt-okunur kontrolde (24.09.2026) bağlı hesap var, billingEnabled=false.
- Hiçbir yeni çalışma deploy edilmedi; canlı trafik ai-investment-backend-00029-bmf'de.
- Technical V2 aktivasyonu, 2027 takvim/protokol kararı ve çağrı yolu kararı bekliyor.

Yerel commit aşaması (24.09.2026): yukarıdaki "commit edilmedi" ifadeleri o anki
tarihsel durumdur. Çalışmalar master üzerinde yalnızca YEREL olarak commit edildi:
`8c0ee31` (Technical V2-R1), `f9d7a1c` (fiyat sekmesi yenileme), `b26fd00`
(EventIntelligence bütçe + mutabakat CLI'ı); bu günlük notları ayrı bir belge
commit'indedir. Push yapılmadı. Deploy ve canlı doğrulama durumları değişmedi.

# MARKET-RISK-1 — Fiyat temelli erken risk modeli (keşifsel, 28.09.2026)

Tek deneme: 6 fiyat özelliği + StandardScaler + L2 lojistik regresyon (C=1), 2024 eğitim,
2025 kronolojik değerlendirme (2025 daha önce görüldüğü için bağımsız holdout DEĞİL).
Hedef: T+1..T+10 seans kapanışlarından biri <= -%10. Çıktı: `backend/app/research/
market_risk_shadow/runs/early_risk_model_20260928/`. Model yakınsadı.
- İlk AL günlerinde (n=903) 152 sert düşüşün 22'si işaretlendi; 110 uyarının 88'inde
  hedef düşüş görülmedi. İlk günlerde Brier sabit referanstan kötü (0,1455 vs 0,1426).
- Tüm AL günlerinde AP 0,238 vs sabit 0,196 (zayıf ayrım; gözlemler örtüşür).
- Eşik kayması: eğitim skorlarının %90 persentili 2025'te ~%21 uyarı oranı üretti.
- Üretime ALINMADI; eşik/özellik/model değiştirilerek yeniden eğitilmedi.

# MARKET-RISK-1 — Araştırma kapanışı (28.09.2026)

- Mevcut gölge risk kuralları erken uyarı kapsamı bakımından yetersiz kaldı: sonradan sert
  düşen AL günlerinin çoğunda T günü uyarı yoktu; hisse kuralı çoğunlukla başlamış düşüşe
  kapanışta tepki verdi (bkz. sharp_drop_coverage.json).
- Fiyat temelli lojistik model keşifsel düzeyde zayıf ayrım gösterdi; üretime alınmadı.
- Hacim deneyi (dvol_20_100) önceden kaydedilmiş karşılaştırma koşulunu karşılamadı:
  EK_ISARET_YOK (runs/volume_experiment_20260928/result.json).
- Bu sonuçlar yalnızca denenen özellikler, model, örneklem (dondurulmuş 100 sembol,
  2024 eğitim/2025 değerlendirme) ve hedef (10 seansta <= -%10) için geçerlidir;
  "hacim işe yaramaz" veya "düşüş tahmin edilemez" genellemesi yapılmaz.
- Sınırlamalar: 2024 teknik karar kapsamı %61,5; XU100 boşlukları; sıfır hacim kuralı
  2024 eğitim örnekleminin ~1/3'ünü dışladı; 2025 bağımsız holdout değildir.
- Eski deneyler, kod ve çıktılar korunmuştur. Risk filtresi gölge modunda kalır.

# PORTFÖY — Salt-okunur pozisyon inceleme modülü (28.09.2026)

- `backend/app/services/portfolio/position_review.py` + yerel JSON CLI; üretim uç noktalarına,
  `pnl_calculator`'a ve karar motoruna bağlı DEĞİL. Otomatik AL/SAT üretmez.
- Değerleme: beklenen son tamamlanmış seans (takvim + 18.00 + 30 dk, saat dilimli
  `evaluated_at`). `retrieved_at` kesinleşmeden önceyse INCOMPLETE_BAR; `retrieved_at` /
  `source_updated_at` değerlendirmeden sonraysa OBSERVED_AFTER_EVALUATION. Anlamı bilinmeyen
  `source_timestamp` yalnızca gösterilir.
- `price_basis` ve kurumsal işlem kontrolü GİRDİ BEYANIDIR; eksik/uyumsuzsa kâr/zarar ve sınır
  sonucu üretilmez. Kâr/zarar fiyat bazlı gerçekleşmemiş farktır (komisyon, vergi, nakit
  temettü hariç). Ağırlık yalnızca açık hisse pozisyonları içindedir.
- Tek sembol gerçek veri denemesi (THYAO.IS, yfinance 1.5.2, auto_adjust=False, tek çağrı,
  çıktı yerel geçici klasörde): seans etiketi ve 25.09 kapanışı alındı; sağlayıcı
  01.09–27.09 aralığında olay bildirmedi (yokluk doğrulaması değildir). `Close`'un ham fiyat
  olduğu Yahoo belgesiyle kanıtlanamadı → PRICE_BASIS_UNVERIFIED (engel geçerli sonuç).
  Karar: haricî doğrulama gerekiyor (resmî BIST kapanışı + KAP bölünme/bedelsiz kontrolü).

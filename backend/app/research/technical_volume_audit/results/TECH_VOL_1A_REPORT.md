# TECH-VOL 1A — High-Volume Confirmation Audit (MECHANICALLY GENERATED)

> **POST-HOC ASSUMPTION AUDIT.** Tetikleyici FLOW 1B'nin ÖN-KAYITSIZ keşif bulgusudur. Veri: FLOW 1C dış evreni (keşif 100'ü ile kesişim 0), Yahoo geriye düzeltmeli snapshot, güncel-listeleme survivorship'i. Technical-KÖR: yalnızca AYNI Technical durumu içindeki yüksek − yüksek-olmayan hacim farkları raporlanır. Üretim kodu DEĞİŞTİRİLMEDİ.

## Kimlik

- `code_head`: 216f24473f9d2b91c8127b395d7153191a62f62a
- `protocol_version`: TECH_VOL_1A_AUDIT_PROTOCOL_V2
- `protocol_sha256`: ce177dcfeccb3a8f2e549f0d9e4aa8c235c44d5480a8c7ed8e70214635aa0bb6
- `flow_1c_dataset_sha256`: 2dddfc3d8525abc0fb05cd2047f972db878ddec67f5dac5b6edd3af930a934b1
- `external_symbols_sha256`: a98aa034fc8d4912ff67ca2ff69f1bc1940e8086e7800d3b3c509c81ec79a409
- `production_states_content_sha256`: 8c7c824dc7a2a4963ddcac4ca22aa259de6ccb0b563d7337e022411787d923a0
- `run_timestamp_utc`: 2026-09-23T13:23:51.362308+00:00
- `python_version`: 3.13.15
- `pandas_version`: 3.0.5
- Technical: engine 1.14.0, scoring_config_hash `90ba569cf09eb771e6a40de7e5c8a75e3ac97629315c4d59b2607e53a88d9850`

## Örneklem

- state_rows: 455011
- merged_rows: 455011
- symbols: 462
- dates: 1304
- first_date: 2021-07-05
- last_date: 2026-09-22
- rv_unavailable_rows: 2760
- high_volume_rows: 104719
- high_volume_share: 0.2315506212258237
- technical_positive_rows: 182469
- technical_negative_rows: 143191
- strong_preconditions_without_volume_rows: 27553
- strong_preconditions_without_volume_high_rows: 6382
- bullish_confirmed_breakout_rows: 134966
- high_equals_low_rows: 4787
- high_equals_low_high_volume_rows: 188
- Durum semantiği doğrulaması (fail-fast): {'predicate_true_rows': 27555, 'predicate_true_high_rows': 6382, 'predicate_true_not_high_rows': 21173, 'strong_rows': 6382, 'violations_predicate_rows': 0, 'violations_strong_rows': 0}

## PRIMARY (V2: hacim hariç STRONG ön-koşulları TRUE iken yüksek hacim [→ STRONG] − yüksek-olmayan [→ BULLISH_CONFIRMED], T+10) ve KEY DIAGNOSTIC

- Getiri farkı: -1.12 pp [-2.10, -0.10] (n=914, NW t=-2.21)
- Hit-rate farkı: -4.39 pp [-6.71, -1.94] (n=914, NW t=-3.76)
- Gözlem (karşılaştırılan tarihlerde) yüksek/yüksek-olmayan: 6076 / 19021 (toplam 6382 / 21171)
- KEY DIAGNOSTIC log(RV20) partial IC | Technical (T+10): -0.0628 [-0.0714, -0.0542] (n=1286, NW t=-15.33)

## İkincil aile (Holm düzeltmeli p)

| Test | getiri farkı [95% CI] | Holm p | grup / karşılaştırma gözlemi |
|---|---|---|---|
| PRIMARY_T1 | -0.19 pp [-0.39, -0.00] (n=927, NW t=-2.10) | 0.3318 | 6127 / 19149 |
| KEY_DIAGNOSTIC_T1 | -0.0497 [-0.0543, -0.0452] (n=1295, NW t=-22.39) | 0.0021 | — / — |
| PRIMARY_T5 | -0.74 pp [-1.33, -0.15] (n=923, NW t=-2.48) | 0.1422 | 6113 / 19110 |
| KEY_DIAGNOSTIC_T5 | -0.0650 [-0.0732, -0.0573] (n=1291, NW t=-19.13) | 0.0021 | — / — |
| PRIMARY_T20 | -1.26 pp [-2.75, +0.30] (n=902, NW t=-1.65) | 0.4224 | 5983 / 18794 |
| KEY_DIAGNOSTIC_T20 | -0.0531 [-0.0614, -0.0447] (n=1276, NW t=-12.55) | 0.0021 | — / — |
| BEARISH | -2.13 pp [-2.72, -1.60] (n=1214, NW t=-7.97) | 0.0021 | 18045 / 118094 |
| NEUTRAL | -1.09 pp [-1.39, -0.82] (n=1266, NW t=-7.51) | 0.0021 | 24763 / 98735 |
| TECHNICAL_POSITIVE_CONTEXT | -1.20 pp [-1.54, -0.85] (n=1286, NW t=-7.41) | 0.0021 | 60012 / 120524 |
| BREAKOUT_CONTEXT | -1.18 pp [-1.60, -0.76] (n=1269, NW t=-5.66) | 0.0021 | 25839 / 106365 |
| DIRECTION_UP_A_minus_B | -1.18 pp [-1.45, -0.90] (n=1282, NW t=-8.70) | 0.0021 | 62280 / 114200 |
| DIRECTION_DOWN_C_minus_D | -1.70 pp [-2.00, -1.40] (n=1271, NW t=-10.96) | 0.0021 | 30229 / 147383 |
| DIRECTION_FLAT_E_minus_F | -0.82 pp [-1.23, -0.44] (n=1065, NW t=-3.79) | 0.0021 | 8443 / 43827 |
| SPIKE | -0.22 pp [-1.18, +0.85] (n=219, NW t=-0.41) | 0.8920 | 672 / 8580 |
| SUSTAINED | -1.21 pp [-2.63, +0.24] (n=766, NW t=-1.75) | 0.4224 | 3845 / 17476 |
| LIQUIDITY_LOWEST_QUINTILE_PRIMARY | -1.14 pp [-4.23, +1.42] (n=191, NW t=-0.80) | 0.8920 | 647 / 1370 |
| LIQUIDITY_REMAINING_80_PRIMARY | -1.07 pp [-2.14, +0.08] (n=864, NW t=-2.03) | 0.3330 | 4985 / 16252 |
| LIMIT_LOCKED_EXCLUDED_PRIMARY | -1.04 pp [-2.02, -0.00] (n=913, NW t=-2.03) | 0.3318 | 6059 / 18864 |
| LIQUIDITY_LOWEST_QUINTILE_TECHNICAL_POSITIVE | -0.85 pp [-1.63, -0.06] (n=1119, NW t=-2.28) | 0.2784 | 12390 / 16878 |
| LIQUIDITY_REMAINING_80_TECHNICAL_POSITIVE | -1.42 pp [-1.77, -1.08] (n=1284, NW t=-8.47) | 0.0021 | 47344 / 102931 |
| LIMIT_LOCKED_EXCLUDED_TECHNICAL_POSITIVE | -1.19 pp [-1.52, -0.85] (n=1286, NW t=-7.49) | 0.0021 | 59889 / 119600 |

## İstikrar (PRIMARY farkı)

- 2021: +1.46 pp (n=55, t=+1.09)
- 2022: -0.98 pp (n=212, t=-0.94)
- 2023: -0.17 pp (n=166, t=-0.13)
- 2024: -2.01 pp (n=126, t=-1.39)
- 2025: -2.37 pp (n=207, t=-2.35)
- 2026: -0.83 pp (n=148, t=-0.80)
- Piyasa yukarı: -0.13 pp [-1.37, +1.12] (n=621, NW t=-0.21)
- Piyasa aşağı: -2.86 pp [-4.87, -0.84] (n=243, NW t=-3.04)

## 10 offset (seçili yüksek-hacim − tüm bağlam, T+10)

### primary_strong_selection

- Uygun tarih: 1139; tüm tarihler (örtüşen): -0.83 pp [-1.62, -0.07] (n=1139, NW t=-2.16)
| offset | tarih | brüt | net 10 | net 20 | net 40 |
|---|---|---|---|---|---|
| 0 | 114 | -1.58 pp | -1.59 pp | -1.61 pp | -1.64 pp |
| 1 | 114 | -0.24 pp | -0.26 pp | -0.28 pp | -0.32 pp |
| 2 | 114 | -0.94 pp | -0.95 pp | -0.97 pp | -1.00 pp |
| 3 | 114 | +0.57 pp | +0.56 pp | +0.54 pp | +0.50 pp |
| 4 | 114 | -1.13 pp | -1.15 pp | -1.16 pp | -1.20 pp |
| 5 | 114 | -1.96 pp | -1.98 pp | -1.99 pp | -2.03 pp |
| 6 | 114 | -1.09 pp | -1.11 pp | -1.12 pp | -1.16 pp |
| 7 | 114 | -1.07 pp | -1.08 pp | -1.10 pp | -1.14 pp |
| 8 | 114 | -0.01 pp | -0.02 pp | -0.03 pp | -0.06 pp |
| 9 | 113 | -0.86 pp | -0.88 pp | -0.89 pp | -0.92 pp |
- across_gross: ort. -0.83 pp, medyan -1.00 pp, min -1.96 pp, max +0.57 pp, genel tahminle aynı işaret 9/10
- across_net_10bps: ort. -0.85 pp, medyan -1.02 pp, min -1.98 pp, max +0.56 pp, genel tahminle aynı işaret 9/10
- across_net_20bps: ort. -0.86 pp, medyan -1.04 pp, min -1.99 pp, max +0.54 pp, genel tahminle aynı işaret 9/10
- across_net_40bps: ort. -0.90 pp, medyan -1.07 pp, min -2.03 pp, max +0.50 pp, genel tahminle aynı işaret 9/10

### technical_positive_high_volume_selection

- Uygun tarih: 1287; tüm tarihler (örtüşen): -0.81 pp [-1.04, -0.58] (n=1287, NW t=-7.39)
| offset | tarih | brüt | net 10 | net 20 | net 40 |
|---|---|---|---|---|---|
| 0 | 129 | -0.88 pp | -0.93 pp | -0.97 pp | -1.06 pp |
| 1 | 129 | -1.11 pp | -1.16 pp | -1.20 pp | -1.29 pp |
| 2 | 129 | -0.91 pp | -0.96 pp | -1.00 pp | -1.09 pp |
| 3 | 129 | -0.75 pp | -0.80 pp | -0.84 pp | -0.93 pp |
| 4 | 129 | -0.64 pp | -0.69 pp | -0.73 pp | -0.82 pp |
| 5 | 129 | -0.49 pp | -0.53 pp | -0.57 pp | -0.66 pp |
| 6 | 129 | -0.86 pp | -0.91 pp | -0.95 pp | -1.04 pp |
| 7 | 128 | -0.70 pp | -0.74 pp | -0.79 pp | -0.88 pp |
| 8 | 128 | -0.89 pp | -0.94 pp | -0.98 pp | -1.07 pp |
| 9 | 128 | -0.84 pp | -0.88 pp | -0.93 pp | -1.02 pp |
- across_gross: ort. -0.81 pp, medyan -0.85 pp, min -1.11 pp, max -0.49 pp, genel tahminle aynı işaret 10/10
- across_net_10bps: ort. -0.85 pp, medyan -0.89 pp, min -1.16 pp, max -0.53 pp, genel tahminle aynı işaret 10/10
- across_net_20bps: ort. -0.90 pp, medyan -0.94 pp, min -1.20 pp, max -0.57 pp, genel tahminle aynı işaret 10/10
- across_net_40bps: ort. -0.99 pp, medyan -1.03 pp, min -1.29 pp, max -0.66 pp, genel tahminle aynı işaret 10/10

## Sınıflandırma (protokol kuralı, mekanik)

- Sınıf: **HARMFUL**
- Üretim değişikliği gerekli mi (kurala göre): **EVET**

---

## Yorum (ELLE YAZILDI — mekanik çıktı değildir; yukarıdaki sayılar değiştirilmedi)

- **PRIMARY (üretimin gerçek kullanımı):** Hacim dışındaki tüm STRONG koşulları sağlanan 27.553 durumda (436 sembol, 1.297 tarih), yüksek hacim → STRONG olan adaylar (6.382), yüksek hacmi olmadığı için BULLISH_CONFIRMED'da kalanlara (21.171) göre sonraki 10 seansta −1.12 pp [−2.10, −0.10] daha kötü XU100-göreli getiri ve −4.4 pp hit-rate gösterdi. Protokol kuralı: HARMFUL.
- **Güç / kırılganlık:** PRIMARY CI'ın üst sınırı 0'a yakın (−0.10 pp); yıllar karışık (2021 pozitif, 2025 anlamlı negatif), etki ağırlıkla düşen piyasa rejiminde (−2.86 pp) — yükselen piyasada ≈0. 10 offset'in 9'unda negatif. Likidite alt gruplarında örneklem küçülünce CI 0'ı içeriyor (etki yönü aynı, büyüklük benzer: −1.07 / −1.14 pp) — negatif ilişki bir mikro-cap artefaktı gibi görünmüyor.
- **Genel örüntü (ikincil, Holm sonrası çok güçlü):** Yüksek göreli hacim, Technical durumundan (pozitif/nötr/negatif) ve fiyat yönünden (yukarı/aşağı/yatay) BAĞIMSIZ olarak daha düşük 10 seanslık göreli getiriyle ilişkili; log(RV20) partial IC −0.063 (t −15). Yani hacim "yön güçlendirici" (DIRECTION-CONDITIONAL) değil, tek yönlü negatif bir bilgi taşıyor. Bu, FLOW 1B'nin keşif bulgusunu dış evrende güçlü biçimde tekrarlıyor.
- **Üretim etkisi (mutlak Technical performansı olmadan):** Bugünkü kural, hacim dışı STRONG koşullarını sağlayan adayların %76.8'ini STRONG'dan (dolayısıyla portföy dışı "yeni fırsat" bildiriminden — bildirim ayrıca DecisionEngine BUY gerektirir) dışlıyor ve STRONG'u tam da göreli olarak daha kötü performans gösteren yüksek hacimli alt kümeye veriyor.
- **Sınırlamalar:** post-hoc denetim; güncel-listeleme survivorship; Yahoo geriye düzeltmeli veri; bilgi amaçlı Close→Close hedefi; keşifle aynı dönem.

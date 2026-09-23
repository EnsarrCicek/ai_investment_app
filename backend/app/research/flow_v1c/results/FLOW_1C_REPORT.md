# FLOW 1C — External CMF Validation Report (MECHANICALLY GENERATED)

> **EXTERNAL CROSS-SECTIONAL ROBUSTNESS STUDY.** Doğrulama evreni = KAP BIST TÜM − FLOW 1B keşif 100'ü (kesişim 0). Güncel listeleme evreni geriye uygulandı: hayatta kalma yanlılığı ÇÖZÜLMEDİ. Dönem keşifle aynı (2021–2026), semboller ayrık — zamansal değil kesitsel dış doğrulama. CMF gerçek para girişi değil, fiyat/hacim VEKİLİDİR. Technical-KÖR: Technical-pozitif adayların kendi getiri seviyesi hesaplanmadı/gösterilmedi.

## Kimlik

- `code_head`: 41ebfcd5d173a998efd9b367292dca9a3bff659b
- `protocol_version`: FLOW_V1C_EXTERNAL_PROTOCOL_V1
- `protocol_sha256`: b1196e9bdf29fe97f15abcbada9d05c2c21a351c059b70117af67b2b962e8f42
- `dataset_sha256`: 2dddfc3d8525abc0fb05cd2047f972db878ddec67f5dac5b6edd3af930a934b1
- `external_symbols_sha256`: a98aa034fc8d4912ff67ca2ff69f1bc1940e8086e7800d3b3c509c81ec79a409
- `run_timestamp_utc`: 2026-09-23T09:17:50.922272+00:00
- `python_version`: 3.13.15
- `pandas_version`: 3.0.5

## Örneklem

- Dış evren: 484 sembol; Yahoo çekim hatası: 0 → —
- Gözlemi olan sembol: 464; keşif kesişimi: 0
- Tarihler: 2021-03-29 → 2026-09-22 (1370 tarih); panel satırı 503645; P1 tam satır 490631
- P1 kesit büyüklüğü: medyan 366, min 149, max 462
- Kalite: ham bar 553218, hayalet bar 1855, bütünlük ihlali 589, eksik beklenen seans 360, sıfır hacim 3293, H==L 6201; warm-up'tan kısa segment 86

## Eş-birincil hipotezler (Bonferroni, %97.5 CI)

- **P1** CMF20 T+10 partial IC | Technical: +0.0291 [+0.0189, +0.0393] (CI 97.5%, n=1352, NW t=+6.80) → **SUPPORTED** (95% referans: +0.0291 [+0.0201, +0.0381] (CI 95%, n=1352, NW t=+6.80))
- **P2** negatif-CMF filtresi (reddedilen − geçen, Technical-pozitif içinde): getiri -0.61 pp [-1.11, -0.10] (CI 97.5%, n=1350, NW t=-2.96); hit-rate -3.35 pp [-5.15, -1.49] (CI 97.5%, n=1350, NW t=-4.52) → **SUPPORTED**; ekonomik anlamlı (≤ −0.40 pp): True
  - Reddedilen/geçen gözlem (karşılaştırılan tarihlerde): 62345 / 130909; Technical-pozitif gözlem: 193305; reddedilme payı: 0.323

## Negatif-CMF filtresi — 10 offset (filtreli − filtresiz, T+10, örtüşmeyen)

| Offset | tarih | brüt iyileşme | net 10 | net 20 | net 40 | reddedilen−geçen | devir geçen/tümü | ort. aday / red |
|---|---|---|---|---|---|---|---|---|
| 0 | 136 | +0.11 pp | +0.11 pp | +0.10 pp | +0.09 pp | -0.25 pp | 0.48/0.41 | 142.3 / 45.7 |
| 1 | 136 | +0.14 pp | +0.13 pp | +0.12 pp | +0.11 pp | -0.48 pp | 0.47/0.41 | 142.8 / 46.1 |
| 2 | 135 | +0.21 pp | +0.20 pp | +0.20 pp | +0.18 pp | -0.69 pp | 0.48/0.42 | 143.7 / 46.7 |
| 3 | 135 | +0.22 pp | +0.22 pp | +0.21 pp | +0.20 pp | -0.65 pp | 0.48/0.42 | 143.6 / 47.1 |
| 4 | 135 | +0.25 pp | +0.24 pp | +0.24 pp | +0.23 pp | -0.74 pp | 0.48/0.42 | 144.8 / 47.4 |
| 5 | 135 | +0.25 pp | +0.25 pp | +0.24 pp | +0.23 pp | -0.67 pp | 0.48/0.42 | 144.4 / 47.1 |
| 6 | 135 | +0.26 pp | +0.26 pp | +0.25 pp | +0.24 pp | -0.97 pp | 0.47/0.42 | 142.2 / 45.5 |
| 7 | 135 | +0.21 pp | +0.20 pp | +0.20 pp | +0.19 pp | -0.82 pp | 0.47/0.42 | 141.7 / 45.0 |
| 8 | 135 | +0.10 pp | +0.09 pp | +0.09 pp | +0.08 pp | -0.36 pp | 0.47/0.42 | 141.2 / 44.9 |
| 9 | 135 | +0.17 pp | +0.16 pp | +0.16 pp | +0.14 pp | -0.46 pp | 0.48/0.41 | 143.1 / 45.6 |

- gross_improvement: ort. +0.19 pp, medyan +0.21 pp, min +0.10 pp, max +0.26 pp, pozitif 10/10
- rejected_minus_passed: ort. -0.61 pp, medyan -0.66 pp, min -0.97 pp, max -0.25 pp, pozitif 0/10
- net_improvement_10bps: ort. +0.19 pp, medyan +0.20 pp, min +0.09 pp, max +0.26 pp, pozitif 10/10
- net_improvement_20bps: ort. +0.18 pp, medyan +0.20 pp, min +0.09 pp, max +0.25 pp, pozitif 10/10
- net_improvement_40bps: ort. +0.17 pp, medyan +0.19 pp, min +0.08 pp, max +0.24 pp, pozitif 10/10
- all_dates_overlapping_gross_improvement: +0.19 pp [+0.08, +0.31] (CI 95%, n=1352, NW t=+3.59)
- all_dates_overlapping_rejected_minus_passed: -0.61 pp [-1.05, -0.16] (CI 95%, n=1351, NW t=-2.95)

## İkincil: Technical'a göre artıklaştırılmış CMF Q5−Q1 — 10 offset

- Tüm tarihler (örtüşen) brüt: +0.92 pp [+0.56, +1.30] (CI 95%, n=1352, NW t=+5.18)
- across_gross: ort. +0.92 pp, medyan +0.86 pp, min +0.66 pp, max +1.59 pp, pozitif 10/10
- across_net_10bps: ort. +0.81 pp, medyan +0.75 pp, min +0.55 pp, max +1.48 pp, pozitif 10/10
- across_net_20bps: ort. +0.70 pp, medyan +0.64 pp, min +0.44 pp, max +1.37 pp, pozitif 10/10
- across_net_40bps: ort. +0.48 pp, medyan +0.42 pp, min +0.21 pp, max +1.14 pp, pozitif 10/10

## İkincil: ufuklar ve CMF vs eski PVFS (partial IC | Technical, %95 CI)

| h | CMF20 | PVFS | CMF − PVFS |
|---|---|---|---|
| 1 | +0.0150 [+0.0111, +0.0190] (CI 95%, n=1360, NW t=+7.74) | +0.0144 [+0.0107, +0.0181] (CI 95%, n=1360, NW t=+7.82) | +0.0006 [-0.0007, +0.0020] (CI 95%, n=1360, NW t=+1.00) |
| 5 | +0.0216 [+0.0144, +0.0289] (CI 95%, n=1357, NW t=+6.35) | +0.0194 [+0.0127, +0.0262] (CI 95%, n=1357, NW t=+6.05) | +0.0022 [-0.0004, +0.0049] (CI 95%, n=1357, NW t=+1.90) |
| 10 | +0.0291 [+0.0201, +0.0381] (CI 95%, n=1352, NW t=+6.80) | +0.0262 [+0.0179, +0.0348] (CI 95%, n=1352, NW t=+6.50) | +0.0028 [-0.0004, +0.0062] (CI 95%, n=1352, NW t=+1.90) |
| 20 | +0.0326 [+0.0216, +0.0439] (CI 95%, n=1342, NW t=+5.64) | +0.0284 [+0.0183, +0.0386] (CI 95%, n=1342, NW t=+5.35) | +0.0042 [+0.0005, +0.0081] (CI 95%, n=1342, NW t=+2.18) |

## İkincil: yıllar

| Yıl | P1 ort. (n, t) | P2 ort. (n) |
|---|---|---|
| 2021 | +0.0203 (188, +1.95) | -0.34 pp (188) |
| 2022 | +0.0232 (252, +2.09) | -0.43 pp (252) |
| 2023 | +0.0361 (246, +3.70) | -0.45 pp (244) |
| 2024 | +0.0325 (248, +3.58) | -0.83 pp (248) |
| 2025 | +0.0355 (249, +3.92) | -0.72 pp (249) |
| 2026 | +0.0228 (169, +1.78) | -0.94 pp (169) |

- Likidite (en düşük quintile hariç, 100161 gözlem dışlandı): P1 +0.0241 [+0.0149, +0.0334] (CI 95%, n=1352, NW t=+5.41); P2 -0.42 pp [-0.90, +0.08] (CI 95%, n=1350, NW t=-1.84)

## Araştırma kapısı (protokol kuralı, mekanik)

- decision: **DEVAM**
- p1_label: SUPPORTED
- p2_label: SUPPORTED
- p2_economically_meaningful: True
- net20_positive_offsets: 10
- offset_condition_met: True
- sample_condition_met: True

---

## Yorum (ELLE YAZILDI — mekanik çıktı değildir; yukarıdaki sayılar değiştirilmedi)

- **Dış kesitsel doğrulama olumlu:** Keşifte kullanılmayan 464 sembolde CMF20'nin Technical ötesindeki T+10 bilgisi (P1 +0.029) ve Technical-pozitif içinde negatif-CMF filtresinin etkisi (P2 −0.61 pp, hit-rate −3.4 pp) Bonferroni düzeltmeli %97.5 CI ile destekleniyor. P1 6/6 yılda, P2 6/6 yılda aynı yönde. Filtre iyileşmesi 10/10 offset'te pozitif (net 20 bps min +0.09 pp) — FLOW 1B'deki tek-offset kırılganlığı burada görülmüyor.
- **Önemli sınırlama — likidite:** En düşük işlem-değeri quintile'ı çıkarıldığında P2 −0.42 pp'ye düşüyor ve %95 CI 0'ı içeriyor ([−0.90, +0.08]). Filtre etkisinin bir kısmı en az likit küçük hisselerden geliyor; bu isimlerde kapanış fiyatıyla işlem, fiyat limitleri ve spread gerçekçi olmayabilir. P1 likidite filtresinden sonra da güçlü kalıyor.
- **Hâlâ çözülmeyenler:** (1) Evren güncel listeleme — survivorship devam ediyor; (2) dönem keşifle aynı (2021–2026) — zamansal out-of-sample değil; (3) hedef bilgi amaçlı Close→Close; (4) Yahoo verisi geriye dönük düzeltmeli.
- **CMF vs PVFS (ikincil):** Dış evrende NSV'nin seyreltmesi küçük (T+10 fark +0.003, CI 0'ı içeriyor; yalnız T+20'de anlamlı). CMF-tek skor tercih edilebilir ama fark büyük değil.
- **Sonuç:** Kilitli kapı DEVAM. Bu, production altyapısını DEĞİL, yalnızca prospektif (ileriye dönük) shadow doğrulamanın tasarlanmasını yetkilendirir.

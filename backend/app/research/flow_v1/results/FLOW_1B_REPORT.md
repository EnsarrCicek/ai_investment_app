# FLOW 1B — Offline Incremental-Value Report (MECHANICALLY GENERATED)

> **CURRENT FROZEN-UNIVERSE RETROSPECTIVE STUDY.** 2026-09-09 BIST100 listesi geçmişe uygulandı — yüksek hayatta kalma yanlılığı riski; tarihsel BIST100 portföy performansı DEĞİLDİR. Yahoo verisi temettü/bölünme düzeltmeli ve geriye dönük değişebilir; bu çalışma dondurulmuş bir snapshot üzerindedir, point-in-time kanıtı veya prospektif geçerlilik DEĞİLDİR. CMF/NSV/MFI gerçek para girişi değil, fiyat/hacim VEKİLLERİDİR. Technical-KÖR mod: Technical'ın kendi getiri performansı hesaplanmadı.

## Kimlik

- `code_head`: 51d019f3a7e310a9327e523f6fcccc183a578b92
- `protocol_version`: FLOW_V1_OFFLINE_PROTOCOL_V1
- `protocol_sha256`: 0b94f8035e888fcb2a1a9b8f52a29b44f9acc4ae9573aeef376317ced8db381b
- `dataset_sha256`: a031900a35cc01d91c967a5ef3541b1cf2195a7913227a4ad22bb9d4cee4b61a
- `run_timestamp_utc`: 2026-09-23T08:25:33.699851+00:00
- `python_version`: 3.13.15
- `numpy_version`: 2.5.2
- `pandas_version`: 3.0.5
- Technical baseline: `app.engines.backtest.engine.technical_score_series`, engine 1.14.0 (manifest 1.14.0), scoring_config_hash `90ba569cf09eb771e6a40de7e5c8a75e3ac97629315c4d59b2607e53a88d9850`, freeze_manifest_sha256 `6556f7a9c9b9eedcc4b789c861cc2e1b5b2d4a13be1be75605162f0e578bdc97`
- Vektörize vs canlı Technical skor paritesi: 25 örnek, max |fark| = 0.0, hata = 0

## Örneklem

- Gözlem tarihleri: 2021-03-29 → 2026-09-21 (1369 farklı tarih)
- Panel satırı: 113173, sembol: 100, birincil tam satır (PVFS+Technical+T+10): 110715
- Hedef mevcut satır: {'ex_1': 112305, 'ex_5': 111636, 'ex_10': 110725, 'ex_20': 108907}
- Warm-up dışı bırakılan bar: 11580, warm-up'tan kısa segment: 22

- Kalite toplamları (hisseler): ham bar 125290, tamamlanmamış bar 0, takvim-dışı (hayalet) bar 390, bütünlük ihlali 147, eksik beklenen seans 108, sıfır hacimli seans 191, H==L seans 374
- 2021-03 sonrası başlayan (yeni halka arz vb.) semboller: 30 → QUAGR (2021-04-09), CANTE (2021-04-30), GENIL (2021-08-05), GESAN (2021-08-19), MAGEN (2021-11-02), MIATK (2021-11-22), PSGYO (2021-12-16), DAPGM (2022-02-24), GRSEL (2022-03-09), EUREN (2022-06-08), ASTOR (2023-01-18), CVKMD (2023-04-13), EUPWR (2023-04-20), CWENE (2023-05-10), IZENR (2023-08-16), ENERY (2023-08-23), PATEK (2024-02-14), OBAMS (2024-03-01), GRTHO (2024-03-21), KLRHO (2024-03-21), KTLEV (2024-03-21), PASEU (2024-03-21), REEDR (2024-03-21), ODINE (2024-05-02), ALTNY (2024-05-16), EFOR (2024-07-05), GLRMK (2025-01-17), DSTKF (2025-02-06), BALSU (2025-02-20), PAHOL (2025-11-21)

## Birincil hipotez P1 (T+10, PVFS partial IC | Technical)

- +0.0359 [+0.0175, +0.0540] (n=1352, NW t=+4.15) → **SUPPORTED**

## IC ve partial IC (bilgi hedefi: Close(T)→Close(T+h), XU100-göreli)

| Özellik | h | IC | partial IC (kontrol) |
|---|---|---|---|
| pvfs | 1 | +0.0260 [+0.0157, +0.0362] (n=1359, NW t=+5.82) | +0.0146 [+0.0059, +0.0230] (n=1359, NW t=+3.93) (technical_score) |
| pvfs | 5 | +0.0375 [+0.0174, +0.0570] (n=1357, NW t=+4.55) | +0.0224 [+0.0075, +0.0371] (n=1357, NW t=+3.40) (technical_score) |
| pvfs | 10 | +0.0493 [+0.0236, +0.0744] (n=1352, NW t=+4.19) | +0.0359 [+0.0175, +0.0540] (n=1352, NW t=+4.15) (technical_score) |
| pvfs | 20 | +0.0532 [+0.0231, +0.0827] (n=1342, NW t=+3.47) | +0.0356 [+0.0158, +0.0546] (n=1342, NW t=+3.53) (technical_score) |
| cmf20 | 1 | +0.0301 [+0.0198, +0.0402] (n=1359, NW t=+6.73) | +0.0209 [+0.0123, +0.0291] (n=1359, NW t=+5.54) (technical_score) |
| cmf20 | 5 | +0.0428 [+0.0224, +0.0626] (n=1357, NW t=+5.10) | +0.0305 [+0.0147, +0.0461] (n=1357, NW t=+4.40) (technical_score) |
| cmf20 | 10 | +0.0565 [+0.0295, +0.0832] (n=1352, NW t=+4.62) | +0.0452 [+0.0246, +0.0657] (n=1352, NW t=+4.78) (technical_score) |
| cmf20 | 20 | +0.0631 [+0.0314, +0.0936] (n=1342, NW t=+3.93) | +0.0490 [+0.0257, +0.0715] (n=1342, NW t=+4.12) (technical_score) |
| nsv20 | 1 | +0.0146 [+0.0055, +0.0237] (n=1359, NW t=+3.54) | +0.0000 [-0.0078, +0.0082] (n=1359, NW t=+0.01) (technical_score) |
| nsv20 | 5 | +0.0216 [+0.0051, +0.0377] (n=1357, NW t=+3.03) | +0.0018 [-0.0117, +0.0160] (n=1357, NW t=+0.29) (technical_score) |
| nsv20 | 10 | +0.0258 [+0.0046, +0.0464] (n=1352, NW t=+2.64) | +0.0053 [-0.0116, +0.0228] (n=1352, NW t=+0.65) (technical_score) |
| nsv20 | 20 | +0.0259 [-0.0010, +0.0528] (n=1342, NW t=+1.87) | +0.0008 [-0.0196, +0.0217] (n=1342, NW t=+0.08) (technical_score) |
| mfi14 | 1 | +0.0091 [+0.0009, +0.0171] (n=1359, NW t=+2.17) | -0.0096 [-0.0170, -0.0021] (n=1359, NW t=-2.79) (technical_score+rsi14) |
| mfi14 | 5 | +0.0089 [-0.0056, +0.0228] (n=1357, NW t=+1.26) | -0.0189 [-0.0327, -0.0054] (n=1357, NW t=-2.98) (technical_score+rsi14) |
| mfi14 | 10 | +0.0121 [-0.0071, +0.0305] (n=1352, NW t=+1.34) | -0.0183 [-0.0343, -0.0022] (n=1352, NW t=-2.28) (technical_score+rsi14) |
| mfi14 | 20 | +0.0126 [-0.0112, +0.0361] (n=1342, NW t=+1.03) | -0.0229 [-0.0414, -0.0047] (n=1342, NW t=-2.44) (technical_score+rsi14) |
| log_rv20 | 1 | -0.0212 [-0.0293, -0.0129] (n=1358, NW t=-5.19) | -0.0241 [-0.0321, -0.0159] (n=1358, NW t=-6.07) (technical_score) |
| log_rv20 | 5 | -0.0238 [-0.0352, -0.0124] (n=1356, NW t=-4.37) | -0.0277 [-0.0392, -0.0162] (n=1356, NW t=-5.13) (technical_score) |
| log_rv20 | 10 | -0.0295 [-0.0420, -0.0174] (n=1351, NW t=-4.85) | -0.0343 [-0.0470, -0.0219] (n=1351, NW t=-5.59) (technical_score) |
| log_rv20 | 20 | -0.0146 [-0.0286, -0.0011] (n=1341, NW t=-2.11) | -0.0199 [-0.0336, -0.0064] (n=1341, NW t=-2.87) (technical_score) |

### Yürütme varyantı (AYRI): Open(E1)→Close(Eh)

| Özellik | h | IC | partial IC |
|---|---|---|---|
| pvfs | 1 | +0.0392 [+0.0287, +0.0497] (n=1363, NW t=+8.74) | +0.0346 [+0.0265, +0.0426] (n=1363, NW t=+9.41) |
| pvfs | 5 | +0.0426 [+0.0224, +0.0617] (n=1357, NW t=+5.18) | +0.0300 [+0.0153, +0.0446] (n=1357, NW t=+4.58) |
| pvfs | 10 | +0.0526 [+0.0265, +0.0780] (n=1352, NW t=+4.46) | +0.0407 [+0.0225, +0.0588] (n=1352, NW t=+4.74) |
| pvfs | 20 | +0.0552 [+0.0251, +0.0847] (n=1342, NW t=+3.61) | +0.0394 [+0.0198, +0.0582] (n=1342, NW t=+3.96) |
| cmf20 | 1 | +0.0470 [+0.0364, +0.0576] (n=1363, NW t=+10.50) | +0.0443 [+0.0363, +0.0522] (n=1363, NW t=+11.88) |
| cmf20 | 5 | +0.0495 [+0.0293, +0.0692] (n=1357, NW t=+5.92) | +0.0397 [+0.0241, +0.0552] (n=1357, NW t=+5.75) |
| cmf20 | 10 | +0.0609 [+0.0337, +0.0877] (n=1352, NW t=+4.97) | +0.0511 [+0.0308, +0.0715] (n=1352, NW t=+5.45) |
| cmf20 | 20 | +0.0659 [+0.0346, +0.0963] (n=1342, NW t=+4.12) | +0.0534 [+0.0306, +0.0755] (n=1342, NW t=+4.56) |
| nsv20 | 1 | +0.0139 [+0.0046, +0.0231] (n=1363, NW t=+3.36) | +0.0013 [-0.0069, +0.0097] (n=1363, NW t=+0.36) |
| nsv20 | 5 | +0.0210 [+0.0044, +0.0372] (n=1357, NW t=+2.97) | +0.0019 [-0.0119, +0.0162] (n=1357, NW t=+0.29) |
| nsv20 | 10 | +0.0253 [+0.0040, +0.0459] (n=1352, NW t=+2.59) | +0.0051 [-0.0119, +0.0226] (n=1352, NW t=+0.63) |
| nsv20 | 20 | +0.0253 [-0.0015, +0.0522] (n=1342, NW t=+1.83) | +0.0010 [-0.0194, +0.0219] (n=1342, NW t=+0.10) |

## Quintile'lar (ortalama XU100-göreli getiri, tarih-dengeli)

| Özellik | h | n | Q1 | Q2 | Q3 | Q4 | Q5 | Q5−Q1 [CI] | monotonluk ρ / artan adım |
|---|---|---|---|---|---|---|---|---|---|
| pvfs | 1 | 1298 | -0.05% | +0.01% | +0.03% | +0.06% | +0.10% | +0.15% [+0.07, +0.22] | +1.00 / 4 |
| cmf20 | 1 | 1298 | -0.07% | +0.03% | +0.02% | +0.08% | +0.08% | +0.15% [+0.07, +0.23] | +0.80 / 2 |
| nsv20 | 1 | 1298 | -0.05% | +0.03% | +0.00% | +0.08% | +0.08% | +0.13% [+0.06, +0.20] | +0.80 / 2 |
| pvfs_resid_tech | 1 | 1298 | -0.00% | -0.01% | +0.05% | +0.12% | -0.01% | -0.01% [-0.08, +0.05] | -0.10 / 2 |
| pvfs | 5 | 1291 | -0.09% | +0.09% | +0.23% | +0.35% | +0.41% | +0.49% [+0.12, +0.86] | +1.00 / 4 |
| cmf20 | 5 | 1291 | -0.18% | +0.20% | +0.20% | +0.37% | +0.40% | +0.58% [+0.21, +0.94] | +1.00 / 4 |
| nsv20 | 5 | 1291 | -0.07% | +0.21% | +0.16% | +0.31% | +0.38% | +0.45% [+0.12, +0.78] | +0.90 / 3 |
| pvfs_resid_tech | 5 | 1291 | +0.07% | +0.02% | +0.23% | +0.51% | +0.16% | +0.09% [-0.21, +0.37] | +0.60 / 2 |
| pvfs | 10 | 1281 | -0.06% | +0.20% | +0.52% | +0.74% | +0.82% | +0.88% [+0.17, +1.56] | +1.00 / 4 |
| cmf20 | 10 | 1281 | -0.22% | +0.38% | +0.53% | +0.70% | +0.82% | +1.04% [+0.34, +1.73] | +1.00 / 4 |
| nsv20 | 10 | 1281 | -0.04% | +0.50% | +0.44% | +0.49% | +0.82% | +0.87% [+0.25, +1.48] | +0.70 / 3 |
| pvfs_resid_tech | 10 | 1281 | +0.19% | +0.16% | +0.47% | +0.79% | +0.60% | +0.40% [-0.12, +0.92] | +0.80 / 2 |
| pvfs | 20 | 1261 | +0.21% | +0.60% | +1.09% | +1.37% | +1.78% | +1.58% [+0.22, +2.86] | +1.00 / 4 |
| cmf20 | 20 | 1261 | -0.13% | +0.94% | +1.17% | +1.28% | +1.79% | +1.92% [+0.55, +3.24] | +1.00 / 4 |
| nsv20 | 20 | 1261 | +0.27% | +1.03% | +0.90% | +1.09% | +1.76% | +1.49% [+0.24, +2.72] | +0.90 / 3 |
| pvfs_resid_tech | 20 | 1261 | +0.62% | +0.51% | +0.94% | +1.62% | +1.34% | +0.72% [-0.20, +1.67] | +0.80 / 2 |

## Hipotezler (T+10; yalnızca farklar — Technical-kör)

- **H1** SUPPORTED: getiri farkı +0.0035 [+0.0006, +0.0063] (n=1348, NW t=+2.58); hit-rate farkı (pp) +1.39 [+0.26, +2.49] (n=1348, NW t=+2.57); grup gözlemi 25605 / karşılaştırma 50508 (alt küme toplamı 50527, grup toplamı 25609)
- **H2** SUPPORTED: getiri farkı -0.0101 [-0.0152, -0.0048] (n=1010, NW t=-3.79); hit-rate farkı (pp) -5.13 [-7.57, -2.66] (n=1010, NW t=-4.06); grup gözlemi 6333 / karşılaştırma 43564 (alt küme toplamı 50527, grup toplamı 6533)
- **H1_H2_spread** (betimsel): getiri farkı +0.0141 [+0.0065, +0.0216] (n=1010, NW t=+3.83); hit-rate farkı (pp) +7.06 [+3.64, +10.32] (n=1010, NW t=+4.29); grup gözlemi 21217 / karşılaştırma 6333 (alt küme toplamı 50527, grup toplamı 25609)
- **neutral_vs_all** (betimsel): getiri farkı +0.0002 [-0.0025, +0.0031] (n=1317, NW t=+0.18); hit-rate farkı (pp) +0.02 [-1.07, +1.13] (n=1317, NW t=+0.03); grup gözlemi 18360 / karşılaştırma 50238 (alt küme toplamı 50527, grup toplamı 18385)
- **H4** NOT_ESTABLISHED: getiri farkı -0.0027 [-0.0079, +0.0026] (n=980, NW t=-1.04); hit-rate farkı (pp) -1.59 [-4.24, +1.10] (n=980, NW t=-1.15); grup gözlemi 3904 / karşılaştırma 13273 (alt küme toplamı 20259, grup toplamı 4180)
- **H5** NOT_ESTABLISHED: getiri farkı -0.0055 [-0.0220, +0.0115] (n=248, NW t=-0.66); hit-rate farkı (pp) -4.42 [-9.95, +1.48] (n=248, NW t=-1.42); grup gözlemi 667 / karşılaştırma 8044 (alt küme toplamı 33391, grup toplamı 1055)
- **H6** MFI_REDUNDANT_OR_UNPROVEN: MFI partial IC | Technical+RSI = -0.0183 [-0.0343, -0.0022] (n=1352, NW t=-2.28)
- MFI partial IC | yalnız RSI (T+10) = -0.0168 [-0.0325, -0.0006] (n=1352, NW t=-2.08)

## Maliyet duyarlılığı (T+10, örtüşmeyen 10 seanslık yeniden dengeleme)

| Skor | yeniden dengeleme | devir L/S | L−S brüt | L−S net 10/20/40 bps | Q5−XU100 brüt | Q5−XU100 net 10/20/40 bps |
|---|---|---|---|---|---|---|
| pvfs | 129 | 0.51/0.56 | +0.75% [-0.07, +1.52] | +0.64% / +0.53% / +0.32% | +0.79% | +0.74% / +0.69% / +0.59% |
| pvfs_resid_tech | 129 | 0.62/0.64 | -0.17% [-0.85, +0.48] | -0.29% / -0.42% / -0.67% | +0.24% | +0.17% / +0.11% / -0.01% |

## İstikrar (T+10 partial IC)

| Yıl | pvfs | cmf20 | nsv20 |
|---|---|---|---|
| 2021 | +0.0459 (n=188, t=+2.20) | +0.0546 (n=188, t=+2.52) | -0.0006 (n=188, t=-0.03) |
| 2022 | +0.0071 (n=252, t=+0.34) | +0.0029 (n=252, t=+0.13) | +0.0193 (n=252, t=+0.92) |
| 2023 | +0.0472 (n=246, t=+2.48) | +0.0596 (n=246, t=+2.99) | -0.0065 (n=246, t=-0.30) |
| 2024 | +0.0682 (n=248, t=+2.91) | +0.0852 (n=248, t=+3.18) | +0.0070 (n=248, t=+0.39) |
| 2025 | +0.0396 (n=249, t=+2.20) | +0.0499 (n=249, t=+2.39) | +0.0179 (n=249, t=+1.35) |
| 2026 | -0.0019 (n=169, t=-0.12) | +0.0117 (n=169, t=+0.64) | -0.0126 (n=169, t=-0.56) |

- Piyasa yukarı rejimi: +0.0338 [+0.0116, +0.0560] (n=807, NW t=+3.17)
- Piyasa aşağı rejimi: +0.0417 [+0.0162, +0.0678] (n=465, NW t=+3.14)
- Düşük likidite quintile'ı hariç P1: +0.0280 [+0.0084, +0.0474] (n=1347, NW t=+2.94) (dışlanan gözlem 22034)

## Korelasyonlar (tarih bazlı kesitsel Spearman ortalaması)

| | cmf20 | nsv20 | pvfs | mfi14 | log_rv20 | technical_score | rsi14 | momentum_component | roc_component | roc20_price |
|---|---|---|---|---|---|---|---|---|---|---|
| cmf20 | +1.00 | +0.57 | +0.96 | +0.45 | +0.05 | +0.61 | +0.62 | +0.47 | +0.46 | +0.66 |
| nsv20 | +0.57 | +1.00 | +0.75 | +0.60 | +0.07 | +0.60 | +0.64 | +0.50 | +0.49 | +0.69 |
| pvfs | +0.96 | +0.75 | +1.00 | +0.54 | +0.06 | +0.66 | +0.68 | +0.53 | +0.51 | +0.73 |
| mfi14 | +0.45 | +0.60 | +0.54 | +1.00 | +0.13 | +0.64 | +0.68 | +0.64 | +0.62 | +0.62 |
| log_rv20 | +0.05 | +0.07 | +0.06 | +0.13 | +1.00 | +0.12 | +0.16 | +0.21 | +0.22 | +0.08 |
| technical_score | +0.61 | +0.60 | +0.66 | +0.64 | +0.12 | +1.00 | +0.94 | +0.81 | +0.81 | +0.83 |
| rsi14 | +0.62 | +0.64 | +0.68 | +0.68 | +0.16 | +0.94 | +1.00 | +0.82 | +0.80 | +0.85 |
| momentum_component | +0.47 | +0.50 | +0.53 | +0.64 | +0.21 | +0.81 | +0.82 | +1.00 | +0.97 | +0.66 |
| roc_component | +0.46 | +0.49 | +0.51 | +0.62 | +0.22 | +0.81 | +0.80 | +0.97 | +1.00 | +0.67 |
| roc20_price | +0.66 | +0.69 | +0.73 | +0.62 | +0.08 | +0.83 | +0.85 | +0.66 | +0.67 | +1.00 |

## Özellik betimsel istatistikleri

| Özellik | n | mevcut değil | ort. | std | p05 | medyan | p95 |
|---|---|---|---|---|---|---|---|
| cmf20 | 113163 | 10 | -0.06709 | 0.191 | -0.3833 | -0.06749 | 0.245 |
| nsv20 | 113163 | 10 | 0.1107 | 0.2625 | -0.3261 | 0.1158 | 0.5303 |
| pvfs | 113163 | 10 | -5.386 | 40.07 | -63.49 | -7.864 | 66.68 |
| mfi14 | 113156 | 17 | 56.99 | 17.42 | 27.07 | 57.87 | 84.2 |
| rv20 | 113033 | 140 | 1.198 | 1.13 | 0.4855 | 0.99 | 2.513 |
| turnover20 | 113173 | 0 | 8.86e+08 | 1.571e+09 | 2.313e+07 | 3.187e+08 | 3.785e+09 |
| roc20_price | 113173 | 0 | 0.04413 | 0.1731 | -0.1736 | 0.02316 | 0.3317 |
| technical_score | 113173 | 0 | 10.7 | 37.4 | -48.35 | 9.83 | 73.91 |

## Araştırma kapısı (protokoldeki kurallarla mekanik)

- Karar: **BELIRSIZ**
- P1: SUPPORTED, CI [0.0174709727576443, 0.05400536111977763]; anlamlı eşik 0.02
- Yıl koşulu: 5/6 pozitif → True
- Maliyet koşulu (artık PVFS L−S net 20 bps ort.): -0.004185821220713901 → False

Holm düzeltmeli ikincil p-değerleri: `summary.json` → `holm_adjusted_secondary`.

---

## Yorum (ELLE YAZILDI — mekanik çıktı değildir; yukarıdaki sayılar değiştirilmedi)

**Survivorship uyarısı her sonuç için geçerli:** evren 2026-09-09 BIST100 listesidir; 100 sembolün 30'u 2021-03 sonrası halka arz/listelenme ile sonradan girmiştir. Flow vekilleri trend ile korelasyonlu olduğundan (ρ≈0.6–0.7) yanlılık IC'yi şişirebilir; Technical kontrolü bunu yalnızca kısmen giderir.

1. **CMF20 Technical ötesinde ek bilgi taşıyor mu?** Bu örneklemde evet: T+10 partial IC +0.045 [+0.025, +0.066], Holm sonrası p≈0.011; tüm ufuklarda ve yürütme varyantında pozitif. 2022 (≈0) ve 2026 (+0.012, anlamsız) zayıf yıllar.
2. **NSV20 ek bilgi taşıyor mu?** Hayır. Ham IC pozitif ama Technical kontrolünden sonra partial IC tüm ufuklarda ≈0 (T+10 +0.005 [−0.012, +0.023]). NSV'nin bilgisi Technical/trend tarafından zaten taşınıyor.
3. **CMF+NSV birleşimi sağlamlığı artırıyor mu?** Hayır. PVFS partial IC (+0.036) CMF'nin tek başına değerinden (+0.045) düşük; NSV bileşeni sinyali seyreltiyor. Bu, protokol dışı bir gözlemdir; CMF-tek bileşenli bir skor ancak yeni bir protokol (V2) ile test edilebilir.
4. **MFI redundant mı?** Evet, hatta zararlı yönde: RSI+Technical kontrolünden sonra MFI partial IC negatif (−0.018 [−0.034, −0.002]; Holm sonrası anlamsız). MFI gelecekteki FlowScore'a girmemeli.
5. **Ufuklar arası istikrar:** PVFS/CMF partial IC T+1/5/10/20'nin hepsinde pozitif ve CI'lar 0'ı dışlıyor.
6. **Yıllar/rejimler arası istikrar:** PVFS 6 yılın 5'inde pozitif (2022 ≈0, 2026 ≈0 / n=169). Piyasa yukarı ve aşağı rejimlerinde benzer. Düşük likidite quintile'ı çıkarıldığında P1 azalıyor ama anlamlı kalıyor (+0.028 [+0.008, +0.047]).
7. **Maliyetlere dayanıklı mı?** Ham PVFS evet (Q5−Q1 örtüşmeyen net 20 bps +0.53%/10 seans, ama brüt CI 0'ı içeriyor). **Technical'a göre artıklaştırılmış** PVFS hayır: örtüşmeyen L−S brüt −0.17% [−0.85, +0.48], net 20 bps −0.42%. Günlük (örtüşen) tahmin ise +0.40% [−0.12, +0.92] — işaret, hangi 10'uncu günlerin örneklendiğine duyarlı; ekonomik büyüklük belirsiz. Devir oranı ~%60 / 10 seans.
8. **Production FlowAnalysisEngine altyapısı haklı mı?** Henüz değil. İstatistiksel ek bilgi var (P1 SUPPORTED), ama kilitli kapının maliyet koşulu sağlanmadı, survivorship yanlılığı çözülmedi ve 2026'da sinyal zayıf.

**Dikkat çeken ikincil bulgular (keşif amaçlı, önceden yön hipotezi yoktu):**
- H2 güçlü: Technical-pozitif (skor ≥ 15) içinde PVFS ≤ −20 olan grup, Technical-pozitif ortalamasının 10 seansta −1.01 puan altında kaldı [−1.52, −0.48], hit-rate −5.1 pp; Holm sonrası p≈0.028. Flow'un olası değeri "ek AL sinyali"nden çok **zayıf-akışlı AL'ları filtreleme** yönünde görünüyor. H1 (pozitif akış ek iyileştirme) Holm sonrası anlamlı değil.
- log(RV20) (anormal hacim) negatif partial IC (−0.034, Holm p≈0.011): yüksek göreli hacim sonraki 10 seansta düşük göreli getiriyle ilişkili. Mevcut `signal_classifier` yüksek hacmi yükseliş onayı olarak kullanıyor; bu gözlem ayrı bir Technical denetimi gerektirebilir (bu bilette yorumlanmadı, Technical metodolojisine dokunulmadı).

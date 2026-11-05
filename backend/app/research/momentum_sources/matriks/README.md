# Matriks — araştırma yer tutucusu

Durum: **NOT ACTIVE — WAITING FOR OFFICIAL DOCS/CREDENTIALS**

Bu paket yalnız araştırma altyapısıdır. Ücretli bir API entegrasyonu yoktur; resmi teknik doküman ve kimlik
bilgisi gelene kadar her bağlantı yöntemi `MatriksConfigurationRequired` fırlatır.

| Dosya | İçerik |
|---|---|
| `config.py` | `MATRIKS_TRANSPORT / BASE_URL / USERNAME / PASSWORD / API_KEY` (hiçbiri zorunlu değil; gizli değerler maskeli, loglanmaz). `DOCUMENTED_TRANSPORTS` boş. |
| `models.py` | `TradeTick`, `OrderFlowSnapshot`, `OrderBookSnapshot` (L1/L5/L10/L25) ve defter öznitelikleri. Yetenek listesi. |
| `field_mapping.py` | Kanonik alan → sağlayıcı alanı; hepsi `UNKNOWN`. Tahmin yok. |
| `adapter.py` | `momentum_pilot.sources` arayüzlerini uygular; hepsi yapılandırma ister. Yetenekler varsayılan `UNKNOWN`. |
| `matriks_smoke_test.py` | Gelecekteki kısa, sınırlı canlı test (AKBNK, ≤50 işlem, ≤60 sn). Şu an "NOT ACTIVE" ile çıkar. |
| `REQUIRED_VENDOR_INFO.md` | Sağlayıcıdan istenecek bilgiler. |

Kurallar:

* Rol her zaman `EXPERIMENTAL_SECONDARY`; Yahoo referans kalır, sağlayıcılar birleştirilmez.
* Depo: `app/research/momentum_sources/store/momentum_secondary/` (Yahoo deposundan ayrı; git dışı).
* `source_timestamp` sağlayıcının orijinal zamanı; yoksa `UNVERIFIED`, uydurulmaz. `received_at` geriye tarihlenmez.
* TRY / IST / BIST sembolden varsayılmaz; kimlik yalnız sağlayıcı meta verisinden (`MATCH/UNVERIFIED/MISMATCH`).
* Agresör tarafı yalnız belgelenmiş sağlayıcı alanından; aracı kurum (buyer/seller member) bilgisinden türetilmez.
* 2026-11-02 ve sonrası için ham toplama serbest; olay/etiket/alarm/metrik hesabı yasak.

Doküman geldiğinde sıra: `REQUIRED_VENDOR_INFO.md` maddelerini doldur → `DOCUMENTATION_REF` ve
`DOCUMENTED_TRANSPORTS` güncelle → `field_mapping.REGISTRY`'yi doküman referansıyla doldur → yetenekleri
`CapabilitySet.declare(..., documentation_ref)` ile beyan et → smoke testi çalıştır.

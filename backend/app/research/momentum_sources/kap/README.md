# Resmi KAP REST API — araştırma hazırlığı

Durum: **WAITING_FOR_AUTHORIZATION** — canlı entegrasyon yok.

Resmi KAP API'si vardır ancak abonelik/yetki ister (Borsa İstanbul veri dağıtım sözleşmesi, MKK yetkilendirmesi,
yetkili kaynak IP, aboneye verilen API anahtarı). Bu paket yalnız araştırma altyapısıdır; uç nokta, HTTP yöntemi,
kimlik doğrulama başlığı, sorgu parametresi veya yanıt alanı **uydurulmaz**.

| Dosya | İçerik |
|---|---|
| `config.py` | `KAP_BASE_URL`, `KAP_API_KEY`, `KAP_SOURCE_IP_MODE` (gizli değer maskeli). Erişim durumları; `DOCUMENTATION_REF` yok → `WAITING_FOR_AUTHORIZATION`. |
| `field_mapping.py` | Adı resmi olarak doğrulanmış 11 servis (`CONFIRMED_SERVICE`); yol/yöntem/şema `UNKNOWN`. Kanonik alanların hepsi `UNKNOWN`. Bildirim kimliği semantiği doğrulanmadı. |
| `models.py` | `KapDisclosure`, `KapMember`, `KapSecurity` — sembol/ISIN/borsa şirket adından çıkarılmaz. |
| `adapter.py` | `NewsEventSource` + soyut `KapServiceClient` (lastDisclosureIndex / disclosures / disclosureDetail anlamsal karşılıkları). Her çağrı `KapConfigurationRequired`. |
| `collector.py` | Artımlı toplama tasarımı: checkpoint → lastDisclosureIndex → daha yeni bildirimler → kalıcılaştır → checkpoint'i SONRA ilerlet. Ağ yok. |
| `kap_smoke_test.py` | Gelecekteki sınırlı smoke test (≤5 kayıt, yazım yalnız `--persist`). Şu an "NOT ACTIVE". |
| `REQUIRED_ACCESS.md` | Ön koşullar ve resmi kaynaktan istenecek teknik bilgiler. |

Kurallar:

* **Herkese açık kap.org.tr otomatik toplayıcı olarak kullanılmaz** (5 dakikalık kazıyıcı yok, tarayıcı çağrısı tersine mühendisliği yok). Herkese açık sayfalar yalnız elle dokümantasyon/doğrulama içindir.
* Depo: ikincil ad alanı (`momentum_secondary`), ayrı `kap_*` tabloları. Foreks kayıtlarıyla birleştirme yok; aynı olay iki sağlayıcıda ayrı kayıt olarak kalır.
* Mantıksal anahtar: sağlayıcı + resmi bildirim kimliği — yalnız kimlik semantiği resmi olarak doğrulanınca. Kayıtlar append-only; aynı kimlik farklı içerik → `DUPLICATE_CONFLICT`, orijinal değişmez.
* `source_timestamp` = resmi KAP yayın zamanı; `received_at` = gerçek alım anı (geriye dönük veride bile eşitlenmez). `received_at − source_timestamp` = arşiv keşif gecikmesi, ağ gecikmesi değil.
* 2026-11-02 ve sonrası ham bildirim toplanabilir; fiyat sonucu / V2 olayı / tepe / MFE / alarm / lead / aday sonucu ile birleştirme `HoldoutAccessError`.
* Entegrasyon soruları için resmi iletişim: `kapdestek@mkk.com.tr` (otomatik e-posta gönderilmez; soru listesi `REQUIRED_ACCESS.md`).

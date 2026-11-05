# Matriks'ten istenecek bilgiler (entegrasyon öncesi zorunlu)

Bu listedeki her madde yazılı/resmi kaynakla cevaplanmadan canlı entegrasyon yapılmaz. Cevaplar geldiğinde
kaynağı (doküman adı, sürüm, tarih) ile birlikte buraya işlenir.

## Erişim ve bağlantı
- [ ] Resmi API teknik dokümanı (sürüm ve tarih)
- [ ] Kimlik doğrulama yöntemi (API anahtarı / kullanıcı-parola / token yenileme)
- [ ] Mevcut taşıma yöntemleri (REST / MQTT / socket / XML) ve her birinin kapsamı
- [ ] Test ortamı (sandbox) erişimi
- [ ] Yeniden bağlanma semantiği (kopma sonrası boşluk doldurma var mı)
- [ ] Hız sınırları (istek / abonelik / mesaj başına)

## Semboller, zaman ve kimlik
- [ ] Sembol formatı (BIST pay kodu nasıl yazılıyor, pazar/seans eki var mı)
- [ ] Zaman dilimi (UTC mi, Europe/Istanbul mu, sağlayıcı yerel saati mi)
- [ ] Zaman damgası hassasiyeti (saniye / milisaniye / mikrosaniye) ve kaynağı (borsa mı, sağlayıcı mı)
- [ ] Borsa / pazar / para birimi meta verisi her kayıtta var mı

## İşlem (trade) verisi
- [ ] Trade tick şeması (alan adları, tipleri, birimleri)
- [ ] İşlem kimliği (trade_id) ve sıra numarası (sequence number) var mı
- [ ] Alıcı / satıcı aracı kurum (buyer/seller member) şeması
- [ ] Agresör tarafı (aggressor side) doğrudan veriliyor mu; veriliyorsa tanımı
- [ ] Tekrarlayan mesaj (duplicate) politikası ve düzeltme/iptal (trade correction) mesajları

## Analitik ve emir akışı
- [ ] "BIST Pay Piyasası Veri Analitikleri" alan listesi ve tanımları
- [ ] Emir akışı (order flow) alanları
- [ ] Emir girişi (order arrival) alanları
- [ ] Emir iptali (order cancel) alanları

## Emir defteri
- [ ] Defter güncelleme şeması
- [ ] Derinlik seviyeleri (L1 / L5 / L10 / L25 …)
- [ ] Snapshot mı delta mı; delta ise sıra numarası ve yeniden senkronizasyon kuralı

## Geçmiş veri
- [ ] Geçmiş tick / emir akışı / derinlik için yeniden oynatma (replay) mümkün mü, ne kadar geriye

## Lisans ve kullanım
- [ ] Lisans kısıtları
- [ ] Verinin yerel olarak saklanma izni (araştırma arşivi)
- [ ] Ekranda gösterilmeyen (non-display) / araştırma amaçlı kullanım izni
- [ ] Türetilmiş verinin (öznitelik, model çıktısı) kullanım/paylaşım koşulları

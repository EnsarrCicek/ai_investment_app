# Resmi KAP API — erişim ön koşulları ve istenecek bilgiler

Canlı entegrasyondan önce aşağıdakilerin hepsi yazılı/resmi kaynakla tamamlanmalıdır. Cevaplar kaynağıyla (doküman
adı, sürüm, tarih) birlikte buraya işlenir; ardından `config.DOCUMENTATION_REF`, `field_mapping.SERVICES` ve
`field_mapping.FIELDS` doküman referansıyla doldurulur.

## Resmi ön koşullar
- [ ] Borsa İstanbul veri dağıtım sözleşmesi
- [ ] MKK yetkilendirmesi
- [ ] Yetkili kaynak IP adres(ler)i
- [ ] Aboneye verilen API KEY

## Resmi olarak adı doğrulanmış servisler
`disclosures`, `disclosureDetail`, `downloadAttachment`, `lastDisclosureIndex`, `members`, `memberDetail`, `funds`,
`fundDetail`, `memberSecurities`, `blockedDisclosures`, `caEventStatus`

Her biri için gereken: uç nokta yolu, HTTP yöntemi, istek şeması, yanıt şeması, örnek yanıt.

## Hâlâ gereken teknik bilgiler
- [ ] Resmi temel adres (base URL)
- [ ] Kimlik doğrulama başlık biçimi
- [ ] İstek yöntemleri
- [ ] İstek şemaları
- [ ] Yanıt şemaları (alan adları, tipler, örnekler)
- [ ] Sayfalama semantiği
- [ ] Bildirim kimliği / indeks tekilliği ve monotonluğu (`lastDisclosureIndex` ↔ `disclosures` ilişkisi)
- [ ] Zaman dilimi
- [ ] Zaman damgası hassasiyeti (yayın zamanı alanı hangisi)
- [ ] Hız sınırları
- [ ] Yeniden deneme politikası
- [ ] Geçmişe dönük erişim sınırları
- [ ] Ek (attachment) boyut/adet sınırları
- [ ] Lisans ve yerel saklama koşulları (araştırma arşivi)
- [ ] Test / sandbox erişimi

## Resmi destek
Resmi KAP bilgisi entegrasyon sorularını **kapdestek@mkk.com.tr** adresine yönlendirir. Bu proje otomatik e-posta
göndermez; aşağıdaki liste elle iletilmek üzere hazırlanmıştır.

### Teknik soru listesi
1. Abonelik sonrası verilen API anahtarı hangi başlık/biçimle iletilir? Anahtar yenileme süreci nedir?
2. Kaynak IP yetkilendirmesi nasıl yapılır; birden fazla IP veya IP değişikliği nasıl bildirilir?
3. `lastDisclosureIndex` değeri tekil ve monoton artan mıdır? `disclosures` servisi bu indeksten sonrasını nasıl döndürür?
4. Bildirim kimliği ile bildirim indeksi aynı mıdır; bir bildirim düzeltilirse kimlik/indeks değişir mi?
5. Yayın zamanı hangi alandadır, hangi zaman dilimindedir ve hassasiyeti nedir?
6. Bildirimlerde sembol / ISIN / üye kodu nasıl verilir; birden fazla menkul kıymet içeren bildirimler nasıl gösterilir?
7. `blockedDisclosures` ve `caEventStatus` servislerinin anlamı ve kullanım koşulları nedir?
8. Sayfalama, en fazla kayıt sayısı ve hız sınırları nelerdir? 429/5xx durumunda önerilen yeniden deneme politikası nedir?
9. Geçmişe dönük ne kadar veri alınabilir? Ekler için boyut/adet sınırı var mı?
10. Verinin yerel araştırma arşivinde saklanması ve türetilmiş verinin kullanımı lisans açısından uygun mudur?
11. Test/sandbox ortamı var mı?

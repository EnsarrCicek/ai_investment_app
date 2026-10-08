/// Backend'in tek gerçek adresi — tüm *_api.dart dosyaları buradan okur.
/// Önceden her dosyada ayrı ayrı '10.0.2.2:8000' (yalnızca emulator'den
/// host'a erişim için) tanımlıydı; artık gerçek Cloud Run URL'i kullanılıyor,
/// böylece derlenen APK herhangi bir cihazdan/ağdan çalışabiliyor.
///
/// Yerel ağ denemesi için derleme anında değiştirilebilir:
/// `flutter build apk --dart-define=API_BASE_URL=http://<bilgisayar-ip>:8000`.
/// Parametre verilmezse production adresi kullanılır.
const String apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'https://ai-investment-backend-244094132223.europe-west1.run.app',
);

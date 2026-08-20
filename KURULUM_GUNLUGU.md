# Kurulum Günlüğü
## AI Destekli Yatırım Analiz Mobil Uygulaması — Yeni Bilgisayar Kurulum Kaydı

> Bu dosya, `AI_Yatirim_Analiz_Projesi_Ana_Dokuman.md` içinde planlanan kurulum adımlarının **gerçekte** bu bilgisayarda nasıl uygulandığını kayıt altına alır: hangi araç ne zaman kuruldu, hangi komut çalıştırıldı, doğrulama çıktısı ne oldu, hangi hatalarla karşılaşıldı ve nasıl çözüldü.
>
> Hesaplama mantığı (TechnicalScore, DecisionEngine formülü vb.) burada **tekrar edilmez** — bunlar için ana dokümana bakın. Bu dosya yalnızca kurulum/işlem kaydıdır.
>
> **Nasıl kullanılır:** Her araç kurulduğunda ilgili bölümü doldurun, özet tablosundaki durumu güncelleyin.

---

## 0.0 ÖNCE BURAYA BAKIN — Bu Depoyu (`git clone`) Yeni Bir Bilgisayara Çektiyseniz

Proje artık private bir GitHub deposunda (`https://github.com/EnsarrCicek/ai_investment_app`). **`git clone` size yalnızca kaynak kodu verir** — aşağıdakiler bilerek `.gitignore` ile depo dışında bırakılmıştır (ya makineye özel ya da gizli oldukları için) ve her yeni bilgisayarda **elle yeniden yapılmalıdır**:

| # | Eksik olan | Neden depoda değil | Nasıl giderilir |
|---|---|---|---|
| 1 | **Tüm geliştirme araçları** (Git, Flutter SDK, Dart, Android Studio+SDK+Emulator, Java, Python, Node.js, Firebase CLI, FlutterFire CLI, Google Cloud SDK) | Kod deposu değil, işletim sistemi düzeyinde kurulumlar | Bölüm 1-9 ve 27'deki komutları sırayla uygulayın (`flutter doctor -v` ile doğrulayın) |
| 2 | **`backend/.env`** | `.gitignore`'da (makineye özel ayar dosyası) | Elle oluşturun, tek satır yeterli: `FIREBASE_PROJECT_ID=ai-investment-app-2026` |
| 3 | **`backend/.venv`** (Python sanal ortamı) | `.gitignore`'da (makineye özel, taşınabilir değil) | `python -m venv .venv` → `pip install -r requirements.txt` (bkz. Bölüm 13) |
| 4 | **Flutter paket bağımlılıkları** | `.dart_tool/`, `build/` `.gitignore`'da | Proje kökünde `flutter pub get` |
| 5 | **Google Cloud kimlik doğrulaması (ADC)** | Kimlik bilgisi dosyası, hiçbir yerde saklanmaz/taşınmaz | O makinede `gcloud auth application-default login` + `gcloud auth application-default set-quota-project ai-investment-app-2026` (bkz. Bölüm 16 ve 27) |
| 6 | **Firebase CLI girişi** (`firebase login`) | Kimlik bilgisi, makineye özel | O makinede `firebase login` (bkz. Bölüm 8) |
| 7 | **Windows Geliştirici Modu** (yalnızca Windows'ta native plugin build'i için) | İşletim sistemi ayarı | Ayarlar → Gizlilik ve güvenlik → Geliştiriciler için |
| 8 | **Android Emulator kullanılacaksa: Hypervisor** (Windows Hypervisor Platform / WHPX ya da macOS'ta HAXM gerekmez, Apple Silicon/Intel HVF otomatik) | İşletim sistemi/donanım özelliği | Windows'ta: `Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -All` + yeniden başlatma (bkz. Bölüm 27) |

**Depoda olan, dokunmanıza gerek olmayanlar:** Firebase proje bağlantısı (`lib/firebase_options.dart`, `android/app/google-services.json`) — bunlar gizli anahtar değil, client config dosyaları, zaten repoda. Firebase projesini (`ai-investment-app-2026`) veya Firestore veritabanını **yeniden oluşturmayın**, zaten bulutta mevcut ve tüm veriler orada duruyor.

**Özetle sıra:** `git clone` → Bölüm 1-9 (araçlar) → `flutter pub get` → Bölüm 13 (venv) → Bölüm 27'deki `gcloud`/Firebase login adımları → Bölüm 27 (uçtan uca test).

---

## 0. Kurulum Durumu Özet Tablosu

| Araç | Durum | Kurulum Tarihi | Doğrulama Komutu |
|---|---|---|---|
| Git | ✅ Tamamlandı | 13.08.2026 | `git --version` |
| VS Code | ✅ Tamamlandı | 13.08.2026 | `code --version` |
| Flutter SDK | ✅ Tamamlandı | 13.08.2026 | `flutter --version` |
| Dart SDK | ✅ Tamamlandı | 13.08.2026 | `dart --version` |
| Android Studio | ✅ Tamamlandı | 13.08.2026 | |
| Android SDK | ✅ Tamamlandı | 13.08.2026 | `flutter doctor -v` |
| Android Emulator | ✅ Tamamlandı | 13.08.2026 | `flutter doctor -v` |
| Android Lisansları | ✅ Tamamlandı | 13.08.2026 | `flutter doctor --android-licenses` |
| Python | ✅ Tamamlandı | 13.08.2026 | `python --version` |
| Node.js | ✅ Tamamlandı | 13.08.2026 | `node --version` / `npm --version` |
| Firebase CLI | ✅ Tamamlandı | 13.08.2026 | `firebase --version` |
| Firebase Login | ✅ Tamamlandı | 13.08.2026 | `firebase login` |
| FlutterFire CLI | ✅ Tamamlandı | 13.08.2026 | `flutterfire --version` |
| Flutter Projesi (`flutter create`) | ✅ Tamamlandı | 13.08.2026 | proje yapısı doğrulandı |
| Firebase Projesine Bağlama (`flutterfire configure`) | ✅ Tamamlandı | 13.08.2026 | `lib\firebase_options.dart` kontrolü |
| Flutter Firebase Paketleri (core/auth/firestore) | ✅ Tamamlandı | 13.08.2026 | `pubspec.yaml` kontrolü |
| Python venv + Backend Paketleri | ✅ Tamamlandı | 13.08.2026 | `pip list` |

---

## 1. Git

**Ne kuruldu / neden gerekli:** Sürüm kontrolü için. Proje geliştirmenin temel araçlarından biri.

**Kurulum komutu:**
```powershell
winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
```
Kurulan sürüm: Git 2.55.0.3 (winget üzerinden otomatik olarak en güncel sürüm bulundu). Kurulum sırasında yönetici izni istendi ve onaylandı.

**Doğrulama komutu ve çıktısı:**
```powershell
git --version
→ git version 2.55.0.windows.3
```
Not: Kurulumdan hemen sonra `git` komutu mevcut PowerShell oturumunda tanınmadı ("CommandNotFoundException") çünkü PATH değişkeni oturuma yeni yansımamıştı. Şu komutla PATH'i oturum içinde yenileyip tekrar denemek çözdü:
```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
```
Yeni bir terminal/PowerShell penceresi açmak da aynı sorunu çözer.

**Karşılaşılan hata / çözüm:**
"git : The term 'git' is not recognized..." → PATH oturum içinde güncel değildi. Yukarıdaki PATH yenileme komutu veya yeni terminal açmak çözdü.

**Tarih / Not:**
13.08.2026 — Git başarıyla kuruldu ve doğrulandı.


---

## 2. VS Code

**Ne kuruldu / neden gerekli:** Ana kod editörü.

**Kurulum komutu:**
```powershell
winget install --id Microsoft.VisualStudioCode -e --source winget --accept-package-agreements --accept-source-agreements
```
Not: winget "Found an existing package already installed" dedi — VS Code bu bilgisayarda daha önceden kurulmuş olduğu ortaya çıktı, yeni bir kurulum yapılmadı.

**Doğrulama komutu ve çıktısı:**
```powershell
code --version
→ 1.133.0
  a5b500951314efd502d07465bd138dfbd714a960
  x64
```
Not: Git adımında olduğu gibi, `code` komutu ilk denemede PATH oturuma yansımadığı için tanınmadı; PATH'i oturum içinde yenileyince (`$env:Path = ...Machine + User`) çalıştı.

**Karşılaşılan hata / çözüm:**
"code : The term 'code' is not recognized..." → PATH oturum içinde güncel değildi. PATH yenileme veya yeni terminal açmak çözdü.

**Tarih / Not:**
13.08.2026 — VS Code zaten kuruluydu, doğrulandı.


---

## 3. Flutter SDK

**Ne kuruldu / neden gerekli:** Mobil uygulamanın yazılacağı framework. Dart SDK Flutter ile birlikte gelir.

**Kurulum yöntemi:** winget'te resmi bir "Flutter SDK" paketi bulunmadığı için (yalnızca ayrı bir `Google.DartSDK` paketi ve flutter etiketli üçüncü parti uygulamalar mevcut) ana dokümanın 50. bölümündeki manuel zip yöntemi kullanıldı.

**Kurulum adımları:**
1. Güncel stable sürüm bilgisi resmi Flutter release API'sinden sorgulandı:
   ```powershell
   Invoke-RestMethod -Uri "https://storage.googleapis.com/flutter_infra_release/releases/releases_windows.json"
   ```
   → Sonuç: Flutter 3.47.0 (stable, 12.08.2026 tarihli)
2. Zip indirildi (~1,84 GB, indirme büyük olduğu için arka planda birkaç dakika sürdü):
   ```powershell
   Invoke-WebRequest -Uri "https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_3.47.0-stable.zip" -OutFile "...\flutter_windows_3.47.0-stable.zip"
   ```
3. `C:\development\flutter` altına çıkarıldı:
   ```powershell
   Expand-Archive -Path "...\flutter_windows_3.47.0-stable.zip" -DestinationPath "C:\development" -Force
   ```
4. İndirilen zip dosyası silindi (SDK zaten çıkarıldığı için gerek kalmadı).

**SDK dizini:**
```text
C:\development\flutter
```

**PATH:** `C:\development\flutter\bin` kullanıcı PATH ortam değişkenine eklendi (kullanıcı onayı alınarak).

**Doğrulama komutu ve çıktısı:**
```powershell
flutter --version
→ Flutter 3.47.0 • channel stable • https://github.com/flutter/flutter.git
  Framework • revision 4cf2416426 (2 days ago) • 2026-08-11
  Engine • hash 59d54a2b2896a6bbf356c94b7fac7b9e235bdacd
  Tools • Dart 3.13.0 • DevTools 2.60.0

dart --version
→ Dart SDK version: 3.13.0 (stable) on "windows_x64"
```

**Karşılaşılan hata / çözüm:**
`winget install --id=Google.Flutter` → "No package found matching input criteria." Flutter SDK'nın resmi bir winget paketi yok. Manuel zip + PATH yöntemine geçildi (ana doküman bölüm 50).

**Tarih / Not:**
13.08.2026 — Flutter 3.47.0 ve Dart 3.13.0 başarıyla kuruldu ve doğrulandı.


---

## 4. Android Studio + SDK + Emulator

**Ne kuruldu / neden gerekli:** Android geliştirme, SDK bileşenleri ve emulator için.

**Kurulum yöntemi:** Android Studio winget ile kuruldu (IDE olarak). Ancak SDK bileşenleri Android Studio'nun ilk-açılış kurulum sihirbazı (GUI, interaktif) yerine, tamamen komut satırından **Android SDK Command-line Tools** ile kuruldu — bu, otomasyonu bozan GUI adımlarını atlamayı sağladı.

**Kurulum adımları:**
1. Android Studio kuruldu:
   ```powershell
   winget install --id Google.AndroidStudio -e --source winget --accept-package-agreements --accept-source-agreements
   ```
   → Android Studio 2026.1.3.7 kuruldu.
2. Android SDK "command line tools only" indirildi (resmi indirme sayfasından güncel sürüm bulundu: build 15859902):
   ```powershell
   Invoke-WebRequest -Uri "https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip" -OutFile "...\commandlinetools-win-15859902_latest.zip"
   ```
   Not: İlk denemede `edgedl.me.gvt1.com` üzerinden bir link denendi ve 404 döndü; doğru/kalıcı indirme deseni `dl.google.com/android/repository/...` olduğu ortaya çıktı.
3. Zip, `sdkmanager`'ın beklediği klasör yapısına (`cmdline-tools\latest\bin\...`) göre `C:\Android\sdk\cmdline-tools\latest` altına çıkarıldı.
4. `ANDROID_HOME = C:\Android\sdk` kullanıcı ortam değişkeni olarak eklendi; `cmdline-tools\latest\bin` ve `platform-tools` PATH'e eklendi (kullanıcı onayıyla).
5. `sdkmanager --licenses` ile tüm SDK lisansları kabul edildi.
   Not: `sdkmanager` Java gerektiriyor ("JAVA_HOME is not set and no 'java' command could be found"). Android Studio'nun kendi JBR'ı (`C:\Program Files\Android\Android Studio\jbr`) `JAVA_HOME` olarak kullanıldı — ayrıca bir JDK kurmaya gerek kalmadı.
   Not 2: PowerShell'den doğrudan pipe ile "y" cevapları göndermek ilk denemede işe yaramadı (sdkmanager interaktif "Review licenses (y/N)?" adımında takıldı); bir cevap dosyası (`y\n` satırları) oluşturup `cmd /c "sdkmanager --licenses < cevaplar.txt"` ile yönlendirmek çalıştı.
6. Aşağıdaki SDK bileşenleri kuruldu:
   ```powershell
   sdkmanager "platform-tools" "build-tools;37.0.0" "platforms;android-36" "emulator" "system-images;android-36;google_apis;x86_64"
   ```
   (android-36, o sırada mevcut en güncel stabil — beta olmayan — platform sürümüydü; x86_64 imajı, bu bilgisayarın AMD64/Intel mimarisiyle uyumlu olduğu için seçildi.)
7. Bir Android Sanal Cihazı (AVD) oluşturuldu:
   ```powershell
   avdmanager create avd -n "Pixel_7_API_36" -k "system-images;android-36;google_apis;x86_64" -d "pixel_7"
   ```
   → `Pixel_7_API_36` (Android 16 "Baklava", google_apis/x86_64) oluşturuldu.
   Not: `avdmanager` bu komutta bir `devices.xml` hata mesajı gösterdi ama AVD'nin aslında başarıyla oluşturulduğu `avdmanager list avd` ile doğrulandı — hata kozmetikti.

**Kurulan bileşenler:**
- [x] Android SDK (`C:\Android\sdk`)
- [x] Android SDK Platform (android-36)
- [x] Android SDK Platform-Tools
- [x] Android SDK Build-Tools (37.0.0)
- [x] Android SDK Command-line Tools
- [x] Android Emulator (+ AVD: Pixel_7_API_36)

**Doğrulama komutu ve çıktısı:**
```powershell
flutter doctor -v
→ [√] Android toolchain - develop for Android devices (Android SDK version 37.0.0)
    • Android SDK at C:\Android\sdk
    • Emulator version 37.1.11.0
    • Platform android-36, build-tools 37.0.0
    • ANDROID_HOME = C:\Android\sdk
    • Java binary at: C:\Program Files\Android\Android Studio\jbr\bin\java
    • Java version OpenJDK Runtime Environment (build 25.0.2+-15348964-b329.117)
    • All Android licenses accepted.
```

**Karşılaşılan hata / çözüm:**
- `winget install --id=Google.Flutter` (Flutter için değil ama ilgili not) → bkz. bölüm 3.
- Command-line tools indirme linki (`edgedl.me.gvt1.com`) 404 verdi → doğru domain `dl.google.com` kullanıldı.
- `sdkmanager`: "JAVA_HOME is not set" → Android Studio JBR'ı JAVA_HOME olarak ayarlandı (hem oturumda hem kalıcı olarak, bkz. not altında).
- `sdkmanager --licenses` pipe ile interaktif cevap almadı → cevap dosyası + `cmd /c "... < dosya"` yönlendirmesiyle çözüldü.
- `avdmanager create avd -d pixel_7`: "Could not load devices from ...\devices.xml" hatası gösterdi ama AVD gerçekte oluşmuştu (kozmetik hata).

**Tarih / Not:**
13.08.2026 — Android Studio, SDK, build-tools, platform, emulator ve bir AVD (Pixel_7_API_36) başarıyla kuruldu ve `flutter doctor -v` ile doğrulandı. Ayrıca `JAVA_HOME` kullanıcı onayıyla kalıcı ortam değişkeni olarak eklendi (`C:\Program Files\Android\Android Studio\jbr`).

---

## 5. Android Lisansları

**Kurulum komutu:** Bölüm 4'te `sdkmanager --licenses` ile birlikte halloldu (ayrı bir `flutter doctor --android-licenses` adımına gerek kalmadı).

**Doğrulama komutu ve çıktısı:**
```powershell
flutter doctor -v
→ All Android licenses accepted.
```

**Karşılaşılan hata / çözüm:**
Bkz. bölüm 4 — pipe ile interaktif "y" gönderme sorunu.

**Tarih / Not:**
13.08.2026 — Tüm lisanslar kabul edildi.


---

## 6. Python

**Ne kuruldu / neden gerekli:** Backend (FastAPI) için.

**Kurulum komutu:**
```powershell
winget install --id Python.Python.3.13 -e --source winget --accept-package-agreements --accept-source-agreements
```

**Doğrulama komutu ve çıktısı:**
```powershell
python --version
→ Python 3.13.15

pip --version
→ pip 26.2.1 from C:\Users\Nolto TC\AppData\Local\Programs\Python\Python313\Lib\site-packages\pip (python 3.13)
```

**Karşılaşılan hata / çözüm:**
İlk kontrolde `python --version` "Python bulunamadı" mesajı verdi — bu, Windows'un Python kurulu değilken devreye giren "Uygulama Yürütme Takma Adı" (App Execution Alias) stub'ıydı, gerçek bir hata değildi; winget ile kurulumdan sonra normal şekilde çalıştı.

**Tarih / Not:**
13.08.2026 — Python 3.13.15 ve pip 26.2.1 kuruldu ve doğrulandı.


---

## 7. Node.js

**Ne kuruldu / neden gerekli:** Firebase CLI'nin çalışması için gerekli.

**Kurulum komutu:**
```powershell
winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements
```

**Doğrulama komutu ve çıktısı:**
```powershell
node --version
→ v24.19.0

npm --version
→ 11.17.0
```

**Karşılaşılan hata / çözüm:**
Yok — sorunsuz kuruldu.

**Tarih / Not:**
13.08.2026 — Node.js v24.19.0 (LTS) ve npm 11.17.0 kuruldu ve doğrulandı.


---

## 8. Firebase CLI + Login

**Kurulum komutu:**
```powershell
npm install -g firebase-tools
```

**Doğrulama komutu ve çıktısı:**
```powershell
firebase --version
→ 15.26.0
```

**Giriş:**
```powershell
firebase login --no-localhost
```
Standart `firebase login` tarayıcıyı otomatik açamadı (bu ortamda beklenen bir durum) ve `--no-localhost` moduna düştü: bir oturum ID'si ve manuel ziyaret edilecek bir `auth.firebase.tools` linki verdi. Kullanıcı bu linki kendi tarayıcısında açıp Google hesabıyla giriş yaptı, sayfa bir doğrulama kodu (`4/0AXEQ...` ile başlayan) üretti. Bu kod ile:
```powershell
firebase login "4/0AXEQxIDowObxB1MNdbocnu8eU61RuwP-gdrFQW-bUt79uxO5lV3Jz39hCAUeNiqj1LEiIQ"
```
çalıştırılarak giriş tamamlandı: **"Success! Logged in as ensarcckk@gmail.com"**.

Kullanılan hesap: ensarcckk@gmail.com

**Karşılaşılan hata / çözüm:**
1. İlk `firebase login` denemesi (localhost modunda) bir link üretti ama arkasında Node.js/libuv'a özgü kozmetik bir çökme oldu (`Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)`, exit code 9); bu bilinen bir Windows/Node sorunu, işlevi bozmuyor. `--no-localhost` ile tekrar denendi ve temiz (exit code 0) sonuç alındı.
2. Login başarılı olduktan sonra `firebase projects:list` şu hatayı verdi: `getaddrinfo ENOENT firebase.googleapis.com` — yani `*.googleapis.com` alan adları DNS'te çözümlenemiyordu (`0.0.0.0` dönüyordu), oysa `google.com` normal çözümleniyordu. Kök neden: Wi-Fi ağının router DNS'i (192.168.1.1) `googleapis.com` alt alan adlarını engelliyordu (aile/güvenlik filtresi ya da reklam engelleyici DNS listesi olabilir). **Çözüm:** Bu bilgisayarın Wi-Fi adaptöründe DNS sunucuları yönetici izniyle `8.8.8.8` / `8.8.4.4` (Google Public DNS) olarak değiştirildi (`Set-DnsClientServerAddress`, UAC onayı gerekti), ardından `ipconfig /flushdns` yapıldı ve sorun çözüldü.
   - **Önemli not:** Bu DNS değişikliği kalıcıdır (Wi-Fi adaptörü ayarı). Router'a bağlanan diğer cihazlar etkilenmez, sadece bu bilgisayar. İleride farklı bir ağa (ör. başka bir Wi-Fi) bağlanılırsa oradaki DNS ayrı olacağından bu sorun tekrar görülebilir; aynı çözüm (adaptör DNS'ini 8.8.8.8/8.8.4.4 yapmak) uygulanabilir.

**Tarih / Not:**
13.08.2026 — Firebase CLI 15.26.0 kuruldu, login tamamlandı (ensarcckk@gmail.com), DNS engeli tespit edilip çözüldü.


---

## 9. FlutterFire CLI

**Kurulum komutu:**
```powershell
dart pub global activate flutterfire_cli
```

**Doğrulama komutu ve çıktısı:**
```powershell
flutterfire --version
→ 1.4.1
```

**PATH sorunu yaşandı mı?** Evet — ana dokümanda öngörüldüğü gibi. Dart pub-cache bin klasörü:
```text
C:\Users\Nolto TC\AppData\Local\Pub\Cache\bin
```
kullanıcı onayıyla kullanıcı PATH'ine eklendi, ardından `flutterfire --version` çalıştı.

**Karşılaşılan hata / çözüm:**
"flutterfire : The term 'flutterfire' is not recognized..." → Dart global bin klasörü PATH'te değildi. Yukarıdaki klasör PATH'e eklenince çözüldü.

**Tarih / Not:**
13.08.2026 — FlutterFire CLI 1.4.1 kuruldu ve doğrulandı.


---

## 10. Flutter Projesi Oluşturma

**Kurulum komutu:**
```powershell
flutter create ai_investment_app
```
(ana dokümandaki gibi `flutter run` ile emulator'de otomatik açılış bu adımda çalıştırılmadı — emulator boot süresi uzun olduğu için proje yapısı dosya bazında doğrulandı; ilk gerçek `flutter run` denemesi, geliştirmeye başlarken/UI değişikliklerinde yapılacak)

**Proje konumu:**
```text
C:\Users\Nolto TC\Projects\ai_investment_app
```

**Doğrulama:** `pubspec.yaml`, `lib\main.dart` ve tüm platform klasörleri (android, ios, web, windows, linux, macos) oluştu; "Wrote 131 files. All done!" çıktısı alındı.
- [x] Proje dosya yapısı doğrulandı
- [ ] `flutter run` ile emulator'de gerçek açılış testi (henüz yapılmadı — bkz. not)

**Tarih / Not:**
13.08.2026 — Proje oluşturuldu. Gerçek cihaz/emulator üzerinde çalıştırma testi ileride (geliştirmeye başlarken) yapılacak.


---

## 11. Firebase Projesine Bağlama

**Firebase projesi oluşturma:**
Hesapta zaten "siirolog" (`siirolog-51194`) adında, bu projeyle ilgisi olmayan başka bir Firebase projesi vardı. Bu uygulama için **yeni, özel bir proje** oluşturuldu:
```powershell
firebase projects:create ai-investment-app-2026 --display-name "AI Yatirim Analiz"
```

**Kurulum komutu:**
```powershell
flutterfire configure --project=ai-investment-app-2026 --platforms=android,ios,web --yes
```

**Firebase proje adı:** AI Yatirim Analiz
**Proje ID:** ai-investment-app-2026
**Proje numarası:** 244094132223
**Firebase Console:** https://console.firebase.google.com/project/ai-investment-app-2026/overview

**Seçilen platformlar:** android, ios, web
(Windows/macOS/Linux masaüstü platformları bu adımda dahil edilmedi — ana doküman mobil odaklı MVP tanımlıyor; gerekirse ileride `flutterfire configure` tekrar çalıştırılarak eklenebilir.)

**Oluşan Firebase App ID'leri:**
```text
web       1:244094132223:web:db2c6d5e90a4eda64a51ca
android   1:244094132223:android:7933abefc3f4b7e64a51ca
ios       1:244094132223:ios:f1d1fdbb78ce8ecf4a51ca
```

**Doğrulama:** `lib\firebase_options.dart` ve `android\app\google-services.json` dosyalarının oluştuğu doğrulandı.

**Karşılaşılan hata / çözüm:**
İlk denemede `flutterfire configure --project=ai-investment-app-2026 ...` şu hatayı verdi: `FirebaseProjectNotFoundException: Firebase project id "ai-investment-app-2026" could not be found`. Sebep: proje saniyeler önce oluşturulmuştu ve Firebase/Google Cloud tarafında tam yayılması (propagation) birkaç saniye sürdü. ~20 saniye beklenip `firebase projects:list` ile projenin göründüğü doğrulandıktan sonra `flutterfire configure` tekrar çalıştırıldı ve başarılı oldu.

**Tarih / Not:**
13.08.2026 — "ai-investment-app-2026" adında yeni Firebase projesi oluşturuldu ve Flutter projesine (android/ios/web) başarıyla bağlandı.


---

## 12. Flutter Firebase Paketleri

**Kurulum komutu:**
```powershell
flutter pub add firebase_core
flutter pub add firebase_auth
flutter pub add cloud_firestore
```

**Sonuç (pubspec.yaml):**
```yaml
firebase_core: ^4.13.0
firebase_auth: ^6.5.7
cloud_firestore: ^6.8.0
```

**Gerektiğinde eklenecekler (opsiyonel):**
- [ ] firebase_storage
- [ ] firebase_messaging
- [ ] firebase_crashlytics
- [ ] firebase_analytics
- [ ] firebase_app_check

**Karşılaşılan hata / çözüm:**
Komutlar çalışırken "exit code 1" ile göründü ve şu uyarıyı verdi: "Building with plugins requires symlink support. Please enable Developer Mode in your system settings." Bu bir hata değil, Windows'ta Firebase gibi native plugin içeren paketlerle build alabilmek için gereken bir sistem ayarıydı — paketlerin kendisi pubspec.yaml'a sorunsuz eklenmişti. Çözüm: Windows Geliştirici Modu, registry üzerinden (yönetici izniyle, `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock\AllowDevelopmentWithoutDevLicense = 1`) etkinleştirildi. UAC onayı gerekti.

**Tarih / Not:**
13.08.2026 — firebase_core, firebase_auth, cloud_firestore eklendi. Windows Geliştirici Modu ayrıca etkinleştirildi (yönetici/UAC onayıyla).


---

## 13. Backend Sanal Ortamı + İlk Paketler

**Kurulum komutu:**
```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\pip.exe install fastapi uvicorn pydantic firebase-admin python-dotenv httpx pandas numpy
```

**Backend klasör konumu:**
```text
C:\Users\Nolto TC\Projects\ai_investment_app\backend
```

**Doğrulama:**
```powershell
pip list
→ fastapi 0.141.1, uvicorn 0.52.2, pydantic 2.13.4, firebase_admin 7.5.0,
  python-dotenv 1.2.2, httpx 0.28.1, pandas 3.0.5, numpy 2.5.2 (+ bağımlılıklar)
```

**Karşılaşılan hata / çözüm:**
Yok — sorunsuz kuruldu.

**Tarih / Not:**
13.08.2026 — venv oluşturuldu, tüm ilk backend paketleri kuruldu ve doğrulandı. Ayrıca:
- `requirements.txt` oluşturuldu (`pip freeze` çıktısı).
- Ana dokümanın 62. bölümündeki backend klasör yapısı (`app/api`, `app/core`, `app/engines/{technical,event,macro,decision,explanation}`, `app/models`, `app/repositories`, `app/services`, `app/schemas`, `app/utils`, `tests/`, `app/main.py`, `.env`, `README.md`) baştan oluşturuldu.


---

## 14. İlk Teknik Kontrol Noktası (Tam Doğrulama)

Ana doküman bölüm 89'a göre, aşağıdaki komutların tamamı çalışmalıdır. Kritik uygulama geliştirme aşamasına geçmeden önce hepsini çalıştırıp çıktıyı buraya yapıştırın:

```powershell
git --version
code --version
flutter --version
dart --version
python --version
node --version
npm --version
firebase --version
flutterfire --version
flutter doctor -v
```

**Çıktı:**
```text
git version 2.55.0.windows.3
code 1.133.0
Flutter 3.47.0 • channel stable • Tools • Dart 3.13.0 • DevTools 2.60.0
Dart SDK version: 3.13.0 (stable)
Python 3.13.15
node v24.19.0
npm 11.17.0
firebase-tools 15.26.0
flutterfire_cli 1.4.1
flutter doctor -v → Android toolchain [√], Windows Version [√], Chrome [√],
                     Connected device [√], Network resources [√]
                     (Visual Studio [X] — bu proje için gerekli değil, mobil odaklı)
```

**Tüm kontroller başarılı mı?**
- [x] Evet — bir sonraki aşamaya (geliştirmeye başlama / AŞAMA 9: Asset modeli) geçilebilir
- [ ] Hayır — eksikler:

---

## 15. Genel Notlar / Kararlar

Kurulum sırasında alınan ek kararlar, ana dokümandaki plandan sapmalar (örn. farklı bir SDK dizini, farklı bir PATH yöntemi, farklı Firebase proje adı vb.) buraya not edilir.

- **Proje konumları:** Flutter projesi `C:\Users\Nolto TC\Projects\ai_investment_app`, backend `C:\Users\Nolto TC\Projects\ai_investment_app\backend` altında. Ana teknik doküman ve bu kurulum günlüğü `C:\Users\Nolto TC\Downloads\` altında kaldı (istenirse ileride proje klasörüne taşınabilir).
- **Android SDK konumu:** `C:\Android\sdk` (ana dokümanda önerilen `C:\development\flutter` deseniyle tutarlı ayrı bir kök klasör).
- **Ortam değişkenleri (kullanıcı düzeyinde) eklendi:** `ANDROID_HOME`, `JAVA_HOME`; PATH'e `C:\development\flutter\bin`, `C:\Android\sdk\cmdline-tools\latest\bin`, `C:\Android\sdk\platform-tools`, `C:\Users\Nolto TC\AppData\Local\Pub\Cache\bin` eklendi.
- **Windows Geliştirici Modu** etkinleştirildi (registry, yönetici onayıyla) — Flutter'ın Firebase gibi native plugin içeren paketlerle build alabilmesi için gerekliydi.
- **Ağ/DNS düzeltmesi:** Bu bilgisayarın Wi-Fi DNS'i router üzerinden `*.googleapis.com` alan adlarını engelliyordu; adaptör DNS'i `8.8.8.8` / `8.8.4.4`'e çevrilerek çözüldü (bkz. bölüm 8). Bu, Firebase/Google API'leriyle çalışırken tekrar karşılaşılabilecek bir ağ kısıtlamasıdır, kurulumla ilgili bir hata değildir.
- **Mevcut/ilgisiz Firebase projesi:** Hesapta "siirolog" (`siirolog-51194`) adında, bu projeyle alakasız başka bir Firebase projesi bulundu ve olduğu gibi bırakıldı; bu uygulama için ayrı, yeni bir proje (`ai-investment-app-2026`) oluşturuldu.
- **Kapsam dışı bırakılanlar:** `flutter run` ile emulator'de gerçek uygulama açılış testi ve masaüstü (Windows/macOS/Linux) Firebase platformları bu oturumda yapılmadı — geliştirmeye başlarken ele alınacak.

---

## 16. AŞAMA 9 — Asset Modeli

Ana dokümanın 82. bölümündeki geliştirme sırasına göre ilk gerçek kodlama adımı: `assets` collection'ı (bölüm 29) için model, repository ve API katmanı.

**Oluşturulan dosyalar (backend):**
```text
app/core/config.py            → .env okuma (GOOGLE_APPLICATION_CREDENTIALS, FIREBASE_PROJECT_ID)
app/core/firebase.py          → Firebase Admin SDK / Firestore client başlatma
app/models/asset.py           → Asset (Pydantic): symbol, name, market, asset_type, currency, active
app/repositories/asset_repository.py → Firestore "assets" koleksiyonu için upsert / get_by_symbol / list_active
app/api/assets.py             → GET /assets, GET /assets/{symbol}
app/main.py                   → FastAPI app, GET /health, assets router bağlantısı
scripts/seed_assets.py        → Ana dokümanın 68. bölümündeki 6 test hissesini (THYAO, ASELS, GARAN,
                                 AKBNK, EREGL, TUPRS) Firestore'a yazan seed script'i
.gitignore                    → .venv/, .env, firebase-service-account.json, __pycache__/ hariç tutuldu
.env                          → FIREBASE_PROJECT_ID=ai-investment-app-2026
```

**Firestore'a gerçek bağlantı kurulumu (kritik ön koşul):**
Asset repository'nin gerçekten çalışabilmesi için backend'in Firestore'a kimlik doğrulamasıyla bağlanması gerekiyordu. Bu, ayrı bir kurulum zinciri gerektirdi:

1. **Google Cloud SDK (gcloud) kuruldu:**
   ```powershell
   winget install --id Google.CloudSDK -e --source winget --accept-package-agreements --accept-source-agreements
   ```
   → Google Cloud SDK 580.0.0.

2. **Application Default Credentials (ADC) girişi** — `gcloud auth login` ve `gcloud auth application-default login`'in headless/arka plan modunda çalıştırılması "EOFError: EOF when reading a line" ile çöktü (interaktif kod isteme adımı, kapalı stdin ile uyuşmuyor); ayrıca yeni gcloud sürümlerinde `--no-launch-browser` yerine iki-makineli bir "remote-bootstrap" akışına geçilmiş, tek makineden headless kod yapıştırma artık desteklenmiyor. **Çözüm:** Kullanıcının kendi (gerçek masaüstü/tarayıcı erişimi olan) teriminalinde şu komutu çalıştırması istendi:
   ```powershell
   gcloud auth application-default login
   ```
   Kullanıcı tarayıcıda `ensarcckk@gmail.com` ile giriş yaptı; `%APPDATA%\gcloud\application_default_credentials.json` dosyası oluştu.

3. Kota projesi ayarlandı:
   ```powershell
   gcloud auth application-default set-quota-project ai-investment-app-2026
   gcloud config set project ai-investment-app-2026
   ```

4. **Firestore API etkinleştirme ve veritabanı oluşturma** — `firebase firestore:databases:list` ilk denemede "Cloud Firestore API has not been used in this project before or it is disabled" hatası verdi (yeni Firebase projelerinde Firestore otomatik provision edilmiyor). `gcloud` CLI'nin kendi aktif hesabı (`gcloud auth login`, ADC'den ayrı bir kimlik deposu) ayarlı olmadığından `gcloud firestore databases create` doğrudan kullanılamadı. **Çözüm:** ADC'den alınan bir erişim token'ı (`gcloud auth application-default print-access-token`) ile doğrudan REST API'ler çağrıldı:
   ```powershell
   # 1) Firestore API'sini etkinleştir
   POST https://serviceusage.googleapis.com/v1/projects/ai-investment-app-2026/services/firestore.googleapis.com:enable

   # 2) Native mode Firestore veritabanı oluştur (bölge: eur3)
   POST https://firestore.googleapis.com/v1/projects/ai-investment-app-2026/databases?databaseId=(default)
   Body: { "type": "FIRESTORE_NATIVE", "locationId": "eur3" }
   ```
   `firebase firestore:databases:list` ile doğrulandı: `projects/ai-investment-app-2026/databases/(default)` (STANDARD / FIRESTORE_NATIVE).

5. **Kimlik bilgisi stratejisi:** Ayrı bir servis hesabı JSON anahtarı oluşturmaya gerek kalmadı — `app/core/firebase.py`, `GOOGLE_APPLICATION_CREDENTIALS` .env'de tanımlı değilse otomatik olarak `credentials.ApplicationDefault()`'a düşecek şekilde yazıldığından, adım 2'de oluşan ADC dosyası doğrudan yeterli oldu. (İleride prod ortamında gerçek bir servis hesabı anahtarı kullanılması önerilir; `.gitignore`'da `firebase-service-account.json` şimdiden hariç tutuldu.)

**Doğrulama:**
```powershell
python scripts\seed_assets.py
→ Seeded THYAO, ASELS, GARAN, AKBNK, EREGL, TUPRS (6 kayıt)

uvicorn app.main:app --host 127.0.0.1 --port 8000
GET /health         → {"status": "ok"}
GET /assets          → 6 kayıt (JSON array)
GET /assets/THYAO    → {"symbol": "THYAO", "name": "Türk Hava Yolları", ...}
```
Firestore'daki verinin gerçekten doğru (Türkçe karakterler dahil) yazıldığı Python üzerinden doğrudan kontrol edilerek teyit edildi (`'Türk Hava Yolları'` → UTF-8 `b'T\xc3\xbcrk Hava Yollar\xc4\xb1'`). PowerShell konsolunda Türkçe karakterlerin bozuk görünmesi (`TÃ¼rk Hava YollarÄ±`) sadece konsol render sorunuydu, veri katmanında bir hata yoktu.

**Karşılaşılan hata / çözüm (özet):**
- `gcloud auth login`/`application-default login` arka planda EOFError ile çöktü → kullanıcı kendi terminalinde interaktif çalıştırdı.
- Firestore API etkin değildi → Service Usage API üzerinden REST ile etkinleştirildi.
- Firestore veritabanı yoktu (yeni proje) → REST API ile native mode veritabanı oluşturuldu.
- `where("active", "==", True)` pozisyonel filtre kullanımı için deprecation uyarısı verdi → `FieldFilter` (keyword `filter=`) kullanımına geçildi.

**Tarih / Not:**
13.08.2026 — Asset modeli, repository, API endpoint'leri ve Firestore canlı bağlantısı uçtan uca test edilip doğrulandı. Sıradaki adım: AŞAMA 10 — Market Data Provider.

---

## 17. AŞAMA 10 — Market Data Provider

Ana dokümanın 67. bölümündeki Provider Mimarisi ilkesine göre: piyasa verisi sağlayıcıları doğrudan engine'lere bağlanmaz, `MarketDataProvider` arayüzü üzerinden soyutlanır. Bu aşamada BIST için ilk somut adaptör (`BistProvider`) ve `market_data` collection'ı (bölüm 30) için repository yazıldı.

**Oluşturulan dosyalar (backend):**
```text
app/models/market_data.py                    → MarketData (Pydantic): asset_id, timestamp, OHLCV, source
app/services/market_data/base.py              → MarketDataProvider soyut arayüzü (get_latest)
app/services/market_data/bist_provider.py     → Yahoo Finance tabanlı BIST adaptörü (sembol + ".IS")
app/repositories/market_data_repository.py    → Firestore "market_data" için add / list_for_asset
scripts/fetch_market_data.py                  → Seed edilmiş 6 varlık için gerçek fiyat çekip Firestore'a yazan script
```

**Veri kaynağı kararı:** Ana doküman bir BIST veri sağlayıcısı adı vermiyor (bölüm 68 sadece "BIST ile başlamak planlanabilir" diyor). Kural 11-12 gereği ("AI yalnız gerçek verilere dayanacak, veri uydurmayacak") uydurma/sahte veri yerine **gerçek, halka açık bir kaynak** seçildi: **Yahoo Finance** (`yfinance` Python paketi üzerinden), BIST sembolleri `SEMBOL.IS` formatıyla sorgulanıyor (örn. `THYAO.IS`). Bu, MVP/prototip aşaması için yaygın kullanılan ücretsiz bir kaynaktır; ileride resmi/lisanslı bir BIST veri sağlayıcısına geçilmek istenirse yalnızca `BistProvider` implementasyonu değişir, arayüz ve geri kalan kod etkilenmez (provider mimarisinin amacı tam olarak bu).

**Kurulum komutu:**
```powershell
pip install yfinance
```
→ `yfinance==1.5.2` kuruldu, `requirements.txt` güncellendi.

**Tasarım notu — append-only:** Ana dokümanın 6. kuralı ("yeni analiz geldiğinde eski kayıt güncellenmez, yeni kayıt oluşturulur") market_data için de uygulandı: `MarketDataRepository.add()` her zaman yeni bir Firestore dokümanı ekler (`upsert` değil), var olan kayıtları değiştirmez. Okuma tarafında (`list_for_asset`) composite index gerektirmemesi için filtreleme Firestore'da eşitlik sorgusuyla, sıralama ise Python tarafında yapılıyor.

**Doğrulama:**
```powershell
python scripts\fetch_market_data.py
→ AKBNK: close=68.70 volume=112996906 @ 2026-08-13 (source=yahoo_finance)
  ASELS: close=389.75 volume=26656116 @ 2026-08-13 (source=yahoo_finance)
  EREGL: close=38.36 volume=200781066 @ 2026-08-13 (source=yahoo_finance)
  GARAN: close=129.40 volume=22158140 @ 2026-08-13 (source=yahoo_finance)
  THYAO: close=307.25 volume=18698493 @ 2026-08-13 (source=yahoo_finance)
  TUPRS: close=344.75 volume=16352571 @ 2026-08-13 (source=yahoo_finance)
```
Firestore'a yazılan veri `MarketDataRepository.list_for_asset("THYAO")` ile geri okunarak doğrulandı (OHLCV ve `source` alanları eksiksiz döndü).

**Karşılaşılan hata / çözüm:**
Script'in ilk çalıştırması 60 saniyelik ön izleme süresini aştı (Yahoo Finance'e 6 ayrı sorgu + yfinance'in ilk çalıştırmada yaptığı ek metadata istekleri nedeniyle yavaş kaldı) ve otomatik olarak arka plana alındı; birkaç saniye sonra sorunsuz tamamlandı. Gerçek bir hata değildi.

**Tarih / Not:**
13.08.2026 — Market Data Provider (BIST/Yahoo Finance) uçtan uca test edildi: gerçek fiyat verisi çekildi, Firestore'a yazıldı, repository üzerinden geri okundu. Sıradaki adım: AŞAMA 11 — TechnicalAnalysisEngine.

---

## 18. AŞAMA 11 — TechnicalAnalysisEngine

Ana dokümanın 5. bölümündeki `TechnicalScore` (-100...+100) hesaplamasını üreten motor.

**Oluşturulan/güncellenen dosyalar (backend):**
```text
app/services/market_data/base.py               → arayüze get_history(symbol, period) eklendi
app/services/market_data/bist_provider.py       → get_history(): Yahoo Finance'ten OHLCV geçmiş serisi
app/engines/technical/indicators.py              → SMA, EMA, RSI, MACD, Bollinger Bands, ATR, Momentum, ROC, Volume SMA
app/engines/technical/engine.py                  → TechnicalAnalysisEngine: göstergeleri TechnicalScore'a birleştirir
app/repositories/system_config_repository.py     → Firestore "system_config" — ağırlıklar hard-code edilmez (kural 13)
app/models/technical_analysis.py                 → TechnicalAnalysis (Pydantic)
app/repositories/technical_analysis_repository.py→ Firestore "technical_analyses" (append-only, kural 5-6)
app/api/analysis.py                              → GET /analysis/{symbol}/technical
app/main.py                                      → analysis router bağlandı
```

**Kapsam kararı (bilinçli, dokümante edilmiş eksik):** Ana dokümanın 5. bölümü 15 gösterge listeliyor ("ilk etapta desteklenebilecek" — zorunlu değil). Bu turda **RSI, MACD, EMA (trend kesişimi), Bollinger Bands, Momentum, ROC** doğrudan skora katkı sağlıyor; **ATR** volatilite normalizasyonu için, **Volume/Volume SMA** ise yön belirtmediği için skora değil `confidence`'a (bölüm 19: "teknik göstergelerin uyumu") katkı sağlıyor. **ADX, Stochastic RSI, Support/Resistance, ayrı bir Trend Strength metriği ve Relative Strength bu sürümde YOK** — ileride ayrı bir iyileştirme adımında eklenebilir. Üçüncü parti bir TA kütüphanesi (`ta`/`pandas-ta`) yerine göstergeler elle pandas ile yazıldı; gerekçe: (1) bu paketlerin çok yeni pandas 3.x/numpy 2.5 sürümleriyle uyumluluğu belirsizdi, (2) AIExplanationEngine'in hesaplamayı denetlenebilir şekilde açıklayabilmesi için mantığın bu kod tabanında şeffaf olması istendi.

**Skor birleştirme mantığı:** Her gösterge -100..+100 aralığında bir alt-skora normalize edilir (ör. RSI: `(RSI-50)*2`; MACD histogramı ATR'ye bölünerek ölçeklenir; EMA20/EMA50 kesişimi yüzdesel farkla; Bollinger: kapanışın orta banda göre pozisyonu; Momentum/ROC kendi formülleriyle). Alt-skorlar `system_config/technical_indicator_weights` dokümanındaki ağırlıklarla (varsayılan: ~%16,7 eşit ağırlık) çarpılıp toplanır → `technical_score`. `trend` etiketi: skor >15 BULLISH, <-15 BEARISH, aksi NEUTRAL. `confidence`, alt-skorların yön uyumu (agreement) ve hacim doğrulaması (mevcut hacim / hacim SMA'sı) birleşiminden hesaplanır — salt `technical_score` büyüklüğünden üretilmez (bölüm 19'un açıkça yasakladığı şey).

**Doğrulama:**
```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
GET /analysis/THYAO/technical
→ {
    "asset": "THYAO", "technical_score": -15.64, "trend": "BEARISH", "confidence": 0.84,
    "components": {"rsi": -12.44, "macd": -3.43, "trend": -7.81, "bollinger": -43.80, "momentum": -12.31, "roc": -14.05},
    "indicators": {"rsi": 43.78, "ema_20": 314.09, "ema_50": 316.56, "bollinger_upper": 331.88, ...},
    "engine_version": "1.0.0"
  }
```
Sonuç, RSI 43.78 (nötrün hafif altı) → `(43.78-50)*2=-12.44` bileşen skoruyla ve EMA20(314.09) < EMA50(316.56) → negatif trend bileşeniyle manuel olarak çapraz kontrol edilip tutarlı bulundu. Ayrıca doğrulandı:
- `TechnicalAnalysisRepository.get_latest("THYAO")` ile Firestore'a kalıcı kayıt olarak yazıldığı (append-only) teyit edildi.
- `system_config/technical_indicator_weights` dokümanının otomatik seed edildiği ve doğru okunduğu teyit edildi.

**Karşılaşılan hata / çözüm:**
Yok — ilk denemede sorunsuz çalıştı.

**Tarih / Not:**
13.08.2026 — TechnicalAnalysisEngine gerçek piyasa verisiyle uçtan uca test edildi (RSI/MACD/EMA/Bollinger/Momentum/ROC skora, ATR normalize, Volume confidence'a). Sıradaki adım: AŞAMA 12 — TechnicalScore (zaten bu aşamada üretiliyor, doğrulandı) → AŞAMA 13: AI Decision History.

---

## 19. AŞAMA 12-13 — TechnicalScore Çıktısı & AI Decision History

Ana dokümanın 17-19, 32-33 ve 72. bölümlerine göre `DecisionEngine` ve immutable `ai_decisions` kaydı.

**Önemli mimari not (kasıtlı, dokümana uygun):** Ana dokümanın 82. bölümündeki geliştirme sırasında AŞAMA 13 (AI Decision History), AŞAMA 15-23'teki News/Macro engine'lerinden ve tam `DecisionEngine`'den (AŞAMA 23) **önce** geliyor. Bu, MVP1'in (bölüm 77) yalnızca TechnicalScore ile çalışan bir "AL/SAT/TUT" ekranı hedeflemesiyle tutarlı. Bu yüzden `DecisionEngine` şimdiden **News ve Macro skorlarını opsiyonel/eksik olarak** kabul edecek şekilde, bölüm 72'nin "Missing Data Davranışı" ilkesine göre tasarlandı — News/Macro engine'leri ileride eklendiğinde bu koda dokunmaya gerek kalmayacak.

**Oluşturulan/güncellenen dosyalar (backend):**
```text
app/engines/technical/engine.py         → analyze_with_id() eklendi (DecisionEngine'in technical_analysis_id
                                            alabilmesi için; mevcut analyze() API sözleşmesi değişmedi)
app/models/ai_decision.py                → AIDecision (Pydantic) — bölüm 32 şemasına uygun, skorlar Optional
app/repositories/ai_decision_repository.py → Firestore "ai_decisions" — YALNIZCA add() ve get_latest();
                                              bilerek update/delete metodu YOK (bölüm 33: immutable)
app/engines/decision/engine.py           → DecisionEngine: decide() ve decide_from_technical()
app/api/decisions.py                     → GET /decisions/{symbol}
app/main.py                              → decisions router bağlandı
```

**Karar mantığı:**
- Ağırlıklar (`decision_weights`, varsayılan Technical=0.50/News=0.30/Macro=0.20 — bölüm 17) ve eşikler (`decision_thresholds`, bölüm 18: AL≥40, ZAYIF AL≥15, ZAYIF SAT≤-15, SAT≤-40, aradaki TUT) `system_config`'ten okunur, hard-code değildir.
- Yalnızca mevcut skorlar kullanılır; `final_score`, mevcut skorların ağırlıkları kendi aralarında normalize edilerek hesaplanır (ör. yalnızca technical varsa final_score = technical_score).
- `confidence`, temel teknik güven değeri ile "veri tamlık oranı" (mevcut ağırlık toplamı / tam ağırlık toplamı) çarpılarak hesaplanır — yani News/Macro eksikken confidence bilerek düşük çıkar (bölüm 19: confidence salt final_score büyüklüğünden üretilmemeli, veri eksikliği dikkate alınmalı).
- `technical_analysis_id` alanı, kararın hangi teknik analiz kaydına dayandığını izlenebilir kılar (bölüm 22 "AI Açıklaması İçin Kanıt Kaydı" ile uyumlu).

**Doğrulama:**
```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
GET /decisions/THYAO
→ {
    "asset": "THYAO", "technical_score": -15.14, "news_score": null, "macro_score": null,
    "technical_weight": 0.5, "news_weight": 0.3, "macro_weight": 0.2,
    "final_score": -15.14, "decision": "WEAK_SELL", "confidence": 42.0,
    "technical_analysis_id": "EGMM5hwJtNYFdA1jhSR0", "news_analysis_ids": [], "macro_snapshot_id": null,
    "decision_engine_version": "1.0.0", "immutable": true
  }
```
Elle çapraz kontrol: final_score(-15.14) = technical_score (tek mevcut skor) ✓; -15.14 ≤ weak_sell eşiği (-15) → `WEAK_SELL` ✓; confidence = 0.84 (teknik analiz güveni) × 0.5 (tamlık oranı: 0.5/1.0 ağırlık) × 100 = 42.0 ✓.
Ayrıca doğrulandı:
- `AIDecisionRepository.get_latest("THYAO")` ile Firestore'a kalıcı, immutable kayıt olarak yazıldığı teyit edildi.
- `system_config/decision_weights` ve `system_config/decision_thresholds` dokümanlarının otomatik seed edildiği ve doğru okunduğu teyit edildi.

**Karşılaşılan hata / çözüm:**
Yok — ilk denemede sorunsuz çalıştı.

**Tarih / Not:**
13.08.2026 — DecisionEngine ve immutable ai_decisions kaydı, yalnızca TechnicalScore mevcutken (News/Macro henüz yok) uçtan uca test edildi; eksik veri davranışı (ağırlık normalizasyonu + düşük confidence) doğru çalıştığı doğrulandı. Sıradaki adım: AŞAMA 14 (Flutter AL/SAT/TUT ekranı — mobil taraf) veya AŞAMA 15 (News Provider — backend tarafı).

---

## 20. AŞAMA 15 — News Provider

Ana dokümanın 67. bölümündeki Provider Mimarisi ile 7. bölümdeki SourceReliabilityScore ilkesine göre: haber sağlayıcıları da `NewsProvider` arayüzü üzerinden soyutlanır. Bu aşamanın kapsamı **yalnızca ham haber toplama**dır (`news_raw`); AI ile olay sınıflandırma/duygu analizi/etki skoru (EventIntelligenceEngine, bölüm 6/8/10) kasıtlı olarak **AŞAMA 16+'ya bırakıldı** — çünkü o, gerçek bir AI (LLM) çağrısı gerektiriyor ve ayrı bir tasarım kararı (hangi model, prompt, grounding stratejisi) gerektirir.

**Oluşturulan dosyalar (backend):**
```text
app/models/news_raw.py                    → NewsRawItem (Pydantic): title, summary, url, publisher,
                                              source, source_reliability, related_assets, published_at, received_at
app/services/news/base.py                  → NewsProvider soyut arayüzü (get_latest_news)
app/services/news/yahoo_news_provider.py   → Yahoo Finance (yfinance Ticker.news) tabanlı adaptör +
                                              yayıncı adından bölüm 7 kategorisine (NEWS_AGENCY,
                                              FINANCIAL_MEDIA, OTHER_MEDIA vb.) sınıflandırma
app/repositories/news_raw_repository.py    → Firestore "news_raw" — upsert (external_id ile teknik dedup) / get_recent
scripts/fetch_news.py                      → Seed edilmiş 6 varlık için gerçek haber çekip Firestore'a yazan script
```

**Veri kaynağı kararı:** Ana doküman bölüm 67'de örnek adaptör isimleri (`InternationalNewsProvider`, `FinancialNewsProvider` vb.) veriyor ama somut bir API belirtmiyor. AŞAMA 10'daki (Market Data) kararla tutarlı olarak, zaten kullanılan **Yahoo Finance** (`yfinance`'in `Ticker.news` özelliği) tercih edildi — ek bir API anahtarı/bağımlılık gerektirmiyor ve zaten kullandığımız BIST sembolleriyle doğrudan çalışıyor.

**SourceReliabilityScore uygulaması:** Ağırlıkların kendisi (`OFFICIAL_INSTITUTION: 1.00` ... `SOCIAL_MEDIA: 0.30`) bölüm 7'deki örnek config ile birebir `system_config/source_reliability` dokümanına seed edildi (hard-code değil). Kod tarafında yalnızca **yayıncı adının hangi kategoriye girdiğini** belirleyen küçük bir sınıflandırma tablosu var (ör. "Reuters" → NEWS_AGENCY, "Bloomberg"/"MT Newswires" → FINANCIAL_MEDIA, bilinmeyenler → OTHER_MEDIA); bu bir ağırlık değil, sınıflandırma mantığıdır.

**Teknik dedup notu:** `news_raw` dokümanları, Yahoo'nun verdiği `external_id` doküman ID'si olarak kullanılarak upsert edilir — bu yalnızca AYNI makalenin tekrar tekrar kopyalanmasını önler. Ana dokümanın 9. bölümündeki asıl "Duplicate Event Detection" (farklı kaynaklarda yayınlanan AYNI OLAYIN semantik olarak tekilleştirilmesi) bu aşamada YOK, AŞAMA 16+'da ele alınacak.

**Doğrulama:**
```powershell
python scripts\fetch_news.py
→ AKBNK: 5 haber yazıldı  (örnek: GuruFocus.com, güvenilirlik=0.6)
  ASELS: 0 haber yazıldı  (Yahoo'da bu sembol için haber yoktu — uydurulmadı, dürüstçe 0)
  EREGL: 0 haber yazıldı  (aynı sebep)
  GARAN: 5 haber yazıldı  (örnek: Simply Wall St., güvenilirlik=0.6)
  THYAO: 5 haber yazıldı  (örnek: MT Newswires, güvenilirlik=0.8)
  TUPRS: 1 haber yazıldı  (örnek: GuruFocus.com, güvenilirlik=0.6)
```
`NewsRawRepository.get_recent("THYAO")` ile Firestore'dan geri okuma yapıldı: 5 kayıt, `published_at`'e göre azalan sırada, `source_reliability` alanları doğru (MT Newswires=0.8 FINANCIAL_MEDIA, diğerleri=0.6 OTHER_MEDIA) döndü.

**Karşılaşılan hata / çözüm:**
İlk denemede yfinance'in `Ticker.news` çıktı şeması tahmin edilmeden kod yazılmadı — önce canlı bir örnek çekilip gerçek alan adları (`content.title`, `content.pubDate`, `content.provider.displayName`, `content.canonicalUrl.url`) doğrulandı, kod buna göre yazıldı. Bu sayede yanlış alan adı hatası hiç yaşanmadı.

**Tarih / Not:**
13.08.2026 — News Provider (Yahoo Finance) gerçek haber verisiyle uçtan uca test edildi, SourceReliabilityScore config'i seed edildi ve doğrulandı. Sıradaki adım: AŞAMA 16 — EventIntelligenceEngine (AI ile haber sınıflandırma — bir LLM entegrasyonu gerektirir, ayrı bir tasarım kararı olarak ele alınmalı).

---

## 21. AŞAMA 14 — Flutter AL/SAT/TUT Ekranı

Ana dokümanın 85. bölümündeki ("Ana Ekran Taslağı") hedef görünüme uygun ilk gerçek mobil ekran. Bu, projenin ilk kez **uçtan uca** (Flutter → HTTP → FastAPI → Firestore/Yahoo Finance → geri) çalıştığı ve gerçek bir Android emulator'de görsel olarak doğrulandığı adımdır.

**Oluşturulan/güncellenen dosyalar (Flutter):**
```text
lib/models/decision.dart                      → Decision modeli (backend'in /decisions/{symbol} çıktısını parse eder)
lib/services/api/decision_api.dart             → DecisionApi: backend'e HTTP GET isteği
lib/features/dashboard/dashboard_screen.dart   → Ana ekran: 6 test varlığı için kart listesi
lib/main.dart                                  → Firebase.initializeApp() + DashboardScreen ana ekran olarak bağlandı
android/app/src/main/AndroidManifest.xml       → usesCleartextTraffic="true" (yalnızca geliştirme, http:// erişimi için)
```

**Kurulum komutu:**
```powershell
flutter pub add http
```

**Android emulator networking notu:** Android emulator'de `localhost`/`127.0.0.1` emulator'ün kendisini işaret eder, host (Windows) makineyi değil. Bu yüzden backend'e `http://10.0.2.2:8000` üzerinden erişildi (Android emulator'ün host'a yönlendiren özel alias'ı) — bu, fiziksel cihaz/prod ortamında gerçek bir API URL'i ile değiştirilmesi gereken, yalnızca emulator'e özgü bir adres.

**Cleartext (http://) izni:** Android 9+ varsayılan olarak şifresiz HTTP trafiğini engeller. `AndroidManifest.xml`'e `android:usesCleartextTraffic="true"` eklendi (yorum satırıyla "yalnızca geliştirme, production'da kaldırılmalı" notu düşülerek).

**Doğrulama — tam uçtan uca test:**
1. Backend `--host 0.0.0.0` ile başlatıldı (emulator'ün erişebilmesi için, `127.0.0.1` yerine).
2. Android emulator (`Pixel_7_API_36`) `emulator.exe -avd Pixel_7_API_36` ile ilk kez boot edildi (~60 saniye soğuk başlatma), `adb shell getprop sys.boot_completed` ile hazır olduğu doğrulandı.
3. `flutter run -d emulator-5554` ile uygulama derlendi ve cihaza kuruldu. İlk derlemede Gradle, Android NDK r28c'yi indirdi (~10 dakika, tek seferlik — sonraki derlemeler çok daha hızlı olacak).
4. `adb shell screencap` ile ekran görüntüsü alınıp görsel olarak doğrulandı: **THYAO = ZAYIF SAT (%42), ASELS = AL (%41), GARAN = TUT (%41), AKBNK = ZAYIF AL** — her biri gerçek `technical_score` değerleriyle (backend'den canlı çekilen), `News`/`Macro` alanlarında dürüstçe "Veri yok" yazıyor (uydurma veri yok).
5. Edge case testi: "Neden AL?" butonuna `adb shell input tap` ile tıklandı, beklenen SnackBar mesajı ("AIExplanationEngine henüz uygulanmadı") ekranda göründü — buton etkileşiminin de çalıştığı doğrulandı.
6. `flutter analyze` çalıştırıldı: yalnızca 1 kozmetik lint uyarısı (`_, __` yerine `_, _`) çıktı, düzeltildi; son durumda 0 sorun.

**Karşılaşılan hata / çözüm:**
Yok — networking (10.0.2.2) ve cleartext ayarları baştan doğru yapılandırıldığı için ilk denemede backend'e bağlanma sorunu yaşanmadı.

**Tarih / Not:**
13.08.2026 — İlk Flutter ekranı gerçek Android emulator'de, gerçek backend verisiyle uçtan uca test edildi ve ekran görüntüsüyle görsel olarak doğrulandı. Sıradaki adım: AŞAMA 16+ (EventIntelligenceEngine — LLM entegrasyonu, kullanıcı onayı bekliyor) veya kullanıcının seçtiği başka bir aşama.

---

## 22. AŞAMA 21-22 — MacroAnalysisEngine & MacroScore

Ana dokümanın 15. bölümündeki `MacroScore` (-100...+100). LLM gerektirmeyen, sayısal piyasa verisine dayalı bir motor olduğu için News/Macro engine'leri arasında önce bu yapıldı (EventIntelligenceEngine için AI sağlayıcı kararı hâlâ bekliyor).

**Oluşturulan/güncellenen dosyalar (backend):**
```text
app/services/macro/base.py               → MacroDataProvider arayüzü (get_indicator_changes)
app/services/macro/yahoo_macro_provider.py → DXY, ABD 10Y tahvil faizi, VIX, petrol, altın, USD/TRY
app/models/macro_snapshot.py              → MacroSnapshot (Pydantic)
app/repositories/macro_snapshot_repository.py → Firestore "macro_snapshots" (append-only) + get_latest_with_id()
app/engines/macro/engine.py               → MacroAnalysisEngine: göstergeleri MacroScore'a birleştirir
app/api/analysis.py                       → GET /analysis/macro eklendi
app/engines/decision/engine.py            → decide_from_technical() → decide_for_asset() olarak genişletildi:
                                             artık en son macro_snapshot'ı da otomatik topluyor
app/api/decisions.py                      → decide_for_asset() çağrısına güncellendi
```

**Kapsam kararı:** Ana dokümanın 15. bölümü çok geniş bir makro veri listesi veriyor (Fed/TCMB/ECB faiz kararları, CPI, NFP, GDP, likidite koşulları) — bunların çoğu özel ekonomik veri API'leri ve API anahtarı gerektiriyor (FRED, TCMB EVDS vb.). Bu ilk sürümde, zaten kullanılan **Yahoo Finance** üzerinden anahtarsız ve gerçek olarak elde edilebilen alt küme kullanıldı: **DXY, ABD 10Y tahvil faizi, VIX, petrol (WTI), altın, USD/TRY**. Fed/TCMB açıklamaları, enflasyon verileri gibi geri kalanlar ileride ayrı bir provider ile eklenebilir (dokümante edilmiş, bilinçli eksik — AŞAMA 11 ve 15'teki kapsam kararlarıyla aynı desende).

**Yön sözleşmesi (tasarım kararı, kod içinde de belgelendi):** Tüm 6 gösterge için **yükseliş = risk-off/BIST için negatif** olarak yorumlanır (dolar güçlenmesi, faiz artışı, VIX artışı, petrol/altın artışı, TL değer kaybı — hepsi gelişen piyasa risk iştahını azaltan veya maliyet baskısı yaratan sinyaller). `macro_score`, her göstergenin N-günlük (varsayılan 20 gün) yüzde değişiminin göstergeye özgü bir ölçek faktörüyle çarpılıp `system_config/macro_indicator_weights` ağırlıklarıyla birleştirilmesiyle hesaplanır — ne ölçekler ne ağırlıklar hard-code'dur, `system_config`'ten okunur ve otomatik seed edilir.

**DecisionEngine entegrasyonu (AŞAMA 13'teki tasarım hedefinin doğrulanması):** AŞAMA 13'te "News/Macro eklendiğinde bu kod DEĞİŞMEDEN çalışmaya devam eder" denmişti. Gerçekten de `decide()`'ın çekirdek mantığına hiç dokunulmadı; yalnızca `decide_for_asset()` (eski adıyla `decide_from_technical()`), artık `MacroSnapshotRepository.get_latest_with_id()` ile en son makro snapshot'ı da alıp `decide()`'a iletiyor. Not: MacroScore varlığa özel değil (piyasa geneli) olduğu için her `/decisions/{symbol}` isteğinde yeniden hesaplanmıyor — en son kaydedilmiş snapshot kullanılıyor; makro motor ayrı bir zamanlama/talep ile (`GET /analysis/macro`) tetiklenir.

**Doğrulama:**
```powershell
GET /analysis/macro
→ { "macro_score": -8.38, "confidence": 0.87,
    "components": {"dxy": 12.34, "us_10y_yield": -16.63, "vix": 27.73, "oil": -14.82, "gold": -90.02, "usdtry": -12.32},
    "indicators": {"dxy": {"value": 99.901, "pct_change": -0.823}, ...} }

GET /decisions/THYAO   (macro snapshot'tan SONRA çağrıldı)
→ { "technical_score": -14.65, "macro_score": -8.38, "final_score": -12.86, "decision": "HOLD",
    "confidence": 58.8, "technical_analysis_id": "B18XTLv5...", "macro_snapshot_id": "MAMPb3RG..." }
```
Elle çapraz kontrol: her bileşen (`-pct_change × ölçek`) doğru; ağırlıklı `macro_score` toplamı (-8.384685 → -8.38) doğru; `final_score = (technical_score×0.5 + macro_score×0.2)/0.7 = -12.86` doğru; `confidence = 0.84(teknik güven) × (0.7 tamlık oranı) × 100 = 58.8` doğru. `macro_snapshot_id` ilk denemede `null` geldi (get_latest() doc ID döndürmüyordu) → `get_latest_with_id()` eklenerek düzeltildi ve doğrulandı.

**Karşılaşılan hata / çözüm:**
`MacroSnapshotRepository.get_latest()` başlangıçta yalnızca `MacroSnapshot` modelini döndürüyordu, Firestore doküman ID'sini kaybediyordu → `AIDecision.macro_snapshot_id` hep `null` kalıyordu. `get_latest_with_id()` eklenerek (aynı `analyze_with_id()` deseninde, AŞAMA 13) düzeltildi.

**Tarih / Not:**
13.08.2026 — MacroAnalysisEngine gerçek piyasa verisiyle uçtan uca test edildi ve DecisionEngine'e sorunsuz entegre edildi; AŞAMA 13'teki "genişletilebilir mimari" iddiası doğrulanmış oldu. Sıradaki adım: AŞAMA 16+ (EventIntelligenceEngine, LLM kararı bekliyor) veya kullanıcının seçtiği başka bir aşama.

---

## 23. AŞAMA 30-31 — Portföy Modülü & Kâr/Zarar

Ana dokümanın 37. bölümündeki Portföy Modülü. LLM gerektirmeyen, mevcut Firestore/FastAPI deseniyle devam eden bir aşama.

**Oluşturulan dosyalar (backend):**
```text
app/models/portfolio_position.py           → PortfolioPosition (Pydantic): user_id, asset, buy_price,
                                               buy_date, quantity, created_at
app/schemas/portfolio.py                    → PortfolioPositionCreate (API girişi — created_at hariç)
app/repositories/portfolio_repository.py    → Firestore "portfolio_positions" — add / list_for_user / delete
app/services/portfolio/pnl_calculator.py    → Güncel piyasa fiyatına göre kâr/zarar hesaplama
app/api/portfolio.py                        → POST/GET /portfolio/positions, DELETE /portfolio/positions/{id}
app/main.py                                 → portfolio router bağlandı
```

**Önemli mimari fark (bilinçli, dokümante edilmiş):** `ai_decisions` ve `technical_analyses`'in aksine `portfolio_positions` **immutable DEĞİLDİR** — bu AI'ın ürettiği bir kayıt değil, kullanıcının kendi verisidir; kullanıcı pozisyonunu silebilmeli/düzenleyebilmelidir. Bu yüzden repository'de bilerek bir `delete()` metodu var (ai_decisions/technical_analyses repository'lerinde YOK).

**Güvenlik notu (bilinçli, dokümante edilmiş eksik):** Auth/Login ekranı henüz yazılmadı (AŞAMA 4 sadece Firebase Authentication'ı bağladı, gerçek bir giriş UI'ı yok). Bu yüzden `user_id` şu an istemciden düz bir parametre olarak alınıyor — bu geçici bir MVP kısayolu ve kod içinde açıkça böyle işaretlendi. Production öncesi mutlaka: (1) `user_id` Firebase Auth token'ından doğrulanmalı, (2) ana dokümanın 34. bölümündeki "kullanıcı yalnız kendi verisini okur/yazar" Firestore Security Rules kuralı uygulanmalı.

**Doğrulama:**
```powershell
POST /portfolio/positions  {user_id: demo_user, asset: THYAO, buy_price: 250, quantity: 100, buy_date: 2026-06-01}
→ {"id": "krNy9BS127I3DfY7mnpx", ...}

GET /portfolio/positions?user_id=demo_user
→ {
    "positions": [{..., "current_price": 308.0, "invested_amount": 25000.0,
                   "current_value": 30800.0, "profit_loss": 5800.0, "return_percent": 23.2}],
    "summary": {"total_invested": 25000.0, "total_current_value": 30800.0,
                "total_profit_loss": 5800.0, "total_return_percent": 23.2}
  }

DELETE /portfolio/positions/krNy9BS127I3DfY7mnpx
→ liste tekrar kontrol edildi, boş döndü (silme doğrulandı)
```
Elle çapraz kontrol: 100×250=25.000 yatırım ✓; güncel fiyat (308, gerçek THYAO kapanışı) ×100=30.800 ✓; kâr=5.800, getiri=%23,2 ✓ — tümü tutarlı.

**Karşılaşılan hata / çözüm:**
Yok — ilk denemede sorunsuz çalıştı.

**Tarih / Not:**
13.08.2026 — Portföy modülü (oluştur/listele+P&L/sil) uçtan uca test edildi, gerçek güncel piyasa fiyatıyla kâr/zarar doğru hesaplandığı doğrulandı. Sıradaki adım: AŞAMA 16+ (EventIntelligenceEngine, LLM kararı bekliyor) veya kullanıcının seçtiği başka bir aşama (ör. RiskEngine, BacktestEngine, Flutter Portföy ekranı).

---

## 24. AŞAMA 33 — RiskEngine

Ana dokümanın 44. bölümündeki risk metrikleri. LLM gerektirmez, mevcut market_data/portfolio verisinden hesaplanır.

**Oluşturulan dosyalar (backend):**
```text
app/engines/risk/engine.py   → RiskEngine: asset_risk() (volatilite, max drawdown) ve
                                 portfolio_concentration() (Herfindahl-Hirschman Index)
app/api/risk.py               → GET /risk/{symbol}, GET /risk/portfolio/concentration?user_id=...
app/main.py                   → risk router bağlandı
```

**Kapsam kararı:** Bölüm 44'teki 9 riskten (volatilite, max drawdown, likidite, gap riski, haber yoğunluğu, sektör riski, piyasa riski, korelasyon, portföy konsantrasyonu) yalnızca **volatilite, maximum drawdown ve portföy konsantrasyonu** uygulandı — LLM'siz ve mevcut veriyle doğrudan hesaplanabilenler bunlar. Haber yoğunluğu EventIntelligenceEngine'e (LLM, hâlâ bekliyor), korelasyon ve sektör riski ise ayrı bir veri modeline (sektör sınıflandırması, çoklu varlık zaman serisi hizalaması) ihtiyaç duyduğu için bilinçli olarak ertelendi.

**Hesaplama mantığı:**
- Volatilite: günlük getirilerin standart sapması × √252 (yıllıklandırma), yüzde olarak.
- Maximum Drawdown: kümülatif getiri serisinin, o ana kadarki tepe noktasına göre en büyük düşüşü.
- Portföy Konsantrasyonu: her pozisyonun güncel değerinin portföy toplamına oranının karelerinin toplamı (HHI) — 1'e yakın = yüksek yoğunlaşma (tek varlığa bağımlılık), düşük = iyi çeşitlendirme.

**Doğrulama:**
```powershell
GET /risk/THYAO
→ {"asset": "THYAO", "volatility_annualized_pct": 35.24, "max_drawdown_pct": -21.21, "period": "6mo"}

GET /risk/portfolio/concentration?user_id=demo_user   (THYAO 100 adet + GARAN 50 adet pozisyonlarıyla)
→ {"herfindahl_index": 0.7128, "weights_pct": {"THYAO": 82.62, "GARAN": 17.38}}
```
Elle çapraz kontrol: ağırlıklar toplamı %100 ✓; HHI = 0.8262² + 0.1738² = 0.6826 + 0.0302 = 0.7128 ✓ tam eşleşti. Test pozisyonları doğrulama sonrası temizlendi.

**Karşılaşılan hata / çözüm:**
Yok — ilk denemede sorunsuz çalıştı.

**Tarih / Not:**
13.08.2026 — RiskEngine (volatilite, max drawdown, portföy konsantrasyonu) gerçek veriyle uçtan uca test edildi ve elle doğrulandı. Sıradaki adım: AŞAMA 16+ (EventIntelligenceEngine, LLM kararı bekliyor) veya kullanıcının seçtiği başka bir aşama.

---

## 25. AŞAMA 30-31 (Flutter Tarafı) — Portföy Ekranı

AŞAMA 23'te (bkz. [Bölüm 23](#23-aşama-30-31--portföy-modülü--kâr-zarar)) backend'i tamamlanan Portföy Modülü'nün Flutter arayüzü. Uygulama artık iki sekmeli: "Analiz" (AŞAMA 21'deki Dashboard) ve "Portföy".

**Oluşturulan/güncellenen dosyalar (Flutter):**
```text
lib/models/portfolio_position.dart           → PortfolioPosition + PortfolioSummary modelleri
lib/services/api/portfolio_api.dart          → PortfolioApi: fetchPositions/createPosition/deletePosition
lib/features/portfolio/portfolio_screen.dart → PortfolioScreen: özet kart + pozisyon listesi + FAB ile ekleme
lib/main.dart                                → RootScreen eklendi: NavigationBar ile Analiz/Portföy sekme geçişi
```

**Tasarım notu:** Auth/Login ekranı henüz yok (bkz. AŞAMA 23'teki güvenlik notu), bu yüzden Flutter tarafında da `_demoUserId = 'demo_user'` sabit değeri kullanıldı — backend'deki geçici kısayolun mobil tarafındaki yansıması, aynı şekilde kod içinde işaretlendi.

**Doğrulama — tam uçtan uca test (gerçek Android emulator, `adb` ile):**
1. Backend ve emulator yeniden başlatıldı, `adb shell getprop sys.boot_completed` ile boot tamamlandığı doğrulandı.
2. Debug APK doğrudan `adb install -r` ile kurulup `adb shell am start` ile başlatıldı (bkz. aşağıdaki "Karşılaşılan hata/çözüm" — `flutter run` bu ortamda güvenilir değil).
3. `adb shell uiautomator dump` ile ekranın gerçek widget koordinatları alınıp (görsel tahmin yerine) kesin buton/alan sınırlarıyla dokunuldu.
4. "Portföy" sekmesine geçildi → boş durum ("Henüz pozisyon eklenmedi.") doğru göründü.
5. FAB (+) ile "Pozisyon Ekle" diyaloğu açıldı; Alış Fiyatı = 310.50, Adet = 100 (THYAO) girildi; "Ekle" ile gönderildi.
6. Sonuç: pozisyon listede **THYAO • 100 adet, Alış: 310.50 TL, Güncel: 308.00 TL (gerçek THYAO kapanış fiyatı), -250 TL** olarak göründü. Özet kart: **Toplam Yatırım: 31050 TL, Güncel Değer: 30800 TL, -250 TL, %-0.8** — elle çapraz kontrol: (308.00-310.50)×100 = -250 ✓, 310.50×100=31050 ✓, 308.00×100=30800 ✓.
7. Çöp kutusu ikonuna dokunuldu → `DELETE /portfolio/positions/{id}` çağrıldı, liste yeniden yüklendi, boş duruma geri döndüğü doğrulandı (silme çalışıyor).
8. `flutter analyze`: "No issues found!"

**Karşılaşılan hata / çözüm (emulator/bağlantı kararsızlığı):**
Bu ortamda `flutter run -d emulator-5554` art arda iki kez, APK başarıyla kurulup uygulama açıldıktan hemen sonra "Lost connection to device" mesajıyla (exit code 0) kendiliğinden sonlandı — Dart VM Service dev bağlantısı bu sandbox'lı arka-plan yürütme ortamında güvenilir değil. Bir noktada emulator süreci de tamamen çöktü (`adb devices` boş liste döndürdü). **Çözüm/iş akışı:** `flutter run`'ın geliştirme bağlantısına bağımlı kalmak yerine, APK zaten derlenmiş olduğundan `adb install -r build\app\outputs\flutter-apk\app-debug.apk` ile kurulup `adb shell am start -n com.example.ai_investment_app/.MainActivity` ile doğrudan başlatıldı — bu, doğrulamayı kararsız dev-tools bağlantısından tamamen ayırdı ve güvenilir şekilde çalıştı.

**Karşılaşılan hata / çözüm (dokunma koordinatları):**
İlk denemelerde "Alış Fiyatı"/"Adet" alanlarına görsel tahminle hesaplanan koordinatlarla dokunulduğunda diyalog beklenmedik şekilde kapandı (`Henüz pozisyon eklenmedi.` durumuna geri döndü). Kök neden: metin klavyesi açıldığında `AlertDialog` ekranda yukarı kayıyor (klavyenin kapladığı alanı boşaltmak için) — klavye açılmadan ÖNCE alınan koordinatlar, klavye açıldıktan SONRA artık diyaloğun dışına (arka plandaki karartılmış "Dismiss" katmanına) denk geliyor ve diyaloğu kapatıyordu. **Çözüm:** her adımdan hemen önce `adb shell uiautomator dump` ile o anki gerçek widget sınırları (`bounds`) alınıp, tahmine değil bu kesin koordinatlara dokunuldu; klavye açıkken alınan yeni dump'la Adet alanı ve "Ekle" butonu doğru bulundu.

**Tarih / Not:**
14.08.2026 — Flutter Portföy ekranı (sekme geçişi, pozisyon ekleme diyaloğu, özet kart, silme) gerçek Android emulator'de, gerçek backend verisiyle uçtan uca test edildi. Sıradaki adım: AŞAMA 16+ (EventIntelligenceEngine, LLM kararı bekliyor) veya kullanıcının seçtiği başka bir aşama.

---

## 26. Sonraki Adım

Bu doküman, ana dokümanın **93. bölümündeki** ilkeye paralel olarak yaşayan bir kayıttır: her yeni kurulum adımı tamamlandığında hem [Bölüm 0'daki Özet Tablo](#0-kurulum-durumu-özet-tablosu) hem de ilgili araç bölümü güncellenmelidir. Kurulum tamamlandıktan sonra sıradaki iş, ana dokümanın **82. bölümündeki** "Tam Geliştirme Sırası" (AŞAMA 1 → AŞAMA 35) listesine geçmektir.

### 26.1 Güncel Durum Notu (14.08.2026 — bilgisayar değişikliği öncesi)

Bu proje **başka bir bilgisayara taşınacak**. Yeni makinede kaldığı yerden devam edebilmek için buraya güncel bir durum özeti düşülüyor (sohbet geçmişi otomatik taşınmıyor, bu dosya + kod tek kaynak olacak).

**Şu ana kadar tamamlanmış olanlar (hepsi bu dokümanda ayrıntılı, bkz. ilgili bölümler):**
- Bölüm 1-14: Tüm geliştirme araçları kurulu ve doğrulanmış (Git, VS Code, Flutter SDK, Android Studio+SDK+Emulator, Python, Node.js, Firebase CLI, FlutterFire CLI), Flutter projesi ve Firebase bağlantısı yapıldı.
- Bölüm 16-19: Backend — Asset modeli, MarketDataProvider (Yahoo Finance/BIST), TechnicalAnalysisEngine, DecisionEngine + AI Decision History (immutable kayıtlar).
- Bölüm 20: News Provider (Yahoo Finance haberleri, kaynak güvenilirlik sınıflandırması) — henüz bir haber analiz motoruna (EventIntelligenceEngine) bağlanmadı, LLM kararı bekliyor.
- Bölüm 21: Flutter Dashboard ekranı (AL/SAT/TUT kartları) — gerçek emulator'de doğrulandı.
- Bölüm 22: MacroAnalysisEngine (DXY, ABD 10Y faiz, VIX, petrol, altın, USD/TRY) — DecisionEngine'e entegre, Dashboard'da otomatik görünüyor.
- Bölüm 23: Portföy Modülü backend'i (ekle/listele/sil + kâr-zarar hesabı).
- Bölüm 24: RiskEngine (volatilite, max drawdown, portföy konsantrasyonu/HHI).
- Bölüm 25: Flutter Portföy ekranı (sekme geçişi, pozisyon ekleme diyaloğu, özet kart, silme) — gerçek emulator'de uçtan uca doğrulandı.

**Henüz yapılmamış olanlar / bilinen eksikler:**
- **EventIntelligenceEngine** (LLM gerektiriyor) — hangi sağlayıcı (OpenAI/Claude/başka) kullanılacağı hâlâ kullanıcı kararı bekliyor. Bu proje mimarisinin tek LLM'e bağımlı parçası.
- **Login/Auth ekranı + Firestore Security Rules** (AŞAMA 4/34) — **kullanıcı bu konuşmada bu aşamayı "sıradaki adım" olarak seçti ama başlanmadı.** Şu an Portföy modülünde `user_id` istemciden düz parametre olarak geliyor (`_demoUserId = 'demo_user'`), bu geçici bir MVP kısayolu; production öncesi mutlaka gerçek Firebase Auth + Security Rules ile değiştirilmeli.
- BacktestEngine / Walk-Forward Optimization (AŞAMA 28-29).
- Firebase Cloud Messaging bildirimleri (AŞAMA 32).
- Ek Flutter ekranları: Teknik Analiz detay, Haber Analizi, Makro Analiz, Geçmiş Kararlar, Performans, Ayarlar (AŞAMA 86).
- **Proje henüz bir git deposunda değil** (`git status` → "not a git repository"). Bilgisayar değişikliği için kodun taşınma yöntemi henüz kararlaştırılmadı (git init + GitHub private repo önerildi, kullanıcı onayı bekliyor) — alternatif olarak klasörün doğrudan kopyalanması (USB/OneDrive) da mümkün. `backend/.env` ve varsa `firebase-service-account.json` `.gitignore` içinde olduğu için bir git push ile taşınmaz, elle/güvenli bir kanalla ayrıca taşınmalı.

**Yeni bilgisayarda ilk yapılacaklar:**
1. Bu dokümanın (`KURULUM_GUNLUGU.md`) ve ana dokümanın (`AI_Yatirim_Analiz_Projesi_Ana_Dokuman.md`) yeni makineye kopyalanması (örn. Downloads klasörüne).
2. Proje kodunun taşınması (git clone veya klasör kopyası — yukarıdaki karara göre).
3. Bölüm 1-13'teki tüm araçların yeni makinede sıfırdan kurulması (bu makineye özgü kurulumlar, taşınmazlar) — bu doküman adım adım rehber olarak kullanılabilir.
4. `backend/.env` (ve varsa servis hesabı anahtarı) elle yeniden oluşturulmalı/kopyalanmalı.
5. Kaldığımız yerden devam: **Login/Auth ekranı + Security Rules** (kullanıcının seçtiği sıradaki aşama).

---

## 27. YENİ PC KURULUMU - 14.08.2026

> Bu bölüm, yukarıdaki 26.1'de planlanan taşımanın **bu (ikinci) bilgisayarda gerçekte nasıl uygulandığının** kaydıdır. Eski makinedeki (bölüm 1-26) kayıtlar korunmuştur, karıştırılmamıştır — bu tamamen yeni, ayrı bir günlük bölümüdür.

**Taşıma yöntemi (gerçekleşen):** Kod, git/GitHub yerine doğrudan klasör kopyalama (zip: `Projects.zip`, `.claude.zip`) ile taşındı; proje hâlâ bir git deposu değil. `.claude` klasörü de Masaüstü'ne kopyalandı ve eski oturum kayıtları (`file-history`) üzerinden bu dosyanın (`KURULUM_GUNLUGU.md`, eskiden `Downloads` altındaydı) v20 + 26.1 içeriği eksiksiz kurtarılıp proje köküne (`ai_investment_app\KURULUM_GUNLUGU.md`) yazıldı — Downloads'taki orijinali kopyalanmamıştı. Ana doküman (`AI_Yatirim_Analiz_Projesi_Ana_Dokuman.md`) taşınamadı, kullanıcıda yedeği yok; bu bölümden sonraki kurulumlar onsuz, yalnızca bu günlüğe dayanarak ilerletildi.

**Kullanıcı hesabı farkı:** Eski makinede Windows kullanıcı adı `Nolto TC` idi (yollar `C:\Users\Nolto TC\...`); bu makinede `Nolto Teknoloji` (yollar `C:\Users\Nolto Teknoloji\...`). Bu yüzden PATH, `ANDROID_HOME`, `JAVA_HOME` gibi tüm ortam değişkenleri ve SDK/proje yolları bu makinede sıfırdan, yeni kullanıcı yoluna göre kurulacak.

| Araç | Önceden kurulu muydu? | Kurulan sürüm | Kullanılan komut | Doğrulama | Hata | Çözüm | Son durum |
|---|---|---|---|---|---|---|---|
| Git | ✅ Evet (önceden) | 2.55.0.windows.3 | — | `git --version` | — | — | ✅ |
| Node.js | ✅ Evet (önceden) | v24.19.0 | — | `node -v` | — | — | ✅ |
| npm | ✅ Evet (önceden) | 11.17.0 | — | `npm -v` | — | — | ✅ |
| Python | ❌ Hayır | 3.13.15 | `winget install --id Python.Python.3.13 -e --source winget --accept-package-agreements --accept-source-agreements` | `python --version` → Python 3.13.15; `pip --version` → pip 26.2.1 | Kurulumdan hemen sonra `python --version` "Python bulunamadı" verdi (App Execution Alias stub / PATH oturuma yansımamış) | `$env:Path = ...Machine + User` ile PATH oturum içinde yenilendi | ✅ |
| Flutter/Dart SDK | ❌ Hayır | Flutter 3.47.0 / Dart 3.13.0 | Aynı sürüm hâlâ güncel (releases_windows.json ile doğrulandı); zip indirilip `C:\development\flutter`'a çıkarıldı, `bin` klasörü kullanıcı PATH'ine eklendi | `flutter --version` / `dart --version` → eski makineyle birebir aynı sürümler | — | — | ✅ |
| Java (Android Studio JBR) | ❌ Hayır | | | | | | ⬜ |
| Android Studio + SDK + Emulator | ❌ Hayır | Studio 2026.1.3.7, build-tools 37.0.0, platform android-36, emulator 37.1.11, AVD Pixel_7_API_36 | `winget install --id Google.AndroidStudio ...`; cmdline-tools indirilip `C:\Android\sdk\cmdline-tools\latest`'a çıkarıldı; `ANDROID_HOME`/`JAVA_HOME` (Android Studio JBR) kullanıcı ortam değişkeni olarak ayarlandı; `sdkmanager --licenses` (cevap dosyasıyla); `sdkmanager "platform-tools" "build-tools;37.0.0" "platforms;android-36" "emulator" "system-images;android-36;google_apis;x86_64"`; `avdmanager create avd -n Pixel_7_API_36 ...` | `flutter doctor -v` → Android toolchain [√], Windows Version [√], Chrome [√], Connected device [√], Network resources [√] (Visual Studio [X] — gerekli değil, mobil odaklı) | `avdmanager create avd`: "Could not load devices from ...\devices.xml" | Kozmetik hata, `avdmanager list avd` ile AVD'nin gerçekten oluştuğu doğrulandı (eski makinedeki AYNI davranış) | ✅ |
| Firebase CLI + Login | ❌ Hayır | 15.27.0 | `npm install -g firebase-tools`; kullanıcı kendi terminalinde `firebase login` | `firebase --version` → 15.27.0; `firebase projects:list` → ai-investment-app-2026 + siirolog-51194 görüldü | `firebase projects:list` → `getaddrinfo ENOENT firebase.googleapis.com` (Wi-Fi router DNS'i googleapis.com'u engelliyordu — eski makinedeki AYNI sorun, bkz. Bölüm 8) | Yönetici PowerShell'de (kullanıcı tarafından) `Set-DnsClientServerAddress -InterfaceAlias "Wi-Fi" -ServerAddresses ("8.8.8.8","8.8.4.4")` + `ipconfig /flushdns` | ✅ |
| FlutterFire CLI | ❌ Hayır | 1.4.1 | `dart pub global activate flutterfire_cli` | `flutterfire --version` → 1.4.1 | "flutterfire not recognized" — pub-cache/bin PATH'te değildi (eski makinedeki AYNI sorun) | `C:\Users\Nolto Teknoloji\AppData\Local\Pub\Cache\bin` kullanıcı PATH'ine eklendi | ✅ |
| Google Cloud SDK + ADC | ❌ Hayır | SDK: 580.0.0 | `winget install --id Google.CloudSDK ...`; kullanıcı kendi terminalinde `gcloud auth application-default login`; `gcloud auth application-default set-quota-project ai-investment-app-2026`; `gcloud config set project ai-investment-app-2026` | `%APPDATA%\gcloud\application_default_credentials.json` oluştu; `firebase firestore:databases:list` → `projects/ai-investment-app-2026/databases/(default)` (STANDARD/FIRESTORE_NATIVE) zaten mevcut, yeniden oluşturulmadı | — | — | ✅ |
| Backend `.venv` (yeniden) | ⚠️ Eski makineden kopya, geçersiz sayıldı | requirements.txt'teki tüm sürümlerle birebir | Eski `.venv` silindi; `python -m venv .venv`; `pip install --upgrade pip`; `pip install -r requirements.txt` | `pip list` → fastapi 0.141.1, firebase_admin 7.5.0, pandas 3.0.5, yfinance 1.5.2, ... (requirements.txt ile birebir eşleşti) | — | — | ✅ |

| Windows Geliştirici Modu | ❌ Hayır | — | Ayarlar → Gizlilik ve güvenlik → Geliştiriciler için (kullanıcı tarafından, GUI üzerinden — registry HKLM'ye bu terminal yazamadığı için) | `flutter pub get` sonrasında symlink uyarısı kayboldu, `flutter analyze` → "No issues found!" | `flutter pub get`: "Building with plugins requires symlink support. Please enable Developer Mode" | Kullanıcı Ayarlar üzerinden Geliştirici Modu'nu açtı | ✅ |
| Flutter proje bağımlılıkları (`pub get`) | — | — | `flutter pub get` (mevcut projede, `firebase_options.dart`/`google-services.json`'a dokunulmadı) | `flutter analyze` → No issues found! | — | — | ✅ |

| Emulator Hypervisor (yeni sorun, eski günlükte yoktu) | ❌ Hayır | Windows Hypervisor Platform | Kullanıcı tarafından yönetici PowerShell'de `Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -All -NoRestart` + PC yeniden başlatma | Emulator "hypervisor driver is not installed" hatası olmadan açıldı | `emulator.exe`: "x86_64 emulation currently requires hardware acceleration! ... hypervisor driver is not installed" | Windows Hypervisor Platform özelliği açılıp bilgisayar yeniden başlatıldı. Not: Eski makinede bu adım muhtemelen Android Studio'nun GUI ilk-kurulum sihirbazı tarafından otomatik yapılmıştı; biz command-line-only SDK kurulumu kullandığımız için atlanmıştı. | ✅ |
| Uçtan uca test | — | — | Backend `--host 0.0.0.0` ile başlatıldı; `flutter build apk --debug`; `adb install -r` + `adb shell am start`; `adb shell screencap` ile görsel doğrulama | `/health`→ok, `/assets`→6 kayıt, `/decisions/THYAO`→gerçek skor (Firestore hâlâ eski makinedeki verilerle dolu, yeniden seed gerekmedi); emulator ekranında THYAO/ASELS/GARAN gerçek technical/macro skorlarla göründü | `flutter build apk`: "JAVA_HOME is not set" (bu terminal oturumunda unutulmuştu, ayrı bir sorun değil); ilk ekran görüntüsünde emulator'e özgü kozmetik "System UI isn't responding" (soğuk açılış) diyaloğu çıktı | JAVA_HOME oturuma eklenip build tekrarlandı; ANR diyaloğu "Wait" ile geçildi, ikinci ekran görüntüsünde normal görünüm doğrulandı | ✅ |

*(Bu tablo, her araç bu makinede kurulup doğrulandıkça satır satır güncellenecektir.)*

### 27.1 Sonuç

Bu bilgisayarda kurulum tamamen bitti ve proje eski makinedeki son durumuyla (AŞAMA 25'e kadar) birebir çalışır durumda doğrulandı: backend gerçek Firestore verisine bağlanıyor, Flutter uygulaması gerçek Android emulator'de backend'den canlı veri çekip gösteriyor. Sıradaki iş, 26.1'de belirtildiği gibi **Login/Auth ekranı + Firestore Security Rules**.

Eski makineden farklı olarak bu bilgisayarda karşılaşılan tek yeni sorun **Android Emulator Hypervisor** eksikliğiydi (yukarıda çözüldü) — muhtemelen eski makinede Android Studio'nun GUI kurulum sihirbazı çalıştırıldığı için bu adım orada görünmemişti.

### 27.2 Git Deposuna Alma (14.08.2026)

26.1'de not edilen eksiklerden biri ("Proje henüz bir git deposunda değil") bu oturumda giderildi:

- `git init` ile proje kök dizininde depo başlatıldı.
- Commit kimliği bu depoya özel ayarlandı: `Ensar Çiçek <ensarcckk@gmail.com>` (global git config'e dokunulmadı).
- `.gitignore`'a `.claude/settings.local.json` eklendi (Claude Code'un bu makineye özel, gizli olmayan ama makineye özgü yerel izin ayarları — depoya girmemeli).
- Commit öncesi kontrol: `backend/.env`, `backend/.venv`, herhangi bir servis hesabı/`.pem` dosyası staged listede **yoktu**; `android/app/google-services.json` normal şekilde eklendi (client config, gizli anahtar değil).
- İlk commit: 182 dosya, "İlk commit: AI Yatırım Analiz uygulaması (Flutter + FastAPI backend)".
- **Uzak depo (GitHub vb.) henüz bağlanmadı** — bu tamamen yerel bir depo. İleride uzak bir depoya push edilmek istenirse ayrıca ele alınmalı.

---

## 28. AŞAMA 30-31 (Devam) — Portföy Ortalama Maliyet Birleştirme (17.08.2026)

Aynı varlıktan (ör. THYAO) birden fazla farklı fiyattan alım yapıldığında, portföy listesinde her alımın ayrı bir satır olarak görünmesi yerine tek satırda ağırlıklı ortalama maliyetle birleştirilmesi istendi.

**Değişen dosyalar (backend):**
```text
app/api/portfolio.py                 → GET /portfolio/positions artık kayıtları asset'e göre grupluyor,
                                         ağırlıklı ortalama alış fiyatı = sum(qty×price)/sum(qty) hesaplıyor
app/repositories/portfolio_repository.py → delete() kaldırıldı, yerine delete_for_asset(user_id, asset)
                                         eklendi (bir varlığa ait tüm lotları tek seferde siler)
```
Firestore'da her alım **hâlâ ayrı bir doküman** olarak saklanıyor (işlem geçmişi/audit trail korunuyor) — birleştirme yalnızca `GET` yanıtında, sunum katmanında yapılıyor. `DELETE /portfolio/positions/{asset}` artık tek bir lot değil, o varlığa ait tüm lotları siliyor (liste ekranında artık tek satır olarak göründükleri için).

**Değişen dosyalar (Flutter):**
```text
lib/models/portfolio_position.dart   → id alanı kaldırıldı, lotCount eklendi
lib/services/api/portfolio_api.dart  → deletePosition artık asset bazlı
lib/features/portfolio/portfolio_screen.dart → birden fazla lot varsa "(N alım)" etiketi gösteriliyor
```

**Doğrulama (gerçek Firestore + emulator):**
```text
POST asset=GARAN buy_price=100 quantity=5
POST asset=GARAN buy_price=200 quantity=5
GET  → {"asset":"GARAN","quantity":10,"buy_price":150.0,"lot_count":2, ...}   ← (5×100+5×200)/10=150 ✓
```
Emulator'de "GARAN • 10 adet (2 alım)", "Ort. Alış: 150.00 TL" olarak doğru göründü; silme her iki lotu birden temizledi.

**Karşılaşılan hata / çözüm:**
Yok — ilk denemede sorunsuz çalıştı.

**Tarih / Not:**
17.08.2026 — Ortalama maliyet birleştirme uçtan uca test edildi, commit `82865d8`.

---

## 29. AŞAMA 24 — AIExplanationEngine (17.08.2026)

Dashboard'daki "Neden AL/SAT/TUT?" butonu o zamana kadar sadece "AIExplanationEngine henüz uygulanmadı" yazan bir placeholder'dı. Kural tabanlı (LLM'siz) bir açıklama motoruyla dolduruldu — proje mimarisinde bilinçli olarak yalnızca EventIntelligenceEngine'in LLM'e bağımlı bırakılması kararına uygun.

**Oluşturulan/değişen dosyalar (backend):**
```text
app/engines/explanation/engine.py   → ExplanationEngine: TechnicalAnalysisEngine ve MacroAnalysisEngine'in
                                        bileşen kırılımını (RSI, MACD, trend, VIX, DXY, vb.) en etkili 3
                                        faktöre göre sıralayıp Türkçe cümlelere çeviriyor
app/api/decisions.py                → GET /decisions/{symbol}/explanation eklendi
```
Üretilen açıklama, AI Decision History'e **yazılmıyor** (`persist=False`) — bu uç nokta yalnızca mevcut kararın gerekçesini gösterir, yeni bir resmi karar kaydı oluşturmaz.

**Oluşturulan/değişen dosyalar (Flutter):**
```text
lib/models/explanation.dart                  → Explanation modeli
lib/services/api/decision_api.dart           → fetchExplanation eklendi
lib/features/dashboard/dashboard_screen.dart → "Neden X?" butonu artık gerçek bir AlertDialog açıyor
```

**Doğrulama (gerçek Firestore + Yahoo Finance + emulator):**
```text
GET /decisions/THYAO/explanation
→ "THYAO için 'ZAYIF SAT' kararı verildi (final skor: -17.3, güven: %57)."
   Teknik: Bollinger Bantları -45.3, ROC -27.1, Momentum -26.4 (hepsi olumsuz)
   Makro: Altın -90.0, VIX +27.7, ABD 10Y Faizi -16.6
   Not: "Haber analizi (EventIntelligenceEngine) henüz uygulanmadı, karara dahil edilmedi."
```
Emulator'de diyalog gerçek verilerle doğru göründü, Kapat butonu düzgün çalıştı.

**Karşılaşılan hata / çözüm:**
Yok — ilk denemede sorunsuz çalıştı.

**Tarih / Not:**
17.08.2026 — AIExplanationEngine uçtan uca test edildi, commit `d301a96`.

---

## 30. AŞAMA 4/34 — Firebase Auth Login Ekranı + Backend Token Doğrulama (17.08.2026)

AŞAMA 23/25'te (bkz. [Bölüm 23](#23-aşama-30-31--portföy-modülü--kâr-zarar)) bilinçli olarak ertelenen güvenlik eksiği kapatıldı: gerçek bir Login/Register ekranı ve backend'de Firebase ID token doğrulaması eklendi. `demo_user` sabit kullanıcı kimliği tamamen kaldırıldı.

**Karar (kullanıcıya soruldu, ikisi de "Önerilen" seçildi):**
1. Giriş yöntemi: **E-posta/Şifre** (Google Sign-In'in gerektirdiği ekstra OAuth kurulumu istenmedi).
2. Backend güvenliği: **Gerçek token doğrulama** — yalnızca UI eklemek "görsel" kalırdı, çünkü backend Firestore'a Admin SDK ile bağlanıyor ve bu, Firestore Security Rules'ı tamamen bypass ediyor. Gerçek güvenlik sınırı ancak backend'in her istekte Firebase ID token'ı doğrulamasıyla sağlanabilir.

**Oluşturulan/değişen dosyalar (backend):**
```text
app/core/auth.py            → get_current_user_id: Authorization: Bearer <token> header'ını
                                firebase_admin.auth.verify_id_token ile doğrulayıp gerçek uid döner;
                                token yoksa/geçersizse 401
app/api/portfolio.py        → tüm endpoint'ler artık user_id parametresi yerine
                                Depends(get_current_user_id) kullanıyor
app/api/risk.py             → portfolio/concentration endpoint'i aynı şekilde güncellendi
app/schemas/portfolio.py    → PortfolioPositionCreate'ten user_id alanı kaldırıldı (artık token'dan geliyor)
```

**Oluşturulan/değişen dosyalar (Flutter):**
```text
lib/features/auth/login_screen.dart   → e-posta/şifre ile giriş+kayıt formu (tek ekran, mod değiştirme)
lib/main.dart                          → AuthGate: authStateChanges() dinleyip LoginScreen/RootScreen arasında geçiyor
lib/features/dashboard/dashboard_screen.dart,
lib/features/portfolio/portfolio_screen.dart → AppBar'a "Çıkış Yap" ikonu eklendi
lib/services/api/portfolio_api.dart    → her istek FirebaseAuth.instance.currentUser.getIdToken() ile
                                          Authorization header'ı ekliyor
```

**Firestore Security Rules (savunma katmanı):**
`firestore.rules` oluşturulup `firebase deploy --only firestore:rules` ile canlı projeye deploy edildi — `portfolio_positions` koleksiyonunda kullanıcı yalnız `request.auth.uid == resource.data.user_id` eşleşen kendi verisini okur/siler, diğer tüm koleksiyonlar istemciye tamamen kapalı. **Not:** Backend Admin SDK kullandığı için bu kurallar şu an hiçbir isteği etkilemiyor — yalnızca ileride doğrudan istemci-Firestore erişimi eklenirse devreye giren bir savunma katmanı.

**Karşılaşılan hata / çözüm (uzun bir zincir — sırayla elendi):**
İlk kayıt denemesi Android logcat'te `RecaptchaCallWrapper ... CONFIGURATION_NOT_FOUND` hatasıyla başarısız oldu. Kök nedene ulaşmak için sırayla kontrol edilip düzeltildi:
1. **Android uygulamasının SHA-1/SHA-256 sertifika parmak izleri Firebase projesine hiç kayıtlı değildi** (bu app o zamana kadar Auth kullanmadığı için gerek olmamıştı) → `keytool` ile debug keystore'dan çıkarılıp `firebase apps:android:sha:create` ile eklendi. Hata devam etti.
2. **Proje Blaze (ücretli) planına bağlı değildi** (`gcloud billing projects describe` → `billingEnabled: false`) — Firebase Auth'un reCAPTCHA Enterprise tabanlı kötüye kullanım koruması billing gerektiriyor → kullanıcı Firebase Console'dan Blaze'e geçti, `recaptchaenterprise.googleapis.com` API'sini etkinleştirdi. Hata devam etti.
3. **Kesin kanıt için** `identitytoolkit.googleapis.com/admin/v2/projects/{project}/config` doğrudan REST ile sorgulandı → `404 CONFIGURATION_NOT_FOUND`. Bu, yukarıdakilerin hiçbirinin asıl neden olmadığını, **bu proje için Firebase Authentication ürününün hiç başlatılmamış olduğunu** (Console'da "Get Started" hiç tıklanmamış) kanıtladı — Blaze/SHA/reCAPTCHA gerçekten eksikti ve düzeltilmesi gerekiyordu, ama asıl blokaj bu değildi.
4. Kullanıcı Firebase Console → Authentication → "Get Started" → E-posta/Şifre sağlayıcısını etkinleştirdi → aynı config sorgusu `signIn.email.enabled: true` döndü → kayıt anında başarılı oldu, gerçek bir Firebase UID üretildi.

**Doğrulama (gerçek Android emulator, uçtan uca):**
1. Uygulama ilk açılışta LoginScreen gösterdi (henüz giriş yapılmamış).
2. `test@example.com` ile kayıt olundu → `FirebaseAuth: Notifying id token listeners about user (0nUrHXSkxPZYYL1HnsSkmjpT4hB3)` → otomatik olarak Dashboard'a yönlendirildi.
3. Portföy sekmesinde boş liste hatasız yüklendi (backend log: token'sız `401`, token'lı `200 OK` — net karşılaştırma).
4. THYAO 500 TL / 3 adet eklendi, gerçek UID ile Firestore'a yazıldığı ve PnL'in doğru hesaplandığı doğrulandı; silme de çalıştı.
5. "Çıkış Yap" ikonuna basıldı → `FirebaseAuth.instance.signOut()` → uygulama otomatik olarak LoginScreen'e geri döndü.

**Tarih / Not:**
17.08.2026 — Login/Auth + backend token doğrulama uçtan uca test edildi, commit `9a10d66`. Bilinen sınır: e-posta doğrulama (email verification) ve şifre sıfırlama akışı bu MVP'de henüz yok; tek kullanıcı için şu an gerekli görülmedi.

---

## 31. AŞAMA 28-29 — BacktestEngine & Walk-Forward Optimization (17.08.2026)

Geçmiş fiyat verisi üzerinde DecisionEngine'in ürettiği sinyallerin gerçekte ne kadar iyi çalıştığını ölçen iki backend motoru.

**Kapsam kararı:** Yalnızca `technical_score` kullanılıyor. `news_score` zaten hiç mevcut değil (EventIntelligenceEngine, LLM bekliyor); `macro_score`'un ise günlük geçmiş serisi henüz saklanmıyor (`macro_snapshots` yalnızca "son görülen" durumu tutuyor, ana doküman kural 6). DecisionEngine'in "Missing Data Davranışı" ilkesi sayesinde bu, kararın yanlış olmasına değil, mevcut tek skorun ağırlığının otomatik %100'e normalize edilmesine yol açıyor — canlı sistemle birebir aynı davranış sözleşmesi.

**Oluşturulan dosyalar (backend):**
```text
app/engines/backtest/engine.py        → technical_score_series() (TechnicalAnalysisEngine ile aynı
                                          formül, vektörize/tüm seri için), simulate() (sinyalde
                                          pozisyon aç/kapat stratejisi), BacktestEngine.run()
app/engines/backtest/walk_forward.py  → WalkForwardOptimizer: veriyi kayan pencerelere bölüp karar
                                          eşiklerini yalnızca eğitim penceresinde seçer, test
                                          penceresinde (out-of-sample) dener
app/api/backtest.py                    → GET /backtest/{symbol}?period=2y
                                          GET /backtest/{symbol}/walk-forward?period=3y
app/main.py                            → backtest router bağlandı
```

**Mimari not (bilinçli, dokümante edilmiş):** `technical_score` formülü `TechnicalAnalysisEngine.analyze_with_id` ile elle senkronize tutuluyor, ortak bir yardımcıya taşınmadı — canlı motor yalnızca son günü hesaplarken backtest tüm seriyi vektörize hesaplaması gerektiğinden, paylaşılan soyutlama şu an için gereğinden fazla karmaşıklık katardı (bkz. proje ilkesi: erken soyutlamadan kaçınma).

**Walk-forward tasarım kararı:** Optimize edilen parametre 6 teknik gösterge ağırlığı değil, yalnızca DecisionEngine'in karar eşikleri (buy/weak_buy/weak_sell/sell) — küçük ve yorumlanabilir bir arama uzayı (3 aday: varsayılan/agresif/muhafazakar), "ne kadar sık işlem yapılsın" sorusuna doğrudan karşılık geliyor.

**Doğrulama (gerçek Yahoo Finance verisiyle):**
```text
GET /backtest/THYAO?period=2y
→ 12 işlem, %50 kazanma oranı, toplam getiri -2.43% (al-tut: +9.31%), max drawdown -19.3%

GET /backtest/THYAO/walk-forward?period=3y
→ 6 pencere, pencere kazanma oranı %33.33, out-of-sample bileşik getiri: -14.8%
```
Sayılar iç tutarlı (equity curve, işlem giriş/çıkış fiyatları, pencere tarihleri ardışık). Walk-forward sonucunun düz backtest'ten daha kötü çıkması **beklenen ve dürüst bir sonuç** — basit backtest, eşikleri tüm veriye bakarak seçmenin (üstü kapalı) avantajını taşırken, walk-forward bunu engelliyor ve stratejinin gerçek zamanlı koşullarda ne kadar zayıf kaldığını gösteriyor; sayı iyi görünsün diye ayarlanmadı.

**Flutter tarafı:** Şu an yok — RiskEngine (AŞAMA 33, [Bölüm 24](#24-aşama-33--riskengine)) gibi bilinçli olarak backend-only bırakıldı.

**Karşılaşılan hata / çözüm:**
Yok — ilk denemede sorunsuz çalıştı.

**Tarih / Not:**
17.08.2026 — BacktestEngine ve WalkForwardOptimizer gerçek THYAO verisiyle uçtan uca test edildi, commit `3638fcf`.

---

## 32. Ek Flutter Ekranları — Varlık Detayı, Makro, Ayarlar (17.08.2026)

Ana doküman bölüm 86'da listelenen ek ekranlardan (Teknik Analiz detay, Haber Analizi, Makro Analiz, Geçmiş Kararlar, Performans, Ayarlar) hepsi tek oturumda eklendi.

**Navigasyon kararı (kullanıcıya soruldu):** Teknik/Haberler/Geçmiş/Performans varlık-bazında olduğu için Dashboard'daki her hisse kartı tıklanabilir yapıldı ve 4 sekmeli (Teknik/Haberler/Geçmiş/Performans) tek bir `AssetDetailScreen`'e yönlendirildi — alt navigasyona 6 ayrı sekme eklemek yerine. Makro (piyasa geneli) ve Ayarlar (uygulama geneli) için alt navigasyona 2 yeni sekme eklendi (toplam 4: Analiz/Portföy/Makro/Ayarlar). Ayarlar sade tutuldu: hesap e-postası, uygulama sürümü, çıkış yap — karar ağırlıklarının ekrandan düzenlenmesi (system_config) kapsam dışı bırakıldı.

**Backend'de eksik olup eklenen parçalar:**
```text
app/api/news.py                          → GET /news/{symbol}: YahooNewsProvider ile canlı haber
                                             çekip NewsRawRepository'ye upsert eder, listeyi döner
app/repositories/ai_decision_repository.py → list_for_asset(asset, limit) eklendi (önceden yalnızca
                                             get_latest vardı, geçmiş karar listesi mümkün değildi)
app/api/decisions.py                      → GET /decisions/{symbol}/history eklendi
```
`GET /analysis/{symbol}/technical` ve `GET /analysis/macro` (AŞAMA 18/22'den) ve `GET /backtest/{symbol}` (AŞAMA 28) zaten mevcuttu, değiştirilmedi.

**Oluşturulan dosyalar (Flutter):**
```text
lib/utils/decision_style.dart                 → decisionLabel()/decisionColor() — Dashboard'daki
                                                  private kopyalar buradan tek kaynağa taşındı
lib/models/technical_analysis.dart, macro_snapshot.dart, news_item.dart, backtest_result.dart
lib/services/api/analysis_api.dart, news_api.dart, backtest_api.dart
lib/services/api/decision_api.dart            → fetchHistory() eklendi
lib/features/asset_detail/asset_detail_screen.dart → 4 sekme: Teknik (gösterge katkıları + ham
                                                  değerler), Haberler ("ham/işlenmemiş" uyarı notuyla),
                                                  Geçmiş (kronolojik karar listesi), Performans
                                                  (backtest özeti + işlem listesi)
lib/features/macro/macro_screen.dart          → makro skor + 6 göstergenin katkısı/ham değeri
lib/features/settings/settings_screen.dart    → hesap + sürüm + çıkış yap
```

**Doğrulama (gerçek Android emulator, uçtan uca):**
1. Giriş yapıldı (bkz. aşağıdaki ağ notu), 4 sekmeli alt navigasyon (Analiz/Portföy/Makro/Ayarlar) doğrulandı.
2. THYAO kartına dokunulup `AssetDetailScreen` açıldı; 4 sekmenin hepsi gerçek veriyle test edildi:
   - **Teknik:** Skor -30.2/BEARISH, 6 gösterge katkısı (RSI, MACD, Trend, Bollinger, Momentum, ROC) ve ham değerler doğru göründü.
   - **Haberler:** 5 gerçek Yahoo Finance haberi, yayıncı ve güvenilirlik yüzdesiyle; "AI analizi henüz yok" uyarı notu görünüyor.
   - **Geçmiş:** 14.08'den 17.08'e uzanan kronolojik karar listesi, doğru renk/etiketlerle.
   - **Performans:** Backtest özeti (Strateji -2.4%, Al-Tut +8.9%, Max Düşüş -19.3%, 12 işlem/%50) ve işlem listesi.
3. Makro sekmesi: 6 göstergenin (DXY, ABD 10Y, VIX, Petrol, Altın, USD/TRY) hem katkı puanı hem ham değer+yüzde değişimi doğru göründü.
4. Ayarlar sekmesi: hesap e-postası, sürüm, çıkış yap — çalıştı.

**Karşılaşılan hata / çözüm (ağ dalgalanması, kod hatası değil):**
Doğrulama sırasında emulator'ün ağ bağlantısı geçici olarak yavaşladı (ping ~500ms): (1) Firebase Auth girişi `network-request-failed` (reCAPTCHA doğrulama isteği zaman aşımı) ile art arda birkaç kez başarısız oldu, birkaç tekrar denemeden sonra geçti; (2) GARAN'ın teknik analiz sekmesinde bir kerelik `HTTP 422` hatası çıktı — backend'i doğrudan `curl` ile aynı anda test ettiğimde sorunsuz tam yanıt döndüğü görüldü, yani backend'de bir hata yoktu, yalnızca o anki istek ağ gecikmesinden etkilenmişti. Her iki durumda da hata ekranı Flutter tarafında düzgün gösterildi (uygulama çökmedi) — bu da `FutureBuilder`/`snapshot.hasError` hata yönetiminin doğru çalıştığının kanıtı.

**Tarih / Not:**
17.08.2026 — Ek Flutter ekranları (Varlık Detayı 4 sekme, Makro, Ayarlar) gerçek emulator'de uçtan uca test edildi, commit `809195c`.

---

## 33. İlk Otomatik Test Paketi (17.08.2026)

Projede daha önce hiç otomatik test yoktu — backend'de sıfır test dosyası, Flutter'da yalnızca `flutter create`'in ürettiği, hiç özelleştirilmemiş şablon `widget_test.dart` (var olmayan bir sayaç uygulamasını test ediyordu, `Firebase.initializeApp()` mock'lanmadığı için zaten patlıyordu). Bütün doğrulamalar bu güne kadar manuel yapılıyordu (curl + emulator screenshot). Kullanıcının "başka eksik var mı" sorusuna verilen kapsamlı kod taramasının ardından "test yaz" talebiyle eklendi.

**Kapsam kararı:** Firestore/ağ gerektiren repository ve API endpoint entegrasyon testleri (Firestore emulator kurulumu gerektirir) ile Firebase Auth mock'lanması gereken widget testleri **kapsam dışı** bırakıldı. Bunun yerine, zaten constructor'dan provider/repo enjekte edilebilecek şekilde tasarlanmış (bu proje baştan beri bu şekilde yazılmıştı) **saf/deterministik mantık** için birim testleri yazıldı — Firestore/Yahoo Finance'e hiç gitmeden, hızlı ve güvenilir.

**Backend — `backend/tests/` (pytest, 36 test):**
```text
conftest.py            → FakeMarketDataProvider fixture (sabit fiyat/geçmiş veri döndüren sahte provider)
test_indicators.py     → indicators.py'nin 8 fonksiyonu (sma, ema, rsi, macd, bollinger_bands, atr,
                          momentum, roc, volume_sma) — sentetik seriler üzerinde
test_decision_engine.py → _classify() eşik sınıflandırması (parametrize, 11 sınır durumu) + decide()'ın
                          eksik-veri ağırlık normalizasyonu ve persist=False'a saygı göstermesi
test_pnl_calculator.py → kâr/zarar/getiri hesabı (kâr, zarar, sıfır-yatırım durumu)
test_risk_engine.py    → portfolio_concentration (tek varlık/eşit dağılım/boş) + enjekte edilmiş
                          provider ile asset_risk
test_backtest_engine.py → technical_score_series sınırları + simulate()'in al-sat sinyali, düz kalma
                          ve dönem sonu açık pozisyon kapatma senaryoları
```
`requirements.txt`'e `pytest==9.1.1` (+ `iniconfig`, `packaging`, `pluggy`, `Pygments`) eklendi. Çalıştırma: `.venv/Scripts/python.exe -m pytest tests/` (backend/ dizininden — `-m` modül çağrısı cwd'yi otomatik `sys.path`'e ekliyor, bu proje zaten `-m uvicorn` ile aynı desenle çalıştırılıyordu, ekstra `pytest.ini`/`conftest.py` yol ayarı gerekmedi).

**Flutter — `test/` (flutter_test, 12 test):**
```text
test/widget_test.dart          → KALDIRILDI (bozuk şablon)
test/utils/decision_style_test.dart      → decisionLabel/decisionColor (5 bilinen karar + bilinmeyen durum)
test/models/decision_test.dart           → Decision.fromJson (tüm alanlar + created_at eksik durumu)
test/models/portfolio_position_test.dart → PortfolioPosition.fromJson (çoklu lot birleşimi + hata durumu),
                                            PortfolioSummary.fromJson
test/models/backtest_result_test.dart    → BacktestTrade/BacktestResult.fromJson (iç içe işlem listesi)
```

**Doğrulama:**
```text
.venv/Scripts/python.exe -m pytest tests/ -v   → 36 passed
flutter test                                    → 12 passed (+0)
flutter analyze                                 → No issues found!
```

**Karşılaşılan hata / çözüm (test yazarken gerçek bir edge-case bulundu):**
İlk RSI testi ("kesinlikle artan bir seri için RSI >95 olmalı") başarısız oldu — sonuç 50 çıktı. Kök neden kodda değil, test verisinde: `indicators.py`'nin `rsi()` fonksiyonu, mutlak monoton (hiç kaybı olmayan) bir seride `avg_loss` tam 0 olduğu için `rs = avg_gain/0` → NaN → `.fillna(50)` (nötr) devreye giriyor — RSI'ın klasik "tüm kazanç = 100" beklentisinin aksine. Bu, gerçek piyasa verisinde (asla mutlak monoton olmayan) neredeyse hiç karşılaşılmayan bir durum; kod değiştirilmedi, test küçük ara düşüşler içeren daha gerçekçi bir seriyle güncellendi ve bu davranış bir yorumla belgelendi.

**Tarih / Not:**
17.08.2026 — İlk otomatik test paketi (48 test, backend+Flutter) eklendi ve tamamı yeşil, commit `a760317`.

---

## 34. RiskEngine — Kalan Risk Metrikleri + Portföy Pozisyon Düzenleme (17.08.2026)

Kullanıcının kapsamlı kod taramasında (bkz. Bölüm 33'ün de kaynağı olan tarama) tespit edilen iki eksik aynı oturumda kapatıldı.

**RiskEngine — 4 yeni metrik:**
```text
asset_liquidity(symbol, quantity)  → ortalama günlük hacme göre elden çıkarma süresi (gün)
gap_risk(symbol)                    → önceki kapanış ile o günkü açılış arasındaki sıçrama (%)
market_risk(symbol, benchmark)      → BIST 100 (XU100) endeksine göre beta + korelasyon
portfolio_correlation(symbols)      → portföydeki varlıklar arası ortalama korelasyon matrisi
```
Yeni endpoint'ler: `GET /risk/{symbol}/liquidity|gap|market`, `GET /risk/portfolio/correlation`. 11 yeni test eklendi (`test_risk_engine.py`, toplam 43 backend testi). **Sektör riski hâlâ bilinçli olarak ertelendi** — `Asset` modelinde sektör alanı yok ve fabrikasyon veri kullanmamak ana doküman kural 11-12 gereği; gerçek bir sektör sınıflandırma kaynağı bulunana kadar eklenmeyecek.

**Doğrulama (gerçek THYAO/BIST100 verisiyle):**
```text
GET /risk/THYAO/market → beta: 1.0266, correlation_with_market: 0.7341
GET /risk/portfolio/correlation (THYAO+GARAN) → average_correlation: 0.7211
```

**Portföy pozisyon düzenleme:**
`PortfolioRepository.replace_for_asset()` — o varlığa ait tüm lotları tek yeni lotla değiştirir (AŞAMA 30-31'deki ortalama-maliyet-birleştirme görünümüyle tutarlı: kullanıcı tek bir birleşik satırı düzenliyormuş gibi davranır, ayrı alım tarihleri feda edilir). `PUT /portfolio/positions/{asset}` endpoint'i eklendi. Flutter'da kalem ikonu ile açılan düzenleme diyaloğu, mevcut ortalama fiyat/adetle önceden dolduruluyor.

Bu arada `portfolio_repository.py`'deki bayat "Auth henüz yazılmadı" güvenlik yorumu da güncellendi (AŞAMA 4/34'te Auth zaten yazılmıştı).

**Doğrulama (emulator):** THYAO 250 TL/10 adet eklendi → kalemle 300 TL/5 adete düzenlendi → liste Toplam Yatırım: 1500 TL (5×300) olarak doğru güncellendi → silindi.

**Karşılaşılan hata / çözüm:**
Yok — ilk denemede sorunsuz çalıştı.

**Tarih / Not:**
17.08.2026 — RiskEngine'in kalan metrikleri ve portföy düzenleme uçtan uca test edildi, commit `b40a673`.

---

## 35. Native Gösterge Rehberi Ekranı (17.08.2026)

Kullanıcı Makro Analiz ekranındaki yüzdelerin ne anlama geldiğini sordu; cevap önce bir Artifact sayfası (web) olarak yayınlandı, ardından "mobil projeye ekledin di mi" sorusu üzerine aynı içeriğin **native Flutter karşılığı** istendi ve eklendi.

**Oluşturulan dosya:** `lib/features/guide/guide_screen.dart` — Ayarlar'dan erişilen, `ExpansionTile` ile açılıp kapanan 7 bölümlü bir referans ekranı: Analiz (karar eşikleri tablosu + Confidence/Technical/News/Macro alanları), Varlık Detayı → Teknik/Haberler/Geçmiş/Performans, Makro (6 göstergenin yön sözleşmesi dahil), Portföy. Karar eşikleri tablosu, Dashboard'da zaten kullanılan `decisionColor`/`decisionLabel` yardımcılarını (AŞAMA 86/Ek Ekranlar, [Bölüm 32](#32-ek-flutter-ekranları--varlık-detayı-makro-ayarlar-17082026)) yeniden kullanıyor — tek kaynak korunuyor.

`lib/features/settings/settings_screen.dart`'a "Gösterge Rehberi" satırı eklendi (Hesap ile Uygulama Sürümü arasına).

**Doğrulama (emulator):** Ayarlar → Gösterge Rehberi açıldı, 7 bölüm başlığı doğru göründü; Performans ve Makro bölümleri genişletilip içerik (özellikle kullanıcının sorduğu Makro yön sözleşmesi açıklaması) doğru render olduğu doğrulandı. `flutter analyze`: bir yazım hatası (`_MakroSection` vs `_MacroSection` isim uyuşmazlığı) ve fazladan bir `}` parantez hatası düzeltildi, sonra temiz. `flutter test`: 12/12 geçti.

**Karşılaşılan hata / çözüm:**
İlk yazımda `_MakroSection()` (main listede) ile `_MacroSection` (sınıf tanımı) arasında Türkçe/İngilizce yazım tutarsızlığı vardı — `flutter analyze` `undefined_method` hatasıyla hemen yakaladı, isim düzeltildi. Ayrıca bir bölüm sonunda yanlışlıkla `}}` (fazladan kapanış parantezi) vardı, kaldırıldı.

**Tarih / Not:**
17.08.2026 — Native Gösterge Rehberi eklendi ve emulator'de doğrulandı, commit `c710b1a`.

---

## 36. AŞAMA 32 — FCM Push Bildirimleri (17-18.08.2026)

**Mimari kısıt (kullanıcıya soruldu, karar alındı):** Bu projede hiç zamanlayıcı/scheduler (cron, APScheduler, Cloud Scheduler) yok — her motor yalnızca bir HTTP isteği geldiğinde çalışıyor. Bu yüzden "gerçek zamanlı, arka planda kendiliğinden" bildirim mümkün değil. Seçilen yaklaşım: kullanıcı bir kararı sorguladığında (`GET /decisions/{symbol}` — Dashboard her açıldığında zaten çağrılıyor) sonuç güçlü bir AL/SAT ise ve bu, o kullanıcı için daha önce bildirilmemiş yeni bir kararsa, bildirim gönderilir. Aynı kararın her Dashboard açılışında tekrar tekrar bildirilmemesi için `notification_log` koleksiyonunda basit bir "son bildirilen karar" karşılaştırması tutuluyor.

**Oluşturulan dosyalar (backend):**
```text
app/models/fcm_token.py                        → FcmToken (user_id, token, updated_at)
app/repositories/fcm_token_repository.py        → kullanıcı başına tek cihaz token'ı (doküman ID = user_id)
app/repositories/notification_log_repository.py → {user_id}_{asset} başına son bildirilen karar
app/services/notifications/fcm_sender.py        → notify_if_strong_decision() — repo'lar enjekte edilebilir
app/schemas/notifications.py, app/api/notifications.py → POST /notifications/register-token
app/core/auth.py                                → get_current_user_id_optional eklendi (401 fırlatmaz, None döner)
app/api/decisions.py                            → GET /decisions/{symbol} artık opsiyonel auth alıp
                                                     bildirimi tetikliyor; yetkisiz çağrılar hâlâ normal çalışıyor
```
5 yeni test (`test_fcm_sender.py`, `messaging.send` monkeypatch ile taklit ediliyor — gerçek ağa hiç gitmiyor), toplam 53 backend testi.

**Oluşturulan/değişen dosyalar (Flutter):**
```text
pubspec.yaml                          → firebase_messaging ^16.5.0 (flutter pub add ile çözümlendi)
lib/services/api/notification_api.dart → registerToken()
lib/services/notification_service.dart → izin iste, token al, backend'e kaydet, foreground mesajını SnackBar ile göster
lib/main.dart                          → RootScreen girişte NotificationService.initialize()'ı çağırıyor
android/.../AndroidManifest.xml        → POST_NOTIFICATIONS izni (Android 13+)
```

**Doğrulama (gerçek emulator, uçtan uca):**
1. Uygulama açıldığında bildirim izni sistem dialogu otomatik çıktı, "Allow" ile onaylandı.
2. Backend log: `POST /notifications/register-token → 200 OK` — gerçek FCM cihaz token'ı kaydedildi.
3. TUPRS için `GET /decisions/TUPRS` → `BUY` (güçlü sinyal) → bildirim mantığı tetiklendi.
4. **Gerçek push teslimi başarısız oldu**: bildirim çekmecesinde bildirim görünmedi. Kök neden Python ile doğrudan `messaging.send()` çağrılarak izole edildi: `UnregisteredError: NotRegistered`. Bu, mevcut AVD'nin (`Pixel_7_API_36`, `google_apis` — **Play Store'suz**) FCM token'ı üretebildiği ama Google'ın FCM sunucusuna gerçek anlamda kayıt olamadığı bilinen bir emulator kısıtlaması — kodda hata yok. Gerçek cihazda veya Play Store etiketli bir emulator image'ında çalışması beklenir.
5. Kullanıcıya soruldu: yeni bir Play Store'lu AVD kurup tekrar test etmek yerine, kod tarafının (token kaydı, otomatik tetikleme, sessiz hata yönetimi) tam doğrulanmış olmasını yeterli kabul edip devam etmesi seçildi.

**Karşılaşılan hata / çözüm:**
- `firebase_admin` 7.5.0'da `messaging.Message(token=...)` deprecated — `fid=...` parametresine geçildi (SDK deprecation uyarısı doğru okundu ve düzeltildi, davranış aynı).
- Gerçek push teslimi emulator kısıtlaması nedeniyle doğrulanamadı (yukarıda ayrıntılı).

**Tarih / Not:**
17-18.08.2026 — FCM bildirim altyapısı (token kaydı, otomatik tetikleme, tekrar-bildirmeme mantığı) uçtan uca test edildi; gerçek push teslimi emulator kısıtlaması nedeniyle doğrulanamadı ama kod tarafı tam doğru, commit `81a9409`.

---

## 37. EventIntelligenceEngine — OpenAI GPT-5.6 Luna Entegrasyonu (18.08.2026)

**Kullanıcı kararı:** Sağlayıcı OpenAI. Maliyet kontrolü için TÜM normal haber analizleri önce ucuz/hızlı katman olan Luna (`gpt-5.6-luna`) ile işlenecek. İleride düşük confidence veya çok yüksek importance durumunda daha güçlü Terra (`gpt-5.6-terra`) ile ikinci bir analiz/fallback yapılabilecek bir mimari kurulacak — ama bu aşamada yalnızca Luna entegrasyonu çağrılacak, fallback bilinçli olarak ertelenecek. Model adı hiçbir yerde hard-code edilmeyecek, API anahtarı asla kaynak koduna yazılmayacak.

**Oluşturulan/değişen dosyalar (backend):**
```text
app/core/config.py                              → OPENAI_API_KEY, EVENT_INTELLIGENCE_PRIMARY_MODEL
                                                     (varsayılan gpt-5.6-luna), EVENT_INTELLIGENCE_FALLBACK_MODEL
                                                     (varsayılan gpt-5.6-terra) — hepsi .env'den okunuyor
app/models/news_analysis.py                     → NewsAnalysis (immutable — ai_decisions/technical_analyses ile aynı ilke)
app/repositories/news_analysis_repository.py    → add/get_by_news_id/list_for_asset (update/delete yok)
app/engines/event_intelligence/engine.py         → EventIntelligenceEngine — Luna ile analiz eder,
                                                     _should_escalate() Terra eşiklerini hesaplar (henüz çağrılmıyor)
app/api/news_analysis.py                         → POST /news/{symbol}/analyze
backend/.env.example                             → commit edilebilir şablon (gerçek anahtar içermez)
requirements.txt                                 → openai==3.2.0 + transitive bağımlılıklar
```

**Yapılandırılmış çıktı:** OpenAI'nin structured outputs özelliği (`response_format={"type": "json_schema", ..., "strict": True}`) modelin şema dışına çıkmasını API seviyesinde engelliyor; dönen JSON ayrıca Pydantic `NewsAnalysis` modeliyle ikinci kez doğrulanıyor — hiçbir zaman serbest metin olarak saklanmıyor. Aynı haber tekrar tekrar analiz edilip gereksiz LLM maliyeti oluşturmasın diye `get_by_news_id` ile daha önce analiz edilenler atlanıyor.

**Güvenlik:** `OPENAI_API_KEY` yalnızca `backend/.env` içinde duruyor; `git ls-files backend/.env` boş döndü (hiç izlenmiyor), `.gitignore` içinde zaten vardı. Kaynak kodun hiçbir yerinde anahtar hard-code edilmedi.

9 yeni test eklendi (`test_event_intelligence_engine.py`, sahte OpenAI istemcisi ile — gerçek API'ye hiç gitmeden model adının hard-code edilmediğini, structured JSON şemasının gönderildiğini, tekrar-analiz atlamasını ve `_should_escalate` eşiklerini doğruluyor), toplam 57 backend testi.

**Doğrulama (gerçek OpenAI çağrısı):** Kullanıcının kendi API anahtarıyla tek bir haber üzerinde gerçek `analyze_item()` çağrısı yapıldı. İlk denemede hesapta kota/bakiye olmadığı için `openai.RateLimitError: insufficient_quota` alındı (kimlik doğrulama sorunsuzdu — entegrasyon kodunun doğru çalıştığını, sorunun yalnızca billing tarafında olduğunu doğruladı). Kullanıcı hesabına bakiye ekledikten sonra aynı test tekrarlandı ve **gerçek bir Luna yanıtı başarıyla alındı**:
```text
model: gpt-5.6-luna
sentiment_score: 82.0, confidence: 0.97, importance: 0.86, event_type: earnings
reasoning: "Beklentilerin belirgin şekilde üzerinde net kâr ve yüzde 20 satış
büyümesi, şirketin finansal performansına yönelik olumlu algı yaratır..."
```
Bu örnekte `importance` (0.86), `HIGH_IMPORTANCE_THRESHOLD`'u (0.8) geçiyor — yani `_should_escalate()` burada `True` dönerdi; Terra fallback mimarisi tam tasarlandığı gibi tetiklenecek bir senaryoydu (henüz gerçek ikinci çağrı yapılmıyor, beklendiği gibi).

**Karşılaşılan hata / çözüm:**
İlk denemede OpenAI hesabında kota/bakiye yoktu (`insufficient_quota`) — kod tarafında hata değildi, kullanıcı hesabına bakiye ekleyince ikinci denemede sorunsuz çalıştı.

**Kapsam dışı bırakılan (bilinçli erteleme):**
Terra fallback'in gerçek ikinci LLM çağrısı henüz yapılmıyor — yalnızca karar mantığı (`_should_escalate`) hazır. `DecisionEngine`'in `news_score` alanını bu motorun çıktısıyla beslemek [Bölüm 38](#38-news_score-decisionengineye-bağlandı-18082026)'de yapıldı.

**Tarih / Not:**
18.08.2026 — EventIntelligenceEngine (OpenAI GPT-5.6 Luna) eklendi, 57/57 test geçti, gerçek API anahtarıyla uçtan uca doğrulandı (gerçek Luna yanıtı alındı), commit `d6d7b96`.

---

## 38. news_score DecisionEngine'e Bağlandı (18.08.2026)

AŞAMA 37'de bilinçli olarak ertelenen parça: `DecisionEngine`'in `news_score` alanı artık her zaman `None` değil — `EventIntelligenceEngine`'in ürettiği `NewsAnalysis` kayıtlarından besleniyor.

**Maliyet kararı (önemli):** `decide_for_asset()` — Dashboard her açıldığında `GET /decisions/{symbol}` üzerinden çağrılıyor — bu sırada **yeni bir OpenAI çağrısı YAPMIYOR**. Yalnızca daha önce ayrıca tetiklenmiş (`POST /news/{symbol}/analyze`) ve Firestore'a zaten kaydedilmiş `NewsAnalysis` kayıtlarını okuyor. Bu, `macro_score`'un zaten kullandığı "en son kaydedilmiş sonucu oku, otomatik yeniden hesaplama" deseniyle birebir aynı — karar hesaplaması hiçbir zaman LLM'e bağımlı/yavaş hale gelmiyor, maliyet yalnızca haber analizi ayrıca istendiğinde oluşuyor.

**Değişen dosyalar (backend):**
```text
app/engines/decision/engine.py     → _aggregate_news_score() eklendi: son 10 analizin (NEWS_SCORE_LIMIT)
                                       confidence-ağırlıklı ortalaması. Hiç analiz yoksa None (Missing
                                       Data Davranışı korunuyor — 0 gibi yanlış bir "nötr" varsayımı yok).
                                       decide_for_asset() artık news_repo enjekte edilebiliyor.
app/engines/explanation/engine.py  → aynı aggregasyon kullanılıyor; yeni "news_reasons" alanı en önemli
                                       (importance*confidence) haberleri Türkçe gerekçeleriyle listeliyor;
                                       "missing" mesajı yalnızca gerçekten hiç analiz yokken gösteriliyor.
app/engines/backtest/engine.py     → bayat "EventIntelligenceEngine henüz yok" yorumu güncellendi.
```
8 yeni test (`test_decision_engine.py`'de 5, yeni `test_explanation_engine.py`'de 3 — hepsi fake repo'larla, gerçek Firestore/OpenAI'ye gitmeden), toplam 65 backend testi.

**Doğrulama (gerçek THYAO verisiyle, uçtan uca):**
1. `GET /news/THYAO` → 10 gerçek haber çekildi.
2. `POST /news/THYAO/analyze?limit=5` → 5 haber gerçek Luna ile analiz edildi (ör. earnings +58 puan, corporate_action +45 puan, other -18 puan).
3. `GET /decisions/THYAO` → `news_score: 17.9` (5 analizin confidence-ağırlıklı ortalaması), `news_analysis_ids` 5 kayıtla dolu, `final_score: -12.71` → `HOLD`, güven %82.
4. `GET /decisions/THYAO/explanation` → `missing: []`, `news_reasons` en önemli 3 haberi doğru sırada (importance×confidence) Türkçe gerekçeleriyle listeledi.

**Karşılaşılan hata / çözüm:**
Yok — ilk denemede sorunsuz çalıştı.

**Tarih / Not:**
18.08.2026 — news_score DecisionEngine ve ExplanationEngine'e bağlandı, 65/65 test geçti, THYAO ile gerçek uçtan uca doğrulandı, commit `e9662f8`.

---

## 39. API Kullanımı / Maliyet Takip Ekranı (18.08.2026)

Kullanıcı isteği: OpenAI API'sinin ne kadar "yediğini" gösteren bir mobil ekran. Netleştirme: bütçe toplamda tek seferlik **$5**; gerçek OpenAI billing/usage API'sinden anlık çekmiyoruz (kullanıcı kararı: "direkt api üzerinden çekmemize gerek yok") — bunun yerine her gerçek çağrının kendi `response.usage`'ı (prompt/completion token sayısı) OpenAI'nin yayınladığı GPT-5.6 fiyat tarifesiyle çarpılıp maliyet tahmin ediliyor.

**Oluşturulan/değişen dosyalar (backend):**
```text
app/core/config.py                              → EVENT_INTELLIGENCE_BUDGET_USD (varsayılan 5.0, .env'den değiştirilebilir)
app/models/token_usage.py                       → TokenUsageLog (immutable, ai_decisions/news_analyses ile aynı ilke)
app/repositories/token_usage_repository.py       → add/list_all
app/engines/event_intelligence/usage.py          → MODEL_PRICING_PER_1M (Luna $0.20/$1.20, Terra $2.50/$15, Sol
                                                     $5/$20 — 1M token başına), compute_cost_usd(), summarize()
app/engines/event_intelligence/engine.py         → analyze_item() artık her çağrıda _log_usage() ile gerçek
                                                     token sayısını ve tahmini maliyeti kaydediyor
app/api/usage.py                                 → GET /usage: budget_usd, spent_total_usd, remaining_usd,
                                                     spent_today_usd, calls/tokens (bugün+toplam), son 7 gün dökümü
```
8 yeni test (pricing + summarize + engine'in artık usage_repo'ya log yazdığının doğrulanması), toplam 71 backend testi.

**Oluşturulan dosyalar (Flutter):**
```text
lib/models/usage_summary.dart          → UsageSummary + DailyUsage
lib/services/api/usage_api.dart        → fetchUsage()
lib/features/usage/usage_screen.dart   → Kalan Bakiye (büyük rakam + ilerleme çubuğu, %70/%90 eşiklerinde
                                           yeşil/turuncu/kırmızı), Bugün Harcanan, Toplam, Son 7 Gün (basit
                                           bar liste — yeni bir chart paketi eklenmedi)
lib/features/settings/settings_screen.dart → "API Kullanımı" satırı eklendi (Gösterge Rehberi ile Uygulama
                                               Sürümü arasına)
```
1 yeni Flutter model testi (`usage_summary_test.dart`).

**Doğrulama (emulator, gerçek THYAO verisiyle uçtan uca):** Ayarlar → API Kullanımı açıldı: "Kalan Bakiye: $4.9997", "$0.0003 / $5.0000 harcandı (%0.0)", "Bugün Harcanan: $0.0003, 1 çağrı · 714 token", "Son 7 Gün" bar grafiğinde 2026-08-18 için $0.0003 doğru göründü.

**Karşılaşılan hata / çözüm:**
Doğrulama sırasında emulator'de "News: Veri yok" görünmeye devam etti ve `/usage` `404 Not Found` döndü — kök neden, arka planda AŞAMA 37'den beri hâlâ çalışan **eski bir uvicorn süreciydi** (yeni kodu hiç yüklememişti, `--reload` ile başlatılmamış). Süreç sonlandırılıp güncel kodla yeniden başlatılınca hem `/usage` hem `news_score` doğru döndü. Kod tarafında hata yoktu — geliştirme ortamı hijyeni sorunuydu.

**Tarih / Not:**
18.08.2026 — API Kullanımı ekranı eklendi, 71/71 backend testi ve yeni Flutter model testi geçti, emulator'de gerçek verilerle uçtan uca doğrulandı, commit `5727888`.

---

## 40. Ücretsiz BIST Fiyat Verisi (yfinance) + Fiyat Sekmesi + AI Destekli Haber Duygu Analizi (18.08.2026)

**Kullanıcı kararı:** Piyasa verisi için tamamen ücretsiz bir çözüm — ücretli API yok. İlk adım: `yfinance` zaten kurulu muydu diye kontrol edilip gerçek BIST sembolleriyle (`THYAO.IS`, `ASELS.IS`, `TUPRS.IS`, `GARAN.IS`, `AKBNK.IS`) doğrulama yapıldı. `yfinance` zaten kuruluydu (v1.5.2, `requirements.txt`'de zaten pinli) — yeni paket kurulmadı.

**Doğrulama (standalone script, gerçek veri):** fast_info ile güncel fiyat/önceki kapanış/günlük değişim, günlük OHLCV+timestamp, THYAO.IS için 5 dakikalık veri (423 satır/5 gün), haftalık/aylık/uzun dönem geçmiş fiyatlar, ve gerçek kapanışlardan 1g/1h/1a/3a/6a/1y yüzde değişim hesapları — hepsi çalıştı. Gün-içi veride gözlemlenen gerçek gecikme **~15 dakika** (Yahoo'nun bilinen politikasıyla uyumlu, gizlenmiyor).

**Backend entegrasyonu:**
```text
app/services/market_data/bist_provider.py → get_quote() eklendi (güncel fiyat, önceki kapanış,
                                              değişim/%, gerçek timestamp); get_history() artık
                                              interval parametresi alıyor (geriye uyumlu, varsayılan "1d")
app/services/market_data/base.py          → ABC'ye get_quote eklendi, get_history imzası güncellendi
app/models/market_data.py                 → Quote modeli eklendi
app/services/market_data/changes.py       → compute_period_changes(): 1g/1h/1a/3a/6a/1y yüzde değişim,
                                              yetersiz geçmiş varsa None (sahte değer YOK)
app/api/market_data.py                    → GET /market-data/{symbol}/quote|history|changes
tests/conftest.py                         → FakeMarketDataProvider get_quote/interval ile güncellendi
```

**Flutter — yeni "Fiyat" sekmesi (Varlık Detayı'nda ilk sekme):** güncel fiyat + değişim, gerçek timestamp ("Yahoo Finance, hafif gecikmeli olabilir" notuyla), açılış/yüksek/düşük/hacim, 6 periyotlu (1G/1H/1A/3A/6A/1Y) gerçek OHLCV grafik (`CustomPainter` ile basit sparkline — yeni chart paketi eklenmedi), 1g/1h/1a/3a/6a/1y yüzde değişim kartları.

**Haberler sekmesi artık AI destekli:** Önceden yalnızca ham liste + "henüz uygulanmadı" notu vardı. Şimdi:
```text
app/api/news_analysis.py → GET /news/{symbol}/analysis eklendi (maliyetsiz — yalnızca daha önce
                            üretilmiş NewsAnalysis kayıtlarını okur, YENİ OpenAI çağrısı yapmaz)
lib/features/asset_detail/asset_detail_screen.dart → her haber kartında (varsa) Luna'nın duygu
                            skoru/olay tipi/güven/etki yüzdesi ve Türkçe gerekçesi renkli kutuda
                            gösteriliyor; "Analiz Et" butonu POST /news/{symbol}/analyze'ı tetikliyor
```
Maliyet ilkesi korundu: sekme açıldığında otomatik LLM çağrısı YAPILMAZ, yalnızca kullanıcı "Analiz Et"e bastığında (ve yalnızca henüz analiz edilmemiş haberler için) gerçek maliyet oluşur.

12 yeni backend testi (pricing/changes + provider ABC güncellemeleri, toplam 78), 5 yeni Flutter model testi.

**Doğrulama (emulator, THYAO ile uçtan uca):** Fiyat sekmesinde gerçek fiyat/grafik/yüzde değişimler doğru göründü; periyot chip'leri (1G seçilince gün-içi 5dk grafiğe geçiş) doğru çalıştı. Haberler sekmesinde "Analiz Et"e basılınca gerçek Luna yanıtları (ör. "+58 puan, Bilanço/Kâr", "-18 puan, Diğer") Türkçe gerekçeleriyle renkli kartlarda göründü.

**Karşılaşılan hata / çözüm:**
Doğrulama sırasında yine arka planda eski bir uvicorn süreci çalışıyordu (yeni `/market-data` ve `/news/{symbol}/analysis` route'larını yüklememişti) — süreç sonlandırılıp güncel kodla yeniden başlatıldı. Bu, projede tekrarlayan bir geliştirme-ortamı alışkanlığı sorunu; kod tarafında hata değil.

**Tarih / Not:**
18.08.2026 — Ücretsiz BIST fiyat verisi entegre edildi (Fiyat sekmesi) ve Haberler sekmesi AI duygu analizine bağlandı, 78/78 backend + yeni Flutter testleri geçti, emulator'de uçtan uca doğrulandı, commit `12b1a9d`.

---

## 41. Haberlerde AL/TUT/SAT Etiketi + Analiz Et Artık Ekrandaki Tüm Haberleri Kapsar (18.08.2026)

Kullanıcı, Haberler sekmesindeki "Analiz Et" butonunun tam olarak ne yaptığını sorduktan sonra, her haberin duygu skorunun Dashboard'daki AL/ZAYIF AL/TUT/ZAYIF SAT/SAT diliyle de gösterilmesini istedi.

`lib/utils/decision_style.dart`'a `classifyScore(double score)` eklendi — `DecisionEngine.DEFAULT_THRESHOLDS` (40/15/-15/-40) ile **birebir aynı eşiklerle** bir skoru karara çeviriyor; `decisionLabel`/`decisionColor` zaten var olan tek kaynak fonksiyonlarla birleştirilip her haber kartında renkli bir rozet (`AL`, `ZAYIF SAT` vb.) gösteriliyor. Ayrıca "Analiz Et" butonu artık sabit `limit=5` yerine `limit=items.length` ile çağrılıyor — ekranda kaç haber listeleniyorsa hepsi kapsanıyor (zaten analiz edilmiş olanlar backend'de otomatik atlandığı için tekrar maliyet oluşmuyor).

1 yeni test (`classifyScore` eşik sınırları, DecisionEngine testleriyle birebir aynı parametrelerle).

**Doğrulama (emulator, THYAO):** Önceden analiz edilmiş haberlerde rozetler (`ZAYIF SAT`, `AL`) doğru göründü; "Analiz Et"e basılınca listenin alt sıralarındaki (önceden analiz edilmemiş) haberler de `TUT`/`ZAYIF SAT` rozetleriyle geldi.

**Tarih / Not:**
18.08.2026 — Haberlerde AL/TUT/SAT rozeti eklendi, Analiz Et tüm listelenmiş haberleri kapsıyor, 20/20 Flutter testi geçti, emulator'de uçtan uca doğrulandı, commit `9523d21`.

---

## 42. Performans Sekmesinde İşlemlerin Detaylı Türkçe Anlatımı (18.08.2026)

Kullanıcı, Performans sekmesindeki kırmızı/yeşil işlem satırlarının ne anlama geldiğini (satıp zarar mı ettik, yoksa hisse mi düştü) netleştirmek istedi.

Her işlem kartı artık yalnızca renk/yüzde değil, tam bir Türkçe cümle: *"18.03.2026'de 250.00 TL'den alındı, 02.04.2026'de 270.00 TL'den satıldı. Fiyat %8.0 yükseldi, kâr edildi."* (kırmızıda "düştü, zarar edildi"). Liste başına, stratejinin her zaman önce alıp sonra sattığını (açığa satış yok) ve renklerin anlamını açıklayan bir not eklendi. Bu netlik, `BacktestEngine`'in gerçek davranışına dayanıyor: `simulate()` yalnızca `shares == 0` iken AL/ZAYIF AL sinyalinde pozisyon açıyor, `shares > 0` iken SAT/ZAYIF SAT sinyalinde kapatıyor — yani her satır zaten bir "önce aldık, sonra sattık" round-trip'i, backend kodu doğrulanarak teyit edildi.

**Doğrulama (emulator, THYAO):** Yeşil kartlarda "...yükseldi, kâr edildi", kırmızı kartlarda "...düştü, zarar edildi" cümleleri gerçek backtest verisiyle doğru göründü.

**Tarih / Not:**
18.08.2026 — Performans sekmesi işlem anlatımları detaylandırıldı, 20/20 Flutter testi geçti, emulator'de uçtan uca doğrulandı, commit `0503f51`.

---

## 43. Dashboard: BIST100'ün Tamamı + final_score'a Göre Sıralama (18.08.2026)

Kullanıcı geri bildirimi: "sen tüm BIST100'e bakıyor musun, çok az hisse var burada" — Dashboard o ana kadar `_testAssets` adlı sabit 6 sembollük bir test listesi (THYAO, ASELS, GARAN, AKBNK, EREGL, TUPRS) kullanıyordu; backend'in `assets` koleksiyonu da yalnızca aynı 6 kaydı içeriyordu.

Önce sıralama isteği ayrıca ele alındı: `dashboard_screen.dart`'ta `_loadAll()` artık sonuçları `decision.finalScore`'a göre azalan sırada döndürüyor (en güçlü AL üstte, en güçlü SAT altta; hata alan varlıklar sıralanamadığı için en altta kalıyor).

**Gerçek BIST100 listesi:** getmidas.com'dan (18.08.2026) 100 sembollük gerçek bileşen listesi alındı, **100 sembolün TAMAMI** gerçek bir yfinance script'iyle tek tek doğrulandı (100/100 başarılı, şirket isimleri de Yahoo Finance'in kendi verisinden) — hiçbir sembol uydurulmadı. `backend/scripts/seed_assets.py` bu 100 kaydı içerecek şekilde güncellendi ve çalıştırılıp canlı Firestore'a uygulandı (`GET /assets` artık 100 döner).

`lib/models/asset.dart`, `lib/services/api/asset_api.dart` eklendi; `dashboard_screen.dart` artık sabit liste yerine `GET /assets`'i dinamik çekiyor.

**Doğrulama (emulator, gerçek veriyle):** Dashboard 100 hissenin tamamını yükledi, final_score'a göre doğru sıralı (TUPRS/TKFEN/IEYHO en üstte AL). **Dürüst performans notu:** ilk (soğuk) yükleme ~60-80 saniye sürdü — bu sorun [Bölüm 44](#44-dashboard-performansı-technicalanalysisengine-15-dakikalık-ttl-cache)'te ele alındı.

**Tarih / Not:**
18.08.2026 — Dashboard tam BIST100'e genişletildi ve final_score'a göre sıralandı, commit `2f72545` ve `142e755`.

---

## 44. Dashboard Performansı: TechnicalAnalysisEngine'e 15 Dakikalık TTL Cache

Kullanıcı: "önce performansı çözelim." Kök neden: `TechnicalAnalysisEngine.analyze_with_id()` her çağrıldığında yfinance'e taze bir istek atıyordu — cache yoktu. 100 hisseli Dashboard'da bu, her açılışta ~60-80 saniyelik yükleme demekti.

Macro/news skorlarında zaten kullanılan "son kaydedilmiş sonucu oku, otomatik yeniden hesaplama" ilkesi technical analize de uygulandı: `TECHNICAL_CACHE_TTL_SECONDS` (900s = 15dk) içinde zaten hesaplanmış bir kayıt varsa, yfinance'e HİÇ gidilmeden o kayıt döner.

`TechnicalAnalysisRepository`'ye `get_latest_with_id()` eklendi. Firestore'un `where + order_by` composite index gerektirdiği **canlı olarak test edilip doğrulandı** (`FailedPrecondition` hatası gerçekten alındı) — yeni bir Firestore index oluşturmak yerine `news_analysis_repository` ile aynı, index gerektirmeyen desen (filtrele + Python'da sırala) kullanıldı.

4 yeni test (cache hit'te provider'a hiç gidilmediği, sahte bir provider `NotImplementedError` fırlatacak şekilde kurularak kanıtlandı; bayat cache'te yeniden hesaplama; cache yokken hesaplama; özel TTL parametresi).

**Doğrulama (emulator, gerçek BIST100 verisiyle):** Uygulama yeniden başlatılıp Dashboard tekrar açıldığında 100 hisse birkaç saniyede yüklendi (önceden 60-80 saniye). İlk soğuk yükleme hâlâ yavaş — ücretsiz/toplu-olmayan bir veri kaynağıyla (yfinance) 100 sembolü kapsamanın doğal maliyeti, ödemeli bir API olmadan aşılamıyor.

**Tarih / Not:**
18.08.2026 — Technical analiz cache'i eklendi, 78/78 backend testi geçti, emulator'de gerçek verilerle uçtan uca doğrulandı, commit `0a27d08`.

---

## 45. AL Butonu ile Hızlı Portföy Ekleme + Bildirimleri Portföy Sahipliğine Sınırlama (18.08.2026)

Kullanıcı: "AL butonu olacak ve aldığımız hisselerde al veya sat durumu olursa bildirim yollayacak."

**AL butonu:** Varlık Detayı → Fiyat sekmesine "AL — Portföye Ekle" butonu eklendi; güncel fiyat (`Quote.lastPrice`) otomatik dolduruluyor, kullanıcı yalnızca adet giriyor, mevcut `POST /portfolio/positions` kullanılarak tek dokunuşla portföye ekleniyor. Portföy ekranındaki "Pozisyon Ekle" dialog'u da sabit 6 sembol yerine `Autocomplete` ile BIST100'ün tamamında arama yapacak şekilde güncellendi.

**Bildirim kapsamı daraltıldı (kritik):** Dashboard artık BIST100'ün tamamını sorguladığından ([Bölüm 43](#43-dashboard-bist100ün-tamamı--final_scorea-göre-sıralama-18082026)), eski davranış ("her sorgulanan varlık güçlü AL/SAT ise bildir") onlarca alakasız bildirime yol açacaktı. `PortfolioRepository.get_position_for_asset()` eklendi (lotları birleştirip tek pozisyon döner); `GET /decisions/{symbol}` artık bildirimi **yalnızca** o varlık kullanıcının portföyünde varsa tetikliyor, ve bildirim metni kaç adet elde olduğunu belirtiyor (`fcm_sender.py`'ye `quantity_held` parametresi eklendi).

**Bulunup düzeltilen gerçek bir arka plan hatası:** `DecisionApi.fetchDecision` (Flutter) backend'e hiç Firebase auth token'ı göndermiyordu — bu yüzden `get_current_user_id_optional` her zaman `None` dönüyor ve bildirim mantığı **AŞAMA 32'den beri hiç çalışmıyordu**, sessizce. Token eklendi.

8 yeni/güncellenmiş backend testi.

**Doğrulama (emulator, gerçek uçtan uca):** TUPRS, AL butonuyla 10 adet portföye eklendi (Portföy ekranında `TUPRS · 10 adet, Ort. Alış: 372.00 TL` doğru göründü). Backend debug logları ile: (1) auth token'ının artık her istekte doğru `user_id`'yi çözdüğü, (2) `get_position_for_asset`'in doğru pozisyonu döndürdüğü, (3) TUPRS'in güçlü BUY (63.74) olarak sınıflandığı, (4) `notify_if_strong_decision`'ın çağrıldığı — hepsi kanıtlandı. Gerçek FCM gönderimi test edildiğinde `UnregisteredError: NotRegistered` alındı — bu, AŞAMA 32'de zaten belgelenmiş, mevcut AVD'nin (Play Store'suz) bilinen kısıtlaması; kod tarafı uçtan uca doğru, yalnızca gerçek push teslimi bu emulator'de doğrulanamıyor.

**Karşılaşılan hata / çözüm:**
- Bildirim beklenenden gelmiyordu → sırayla auth token eksikliği (asıl kök neden) ve ardından bilinen emulator FCM kısıtlaması tespit edildi; ikisi de yukarıda detaylandırıldı.

**Tarih / Not:**
18.08.2026 — AL butonu ve portföy-kapsamlı bildirimler eklendi, 80 backend + 21 Flutter testi geçti, emulator'de uçtan uca doğrulandı (gerçek push hariç, bilinen kısıtlama), commit `3a8bf2f`.

---

## 46. Backend'i Cloud Run'a Deploy Et — APK Artık Gerçek Bir Cihazda Çalışıyor (18.08.2026)

Kullanıcı: "uygulamanın APK'sını çıkart, eksiksiz çalışır değil mi?" Dürüst cevap: hayır — APK o ana kadar yalnızca `10.0.2.2` (emulator'ün host makineye erişim takma adı) kullanıyordu; gerçek bir telefona kurulsaydı hiçbir ekran veri getirmezdi, çünkü backend yalnızca geliştirme bilgisayarında `127.0.0.1`'de çalışıyordu. Kullanıcı "bir sunucuya kuralım, hep çalışsın" dedi.

**Deploy (Google Cloud Run seçildi — zaten aynı GCP projesinde Firebase/Firestore kullanıldığı için doğal seçim, billing zaten aktifti):**
```text
backend/Dockerfile, .dockerignore   → python:3.13-slim + uvicorn
gcloud run deploy ai-investment-backend --source . --region europe-west1
```
Servis URL'i: `https://ai-investment-backend-244094132223.europe-west1.run.app`

**Sırlar:** `OPENAI_API_KEY` koda/commit'e hiç yazılmadı — Secret Manager'a (`openai-api-key`) eklendi, yalnızca Cloud Run'ın servis hesabına (`...-compute@developer.gserviceaccount.com`) erişim izni verildi (`roles/secretmanager.secretAccessor`). Firestore erişimi Cloud Run'ın attached servis hesabı üzerinden otomatik (`credentials.ApplicationDefault()`) — ek bir anahtar dosyası taşımaya gerek kalmadı.

**Güvenlik düzeltmesi (deploy öncesi tespit edildi):** Backend artık herkese açık bir adreste olacağından, gerçek OpenAI maliyeti oluşturan `POST /news/{symbol}/analyze`'ın hiç auth kontrolü olmadığı fark edildi — kimliği doğrulanmamış herkes bütçeyi tüketebilirdi. `get_current_user_id` zorunlu hale getirildi (canlıda `curl` ile 401 döndüğü doğrulandı).

**Flutter tarafı:** 10 ayrı `*_api.dart` dosyasındaki tekrarlı `'http://10.0.2.2:8000'` tanımı `lib/services/api/api_config.dart`'taki tek bir `apiBaseUrl` sabitine bağlandı (artık gerçek Cloud Run URL'i). `DecisionApi.fetchDecision`'a da (bu sırada, AŞAMA 45'teki bildirim hatasıyla ilgisiz ama aynı dosyada) auth token eklenmesi zaten yapılmıştı.

**Gerçek, canlı bir prod sorunu tespit edilip düzeltildi:** Dashboard'un 100 sembolü **tamamen eşzamanlı** (`Future.wait` tek seferde) çekmesi, localhost'a karşı sorun değildi ama gerçek Cloud Run adresine karşı `SocketException: connection abort` hatalarına yol açtı (100 eşzamanlı yeni TLS bağlantısı açılmaya çalışılması). `dashboard_screen.dart`'ta istekler artık 10'luk gruplar hâlinde art arda gönderiliyor (`_batchSize = 10`).

Ayrıca ilgisiz bir flaky test bulunup düzeltildi: `test_summarize_splits_today_vs_total`, `datetime.now()`'a göre veri üretip sabit bir `today` parametresiyle karşılaştırıyordu — gerçek saat gece yarısını (UTC) geçince test kırıldı; artık sabit bir referans zaman kullanıyor.

**Doğrulama (gerçek, uçtan uca):** `curl` ile `/health`, `/assets` (100 döndü), `/decisions/THYAO` (gerçek yfinance+Firestore), ve güvenlik düzeltmesi (`401`) canlıda doğrulandı. Yeni APK derlenip emulator'e kuruldu (gerçek internet üzerinden, `10.0.2.2` değil) — Dashboard (100 hisse, sıralı, hatasız), Portföy (auth + gerçek pozisyon), Makro Analiz (gerçek göstergeler) hepsi gerçek bulut backend'inden doğru çalıştı.

**Karşılaşılan hatalar / çözümler:**
- Secret Manager erişimi ilk deploy'da `Permission denied` verdi — Cloud Run'ın servis hesabına `secretmanager.secretAccessor` rolü verilmeyi unutulmuştu, eklenip düzeltildi.
- 100 sembollük tam-eşzamanlı istek, buluta karşı bağlantı kopmalarına yol açtı — gruplu istek deseniyle çözüldü (yukarıda detaylandırıldı).
- Emulator, uzun oturum sırasında kendiliğinden kapanmıştı — yeniden başlatıldı.

**Tarih / Not:**
18.08.2026 — Backend Cloud Run'a deploy edildi, APK gerçek adrese bağlandı ve gerçek internetten uçtan uca doğrulandı, 80 backend testi geçti, commit `97984c3`.

---

## 47. Portföy Geçmişi — Pozisyon Kapatma, Gerçekleşen Kâr/Zarar Takibi (19.08.2026)

Kullanıcı: "portföyde geçmiş yok, hisse geçmişi de olsun istiyorum, ne kadar kâr zarar yaptığımızda olsun, geçmişten bugüne toplam kâr zarar." O ana kadar bir pozisyonu silmek, o pozisyona dair TÜM geçmişi sessizce kaybettiriyordu — kullanıcı hiçbir zaman "TUPRS'ten şu kadar kâr ettim" diyemiyordu.

**Çözüm — silme yerine "kapatma":** Pozisyon artık doğrudan silinmiyor; kullanıcı bir satış fiyatı girip pozisyonu "kapatıyor", gerçekleşen kâr/zarar hesaplanıp ayrı, değiştirilemez bir `PortfolioTransaction` kaydına yazılıyor, ANCAK SONRA açık pozisyon siliniyor. Bu, projenin AI karar kayıtlarında (`ai_decisions`, `news_analyses`) zaten uygulanan "geçmiş asla değiştirilmez/silinmez" ilkesinin kullanıcı işlemlerine de (analoji yoluyla) genişletilmesi.

**Backend:** `models/portfolio_transaction.py` (immutable), `repositories/portfolio_transaction_repository.py`, `services/portfolio/pnl_calculator.py`'ye `calculate_realized_pnl()` eklendi, `POST /portfolio/positions/{asset}/close` (satış fiyatı alır, K/Z hesaplar, transaction'a yazar, pozisyonu siler), `GET /portfolio/history` (tüm işlemler + toplam gerçekleşen K/Z).

**Flutter:** Portföy ekranındaki çöp kutusu ikonu "Sattım" (satış fiyatı dialogu) ile değiştirildi; yeni `PortfolioHistoryScreen` — gerçekleşen K/Z + açık pozisyon K/Z + toplam özet, her işlem için Performans sekmesindeki `_TradeCard` ile tutarlı Türkçe anlatı cümlesi ("18.08.2026'de 372 TL'den 10 adet alındı, 19.08.2026'de 390 TL'den satıldı. Fiyat %4.8 yükseldi, kâr edildi.").

**Doğrulama:** Backend testleri + Cloud Run'a deploy + emulator'de uçtan uca (pozisyon kapatma, Geçmiş ekranı, toplam K/Z hesabı) doğrulandı.

**Tarih / Not:**
19.08.2026 — Portföy Geçmişi eklendi, commit `a71fa94`.

---

## 48. TECHNICAL_ANALYSIS_RESEARCH1.md — Teknik Analiz Altyapısını Araştırma Raporuna Göre Genişletme (19.08.2026)

Kullanıcı kendi araştırdığı bir teknik analiz dokümanı (`TECHNICAL_ANALYSIS_RESEARCH1.md`, proje kökünde, 1625 satır) oluşturup "incele, yaptığım araştırmalara göre projemizdeki AL/SAT/TUT durumuna eklemeler yapıp doğruluğu artıralım" dedi. Dokümanın kendi 47. bölümü açıkça şunu istiyordu: önce mevcut kodu incele, bir analiz raporu çıkar (mevcut özellikler / eksikler / hatalı hesaplamalar / look-ahead-bias riskleri / gereken yeni modüller / önerilen sıra), kör kör özellik ekleme. Bu yöntem birebir izlendi.

**Analiz raporu (kod değişikliğinden önce sunuldu):** Mevcut motor yalnızca RSI/MACD/EMA-trend(kesişim)/Bollinger/Momentum/ROC kullanıyordu, hepsi eşit ağırlıklı. Eksikler: market structure (HH/HL/LH/LL), destek/direnç bölgeleri, breakout/false-breakout/retest, gerçek göreli hacim, VWAP, çoklu zaman dilimi, göreli güç, volatilite/trend rejimi, veri kalitesi hard-veto'ları, sinyal sınıfı taksonomisi, walk-forward backtest. En kritik look-ahead-bias riski: `BistProvider.get_history` piyasa açıkken bugünün tamamlanmamış barını da döndürüyordu. Dokümanın önerdiği 14 aşamalı geliştirme sırası, backtest ile doğrulanmadan hiçbir eşiğin "evrensel doğru" sayılmaması uyarısıyla birlikte kabul edildi.

Kullanıcı: "sırayla hepsini kademe kademe ekleyelim" — 14 aşamanın tamamı (+ canlı skora entegrasyon + UI bağlama + bir prod hatası düzeltmesi) tamamlandı:

- **1-8 (altyapı, henüz skora bağlanmadı):** `data_quality.py` (skorlama öncesi hard-veto: eksik sütun/yetersiz geçmiş/eksik OHLCV/bayat veri — hem canlı motora hem BacktestEngine'e bağlandı), `test_indicator_causality.py` (tüm göstergelerin gelecekteki veriyi "görmediğini" doğrulayan regresyon testi, yeni özelliklerden ÖNCE kuruldu), `market_structure.py` (onay-gecikmeli swing high/low + HH/HL/LH/LL), `support_resistance.py` (ATR-normalize destek/direnç bölgeleri), `breakout.py` (breakout kalitesi + false breakout + retest onayı), `relative_volume.py` (medyan tabanlı), `indicators.ema_slope` (EMA'nın anlık farkı değil zaman içindeki eğimi), `regime.py` (ATR percentile + Kaufman Efficiency Ratio).
- **9 (canlı skora entegrasyon — riskli adım, backtest ile doğrulandı):** RSI/MACD/Bollinger ağırlığı 0.1667'den 0.10'a düşürüldü (doğrulama amaçlı kullanım), `ema_slope` yeni bir bileşen olarak eklendi, `final_score` artık ağırlık toplamına bölünerek normalize ediliyor (Firestore'daki eski 6 anahtarlı config'in yeni "ema_slope" anahtarını bozmadan birleşebilmesi için — regresyon testiyle kilitlendi). 10 BIST sembolünde (2 yıl) eski/yeni ağırlıklandırma karşılaştırıldı: ortalama getiri %39.68 → %43.10, ortalama max drawdown -%26.13 → -%25.62, kazanma oranı %44.20 → %47.34, daha az işlem sayısı.
- **10-13:** `relative_strength.py` (BIST100/XU100'e göre — RiskEngine'de zaten kullanılan aynı benchmark mekanizması), `multi_timeframe.py` (farklı zaman dilimlerinde EMA eğimi yönü karşılaştırması), `signal_classifier.py` (7 sınıflı sinyal taksonomisi: STRONG_BULLISH_INITIATION..NO_SIGNAL — TechnicalScore/DecisionEngine kararını değiştirmez, ayrı bir zenginleştirme katmanı), `metrics.py` (Sharpe/Sortino/Profit Factor/Expectancy), `weight_walk_forward.py` (ağırlık grid'i için walk-forward optimizasyon: train'de seç, testte/out-of-sample ölç).
- **14a-b:** `gap_analysis.py`, `candlestick_patterns.py` (Doji/Hammer/Shooting Star/Engulfing — bilinçli olarak yalnızca TESPİT eder, bağlamdan bağımsız yorumlamaz), `chart_patterns.py` (Double Bottom/Top, yalnızca neckline kırılımıyla onaylanır) — hepsi günlük barla çalışır, altyapı gerektirmez. Ayrıca `IntradayBar` modeli/repository'si, `scripts/fetch_intraday_bars.py` (mevcut `fetch_market_data.py` ile aynı elle-tetiklenen script deseni — otomatik zamanlama BİLİNÇLİ OLARAK kurulmadı), `vwap.py`, `session_timing.py` (BIST seansını OPENING/MIDDAY/CLOSING/CLOSED olarak sınıflandırır).
- **15 (UI'ya bağlama):** market_structure/S-R/breakout/relative_volume/regime/gap/candlestick/signal_classifier artık her `analyze_with_id()` çağrısında (AYNI veriden, ek ağ isteği olmadan) hesaplanıp `TechnicalAnalysis`'e ekleniyor. Teknik sekmesine yeni bir "Sinyal Özeti" kartı eklendi (sinyal rozeti, piyasa yapısı, trend/volatilite rejimi, göreli hacim, en yakın destek/direnç, breakout durumu). Test sırasında bu değişiklikten ÖNCE de var olan bir görüntüleme hatası bulunup düzeltildi: "Güven" yüzdesi 0-1 ölçekli değeri 100'le çarpmadan gösteriyordu (%85 yerine %1).
- **16 (prod hatası düzeltmesi):** Dashboard testinde bazı semboller (AKSEN, HEKTS, ISMEN, PATEK) "possibly delisted" hatası veriyordu. Silmeden önce izole sorguyla doğrulandı: hepsi geçerli, aktif BIST hisseleri — hata Dashboard'un 10'arlı eşzamanlı isteklerinin Yahoo Finance'i rate-limit'e sokmasıydı, gerçek bir delisting değildi. `BistProvider`'a otomatik yeniden deneme eklendi (`_fetch_with_retry`, 3 deneme, 2sn ara) — semboller SİLİNMEDİ.

**Önemli bir hata yakalanıp düzeltildi:** 10-13 aşamasında yeni bir "walk-forward" dosyası yazılırken, fark edilmeden AŞAMA 29'dan beri var olan ve `/backtest` API'sine bağlı çalışan `WalkForwardOptimizer` sınıfının (eşik optimizasyonu, `walk_forward.py`) üzerine yazılmıştı. Commit'lemeden önce fark edilip orijinal dosya `git checkout --` ile geri getirildi, yeni ağırlık-grid'i kodu ayrı bir dosyaya (`weight_walk_forward.py`) taşındı — üretimde hiçbir kayıp olmadı.

**Kapsam dışı bırakılanlar (bilinçli):** `relative_strength`/`multi_timeframe` skora/UI'ya bağlanmadı (ikisi de ek bir yfinance isteği gerektirir — Dashboard'un 100 sembolü tek seferde yüklediği göz önüne alınırsa AŞAMA 44'te çözülen N+1 istek sorununu geri getirirdi). `vwap.py`/`session_timing.py` hiçbir yerde kullanılmıyor (intraday veri biriktirme altyapısı var ama hiçbir otomatik zamanlama yok, gerçekte veri birikmiyor). MFE/MAE backtest metrikleri yok. Gelişmiş mum/grafik formasyonları (Morning/Evening Star, Head & Shoulders) yok. `signal_classifier` gap/mum formasyonu bilgisini henüz girdi olarak almıyor.

**Doğrulama:** Her aşamada backend pytest (102 → 258 test, kademeli), `flutter analyze`/`flutter test`, gerçek Cloud Run deploy + emulator'de görsel doğrulama (THYAO/TUPRS üzerinde Teknik sekmesi).

**Tarih / Not:**
19.08.2026 — TECHNICAL_ANALYSIS_RESEARCH1.md'nin 14 aşamalı yol haritası + skor entegrasyonu + UI bağlama + prod hatası düzeltmesi tamamlandı, 258/258 backend test yeşil, commit'ler `c6da6e7`, `a0e4d23`, `1fbdc43`, `0ed9553`, `32350f0`, `a616750`, `26bae2a`.

---

## 49. Dashboard'a Hisse Arama Butonu (19.08.2026)

Kullanıcı: "piyasalar kısmına arama butonu ekle ve oradan istediğimiz hisseyi arayabilelim."

**Çözüm:** Piyasa Analizi ekranının AppBar'ına bir arama ikonu eklendi. Tıklanınca başlık bir `TextField`'a dönüşüyor; yazıldıkça, zaten yüklenmiş olan BIST100 listesi (ek bir API isteği YAPILMADAN, client-side) sembol adına göre filtreleniyor. Sonuç yoksa bilgilendirici bir mesaj gösteriliyor, X butonuyla arama kapatılıp tam liste (final_score'a göre sıralı) geri geliyor.

**Doğrulama:** Emulator'de uçtan uca test edildi — "PG" araması DAPGM ve PGSUS'u doğru filtreledi, "PGZZ" için doğru boş-sonuç mesajı gösterildi, X ile arama temizlenip orijinal sıralı liste geri geldi. (Test sırasında emulator'ün "stylus" eğitim penceresi birkaç kez araya girdi — `adb shell input keyevent KEYCODE_BACK` ile atlatıldı, uygulamanın kendi davranışıyla ilgisi yok.)

**Tarih / Not:**
19.08.2026 — Dashboard arama özelliği eklendi, `flutter analyze` temiz, 26/26 flutter test yeşil, commit `19daa27`.

---

## 50. relative_strength'i N+1 İstek Sorunu Olmadan Sinyal Özeti'ne Bağlama (AŞAMA 48/17) (19.08.2026)

AŞAMA 48'de (madde 48) `relative_strength.py` yazılmıştı ama "her sembol için ek bir XU100 isteği, Dashboard'un 100 sembollük yüklemesinde AŞAMA 44'te çözülen N+1 sorununu geri getirir" gerekçesiyle bilinçli olarak skora/UI'ya bağlanmamıştı. Kullanıcı "senin fikrin ne" diye sorduğunda bu maddeyi önerdim — gerekçe: engel aslında çözülebilir, çünkü XU100'ün kapanış serisi TÜM semboller için AYNIDIR.

**Çözüm — paylaşılan, önbellekli benchmark servisi:** `benchmark_cache_repository.py` (tek Firestore belgesi, `system_cache/benchmark_xu100_close_series`) + `benchmark_service.py` (`get_benchmark_close_series()` — technical_analyses ile aynı 15 dakikalık TTL mantığı). Dashboard'un 100 sembolünün İLKİNDE XU100 bir kez çekilir, geri kalan 99'u önbellekten okur — hiçbir ek N+1 isteği oluşmaz. Seri, `datetime.date` anahtarlı bir pandas Series olarak döner (Timestamp değil) — yfinance'in tz-aware DatetimeIndex'i ile önbellekten geri okunan seri arasındaki uyumsuzluğu (join'in sessizce boş dönmesi riskini) baştan önlemek için.

`TechnicalAnalysisEngine._compute_enrichment()` artık `relative_strength_class`'ı hesaplayıp `TechnicalAnalysis`'e ekliyor; benchmark fetch'i başarısız olursa (`ValueError`) sessizce "UNKNOWN" kalır — bir sembolün XU100 verisi alınamaması, o sembolün asıl analizini düşürmez (Missing Data Davranışı). Flutter tarafında Sinyal Özeti kartına "Göreli Güç" bilgisi eklendi.

**Doğrulama (gerçek, uçtan uca):** Cloud Run'a deploy edildi, `curl` ile THYAO için `relative_strength_class: "UNDERPERFORMING"` doğrulandı; ikinci bir sembolün (TUPRS) isteği yalnızca 0.78 saniyede döndü — benchmark'ın önbellekten okunduğunun, yeniden çekilmediğinin kanıtı. Emulator'de TUPRS'in Teknik sekmesinde "Göreli Güç: Endeksten İyi (BIST100)" doğru göründü.

**Tarih / Not:**
19.08.2026 — relative_strength Sinyal Özeti'ne bağlandı, 263/263 backend + 27/27 flutter test yeşil, commit `ccff2d2`.

---

## 51. multi_timeframe'i Ek İstek Olmadan Sinyal Özeti'ne Bağlama (AŞAMA 48/18) (19.08.2026)

Kullanıcı "sıradaki adıma geç" dedi — kalan madde `multi_timeframe.py`'ydi. Bu, relative_strength'ten (madde 50) FARKLI bir engeldi: haftalık zaman dilimi sembole özeldir, XU100 gibi semboller arasında paylaşılamaz. Ama daha basit bir çözüm vardı: haftalık kapanış, zaten çekilmiş günlük Close serisinden TÜRETİLEBİLİYOR — hiç yeni yfinance isteği gerekmiyor.

**Çözüm:** `multi_timeframe.resample_to_weekly_close()` — pandas `resample("W")` ile günlük Close serisini haftalık kapanışlara indirger (saf hesaplama). `TechnicalAnalysisEngine` artık günlük ve haftalık EMA eğimi yönünü karşılaştırıp `mtf_aligned`/`mtf_consensus`'u `TechnicalAnalysis`'e ekliyor.

**Fark edilen, düzeltilen dormant bug:** `signal_classifier.classify_signal()`'ın `STRONG_BULLISH_INITIATION` dalı `mtf_aligned`'a bakıyordu ama bu alan şimdiye kadar hep sabit `False` varsayılıyordu (hiçbir yerde gerçek veriyle hesaplanmıyordu) — yani bu en üst sinyal sınıfı, tüm diğer koşullar (skor≥40, UPTREND yapı, teyitli breakout, yüksek hacim) sağlansa bile HİÇBİR sembol için hiç tetiklenemiyordu. Bu değişiklik, tasarlanmış ama önceden erişilemez olan bir kod yolunu ilk kez gerçekten çalışır hale getirdi.

**Doğrulama (gerçek, uçtan uca):** Cloud Run'a deploy edildi, `curl` ile THYAO için `mtf_aligned: true, mtf_consensus: "DOWN"` doğrulandı. Emulator'de TUPRS'in Teknik sekmesinde "Zaman Dilimi Uyumu: Yukarı (günlük + haftalık uyumlu)" kalın yazıyla doğru göründü.

**Tarih / Not:**
19.08.2026 — multi_timeframe Sinyal Özeti'ne bağlandı, 266/266 backend + 27/27 flutter test yeşil, commit `259cf5d`.

---

## 52. Yarı-Otomatik AL/SAT Bildirimleri — Somut Miktar Önerisiyle (AŞAMA 48/19) (19.08.2026)

Kullanıcı, daha önce sorulan (ve o zaman cevaplanmamış) "borsaya otomatik bağlanalım mı" sorusuna şimdi cevap verdi: "al sat kısmında bana bildirim göndersin sat veya şu kadar miktar al gibisinden yeter, daha sonra otomatiğe geçeriz." Bu, yarı-otomatik ("AI önerir, kullanıcı onaylar") yaklaşımın ilk somut adımı — gerçek alım-satım YAPILMIYOR, yalnızca bildirimler artık somut bir eylem öneriyor.

**SAT bildirimi (elde tutulan varlıklar):** Metin "Elinizdeki X adet {sembol} hissesini SATMANIZ öneriliyor" şeklinde netleştirildi (öncesinde yalnızca "X adet var" bilgisi veriyordu, bir eylem önermiyordu).

**AL bildirimi — iki senaryo:**
1. Elde tutulan bir varlıkta AL sinyali (ek alım) — mevcut davranış korundu.
2. Elde TUTULMAYAN bir varlıkta yeni fırsat — `notify_if_new_opportunity()` (yeni fonksiyon). AŞAMA 45'te çözülen "100 sembolün onlarcası spam bildirim" sorununu yeniden yaratmamak için yalnızca en yüksek güvenilirlikli sinyal sınıfında (`STRONG_BULLISH_INITIATION` — madde 48/18'de az önce gerçekten ulaşılabilir hale gelen sınıf) tetiklenir. Önerilen miktar = config'ten gelen sabit TL bütçesi (varsayılan 5000 TL, `system_config/notification_settings`) o anki fiyata bölünerek hesaplanır — kullanıcının risk toleransını/portföy büyüklüğünü bilmeden yapılabilecek en basit, en şeffaf tahmin. Gerçek bir pozisyon büyüklüğü stratejisi, kullanıcının kendi ifadesiyle "otomatiğe geçilince" ayrıca ele alınacak.

**Doğrulama:** Cloud Run'a deploy edildi; uygulama üzerinden gerçek, authenticated ~100 sembollük Dashboard yüklemesi sırasında hiçbir hata/500 oluşmadığı doğrulandı (119/119 istek 200 OK). Gerçek push teslimatı emülatörde test edilemiyor (Play Store yok, AŞAMA 32'den beri bilinen kısıtlama) — ama `UnregisteredError` zaten `firebase_exceptions.FirebaseError`'ın alt sınıfı olduğu doğrulandı, yani endpoint'i çökertmiyor.

**Tarih / Not:**
19.08.2026 — Yarı-otomatik bildirimler eklendi, 274/274 backend test yeşil (11 yeni test), commit `af99ea5`.

---

## 53. Test Bildirimi Butonu + Bildirimler Geçmişi Ekranı (AŞAMA 48/20) (19.08.2026)

Kullanıcı: "gerçek telefonuma apk'sını kuracağız, bildirim gönderme butonunu test edelim; ayarlara bir buton koy, basınca bana bildirim gelsin; AL/SAT bildirimi geldi mi görmek için bir bildirim sayfası da oluştur."

**Bildirim geçmişi:** `NotificationRecord` modeli/repository'si eklendi — kullanıcıya GÖNDERİLMİŞ her bildirimin değiştirilemez kaydı. `notification_log` (yalnızca dedup için "son bildirilen karar" tutan eski kayıt) ile KARIŞTIRILMAMALI; bu gerçek bir gönderim geçmişidir. `notify_if_strong_decision()`/`notify_if_new_opportunity()` artık başarıyla gönderilen her bildirimi buraya da yazıyor.

**Test bildirimi:** `fcm_sender.send_test_notification()` — gerçek bir AL/SAT kararına bağlı olmadan, yalnızca FCM'in cihazda çalışıp çalışmadığını doğrulamak için. Dedup uygulanmaz, kullanıcı istediği kadar test edebilir. Backend: `POST /notifications/test`, `GET /notifications/history` (ikisi de auth zorunlu).

**Flutter:** Ayarlar ekranına iki yeni kart — "Bildirimler" (yeni `NotificationHistoryScreen`'e gider, AL/SAT/Test bildirimlerini renkli rozet+ikonla listeler) ve "Test Bildirimi Gönder" (anında test bildirimi tetikler, sonucu snackbar'da gösterir).

**Doğrulama (gerçek, uçtan uca, emulator sınırları içinde):** Cloud Run'a deploy edildi. Emulator'de "Test Bildirimi Gönder" butonuna basıldı — istek backend'e ulaştı, FCM gönderimi denendi, emulator'de Play Store olmadığından (AŞAMA 32'den beri bilinen kısıtlama) beklenen hata ("Bildirim gönderilemedi — cihaz kayıtlı değil ya da FCM hatası oluştu") snackbar'da doğru göründü — Cloud Run loglarında `POST /notifications/test` → `400 Bad Request` olarak doğrulandı (500/crash YOK). Bildirimler ekranı boş durumunu ("Henüz bildirim gönderilmedi...") doğru gösterdi. Gerçek, Play Store'lu bir cihazda bu aynı zincir gerçek bir bildirim teslim etmelidir — kullanıcı bunu kendi telefonunda deneyecek.

**Tarih / Not:**
19.08.2026 — Test bildirimi + Bildirimler ekranı eklendi, 279/279 backend test yeşil (9 yeni test), 29/29 flutter test yeşil (2 yeni test), commit `7ad35be`.

---

## 54. Güncel Fiyat 422 Hatası: Gün-İçi Veri Boşken Günlük Bar'a Düşme (20.08.2026)

Kullanıcı: "güncel fiyat alınamadı 422 diyor fiyatları göremiyorum." Canlı ortamda izole yfinance çağrılarıyla doğrulandı: seans açılışına yakın saatlerde Yahoo'nun `period="1d", interval="5m"` gün-içi isteği THYAO/GARAN/AKBNK gibi geçerli semboller için bile "possibly delisted" yanılgılı hatasıyla boş DataFrame döndürüyordu (3 denemelik retry bile yetersizdi — bu AŞAMA 48/16'daki eş zamanlı-batch rate-limit sorunundan FARKLI, tekil istekte de görüldü). `BistProvider.get_quote()` bunu direkt `ValueError` → 422 olarak fırlatıyordu.

**Çözüm:** Gün-içi veri boşsa artık günlük bar'a (`period="5d"`) düşülüyor — `last_price`/`open`/`high`/`low`/`volume` son günlük satırdan alınıyor, `timestamp` yine verinin GERÇEK ait olduğu günü gösteriyor (sahte bir "şimdi" üretilmiyor). `previous_close` de `fast_info` başarısız olursa günlük geçmişin bir önceki satırından türetiliyor.

**Doğrulama (gerçek, uçtan uca):** 4 yeni test (`test_bist_provider.py`) + mevcut 283 test yeşil. Cloud Run'a deploy edildi, `curl` ile `/market-data/THYAO/quote` artık `200 OK` ve gerçek fiyat (`302.75`) döndürüyor — öncesinde 422 veriyordu.

**Tarih / Not:**
20.08.2026 — Güncel fiyat 422 fallback'i eklendi, 283/283 backend test yeşil (4 yeni test), commit `ab94849`.

---

## 55. Haber Kapsamını Genişletme: Google News RSS Kaynağı (20.08.2026)

Kullanıcı: "haberler kısmında çok az haber var neden." Araştırıldı: Yahoo Finance'in (`Ticker.news`) BIST sembolleri için haber kapsamı çok kısıtlı — yalnızca uluslararası ajansların İngilizce haberlerini kapsıyor, birçok sembolde 0-1 haber dönüyor (canlı test: ASELS 0, SASA 1, KCHOL 1; THYAO/GARAN gibi büyük semboller 6-10).

**Araştırılan seçenekler:** (1) Google News RSS arama — canlı test edildi, çok daha zengin Türkçe kapsam (ASELS için 14, SASA için 15+ haber: KAP bildirimlerini yansıtan haberler, analist hedef fiyatları, Bloomberght/Mynet Finans/Foreks/Investing.com Türkiye kaynaklı içerik); feed'in telif metni kullanımı "kişisel, ticari olmayan, kişisel feed reader" ile sınırlıyor — kullanıcıya bu gri alan açıkça anlatıldı, tek kullanıcılı kişisel bu uygulama için kabul edildi. (2) KAP'ın resmi API/RSS'i — hızlı denemede dokümante edilmiş bir uç nokta bulunamadı (404/boş yanıt), reverse-engineering gerektirir, ertelendi.

**Çözüm:** `GoogleNewsRssProvider` eklendi — `{sembol} hisse` sorgusuyla `news.google.com/rss/search` araması yapıp `<source>` etiketinden yayıncıyı, `pubDate`'ten yayın tarihini alıyor; ağ hatası/bozuk XML'de sessizce boş liste döner (endpoint'i çökertmez). `/news/{symbol}` artık Yahoo + Google News'i birleştirip `published_at`'e göre sıralıyor; Yahoo geçici hata verirse (bilinen bir durum, bkz. AŞAMA 48/16) sessizce Google News ile devam ediyor. Kaynak güvenilirlik sınıflandırması (`_classify_publisher`) iki sağlayıcı arasında tekrar edilmesin diye ortak `source_reliability.py`'ye taşındı ve Türkçe finans medyası (Bloomberght, Mynet, Foreks, Investing.com Türkiye, Bigpara, vb.) kategorilerine eklendi.

**Doğrulama (gerçek, uçtan uca):** 13 yeni test (`test_google_news_rss_provider.py`, `test_source_reliability.py`) + mevcut 293 test yeşil. Cloud Run'a deploy edildi, `curl` ile `/news/ASELS` artık `200 OK` ve 0 yerine 10 gerçek Türkçe haber döndürüyor (`Mynet`, `Paratic Haber`, `Ekonomim` vb. yayıncılarla).

**Tarih / Not:**
20.08.2026 — Google News RSS haber kaynağı eklendi, 293/293 backend test yeşil (13 yeni test), commit `8636630`.

---

## 56. Gerçek Cihazda Bildirim Gönderilemiyordu: `fid` FCM Token Değilmiş (20.08.2026)

Kullanıcı gerçek telefonuna kurduğu APK'da Ayarlar'daki "Test Bildirimi Gönder" butonunu denedi: "bildirim de hata aldık olmadı, cihaz kayıtlı değil ya da fcm hatası oluştu diyor." Bu hata emülatörde de görülmüştü (AŞAMA 48/20) ama o zaman "emülatörde Play Store yok, beklenen bir durum" diye açıklanmıştı — gerçek cihazda da AYNI hatanın çıkması bunun aslında GERÇEK bir bug olduğunu gösterdi.

**Kök neden:** `fcm_sender.py`, `messaging.Message`'a `fid=token` geçiriyordu — önceki bir oturumda "`Message.token` deprecated, `Message.fid` kullan" uyarısı görülünce ikisinin aynı şey olduğu varsayılmıştı (yalnızca `inspect.signature` ile kontrol edilmişti, gerçek bir gönderimle DOĞRULANMAMIŞTI). Ama `firebase_admin/_messaging_encoder.py` kaynağına bakıldığında `fid`'in FCM registration token'la aynı şey olmadığı görüldü: `fid` = "Firebase Installation ID" (FCM'den TAMAMEN FARKLI bir kimlik türü). Flutter'daki `FirebaseMessaging.instance.getToken()` ise gerçek bir FCM registration token döndürüyor. Bu iki farklı kimlik türünü `fid` alanına karıştırınca Firebase "NotRegistered" (404/`UnregisteredError`) döndürüyor — kullanıcının HEM emülatörde HEM gerçek cihazda gördüğü hatanın asıl kaynağı buydu; emülatördeki hata "Play Store yok" diye yanlış teşhis edilmişti.

**Doğrulama:** Kullanıcının Firestore'daki gerçek `fcm_tokens` kaydı okunup doğrudan `messaging.send(fid=token)` ile denendi → gerçekten `UnregisteredError('NotRegistered')`, 404. Aynı token'la `messaging.send(token=token)` → başarılı. `fcm_sender.py`'deki iki `fid=token` kullanımı (`notify_if_strong_decision`, `send_test_notification`) `token=token`'a geri döndürüldü (deprecation uyarısı zararsız — SDK'nın kendi dokümantasyonu yanıltıcıydı, davranış olarak `token` doğru olan). 293/293 backend test yeşil (2 test `fid` yerine `token` assertion'ına güncellendi). Deploy sonrası kullanıcının GERÇEK kayıtlı cihaz token'ına doğrudan gönderim denendi → başarılı.

**Ders:** Bir SDK'nın deprecation uyarısı, iki parametrenin aynı VERİ TÜRÜNÜ beklediği anlamına gelmez — davranış, imza kontrolüyle değil gerçek bir uçtan uca çağrıyla doğrulanmalı.

**Tarih / Not:**
20.08.2026 — FCM `fid`→`token` düzeltmesi, 293/293 backend test yeşil, commit `5d5b46e`.

---

## 57. Strateji Laboratuvarı — Çok Sembollü Teknik Strateji Karşılaştırma (20.08.2026)

Kullanıcı: "eski bir tarihe gidip verileri alıp o tarihte yapay zekamız nasıl işliyor diye test edicez... yapay zeka grafiklere haberlere vs bakarak ne kadar doğru tut al sat diyor bunu test etmemiz lazım ve her yolu deneyip hangisi daha iyi sonuç veriyor diye eğitim yapıcaz."

**Netleştirilen kısıt (kullanıcıya anlatıldı, onaylandı):** Haber (Yahoo + Google News, bkz. AŞAMA 55) ve makro (`macro_snapshots`) için gerçek bir geçmiş tarihli arşiv YOK — ikisi de yalnızca "o an geçerli olan"ı tutuyor/döndürüyor. Yani "2024'te bu hisse için hangi haberler vardı, AI o gün ne derdi" sorgulanamaz. Kullanıcıya 3 seçenek sunuldu (teknik tarafı derinleştir / ücretli haber arşivi araştır / haberleri şimdiden biriktirmeye başla); "şimdilik teknik sinyali derinlemesine test/eğit" seçildi.

**Çözüm — kapsam bilinçli olarak TEKNİK sinyale sınırlandı:** `strategy_presets.py` — 5 adlandırılmış `technical_indicator_weights` ön ayarı (Dengeli/varsayılan, Trend Takibi, Momentum Odaklı, Ortalamaya Dönüş, MACD Odaklı). Yeni `compare_strategies()` fonksiyonu, AŞAMA 28'deki `technical_score_series()`/`simulate()`'i DEĞİŞTİRMEDEN yeniden kullanıp her ön ayarı aynı fiyat serisi üzerinde çalıştırıp getiriye göre sıralanmış bir liste döner. Yeni endpoint: `GET /backtest/{symbol}/compare-strategies`.

**Flutter — "Strateji Laboratuvarı" (Ayarlar'dan erişilir):** Dönem (6ay-5yıl) ve sembol evreni (Portföyüm / BIST100 tümü) seçilir; "Testi Başlat" ile Dashboard'daki 10'arlı batch deseniyle (AŞAMA 43'te Cloud Run'a karşı tüm bağlantıları aynı anda açmanın bağlantı kopmalarına yol açtığı için benimsenmişti) toplu istek atılır. Sonuç: her ön ayarın TÜM test edilen sembollerdeki ortalama getirisi, ortalama kazanma oranı ve kaç sembolde #1 sırada (en iyi) çıktığı — kazanan altın renkle vurgulanır. Veri hatası veren semboller (delisted, yetersiz geçmiş vb.) sessizce atlanıp sayılır, tüm taramayı durdurmaz.

**Doğrulama (gerçek, uçtan uca):** 8 yeni backend testi (`test_backtest_engine.py`) + mevcut 295 test yeşil, 28/28 flutter test yeşil. Cloud Run'a deploy edildi, `curl` ile GARAN/THYAO için gerçek verilerle doğrulandı (ör. THYAO 2y'de MOMENTUM ön ayarı %17,28 getiriyle diğerlerini geride bıraktı, TREND_FOLLOWING %-14,03 ile en kötüsüydü — beklenen davranış: farklı rejimlerde farklı stratejiler kazanıyor). Gerçek cihaz için release APK yeniden derlendi (51,9MB).

**Tarih / Not:**
20.08.2026 — Strateji Laboratuvarı eklendi, 295/295 backend test yeşil (8 yeni test), 28/28 flutter test yeşil, commit `b8a387c`.

---

## 58. Fonlar — TEFAS Tabanlı Fon Analizi, Aylık Bütçe Önerisi ve Bildirimler (20.08.2026)

Kullanıcı: "fonlar için de analiz yaptır ve fonlar için ayrı sayfa oluştur, hangisi alınabilir hangisi en mantıklı gibisinden. Aylık ne kadar para kazanıyorum onu giricem ve her ay başı bana alınacak fonları ne kadar parayla gireceğimi söyleyecek. Ayrıca maaştan ayrı para olan bir buton olacak, o butona basınca o an hangi fonlar alınacak ise o fonları aldıracak; ekstra fonların düşeceği zaman var ise ya da daha da kar ettirecek bir fon var ise onun bildirimini yollayacak."

**Araştırma — iki gerçek engel netleştirildi (kullanıcıya anlatıldı, karar alındı):**
1. **TEFAS erişimi:** `tefas.gov.tr` ana sitesi F5 bot korumasıyla (TSPD, JS-challenge) korunuyor — düz `curl`/`requests` ile erişilemiyor, denendi ve doğrulandı. Ama TEFAS 2026'da Next.js tabanlı yeni bir altyapıya geçmiş ve kimlik doğrulama GEREKTİRMEYEN resmi bir JSON API sunuyor (`/api/funds/...`) — eski `/api/DB/BindHistoryInfo` gibi uç noktalar artık "Method not found or disabled" veriyor. `pytefas` (MIT lisanslı, aktif CI'lı açık kaynak kütüphane) bu yeni API'yi kullanıyor; canlı test edildi, çalışıyor.
2. **Gerçek alım-satım imkânsızlığı:** TEFAS'a genel kullanıcılar için açık bir işlem-emri (buy/sell) API'si YOK — bir bankaya/aracı kuruma üye olmadan ya da o kurumun SANA özel bir API anahtarı vermeden bu platformdan otomatik alım yapılamaz. Kullanıcıya bu netleştirildi; "Ekstra Para" butonunun somut bir bildirim (hisseler için AŞAMA 48/19'da kurulan yarı-otomatik desenin aynısı) göndermesi kabul edildi. Tema bazlı ("Nvidia/robot gündemde → ilgili hisseleri öner") hisse önerisi kısmı da ayrı bir oturuma ertelendi.

**TEFAS veri stratejisi — N+1 sorununun ÖNCEDEN çözülmesi:** TEFAS dakikada 6 istek sınırı uyguluyor; ~2000 fonun her biri için ayrı geçmiş çekmek saatler sürerdi. Bunun yerine TEK istekte TÜM fonların bir anlık görüntüsünü döndüren özellik kullanıldı — yalnızca 5 REFERANS TARİHİ (son işlem günü, -1ay, -3ay, -6ay, -1yıl) çekilip fund_code'a göre birleştiriliyor. Her tarih Firestore'da KALICI önbelleğe alınıyor (`FundSnapshotRepository` — geçmiş bir tarihin fon fiyatı asla değişmez, TTL yok); hesaplanmış SIRALAMA ayrıca 6 saatlik TTL'li ayrı bir önbellekte tutuluyor (`FundAnalysisCacheRepository`, benchmark_service.py ile aynı desen).

**FundAnalysisEngine:** 1a/3a/6a/1y getirilerin ağırlıklı ortalaması (`composite_score`, ağırlıklar 0.15/0.25/0.30/0.30). Missing Data Davranışı (DecisionEngine ile AYNI ilke): bir fonun bir ufukta verisi yoksa (yeni kurulmuş fon) o ufuk skora dahil edilmez, kalanların ağırlığı otomatik normalize edilir. Küçük/az yatırımcılı fonlar (< 5M TL portföy ya da < 20 yatırımcı) veri kalitesi hard-veto'suyla tamamen elenir (data_quality.py ile aynı prensip).

**Bütçe dağıtımı ve bildirimler:** `recommend_allocation()` bütçeyi en iyi 3 fona skora orantılı dağıtır (negatif skorlar pozitif ölçeğe kaydırılır, negatif TL tutarı üretilmez). `fund_notifier.py` üç bildirim türü: (1) aylık öneri — `GET /funds` her çağrıldığında "bu ay zaten bildirildi mi" kontrolü yapılır (decisions.py ile AYNI mimari desen — scheduler yok, kullanıcı eylemiyle tetiklenir); (2) ad-hoc "Ekstra Para Yatır" — dedup YOK, her basışta yeniden hesaplanıp gönderilir; (3) fon değiştirme önerisi — tutulan bir fonun skoru en iyi fondan 15 puandan fazla geride kalıyorsa "bunu satıp şuna geç" bildirimi, aynı öneri aynı gün tekrar gönderilmez.

**Flutter — "Fonlar" sekmesi** (yeni 3. bottom-nav sekmesi, Analiz/Portföy/Fonlar/Makro/Ayarlar): "Öneriler" (sıralı fon listesi + 1a/3a/6a/1y rozetleri + "Ekstra Para Yatır" butonu), "Fonlarım" (pozisyon ekle/sil, kâr-zarar), "Ayarlar" (aylık gelir/bütçe girişi). Bildirimler ekranındaki kind eşlemeleri (`FUND_BUY_MONTHLY`/`FUND_BUY_ADHOC`/`FUND_SWITCH`) güncellendi.

**Doğrulama (gerçek, uçtan uca):** 22 yeni backend testi (`test_fund_analysis_engine.py`, `test_fund_allocation.py`, `test_fund_notifier.py`, `test_fund_analysis_cache_service.py`) eklendi, toplam 317/317 backend test yeşil, 33/33 flutter test yeşil (5 yeni). Cloud Run'a deploy edildi; canlıda gerçek TEFAS verisiyle `/funds` doğrulandı (1341 fon geçti, ör. PKU %1285 1 yıllık getiriyle 1. sırada — serbest/hisse yoğun fonlarda böylesi uç değerler normal, ekranda "geçmiş performans garanti değildir + serbest fonlar yüksek volatilite taşır" uyarısı gösteriliyor). Ayarlar/pozisyon/allocate/switch zincirlerinin tamamı kullanıcının GERÇEK hesabıyla uçtan uca test edildi (aylık+ad-hoc+switch bildirimleri gerçekten cihaza gönderildi, doğrulama sonrası test verisi — pozisyon, bütçe, dedup kayıtları — temizlendi). Gerçek cihaz için release APK yeniden derlendi (52,1MB).

**Tarih / Not:**
20.08.2026 — Fonlar sayfası + TEFAS analiz motoru + aylık/ad-hoc/switch bildirimleri eklendi, 317/317 backend test yeşil (22 yeni test), 33/33 flutter test yeşil (5 yeni), commit `139636c`.

---

## 59. Ayarlar Sekmesinde Anlık Dağıtım Önizlemesi (20.08.2026)

Kullanıcı: "Aylık yatırım yapacağın miktarı seçebilsin kullanıcı ve bizim sistemimizde ona öneri versin, işte aylık 10 bin girdiysem 7 bin buna atalım 3 bin buna gibisinden — bu da güven değeri yüksekliği veya kâr edebileceğimiz hangisi daha yüksek ise ona göre değişir."

Bu mantık AŞAMA 58'de `recommend_allocation()` ile zaten vardı (skora orantılı dağıtım) ama kullanıcıya yalnızca AYDA BİR (bildirimle) ya da ayrı "Ekstra Para Yatır" butonuyla gösteriliyordu — Ayarlar sekmesinde bütçeni girdiğinde ANINDA görünmüyordu.

**Çözüm:** Yeni `GET /funds/allocation-preview?amount_tl=X` uç noktası — `/allocate`'ten FARKLI olarak bildirim GÖNDERMEZ, dedup'a dokunmaz, kullanıcı tutarı değiştirdikçe istediği kadar sorgulanabilir (aynı `recommend_allocation()` fonksiyonunu kullanır, dağıtım mantığı ayın başında gelecek gerçek bildirimle birebir aynı). Flutter: Ayarlar sekmesi artık bütçe her kaydedildiğinde (ve sayfa ilk açıldığında, bütçe zaten ayarlıysa) önizlemeyi otomatik çekip "Bu bütçe şöyle dağıtılır" kartı olarak gösteriyor.

**Doğrulama:** Mevcut 317 backend testi (yeni mantık olmadığından, sadece ince bir route — zaten test edilmiş `recommend_allocation`/`get_ranked_funds`'ı yeniden kullanıyor) + 33 flutter testi yeşil kaldı. `TestClient` ile auth override edilerek canlı doğrulandı: 10.000 TL girildiğinde skora orantılı 3506/3441/3051 TL dağılımı doğru döndü, bildirim tetiklenmedi. Cloud Run'a deploy edildi, gerçek cihaz için release APK yeniden derlendi.

**Not:** Bu kayıt sırasında AŞAMA 58'in doğrulama satırındaki test sayısı hatası da (yanlışlıkla "23 yeni test, 340 toplam" yazılmıştı) 22/317 olarak düzeltildi.

**Tarih / Not:**
20.08.2026 — Ayarlar'da anlık dağıtım önizlemesi eklendi, 317/317 backend test yeşil, 33/33 flutter test yeşil.

---

## 60. Fon Analizini Detaylandırma: Risk Oranı, "Neden Bu Fon", Haber Kaynakları ve Arama (20.08.2026)

Kullanıcı: "Filtreleme kısmı yok, işte risk oranı ne gibi oranları da detaylıca belirt, neden almamı önerdiğini belirt, ayrıca ünlü borsa bilgileri paylaşan sayfalardan önerilerine bakıp bunu önerdiler ve şu yüzden gibi anlat, arama kısmı ekle her fona ulaşabileyim... Açıkçası fon kısmı daha detaylı olsun."

**Risk oranı — TEFAS'ın GERÇEK portföy dağılım verisinden:** `TefasProvider.get_breakdown_snapshot()` (pytefas `columns="breakdown"`, aynı "tek istekte tüm fonlar" verimliliğiyle, ~50 varlık sınıfı yüzdesi) eklendi; `FundBreakdownRepository` (fund_snapshot_repository.py ile aynı KALICI önbellek deseni, ayrı koleksiyon). Yeni `risk.py`: hisse/ETF/gayrimenkul/girişim sermayesi/türev ağırlığı %50'yi geçerse YÜKSEK, nakit/repo/mevduat/devlet tahvili ağırlığı %60'ı geçerse DÜŞÜK, aksi halde ORTA — bir portföy optimizasyon modeli değil, şeffaf/yorumlanabilir bir sınıflandırma (Sharpe/volatilite TEFAS tarafından yayınlanmıyor, günlük fiyat serisi rate-limit yüzünden pratik değil).

**"Neden bu fon" açıklaması — LLM YOK, tamamen deterministik:** Yeni `explanation.py`, getiri rakamları + risk seviyesi + sıralamadaki konumu şablonla okunabilir bir Türkçe cümleye çeviriyor (ör. "Getiri (1 ay: %+24.6, ... 1 yıl: %+1285.4). Analiz edilen 1341 fon arasında 1. sırada. Risk seviyesi: Yüksek."). LLM çağrısı bilinçli olarak kullanılmadı — haber duygu analizinin aksine burada sayısal veriden üretilen bir metin yeterli, daha ucuz ve halüsinasyon riski sıfır.

**Haber/yorum kaynakları — "ünlü sayfalar ne diyor":** `GoogleNewsRssProvider.get_latest_news()` artık opsiyonel `query_suffix` alıyor (AŞAMA 55'te sabit "hisse" idi, fonlar için "fon" kullanılıyor). Yeni `GET /funds/{code}/news` bu fonla ilgili GERÇEKTEN bulunan haber/yorum makalelerini listeler — belirli bir hesabın/otoritenin önerdiği İDDİA EDİLMEZ (uydurma atıf riski), yalnızca gerçek başlık/kaynak olduğu gibi gösterilip yorum kullanıcıya bırakılıyor.

**Arama — "her fona ulaşabileyim":** `GET /funds?q=...` artık kalite filtresini geçen TÜM (1341) fonda kod/ad araması yapıyor, yalnızca varsayılan öneri listesindeki ilk 30'da değil. **Bulunan ve düzeltilen gerçek bug:** Python'un standart `str.upper()`'ı Türkçe küçük "i"yi ASCII "I"ye çeviriyor, ama TEFAS verisi Türkçe noktalı "İ" kullanıyor — "hisse" araması ilk denemede SIFIR sonuç döndürdü (canlı testte yakalandı). `_tr_upper()` yardımcı fonksiyonu (önce Türkçe küçük harfleri doğru büyük karşılıklarına çevirip sonra upper() çağırıyor) ile düzeltildi, regresyon testiyle kilitlendi.

**Fon detay ekranı (yeni):** Öneriler listesinden/aramadan bir fona dokununca açılıyor — tam getiri skorları, risk kartı (seviye + hisse/güvenli varlık yüzdeleri), "Neden Bu Fon?" açıklaması, haber/yorum kaynakları (otomatik yüklenir). Fonlarım sekmesindeki pozisyonlar da artık aynı detay ekranına gidiyor.

**Not — önbellek/şema uyumu:** `get_ranked_funds()`'ın 6 saatlik TTL'li önbelleği yeni alanlar (risk_level vb.) eklenmeden ÖNCE dolmuştu; yeni alanlar pydantic'te opsiyonel/varsayılanlı olduğundan eski önbellek çökme YARATMADI ama `risk_level: null` gibi eksik veri döndürdü — canlı testte fark edilip önbellek belgesi manuel temizlendi, yeni hesaplama doğru alanlarla doldu.

**Doğrulama (gerçek, uçtan uca):** 15 yeni backend testi (`test_fund_risk.py`, `test_fund_explanation.py`, `test_funds_api_helpers.py`, `test_fund_analysis_engine.py`'ye 3 ek) + mevcut, toplam 332/332 backend test yeşil, 34/34 flutter test yeşil (2 yeni). Cloud Run'a deploy edildi; canlıda gerçek verilerle doğrulandı — PKU için risk_level: YUKSEK (equity %105.6), açıklama metni doğru, "hisse" araması artık 50 sonuç döndürüyor (önceden 0), `/funds/PKU/news` gerçek bir makale (YatırımX kaynaklı) döndürdü. Gerçek cihaz için release APK yeniden derlendi.

**Tarih / Not:**
20.08.2026 — Risk oranı + açıklama + haber kaynağı + arama + fon detay ekranı eklendi, 332/332 backend test yeşil (15 yeni test), 34/34 flutter test yeşil (2 yeni).

---

## 61. Hisseler İçin Analist Görüşleri: Hedef Fiyat/Tavsiye Haberleri + AI Kararı Karşılaştırması (20.08.2026)

Kullanıcı: "Analistlerin değerlendirmeleri de bulunsun, al mı diyorlar yoksa sat mı diyorlar, güvenilir analistleri araştır ve bizim al dediklerimizi de yanında belirt, işte AI de bunu öneriyor gibisinden." (Bu, önceki 2 mesajın fon odaklı akışından farklı olarak HİSSELER — Varlık Detayı ekranı — için.)

**Araştırma:** Google News RSS'e (AŞAMA 55) `"{sembol} hedef fiyat OR tavsiye OR analist"` sorgusuyla gidildiğinde, mevcut genel `"{sembol} hisse"` sorgusundan ÇOK daha yüksek kaliteli, gerçek banka/aracı kurum içeriği geldiği canlı testte doğrulandı (ör. THYAO için "HSBC: ... favori THYAO, hedef fiyat yükseldi", "THYAO için hedef fiyat 474 TL'ye indirilirken 'al' korundu", "15 kurumdan yeni hedef fiyat geldi"). Google'ın RSS'i `OR` boolean operatörünü destekliyor.

**Bilinçli tasarım kararı — keyword sınıflandırıcı YERİNE mevcut LLM pipeline'ı:** İlk planda başlıktan "AL_EGILIMLI"/"SAT_EGILIMLI" çıkaran bir anahtar kelime sınıflandırıcısı düşünüldü, ama gerçek başlıklar incelenince (ör. "hedef fiyat düşürüldü" bile "al" tavsiyesi KORUNMUŞ olabiliyor — başlık tek başına yönü güvenilir belirlemiyor) bunun YANLIŞ bir "AL" etiketi üretip kullanıcıyı gerçek bir finansal kararda yanıltabileceği görüldü. Bunun yerine: (1) bu haberler mevcut, zaten test edilmiş/maliyet takipli OpenAI tabanlı haber duygu analizi pipeline'ına (EventIntelligenceEngine, "Analiz Et" butonu) dahil edildi — kullanıcı isterse gerçek bir AI okuması alır; (2) mevcut DecisionEngine kararımız ("AI Kararımız: AL/SAT/TUT") Haberler sekmesinin en üstünde ayrıca gösterilerek karşılaştırma kullanıcıya bırakıldı.

**Çözüm:** `NewsRawItem`e `is_analyst_mention: bool` eklendi. `GET /news/{symbol}` artık Yahoo + genel Google + analist-odaklı Google sorgusunu birleştiriyor; yeni `merge_prioritizing_analyst_mentions()` (services/news/merge.py) analist etiketli haberlerin sıradan haberler tarafından listeden itilmesini önlüyor (önce analist içerik garanti edilir, kalan yer en yeni diğer haberlerle doldurulur). Flutter: Haberler sekmesinin en üstünde "AI Kararımız: AL (skor +45.2, güven %70)" kartı (mevcut `/decisions/{symbol}`'dan); analist etiketli haber kartlarında mor "Analist / Hedef Fiyat" rozeti.

**Doğrulama (gerçek, uçtan uca):** 4 yeni backend testi (`test_news_merge.py`) + mevcut, toplam 336/336 backend test yeşil, 36/36 flutter test yeşil (2 yeni). Cloud Run'a deploy edildi; GARAN için canlı doğrulandı ("Aracı kurumlardan dört büyük banka için hedef fiyat revizyonu - Forbes Türkiye" doğru döndü). Gerçek cihaz için release APK yeniden derlendi.

**Tarih / Not:**
20.08.2026 — Hisseler için analist görüşü entegrasyonu eklendi, 336/336 backend test yeşil (4 yeni test), 36/36 flutter test yeşil (2 yeni).

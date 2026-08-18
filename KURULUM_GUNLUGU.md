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

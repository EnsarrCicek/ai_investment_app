import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';

import 'features/auth/login_screen.dart';
import 'features/dashboard/dashboard_screen.dart';
import 'features/funds/funds_screen.dart';
import 'features/macro/macro_screen.dart';
import 'features/portfolio/portfolio_screen.dart';
import 'features/settings/settings_screen.dart';
import 'firebase_options.dart';
import 'services/notification_service.dart';
import 'utils/app_gradients.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  runApp(const MyApp());
}

// AŞAMA 68: kullanıcı isteği — "renk paketlerini modern hale getir, renk
// geçişleri yap, mavi tonlarını kullanabilirsin, görünürlüğü güçleştirme."
// Mavi tonlu bir seed'den Material 3 tam paleti üretilir (birincil/ikincil/
// yüzey tonları otomatik uyumlu olur); bileşen temaları (Card/Button/Input/
// Chip/TabBar/NavigationBar) modern, yuvarlatılmış bir görünüm için ayrıca
// özelleştirilir. Kontrast her zaman korunur: koyu gradyanların üzerinde
// yalnızca beyaz metin/ikon kullanılır (bkz. app_gradients.dart, GradientAppBar).
final ThemeData _appTheme = () {
  final colorScheme = ColorScheme.fromSeed(seedColor: AppGradients.vividBlue);
  return ThemeData(
    useMaterial3: true,
    colorScheme: colorScheme,
    scaffoldBackgroundColor: colorScheme.surface,
    appBarTheme: AppBarTheme(
      backgroundColor: AppGradients.deepBlue,
      foregroundColor: Colors.white,
      elevation: 0,
      centerTitle: false,
    ),
    cardTheme: CardThemeData(
      elevation: 1,
      surfaceTintColor: colorScheme.surfaceTint,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      clipBehavior: Clip.antiAlias,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    ),
    chipTheme: ChipThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      side: BorderSide.none,
      backgroundColor: colorScheme.surfaceContainerHighest,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide.none,
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: colorScheme.primary, width: 1.6),
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: colorScheme.surface,
      indicatorColor: colorScheme.primaryContainer,
      elevation: 3,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => TextStyle(
          fontSize: 12,
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.bold
              : FontWeight.normal,
          color: states.contains(WidgetState.selected)
              ? colorScheme.primary
              : colorScheme.onSurfaceVariant,
        ),
      ),
    ),
    tabBarTheme: const TabBarThemeData(
      labelColor: Colors.white,
      unselectedLabelColor: Colors.white70,
      indicatorColor: Colors.white,
      indicatorSize: TabBarIndicatorSize.label,
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
  );
}();

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AI Yatirim Analiz',
      theme: _appTheme,
      home: const AuthGate(),
    );
  }
}

class AuthGate extends StatelessWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<User?>(
      stream: FirebaseAuth.instance.authStateChanges(),
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.active) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }
        return snapshot.data == null ? const LoginScreen() : const RootScreen();
      },
    );
  }
}

class RootScreen extends StatefulWidget {
  /// Testler için enjekte edilebilir sekme ekranları ve bildirim başlatma.
  final List<Widget> screens;
  final bool initializeNotifications;

  const RootScreen({super.key, this.screens = defaultScreens, this.initializeNotifications = true});

  static const defaultScreens = [
    DashboardScreen(),
    PortfolioScreen(),
    FundsScreen(),
    MacroScreen(),
    SettingsScreen(),
  ];

  @override
  State<RootScreen> createState() => _RootScreenState();
}

class _RootScreenState extends State<RootScreen> {
  int _index = 0;

  // Analiz sekmesi (0) bir kez kurulur ve durumu korunur (IndexedStack): sekmeye geri dönmek veriyi yeniden çekmez
  // (eskiden her dönüşte sıfırdan kurulup ~101 istek atıyordu); yenileme yalnız açık "çek-yenile" ile. Diğer
  // sekmeler önceki gibi yalnız seçiliyken kurulur, böylece her ziyarette güncel veri çeker (ör. Analiz'den hızlı
  // alım sonrası Portföy) ve açılışta istek tetiklemez.
  static const _persistentTabs = {0};

  bool _isBuilt(int i) => i == _index || _persistentTabs.contains(i);

  @override
  void initState() {
    super.initState();
    if (!widget.initializeNotifications) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) NotificationService.initialize(context);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _index,
        children: [
          for (var i = 0; i < widget.screens.length; i++)
            _isBuilt(i) ? widget.screens[i] : const SizedBox.shrink(),
        ],
      ),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          boxShadow: [
            BoxShadow(
              color: AppGradients.deepBlue.withValues(alpha: 0.12),
              blurRadius: 12,
              offset: const Offset(0, -3),
            ),
          ],
        ),
        child: NavigationBar(
          selectedIndex: _index,
          onDestinationSelected: (i) => setState(() => _index = i),
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.show_chart),
              label: 'Analiz',
            ),
            NavigationDestination(
              icon: Icon(Icons.pie_chart),
              label: 'Portföy',
            ),
            NavigationDestination(
              icon: Icon(Icons.savings_outlined),
              label: 'Fonlar',
            ),
            NavigationDestination(icon: Icon(Icons.public), label: 'Makro'),
            NavigationDestination(icon: Icon(Icons.settings), label: 'Ayarlar'),
          ],
        ),
      ),
    );
  }
}

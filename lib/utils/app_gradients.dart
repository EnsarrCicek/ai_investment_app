import 'package:flutter/material.dart';

/// AŞAMA 68: kullanıcı isteği — "renk paketlerini modern hale getir, renk
/// geçişleri yap, mavi tonlarını kullanabilirsin, görünürlüğü güçleştirme."
/// Uygulama genelinde tekrar kullanılan mavi tonlu gradyanlar — tüm
/// gradyanlar koyu uçlu tutulur ki üzerlerine BEYAZ metin/ikon her zaman
/// yeterli kontrastla okunabilsin (WCAG AA hedefi).
class AppGradients {
  AppGradients._();

  static const Color deepBlue = Color(0xFF0F2E6B);
  static const Color vividBlue = Color(0xFF2563EB);
  static const Color skyBlue = Color(0xFF3B82F6);

  /// AppBar'lar ve öne çıkan başlık alanları için — sol üstten sağ alta
  /// koyudan canlıya geçen mavi gradyan.
  static const LinearGradient appBar = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [deepBlue, vividBlue],
  );

  /// Giriş ekranı gibi geniş, tek başına arka planlar için — biraz daha
  /// yumuşak/derinlikli üç renkli geçiş.
  static const LinearGradient hero = LinearGradient(
    begin: Alignment.topCenter,
    end: Alignment.bottomCenter,
    colors: [deepBlue, vividBlue, skyBlue],
  );

  /// Vurgu kartları (ör. Dashboard/Portföy özet kartı) için daha kısa,
  /// köşegen geçiş.
  static const LinearGradient card = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [vividBlue, skyBlue],
  );
}

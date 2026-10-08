import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;

import '../../models/portfolio_position.dart';
import '../../models/portfolio_transaction.dart';
import '../../models/position_limits.dart';
import 'api_config.dart';

/// `/sell` hata yanıtı. `code` backend'in `detail.code` alanı (ör. POSITION_CHANGED, QUANTITY_EXCEEDS_AVAILABLE);
/// doğrulama (pydantic) hatalarında null.
class SellPositionException implements Exception {
  final int statusCode;
  final String? code;
  final String message;

  const SellPositionException(this.statusCode, this.code, this.message);

  bool get positionChanged => statusCode == 409 || code == 'POSITION_CHANGED';

  @override
  String toString() => message;
}

class PortfolioApi {
  static const String baseUrl = apiBaseUrl;

  /// `POST /portfolio/positions/{asset}/sell` gövdesi (backend `PositionSaleRequest` ile birebir).
  /// `currency` yalnız pozisyonun kayıtlı para birimi; bilinmiyorsa null (tahmin yok).
  static Map<String, dynamic> sellBody({
    required double quantity,
    required double sellPrice,
    required String positionVersion,
    String? currency,
    DateTime? sellDate,
  }) =>
      {
        'quantity': quantity,
        'sell_price': sellPrice,
        'position_version': positionVersion,
        'currency': currency,
        'sell_date': sellDate?.toIso8601String(),
      };

  /// Backend hata gövdesini çözer: `{"detail": {"code", "message"}}` (satış hataları) veya
  /// `{"detail": [...]}` (istek doğrulama hataları).
  static SellPositionException parseSellError(int statusCode, String body) {
    String? code;
    String? message;
    try {
      final detail = (jsonDecode(body) as Map<String, dynamic>)['detail'];
      if (detail is Map<String, dynamic>) {
        code = detail['code'] as String?;
        message = detail['message'] as String?;
      }
    } catch (_) {
      // gövde JSON değil: genel mesaj
    }
    if (code == 'QUANTITY_EXCEEDS_AVAILABLE') message = 'Satılacak adet mevcut adetten fazla olamaz.';
    if (statusCode == 409 || code == 'POSITION_CHANGED') message = 'Pozisyon değişti. Güncel bilgiler yeniden yüklendi.';
    return SellPositionException(statusCode, code, message ?? 'Satış kaydedilemedi (HTTP $statusCode)');
  }

  /// Kısmi/tam satış (ağırlıklı ortalama, sunucuda). Kalan pozisyon istemcide HESAPLANMAZ; çağıran portföyü yeniden yükler.
  Future<PortfolioTransaction> sellPosition({
    required String asset,
    required double quantity,
    required double sellPrice,
    required String positionVersion,
    String? currency,
    DateTime? sellDate,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/portfolio/positions/$asset/sell'),
      headers: await _authHeaders(),
      body: jsonEncode(sellBody(
          quantity: quantity, sellPrice: sellPrice, positionVersion: positionVersion, currency: currency, sellDate: sellDate)),
    );
    if (response.statusCode != 200) {
      throw parseSellError(response.statusCode, utf8.decode(response.bodyBytes));
    }
    return PortfolioTransaction.fromJson(jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>);
  }

  Future<Map<String, String>> _authHeaders() async {
    final token = await FirebaseAuth.instance.currentUser?.getIdToken();
    return {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
  }

  Future<(List<PortfolioPosition>, PortfolioSummary)> fetchPositions() async {
    final response = await http.get(
      Uri.parse('$baseUrl/portfolio/positions'),
      headers: await _authHeaders(),
    );
    if (response.statusCode != 200) {
      throw Exception('Portföy alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    final positions = (json['positions'] as List)
        .map((e) => PortfolioPosition.fromJson(e as Map<String, dynamic>))
        .toList();
    final summary = PortfolioSummary.fromJson(json['summary'] as Map<String, dynamic>);
    return (positions, summary);
  }

  /// Pozisyon oluşturma/güncelleme gövdesi. [currency] kayıtlı alış fiyatının birimidir; yalnız doğrulanmış
  /// kaynaktan biliniyorsa verilir, aksi hâlde null gönderilir (TRY varsayılmaz).
  static Map<String, dynamic> positionBody({
    String? asset,
    required double buyPrice,
    required double quantity,
    required DateTime buyDate,
    String? currency,
  }) =>
      {
        'asset': ?asset,
        'buy_price': buyPrice,
        'quantity': quantity,
        'buy_date': buyDate.toIso8601String(),
        'currency': currency,
      };

  Future<void> createPosition({
    required String asset,
    required double buyPrice,
    required double quantity,
    required DateTime buyDate,
    String? currency,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/portfolio/positions'),
      headers: await _authHeaders(),
      body: jsonEncode(positionBody(
          asset: asset, buyPrice: buyPrice, quantity: quantity, buyDate: buyDate, currency: currency)),
    );
    if (response.statusCode != 200) {
      throw Exception('Pozisyon eklenemedi (HTTP ${response.statusCode})');
    }
  }

  Future<void> updatePosition({
    required String asset,
    required double buyPrice,
    required double quantity,
    required DateTime buyDate,
    String? currency,
  }) async {
    final response = await http.put(
      Uri.parse('$baseUrl/portfolio/positions/$asset'),
      headers: await _authHeaders(),
      body: jsonEncode(positionBody(buyPrice: buyPrice, quantity: quantity, buyDate: buyDate, currency: currency)),
    );
    if (response.statusCode != 200) {
      throw Exception('Pozisyon güncellenemedi (HTTP ${response.statusCode})');
    }
  }

  Future<void> deletePosition(String asset) async {
    final response = await http.delete(
      Uri.parse('$baseUrl/portfolio/positions/$asset'),
      headers: await _authHeaders(),
    );
    if (response.statusCode != 200) {
      throw Exception('Pozisyon silinemedi (HTTP ${response.statusCode})');
    }
  }

  /// "Sattım" akışı (AŞAMA 47): pozisyonu silmek yerine satış fiyatını
  /// kaydedip gerçekleşen kâr/zararı geçmişe (Portföy Geçmişi) ekler.
  Future<void> closePosition({required String asset, required double sellPrice}) async {
    final response = await http.post(
      Uri.parse('$baseUrl/portfolio/positions/$asset/close'),
      headers: await _authHeaders(),
      body: jsonEncode({'sell_price': sellPrice}),
    );
    if (response.statusCode != 200) {
      throw Exception('Pozisyon kapatılamadı (HTTP ${response.statusCode})');
    }
  }

  /// Kullanıcı sınırlarının ELLE kontrolü (salt-okunur). Yalnız sınır yüzdeleri ve pozisyon sürümü
  /// gönderilir; fiyat ve maliyet sunucuda kayıtlı pozisyondan ve veri kaynağından alınır.
  Future<LimitCheckResult> checkLimits({
    required String asset,
    required String positionVersion,
    double? profitTargetPct,
    double? maxLossPct,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/portfolio/positions/$asset/limit-check'),
      headers: await _authHeaders(),
      body: jsonEncode({
        'position_version': positionVersion,
        'profit_target_pct': profitTargetPct,
        'max_loss_pct': maxLossPct,
      }),
    );
    if (response.statusCode != 200) {
      throw Exception('Sınır kontrolü yapılamadı (HTTP ${response.statusCode})');
    }
    return LimitCheckResult.fromJson(jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>);
  }

  Future<PortfolioHistorySummary> fetchHistory() async {
    final response = await http.get(
      Uri.parse('$baseUrl/portfolio/history'),
      headers: await _authHeaders(),
    );
    if (response.statusCode != 200) {
      throw Exception('Portföy geçmişi alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return PortfolioHistorySummary.fromJson(json);
  }
}

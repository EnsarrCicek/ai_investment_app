/// Para birimi gösterimi — hiçbir değer varsayılmaz.
///
/// ISO 4217 kodu bilinmiyorsa (null) birim yazılmaz; TRY → "TL", diğerleri ISO koduyla.
String? currencyUnit(String? iso) => iso == null ? null : (iso == 'TRY' ? 'TL' : iso);

/// Birim biliniyorsa "tutar birim", değilse yalnız tutar.
String withUnit(String amount, String? unit) => unit == null ? amount : '$amount $unit';

/// Birden çok tutarın toplamı için ortak birim: liste boş değilse ve tüm birimler bilinen ve AYNI ise o birim.
String? commonUnit(Iterable<String?> units) {
  final set = units.toSet();
  return set.length == 1 ? set.first : null;
}

import 'dart:convert';

import 'package:crypto/crypto.dart';

/// Canonical JSON identical to the Windows collector's Python
/// `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)`,
/// so bar/response hashes computed on the phone are comparable with the Windows archive.
String canonicalJson(Object? value) {
  final out = StringBuffer();
  _write(out, value);
  return out.toString();
}

String sha256Hex(String text) => sha256.convert(utf8.encode(text)).toString();

String canonicalSha256(Object? value) => sha256Hex(canonicalJson(value));

/// Bar hash = SHA-256 of canonical `[open, high, low, close, volume]` (same as `storage.bar_hash`).
String barHash(double? open, double? high, double? low, double? close, double? volume) =>
    canonicalSha256(<double?>[open, high, low, close, volume]);

/// Python `repr(float)`: shortest round-trip digits; scientific notation when the decimal exponent is
/// < -4 or >= 16 (exponent at least two digits), otherwise fixed notation with a trailing `.0` for integers.
String pyFloatRepr(double v) {
  if (v.isNaN || v.isInfinite) {
    throw ArgumentError('NaN/Infinity is not allowed in canonical JSON');
  }
  if (v == 0) return v.isNegative ? '-0.0' : '0.0';
  final parts = v.toStringAsExponential().split('e');
  final mantissa = parts[0];
  final exp = int.parse(parts[1]);
  if (exp < -4 || exp >= 16) {
    final sign = exp < 0 ? '-' : '+';
    return '${mantissa}e$sign${exp.abs().toString().padLeft(2, '0')}';
  }
  final negative = mantissa.startsWith('-');
  final digits = mantissa.replaceAll('-', '').replaceAll('.', '');
  String body;
  if (exp >= 0) {
    if (digits.length <= exp + 1) {
      body = '${digits.padRight(exp + 1, '0')}.0';
    } else {
      body = '${digits.substring(0, exp + 1)}.${digits.substring(exp + 1)}';
    }
  } else {
    body = '0.${'0' * (-exp - 1)}$digits';
  }
  return negative ? '-$body' : body;
}

void _write(StringBuffer out, Object? value) {
  if (value == null) {
    out.write('null');
  } else if (value is bool) {
    out.write(value ? 'true' : 'false');
  } else if (value is int) {
    out.write(value.toString());
  } else if (value is double) {
    out.write(pyFloatRepr(value));
  } else if (value is String) {
    _writeString(out, value);
  } else if (value is List) {
    out.write('[');
    for (var i = 0; i < value.length; i++) {
      if (i > 0) out.write(',');
      _write(out, value[i]);
    }
    out.write(']');
  } else if (value is Map) {
    final keys = value.keys.map((k) => k as String).toList()..sort();
    out.write('{');
    for (var i = 0; i < keys.length; i++) {
      if (i > 0) out.write(',');
      _writeString(out, keys[i]);
      out.write(':');
      _write(out, value[keys[i]]);
    }
    out.write('}');
  } else {
    throw ArgumentError('Unsupported canonical JSON type: ${value.runtimeType}');
  }
}

const _shortEscapes = {0x22: r'\"', 0x5c: r'\\', 0x0a: r'\n', 0x0d: r'\r', 0x09: r'\t', 0x08: r'\b', 0x0c: r'\f'};

void _writeString(StringBuffer out, String s) {
  out.write('"');
  for (final unit in s.codeUnits) {
    final short = _shortEscapes[unit];
    if (short != null) {
      out.write(short);
    } else if (unit < 0x20 || unit > 0x7e) {
      out.write('\\u${unit.toRadixString(16).padLeft(4, '0')}');
    } else {
      out.writeCharCode(unit);
    }
  }
  out.write('"');
}

/// HATA 5C-UI2 (31.08.2026): `DecisionEngine` 1.1.0 öncesi kayıtlarda
/// `AIDecision.confidence` eski heuristik anlam taşır (kanal eksikse sabit
/// `0.6` fallback dahil) -- >=1.1.0 kayıtlarda ise "Sinyal Mutabakatı"
/// (cross-engine yönsel mutabakat) anlamına gelir. Aynı sayıyı aynı label
/// ile göstermek metodolojik olarak YANLIŞ olur (bkz. journal'daki
/// version-aware etiketleme).
///
/// Lexicographic string compare GÜVENLİ DEĞİLDİR (ör. "1.10.0" < "1.2.0"
/// olurdu) -- bu yüzden major/minor sayısal olarak parse edilip
/// karşılaştırılır. Geçersiz/eksik versiyon LEGACY kabul edilir (yeni
/// formülün üretildiği kanıtlanamıyorsa eski etiket güvenli varsayılan).
bool isNewDecisionConfidenceSemantics(String? version) {
  if (version == null || version.isEmpty) return false;
  final parts = version.split('.');
  if (parts.length < 2) return false;
  final major = int.tryParse(parts[0]);
  final minor = int.tryParse(parts[1]);
  if (major == null || minor == null) return false;
  if (major != 1) return major > 1;
  return minor >= 1;
}

/// HATA 5C-UI2 (31.08.2026): Karar Günlüğü'ndeki (Decision Journal) tek
/// doğru label kaynağı -- eski/legacy kayıtlarda "Sinyal Mutabakatı" YAZILMAZ
/// (o sayı yeni agreement formülünden üretilmedi).
String journalConfidenceLabel(String? decisionEngineVersion) =>
    isNewDecisionConfidenceSemantics(decisionEngineVersion) ? 'Sinyal Mutabakatı' : 'Eski Güven Skoru';

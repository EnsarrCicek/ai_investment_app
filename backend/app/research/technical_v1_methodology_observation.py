"""Technical V1 METHODOLOGY kimlik-kapısı -- gözlemlenen (observed)
metodoloji parmak-izi adaptörü. HATA 12N3C2-B2-D.

Beklenen (expected) taraf İÇİN ayrı bir loader/adaptör YOKTUR -- section 11
gereği bu değer doğrudan ZATEN doğrulanmış bir `TechnicalV1ActivationLock.
authorized_methodology_source_fingerprint` alanından okunur (basit bir
attribute erişimi, dosya/ağ I/O'su İÇERMEZ) -- çağıran bunu doğrudan
`identity_gates.evaluate_methodology_gate()`'e verir.

Bu modül YALNIZCA gözlemlenen tarafı sarmalar: `compute_methodology_
source_fingerprint()` (bkz. `methodology_fingerprint.py`, 27-dosya
implementasyonu) GERÇEKTEN dosya sistemi okuması yapar -- bu I/O, saf kapı
karşılaştırmasından (section 12/20) burada AYRI tutulur.
"""

from __future__ import annotations

from app.research.methodology_fingerprint import compute_methodology_source_fingerprint


def observe_methodology_source_fingerprint() -> str:
    """Şu an deploy edilmiş 27-dosya metodoloji kaynağının parmak-izini
    döner -- `methodology_fingerprint.py`'nin KENDİ, TEK implementasyonunu
    (dosya listesi + hash algoritması) DOĞRUDAN çağırır, ikinci bir kopya
    İCAT ETMEZ (section 12/31)."""
    return compute_methodology_source_fingerprint()

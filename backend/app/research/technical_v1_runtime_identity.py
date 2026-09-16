"""Technical V1 RUNTIME kimlik-kapısı -- gözlemlenen (observed) runtime
kimliği adaptörü. HATA 12N3C2-B2-D.

Bu modül, `identity_gates.evaluate_runtime_gate()`'in SAF karşılaştırma
katmanından AYRI tutulan, GERÇEK ortam değişkeni okuması yapan I/O
adaptörüdür (section 16/20: repository/ortam I/O'su, saf kapı
karşılaştırmasından her zaman ayrı tutulur).

ÖNEMLİ, DÜRÜST GARANTİ (section 15): `FIREBASE_PROJECT_ID`, `app/core/
config.py`'de bir ortam değişkeni (APPLICATION_CONFIG) olarak tanımlıdır --
kriptografik bir GCP platform attestation'ı DEĞİLDİR. Bu modülün ürettiği
runtime kimliği bu yüzden bir DEPLOYMENT YETKİLENDİRME/AUDIT kimliğidir,
kriptografik GCP tenancy KANITI DEĞİLDİR. Bu gerçek asla abartılmaz/yanlış
temsil edilmez.

`K_SERVICE`/`K_REVISION`, Cloud Run'ın HER servis instance'ına kendisinin
enjekte ettiği standart ortam değişkenleridir (bkz. Cloud Run resmi
dokümantasyonu) -- bu proje bunları KENDİSİ set etmez, yalnızca OKUR.
"""

from __future__ import annotations

import os

from app.core.config import FIREBASE_PROJECT_ID
from app.research.activation_lock import compute_runtime_fingerprint


class RuntimeIdentityUnobservableError(RuntimeError):
    """`K_SERVICE`/`K_REVISION` ortam değişkenlerinden biri ya da ikisi de
    eksik -- bu, "gözlemlenen runtime kimliği YETKİSİZ" (bir RUNTIME kapısı
    FAIL'i) DEĞİLDİR; runtime kimliğinin KENDİSİ hiç GÖZLEMLENEMEDİ
    (operasyonel/ortam yapılandırma hatası). Bu ikisi KASITLI OLARAK
    ayrılır (section 16) -- gözlemlenemeyen bir kimlik asla sahte bir
    "local"/"unknown"/"development"/boş string değerine düşürülüp bir
    GateCheckResult.FAIL'e dönüştürülmez; bunun yerine bu istisna
    fırlatılır ve çağıran (gelecekteki attempt-execution servisi) bunu
    ayrı bir operasyonel hata olarak ele alır."""


def observe_runtime_fingerprint() -> str:
    """Gerçek ortamdan `K_SERVICE`/`K_REVISION`'ı okur, `app.core.config.
    FIREBASE_PROJECT_ID`'yi (zaten yapılandırılmış) kullanır, ve
    `compute_runtime_fingerprint()` (activation_lock.py'den import edilen,
    TEK string-birleştirme uygulaması) ile kanonik runtime-fingerprint
    string'ini üretir.

    `K_SERVICE`/`K_REVISION` eksikse -- SESSİZCE bir varsayılana
    DÜŞÜLMEZ, `RuntimeIdentityUnobservableError` fırlatılır."""
    service = os.environ.get("K_SERVICE")
    revision = os.environ.get("K_REVISION")

    missing = [name for name, value in (("K_SERVICE", service), ("K_REVISION", revision)) if not value]
    if missing:
        raise RuntimeIdentityUnobservableError(
            f"Runtime kimliği gözlemlenemedi -- eksik ortam değişkeni/değişkenleri: {', '.join(missing)}. "
            "Sahte bir 'local'/'unknown'/'development'/boş string değeri ASLA üretilmez."
        )

    return compute_runtime_fingerprint(FIREBASE_PROJECT_ID, service, revision)

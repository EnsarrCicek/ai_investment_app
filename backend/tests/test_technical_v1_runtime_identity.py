"""HATA 12N3C2-B2-D — `app/research/technical_v1_runtime_identity.py`
testleri. Gerçek Cloud Run/ağ erişimi olmadan -- yalnızca `monkeypatch` ile
enjekte edilen ortam değişkenleri/`FIREBASE_PROJECT_ID` kullanılır."""

import pytest

from app.research import technical_v1_runtime_identity as runtime_identity_module
from app.research.technical_v1_runtime_identity import (
    RuntimeIdentityUnobservableError,
    observe_runtime_fingerprint,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("K_REVISION", raising=False)


def test_observes_fingerprint_from_env_and_configured_project(monkeypatch):
    monkeypatch.setattr(runtime_identity_module, "FIREBASE_PROJECT_ID", "dummy-project-id")
    monkeypatch.setenv("K_SERVICE", "dummy-service")
    monkeypatch.setenv("K_REVISION", "dummy-service-00007-xyz")

    fingerprint = observe_runtime_fingerprint()
    assert fingerprint == "dummy-project-id/dummy-service/dummy-service-00007-xyz"


def test_uses_configured_project_id_exactly_no_normalization(monkeypatch):
    """Section 29: adaptör, verilen `FIREBASE_PROJECT_ID`'yi TAM OLARAK
    kullanır -- büyük/küçük harf/boşluk normalizasyonu YAPMAZ. Bu test,
    kriptografik bir attestation İDDİA ETMEZ -- yalnızca yapılandırılmış
    değerin AYNEN kullanıldığını doğrular."""
    monkeypatch.setattr(runtime_identity_module, "FIREBASE_PROJECT_ID", "Mixed-Case-Project")
    monkeypatch.setenv("K_SERVICE", "svc")
    monkeypatch.setenv("K_REVISION", "rev")

    fingerprint = observe_runtime_fingerprint()
    assert fingerprint == "Mixed-Case-Project/svc/rev"


def test_missing_k_service_fails_loudly(monkeypatch):
    monkeypatch.setattr(runtime_identity_module, "FIREBASE_PROJECT_ID", "dummy-project-id")
    monkeypatch.setenv("K_REVISION", "rev")
    # K_SERVICE bilerek set edilmedi.

    with pytest.raises(RuntimeIdentityUnobservableError):
        observe_runtime_fingerprint()


def test_missing_k_revision_fails_loudly(monkeypatch):
    monkeypatch.setattr(runtime_identity_module, "FIREBASE_PROJECT_ID", "dummy-project-id")
    monkeypatch.setenv("K_SERVICE", "svc")
    # K_REVISION bilerek set edilmedi.

    with pytest.raises(RuntimeIdentityUnobservableError):
        observe_runtime_fingerprint()


def test_missing_both_env_vars_fails_loudly(monkeypatch):
    monkeypatch.setattr(runtime_identity_module, "FIREBASE_PROJECT_ID", "dummy-project-id")
    with pytest.raises(RuntimeIdentityUnobservableError):
        observe_runtime_fingerprint()


def test_empty_k_service_is_treated_as_missing_not_fabricated(monkeypatch):
    """Bos string bir K_SERVICE, sahte bir deger olarak KABUL EDILMEZ --
    eksik ile ayni sekilde ele alinir (section 16: 'local'/'unknown'/
    'development'/bos string ASLA uretilmez)."""
    monkeypatch.setattr(runtime_identity_module, "FIREBASE_PROJECT_ID", "dummy-project-id")
    monkeypatch.setenv("K_SERVICE", "")
    monkeypatch.setenv("K_REVISION", "rev")

    with pytest.raises(RuntimeIdentityUnobservableError):
        observe_runtime_fingerprint()


def test_whitespace_only_k_service_fails_loudly_but_not_silently_accepted(monkeypatch):
    """Yalnizca bosluk iceren bir K_SERVICE "eksik" olarak SAYILMAZ (`not
    value` False doner) ama `compute_runtime_fingerprint()`'in KENDI
    bosluk-doğrulaması bunu reddeder -- her iki yolda da SESSIZCE kabul
    EDILMEZ, yuksek sesle basarisiz olur (farkli istisna tipi olabilir,
    ama asla sahte bir kimlik uretmez)."""
    monkeypatch.setattr(runtime_identity_module, "FIREBASE_PROJECT_ID", "dummy-project-id")
    monkeypatch.setenv("K_SERVICE", " ")
    monkeypatch.setenv("K_REVISION", "rev")

    with pytest.raises(Exception):
        observe_runtime_fingerprint()


def test_missing_env_never_produces_a_fingerprint_string(monkeypatch):
    """K_SERVICE/K_REVISION eksikken, `observe_runtime_fingerprint()`
    HİÇBİR string DÖNDÜRMEZ (bir istisna fırlatır) -- ne gerçek/sahte bir
    fingerprint ne de kısmi bir değer sızar."""
    monkeypatch.setattr(runtime_identity_module, "FIREBASE_PROJECT_ID", "dummy-project-id")
    try:
        result = observe_runtime_fingerprint()
        pytest.fail(f"beklenmedik şekilde bir fingerprint döndü: {result!r}")
    except RuntimeIdentityUnobservableError:
        pass


def test_reuses_compute_runtime_fingerprint_helper_no_duplicate_formatter(monkeypatch):
    """Section 19/30: observed fingerprint, `activation_lock.compute_
    runtime_fingerprint()` ÜZERİNDEN üretilir -- modülün kendi içinde
    ikinci bir `f"{a}/{b}/{c}"` string-birleştirme uygulaması YOKTUR."""
    import inspect

    source = inspect.getsource(runtime_identity_module)
    assert "compute_runtime_fingerprint" in source
    assert 'f"{' not in source  # modülde manuel f-string birlestirme yok

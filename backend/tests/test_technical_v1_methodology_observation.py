"""HATA 12N3C2-B2-D — `app/research/technical_v1_methodology_observation.py`
testleri. Gerçek dosya sistemi taramasını (`compute_methodology_source_
fingerprint()`) tekrar tekrar çalıştırmak yerine `monkeypatch` ile enjekte
edilir (section 31) -- `test_methodology_fingerprint.py` zaten gerçek
27-dosya kümesini kapsıyor."""

import inspect

from app.research import technical_v1_methodology_observation as module
from app.research.technical_v1_methodology_observation import (
    observe_methodology_source_fingerprint,
)


def test_delegates_directly_to_compute_methodology_source_fingerprint(monkeypatch):
    # TECHNICAL V2: normalize_newlines bayrağı değişmeden iletilir (V1 varsayılanı False).
    monkeypatch.setattr(
        module, "compute_methodology_source_fingerprint",
        lambda normalize_newlines=False: ("e" if normalize_newlines else "f") * 64,
    )
    assert observe_methodology_source_fingerprint() == "f" * 64
    assert observe_methodology_source_fingerprint(normalize_newlines=True) == "e" * 64


def test_does_not_duplicate_the_27_file_list_or_hashing_algorithm():
    source = inspect.getsource(module)
    assert "hashlib" not in source
    assert "METHODOLOGY_FINGERPRINT_FILES" not in source
    assert "compute_methodology_source_fingerprint(" in source


def test_real_call_returns_a_canonical_sha256_hex_string():
    """Gercek (monkeypatch'siz) tek bir entegrasyon-duzeyi dogrulama --
    gercek 27-dosya taramasi `test_methodology_fingerprint.py`'de zaten
    kapsamli sekilde test edildigi icin burada YALNIZCA format
    dogrulaniyor, tekrar tekrar cagirilmiyor."""
    fingerprint = observe_methodology_source_fingerprint()
    assert isinstance(fingerprint, str)
    assert len(fingerprint) == 64
    assert all(c in "0123456789abcdef" for c in fingerprint)

"""HATA 12N2A — `app/research/evidence_identity.py` kanonik kimlik
hesaplayıcılarının şema/fail-fast doğrulama testleri (repository/attempt
testlerinde zaten örtük olarak egzersiz edilen golden-ID vektörlerinin
DIŞINDaki, saf giriş-doğrulama davranışı)."""

import pytest

from app.research.evidence_identity import compute_attempt_id, compute_evaluation_id


@pytest.mark.parametrize(
    "malformed_date",
    ["20260909", "2026-9-9", "2026-W37-4", " 2026-09-09", "2026-09-09 ", "2026-09-09T00:00:00"],
)
def test_compute_evaluation_id_rejects_noncanonical_date(malformed_date):
    with pytest.raises(ValueError):
        compute_evaluation_id("TECHNICAL_V1_PROTOCOL_V1", malformed_date, "AKBNK")


def test_compute_evaluation_id_rejects_empty_symbol():
    with pytest.raises(ValueError):
        compute_evaluation_id("TECHNICAL_V1_PROTOCOL_V1", "2026-09-09", "")


def test_compute_evaluation_id_rejects_empty_protocol_version():
    with pytest.raises(ValueError):
        compute_evaluation_id("", "2026-09-09", "AKBNK")


def test_compute_evaluation_id_is_64_lowercase_hex():
    eval_id = compute_evaluation_id("TECHNICAL_V1_PROTOCOL_V1", "2026-09-09", "AKBNK")
    assert len(eval_id) == 64
    assert eval_id == eval_id.lower()
    int(eval_id, 16)  # gecerli hex mi -- degilse ValueError firlatir


@pytest.mark.parametrize("bad_attempt_number", [0, 3, -1, "1", 1.0, None, True, False])
def test_compute_attempt_id_rejects_invalid_attempt_number(bad_attempt_number):
    """`True`/`1.0` özellikle kritik: Python'da `bool` bir `int` alt sınıfıdır
    ve `1.0 == 1`/`True == 1` sayısal eşitliği, saf bir `in (1, 2)` kontrolünü
    SESSİZCE atlatabilir -- kimlik girdisi kesin TİP eşleşmesi ister."""
    eval_id = compute_evaluation_id("TECHNICAL_V1_PROTOCOL_V1", "2026-09-09", "AKBNK")
    with pytest.raises(ValueError):
        compute_attempt_id(eval_id, bad_attempt_number)


def test_compute_attempt_id_rejects_malformed_evaluation_id():
    with pytest.raises(ValueError):
        compute_attempt_id("not-a-valid-hash", 1)


def test_compute_attempt_id_is_64_lowercase_hex():
    eval_id = compute_evaluation_id("TECHNICAL_V1_PROTOCOL_V1", "2026-09-09", "AKBNK")
    attempt_id = compute_attempt_id(eval_id, 1)
    assert len(attempt_id) == 64
    assert attempt_id == attempt_id.lower()
    int(attempt_id, 16)

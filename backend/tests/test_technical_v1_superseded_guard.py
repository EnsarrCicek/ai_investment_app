"""TECH-VOL 1B — Technical V1 SUPERSEDED guard (gerçek çalışan motor, fixture YOK).

Çalışan motor 1.15.0; V1 freeze manifest'i 1.14.0'ı donduruyor. Bu yüzden
V1 kimliğiyle yeni aktivasyon kilidi oluşturulamaz ve V1 attempt'lerinin
beklenen config hash'i yüklenemez — V1 kimliğiyle farklı bir sınıflandırıcı
çıktısı etiketlenemez.
"""

import json
from pathlib import Path

import pytest

from app.engines.technical.engine import ENGINE_VERSION
from app.research.canonical_hash import content_sha256
from app.research.technical_v1_scoring_config_values import (
    TechnicalV1MethodologySupersededError,
    assert_v1_methodology_matches_running_engine,
    load_verified_scoring_config_hash,
)

_RES = Path(__file__).resolve().parents[1] / "app" / "research" / "resources"
_V1 = json.loads((_RES / "technical_v1_freeze_manifest.json").read_text(encoding="utf-8"))


def test_running_engine_differs_from_frozen_v1_methodology():
    assert _V1["methodology_identity"]["engine_version"] == "1.14.0"
    assert ENGINE_VERSION == "1.15.0"


def test_guard_rejects_v1_under_running_engine():
    with pytest.raises(TechnicalV1MethodologySupersededError):
        assert_v1_methodology_matches_running_engine()


def test_verified_v1_loader_is_blocked_after_identity_check():
    with pytest.raises(TechnicalV1MethodologySupersededError):
        load_verified_scoring_config_hash(content_sha256(_V1))


def test_activation_lock_create_fails_before_any_firestore_write():
    from app.repositories.technical_v1_activation_lock_repository import TechnicalV1ActivationLockRepository

    class _ExplodingDb:
        def collection(self, *_a, **_k):
            raise AssertionError("Firestore'a dokunulmamalı")

    repo = TechnicalV1ActivationLockRepository(db=_ExplodingDb())
    with pytest.raises(TechnicalV1MethodologySupersededError):
        repo.create(lock=object())  # guard, kilit içeriğine bakılmadan önce çalışır


def test_guard_passes_when_manifest_matches_running_engine():
    assert_v1_methodology_matches_running_engine({"methodology_identity": {"engine_version": ENGINE_VERSION}})

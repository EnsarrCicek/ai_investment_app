"""HATA 12N3C2-B2-D/B2-D2/B2-D3 — `app/research/technical_v1_scoring_
config_values.py` testleri. Gerçek Firestore erişimi olmadan -- sahte bir
`config_repo` (`get_raw()` sözleşmesine uyan) enjekte edilir; verified
loader testleri gerçek paketlenmiş kanonik manifest'i (fixture DUPLICATE
YOK) ve `tmp_path` altında geçici tamper senaryoları kullanır."""

import inspect
import json
from pathlib import Path

import pytest

from app.engines.technical.scoring import compute_scoring_config_hash
from app.research.canonical_hash import content_sha256
from app.research.evidence_models import EvidenceIntegrityError, ProvenanceConflictError
from app.research.technical_v1_scoring_config_values import (
    _DEFAULT_FREEZE_MANIFEST_PATH,
    compute_observed_scoring_config_hash,
    load_verified_scoring_config_hash,
)

# HATA 12N3C2-B2-D2'de kilitlenen, protokol dosyasında kayıtlı GERÇEK
# değer -- bkz. research/technical_v1_protocol_v1.json ->
# methodology_references.freeze_manifest_sha256.
LOCKED_FREEZE_MANIFEST_SHA256 = "6556f7a9c9b9eedcc4b789c861cc2e1b5b2d4a13be1be75605162f0e578bdc97"

_PROTOCOL_JSON_PATH = Path(__file__).resolve().parents[2] / "research" / "technical_v1_protocol_v1.json"

_VALID_INDICATOR_WEIGHTS = {
    "trend": 1.0,
    "rsi": 1.0,
    "bollinger": 1.0,
    "ema_slope": 1.0,
    "macd": 1.0,
    "momentum": 1.0,
    "roc": 1.0,
}
_VALID_FAMILY_WEIGHTS = {"trend": 1.0, "oscillator_position": 1.0, "momentum_rate": 1.0}


class _FakeConfigRepo:
    def __init__(self, indicator_weights=None, family_weights=None):
        self._indicator_weights = indicator_weights
        self._family_weights = family_weights

    def get_raw(self, config_id: str):
        if config_id == "technical_indicator_weights":
            return self._indicator_weights
        if config_id == "technical_family_weights":
            return self._family_weights
        raise AssertionError(f"beklenmeyen config_id: {config_id}")


# ---------------------------------------------------------------------------
# Paketleme/erişilebilirlik (HATA 12N3C2-B2-D3 section 24/25)
# ---------------------------------------------------------------------------


def test_default_manifest_path_is_inside_backend_app():
    """Kanonik dosya artık `backend/app/` AĞACININ İÇİNDE -- Dockerfile'ın
    `COPY app ./app` adımı EK bir değişiklik olmadan bunu zaten kapsar."""
    resolved = _DEFAULT_FREEZE_MANIFEST_PATH.resolve()
    parts = resolved.parts
    assert "app" in parts
    app_index = parts.index("app")
    # ".../backend/app/research/resources/technical_v1_freeze_manifest.json"
    assert parts[app_index : app_index + 3] == ("app", "research", "resources")
    assert resolved.name == "technical_v1_freeze_manifest.json"


def test_default_manifest_path_does_not_escape_above_app_research_directory():
    """HATA 12N3C2-B2-D3 section 6: repo köküne/backend köküne HİÇ
    çıkılmaz -- dosya bu modülün KENDİ dizininin ("research/") bir alt
    dizini ("resources/") olarak konumlanır."""
    module_dir = Path(
        __import__("app.research.technical_v1_scoring_config_values", fromlist=["x"]).__file__
    ).resolve().parent
    assert _DEFAULT_FREEZE_MANIFEST_PATH.resolve().parent.parent == module_dir


def test_default_manifest_path_exists_at_moved_location():
    assert _DEFAULT_FREEZE_MANIFEST_PATH.exists()


def test_simulated_container_path_matches_expected_shape():
    """HATA 12N3C2-B2-D3 section 25: WORKDIR /app + COPY app ./app
    verildiğinde, container içindeki çözümlenmiş yol TAM OLARAK
    /app/app/research/resources/technical_v1_freeze_manifest.json
    şeklinde olmalı -- kök seviyesinde bir /research/... yolu KALMAMALI."""
    simulated_module_file = Path("/app/app/research/technical_v1_scoring_config_values.py")
    simulated_resolved = simulated_module_file.parent / "resources" / "technical_v1_freeze_manifest.json"
    # PurePosixPath ile platform-bağımsız (Windows'ta calistirilsa bile) dogrulama:
    from pathlib import PurePosixPath

    posix_shape = PurePosixPath("/app/app/research/resources/technical_v1_freeze_manifest.json")
    assert PurePosixPath(*simulated_resolved.parts) == posix_shape or str(simulated_resolved).replace("\\", "/").endswith(
        "/app/app/research/resources/technical_v1_freeze_manifest.json"
    )


def test_current_dockerfile_copies_the_app_tree_containing_the_manifest():
    """Kırılgan bir Dockerfile-syntax parser YAZILMAZ -- yalnızca gerekli
    tek satırın (`COPY app ./app`) var olduğu ve paketlenmiş dosyanın bu
    kopyalanan ağacın (`backend/app/...`) İÇİNDE olduğu doğrulanır."""
    dockerfile_path = Path(__file__).resolve().parents[1] / "Dockerfile"
    dockerfile_text = dockerfile_path.read_text(encoding="utf-8")
    assert "COPY app ./app" in dockerfile_text

    backend_dir = Path(__file__).resolve().parents[1]
    assert _DEFAULT_FREEZE_MANIFEST_PATH.resolve().is_relative_to((backend_dir / "app").resolve())


# ---------------------------------------------------------------------------
# Kilitli tarihsel hash tanımı (HATA 12N3C2-B2-D2)
# ---------------------------------------------------------------------------


def test_current_canonical_manifest_matches_locked_freeze_manifest_sha256():
    with _DEFAULT_FREEZE_MANIFEST_PATH.open(encoding="utf-8") as f:
        parsed = json.load(f)
    assert content_sha256(parsed) == LOCKED_FREEZE_MANIFEST_SHA256


def test_protocol_recorded_hash_matches_current_canonical_manifest():
    """HATA 12N3C2-B2-D3 section 22: gelecekteki bir sürüklenmeye (drift)
    karşı koruma -- protokolün KAYITLI değeri, GERÇEK paketlenmiş
    manifest'in KENDİ hesaplanan hash'iyle HER ZAMAN eşleşmeli."""
    with _PROTOCOL_JSON_PATH.open(encoding="utf-8") as f:
        protocol = json.load(f)
    recorded = protocol["methodology_references"]["freeze_manifest_sha256"]
    assert recorded == LOCKED_FREEZE_MANIFEST_SHA256

    with _DEFAULT_FREEZE_MANIFEST_PATH.open(encoding="utf-8") as f:
        parsed_manifest = json.load(f)
    assert recorded == content_sha256(parsed_manifest)


def test_freeze_manifest_commit_unchanged_by_the_move():
    """HATA 12N3C2-B2-D3 section 23: `freeze_manifest_commit`, dosyayı
    DONDURAN tarihsel commit'i temsil eder -- dosyanın taşındığı (bu
    HATA'nın kendi) commit'e ASLA güncellenmez."""
    with _PROTOCOL_JSON_PATH.open(encoding="utf-8") as f:
        protocol = json.load(f)
    assert protocol["methodology_references"]["freeze_manifest_commit"] == (
        "59497fd5caff00ede177898c04d0de0e1458886b"
    )


# ---------------------------------------------------------------------------
# load_verified_scoring_config_hash -- gerçek kanonik manifest (section 15)
# ---------------------------------------------------------------------------


def test_verified_loader_returns_known_scoring_config_hash_from_real_manifest():
    result = load_verified_scoring_config_hash(LOCKED_FREEZE_MANIFEST_SHA256)
    assert result == "90ba569cf09eb771e6a40de7e5c8a75e3ac97629315c4d59b2607e53a88d9850"


def test_verified_loader_does_not_modify_the_real_manifest_file():
    original_bytes = _DEFAULT_FREEZE_MANIFEST_PATH.read_bytes()
    load_verified_scoring_config_hash(LOCKED_FREEZE_MANIFEST_SHA256)
    assert _DEFAULT_FREEZE_MANIFEST_PATH.read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# Tamper -- sıradan (scoring_config_hash olmayan) bir alan (section 16)
# ---------------------------------------------------------------------------


def test_ordinary_field_tamper_is_rejected_at_manifest_hash_check(tmp_path):
    with _DEFAULT_FREEZE_MANIFEST_PATH.open(encoding="utf-8") as f:
        parsed = json.load(f)
    tampered = dict(parsed)
    tampered["technical_version_name"] = "TAMPERED"
    fixture = tmp_path / "tampered_manifest.json"
    fixture.write_text(json.dumps(tampered), encoding="utf-8")

    # expected hash KASITLI OLARAK ESKİ (gerçek/orijinal) değer olarak kalır.
    with pytest.raises(ProvenanceConflictError):
        load_verified_scoring_config_hash(LOCKED_FREEZE_MANIFEST_SHA256, fixture)


# ---------------------------------------------------------------------------
# Tamper -- scoring_config_hash'in kendisi (section 17)
# ---------------------------------------------------------------------------


def test_scoring_config_hash_tamper_is_rejected_before_being_trusted(tmp_path):
    with _DEFAULT_FREEZE_MANIFEST_PATH.open(encoding="utf-8") as f:
        parsed = json.load(f)
    tampered = json.loads(json.dumps(parsed))  # deep copy
    tampered["methodology_identity"]["scoring_config_hash"] = "f" * 64
    fixture = tmp_path / "tampered_scoring_hash.json"
    fixture.write_text(json.dumps(tampered, indent=4), encoding="utf-8")  # reserialize farklı bicimde

    # expected freeze hash ESKİ (orijinal, artik tutarsiz) deger olarak kalir.
    with pytest.raises(ProvenanceConflictError):
        load_verified_scoring_config_hash(LOCKED_FREEZE_MANIFEST_SHA256, fixture)


# ---------------------------------------------------------------------------
# Yalnızca biçimlendirme değişikliği -- kanonik parsed-JSON semantiği (section 18)
# ---------------------------------------------------------------------------


def test_formatting_only_rewrite_still_passes_with_same_expected_hash(tmp_path):
    with _DEFAULT_FREEZE_MANIFEST_PATH.open(encoding="utf-8") as f:
        parsed = json.load(f)

    # Ayni parsed JSON, FARKLI girinti + FARKLI anahtar sirasi (reversed keys)
    # + Windows-style CRLF satir sonlari ile yeniden yazilir.
    reordered = dict(reversed(list(parsed.items())))
    reformatted_text = json.dumps(reordered, indent=8, sort_keys=False)
    reformatted_text_crlf = reformatted_text.replace("\n", "\r\n") + "\r\n"

    fixture = tmp_path / "reformatted_manifest.json"
    fixture.write_bytes(reformatted_text_crlf.encode("utf-8"))

    result = load_verified_scoring_config_hash(LOCKED_FREEZE_MANIFEST_SHA256, fixture)
    assert result == "90ba569cf09eb771e6a40de7e5c8a75e3ac97629315c4d59b2607e53a88d9850"


# ---------------------------------------------------------------------------
# Malformed expected hash (section 19)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_expected",
    ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "", None, 12345],
    ids=["uppercase", "63_chars", "65_chars", "non_hex", "empty", "none", "not_a_string"],
)
def test_malformed_expected_hash_rejected_before_reading_manifest(bad_expected, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.research.technical_v1_scoring_config_values._read_manifest_json",
        lambda path: calls.append(path) or {},
    )
    with pytest.raises(EvidenceIntegrityError):
        load_verified_scoring_config_hash(bad_expected)
    assert calls == []  # dosyaya HIC dokunulmadi -- format hatasi ONCE yakalandi


# ---------------------------------------------------------------------------
# Malformed manifest / şema (section 20)
# ---------------------------------------------------------------------------


def test_invalid_json_is_rejected(tmp_path):
    fixture = tmp_path / "invalid.json"
    fixture.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ProvenanceConflictError):
        load_verified_scoring_config_hash(LOCKED_FREEZE_MANIFEST_SHA256, fixture)


def test_top_level_list_instead_of_object_is_rejected(tmp_path):
    fixture = tmp_path / "list_manifest.json"
    fixture.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ProvenanceConflictError):
        load_verified_scoring_config_hash(LOCKED_FREEZE_MANIFEST_SHA256, fixture)


def test_missing_methodology_identity_is_rejected(tmp_path):
    payload = {"unrelated": "value"}
    fixture = tmp_path / "missing_identity.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    expected = content_sha256(payload)
    with pytest.raises(ProvenanceConflictError):
        load_verified_scoring_config_hash(expected, fixture)


def test_methodology_identity_not_an_object_is_rejected(tmp_path):
    payload = {"methodology_identity": "not-an-object"}
    fixture = tmp_path / "identity_not_object.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    expected = content_sha256(payload)
    with pytest.raises(ProvenanceConflictError):
        load_verified_scoring_config_hash(expected, fixture)


def test_missing_scoring_config_hash_is_rejected(tmp_path):
    payload = {"methodology_identity": {"methodology_git_commit": "c" * 40}}
    fixture = tmp_path / "missing_scoring_hash.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    expected = content_sha256(payload)
    with pytest.raises(ProvenanceConflictError):
        load_verified_scoring_config_hash(expected, fixture)


@pytest.mark.parametrize(
    "bad_scoring_hash",
    ["A" * 64, "a" * 63, "g" * 64, "", 12345],
    ids=["uppercase", "63_chars", "non_hex", "empty", "not_a_string"],
)
def test_malformed_scoring_config_hash_is_rejected(tmp_path, bad_scoring_hash):
    payload = {"methodology_identity": {"scoring_config_hash": bad_scoring_hash}}
    fixture = tmp_path / "malformed_scoring_hash.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    expected = content_sha256(payload)
    with pytest.raises(ProvenanceConflictError):
        load_verified_scoring_config_hash(expected, fixture)


def test_missing_file_fails_loudly(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(FileNotFoundError):
        load_verified_scoring_config_hash(LOCKED_FREEZE_MANIFEST_SHA256, missing)


# ---------------------------------------------------------------------------
# Yanlış-ama-kendi-içinde-tutarlı manifest (section 21) -- dürüst sınır testi
# ---------------------------------------------------------------------------


def test_tampered_manifest_with_recomputed_matching_hash_passes_loader_alone():
    """Loader TEK BAŞINA bunu bir güvenlik açığı olarak İDDİA ETMEZ --
    yalnızca paketlenmiş baytlar ile çağıranın sağladığı hash arasındaki
    İÇSEL tutarlılığı kanıtlar. Gerçek yetkilendirme `expected_freeze_
    manifest_sha256`'nın BAĞIMSIZ doğrulanmış bir activation lock'tan
    gelmesinden kaynaklanır -- bu test, bu SINIRI dürüstçe belgeler."""
    tampered_payload = {"methodology_identity": {"scoring_config_hash": "9" * 64}}
    attacker_recomputed_hash = content_sha256(tampered_payload)

    # Saldirgan HEM icerigi degistirdi HEM DE kendi (dogru) hash'ini sagladi --
    # loader bunu YAPISAL olarak GECERLI bulur (bu KASITLI, belgelenmis bir sinir,
    # aktivasyon-kilidi yetkilendirmesi OLMADAN bu fonksiyonun kendisi bunu
    # tespit EDEMEZ).
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "self_consistent_tampered.json"
        fixture.write_text(json.dumps(tampered_payload), encoding="utf-8")
        result = load_verified_scoring_config_hash(attacker_recomputed_hash, fixture)
        assert result == "9" * 64  # loader "yetkilendirilmis" SAYAR -- bu dokumante edilen sinirdir


# ---------------------------------------------------------------------------
# Eski, doğrulamasız genel API kaldırıldı (HATA 12N3C2-B2-D3 section 14)
# ---------------------------------------------------------------------------


def test_old_unverified_public_loader_no_longer_exists():
    import app.research.technical_v1_scoring_config_values as module

    assert not hasattr(module, "load_expected_scoring_config_hash")


def test_read_manifest_json_helper_is_private_and_performs_no_verification():
    import app.research.technical_v1_scoring_config_values as module

    assert hasattr(module, "_read_manifest_json")
    source = inspect.getsource(module._read_manifest_json)
    assert "content_sha256" not in source  # kimlik dogrulamasi BURADA YAPILMAZ


def test_module_public_api_exposes_exactly_one_trusted_config_hash_entrypoint():
    import app.research.technical_v1_scoring_config_values as module

    # Yalnizca bu modulde TANIMLANAN (import edilerek yeniden-ihrac edilen
    # bagimliliklar DEGIL) genel, cagrilabilir isimler.
    public_names_defined_here = {
        name
        for name, value in vars(module).items()
        if not name.startswith("_") and callable(value) and getattr(value, "__module__", None) == module.__name__
    }
    config_hash_related = {name for name in public_names_defined_here if "scoring_config_hash" in name.lower()}
    assert config_hash_related == {"load_verified_scoring_config_hash", "compute_observed_scoring_config_hash"}


# ---------------------------------------------------------------------------
# Loader activation-lock repository'sini HİÇ sorgulamaz (section 12)
# ---------------------------------------------------------------------------


def test_module_does_not_import_activation_lock_repository():
    import app.research.technical_v1_scoring_config_values as module

    # Docstring'in KENDISI "bunu import etmez" diye ACIKCA bahsediyor --
    # bu yuzden ham substring degil, GERCEK import ifadelerini kontrol et.
    import_lines = [
        line.strip()
        for line in inspect.getsource(module).splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert not any("activation_lock_repository" in line.lower() for line in import_lines)
    assert not any("TechnicalV1ActivationLockRepository" in line for line in import_lines)
    assert not hasattr(module, "TechnicalV1ActivationLockRepository")


# ---------------------------------------------------------------------------
# compute_observed_scoring_config_hash (DEĞİŞMEDİ -- HATA 12N3C2-B2-D/D2/D3)
# ---------------------------------------------------------------------------


def test_observed_hash_matches_direct_compute_scoring_config_hash_call():
    repo = _FakeConfigRepo(indicator_weights=dict(_VALID_INDICATOR_WEIGHTS), family_weights=dict(_VALID_FAMILY_WEIGHTS))
    observed = compute_observed_scoring_config_hash(repo)

    expected = compute_scoring_config_hash(_VALID_INDICATOR_WEIGHTS, _VALID_FAMILY_WEIGHTS)
    assert observed == expected


def test_observed_hash_changes_when_weights_change():
    repo_a = _FakeConfigRepo(indicator_weights=dict(_VALID_INDICATOR_WEIGHTS), family_weights=dict(_VALID_FAMILY_WEIGHTS))
    changed_weights = dict(_VALID_INDICATOR_WEIGHTS)
    changed_weights["rsi"] = 2.0
    repo_b = _FakeConfigRepo(indicator_weights=changed_weights, family_weights=dict(_VALID_FAMILY_WEIGHTS))

    assert compute_observed_scoring_config_hash(repo_a) != compute_observed_scoring_config_hash(repo_b)


def test_observed_hash_propagates_resolver_fail_fast_on_missing_config():
    """`resolve_indicator_weights(None)` -- config hiç yoksa/eksikse fail-
    fast davranışı (mevcut, ikinci kez YAZILMAYAN mantık) doğrudan
    yansıtılmalı, sessizce bir varsayılana düşülmemeli."""
    repo = _FakeConfigRepo(indicator_weights=None, family_weights=dict(_VALID_FAMILY_WEIGHTS))
    with pytest.raises(Exception):
        compute_observed_scoring_config_hash(repo)


def test_observed_hash_does_not_duplicate_hash_canonicalization():
    """Section 32: gözlemlenen adaptör `compute_scoring_config_hash()`'i
    DOĞRUDAN çağırır -- ikinci bir kanonikleştirme/hash uygulaması YOKTUR."""
    from app.research import technical_v1_scoring_config_values as module

    source = inspect.getsource(module)
    assert "hashlib" not in source
    assert "compute_scoring_config_hash(" in source

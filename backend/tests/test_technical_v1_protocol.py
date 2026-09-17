"""HATA 12N3C2-E1-R1/E1-R2 — `app/research/technical_v1_protocol.py`
testleri. Gerçek Firestore/ağ/canlı-BIST100 erişimi olmadan -- gerçek
paketlenmiş kanonik protokolü (fixture DUPLICATE YOK) ve `tmp_path`
altında geçici tamper/malformed senaryolarını kullanır."""

import inspect
import json
from pathlib import Path

import pytest

from app.research.canonical_hash import content_sha256
from app.research.evidence_models import EvidenceIntegrityError, ProvenanceConflictError
from app.research.technical_v1_protocol import (
    _DEFAULT_PROTOCOL_PATH,
    TrustedTechnicalV1Protocol,
    load_verified_technical_v1_protocol,
)

# HATA 12N3C2-E1-R1'de kilitlenen, TARİHSEL algoritma (content_sha256
# (parsed protocol JSON)) ile TAM olarak yeniden üretilen değer -- bu
# repoda hiçbir zaman bir alan olarak YAZILI OLMADI (bkz. modül docstring'i
# ve E1-R1 raporu), yalnızca GÜNCEL, hiç değiştirilmemiş dosyadan bağımsız
# olarak yeniden hesaplanarak doğrulandı.
LOCKED_PROTOCOL_SHA256 = "ee13afdde2a251bd86fc684e0786f01a9d0b12f7a52ebb2b7771693cb1d38f79"

_KNOWN_FROZEN_MEMBER = "THYAO"


def _load_real_parsed_protocol() -> dict:
    with _DEFAULT_PROTOCOL_PATH.open(encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Paketleme/erişilebilirlik (HATA 12N3C2-E1-R2 section 31/32)
# ---------------------------------------------------------------------------


def test_default_protocol_path_is_inside_backend_app():
    resolved = _DEFAULT_PROTOCOL_PATH.resolve()
    parts = resolved.parts
    assert "app" in parts
    app_index = parts.index("app")
    assert parts[app_index : app_index + 3] == ("app", "research", "resources")
    assert resolved.name == "technical_v1_protocol_v1.json"


def test_default_protocol_path_does_not_escape_above_app_research_directory():
    module_dir = Path(
        __import__("app.research.technical_v1_protocol", fromlist=["x"]).__file__
    ).resolve().parent
    assert _DEFAULT_PROTOCOL_PATH.resolve().parent.parent == module_dir


def test_default_protocol_path_exists_at_moved_location():
    assert _DEFAULT_PROTOCOL_PATH.exists()


def test_current_dockerfile_copies_the_app_tree_containing_the_protocol():
    dockerfile_path = Path(__file__).resolve().parents[1] / "Dockerfile"
    dockerfile_text = dockerfile_path.read_text(encoding="utf-8")
    assert "COPY app ./app" in dockerfile_text

    backend_dir = Path(__file__).resolve().parents[1]
    assert _DEFAULT_PROTOCOL_PATH.resolve().is_relative_to((backend_dir / "app").resolve())


def test_old_root_protocol_file_no_longer_exists():
    """HATA 12N3C2-E1-R2 section 32: `git mv` sonrası eski konumda İKİNCİ
    bir düzenlenebilir kopya KALMAMALI."""
    repo_root = Path(__file__).resolve().parents[2]
    old_path = repo_root / "research" / "technical_v1_protocol_v1.json"
    assert not old_path.exists()


# ---------------------------------------------------------------------------
# Kilitli tarihsel hash tanımı (HATA 12N3C2-E1-R1/E1-R2 section 33)
# ---------------------------------------------------------------------------


def test_current_canonical_protocol_matches_locked_protocol_sha256():
    parsed = _load_real_parsed_protocol()
    assert content_sha256(parsed) == LOCKED_PROTOCOL_SHA256


def test_freeze_manifest_references_unchanged_by_the_move():
    """HATA 12N3C2-E1-R2 section 34: protokolün taşıdığı freeze-manifest
    referansları (KENDİ hash'i DEĞİL, freeze manifest'inki) bu taşımadan
    ETKİLENMEMELİ."""
    parsed = _load_real_parsed_protocol()
    refs = parsed["methodology_references"]
    assert refs["freeze_manifest_sha256"] == "6556f7a9c9b9eedcc4b789c861cc2e1b5b2d4a13be1be75605162f0e578bdc97"
    assert refs["freeze_manifest_commit"] == "59497fd5caff00ede177898c04d0de0e1458886b"


# ---------------------------------------------------------------------------
# load_verified_technical_v1_protocol -- gerçek kanonik artefakt (section 29)
# ---------------------------------------------------------------------------


def test_verified_loader_succeeds_against_real_canonical_artifact():
    result = load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)
    assert isinstance(result, TrustedTechnicalV1Protocol)
    assert result.protocol_sha256 == LOCKED_PROTOCOL_SHA256
    assert result.protocol_version == "TECHNICAL_V1_PROTOCOL_V1"
    assert len(result.frozen_symbol_list) == 100
    assert len(result.frozen_symbols) == 100
    assert _KNOWN_FROZEN_MEMBER in result.frozen_symbols
    assert all("." not in symbol for symbol in result.frozen_symbol_list)


def test_verified_loader_does_not_modify_the_real_protocol_file():
    original_bytes = _DEFAULT_PROTOCOL_PATH.read_bytes()
    load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)
    assert _DEFAULT_PROTOCOL_PATH.read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# Değişmezlik (section 23)
# ---------------------------------------------------------------------------


def test_trusted_protocol_result_is_frozen():
    result = load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)
    with pytest.raises(Exception):
        result.protocol_version = "OTHER"  # type: ignore[misc]


def test_frozen_symbol_list_is_a_tuple():
    result = load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)
    assert isinstance(result.frozen_symbol_list, tuple)
    with pytest.raises(AttributeError):
        result.frozen_symbol_list.append("XXXXX")  # type: ignore[attr-defined]


def test_frozen_symbols_is_a_frozenset():
    result = load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)
    assert isinstance(result.frozen_symbols, frozenset)
    with pytest.raises(AttributeError):
        result.frozen_symbols.add("XXXXX")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Sıra (order) -- section 30
# ---------------------------------------------------------------------------


def test_frozen_symbol_list_preserves_artifact_order():
    result = load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)
    parsed = _load_real_parsed_protocol()
    assert list(result.frozen_symbol_list) == parsed["universe"]["frozen_symbol_list"]


def test_membership_is_order_independent():
    result = load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)
    reversed_set = frozenset(reversed(result.frozen_symbol_list))
    assert reversed_set == result.frozen_symbols
    assert result.frozen_symbols == frozenset(result.frozen_symbol_list)


# ---------------------------------------------------------------------------
# Malformed expected hash (section 11)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_expected",
    ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "", None, 12345],
    ids=["uppercase", "63_chars", "65_chars", "non_hex", "empty", "none", "not_a_string"],
)
def test_malformed_expected_hash_rejected_before_reading_protocol(bad_expected, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.research.technical_v1_protocol._read_protocol_json",
        lambda path: calls.append(path) or {},
    )
    with pytest.raises(EvidenceIntegrityError):
        load_verified_technical_v1_protocol(bad_expected)
    assert calls == []  # dosyaya HIC dokunulmadi


# ---------------------------------------------------------------------------
# Hash tamper -- sıradan bilimsel alan (section 24)
# ---------------------------------------------------------------------------


def test_ordinary_field_tamper_is_rejected_at_protocol_hash_check(tmp_path):
    parsed = _load_real_parsed_protocol()
    tampered = dict(parsed)
    tampered["primary_research_question"] = "TAMPERED"
    fixture = tmp_path / "tampered_protocol.json"
    fixture.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(ProvenanceConflictError):
        load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256, fixture)


# ---------------------------------------------------------------------------
# Hash tamper -- dondurulmuş evren (section 25)
# ---------------------------------------------------------------------------


def test_universe_tamper_is_rejected_at_protocol_hash_check(tmp_path):
    parsed = json.loads(json.dumps(_load_real_parsed_protocol()))  # deep copy
    parsed["universe"]["frozen_symbol_list"][0] = "ZZZZZ"
    fixture = tmp_path / "tampered_universe.json"
    fixture.write_text(json.dumps(parsed), encoding="utf-8")

    with pytest.raises(ProvenanceConflictError):
        load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256, fixture)


# ---------------------------------------------------------------------------
# Yalnızca biçimlendirme değişikliği (section 26)
# ---------------------------------------------------------------------------


def test_formatting_only_rewrite_still_passes_with_same_expected_hash(tmp_path):
    parsed = _load_real_parsed_protocol()

    reordered = dict(reversed(list(parsed.items())))
    reformatted_text = json.dumps(reordered, indent=6, sort_keys=False)
    reformatted_text_crlf = reformatted_text.replace("\n", "\r\n") + "\r\n"

    fixture = tmp_path / "reformatted_protocol.json"
    fixture.write_bytes(reformatted_text_crlf.encode("utf-8"))

    result = load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256, fixture)
    assert result.protocol_version == "TECHNICAL_V1_PROTOCOL_V1"
    assert len(result.frozen_symbols) == 100


# ---------------------------------------------------------------------------
# Yanlış-ama-kendi-içinde-tutarlı sınırı (section 27)
# ---------------------------------------------------------------------------


def test_tampered_protocol_with_recomputed_matching_hash_passes_loader_alone(tmp_path):
    """Loader TEK BAŞINA bunu bir güvenlik açığı olarak İDDİA ETMEZ --
    yalnızca paketlenmiş baytlar ile çağıranın sağladığı hash arasındaki
    İÇSEL tutarlılığı kanıtlar. Gerçek yetkilendirme, `expected_protocol_
    sha256`'nın BAĞIMSIZ doğrulanmış bir activation lock'tan gelmesinden
    kaynaklanır."""
    parsed = json.loads(json.dumps(_load_real_parsed_protocol()))
    parsed["primary_research_question"] = "COMPLETELY DIFFERENT QUESTION"
    attacker_recomputed_hash = content_sha256(parsed)

    fixture = tmp_path / "self_consistent_tampered_protocol.json"
    fixture.write_text(json.dumps(parsed), encoding="utf-8")

    result = load_verified_technical_v1_protocol(attacker_recomputed_hash, fixture)
    assert result.protocol_version == "TECHNICAL_V1_PROTOCOL_V1"  # loader "yetkilendirilmis" SAYAR


# ---------------------------------------------------------------------------
# Yapısal malformed testler (section 28)
# ---------------------------------------------------------------------------


def _write_and_load(tmp_path: Path, payload) -> None:
    fixture = tmp_path / "malformed.json"
    if isinstance(payload, str):
        fixture.write_text(payload, encoding="utf-8")
        expected = LOCKED_PROTOCOL_SHA256
    else:
        fixture.write_text(json.dumps(payload), encoding="utf-8")
        expected = content_sha256(payload)
    load_verified_technical_v1_protocol(expected, fixture)


def test_invalid_json_is_rejected(tmp_path):
    fixture = tmp_path / "invalid.json"
    fixture.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ProvenanceConflictError):
        load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256, fixture)


def test_top_level_list_instead_of_object_is_rejected(tmp_path):
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, [1, 2, 3])


def test_missing_protocol_version_is_rejected(tmp_path):
    payload = {"universe": {"frozen_symbol_list": [f"SYM{i:03d}" for i in range(100)]}}
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


@pytest.mark.parametrize(
    "bad_version",
    ["", " TECHNICAL_V1_PROTOCOL_V1", "TECHNICAL_V1_PROTOCOL_V1 ", 12345, None],
    ids=["empty", "leading_ws", "trailing_ws", "not_a_string", "none"],
)
def test_malformed_protocol_version_is_rejected(tmp_path, bad_version):
    payload = {
        "protocol_version": bad_version,
        "universe": {"frozen_symbol_list": [f"SYM{i:03d}" for i in range(100)]},
    }
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


def test_missing_universe_object_is_rejected(tmp_path):
    payload = {"protocol_version": "X"}
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


def test_universe_not_an_object_is_rejected(tmp_path):
    payload = {"protocol_version": "X", "universe": "not-an-object"}
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


def test_missing_frozen_symbol_list_is_rejected(tmp_path):
    payload = {"protocol_version": "X", "universe": {}}
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


def test_frozen_symbol_list_not_a_list_is_rejected(tmp_path):
    payload = {"protocol_version": "X", "universe": {"frozen_symbol_list": "not-a-list"}}
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


def test_99_symbols_is_rejected(tmp_path):
    payload = {"protocol_version": "X", "universe": {"frozen_symbol_list": [f"SYM{i:03d}" for i in range(99)]}}
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


def test_101_symbols_is_rejected(tmp_path):
    payload = {"protocol_version": "X", "universe": {"frozen_symbol_list": [f"SYM{i:03d}" for i in range(101)]}}
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


def test_duplicate_symbol_is_rejected(tmp_path):
    symbols = [f"SYM{i:03d}" for i in range(99)] + ["SYM000"]
    payload = {"protocol_version": "X", "universe": {"frozen_symbol_list": symbols}}
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


def test_lowercase_symbol_is_rejected(tmp_path):
    symbols = [f"SYM{i:03d}" for i in range(99)] + ["thyao"]
    payload = {"protocol_version": "X", "universe": {"frozen_symbol_list": symbols}}
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


def test_whitespace_padded_symbol_is_rejected(tmp_path):
    symbols = [f"SYM{i:03d}" for i in range(99)] + [" THYAO"]
    payload = {"protocol_version": "X", "universe": {"frozen_symbol_list": symbols}}
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


def test_dot_is_suffix_symbol_is_rejected(tmp_path):
    symbols = [f"SYM{i:03d}" for i in range(99)] + ["THYAO.IS"]
    payload = {"protocol_version": "X", "universe": {"frozen_symbol_list": symbols}}
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


def test_non_string_symbol_is_rejected(tmp_path):
    symbols = [f"SYM{i:03d}" for i in range(99)] + [12345]
    payload = {"protocol_version": "X", "universe": {"frozen_symbol_list": symbols}}
    with pytest.raises(ProvenanceConflictError):
        _write_and_load(tmp_path, payload)


def test_missing_file_fails_loudly(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(FileNotFoundError):
        load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256, missing)


# ---------------------------------------------------------------------------
# Section 21 -- opsiyonel saklanan sayım çapraz-kontrolü
# ---------------------------------------------------------------------------


def test_constituent_count_mismatch_is_rejected(tmp_path):
    parsed = json.loads(json.dumps(_load_real_parsed_protocol()))
    parsed["universe"]["constituent_count"] = 99
    fixture = tmp_path / "wrong_constituent_count.json"
    fixture.write_text(json.dumps(parsed), encoding="utf-8")
    expected = content_sha256(parsed)

    with pytest.raises(ProvenanceConflictError):
        load_verified_technical_v1_protocol(expected, fixture)


def test_unique_ticker_count_mismatch_is_rejected(tmp_path):
    parsed = json.loads(json.dumps(_load_real_parsed_protocol()))
    parsed["universe"]["unique_ticker_count"] = 42
    fixture = tmp_path / "wrong_unique_count.json"
    fixture.write_text(json.dumps(parsed), encoding="utf-8")
    expected = content_sha256(parsed)

    with pytest.raises(ProvenanceConflictError):
        load_verified_technical_v1_protocol(expected, fixture)


def test_no_stored_count_fields_does_not_block_loading(tmp_path):
    """Section 21: alanlar YOKSA İCAT EDİLMEZ -- yalnızca VARSA
    doğrulanır. Bunlar olmadan da geçerli bir 100-sembol listesi kabul
    edilmelidir."""
    payload = {
        "protocol_version": "X",
        "universe": {"frozen_symbol_list": [f"SYM{i:03d}" for i in range(100)]},
    }
    expected = content_sha256(payload)
    fixture = tmp_path / "no_count_fields.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")

    result = load_verified_technical_v1_protocol(expected, fixture)
    assert len(result.frozen_symbols) == 100


# ---------------------------------------------------------------------------
# Firestore/ağ/canlı-BIST100 hiç sorgulanmaz (section 22)
# ---------------------------------------------------------------------------


def test_module_never_imports_activation_lock_repository_or_network():
    import app.research.technical_v1_protocol as module

    import_lines = [
        line.strip()
        for line in inspect.getsource(module).splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert not any("firestore" in line.lower() for line in import_lines)
    assert not any("activation_lock_repository" in line.lower() for line in import_lines)
    assert not any(name in line for line in import_lines for name in ("requests", "httpx", "yfinance"))


def test_old_unverified_public_loader_does_not_exist():
    import app.research.technical_v1_protocol as module

    assert not hasattr(module, "load_protocol")
    assert not hasattr(module, "load_expected_protocol")


def test_read_protocol_json_helper_is_private_and_performs_no_verification():
    import app.research.technical_v1_protocol as module

    assert hasattr(module, "_read_protocol_json")
    source = inspect.getsource(module._read_protocol_json)
    assert "content_sha256" not in source

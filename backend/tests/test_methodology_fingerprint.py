"""HATA 12L/12M — metodoloji dosya-parmak-izi testleri.

Kapsam: `app/research/methodology_fingerprint.py`'nin 27 dosyalik, benzersiz,
gercekte VAR OLAN listesi; hash-stability (tekrarlanan hesaplama -> ayni
sonuc) ve hash-sensitivity (herhangi bir dosyanin tek bir bayti degisirse ->
farkli sonuc, GECICI bir fixture uzerinden -- gercek repo dosyalari
DEGISTIRILMEZ).
"""

from app.research.methodology_fingerprint import (
    EXPECTED_FILE_COUNT,
    METHODOLOGY_FINGERPRINT_FILES,
    TECHNICAL_COMPUTATION_FILES,
    TECHNICAL_CONFIG_RESOLUTION_FILES,
    TECHNICAL_INPUT_CONTRACT_FILES,
    TECHNICAL_MODEL_SCHEMA_FILES,
    compute_file_hashes,
    compute_methodology_source_fingerprint,
)


def test_file_list_has_exactly_27_unique_entries():
    assert len(METHODOLOGY_FINGERPRINT_FILES) == 27 == EXPECTED_FILE_COUNT
    assert len(set(METHODOLOGY_FINGERPRINT_FILES)) == 27


def test_group_counts_match_hata_12l_locked_breakdown():
    assert len(TECHNICAL_COMPUTATION_FILES) == 16
    assert len(TECHNICAL_INPUT_CONTRACT_FILES) == 9
    assert len(TECHNICAL_MODEL_SCHEMA_FILES) == 1
    assert len(TECHNICAL_CONFIG_RESOLUTION_FILES) == 1


def test_technical_analysis_repository_is_deliberately_excluded():
    # HATA 12L: bu dosya yalnizca cache/persistence katmanidir, fresh-compute
    # degerlerini asla etkilemez -- listede OLMAMALI.
    assert not any("technical_analysis_repository" in path for path in METHODOLOGY_FINGERPRINT_FILES)


def test_all_methodology_files_exist_and_hash_without_error():
    hashes = compute_file_hashes()
    assert len(hashes) == 27
    assert all(len(h) == 64 for h in hashes.values())


def test_methodology_source_fingerprint_is_stable_across_repeated_computation():
    first = compute_methodology_source_fingerprint()
    second = compute_methodology_source_fingerprint()
    assert first == second
    assert len(first) == 64


def test_methodology_source_fingerprint_sensitive_to_one_byte_change(tmp_path):
    # Gercek repo dosyalarina DOKUNULMAZ -- gecici, sahte bir iki-dosyalik
    # "metodoloji" fixture'i kurulur.
    file_a = tmp_path / "a.py"
    file_b = tmp_path / "b.py"
    file_a.write_text("original content a\n", encoding="utf-8")
    file_b.write_text("original content b\n", encoding="utf-8")

    relative_paths = ("a.py", "b.py")
    baseline = compute_methodology_source_fingerprint(relative_paths, root=tmp_path)

    file_a.write_text("original content a!\n", encoding="utf-8")  # tek karakter fark
    mutated = compute_methodology_source_fingerprint(relative_paths, root=tmp_path)

    assert baseline != mutated


def test_compute_file_hashes_raises_on_missing_file(tmp_path):
    (tmp_path / "present.py").write_text("x = 1\n", encoding="utf-8")
    import pytest

    with pytest.raises(FileNotFoundError):
        compute_file_hashes(("present.py", "absent.py"), root=tmp_path)

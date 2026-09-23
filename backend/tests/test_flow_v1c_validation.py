"""FLOW 1C — CMFScore, negatif filtre eşiği, dış evren ayrıklığı, 10 offset,
Technical-kör koruması. Ağ yok; sentetik girdiler."""

import json
import math

import numpy as np
import pandas as pd
import pytest

from app.research.canonical_hash import content_sha256
from app.research.flow_v1.dataset import load_frozen_universe
from app.research.flow_v1.study import TechnicalBlindViolation
from app.research.flow_v1c import study as s1c
from app.research.flow_v1c.universe import (
    UNIVERSE_FILE,
    build_external_universe,
    load_external_universe,
    parse_sections,
    select_bist_tum,
)


# ---------------------------------------------------------------- CMFScore / filter


def test_cmf_score_mapping_and_clamp():
    cmf = pd.Series([0.25, -0.25, 0.5, -1.0, 0.0, 0.125, np.nan])
    out = s1c.cmf_score(cmf)
    assert out.iloc[:6].tolist() == pytest.approx([100.0, -100.0, 100.0, -100.0, 0.0, 50.0])
    assert math.isnan(out.iloc[6])


def test_negative_threshold_boundary_is_rejected():
    scores = s1c.cmf_score(pd.Series([-0.05, -0.0499, -0.0501, np.nan]))
    assert scores.iloc[0] == pytest.approx(-20.0)
    assert s1c.is_rejected(scores).tolist() == [True, False, True, False]
    assert s1c.is_rejected(pd.Series([-20.0])).iloc[0]


def test_protocol_threshold_constants_match_protocol_file():
    protocol, _ = s1c.load_protocol()
    assert "CMFScore <= -20" in protocol["candidate"]["negative_filter"]
    assert s1c.NEG_THRESHOLD == -20.0 and s1c.CMF_SCALE == 0.25 and s1c.PRIMARY_H == 10
    assert s1c.CO_PRIMARY_CI == 97.5


# ---------------------------------------------------------------- universe


def _pdf_text():
    lines = ["BIST 100", "Sıra Kod Şirket Unvanı", "1 AAA A A.Ş.", "2 BBB B A.Ş.",
             "BIST TÜM", "Sıra Kod Şirket Unvanı", "1 AAA A A.Ş.", "2 BBB B A.Ş.", "3 CCC C A.Ş.", "4 DDD D A.Ş.",
             "BIST TÜM-100", "Sıra Kod Şirket Unvanı", "1 CCC C A.Ş."]
    return "\n".join(lines)


def test_parse_and_select_bist_tum_requires_superset_of_bist100():
    sections = parse_sections(_pdf_text().replace("BIST 100\n", "BIST 100\n"))
    # sentetik BIST 100 bölümü 100 kayıt değil -> seçim reddetmeli (şüpheli ayrıştırma)
    with pytest.raises(ValueError):
        select_bist_tum(sections)


def test_external_universe_excludes_discovery_and_has_no_overlap():
    external = build_external_universe(["AAA", "BBB", "CCC", "DDD", "CCC"], ["AAA", "BBB"])
    assert external == ["CCC", "DDD"]
    assert not set(external) & {"AAA", "BBB"}


def test_committed_external_universe_is_disjoint_from_frozen_100():
    symbols, artifact = load_external_universe()
    discovery, _ = load_frozen_universe()
    assert len(symbols) == artifact["external_count"] == 484
    assert len(set(symbols)) == len(symbols)
    assert set(symbols).isdisjoint(discovery)
    assert artifact["overlap_with_discovery"] == 0
    assert content_sha256(symbols) == artifact["external_symbols_sha256"]


def test_tampered_universe_is_rejected(tmp_path, monkeypatch):
    artifact = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
    discovery, _ = load_frozen_universe()
    artifact["external_symbols"] = artifact["external_symbols"] + [discovery[0]]
    bad = tmp_path / "u.json"
    bad.write_text(json.dumps(artifact), encoding="utf-8")
    monkeypatch.setattr("app.research.flow_v1c.universe.UNIVERSE_FILE", bad)
    with pytest.raises(ValueError):
        load_external_universe()


# ---------------------------------------------------------------- offsets


def test_enumerate_offsets_covers_all_ten_and_partitions_dates():
    dates = list(range(95))
    offsets = s1c.enumerate_offsets(dates)
    assert sorted(offsets) == list(range(10))
    flat = sorted(d for ds in offsets.values() for d in ds)
    assert flat == dates
    assert offsets[3][:3] == [3, 13, 23]


def test_summarize_offsets_reports_every_offset_and_no_best_pick():
    per = {o: float(o - 4) for o in range(10)}
    summary = s1c.summarize_offsets(per)
    assert summary["offsets_reported"] == list(range(10))
    assert summary["values"] == [float(o - 4) for o in range(10)]
    assert summary["n_positive"] == 5 and summary["n_offsets"] == 10
    assert summary["min"] == -4.0 and summary["max"] == 5.0
    assert not any("best" in k for k in summary)


def test_filter_offset_study_runs_all_offsets_on_synthetic_rows():
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    rng = np.random.default_rng(0)
    rows = pd.DataFrame({
        "improvement": rng.normal(0, 0.01, 40), "rejected_minus_passed": rng.normal(-0.01, 0.01, 40),
        "passed_names": [frozenset({"A", "B"})] * 40, "all_names": [frozenset({"A", "B", "C"})] * 40,
        "_passed_mean": rng.normal(0, 0.01, 40), "_all_mean": rng.normal(0, 0.01, 40),
        "n_all": 3, "n_rejected": 1,
    }, index=idx)
    out = s1c.filter_offset_study(rows)
    assert sorted(out["per_offset"], key=int) == [str(o) for o in range(10)]
    assert out["across_offsets"]["net_improvement_20bps"]["n_offsets"] == 10
    s1c.assert_technical_blind_1c(out)


# ---------------------------------------------------------------- labels / blind


def test_co_primary_labels():
    assert s1c.label_p1({"ci_low": 0.001, "ci_high": 0.05}) == "SUPPORTED"
    assert s1c.label_p1({"ci_low": -0.01, "ci_high": 0.015}) == "NOT_SUPPORTED"
    assert s1c.label_p1({"ci_low": -0.01, "ci_high": 0.04}) == "INCONCLUSIVE"
    assert s1c.label_p2({"ci_low": -0.02, "ci_high": -0.001}) == "SUPPORTED"
    assert s1c.label_p2({"ci_low": -0.003, "ci_high": 0.01}) == "NOT_SUPPORTED"
    assert s1c.label_p2({"ci_low": -0.02, "ci_high": 0.01}) == "INCONCLUSIVE"


def test_technical_blind_guard_1c_rejects_level_keys():
    s1c.assert_technical_blind_1c({"P2": {"return_delta": {"mean": -0.01}}})
    for key in ("technical_ic", "unfiltered_return", "all_candidates_return", "technical_positive_return"):
        with pytest.raises(TechnicalBlindViolation):
            s1c.assert_technical_blind_1c({"x": {key: 0.01}})

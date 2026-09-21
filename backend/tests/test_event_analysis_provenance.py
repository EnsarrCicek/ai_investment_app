"""HATA 15D — EventIntelligenceEngine LLM reproducibility/provenance testleri.

Kapsam: her yeni NewsAnalysis'in, LLM'e GERÇEKTEN gönderilen metnin exact
snapshot'ını + SHA-256 hash'ini + prompt/schema versiyon etiketlerini + o
çağrıda gerçekten invoke edilen modeli taşıdığını, canlı sayfa daha sonra
değişse bile geçmiş provenance'ın MUTASYONA UĞRAMADIĞINI, ve geçersiz LLM
çıktısının hiçbir (tam veya kısmi) NewsAnalysis persist ETMEDİĞİNİ kanıtlar.

HATA 15B/15C skorlama davranışına (dedup, last-10-unique, source-reliability
weighting) bu ticket'ta DOKUNULMUYOR — regresyon testi bunu ayrıca kilitler.
"""

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.engines.decision.engine import _WeightedNewsAnalysis, _aggregate_news_score
from app.engines.event_intelligence import engine as engine_module
from app.engines.event_intelligence.engine import (
    EVENT_INTELLIGENCE_OUTPUT_SCHEMA_VERSION,
    EVENT_INTELLIGENCE_PROMPT_VERSION,
    EventIntelligenceEngine,
    _sha256_hex,
)
from app.models.news_analysis import NewsAnalysis
from app.models.news_raw import NewsRawItem


@pytest.fixture(autouse=True)
def _no_real_article_fetch(monkeypatch):
    monkeypatch.setattr(engine_module, "fetch_article_text", lambda url, **kwargs: "")


class _FakeCompletions:
    def __init__(self, response_json_or_raw, usage: SimpleNamespace | None = None):
        self._response = response_json_or_raw
        self.usage = usage or SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._response, str):
            content = self._response
        else:
            content = json.dumps(self._response)
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice], usage=self.usage)


class _FakeOpenAIClient:
    def __init__(self, response_json_or_raw, usage: SimpleNamespace | None = None):
        self.completions = _FakeCompletions(response_json_or_raw, usage=usage)
        self.chat = SimpleNamespace(completions=self.completions)


class _FakeAnalysisRepo:
    def __init__(self):
        self.added: list[NewsAnalysis] = []

    def add(self, analysis):
        self.added.append(analysis)
        return "fake-id"

    def get_by_news_id(self, news_id, asset):
        return None


class _FakeNewsRepo:
    def __init__(self, items):
        self._items = items

    def get_recent(self, symbol, limit=20):
        return self._items[:limit]


class _FakeUsageRepo:
    def __init__(self):
        self.added: list = []

    def add(self, log):
        self.added.append(log)
        return "fake-usage-id"


def _news_item(external_id="n1", title="Şirket rekor kâr açıkladı", summary="Detaylı özet burada."):
    now = datetime.now(timezone.utc)
    return NewsRawItem(
        external_id=external_id,
        title=title,
        summary=summary,
        url="https://example.com",
        publisher="Test Publisher",
        source="yahoo_finance",
        source_reliability=0.8,
        related_assets=["THYAO"],
        published_at=now,
        received_at=now,
    )


_VALID_RESPONSE = {
    "sentiment_score": 62.5,
    "confidence": 0.8,
    "importance": 0.6,
    "event_type": "earnings",
    "time_horizon": "medium_term",
    "reasoning": "Kâr beklentilerin üzerinde geldi.",
}


def _engine(client, repo=None, news_items=None):
    return EventIntelligenceEngine(
        client=client,
        analysis_repo=repo or _FakeAnalysisRepo(),
        news_repo=_FakeNewsRepo(news_items or []),
        usage_repo=_FakeUsageRepo(),
        primary_model="m",
    )


# ---- Bölüm 16: missing-body — sadece başlık+özet ----------------------------


def test_analyzed_text_snapshot_and_hash_exact_for_headline_and_summary_only():
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = _engine(client)

    result = engine.analyze_item(_news_item(), "THYAO")

    expected_text = "Varlık: THYAO\nBaşlık: Şirket rekor kâr açıkladı\nÖzet: Detaylı özet burada."
    assert result.analyzed_text == expected_text
    assert result.analyzed_text_sha256 == hashlib.sha256(expected_text.encode("utf-8")).hexdigest()


# ---- Bölüm 17: full body — gerçek makale metni mevcut ------------------------


def test_analyzed_text_snapshot_and_hash_exact_when_article_body_fetched(monkeypatch):
    monkeypatch.setattr(
        engine_module,
        "fetch_article_text",
        lambda url, **kwargs: "THYAO icin analistler hedef fiyati yukseltti.",
    )
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = _engine(client)

    result = engine.analyze_item(_news_item(), "THYAO")

    expected_text = (
        "Varlık: THYAO\nBaşlık: Şirket rekor kâr açıkladı\nÖzet: Detaylı özet burada.\n"
        "Makale Metni: THYAO icin analistler hedef fiyati yukseltti."
    )
    assert result.analyzed_text == expected_text
    assert result.analyzed_text_sha256 == hashlib.sha256(expected_text.encode("utf-8")).hexdigest()


# ---- Bölüm 18: canlı makale sonradan değişse de geçmiş provenance sabit ----


def test_live_article_change_after_persist_does_not_mutate_historical_provenance(monkeypatch):
    monkeypatch.setattr(engine_module, "fetch_article_text", lambda url, **kwargs: "VERSION A metni.")
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    repo = _FakeAnalysisRepo()
    engine = _engine(client, repo=repo)

    first = engine.analyze_item(_news_item(external_id="n1"), "THYAO")
    assert "VERSION A" in first.analyzed_text

    # Canlı sayfa artık farklı bir içerik döndürüyor.
    monkeypatch.setattr(engine_module, "fetch_article_text", lambda url, **kwargs: "VERSION B metni.")
    second = engine.analyze_item(_news_item(external_id="n2"), "THYAO")
    assert "VERSION B" in second.analyzed_text

    # İlk (geçmiş) kayıt, ikinci çağrıdan HİÇBİR şekilde etkilenmemiş —
    # repo.added[0] hâlâ orijinal VERSION A snapshot/hash'ini taşıyor.
    assert repo.added[0] is first
    assert "VERSION A" in repo.added[0].analyzed_text
    assert repo.added[0].analyzed_text_sha256 == hashlib.sha256(first.analyzed_text.encode("utf-8")).hexdigest()


# ---- Bölüm 19: hash kararlılığı --------------------------------------------


def test_sha256_hex_stable_for_identical_input_and_changes_with_one_character():
    text = "Varlık: THYAO\nBaşlık: Test"
    assert _sha256_hex(text) == _sha256_hex(text)

    changed = text + "!"
    assert _sha256_hex(changed) != _sha256_hex(text)


def test_sha256_hex_is_not_python_builtin_hash():
    # `hash()` süreçler arası kararlı DEĞİLDİR (PYTHONHASHSEED); üretilen
    # değer 64 karakterlik hex olmalı, kısa bir int-repr olamaz.
    digest = _sha256_hex("örnek metin")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


# ---- Bölüm 20-22: prompt/schema versiyonu ----------------------------------


def test_prompt_version_persisted_on_every_new_record():
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = _engine(client)

    result = engine.analyze_item(_news_item(), "THYAO")

    assert result.prompt_version == EVENT_INTELLIGENCE_PROMPT_VERSION
    assert result.prompt_version == "event_intelligence_v1"


def test_prompt_version_reflects_module_constant_not_a_disconnected_literal(monkeypatch):
    monkeypatch.setattr(engine_module, "EVENT_INTELLIGENCE_PROMPT_VERSION", "event_intelligence_v2_test")
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = _engine(client)

    result = engine.analyze_item(_news_item(), "THYAO")

    assert result.prompt_version == "event_intelligence_v2_test"


def test_output_schema_version_persisted_explicitly_not_omitted():
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = _engine(client)

    result = engine.analyze_item(_news_item(), "THYAO")

    assert result.output_schema_version == EVENT_INTELLIGENCE_OUTPUT_SCHEMA_VERSION
    assert result.output_schema_version is not None


def test_prompt_sha256_persisted_and_is_valid_hex_digest():
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = _engine(client)

    result = engine.analyze_item(_news_item(), "THYAO")

    assert result.prompt_sha256 is not None
    assert len(result.prompt_sha256) == 64


# ---- Bölüm 23: gerçekten invoke edilen model -------------------------------


def test_persisted_model_used_matches_actual_invoked_model_kwarg():
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = EventIntelligenceEngine(
        client=client,
        analysis_repo=_FakeAnalysisRepo(),
        news_repo=_FakeNewsRepo([]),
        usage_repo=_FakeUsageRepo(),
        primary_model="actually-invoked-model-xyz",
    )

    result = engine.analyze_item(_news_item(), "THYAO")

    assert client.completions.calls[0]["model"] == "actually-invoked-model-xyz"
    assert result.model_used == "actually-invoked-model-xyz"
    # Not (rigor check B / bölüm 32): bu sürümde _should_escalate() hiç
    # çağrılmıyor (bkz. engine.py modül docstring'i) — gerçek bir fallback/
    # invoked-model ayrımı test edilebilir DEĞİL; burada N/A olarak
    # belgeleniyor, sahte bir fallback yolu İCAT EDİLMEDİ.


# ---- Bölüm 10: determinism ayarları gerçekten gönderiliyor -----------------


def test_temperature_and_seed_sent_to_client_for_determinism():
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = _engine(client)

    engine.analyze_item(_news_item(), "THYAO")

    call = client.completions.calls[0]
    assert call["temperature"] == 0.0
    assert call["seed"] == 0
    # Not: OpenAI'nin kendi dokümantasyonu `seed`'i "best-effort" olarak
    # tanımlıyor — bu, bitwise-deterministik bir GARANTİ değildir (bkz.
    # engine.py modül-seviyesi yorum, bölüm 10). Bu test yalnızca en
    # deterministik DESTEKLENEN parametrelerin gerçekten GÖNDERİLDİĞİNİ
    # kanıtlar, mutlak determinizmi İDDİA ETMEZ.


# ---- Bölüm 24: geçersiz LLM çıktısı hiçbir kayıt persist etmez -------------


def test_invalid_json_llm_output_does_not_persist_any_analysis():
    client = _FakeOpenAIClient("{not valid json")
    repo = _FakeAnalysisRepo()
    engine = _engine(client, repo=repo)

    with pytest.raises(json.JSONDecodeError):
        engine.analyze_item(_news_item(), "THYAO")

    assert repo.added == []


def test_schema_invalid_llm_output_does_not_persist_any_analysis():
    # `event_type` şema dışı bir değer + `sentiment_score` eksik.
    invalid = {**_VALID_RESPONSE, "event_type": "not_a_real_category"}
    del invalid["sentiment_score"]
    client = _FakeOpenAIClient(invalid)
    repo = _FakeAnalysisRepo()
    engine = _engine(client, repo=repo)

    with pytest.raises(Exception):
        engine.analyze_item(_news_item(), "THYAO")

    assert repo.added == []


# ---- Bölüm 26-27: legacy kayıt uyumluluğu + model validasyonu ---------------


def test_legacy_record_without_provenance_fields_reads_safely():
    legacy = NewsAnalysis(
        news_id="legacy1",
        asset="THYAO",
        sentiment_score=10.0,
        confidence=0.9,
        importance=0.2,
        event_type="other",
        reasoning="Provenance eklenmeden önce üretilmiş.",
        model_used="gpt-5.6-luna",
        created_at=datetime.now(timezone.utc),
    )
    assert legacy.analyzed_text is None
    assert legacy.analyzed_text_sha256 is None
    assert legacy.prompt_version is None
    assert legacy.prompt_sha256 is None
    assert legacy.output_schema_version is None


def test_invalid_sha256_format_rejected():
    with pytest.raises(Exception):
        NewsAnalysis(
            news_id="n",
            asset="THYAO",
            sentiment_score=0.0,
            confidence=0.5,
            importance=0.5,
            event_type="other",
            reasoning="r",
            model_used="m",
            created_at=datetime.now(timezone.utc),
            analyzed_text_sha256="not-a-valid-hash",
        )


def test_empty_prompt_version_rejected():
    with pytest.raises(Exception):
        NewsAnalysis(
            news_id="n",
            asset="THYAO",
            sentiment_score=0.0,
            confidence=0.5,
            importance=0.5,
            event_type="other",
            reasoning="r",
            model_used="m",
            created_at=datetime.now(timezone.utc),
            prompt_version="   ",
        )


# ---- Bölüm 29: DecisionEngine skorlaması değişmedi --------------------------


def test_decision_engine_score_unaffected_by_new_provenance_fields():
    base_kwargs = dict(
        asset="THYAO",
        confidence=1.0,
        importance=0.5,
        event_type="other",
        time_horizon="medium_term",
        reasoning="r",
        model_used="m",
        created_at=datetime.now(timezone.utc),
    )
    without_provenance = NewsAnalysis(news_id="a", sentiment_score=50.0, **base_kwargs)
    with_provenance = NewsAnalysis(
        news_id="a",
        sentiment_score=50.0,
        analyzed_text="metin",
        analyzed_text_sha256=_sha256_hex("metin"),
        prompt_version="event_intelligence_v1",
        prompt_sha256=_sha256_hex("prompt"),
        output_schema_version="event_intelligence_output_v1",
        **base_kwargs,
    )

    score_without = _aggregate_news_score(
        [_WeightedNewsAnalysis(analysis=without_provenance, source_reliability=0.9)]
    )
    score_with = _aggregate_news_score(
        [_WeightedNewsAnalysis(analysis=with_provenance, source_reliability=0.9)]
    )

    assert score_without == score_with

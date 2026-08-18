import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.engines.event_intelligence.engine import (
    HIGH_IMPORTANCE_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
    EventIntelligenceEngine,
    _should_escalate,
)
from app.models.news_analysis import NewsAnalysis
from app.models.news_raw import NewsRawItem


class _FakeCompletions:
    def __init__(self, response_json: dict):
        self.response_json = response_json
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=json.dumps(self.response_json))
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class _FakeOpenAIClient:
    def __init__(self, response_json: dict):
        self.completions = _FakeCompletions(response_json)
        self.chat = SimpleNamespace(completions=self.completions)


class _FakeAnalysisRepo:
    def __init__(self, existing: dict[str, NewsAnalysis] | None = None):
        self._existing = existing or {}
        self.added: list[NewsAnalysis] = []

    def add(self, analysis):
        self.added.append(analysis)
        return "fake-id"

    def get_by_news_id(self, news_id):
        return self._existing.get(news_id)


class _FakeNewsRepo:
    def __init__(self, items: list[NewsRawItem]):
        self._items = items

    def get_recent(self, symbol, limit=20):
        return self._items[:limit]


def _news_item(external_id="n1", title="Şirket rekor kâr açıkladı"):
    now = datetime.now(timezone.utc)
    return NewsRawItem(
        external_id=external_id,
        title=title,
        summary="Detaylı özet burada.",
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
    "reasoning": "Kâr beklentilerin üzerinde geldi.",
}


def test_analyze_item_uses_configured_model_not_hardcoded():
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = EventIntelligenceEngine(
        client=client,
        analysis_repo=_FakeAnalysisRepo(),
        news_repo=_FakeNewsRepo([]),
        primary_model="some-other-model-from-env",
    )

    engine.analyze_item(_news_item(), "THYAO")

    assert client.completions.calls[0]["model"] == "some-other-model-from-env"


def test_analyze_item_returns_validated_news_analysis():
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    repo = _FakeAnalysisRepo()
    engine = EventIntelligenceEngine(
        client=client, analysis_repo=repo, news_repo=_FakeNewsRepo([]), primary_model="gpt-5.6-luna"
    )

    result = engine.analyze_item(_news_item(external_id="n42"), "THYAO")

    assert isinstance(result, NewsAnalysis)
    assert result.news_id == "n42"
    assert result.asset == "THYAO"
    assert result.sentiment_score == 62.5
    assert result.model_used == "gpt-5.6-luna"
    assert repo.added == [result]


def test_analyze_item_requests_structured_json_schema():
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = EventIntelligenceEngine(
        client=client, analysis_repo=_FakeAnalysisRepo(), news_repo=_FakeNewsRepo([]), primary_model="m"
    )

    engine.analyze_item(_news_item(), "THYAO")

    response_format = client.completions.calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True


def test_analyze_recent_for_asset_skips_already_analyzed():
    news = _news_item(external_id="already-done")
    existing_analysis = NewsAnalysis(
        news_id="already-done",
        asset="THYAO",
        sentiment_score=10.0,
        confidence=0.9,
        importance=0.2,
        event_type="other",
        reasoning="Önceden analiz edilmiş.",
        model_used="gpt-5.6-luna",
        created_at=datetime.now(timezone.utc),
    )
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = EventIntelligenceEngine(
        client=client,
        analysis_repo=_FakeAnalysisRepo(existing={"already-done": existing_analysis}),
        news_repo=_FakeNewsRepo([news]),
        primary_model="m",
    )

    results = engine.analyze_recent_for_asset("THYAO")

    assert results == [existing_analysis]
    assert client.completions.calls == []  # LLM hiç çağrılmadı — maliyet oluşmadı


def test_analyze_recent_for_asset_analyzes_new_items():
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    repo = _FakeAnalysisRepo()
    engine = EventIntelligenceEngine(
        client=client,
        analysis_repo=repo,
        news_repo=_FakeNewsRepo([_news_item(external_id="new1")]),
        primary_model="m",
    )

    results = engine.analyze_recent_for_asset("THYAO")

    assert len(results) == 1
    assert results[0].news_id == "new1"
    assert len(client.completions.calls) == 1


def test_missing_api_key_raises_value_error(monkeypatch):
    monkeypatch.setattr("app.engines.event_intelligence.engine.OPENAI_API_KEY", None)
    with pytest.raises(ValueError):
        EventIntelligenceEngine()


@pytest.mark.parametrize(
    "confidence,importance,expected",
    [
        (0.9, 0.5, False),  # normal durum — eskale gerekmez
        (LOW_CONFIDENCE_THRESHOLD - 0.01, 0.5, True),  # düşük güven
        (0.9, HIGH_IMPORTANCE_THRESHOLD + 0.01, True),  # çok yüksek önem
    ],
)
def test_should_escalate_thresholds(confidence, importance, expected):
    analysis = NewsAnalysis(
        news_id="n",
        asset="THYAO",
        sentiment_score=0.0,
        confidence=confidence,
        importance=importance,
        event_type="other",
        reasoning="r",
        model_used="gpt-5.6-luna",
        created_at=datetime.now(timezone.utc),
    )
    assert _should_escalate(analysis) is expected

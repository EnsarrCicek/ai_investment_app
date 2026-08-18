"""EventIntelligenceEngine — AŞAMA 16+.

Ham haberleri (NewsRawItem) yapılandırılmış bir duygu/önem analizine
(NewsAnalysis) çevirir. Bu, proje mimarisinde LLM'e bağımlı tek parça —
geri kalan tüm motorlar (technical/macro/decision/risk/backtest) saf
hesaplama kullanıyor.

Model seçimi (kullanıcı kararı): OpenAI'nin GPT-5.6 model ailesi. Maliyet
kontrolü için TÜM haberler önce ucuz/hızlı katman olan Luna
(EVENT_INTELLIGENCE_PRIMARY_MODEL, varsayılan "gpt-5.6-luna") ile işlenir.
Model adı KESİNLİKLE hard-code edilmez — app/core/config.py üzerinden
.env'den okunur.

Fallback mimarisi (bilinçli olarak bu sürümde ÇAĞRILMIYOR): düşük confidence
veya çok yüksek importance durumunda daha güçlü bir modelle (Terra,
EVENT_INTELLIGENCE_FALLBACK_MODEL) ikinci bir analiz yapılabilmesi için
_should_escalate() zaten burada duruyor ve doğru eşiklerle hesaplıyor —
ama gerçek ikinci LLM çağrısı henüz yapılmıyor, bilinçli olarak sonraki
bir aşamaya bırakıldı (bkz. KURULUM_GUNLUGU).

Yapılandırılmış çıktı: OpenAI'nin structured outputs özelliği (JSON Schema,
strict=True) modelin şema dışına çıkmasını API seviyesinde engeller; dönen
JSON ayrıca Pydantic NewsAnalysis modeliyle ikinci kez doğrulanır (savunma
katmanı) — hiçbir zaman serbest metin olarak saklanmaz.
"""

import json
from datetime import datetime, timezone

from openai import OpenAI

from app.core.config import (
    EVENT_INTELLIGENCE_FALLBACK_MODEL,
    EVENT_INTELLIGENCE_PRIMARY_MODEL,
    OPENAI_API_KEY,
)
from app.models.news_analysis import NewsAnalysis
from app.models.news_raw import NewsRawItem
from app.repositories.news_analysis_repository import NewsAnalysisRepository
from app.repositories.news_raw_repository import NewsRawRepository

ENGINE_VERSION = "1.0.0"

LOW_CONFIDENCE_THRESHOLD = 0.4
HIGH_IMPORTANCE_THRESHOLD = 0.8

_SYSTEM_PROMPT = """Sen bir BIST (Borsa İstanbul) finansal haber analistisin. \
Sana bir hisse senediyle ilgili bir haberin başlığı ve özeti verilecek. Bu \
haberin o hisse senedi için piyasa etkisini değerlendir.

Kurallar:
- sentiment_score: -100 (çok olumsuz/satış baskısı yaratır) ile +100 (çok \
olumlu/alım baskısı yaratır) arası, 0 nötr. Aşırı uçlara yalnızca gerçekten \
çığır açan haberlerde git.
- confidence: Bu değerlendirmeye ne kadar güvendiğin (0-1). Haber belirsiz, \
eksik veya spekülatif ise düşük confidence ver.
- importance: Bu haberin piyasa/hisse fiyatı üzerindeki potansiyel etki \
büyüklüğü (0-1). Rutin bir haber düşük, çeyrek sonuçları/düzenleyici karar \
gibi önemli olaylar yüksek olmalı.
- event_type: haberin kategorisi.
- reasoning: 1-2 cümlelik kısa Türkçe gerekçe.

Yalnızca verilen bilgiye dayan; spekülasyon yapma veya haber dışı bilgi \
ekleme."""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment_score": {
            "type": "number",
            "description": "-100 (çok olumsuz) ile +100 (çok olumlu) arası, 0 nötr",
        },
        "confidence": {
            "type": "number",
            "description": "0-1 arası, bu değerlendirmeye duyulan güven",
        },
        "importance": {
            "type": "number",
            "description": "0-1 arası, olayın piyasa etkisi önemi",
        },
        "event_type": {
            "type": "string",
            "enum": ["earnings", "regulatory", "corporate_action", "macro", "market_sentiment", "other"],
        },
        "reasoning": {
            "type": "string",
            "description": "1-2 cümlelik kısa Türkçe gerekçe",
        },
    },
    "required": ["sentiment_score", "confidence", "importance", "event_type", "reasoning"],
    "additionalProperties": False,
}


def _should_escalate(analysis: NewsAnalysis) -> bool:
    """Terra ile ikinci bir analiz gerekip gerekmediğini hesaplar (mimari
    hazır, ama bu sürümde çağrılmıyor — bkz. modül docstring'i).
    """
    return analysis.confidence < LOW_CONFIDENCE_THRESHOLD or analysis.importance > HIGH_IMPORTANCE_THRESHOLD


class EventIntelligenceEngine:
    def __init__(
        self,
        client: OpenAI | None = None,
        analysis_repo: NewsAnalysisRepository | None = None,
        news_repo: NewsRawRepository | None = None,
        primary_model: str | None = None,
    ):
        if client is None and not OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY ayarlanmamış — backend/.env dosyasına ekleyin"
            )
        self._client = client or OpenAI(api_key=OPENAI_API_KEY)
        self._analysis_repo = analysis_repo or NewsAnalysisRepository()
        self._news_repo = news_repo or NewsRawRepository()
        self._primary_model = primary_model or EVENT_INTELLIGENCE_PRIMARY_MODEL

    def analyze_item(self, news: NewsRawItem, asset: str) -> NewsAnalysis:
        """Tek bir haberi Luna ile analiz edip immutable olarak kaydeder."""
        response = self._client.chat.completions.create(
            model=self._primary_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Varlık: {asset}\nBaşlık: {news.title}\nÖzet: {news.summary}",
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "news_analysis", "schema": _RESPONSE_SCHEMA, "strict": True},
            },
        )
        raw = response.choices[0].message.content
        data = json.loads(raw)

        analysis = NewsAnalysis(
            news_id=news.external_id,
            asset=asset,
            model_used=self._primary_model,
            created_at=datetime.now(timezone.utc),
            engine_version=ENGINE_VERSION,
            **data,
        )
        self._analysis_repo.add(analysis)
        return analysis

    def analyze_recent_for_asset(self, asset: str, limit: int = 5) -> list[NewsAnalysis]:
        """Bu varlık için en son haberleri getirir; daha önce analiz edilmemiş
        olanları Luna ile analiz eder (aynı haberi tekrar tekrar analiz edip
        gereksiz LLM maliyeti oluşturmamak için zaten analiz edilmiş olanlar
        atlanır), tüm sonuç kümesini (eski + yeni) döner.
        """
        news_items = self._news_repo.get_recent(asset, limit=limit)
        results: list[NewsAnalysis] = []
        for news in news_items:
            existing = self._analysis_repo.get_by_news_id(news.external_id)
            results.append(existing if existing else self.analyze_item(news, asset))
        return results

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

Maliyet takibi (AŞAMA 39): her gerçek çağrının response.usage'ı (prompt/
completion token sayısı) usage.py'deki fiyat tarifesiyle çarpılıp
TokenUsageLog olarak kaydedilir — bkz. GET /usage.
"""

import json
from datetime import datetime, timezone

from openai import OpenAI

from app.core.config import (
    EVENT_INTELLIGENCE_FALLBACK_MODEL,
    EVENT_INTELLIGENCE_PRIMARY_MODEL,
    OPENAI_API_KEY,
)
from app.engines.event_intelligence.usage import compute_cost_usd
from app.models.news_analysis import NewsAnalysis
from app.models.news_raw import NewsRawItem
from app.models.token_usage import TokenUsageLog
from app.repositories.news_analysis_repository import NewsAnalysisRepository
from app.repositories.news_raw_repository import NewsRawRepository
from app.repositories.token_usage_repository import TokenUsageRepository
from app.services.news.article_fetcher import fetch_article_text
from app.services.news.event_dedup import DedupEntry, cluster_by_event

ENGINE_VERSION = "1.0.0"

LOW_CONFIDENCE_THRESHOLD = 0.4
HIGH_IMPORTANCE_THRESHOLD = 0.8

_SYSTEM_PROMPT = """Sen bir BIST (Borsa İstanbul) finansal haber analistisin. \
Sana bir hisse senediyle ilgili bir haberin başlığı verilecek; çoğu zaman \
ayrıca özet ve/veya makalenin tam metni de verilecek. Bu haberin o hisse \
senedi için piyasa etkisini değerlendir.

Kurallar:
- sentiment_score: -100 (çok olumsuz/satış baskısı yaratır) ile +100 (çok \
olumlu/alım baskısı yaratır) arası, 0 nötr. Aşırı uçlara yalnızca gerçekten \
çığır açan haberlerde git.
- confidence: Bu değerlendirmeye ne kadar güvendiğin (0-1). ÖNEMLİ: yalnızca \
BAŞLIK verilmiş olması TEK BAŞINA düşük confidence gerektirmez — Türkçe finans \
başlıkları genelde tek başına yeterli bilgi taşır (ör. "X hissesi için hedef \
fiyat yükseltildi", "Y şirketi rekor kâr açıkladı"). Bu durumlarda başlıktaki \
gerçek bilgiye dayanarak normal bir confidence ver. confidence'ı yalnızca \
haberin GERÇEKTEN belirsiz, çelişkili veya anlamsız olduğu durumlarda düşür — \
"detay/metin verilmedi" gerekçesiyle otomatik düşürme.
- importance: Bu haberin piyasa/hisse fiyatı üzerindeki potansiyel etki \
büyüklüğü (0-1). Rutin bir haber düşük, çeyrek sonuçları/düzenleyici karar \
gibi önemli olaylar yüksek olmalı.
- event_type: haberin kategorisi.
- time_horizon: Bu haberin fiyat etkisinin ne kadar süreceğine dair tahmin — \
"short_term" (birkaç gün içinde etkisi geçer, ör. günlük piyasa hareketi/\
teknik yorum), "medium_term" (haftalar-aylar süren etki, ör. çeyrek sonuçları, \
sözleşme/ihale kazanımı), "long_term" (yapısal/kalıcı etki, ör. düzenleyici \
karar, uzun vadeli yatırım/ortaklık anlaşması, kapasite artışı).
- reasoning: 1-2 cümlelik kısa Türkçe gerekçe — verilen bilgiye (başlık/özet/\
metin) dayanan somut bir gerekçe olsun, "yeterli bilgi yok" gibi genel \
ifadelerden kaçın; elindeki bilgiyle en iyi değerlendirmeyi yap.

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
        "time_horizon": {
            "type": "string",
            "description": "Fiyat etkisinin süreceği tahmini vade",
            "enum": ["short_term", "medium_term", "long_term"],
        },
        "reasoning": {
            "type": "string",
            "description": "1-2 cümlelik kısa Türkçe gerekçe",
        },
    },
    "required": ["sentiment_score", "confidence", "importance", "event_type", "time_horizon", "reasoning"],
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
        usage_repo: TokenUsageRepository | None = None,
        primary_model: str | None = None,
    ):
        if client is None and not OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY ayarlanmamış — backend/.env dosyasına ekleyin"
            )
        self._client = client or OpenAI(api_key=OPENAI_API_KEY)
        self._analysis_repo = analysis_repo or NewsAnalysisRepository()
        self._news_repo = news_repo or NewsRawRepository()
        self._usage_repo = usage_repo or TokenUsageRepository()
        self._primary_model = primary_model or EVENT_INTELLIGENCE_PRIMARY_MODEL

    def analyze_item(self, news: NewsRawItem, asset: str) -> NewsAnalysis:
        """Tek bir haberi Luna ile analiz edip immutable olarak kaydeder.

        Kullanıcı isteği: "haberin detayı verilmediği için kesin bir yargıya
        varılamıyor" — kök neden, Google News RSS kaynaklı haberlerde `summary`
        alanının hep boş gelmesiydi (RSS <description>'ı yalnızca başlığı HTML
        içinde tekrarlıyor, gerçek içerik değil — bkz. article_fetcher.py
        docstring'i). İki düzeltme birlikte uygulanıyor: (1) mümkünse GERÇEK
        makale gövde metni çekilip prompta eklenir, (2) boş bir "Özet:" satırı
        ARTIK gönderilmiyor — modele "bilgi eksik" sinyali vermek yerine yalnızca
        gerçekten var olan alanlar gönderiliyor.
        """
        article_text = fetch_article_text(news.url)

        content_lines = [f"Varlık: {asset}", f"Başlık: {news.title}"]
        if news.summary:
            content_lines.append(f"Özet: {news.summary}")
        if article_text:
            content_lines.append(f"Makale Metni: {article_text}")

        response = self._client.chat.completions.create(
            model=self._primary_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(content_lines)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "news_analysis", "schema": _RESPONSE_SCHEMA, "strict": True},
            },
        )
        raw = response.choices[0].message.content
        data = json.loads(raw)
        created_at = datetime.now(timezone.utc)

        analysis = NewsAnalysis(
            news_id=news.external_id,
            asset=asset,
            model_used=self._primary_model,
            created_at=created_at,
            engine_version=ENGINE_VERSION,
            **data,
        )
        self._analysis_repo.add(analysis)
        self._log_usage(response, news.external_id, asset, created_at)
        return analysis

    def _log_usage(self, response, news_id: str, asset: str, created_at: datetime) -> None:
        """Gerçek API yanıtındaki token sayılarını maliyete çevirip kaydeder.

        OpenAI'nin billing/usage API'sinden anlık çekmek yerine (kullanıcı
        kararı), her çağrının kendi `response.usage`'ı kaynak olarak kullanılır
        — bu, ek bir ağ çağrısı gerektirmez ve gerçek token sayımına dayanır.
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        cost_usd = compute_cost_usd(self._primary_model, usage.prompt_tokens, usage.completion_tokens)
        self._usage_repo.add(
            TokenUsageLog(
                news_id=news_id,
                asset=asset,
                model_used=self._primary_model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                cost_usd=cost_usd,
                created_at=created_at,
            )
        )

    def analyze_recent_for_asset(self, asset: str, limit: int = 5) -> list[NewsAnalysis]:
        """Bu varlık için en son haberleri getirir; daha önce analiz edilmemiş
        olanları Luna ile analiz eder (aynı haberi tekrar tekrar analiz edip
        gereksiz LLM maliyeti oluşturmamak için zaten analiz edilmiş olanlar
        atlanır), tüm sonuç kümesini (eski + yeni) döner.

        HATA 15B: aynı gerçek-dünya olayını anlatan birden çok ham haber
        (Yahoo/Google/Foreks) varsa (bkz. app/services/news/event_dedup.py),
        LLM'e SADECE kümenin deterministik temsilcisi gönderilir — kümenin
        diğer üyeleri için YENİ bir NewsAnalysis dokümanı YAZILMAZ (maliyeti
        önlemek için), döndürülen listede temsilcinin analizini paylaşırlar.
        Ham `news_raw` kayıtları HİÇBİR ŞEKİLDE silinmez/değiştirilmez —
        yalnızca hangi maddelerin LLM'e gönderileceği kısıtlanır.
        """
        news_items = self._news_repo.get_recent(asset, limit=limit)
        if not news_items:
            return []

        entries = [
            DedupEntry(
                asset=asset,
                event_id=news.external_id,
                title=news.title,
                published_at=news.published_at,
                has_body=bool(news.summary.strip()),
                payload=news,
            )
            for news in news_items
        ]
        clusters = cluster_by_event(entries)

        result_by_news_id: dict[str, NewsAnalysis] = {}
        for cluster in clusters:
            rep_news = cluster.representative.payload
            existing = self._analysis_repo.get_by_news_id(rep_news.external_id, asset)
            rep_result = existing if existing else self.analyze_item(rep_news, asset)
            for entry in cluster.entries:
                member_news = entry.payload
                if member_news.external_id == rep_news.external_id:
                    result_by_news_id[member_news.external_id] = rep_result
                    continue
                # Kümenin diğer üyesi zaten (bu düzeltmeden ÖNCE) ayrıca
                # analiz edilmişse (legacy veri), o kaydı OLDUĞU GİBİ döndür
                # — provenance korunur, LLM tekrar çağrılmaz. Yoksa yeni bir
                # LLM çağrısı/doküman YAPMADAN temsilcinin analizini paylaşır.
                member_existing = self._analysis_repo.get_by_news_id(member_news.external_id, asset)
                result_by_news_id[member_news.external_id] = member_existing or rep_result

        return [result_by_news_id[news.external_id] for news in news_items]

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
TokenUsageLog olarak kaydedilir — bkz. GET /usage. Bütçe kontrolü: her model
çağrısı budget.py'deki merkezi rezervasyon/uzlaştırma kapısından geçer (günlük
job ve manuel analiz dahil) — bkz. o modülün docstring'i.

Reproducibility/provenance (HATA 15D): her yeni NewsAnalysis, LLM'e
GERÇEKTEN gönderilen son metnin (`analyzed_text`) ve onun SHA-256
hash'inin (`analyzed_text_sha256`) yanı sıra `prompt_version`/
`prompt_sha256`/`output_schema_version` ile birlikte kaydedilir — bkz.
NewsAnalysis model docstring'i. Analiz kimliği hâlâ `news_id + asset`
(DEĞİŞMEDİ, bölüm 13): bu ticket kapsamında yeniden analiz/versiyonlama
akışı YOK — mevcut add-only/immutable + `get_by_news_id` skip sözleşmesi
zaten aynı kaydın sessizce üzerine yazılmasını engelliyor, bu yeterli
görülüp gereksiz bir versiyonlama şeması İCAT EDİLMEDİ.
"""

import hashlib
import json
from datetime import datetime, timezone

from openai import OpenAI

from app.core.config import (
    EVENT_INTELLIGENCE_FALLBACK_MODEL,
    EVENT_INTELLIGENCE_PRIMARY_MODEL,
    OPENAI_API_KEY,
)
from app.engines.event_intelligence.budget import MAX_COMPLETION_TOKENS, EventIntelligenceBudget
from app.models.news_analysis import NewsAnalysis
from app.models.news_raw import NewsRawItem
from app.repositories.news_analysis_repository import NewsAnalysisRepository
from app.repositories.news_raw_repository import NewsRawRepository
from app.services.news.article_fetcher import fetch_article_text
from app.services.news.event_dedup import DedupEntry, cluster_by_event

ENGINE_VERSION = "1.0.0"

LOW_CONFIDENCE_THRESHOLD = 0.4
HIGH_IMPORTANCE_THRESHOLD = 0.8

# HATA 15D: reproducibility/provenance sabitleri. Prompt İÇERİĞİ (_SYSTEM_
# PROMPT) veya şema (_RESPONSE_SCHEMA) bu ticket kapsamında DEĞİŞMİYOR —
# yalnızca bunları tanımlayan sürüm etiketleri ekleniyor. Sürüm dosya
# mtime'ından TÜRETİLMİYOR (bölüm 7) — elle bump edilen sabit bir string;
# prompt/şema içeriği gelecekte değişirse bu sabitlerin BUMP EDİLMESİ
# gerekir (kod bunu otomatik ZORLAMAZ, insan disiplinine dayanır — mevcut
# ENGINE_VERSION ile aynı sözleşme).
EVENT_INTELLIGENCE_PROMPT_VERSION = "event_intelligence_v1"
EVENT_INTELLIGENCE_OUTPUT_SCHEMA_VERSION = "event_intelligence_output_v1"

# Chat Completions API'sinin (gerçek OpenAI istemcisi) desteklediği, "en
# deterministik" iki parametre: `temperature=0.0` (örnekleme rastgeleliğini
# minimize eder) ve `seed` (OpenAI'nin KENDİ dokümantasyonu bunu "best-effort"
# olarak tanımlar — `system_fingerprint` değişirse veya backend güncellenirse
# aynı seed'in aynı çıktıyı GARANTİ ETMEDİĞİNİ açıkça belirtir). Bu ticket
# bitwise-deterministik bir İDDİA yapmıyor — yalnızca API'nin gerçekten
# sunduğu en güçlü reproducibility sinyalini kullanıyor ve bunu dürüstçe
# "best-effort" olarak belgeliyor (bölüm 10).
_DETERMINISM_TEMPERATURE = 0.0
_DETERMINISM_SEED = 0

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


def _sha256_hex(text: str) -> str:
    """Deterministik SHA-256 hex digest — canonical UTF-8 bytes üzerinden.
    Python'ın yerleşik `hash()`'i KULLANILMIYOR (bölüm 6): `hash()` süreçler
    arası (PYTHONHASHSEED randomization) VE Python sürümleri arası kararlı
    DEĞİLDİR, provenance için anlamsız olurdu."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_PROMPT_SHA256 = _sha256_hex(_SYSTEM_PROMPT)


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
        budget: EventIntelligenceBudget | None = None,
        primary_model: str | None = None,
    ):
        if client is None and not OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY ayarlanmamış — backend/.env dosyasına ekleyin"
            )
        # SDK'nin otomatik tekrarları kapalı: tek bütçe rezervasyonu altında
        # birden fazla ücretli deneme olmasın; tekrar deneme, uygulama
        # seviyesinde yeni bir rezervasyonla yapılır (bkz. budget.py).
        self._client = client or OpenAI(api_key=OPENAI_API_KEY, max_retries=0)
        self._analysis_repo = analysis_repo or NewsAnalysisRepository()
        self._news_repo = news_repo or NewsRawRepository()
        self._budget = budget or EventIntelligenceBudget.from_firestore()
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
        # HATA 15D: bu, LLM'e GERÇEKTEN gönderilen son metin — canlı sayfa
        # daha sonra değişse bile bu değişken (ve ondan türeyen hash) o ana
        # ait provenance'ı SABİTLER (bölüm 4/5/14/18). Modelin GÖRDÜĞÜ metin
        # hash'lenir, ham sayfa DEĞİL (bölüm 5).
        analyzed_text = "\n".join(content_lines)

        request = {
            "model": self._primary_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": analyzed_text},
            ],
            "temperature": _DETERMINISM_TEMPERATURE,
            "seed": _DETERMINISM_SEED,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "news_analysis", "schema": _RESPONSE_SCHEMA, "strict": True},
            },
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
        }
        # Bütçe: ücretli çağrıdan HEMEN ÖNCE rezervasyon (yetersiz/okunamaz ise
        # çağrı yapılmaz, istisna yükselir); belirsiz sonuçta rezervasyon tutulur.
        reservation = self._budget.reserve(
            model=self._primary_model, request=request, news_id=news.external_id, asset=asset
        )
        try:
            response = self._client.chat.completions.create(**request)
        except Exception:
            self._budget.mark_uncertain(reservation)
            raise
        # Gerçek kullanım, yanıt ayrıştırılmadan ÖNCE uzlaştırılır — geçersiz
        # çıktı da ücretlidir.
        self._budget.settle(
            reservation,
            usage=getattr(response, "usage", None),
            news_id=news.external_id,
            asset=asset,
            created_at=datetime.now(timezone.utc),
        )
        raw = response.choices[0].message.content
        data = json.loads(raw)
        created_at = datetime.now(timezone.utc)

        # HATA 15D bölüm 24-25: `NewsAnalysis(...)` construction'ı (Pydantic
        # doğrulaması dahil) `self._analysis_repo.add(...)`'DAN ÖNCE olur —
        # `json.loads` (malformed JSON) veya Pydantic (şema-geçersiz `data`)
        # burada fırlatırsa, hiçbir NewsAnalysis ASLA persist edilmez (ne
        # tam ne kısmi/fake bir kayıt) — repository'ye hiç ulaşılmaz. Bu,
        # kod DEĞİŞİKLİĞİ gerektirmeyen, zaten var olan doğru bir sıralama;
        # test_invalid_llm_output_does_not_persist_analysis bunu kilitliyor.
        analysis = NewsAnalysis(
            news_id=news.external_id,
            asset=asset,
            model_used=self._primary_model,
            created_at=created_at,
            engine_version=ENGINE_VERSION,
            analyzed_text=analyzed_text,
            analyzed_text_sha256=_sha256_hex(analyzed_text),
            prompt_version=EVENT_INTELLIGENCE_PROMPT_VERSION,
            prompt_sha256=_PROMPT_SHA256,
            output_schema_version=EVENT_INTELLIGENCE_OUTPUT_SCHEMA_VERSION,
            **data,
        )
        self._analysis_repo.add(analysis)
        return analysis

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

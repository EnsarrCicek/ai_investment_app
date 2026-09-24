"""EventIntelligence OpenAI bütçe kontrolü — TEK merkezi kapı.

Kapsam (bilinçli olarak DEĞİŞTİRİLMEDİ): `EVENT_INTELLIGENCE_BUDGET_USD`, tüm
zamanlar boyunca EventIntelligenceEngine'in OpenAI çağrılarının TOPLAM tahmini
maliyet sınırıdır — günlük/aylık sıfırlama yok. Kodda başka OpenAI çağrısı
yoktur; Terra fallback çağrılmaz.

Her gerçek model çağrısından HEMEN ÖNCE (`EventIntelligenceEngine.analyze_item`)
ihtiyatlı bir maliyet rezerve edilir, çağrıdan sonra gerçek `response.usage`
ile uzlaştırılır. Hem günlük job hem `POST /news/{symbol}/analyze` bu kapıdan
geçer; route girişinde ayrı bir kontrol yoktur.

Rezervasyon = ihtiyatlı YEREL tahmin (doğrulanmış bir sağlayıcı üst sınırı DEĞİL):
  * girdi: gönderilen isteğin (mesajlar + yanıt şeması) UTF-8 bayt sayısı +
    256 sabit pay — bayt düzeyinde tokenizasyon VARSAYIMINA dayanır; sağlayıcının
    şemayı/şablonu nasıl token'laştırdığı doğrulanmadı;
  * çıktı: istekte gönderilen `MAX_COMPLETION_TOKENS` (sağlayıcının bu sınırı
    muhakeme token'ları dahil uyguladığı varsayılır);
  * fiyat: yerel `usage.MODEL_PRICING_PER_1M` tablosu; tablo dışı model için
    çağrı yapılmaz (sıfır/varsayılan fiyat VARSAYILMAZ).
  Kapsamadıkları: fiyat tablosunun güncelliği, sağlayıcının farklı token
  sayımı, önbellek/diğer ücret kalemleri. Gerçek kullanım tahmini aşarsa
  gerçek tutar KIRPILMADAN deftere yazılır; bütçe bu kadar aşılabilir, sonraki
  çağrılar kalan bütçeye göre engellenir. SDK'nin otomatik tekrarları kapalıdır
  (engine.py) — tek rezervasyon = tek HTTP denemesi.

Güvencenin sınırı: yalnızca bu ortak defteri kullanan çağrılar birbirine karşı
korunur; defterin dışında kalan (ör. eski revision'dan gelen) çağrılar ve yerel
fiyat/token tahmininin hataları kapsanmaz. Defter ilk kullanımda mevcut
`token_usage_logs` toplamıyla BİR KEZ tohumlanır; sonradan defter dışından
yazılan kayıtlar sayılmaz.

Eşzamanlılık: defter (committed + reserved) Firestore transaction'ı içinde
okunup güncellenir; aynı kalan bütçeyi iki istek ayrı ayrı harcayamaz
(process içi kilit değil, instance'lar arası ortak kalıcı durum).

Belirsiz çağrı (timeout, bağlantı hatası, istisna, `usage` yok): sağlayıcı
ücret üretmiş olabilir — rezervasyon SERBEST BIRAKILMAZ, UNCERTAIN olarak tahmini
üst sınırıyla tutulmaya devam eder. Süreç rezervasyondan sonra çökerse kayıt
RESERVED kalır ve yine tutulur. İkisi de otomatik geri alınmaz (bilinçli olarak
fazla sayma yönünde tercih). Tekrar deneme YENİ bir rezervasyon açar; eski
rezervasyon yeniden kullanılamaz. Uzlaştırma kimliği rezervasyon kimliğidir:
aynı rezervasyon iki kez uzlaştırılamaz, kullanım kaydı iki kez yazılamaz.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.engines.event_intelligence.usage import MODEL_PRICING_PER_1M
from app.models.token_usage import TokenUsageLog

logger = logging.getLogger(__name__)

# Zorunlu çıktı sınırı: rezervasyonun üst sınırı buna dayanır. Beklenen yapısal
# JSON çıktısının çok üzerinde; aşılırsa yanıt kesilir, geçersiz JSON olarak
# reddedilir ve hiçbir analiz kaydedilmez (kullanım yine uzlaştırılır).
MAX_COMPLETION_TOKENS = 4096
# Sohbet şablonunun metin dışı özel token'ları için sabit pay.
_REQUEST_TOKEN_MARGIN = 256


class EventIntelligenceBudgetError(Exception):
    """Ücretli çağrı başlatılmadı."""


class BudgetExhaustedError(EventIntelligenceBudgetError):
    """Kalan bütçe bu çağrının ihtiyatlı tahminini karşılamıyor."""


class BudgetUnavailableError(EventIntelligenceBudgetError):
    """Bütçe/rezervasyon durumu okunamadı-yazılamadı veya model fiyatı bilinmiyor."""


def pricing_for(model: str, table=MODEL_PRICING_PER_1M) -> dict:
    pricing = table.get(model)
    if pricing is None:
        raise BudgetUnavailableError(f"'{model}' için fiyat tanımlı değil — ücretli çağrı yapılmaz")
    return pricing


def strict_cost_usd(model: str, prompt_tokens: int, completion_tokens: int, table=MODEL_PRICING_PER_1M) -> float:
    pricing = pricing_for(model, table)
    return (prompt_tokens / 1_000_000) * pricing["input"] + (completion_tokens / 1_000_000) * pricing["output"]


def estimate_max_cost_usd(model: str, request: dict, table=MODEL_PRICING_PER_1M) -> float:
    payload = json.dumps(
        {"messages": request["messages"], "response_format": request.get("response_format")}, ensure_ascii=False
    )
    max_input_tokens = len(payload.encode("utf-8")) + _REQUEST_TOKEN_MARGIN
    cost = strict_cost_usd(model, max_input_tokens, request["max_completion_tokens"], table)
    return math.ceil(cost * 1_000_000) / 1_000_000


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    model: str
    amount_usd: float


class EventIntelligenceBudget:
    def __init__(self, store, budget_usd: float, pricing=MODEL_PRICING_PER_1M):
        self._store = store
        self._budget_usd = budget_usd
        self._pricing = pricing

    @classmethod
    def from_firestore(cls) -> EventIntelligenceBudget:
        from app.core.config import EVENT_INTELLIGENCE_BUDGET_USD
        from app.repositories.event_intelligence_budget_repository import FirestoreBudgetLedgerRepository

        return cls(FirestoreBudgetLedgerRepository(), EVENT_INTELLIGENCE_BUDGET_USD)

    def reserve(self, *, model: str, request: dict, news_id: str, asset: str) -> Reservation:
        amount = estimate_max_cost_usd(model, request, self._pricing)
        reservation = Reservation(reservation_id=uuid.uuid4().hex, model=model, amount_usd=amount)
        try:
            accepted = self._store.reserve(
                reservation_id=reservation.reservation_id,
                amount_usd=amount,
                budget_usd=self._budget_usd,
                model=model,
                news_id=news_id,
                asset=asset,
            )
        except Exception as exc:  # noqa: BLE001 — durum okunamıyorsa ücretli çağrı yok
            raise BudgetUnavailableError(f"bütçe durumu okunamadı ({type(exc).__name__})") from exc
        if not accepted:
            raise BudgetExhaustedError(
                f"EventIntelligence bütçesi yetersiz (sınır {self._budget_usd} USD, tüm zamanlar toplamı)"
            )
        return reservation

    def settle(self, reservation: Reservation, *, usage, news_id: str, asset: str, created_at: datetime) -> None:
        if usage is None:
            self.mark_uncertain(reservation)
            return
        log = TokenUsageLog(
            news_id=news_id,
            asset=asset,
            model_used=reservation.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=round(
                strict_cost_usd(reservation.model, usage.prompt_tokens, usage.completion_tokens, self._pricing), 6
            ),
            created_at=created_at,
        )
        try:
            self._store.settle(reservation.reservation_id, log)
        except Exception as exc:  # noqa: BLE001 — rezervasyon tutulmaya devam eder
            raise BudgetUnavailableError(f"kullanım uzlaştırılamadı ({type(exc).__name__})") from exc

    def mark_uncertain(self, reservation: Reservation) -> None:
        """Başarısız olursa kayıt RESERVED kalır — o da aynı tutarla tutulur."""
        try:
            self._store.mark_uncertain(reservation.reservation_id)
        except Exception as exc:  # noqa: BLE001 — asıl hatayı maskelememek için
            logger.warning("budget reservation could not be marked uncertain: %s", type(exc).__name__)

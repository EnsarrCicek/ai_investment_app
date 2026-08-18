"""EventIntelligenceEngine maliyet takibi.

Gerçek OpenAI kullanım/billing API'sinden anlık çekmiyoruz (kullanıcı kararı:
"direkt api üzerinden çekmemize gerek yok") — bunun yerine her gerçek
analyze_item() çağrısında dönen response.usage (prompt/completion/total
tokens) OpenAI'nin yayınladığı GPT-5.6 fiyat tarifesiyle çarpılıp
TokenUsageLog olarak Firestore'a kaydediliyor; bu modül o kayıtları
özetliyor. Fiyatlar model adına göre bir tablodan okunuyor — bilinmeyen bir
model adı gelirse (örn. .env'de değiştirilmiş) Luna fiyatı varsayılan olarak
kullanılır (en düşük maliyetli katman — tahmini maliyeti olduğundan düşük
göstermek, olduğundan yüksek göstermekten daha güvenli bir varsayım).
"""

from collections import defaultdict
from datetime import date, datetime, timezone

from app.models.token_usage import TokenUsageLog

# USD / 1M token (OpenAI GPT-5.6 fiyat tarifesi, 09.07.2026 itibarıyla)
MODEL_PRICING_PER_1M = {
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
    "gpt-5.6-terra": {"input": 2.50, "output": 15.00},
    "gpt-5.6-sol": {"input": 5.00, "output": 20.00},
}

_DEFAULT_PRICING = MODEL_PRICING_PER_1M["gpt-5.6-luna"]


def compute_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = MODEL_PRICING_PER_1M.get(model, _DEFAULT_PRICING)
    cost = (prompt_tokens / 1_000_000) * pricing["input"] + (completion_tokens / 1_000_000) * pricing["output"]
    return round(cost, 6)


def summarize(logs: list[TokenUsageLog], budget_usd: float, today: date | None = None) -> dict:
    """Toplam/bugünkü harcama ve kalan bakiyeyi özetler.

    `today` test edilebilirlik için enjekte edilebilir; verilmezse gerçek
    UTC tarihi kullanılır.
    """
    today = today or datetime.now(timezone.utc).date()

    spent_total_usd = round(sum(log.cost_usd for log in logs), 4)
    today_logs = [log for log in logs if log.created_at.date() == today]
    spent_today_usd = round(sum(log.cost_usd for log in today_logs), 4)

    daily_totals: dict[date, float] = defaultdict(float)
    for log in logs:
        daily_totals[log.created_at.date()] += log.cost_usd
    daily_breakdown = [
        {"date": d.isoformat(), "spent_usd": round(v, 4)}
        for d, v in sorted(daily_totals.items(), reverse=True)[:7]
    ]

    return {
        "budget_usd": round(budget_usd, 4),
        "spent_total_usd": spent_total_usd,
        "remaining_usd": round(budget_usd - spent_total_usd, 4),
        "spent_today_usd": spent_today_usd,
        "calls_today": len(today_logs),
        "calls_total": len(logs),
        "tokens_today": sum(log.total_tokens for log in today_logs),
        "tokens_total": sum(log.total_tokens for log in logs),
        "daily_breakdown": daily_breakdown,
    }
